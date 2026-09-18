from __future__ import annotations

import importlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.sync.auth_support import PASSWORD, SECRET, OfflineGarmin, legacy_tokens
from tests.sync.test_garmin_auth import data
from tests.sync.test_garmin_sync import write_auth
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_sdk import GarminSDK
from trainlab.garmin_auth_store import GarminAuthStore
from trainlab.garmin_sync import run_real_garmin_sync


@pytest.mark.parametrize("kind", ["outside", "symlink-directory", "symlink-token", "hardlink", "escape"])
def test_legacy_paths_cannot_escape_or_follow_links(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "instance"
    root.mkdir()
    external = legacy_tokens(tmp_path / "outside")
    inside = root / "tokens"
    if kind == "outside":
        value = str(external)
    elif kind == "escape":
        value = "../outside/old-tokens"
    elif kind == "symlink-directory":
        inside.symlink_to(external)
        value = "tokens"
    else:
        inside.mkdir()
        for filename in ("oauth1_token.json", "oauth2_token.json"):
            if kind == "symlink-token":
                (inside / filename).symlink_to(external / filename)
            else:
                (inside / filename).hardlink_to(external / filename)
        value = "tokens"
    write_auth(root, {"tokenstore": value})
    result = GarminAuthService(root).status()
    assert result.error is not None and result.error.code == ErrorCode.CONFIG_UNAVAILABLE
    assert SECRET not in json.dumps(result.to_json())


@pytest.mark.parametrize("field", ["expires_in", "expires_at"])
def test_missing_expiry_never_fabricated(tmp_path: Path, field: str) -> None:
    directory = legacy_tokens(tmp_path)
    path = directory / "oauth2_token.json"
    token = json.loads(path.read_text())
    del token[field]
    path.write_text(json.dumps(token))
    write_auth(tmp_path, {"tokenstore": directory.name})
    result = GarminAuthService(tmp_path).status()
    assert result.error is not None and result.error.code == ErrorCode.DATA_INVALID
    assert "expires_at_utc" not in json.dumps(result.to_json())


def test_malformed_sdk_return_and_submit_after_restart(tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch) -> None:
    import garminconnect
    monkeypatch.setattr(garminconnect.Garmin, "login", lambda self: {"needs_mfa": True, "token": SECRET})
    result = GarminAuthService(tmp_path).begin_login("synthetic@example.invalid", PASSWORD, is_cn=False)
    assert result.error is not None and result.error.code == ErrorCode.DATA_INVALID
    assert not (tmp_path / GARMIN_CONFIG_PATH).exists()
    assert SECRET not in json.dumps(result.to_json())


def test_sdk_dependency_unavailable_is_controlled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> Any:
        raise ImportError(SECRET)

    monkeypatch.setattr(importlib, "import_module", missing)
    result = GarminAuthService(tmp_path).begin_login("synthetic@example.invalid", PASSWORD, is_cn=False)
    assert result.error is not None and result.error.code == ErrorCode.CONFIG_UNAVAILABLE
    assert SECRET not in json.dumps(result.to_json())


def test_refresh_commit_failure_preserves_old_pair(tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = legacy_tokens(tmp_path, expires_at=int(time.time()) - 60)
    write_auth(tmp_path, {"tokenstore": directory.name})
    service = GarminAuthService(tmp_path)
    with service._store.locked():
        snapshot = service._store.snapshot()
        sdk = service._store.load(snapshot, GarminSDK)
        service._store.commit(sdk, snapshot.revision, GarminSDK)
        sdk.close()
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    original = GarminAuthStore._write_new

    def fail(path: Path, content: bytes) -> None:
        if path.suffix == ".tmp":
            raise OSError("synthetic failure")
        original(path, content)

    monkeypatch.setattr(GarminAuthStore, "_write_new", staticmethod(fail))
    result = run_real_garmin_sync(tmp_path, now_utc=datetime.now(UTC))
    assert not result.ok
    assert offline.exchange_count == 1
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert not (tmp_path / "states/data.db").exists()


def test_new_process_flow_is_unknown_and_old_wait_does_not_hold_lock(tmp_path: Path, offline: OfflineGarmin) -> None:
    offline.mfa = True
    first = GarminAuthService(tmp_path)
    flow = data(first.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    second = GarminAuthService(tmp_path)
    assert not second.submit_mfa(flow["flow_id"], "123456").ok
    with second._store.locked():
        assert second._store.snapshot().revision == "missing"
    first.close()


def test_auth_lock_busy_prevents_sync_without_data_requests(tmp_path: Path, offline: OfflineGarmin) -> None:
    service = GarminAuthService(tmp_path)
    data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    count = len(offline.calls)
    with GarminAuthStore(tmp_path).locked():
        result = run_real_garmin_sync(tmp_path, now_utc=datetime.now(UTC))
    assert result.code == ErrorCode.RUN_BUSY and len(offline.calls) == count
