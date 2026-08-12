from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from trainlab.mail_agent.locks import MailLockBusyError, MailWriteLock


def make(tmp_path: Path) -> Path:
    state = tmp_path / "state"; locks = state / "locks"; state.mkdir(mode=0o700); locks.mkdir(mode=0o700)
    return locks / "mail.lock"


def test_release_replacement_preserved(tmp_path: Path) -> None:
    path = make(tmp_path); lock = MailWriteLock(path, "mail:1:poll:a"); lock.acquire()
    path.unlink(); path.write_text("third-party"); os.chmod(path, 0o600)
    with pytest.raises(MailLockBusyError): lock.release()
    assert path.exists()


def test_invalid_and_live_records_are_busy(tmp_path: Path) -> None:
    path = make(tmp_path); path.write_text("{"); os.chmod(path, 0o600)
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:a").acquire()


def test_state_symlink_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"; outside.mkdir(); (tmp_path / "state").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MailLockBusyError): MailWriteLock(tmp_path / "state" / "locks" / "mail.lock", "mail:1:poll:a").acquire()


def test_claim_blocker_prevents_new_acquire(tmp_path: Path) -> None:
    path = make(tmp_path); blocker = path.parent / ".mail.lock.claim-dead"
    blocker.write_text("evidence"); os.chmod(blocker, 0o600)
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:a").acquire()
    assert not path.exists() and blocker.exists()


def test_stale_claim_in_place_mutation_is_preserved_and_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make(tmp_path); raw = json.dumps({"pid": 99999999, "run_key": "dead", "started_at_utc": "2026-07-23T00:00:00Z", "uid": os.getuid()}, sort_keys=True, separators=(",", ":"))
    path.write_text(raw); os.chmod(path, 0o600); original = os.rename; mutated = False
    def guarded(src, dst, *args, **kwargs):
        nonlocal mutated
        result = original(src, dst, *args, **kwargs)
        if not mutated:
            mutated = True; fd = os.open(dst, os.O_WRONLY | os.O_TRUNC, dir_fd=kwargs["dst_dir_fd"]); os.write(fd, b"unknown"); os.close(fd)
        return result
    monkeypatch.setattr(os, "rename", guarded)
    lock = MailWriteLock(path, "mail:1:poll:a", process_is_alive=lambda _pid: False)
    with pytest.raises(MailLockBusyError): lock.acquire()
    assert any(item.name.startswith(".mail.lock.tombstone-") for item in path.parent.iterdir())
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:b").acquire()


def test_zero_write_cleans_own_incomplete_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make(tmp_path); monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:a").acquire()
    assert not path.exists() and not list(path.parent.glob("*.tombstone-*"))


def test_claim_scan_error_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make(tmp_path); monkeypatch.setattr(os, "listdir", lambda _fd: (_ for _ in ()).throw(OSError("scan")))
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:a").acquire()


