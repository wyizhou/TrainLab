from __future__ import annotations

import os
from pathlib import Path

import pytest

from trainlab.mail_agent.locks import MailLockBusyError, MailWriteLock


FAULTS = (
    "zero",
    "first_write",
    "mid_write",
    "fchmod",
    "file_fsync",
    "dir_fsync",
    "rename",
    "unlink",
    "post_fsync",
    "blocker_open",
)

EXPECTED_STAGES = {
    "zero": {"zero"},
    "first_write": {"first_write"},
    "mid_write": {"partial", "mid_write"},
    "fchmod": {"fchmod"},
    "file_fsync": {"file_fsync"},
    "dir_fsync": {"dir_fsync"},
    "rename": {"file_fsync", "rename"},
    "unlink": {"file_fsync", "unlink"},
    "post_fsync": {"file_fsync", "post_fsync"},
    "blocker_open": {"file_fsync"},
}


def target(root: Path) -> Path:
    path = root / "state" / "locks" / "mail.lock"
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent.parent, 0o700)
    os.chmod(path.parent, 0o700)
    return path


def _run_fault_once(root: Path, fault: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, set[str], bool]:
    """Run one precisely targeted create-path fault.

    Each hook is bound to the descriptor/name that the lock implementation uses,
    rather than to the first filesystem call in the process.  The boolean is the
    expected retry result after these patches are undone: True means an explicit
    fail-closed blocker remains.
    """
    path = target(root)
    stages: set[str] = set()
    opened: dict[str, int] = {}
    original_open, original_write = os.open, os.write
    original_fchmod, original_fsync = os.fchmod, os.fsync
    original_rename, original_unlink, original_link = os.rename, os.unlink, os.link
    write_calls = 0

    def open_hook(name: str | bytes | Path, flags: int, *args: object, **kwargs: object) -> int:
        text = os.fspath(name)
        # The claim blocker is deliberately injected only after cleanup has
        # unlinked its claim and discovered that directory durability failed.
        if (
            fault == "blocker_open"
            and "post_fsync" in stages
            and isinstance(text, str)
            and text.startswith(".mail.lock.blocker-")
            and flags & os.O_WRONLY
            and flags & os.O_CREAT
            and flags & os.O_EXCL
        ):
            stages.add("blocker_open")
            raise OSError("blocker-open")
        descriptor = original_open(name, flags, *args, **kwargs)
        if text == "mail.lock" and flags & os.O_CREAT and flags & os.O_EXCL:
            opened["create"] = descriptor
        if text == "locks" and kwargs.get("dir_fd") is not None:
            opened["locks"] = descriptor
        return descriptor

    def write_hook(descriptor: int, data: bytes) -> int:
        nonlocal write_calls
        if descriptor != opened.get("create"):
            return original_write(descriptor, data)
        write_calls += 1
        if fault == "zero":
            stages.add("zero")
            return 0
        if fault == "first_write":
            stages.add("first_write")
            raise OSError("first-write")
        if fault == "mid_write":
            if write_calls == 1:
                stages.add("partial")
                return original_write(descriptor, data[:1])
            stages.add("mid_write")
            raise OSError("mid-write")
        return original_write(descriptor, data)

    def chmod_hook(descriptor: int, mode: int) -> None:
        if fault == "fchmod" and descriptor == opened.get("create"):
            stages.add("fchmod")
            raise OSError("fchmod")
        original_fchmod(descriptor, mode)

    def fsync_hook(descriptor: int) -> None:
        if descriptor == opened.get("create") and fault in {"file_fsync", "rename", "unlink", "post_fsync", "blocker_open"}:
            stages.add("file_fsync")
            raise OSError("file-fsync")
        if descriptor == opened.get("locks"):
            if fault == "dir_fsync" and "dir_fsync" not in stages:
                stages.add("dir_fsync")
                raise OSError("publication-dir-fsync")
            if fault in {"post_fsync", "blocker_open"} and "file_fsync" in stages and "post_fsync" not in stages:
                stages.add("post_fsync")
                raise OSError("cleanup-dir-fsync")
        original_fsync(descriptor)

    def rename_hook(src: str | bytes | Path, dst: str | bytes | Path, *args: object, **kwargs: object) -> None:
        if fault == "rename" and os.fspath(src) == "mail.lock":
            stages.add("rename")
            raise OSError("cleanup-rename")
        original_rename(src, dst, *args, **kwargs)

    def unlink_hook(name: str | bytes | Path, *args: object, **kwargs: object) -> None:
        text = os.fspath(name)
        if isinstance(text, str) and text.startswith(".mail.lock.tombstone-") and fault == "unlink":
            stages.add("unlink")
            raise OSError("verified-claim-unlink")
        original_unlink(name, *args, **kwargs)

    def link_hook(src: str | bytes | Path, dst: str | bytes | Path, *args: object, **kwargs: object) -> None:
        if fault == "blocker_open" and os.fspath(dst) == "mail.lock":
            stages.add("restore_link")
            raise OSError("restore-link")
        original_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_hook)
    monkeypatch.setattr(os, "write", write_hook)
    monkeypatch.setattr(os, "fchmod", chmod_hook)
    monkeypatch.setattr(os, "fsync", fsync_hook)
    monkeypatch.setattr(os, "rename", rename_hook)
    monkeypatch.setattr(os, "unlink", unlink_hook)
    monkeypatch.setattr(os, "link", link_hook)

    expected_busy = fault in {"rename", "unlink", "post_fsync", "blocker_open"}
    expected_message = None
    with pytest.raises(MailLockBusyError, match=expected_message):
        MailWriteLock(path, "mail:1:poll:a").acquire()
    assert EXPECTED_STAGES[fault] <= stages
    return path, stages, expected_busy


