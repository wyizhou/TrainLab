from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from trainlab.mail_agent.locks import MailLockBusyError, MailWriteLock


def _target(root: Path) -> Path:
    path = root / "state" / "locks" / "mail.lock"
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent.parent, 0o700)
    os.chmod(path.parent, 0o700)
    return path


def _snapshot(path: Path) -> tuple[bytes, tuple[int, int]]:
    info = path.stat(follow_symlinks=False)
    return path.read_bytes(), (info.st_dev, info.st_ino)


def _alternate_raw(raw: bytes) -> bytes:
    payload = json.loads(raw)
    payload["run_key"] = f"{payload['run_key']}:changed"
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _abandon(lock: MailWriteLock) -> None:
    """Leave a valid canonical record without retaining the test's fd."""
    assert lock._parent_fd is not None
    os.close(lock._parent_fd)
    lock._parent_fd = None
    lock._held = False
    lock._inode = None


def _assert_unknown_preserved(path: Path, raw: bytes, inode: tuple[int, int]) -> None:
    candidates = [
        path,
        *sorted(path.parent.glob(".mail.lock.tombstone-*")),
        *sorted(path.parent.glob(".mail.lock.tombstone-*")),
    ]
    for candidate in candidates:
        if not candidate.exists() or candidate.is_symlink():
            continue
        info = candidate.stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino) == inode and candidate.read_bytes() == raw:
            return
    raise AssertionError("unknown claim was removed or altered")


