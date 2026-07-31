"""Fail-closed single-writer lock for fourth-layer state changes.

The Foundation init owns directory creation.  This module deliberately never
creates a directory: doing so would make a symlink race part of a write path.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class MailLockBusyError(RuntimeError):
    pass


_POISONED_LOCK_DIRS: set[tuple[int, int]] = set()


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _private_directory(path: Path) -> int:
    """Bind a directory entry to its opened fd through its immediate parent."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = os.open(path.parent, flags)
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        info, after = os.fstat(descriptor), os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino) or (info.st_dev,info.st_ino)!=(after.st_dev,after.st_ino):
            raise MailLockBusyError("mail_lock_path_invalid")
        result = descriptor; descriptor = -1
        return result
    except (OSError, MailLockBusyError) as exc:
        raise MailLockBusyError("mail_lock_path_invalid") from exc
    finally:
        if descriptor >= 0: os.close(descriptor)
        if parent_fd >= 0: os.close(parent_fd)


@dataclass
class MailWriteLock:
    path: Path
    run_key: str
    process_is_alive: Callable[[int], bool] = _process_is_alive
    clock: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _held: bool = False
    _inode: tuple[int, int] | None = None
    _parent_fd: int | None = None

    def _directory_fd(self) -> int:
        parent = self.path.parent
        state = parent.parent
        state_fd = _private_directory(state); locks_fd = -1
        try:
            try:
                before = os.stat(parent.name, dir_fd=state_fd, follow_symlinks=False)
                locks_fd = os.open(parent.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=state_fd)
                info, after = os.fstat(locks_fd), os.stat(parent.name, dir_fd=state_fd, follow_symlinks=False)
            except OSError as exc:
                raise MailLockBusyError("mail_lock_path_invalid") from exc
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino) or (info.st_dev,info.st_ino)!=(after.st_dev,after.st_ino):
                os.close(locks_fd); locks_fd = -1; raise MailLockBusyError("mail_lock_path_invalid")
            result = locks_fd; locks_fd = -1
            return result
        finally:
            if locks_fd >= 0: os.close(locks_fd)
            os.close(state_fd)

    def _payload(self) -> bytes:
        if not isinstance(self.run_key, str) or not self.run_key or len(self.run_key) > 256:
            raise MailLockBusyError("mail_lock_record_invalid")
        started_at = self.clock()
        try:
            canonical = datetime.fromisoformat(started_at.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, AttributeError):
            raise MailLockBusyError("mail_lock_record_invalid") from None
        if started_at != canonical:
            raise MailLockBusyError("mail_lock_record_invalid")
        return json.dumps({"pid": os.getpid(), "run_key": self.run_key, "started_at_utc": canonical, "uid": os.getuid()}, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _read_existing(self, directory_fd: int, name: str | None = None) -> tuple[int, bytes, tuple[int, int]] | None:
        target = self.path.name if name is None else name
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            before = os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
            descriptor = os.open(target, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise MailLockBusyError("mail_lock_path_invalid") from None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or (info.st_mode & 0o777) != 0o600 or info.st_size <= 0 or info.st_size > 512:
                raise MailLockBusyError("mail_lock_record_invalid")
            chunks: list[bytes] = []; total = 0
            while total <= 512:
                chunk = os.read(descriptor, 513 - total)
                if not chunk: break
                chunks.append(chunk); total += len(chunk)
            data = b"".join(chunks)
            if len(data) != info.st_size:
                raise MailLockBusyError("mail_lock_record_invalid")
            after = os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            opened_identity = (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if before_identity != opened_identity or after_identity != opened_identity:
                raise MailLockBusyError("mail_lock_replaced")
        except (OSError, FileNotFoundError) as exc:
            raise MailLockBusyError("mail_lock_busy") from exc
        finally:
            os.close(descriptor)
        try:
            value = json.loads(data.decode("utf-8"))
            pid = value["pid"]
            run_key, uid, started = value["run_key"], value["uid"], value["started_at_utc"]
            canonical = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            exact = json.dumps({"pid": pid, "run_key": run_key, "started_at_utc": canonical, "uid": uid}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (UnicodeDecodeError, ValueError, TypeError, KeyError):
            raise MailLockBusyError("mail_lock_record_invalid") from None
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or uid != os.getuid() or not isinstance(run_key, str) or not run_key or len(run_key) > 256 or started != canonical or data != exact:
            raise MailLockBusyError("mail_lock_record_invalid")
        return pid, data, (info.st_dev, info.st_ino)

    def _claim_name(self) -> str:
        return f".{self.path.name}.tombstone-{secrets.token_hex(16)}"

    def _blocker_name(self) -> str:
        return f".{self.path.name}.blocker-{secrets.token_hex(16)}"

    def _claim_owned(self, directory_fd: int, raw: bytes, inode: tuple[int, int]) -> str | None:
        """Move a verified canonical record to a short-lived claim.

        A strictly verified claim is removed by ``_finalize_verified_claim``.
        Any uncertainty restores canonical or leaves durable evidence, so a
        future writer fails closed rather than treating cleanup as complete.
        """
        claim = self._claim_name()
        # ``rename(2)`` replaces an existing target.  Refuse a visible
        # collision before attempting it; a collision is retained diagnostic
        # evidence, not a name that we are entitled to overwrite.
        try:
            os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise MailLockBusyError("mail_lock_busy") from exc
        else:
            raise MailLockBusyError("mail_lock_busy")
        renamed = False
        try:
            os.rename(self.path.name, claim, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            renamed = True
            reread = self._read_existing(directory_fd, claim)
        except (OSError, MailLockBusyError):
            reread = None
        if reread is None or reread[1] != raw or reread[2] != inode:
            # The name became uncertain after rename.  Never leave canonical
            # empty: no-clobber-link the exact renamed object back.  If another
            # holder has already rebuilt canonical, preserve both namespaces.
            if not renamed:
                return None
            try:
                os.link(claim, self.path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                self._fsync_directory(directory_fd)
            except FileExistsError:
                # A contender restored/rebuilt canonical first.  It is a
                # holder/blocker and must be left untouched.
                return None
            except OSError:
                # If canonical is empty, publish durable uncertainty evidence.
                # If a concurrent holder created canonical meanwhile, do not
                # replace it with a blocker.
                try:
                    os.stat(self.path.name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    self._publish_blocker(directory_fd)
                except OSError:
                    self._publish_blocker(directory_fd)
            return None
        return claim

    def _finalize_verified_claim(self, directory_fd: int, claim: str, raw: bytes, inode: tuple[int, int]) -> None:
        """Delete only an unchanged, strictly reread object we own.

        The owner-only deployment model permits deletion after the complete
        name/fd/content/inode proof.  If deletion durability cannot be proven,
        a new durable blocker is published; no unknown name is ever removed.
        """
        reread = self._read_existing(directory_fd, claim)
        if reread is None or reread[1] != raw or reread[2] != inode:
            raise MailLockBusyError("mail_lock_replaced")
        try:
            os.unlink(claim, dir_fd=directory_fd)
        except OSError as exc:
            raise MailLockBusyError("mail_lock_busy") from exc
        try:
            self._fsync_directory(directory_fd)
        except MailLockBusyError:
            # The deletion may already be durable but is not provable here;
            # leave a separate, persistent fail-closed record.
            self._publish_blocker(directory_fd)
            raise

    def _publish_blocker(self, directory_fd: int) -> None:
        """Persistent no-clobber uncertainty evidence; never cleaned here."""
        try:
            fd = os.open(self._blocker_name(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            self._fsync_directory(directory_fd)
        except OSError as exc:
            info = os.fstat(directory_fd)
            _POISONED_LOCK_DIRS.add((info.st_dev, info.st_ino))
            raise MailLockBusyError("mail_lock_blocker_failed") from exc

    def _cleanup_created(self, directory_fd: int, inode: tuple[int, int], raw: bytes) -> None:
        """Clean only a proven failed create; preserve uncertainty evidence.

        ``raw`` is the exact descriptor-bound byte snapshot accumulated by the
        writer.  An in-place mutation therefore fails closed just as an inode
        replacement does.
        """
        claim = self._claim_name()
        renamed = False
        try:
            # Incomplete records intentionally cannot use the JSON reader.  We
            # instead bind the pre-write descriptor snapshot to the renamed
            # entry by inode *and exact bytes*.
            try:
                os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                self._publish_blocker(directory_fd)
                return
            os.rename(self.path.name, claim, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            renamed = True
            fd = os.open(claim, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                chunks: list[bytes] = []
                total = 0
                while total <= len(raw):
                    chunk = os.read(fd, len(raw) + 1 - total)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                after = os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            finally:
                os.close(fd)
            exact = (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and (info.st_mode & 0o777) == 0o600
                and (info.st_dev, info.st_ino) == inode
                and (after.st_dev, after.st_ino) == inode
                and b"".join(chunks) == raw
            )
            if exact:
                # An incomplete O_EXCL record is still safe to remove only
                # after a complete descriptor/name/content proof.
                try:
                    os.unlink(claim, dir_fd=directory_fd)
                    self._fsync_directory(directory_fd)
                    return
                except OSError:
                    self._publish_blocker(directory_fd)
                    return
                except MailLockBusyError:
                    self._publish_blocker(directory_fd)
                    return
        except (OSError, MailLockBusyError):
            pass

        # Unknown/in-place-modified evidence must again occupy canonical when
        # possible; otherwise a durable blocker makes the uncertainty visible.
        if renamed:
            try:
                os.link(claim, self.path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                self._fsync_directory(directory_fd)
                return
            except FileExistsError:
                return
            except OSError:
                pass
        try:
            os.stat(self.path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            try:
                self._publish_blocker(directory_fd)
            except MailLockBusyError:
                return

    def _fsync_directory(self, descriptor: int) -> None:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise MailLockBusyError("mail_lock_fsync_failed") from exc

    def _has_claim_blocker(self, directory_fd: int) -> bool:
        try:
            info = os.fstat(directory_fd)
            if (info.st_dev, info.st_ino) in _POISONED_LOCK_DIRS: return True
            names = os.listdir(directory_fd)
            # A normal finalizer leaves neither claim nor tombstone.  Thus any
            # residual one proves interrupted/uncertain cleanup and blocks the
            # next writer.  Legacy claims are handled identically.
            return any(
                name.startswith(f".{self.path.name}.blocker-")
                or name.startswith(f".{self.path.name}.claim-")
                or name.startswith(f".{self.path.name}.tombstone-")
                for name in names
            )
        except OSError as exc:
            raise MailLockBusyError("mail_lock_busy") from exc

    def acquire(self) -> None:
        payload = self._payload()
        directory_fd = self._directory_fd()
        created_inode: tuple[int, int] | None = None
        created_raw = b""
        try:
            if self._has_claim_blocker(directory_fd):
                raise MailLockBusyError("mail_lock_busy")
            for _ in range(2):
                try:
                    descriptor = os.open(self.path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
                except FileExistsError:
                    existing = self._read_existing(directory_fd)
                    if existing is None:
                        continue
                    pid, raw, inode = existing
                    if self.process_is_alive(pid):
                        raise MailLockBusyError("mail_lock_busy")
                    # Verify the observed name still denotes the same inode
                    # immediately before removal; a replacement is preserved.
                    claimed = self._claim_owned(directory_fd, raw, inode)
                    if claimed is None:
                        raise MailLockBusyError("mail_lock_replaced")
                    self._finalize_verified_claim(directory_fd, claimed, raw, inode)
                    continue
                try:
                    info = os.fstat(descriptor)
                    self._inode = (info.st_dev, info.st_ino)
                    created_inode = self._inode
                    os.fchmod(descriptor, 0o600)
                    offset = 0
                    while offset < len(payload):
                        written = os.write(descriptor, payload[offset:])
                        if written <= 0:
                            raise MailLockBusyError("mail_lock_write_failed")
                        offset += written
                        created_raw = payload[:offset]
                    os.fsync(descriptor)
                    info = os.fstat(descriptor)
                    if info.st_size != len(payload) or (info.st_mode & 0o777) != 0o600:
                        raise MailLockBusyError("mail_lock_record_invalid")
                    self._inode = (info.st_dev, info.st_ino)
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.read(descriptor, len(payload) + 1) != payload:
                        raise MailLockBusyError("mail_lock_record_invalid")
                finally:
                    os.close(descriptor)
                self._fsync_directory(directory_fd)
                reread = self._read_existing(directory_fd)
                if reread is None or reread[1] != payload or reread[2] != self._inode:
                    raise MailLockBusyError("mail_lock_replaced")
                self._held = True
                self._parent_fd = directory_fd
                return
            raise MailLockBusyError("mail_lock_busy")
        except OSError as exc:
            if created_inode is not None: self._cleanup_created(directory_fd, created_inode, created_raw)
            raise MailLockBusyError("mail_lock_io_failed") from exc
        except Exception:
            if created_inode is not None: self._cleanup_created(directory_fd, created_inode, created_raw)
            raise
        finally:
            if not self._held: os.close(directory_fd)

    def _remove_owned(self, directory_fd: int) -> bool:
        if self._inode is None:
            return False
        existing = self._read_existing(directory_fd)
        if existing is None: return False
        _pid, raw, inode = existing
        if inode != self._inode: return False
        claim = self._claim_owned(directory_fd, raw, self._inode)
        if claim is None: return False
        self._finalize_verified_claim(directory_fd, claim, raw, self._inode)
        return True

    def release(self) -> None:
        if not self._held:
            return
        try:
            directory_fd = self._parent_fd
            if directory_fd is None: raise MailLockBusyError("mail_lock_replaced")
            try:
                if not self._remove_owned(directory_fd):
                    raise MailLockBusyError("mail_lock_replaced")
            finally:
                os.close(directory_fd)
        finally:
            self._held = False
            self._inode = None
            self._parent_fd = None

    def __enter__(self) -> "MailWriteLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