def _assert_retry(path: Path, expected_busy: bool) -> None:
    if expected_busy:
        with pytest.raises(MailLockBusyError):
            MailWriteLock(path, "mail:1:poll:retry").acquire()
        return
    lock = MailWriteLock(path, "mail:1:poll:retry")
    lock.acquire()
    lock.release()
    assert not path.exists()
    assert not list(path.parent.glob("*.tombstone-*"))


@pytest.mark.parametrize("fault", FAULTS, ids=FAULTS)
def test_e3a_fault_state_and_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    path, stages, expected_busy = _run_fault_once(tmp_path, fault, monkeypatch)
    assert EXPECTED_STAGES[fault] <= stages
    monkeypatch.undo()
    _assert_retry(path, expected_busy)


def test_e3a_partial_write_success_and_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = target(tmp_path)
    original_write = os.write
    created: dict[str, int] = {}
    original_open = os.open

    def open_hook(name: str | bytes | Path, flags: int, *args: object, **kwargs: object) -> int:
        descriptor = original_open(name, flags, *args, **kwargs)
        if os.fspath(name) == "mail.lock" and flags & os.O_CREAT and flags & os.O_EXCL:
            created["fd"] = descriptor
        return descriptor

    def partial(descriptor: int, data: bytes) -> int:
        if descriptor == created.get("fd") and len(data) > 1:
            return original_write(descriptor, data[:1])
        return original_write(descriptor, data)

    monkeypatch.setattr(os, "open", open_hook)
    monkeypatch.setattr(os, "write", partial)
    lock = MailWriteLock(path, "mail:1:poll:a")
    lock.acquire()
    lock.release()
    assert not path.exists()
    assert not list(path.parent.glob("*.tombstone-*"))


@pytest.mark.parametrize("fault", FAULTS, ids=FAULTS)
def test_e3a_fault_fd_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    """Twenty independent roots prove each exact fault path releases fds."""
    before = len(os.listdir("/dev/fd"))
    for index in range(20):
        with monkeypatch.context() as patch:
            path, stages, expected_busy = _run_fault_once(tmp_path / f"{fault}-{index}", fault, patch)
            assert EXPECTED_STAGES[fault] <= stages
        _assert_retry(path, expected_busy)
    after = len(os.listdir("/dev/fd"))
    assert after <= before + 1
