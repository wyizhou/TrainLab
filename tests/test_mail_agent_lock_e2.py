from __future__ import annotations

import os
from pathlib import Path

import pytest

from trainlab.mail_agent.locks import MailLockBusyError, MailWriteLock


def path(tmp_path: Path) -> Path:
    (tmp_path / "state" / "locks").mkdir(parents=True, mode=0o700)
    os.chmod(tmp_path / "state", 0o700); os.chmod(tmp_path / "state" / "locks", 0o700)
    return tmp_path / "state" / "locks" / "mail.lock"


@pytest.mark.parametrize("kind", ["state_symlink", "locks_symlink", "state_missing", "locks_missing", "state_mode", "locks_mode"])
def test_e2_directory_rejections(tmp_path: Path, kind: str) -> None:
    target = path(tmp_path); outside = tmp_path / "outside"; outside.mkdir(mode=0o700)
    if kind == "state_symlink": (tmp_path / "state").rename(tmp_path / "old"); (tmp_path / "state").symlink_to(outside, target_is_directory=True)
    elif kind == "locks_symlink": (tmp_path / "state" / "locks").rename(tmp_path / "state" / "old"); (tmp_path / "state" / "locks").symlink_to(outside, target_is_directory=True)
    elif kind == "state_missing": os.rmdir(tmp_path / "state" / "locks"); os.rmdir(tmp_path / "state")
    elif kind == "locks_missing": os.rmdir(tmp_path / "state" / "locks")
    elif kind == "state_mode": os.chmod(tmp_path / "state", 0o755)
    else: os.chmod(tmp_path / "state" / "locks", 0o755)
    with pytest.raises(MailLockBusyError): MailWriteLock(target, "mail:1:poll:x").acquire()


def test_e2_success_fd_loop(tmp_path: Path) -> None:
    target = path(tmp_path); baseline = len(os.listdir("/dev/fd"))
    for _ in range(100):
        lock = MailWriteLock(target, "mail:1:poll:x"); lock.acquire(); lock.release()
    # Other pytest fixtures may close descriptors during this loop; only a
    # sustained increase is evidence of a lock-owned leak.
    assert len(os.listdir("/dev/fd")) <= baseline + 1


def test_e2_reader_after_disappearance_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = path(tmp_path); lock = MailWriteLock(target, "mail:1:poll:x"); lock.acquire(); original = os.stat; calls = 0
    def guarded(name, *args, **kwargs):
        nonlocal calls
        calls += 1
        if name == "mail.lock" and calls > 1:
            target.unlink(missing_ok=True)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(os, "stat", guarded)
    with pytest.raises(MailLockBusyError): lock._read_existing(lock._parent_fd or -1)
    if lock._parent_fd is not None:
        os.close(lock._parent_fd); lock._parent_fd = None; lock._held = False


@pytest.mark.parametrize("target,stage", [("state", "before"), ("state", "after"), ("locks", "before"), ("locks", "after")])
def test_e2_directory_swap_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, stage: str) -> None:
    candidate = path(tmp_path); original_open, original_stat = os.open, os.stat; swapped = False; stats = 0
    directory = tmp_path / "state" if target == "state" else tmp_path / "state" / "locks"
    def swap() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True; os.rename(directory, directory.with_name(directory.name + "-old")); directory.mkdir(mode=0o700)
    def guarded_open(name, *args, **kwargs):
        if stage == "before" and name == target: swap()
        return original_open(name, *args, **kwargs)
    def guarded_stat(name, *args, **kwargs):
        nonlocal stats
        if name == target and kwargs.get("dir_fd") is not None:
            stats += 1
            if stage == "after" and stats == 2: swap()
        return original_stat(name, *args, **kwargs)
    monkeypatch.setattr(os, "open", guarded_open); monkeypatch.setattr(os, "stat", guarded_stat)
    with pytest.raises(MailLockBusyError): MailWriteLock(candidate, "mail:1:poll:x").acquire()
    assert swapped
    assert directory.exists() and directory.with_name(directory.name + "-old").exists()


@pytest.mark.parametrize("kind", ["symlink", "different_inode"])
def test_e2_reader_replacement_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    candidate = path(tmp_path); lock = MailWriteLock(candidate, "mail:1:poll:x"); lock.acquire(); original = os.open; changed = False
    _pid, raw, _inode = lock._read_existing(lock._parent_fd or -1)
    def guarded(name, *args, **kwargs):
        nonlocal changed
        if name == "mail.lock" and not changed:
            changed = True; candidate.unlink()
            if kind == "symlink": candidate.symlink_to(tmp_path / "other")
            else: candidate.write_bytes(raw) ; os.chmod(candidate, 0o600)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(os, "open", guarded)
    with pytest.raises(MailLockBusyError): lock._read_existing(lock._parent_fd or -1)
    assert candidate.is_symlink() if kind == "symlink" else candidate.read_bytes() == raw
    if lock._parent_fd is not None: os.close(lock._parent_fd); lock._parent_fd=None; lock._held=False


@pytest.mark.parametrize("case", [
    "state_parent_open", "state_before_stat", "state_child_open", "state_fstat", "state_after_stat",
    "locks_before_stat", "locks_child_open", "locks_fstat", "locks_after_stat",
], ids=lambda value: value)
def test_e2_failure_stage_fd_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    baseline = len(os.listdir("/dev/fd"))
    for index in range(20):
        root = tmp_path / f"case-{index}"; candidate = path(root); fired = False; counts: dict[str, int] = {}; captured: dict[str, int] = {}
        original_open, original_stat, original_fstat = os.open, os.stat, os.fstat
        def guarded_open(name, *args, **kwargs):
            nonlocal fired
            if case == "state_parent_open" and name == candidate.parent.parent.parent:
                fired = True; raise OSError("injected")
            if case == "state_child_open" and name == "state":
                fired = True; raise OSError("injected")
            if case == "locks_child_open" and name == "locks":
                fired = True; raise OSError("injected")
            fd = original_open(name, *args, **kwargs)
            if name in {"state", "locks"}: captured[name] = fd
            return fd
        def guarded_stat(name, *args, **kwargs):
            nonlocal fired
            if name in {"state", "locks"} and kwargs.get("dir_fd") is not None:
                counts[name] = counts.get(name, 0) + 1
                target = name.split("_")[0]
                if case == f"{name}_before_stat" and counts[name] == 1: fired = True; raise OSError("injected")
                if case == f"{name}_after_stat" and counts[name] == 2: fired = True; raise OSError("injected")
            return original_stat(name, *args, **kwargs)
        def guarded_fstat(fd):
            nonlocal fired
            target = "state" if case == "state_fstat" else "locks"
            if case.endswith("_fstat") and captured.get(target) == fd: fired = True; raise OSError("injected")
            return original_fstat(fd)
        monkeypatch.setattr(os, "open", guarded_open); monkeypatch.setattr(os, "stat", guarded_stat); monkeypatch.setattr(os, "fstat", guarded_fstat)
        with pytest.raises(MailLockBusyError): MailWriteLock(candidate, "mail:1:poll:x").acquire()
        assert fired
        monkeypatch.undo()
    assert len(os.listdir("/dev/fd")) <= baseline + 1
