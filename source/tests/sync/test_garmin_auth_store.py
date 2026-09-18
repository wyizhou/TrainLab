from __future__ import annotations

import json
import multiprocessing
import os
import signal
from pathlib import Path
from typing import Any

import pytest

from tests.sync.auth_support import PASSWORD, SECRET, OfflineGarmin
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth_sdk import GarminSDK
from trainlab.garmin_auth_store import GarminAuthStore
from trainlab.garmin_auth_types import GarminAuthError


def authenticated(offline: OfflineGarmin) -> GarminSDK:
    sdk = GarminSDK(is_cn=False)
    assert sdk.begin("synthetic@example.invalid", PASSWORD)
    return sdk


def test_commit_roundtrip_permissions_backup_and_restart(tmp_path: Path, offline: OfflineGarmin) -> None:
    config = tmp_path / GARMIN_CONFIG_PATH
    config.parent.mkdir(parents=True)
    original = b'{"di_token":"synthetic-old"}\n'
    config.write_bytes(original)
    store = GarminAuthStore(tmp_path)
    sdk = authenticated(offline)
    with store.locked():
        old = store.snapshot()
        revision = store.commit(sdk, old.revision, GarminSDK)
        assert revision != old.revision
    fresh = GarminAuthStore(tmp_path)
    with fresh.locked():
        loaded = fresh.load(fresh.snapshot(), GarminSDK)
        assert loaded.fingerprint() == sdk.fingerprint()
        loaded.close()
    backups = list(config.parent.glob("garmin-backup-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    for path in config.parent.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    assert SECRET not in config.read_text()
    sdk.close()


@pytest.mark.parametrize("stage", ["dump", "roundtrip", "backup", "pointer_write", "replace", "fsync", "post_replace_fsync", "second_token"])
def test_commit_failure_keeps_old_pair_and_pointer(
    tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    sdk = authenticated(offline)
    store = GarminAuthStore(tmp_path)
    config = tmp_path / GARMIN_CONFIG_PATH
    with store.locked():
        store.commit(sdk, "missing", GarminSDK)
    before = config.read_bytes()
    files = {p: p.read_bytes() for p in config.parent.rglob("*.json")}

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("synthetic storage failure")

    if stage == "dump":
        monkeypatch.setattr(sdk, "dump", fail)
    elif stage == "roundtrip":
        monkeypatch.setattr(GarminSDK, "load", fail)
    elif stage in {"backup", "pointer_write"}:
        if stage == "backup":
            config.write_text('{"di_token":"synthetic-old"}')
            before = config.read_bytes()
            files[config] = before
        original_write = store._write_new

        def write(path: Path, content: bytes) -> None:
            if (stage == "backup" and path.name.startswith("garmin-backup")) or (stage == "pointer_write" and path.suffix == ".tmp"):
                fail()
            original_write(path, content)

        monkeypatch.setattr(store, "_write_new", write)
    elif stage == "replace":
        monkeypatch.setattr(os, "replace", fail)
    elif stage == "post_replace_fsync":
        original_fsync = store._fsync

        def fsync(path: Path) -> None:
            if path == config.parent and config.read_bytes() != before:
                fail()
            original_fsync(path)

        monkeypatch.setattr(store, "_fsync", fsync)
    elif stage == "second_token":
        original_new = store._write_new

        def second(path: Path, content: bytes) -> None:
            if path.name == "oauth2_token.json":
                fail()
            original_new(path, content)

        monkeypatch.setattr(store, "_write_new", second)
    else:
        monkeypatch.setattr(store, "_fsync", fail)
    with pytest.raises(GarminAuthError), store.locked():
        store.commit(sdk, store.snapshot().revision, GarminSDK)
    assert config.read_bytes() == before
    assert all(path.read_bytes() == raw for path, raw in files.items())
    sdk.close()


@pytest.mark.parametrize("component", ["states", "states/verification", "states/verification/garmin.json", "states/verification/.garmin-auth.lock"])
def test_symlink_boundaries(tmp_path: Path, component: str) -> None:
    root = tmp_path / "instance"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    path = root / component
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    store = GarminAuthStore(root)
    with pytest.raises(GarminAuthError), store.locked():
        store.snapshot()
    assert list(target.iterdir()) == []


def hold_lock(root: str, connection: Any) -> None:
    import socket

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Child process network blocked")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.socket.connect_ex = denied  # type: ignore[method-assign]
    with GarminAuthStore(Path(root)).locked():
        connection.send(True)
        connection.recv()


def test_cross_process_busy_crash_recovery(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=hold_lock, args=(str(tmp_path), child))
    process.start()
    assert parent.poll(10) and parent.recv()
    with pytest.raises(GarminAuthError) as error, GarminAuthStore(tmp_path).locked():
        pytest.fail("lock acquired twice")
    assert error.value.code == ErrorCode.RUN_BUSY
    os.kill(process.pid, signal.SIGKILL)  # type: ignore[arg-type]
    process.join(10)
    with GarminAuthStore(tmp_path).locked():
        pass
    parent.close()
    child.close()


def test_generation_conflict_no_overwrite(tmp_path: Path, offline: OfflineGarmin) -> None:
    sdk = authenticated(offline)
    store = GarminAuthStore(tmp_path)
    with store.locked():
        store.commit(sdk, "missing", GarminSDK)
        before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
        with pytest.raises(GarminAuthError) as error:
            store.commit(sdk, "missing", GarminSDK)
        assert error.value.code == ErrorCode.SOURCE_CONFLICT
        assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert json.loads(before)["version"] == 1
    sdk.close()