def _make_claim_mutator(
    path: Path,
    original_raw: bytes,
    original_inode: tuple[int, int],
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[set[str], bytes, list[tuple[int, int]]]:
    """Mutate/replacement occurs only after canonical -> random claim rename."""
    fired: set[str] = set()
    original_rename = os.rename
    unknown_raw = _alternate_raw(original_raw) if kind == "mutate" else original_raw
    unknown_inode: list[tuple[int, int]] = []

    def rename_hook(src: str | bytes | Path, dst: str | bytes | Path, *args: object, **kwargs: object) -> None:
        original_rename(src, dst, *args, **kwargs)
        if os.fspath(src) != "mail.lock" or not str(os.fspath(dst)).startswith(".mail.lock.tombstone-"):
            return
        directory_fd = kwargs["dst_dir_fd"]
        claim = os.fspath(dst)
        if kind == "mutate":
            fd = os.open(claim, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                assert os.write(fd, unknown_raw) == len(unknown_raw)
                os.fsync(fd)
                info = os.fstat(fd)
                unknown_inode.append((info.st_dev, info.st_ino))
            finally:
                os.close(fd)
            assert unknown_inode[0] == original_inode
            fired.add("inplace_mutation")
            return
        swap = ".claim-swap"
        fd = os.open(swap, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        try:
            assert os.write(fd, unknown_raw) == len(unknown_raw)
            os.fsync(fd)
            info = os.fstat(fd)
            unknown_inode.append((info.st_dev, info.st_ino))
        finally:
            os.close(fd)
        os.replace(swap, claim, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        assert unknown_inode[0] != original_inode
        fired.add("new_inode_replacement")

    monkeypatch.setattr(os, "rename", rename_hook)
    # filled by hook before the operation returns
    return fired, unknown_raw, unknown_inode


def _run_claim_race(root: Path, operation: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes, tuple[int, int], set[str]]:
    path = _target(root)
    owner = MailWriteLock(path, "mail:1:poll:owner")
    owner.acquire()
    original_raw, original_inode = _snapshot(path)
    fired, unknown_raw, unknown_inode_box = _make_claim_mutator(path, original_raw, original_inode, kind, monkeypatch)
    if operation == "release":
        with pytest.raises(MailLockBusyError, match="mail_lock_replaced"):
            owner.release()
        assert not owner._held and owner._parent_fd is None and owner._inode is None
    else:
        _abandon(owner)
        with pytest.raises(MailLockBusyError, match="mail_lock_replaced"):
            MailWriteLock(path, "mail:1:poll:takeover", process_is_alive=lambda _pid: False).acquire()
    assert fired
    unknown_inode = unknown_inode_box[0]
    _assert_unknown_preserved(path, unknown_raw, unknown_inode)
    return path, unknown_raw, unknown_inode, fired


@pytest.mark.parametrize("operation", ("release", "stale"))
@pytest.mark.parametrize("kind", ("mutate", "replace"))
def test_e3b_claim_race_preserves_unknown_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kind: str
) -> None:
    before = len(os.listdir("/dev/fd"))
    for index in range(20):
        with monkeypatch.context() as patch:
            path, raw, inode, fired = _run_claim_race(tmp_path / f"{operation}-{kind}-{index}", operation, kind, patch)
            assert ("inplace_mutation" if kind == "mutate" else "new_inode_replacement") in fired
        _assert_unknown_preserved(path, raw, inode)
        with pytest.raises(MailLockBusyError):
            MailWriteLock(path, "mail:1:poll:retry").acquire()
    assert len(os.listdir("/dev/fd")) <= before + 1


def _run_claim_uncertainty(
    root: Path, operation: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, bytes, tuple[int, int], set[str]]:
    path = _target(root)
    owner = MailWriteLock(path, "mail:1:poll:owner")
    owner.acquire()
    original_raw, original_inode = _snapshot(path)
    fired: set[str] = set()
    original_open, original_stat = os.open, os.stat
    original_link, original_unlink, original_rename = os.link, os.unlink, os.rename

    unknown_raw = _alternate_raw(original_raw) if fault in {"restore_link", "restore_unlink"} else original_raw
    # Restore faults require a claim whose content no longer agrees with the
    # pre-read raw/inode; the other two fail during strict claim reread.
    if fault in {"restore_link", "restore_unlink"}:
        def rename_mutating(src: str | bytes | Path, dst: str | bytes | Path, *args: object, **kwargs: object) -> None:
            original_rename(src, dst, *args, **kwargs)
            if os.fspath(src) == "mail.lock":
                fd = original_open(os.fspath(dst), os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=kwargs["dst_dir_fd"])
                try:
                    os.write(fd, unknown_raw)
                finally:
                    os.close(fd)
                fired.add("mutation")
        monkeypatch.setattr(os, "rename", rename_mutating)

    def open_hook(name: str | bytes | Path, flags: int, *args: object, **kwargs: object) -> int:
        if (
            fault == "claim_open"
            and str(os.fspath(name)).startswith(".mail.lock.tombstone-")
            and flags & os.O_ACCMODE == os.O_RDONLY
        ):
            fired.add("claim_open")
            raise OSError("claim-read-open")
        return original_open(name, flags, *args, **kwargs)

    claim_stats = 0
    def stat_hook(name: str | bytes | Path, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal claim_stats
        if fault == "claim_after_stat" and str(os.fspath(name)).startswith(".mail.lock.tombstone-"):
            claim_stats += 1
            if claim_stats == 2:
                fired.add("claim_after_stat")
                raise OSError("claim-after-stat")
        return original_stat(name, *args, **kwargs)

    def link_hook(*args: object, **kwargs: object) -> None:
        if fault == "restore_link":
            fired.add("restore_link")
            raise OSError("restore-link")
        original_link(*args, **kwargs)

    def unlink_hook(name: str | bytes | Path, *args: object, **kwargs: object) -> None:
        # Retained tombstones are never unlinked.  Keep an explicit guard so
        # this legacy regression proves the new protocol makes no final
        # deletion attempt.
        if fault == "restore_unlink" and str(os.fspath(name)).startswith(".mail.lock.tombstone-"):
            fired.add("restore_unlink")
            raise AssertionError("retained tombstone must not be unlinked")
        original_unlink(name, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_hook)
    monkeypatch.setattr(os, "stat", stat_hook)
    monkeypatch.setattr(os, "link", link_hook)
    monkeypatch.setattr(os, "unlink", unlink_hook)
    if operation == "release":
        with pytest.raises(MailLockBusyError, match="mail_lock_replaced"):
            owner.release()
        assert not owner._held and owner._parent_fd is None
    else:
        _abandon(owner)
        with pytest.raises(MailLockBusyError, match="mail_lock_replaced"):
            MailWriteLock(path, "mail:1:poll:takeover", process_is_alive=lambda _pid: False).acquire()
    if fault == "restore_unlink":
        assert "mutation" in fired and "restore_unlink" not in fired
    else:
        assert fault in fired
    # The original record remains for reread faults; restore faults preserve a
    # mutated claim or canonical record.  In all cases no unknown evidence dies.
    _assert_unknown_preserved(path, unknown_raw, original_inode)
    return path, unknown_raw, original_inode, fired


@pytest.mark.parametrize("operation", ("release", "stale"))
@pytest.mark.parametrize("fault", ("claim_open", "claim_after_stat", "restore_link", "restore_unlink"))
def test_e3b_claim_uncertainty_preserves_busy_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, fault: str
) -> None:
    before = len(os.listdir("/dev/fd"))
    proofs: list[tuple[Path, bytes, tuple[int, int], set[str]]] = []
    for index in range(20):
        with monkeypatch.context() as patch:
            proofs.append(_run_claim_uncertainty(tmp_path / f"{operation}-{fault}-{index}", operation, fault, patch))
    for path, raw, inode, fired in proofs:
        if fault == "restore_unlink":
            assert "mutation" in fired and "restore_unlink" not in fired
        else:
            assert fault in fired
        _assert_unknown_preserved(path, raw, inode)
        with pytest.raises(MailLockBusyError):
            MailWriteLock(path, "mail:1:poll:retry").acquire()
    assert len(os.listdir("/dev/fd")) <= before + 1
    other = _target(tmp_path / "other")
    valid = MailWriteLock(other, "mail:1:poll:other")
    valid.acquire(); valid.release()