def test_create_in_place_mutation_is_preserved_as_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make(tmp_path); original = os.write; calls = 0
    def guarded(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1: return original(fd, data[:5])
        os.ftruncate(fd, 0); original(fd, b"unknown-external-content"); raise OSError("external")
    monkeypatch.setattr(os, "write", guarded)
    with pytest.raises(MailLockBusyError, match="mail_lock_io_failed"):
        MailWriteLock(path, "mail:1:poll:a").acquire()
    assert path.exists() and any(item.name.startswith(".mail.lock.tombstone-") for item in path.parent.iterdir())
    with pytest.raises(MailLockBusyError): MailWriteLock(path, "mail:1:poll:b").acquire()


def test_verified_claim_cleanup_is_bounded_and_reacquires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make(tmp_path)
    calls: list[str] = []
    original_unlink = os.unlink

    def guarded(name, *args, **kwargs):
        text = os.fspath(name)
        calls.append(text)
        assert isinstance(text, str) and text.startswith(".mail.lock.tombstone-")
        return original_unlink(name, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", guarded)
    before = len(os.listdir("/dev/fd"))
    for index in range(1000):
        lock = MailWriteLock(path, f"mail:1:poll:{index}")
        lock.acquire()
        lock.release()
        assert not path.exists()
    assert len(calls) == 1000
    assert not list(path.parent.iterdir())
    assert len(os.listdir("/dev/fd")) <= before + 1
    monkeypatch.setattr(os, "unlink", original_unlink)


def test_verified_dead_stale_recovery_is_bounded_for_long_running_polling(tmp_path: Path) -> None:
    path = make(tmp_path)
    before = len(os.listdir("/dev/fd"))
    for index in range(1000):
        path.write_text(json.dumps({
            "pid": 99999999, "run_key": f"dead-{index}", "uid": os.getuid(),
            "started_at_utc": "2026-07-23T00:00:00Z",
        }, sort_keys=True, separators=(",", ":")))
        os.chmod(path, 0o600)
        replacement = MailWriteLock(path, f"mail:1:poll:stale-{index}", process_is_alive=lambda _pid: False)
        replacement.acquire()
        replacement.release()
        assert not path.exists()
    assert not list(path.parent.iterdir())
    assert len(os.listdir("/dev/fd")) <= before + 1


@pytest.mark.parametrize("operation", ("release", "stale"))
@pytest.mark.parametrize("fault", ("unlink", "post_fsync"))
def test_finalizer_failure_retains_claim_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, fault: str
) -> None:
    path = make(tmp_path)
    fired = False
    if operation == "release":
        owner = MailWriteLock(path, "mail:1:poll:owner")
        owner.acquire()
        assert owner._parent_fd is not None
        held_locks_fd = owner._parent_fd
    else:
        path.write_text(json.dumps({
            "pid": 99999999, "run_key": "dead", "uid": os.getuid(),
            "started_at_utc": "2026-07-23T00:00:00Z",
        }, sort_keys=True, separators=(",", ":")))
        os.chmod(path, 0o600)
        owner = MailWriteLock(path, "mail:1:poll:replacement", process_is_alive=lambda _pid: False)
        held_locks_fd = None
    original_unlink, original_fsync = os.unlink, os.fsync
    locks_fd: dict[str, int] = {}
    original_open = os.open

    def open_hook(name, flags, *args, **kwargs):
        fd = original_open(name, flags, *args, **kwargs)
        if os.fspath(name) == "locks":
            locks_fd["fd"] = fd
        return fd

    def unlink_hook(name, *args, **kwargs):
        nonlocal fired
        if fault == "unlink" and str(os.fspath(name)).startswith(".mail.lock.tombstone-"):
            fired = True
            raise OSError("finalizer-unlink")
        return original_unlink(name, *args, **kwargs)

    def fsync_hook(fd):
        nonlocal fired
        if fault == "post_fsync" and fd == (held_locks_fd if held_locks_fd is not None else locks_fd.get("fd")):
            fired = True
            raise OSError("finalizer-fsync")
        return original_fsync(fd)

    monkeypatch.setattr(os, "open", open_hook)
    monkeypatch.setattr(os, "unlink", unlink_hook)
    monkeypatch.setattr(os, "fsync", fsync_hook)
    with pytest.raises(MailLockBusyError):
        owner.release() if operation == "release" else owner.acquire()
    assert fired
    claims = list(path.parent.glob(".mail.lock.tombstone-*"))
    blockers = list(path.parent.glob(".mail.lock.blocker-*"))
    if fault == "unlink":
        assert claims and claims[0].is_file() and not blockers
        evidence = claims[0]
    else:
        assert not claims and blockers and blockers[0].is_file()
        evidence = blockers[0]
    before = len(os.listdir("/dev/fd"))
    monkeypatch.undo()
    with pytest.raises(MailLockBusyError):
        MailWriteLock(path, "mail:1:poll:retry").acquire()
    assert evidence.exists()
    assert len(os.listdir("/dev/fd")) <= before + 1
