from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


UTC = "2026-07-24T00:00:00Z"


def _tool(root: Path) -> FoundationTool:
    return FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock"))


def test_lock_invalid_records_are_busy_without_fd_growth(tmp_path: Path) -> None:
    root=tmp_path/"f"; tool=_tool(root); lock=root/"state/locks/foundation.lock"; lock.parent.mkdir(parents=True); [p.chmod(0o700) for p in (root,root/"state",lock.parent)]
    baseline=len(list(Path("/dev/fd").iterdir()))
    for raw in (b"{", b"x"*513):
        lock.write_bytes(raw); lock.chmod(0o600)
        for _ in range(20): assert tool.execute(FoundationRequest("init","lock-security",UTC)).status=="lock_busy"
    assert len(list(Path("/dev/fd").iterdir())) <= baseline + 2


def test_stale_lock_recovers_and_writes_safe_audit(tmp_path: Path) -> None:
    root=tmp_path/"f"; tool=_tool(root); lock=root/"state/locks/foundation.lock"; lock.parent.mkdir(parents=True); [p.chmod(0o700) for p in (root,root/"state",lock.parent)]
    lock.write_text(json.dumps({"pid":99999999,"uid":os.getuid(),"started_at_utc":UTC})); lock.chmod(0o600)
    assert tool.execute(FoundationRequest("init","stale-lock",UTC)).status=="initialized"
    audit=root/"state/foundation-lock-recoveries.jsonl"
    assert audit.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["zero", "partial", "raise", "fsync"])
def test_lock_create_failures_leave_no_lock_and_next_init_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    root=tmp_path/"f"; tool=_tool(root); original_write=os.write; original_fsync=os.fsync; calls=0
    def broken_write(fd:int,data:bytes)->int:
        nonlocal calls
        calls += 1
        if failure=="raise": raise OSError("write")
        if failure=="zero" or (failure=="partial" and calls>1): return 0
        return original_write(fd,data[:1]) if failure=="partial" else original_write(fd,data)
    def broken_fsync(fd:int)->None:
        if failure=="fsync": raise OSError("fsync")
        original_fsync(fd)
    monkeypatch.setattr(os,"write",broken_write); monkeypatch.setattr(os,"fsync",broken_fsync)
    assert tool.execute(FoundationRequest("init","create-fail",UTC)).status in {"lock_busy","failed"}
    lock=root/"state/locks/foundation.lock"
    assert not lock.exists()
    monkeypatch.setattr(os,"write",original_write); monkeypatch.setattr(os,"fsync",original_fsync)
    assert tool.execute(FoundationRequest("init","create-ok",UTC)).status=="initialized"


def test_created_claim_replacement_is_restored_as_persistent_busy(tmp_path: Path) -> None:
    root=tmp_path/"f"; tool=_tool(root); lock=root/"state/locks/foundation.lock"; lock.parent.mkdir(parents=True); [p.chmod(0o700) for p in (root,root/"state",lock.parent)]
    lock.write_text(json.dumps({"pid":99999999,"uid":os.getuid(),"started_at_utc":UTC})); lock.chmod(0o600)
    parent_fd=tool._open_checked_directory(lock.parent)
    try:
        old=os.stat(lock,follow_symlinks=False); replacement=lock.parent/"replacement"; replacement.write_text(json.dumps({"pid":os.getpid(),"uid":os.getuid(),"started_at_utc":UTC})); replacement.chmod(0o600)
        os.replace(replacement,lock)
        with pytest.raises(BlockingIOError): tool._claim_created_inode_at(parent_fd,lock.name,(old.st_dev,old.st_ino))
        assert lock.exists()
        assert tool.execute(FoundationRequest("init","replacement-busy",UTC)).status=="lock_busy"
    finally: os.close(parent_fd)


def test_failed_claim_restore_quarantine_blocks_later_acquire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root=tmp_path/"f"; tool=_tool(root); lock=root/"state/locks/foundation.lock"; lock.parent.mkdir(parents=True); [p.chmod(0o700) for p in (root,root/"state",lock.parent)]
    lock.write_text(json.dumps({"pid":99999999,"uid":os.getuid(),"started_at_utc":UTC})); lock.chmod(0o600)
    parent_fd=tool._open_checked_directory(lock.parent)
    original_link=os.link
    try:
        old=os.stat(lock,follow_symlinks=False); replacement=lock.parent/"replacement"; replacement.write_text(json.dumps({"pid":os.getpid(),"uid":os.getuid(),"started_at_utc":UTC})); replacement.chmod(0o600); os.replace(replacement,lock)
        monkeypatch.setattr(os,"link",lambda *a,**k: (_ for _ in ()).throw(OSError("injected")))
        with pytest.raises(BlockingIOError): tool._claim_created_inode_at(parent_fd,lock.name,(old.st_dev,old.st_ino))
    finally: os.close(parent_fd)
    monkeypatch.setattr(os,"link",original_link)
    assert not lock.exists()
    assert tool.execute(FoundationRequest("init","quarantine-busy",UTC)).status=="lock_busy"
