"""A3-05 local run identity, SQLite state, and owner-only subject locks.

This module deliberately has no runner, provider, delivery, or scheduler
integration.  It records only the minimal lifecycle state required before a
future publisher can be introduced.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .contracts import AnalysisRequest


_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WRITE_MODES = frozenset({"daily", "weekly", "revise_plan", "regenerate"})
_KIND_BY_MODE = {"daily": "daily", "weekly": "weekly", "revise_plan": "plan_revision", "regenerate": "regeneration"}
_LOCK_KEYS = frozenset({"pid", "run_key", "started_at_utc"})


class AnalysisRunStateError(RuntimeError):
    """A controlled state/lock/schema failure without payload disclosure."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _valid_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() == timezone.utc.utcoffset(None)
    except ValueError:
        return False


def _atom(value: str | None, label: str, *, allow_colon: bool = False) -> str:
    pattern = _IDENTIFIER if allow_colon else _SUBJECT
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AnalysisRunStateError(f"analysis_run_key_invalid_{label}")
    return value


def _encode(value: str | None, label: str) -> str:
    """Encode only the separator; ordinary documented keys remain unchanged."""

    return _atom(value, label, allow_colon=True).replace(":", "%3A")


def _decode(value: str, label: str) -> str:
    # `%` is not a permitted source identifier character, so accepting only the
    # canonical uppercase escape prevents multiple spellings of the same key.
    if "%" in value and not re.fullmatch(r"(?:[A-Za-z0-9_-]|%3A)+", value):
        raise AnalysisRunStateError(f"analysis_run_key_invalid_{label}")
    decoded = value.replace("%3A", ":")
    _atom(decoded, label, allow_colon=True)
    if _encode(decoded, label) != value:
        raise AnalysisRunStateError(f"analysis_run_key_noncanonical_{label}")
    return decoded


def _date(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise AnalysisRunStateError(f"analysis_run_key_invalid_{label}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise AnalysisRunStateError(f"analysis_run_key_invalid_{label}") from error
    return value


@dataclass(frozen=True)
class RunKey:
    value: str
    subject_key: str
    mode: Literal["daily", "weekly", "revise_plan", "regenerate"]
    invocation_id: str


def build_analysis_run_key(request: AnalysisRequest) -> RunKey:
    """Build exactly one unambiguous §22 run-key format for a write route."""

    request.validate()
    if request.mode not in _WRITE_MODES:
        raise AnalysisRunStateError("analysis_run_mode_not_publishable")
    subject = _atom(request.subject_id, "subject")
    invocation = _encode(request.invocation_id, "invocation")
    if request.mode == "daily":
        target = _date(request.summary_local_date, "summary_date")
        value = f"analysis:{subject}:daily:{target}:{invocation}"
    elif request.mode == "weekly":
        target = _date(request.as_of_local_date, "as_of_date")
        value = f"analysis:{subject}:weekly:{target}:{invocation}"
    elif request.mode == "revise_plan":
        plan_id = _encode(request.plan_id, "plan_id")
        event_id = _encode(request.reason_event_id, "reason_event_id")
        value = f"analysis:{subject}:revise_plan:{plan_id}:{event_id}:{invocation}"
    else:
        artifact_id = _encode(request.artifact_id, "artifact_id")
        value = f"analysis:{subject}:regenerate:{artifact_id}:{invocation}"
    return RunKey(value=value, subject_key=subject, mode=request.mode, invocation_id=_decode(invocation, "invocation"))  # type: ignore[arg-type]


def parse_analysis_run_key(value: str) -> RunKey:
    """Parse only the four canonical formats; reject ambiguous colon payloads."""

    pieces = value.split(":")
    if len(pieces) not in {5, 6} or pieces[:1] != ["analysis"]:
        raise AnalysisRunStateError("analysis_run_key_invalid_format")
    subject, mode = _atom(pieces[1], "subject"), pieces[2]
    if mode == "daily" and len(pieces) == 5:
        _date(pieces[3], "summary_date"); invocation = _decode(pieces[4], "invocation")
    elif mode == "weekly" and len(pieces) == 5:
        _date(pieces[3], "as_of_date"); invocation = _decode(pieces[4], "invocation")
    elif mode == "revise_plan" and len(pieces) == 6:
        _decode(pieces[3], "plan_id"); _decode(pieces[4], "reason_event_id"); invocation = _decode(pieces[5], "invocation")
    elif mode == "regenerate" and len(pieces) == 5:
        _decode(pieces[3], "artifact_id"); invocation = _decode(pieces[4], "invocation")
    else:
        raise AnalysisRunStateError("analysis_run_key_invalid_format")
    return RunKey(value=value, subject_key=subject, mode=mode, invocation_id=invocation)  # type: ignore[arg-type]


@dataclass
class SubjectLock:
    path: Path
    parent_fd: int
    filename: str
    device: int
    inode: int
    pid: int
    run_key: str
    started_at_utc: str
    released: bool = False

    def _payload(self) -> dict[str, object]:
        return {"pid": self.pid, "run_key": self.run_key, "started_at_utc": self.started_at_utc}

    def _close_once(self) -> None:
        if not self.released:
            try:
                os.close(self.parent_fd)
            finally:
                self.released = True

    def _write_cleanup_blocker(self) -> None:
        """Persist a private claim-shaped blocker after post-commit cleanup loss."""
        name = f".{self.filename}.cleanup.{secrets.token_hex(16)}.claim"
        data = json.dumps(self._payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=self.parent_fd)
            try:
                os.fchmod(fd, 0o600)
                offset = 0
                while offset < len(data):
                    count = os.write(fd, data[offset:])
                    if count <= 0:
                        raise OSError("analysis_lock_write_incomplete")
                    offset += count
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(self.parent_fd)
            checked, info = _read_private_lock_at(self.parent_fd, name)
            if checked != self._payload() or not stat.S_ISREG(info.st_mode):
                raise OSError("analysis_cleanup_blocker_invalid")
        except OSError:
            # The directory entry, if created, is deliberately retained even
            # when durability confirmation fails: fail closed over availability.
            pass

    def claim_for_finish(self) -> str:
        """Atomically remove canonical authority while retaining a finish claim."""
        if self.released:
            raise AnalysisRunStateError("analysis_lock_already_released")
        try:
            payload, info = _read_private_lock_at(self.parent_fd, self.filename)
            if payload != self._payload() or (info.st_dev, info.st_ino) != (self.device, self.inode):
                raise AnalysisRunStateError("analysis_lock_busy")
            claim = _claim_private_lock_at(self.parent_fd, self.filename, info, payload, "finish", retain_claim=True)
            assert claim is not None
            return claim
        except (FileNotFoundError, AnalysisRunStateError, OSError) as error:
            self._close_once()
            raise AnalysisRunStateError("analysis_lock_busy") from error

    def finalize_finish_claim(self, claim: str, *, committed: bool) -> None:
        """Delete a verified claim after commit, or restore/block after rollback."""
        try:
            payload, info = _read_private_lock_at(self.parent_fd, claim)
            if payload != self._payload() or (info.st_dev, info.st_ino) != (self.device, self.inode):
                raise AnalysisRunStateError("analysis_lock_busy")
            if committed:
                try:
                    os.unlink(claim, dir_fd=self.parent_fd)
                    os.fsync(self.parent_fd)
                except OSError as error:
                    # If unlink won but the directory fsync did not, recreate
                    # a durable blocker before exposing the controlled result.
                    self._write_cleanup_blocker()
                    raise AnalysisRunStateError("analysis_lock_busy") from error
            else:
                # Restore without overwriting a concurrent canonical owner. A
                # failed create leaves the claim as a durable blocker.
                try:
                    os.link(claim, self.filename, src_dir_fd=self.parent_fd, dst_dir_fd=self.parent_fd, follow_symlinks=False)
                    os.fsync(self.parent_fd)
                    os.unlink(claim, dir_fd=self.parent_fd)
                    os.fsync(self.parent_fd)
                except FileExistsError:
                    raise AnalysisRunStateError("analysis_lock_busy")
        finally:
            self._close_once()

    def release(self) -> None:
        """Claim and remove only this owner's record through the held dirfd."""
        if self.released:
            raise AnalysisRunStateError("analysis_lock_already_released")
        try:
            payload, info = _read_private_lock_at(self.parent_fd, self.filename)
            if payload != {"pid": self.pid, "run_key": self.run_key, "started_at_utc": self.started_at_utc}:
                raise AnalysisRunStateError("analysis_lock_owner_record_replaced")
            if (info.st_dev, info.st_ino) != (self.device, self.inode):
                raise AnalysisRunStateError("analysis_lock_owner_record_replaced")
            _claim_private_lock_at(self.parent_fd, self.filename, info, payload, "release")
        except (FileNotFoundError, AnalysisRunStateError, OSError) as error:
            # A changed/missing record is indistinguishable from a concurrent
            # owner without deleting it, so fail closed as a busy lock.
            raise AnalysisRunStateError("analysis_lock_busy") from error
        finally:
            try:
                os.close(self.parent_fd)
            finally:
                self.released = True


def _read_private_lock(path: Path) -> tuple[dict[str, object], os.stat_result]:
    """Read one lock without following a swapped link or a non-private file."""

    try:
        listed = path.lstat()
        if stat.S_ISLNK(listed.st_mode) or not stat.S_ISREG(listed.st_mode):
            raise AnalysisRunStateError("analysis_lock_busy")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except (FileNotFoundError, OSError) as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (listed.st_dev, listed.st_ino) or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o600:
            raise AnalysisRunStateError("analysis_lock_busy")
        raw = os.read(fd, 16_384)
        if os.read(fd, 1):
            raise AnalysisRunStateError("analysis_lock_busy")
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error
    if not isinstance(payload, dict):
        raise AnalysisRunStateError("analysis_lock_busy")
    return payload, opened


def _read_private_lock_at(parent_fd: int, name: str) -> tuple[dict[str, object], os.stat_result]:
    if not name or "/" in name: raise AnalysisRunStateError("analysis_lock_busy")
    try: before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError: raise
    except OSError as error: raise AnalysisRunStateError("analysis_lock_busy") from error
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600: raise AnalysisRunStateError("analysis_lock_busy")
    try: fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    except OSError as error: raise AnalysisRunStateError("analysis_lock_busy") from error
    try:
        opened = os.fstat(fd)
        chunks=[]; remaining=16_384
        while remaining:
            part=os.read(fd, remaining)
            if not part: break
            chunks.append(part); remaining -= len(part)
        raw=b"".join(chunks)
        if os.read(fd, 1): raise AnalysisRunStateError("analysis_lock_busy")
    finally: os.close(fd)
    try: after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error: raise AnalysisRunStateError("analysis_lock_busy") from error
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    opened_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != opened_identity or after_identity != opened_identity or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode)!=0o600: raise AnalysisRunStateError("analysis_lock_busy")
    try: payload=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as error: raise AnalysisRunStateError("analysis_lock_busy") from error
    if not isinstance(payload,dict) or set(payload) != _LOCK_KEYS or not isinstance(payload.get("pid"),int) or payload["pid"] <= 0 or not isinstance(payload.get("run_key"),str) or not _valid_utc(payload.get("started_at_utc")):
        raise AnalysisRunStateError("analysis_lock_busy")
    try: parse_analysis_run_key(payload["run_key"])
    except AnalysisRunStateError as error: raise AnalysisRunStateError("analysis_lock_busy") from error
    return payload, opened


def _unlink_same_inode(path: Path, expected: os.stat_result) -> bool:
    """Use a no-follow parent dirfd and refuse a name-replacement race."""
    try:
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return False
    try:
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
            return False
        os.unlink(path.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return True
    except OSError:
        return False
    finally:
        os.close(parent_fd)


def _claim_private_lock_at(
    parent_fd: int,
    canonical: str,
    expected_info: os.stat_result,
    expected_payload: dict[str, object],
    purpose: str,
    *,
    allow_incomplete_owned_record: bool = False,
    retain_claim: bool = False,
) -> str | None:
    """Delete only a lock atomically claimed from its trusted parent directory.

    A canonical name is never unlinked after a separate stat: rename first
    claims that exact directory entry.  A mismatching claimed inode remains as
    a durable blocker and, when possible, is hard-linked back to the canonical
    name without overwriting a third-party recreation.
    """

    if not canonical or "/" in canonical or not re.fullmatch(r"[A-Za-z0-9_-]+", purpose):
        raise AnalysisRunStateError("analysis_lock_busy")
    claim = f".{canonical}.{purpose}.{secrets.token_hex(16)}.claim"
    source_fd = -1
    try:
        source_fd = os.open(
            canonical,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        held = os.fstat(source_fd)
        if (
            not stat.S_ISREG(held.st_mode)
            or held.st_uid != os.getuid()
            or stat.S_IMODE(held.st_mode) != 0o600
            or (held.st_dev, held.st_ino)
            != (expected_info.st_dev, expected_info.st_ino)
        ):
            raise AnalysisRunStateError("analysis_lock_busy")
        os.rename(canonical, claim, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except (OSError, AnalysisRunStateError) as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error
    finally:
        if source_fd >= 0:
            os.close(source_fd)
    try:
        payload, claimed = _read_private_lock_at(parent_fd, claim)
    except (FileNotFoundError, AnalysisRunStateError) as error:
        if allow_incomplete_owned_record:
            # A short/zero write cannot meet the strict JSON contract.  The
            # O_EXCL creator still knows its inode, so use the same claimed
            # name plus a no-follow before/open/after inode check to clean only
            # that incomplete record.
            try:
                before = os.stat(claim, dir_fd=parent_fd, follow_symlinks=False)
                fd = os.open(claim, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                try:
                    claimed = os.fstat(fd)
                finally:
                    os.close(fd)
                after = os.stat(claim, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as inode_error:
                raise AnalysisRunStateError("analysis_lock_busy") from inode_error
            if (
                (before.st_dev, before.st_ino) == (claimed.st_dev, claimed.st_ino)
                and (after.st_dev, after.st_ino) == (claimed.st_dev, claimed.st_ino)
                and (claimed.st_dev, claimed.st_ino) == (expected_info.st_dev, expected_info.st_ino)
            ):
                payload = expected_payload
            else:
                raise AnalysisRunStateError("analysis_lock_busy") from error
        else:
            # The claim name is either no longer trustworthy or not readable.
            # It remains isolated; no later cleanup may destroy an unknown record.
            raise AnalysisRunStateError("analysis_lock_busy") from error
    if (
        payload != expected_payload
        or (claimed.st_dev, claimed.st_ino) != (expected_info.st_dev, expected_info.st_ino)
        or claimed.st_size != expected_info.st_size
        or claimed.st_mtime_ns != expected_info.st_mtime_ns
    ):
        # Restore the visible canonical name only with a create-only hardlink;
        # the retained claim is also a durable blocker for any later acquire.
        try:
            os.link(claim, canonical, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise AnalysisRunStateError("analysis_lock_busy") from error
        raise AnalysisRunStateError("analysis_lock_busy")
    # A third party may recreate canonical after our rename.  Never delete the
    # owned claim in that state: preserving it keeps later acquisitions busy.
    try:
        os.stat(canonical, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error
    else:
        raise AnalysisRunStateError("analysis_lock_busy")
    if retain_claim:
        return claim
    try:
        os.unlink(claim, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error
    return None


def _has_claim_blocker_at(parent_fd: int, canonical: str) -> bool:
    """A retained mismatch claim must block future writers for this subject."""

    prefix = f".{canonical}."
    try:
        return any(name.startswith(prefix) and name.endswith(".claim") for name in os.listdir(parent_fd))
    except OSError as error:
        raise AnalysisRunStateError("analysis_lock_busy") from error


class SubjectLockManager:
    """Nonblocking, per-subject, PID-aware local locks."""

    def __init__(self, base_lock_path: Path, *, trusted_root: Path | None = None) -> None:
        self._base = base_lock_path
        # Foundation/A3-03 owns the state root.  Do not resolve before checking:
        # a lexical descendant through a symlink is precisely what we reject.
        self._trusted_root = trusted_root or base_lock_path.parent.parent

    def _path_for(self, subject_key: str) -> Path:
        _atom(subject_key, "subject")
        base = self._base.absolute()
        root = self._trusted_root.absolute()
        parent = base.parent
        if not base.name or "/" in base.name:
            raise AnalysisRunStateError("analysis_lock_parent_invalid")
        try:
            parts = parent.relative_to(root).parts
        except ValueError as error:
            raise AnalysisRunStateError("analysis_lock_path_escape") from error
        fd, _, _ = self._open_lock_parent(subject_key)
        os.close(fd)
        candidate = parent / f"{self._base.name}.{subject_key}.lock"
        return candidate

    def _open_lock_parent(self, subject_key: str) -> tuple[int, os.stat_result, str]:
        """Open the lexical trusted-root→parent chain without following links."""
        base, root = self._base.absolute(), self._trusted_root.absolute()
        try: parts = base.parent.relative_to(root).parts
        except ValueError as error: raise AnalysisRunStateError("analysis_lock_path_escape") from error
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try: root_before = root.lstat(); fd = os.open(root, flags)
        except OSError as error: raise AnalysisRunStateError("analysis_lock_parent_invalid") from error
        try:
            root_info = os.fstat(fd)
            root_after = root.lstat()
            if (root_before.st_dev,root_before.st_ino)!=(root_info.st_dev,root_info.st_ino) or (root_after.st_dev,root_after.st_ino)!=(root_info.st_dev,root_info.st_ino) or not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
                raise AnalysisRunStateError("analysis_lock_parent_unsafe_permissions")
            for part in parts:
                before = os.stat(part, dir_fd=fd, follow_symlinks=False)
                try: nxt = os.open(part, flags, dir_fd=fd)
                except OSError as error: raise AnalysisRunStateError("analysis_lock_path_escape") from error
                info = os.fstat(fd)
                info = os.fstat(nxt); after = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if (before.st_dev,before.st_ino)!=(info.st_dev,info.st_ino) or (after.st_dev,after.st_ino)!=(info.st_dev,info.st_ino) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    os.close(nxt)
                    raise AnalysisRunStateError("analysis_lock_parent_unsafe_permissions")
                os.close(fd); fd = nxt
            return fd, os.fstat(fd), f"{base.name}.{_atom(subject_key, 'subject')}.lock"
        except Exception:
            os.close(fd); raise

    def canonical_path(self, subject_key: str) -> Path:
        return self._path_for(subject_key)

    @staticmethod
    def _existing_is_live_or_invalid(path: Path, subject_key: str) -> bool:
        try: info = path.lstat()
        except FileNotFoundError: return False
        try:
            payload, opened = _read_private_lock(path)
            if set(payload) != _LOCK_KEYS or not isinstance(payload["pid"], int) or payload["pid"] <= 0 or not isinstance(payload["run_key"], str) or not _valid_utc(payload["started_at_utc"]):
                return True
            key = parse_analysis_run_key(payload["run_key"])
            if key.subject_key != subject_key:
                return True
            os.kill(payload["pid"], 0)
            return True
        except ProcessLookupError:
            return False
        except (PermissionError, OSError, AnalysisRunStateError):
            return True

    @staticmethod
    def _existing_is_live_or_invalid_at(parent_fd: int, filename: str, subject_key: str) -> bool:
        try: payload, _ = _read_private_lock_at(parent_fd, filename)
        except FileNotFoundError: return False
        except (OSError, AnalysisRunStateError): return True
        try:
            key = parse_analysis_run_key(payload["run_key"])
            return key.subject_key != subject_key or not isinstance(payload.get("pid"), int) or (os.kill(payload["pid"], 0) is None)
        except ProcessLookupError: return True
        except Exception: return True

    def acquire(self, subject_key: str, run_key: str) -> SubjectLock:
        subject_key = _atom(subject_key, "subject")
        key = parse_analysis_run_key(run_key)
        if key.subject_key != subject_key:
            raise AnalysisRunStateError("analysis_lock_subject_mismatch")
        # This lexical path is presentation-only.  Every filesystem operation
        # below uses the single parent fd returned by _open_lock_parent.
        path = self._base.absolute().parent / f"{self._base.name}.{subject_key}.lock"
        parent_fd, _, filename = self._open_lock_parent(subject_key)
        started_at_utc = _utc_now()
        payload = {"pid": os.getpid(), "run_key": run_key, "started_at_utc": started_at_utc}
        created_info: os.stat_result | None = None
        try:
            if _has_claim_blocker_at(parent_fd, filename):
                raise AnalysisRunStateError("analysis_lock_busy")
            try:
                existing_payload, existing_info = _read_private_lock_at(parent_fd, filename)
            except FileNotFoundError:
                pass
            except AnalysisRunStateError as error:
                raise AnalysisRunStateError("analysis_lock_busy") from error
            else:
                try:
                    existing_key = parse_analysis_run_key(existing_payload["run_key"])
                    if existing_key.subject_key != subject_key:
                        raise AnalysisRunStateError("analysis_lock_busy")
                    os.kill(int(existing_payload["pid"]), 0)
                except ProcessLookupError:
                    _claim_private_lock_at(parent_fd, filename, existing_info, existing_payload, "stale")
                except (PermissionError, OSError, ValueError, TypeError, AnalysisRunStateError) as error:
                    raise AnalysisRunStateError("analysis_lock_busy") from error

            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(filename, flags, 0o600, dir_fd=parent_fd)
            except FileExistsError as error:
                raise AnalysisRunStateError("analysis_lock_busy") from error
            try:
                os.fchmod(fd, 0o600)
                data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                written = 0
                while written < len(data):
                    count = os.write(fd, data[written:])
                    if count <= 0:
                        raise OSError("analysis_lock_write_incomplete")
                    written += count
                os.fsync(fd)
                os.fsync(parent_fd)
                created_info = os.fstat(fd)
            except OSError as error:
                try:
                    created_info = os.fstat(fd)
                except OSError:
                    pass
                raise AnalysisRunStateError("analysis_lock_create_failed") from error
            finally:
                os.close(fd)

            checked, held = _read_private_lock_at(parent_fd, filename)
            if created_info is None or checked != payload or (held.st_dev, held.st_ino) != (created_info.st_dev, created_info.st_ino):
                raise AnalysisRunStateError("analysis_lock_create_failed")
            return SubjectLock(path=path, parent_fd=parent_fd, filename=filename, device=held.st_dev, inode=held.st_ino, pid=payload["pid"], run_key=run_key, started_at_utc=started_at_utc)
        except Exception:
            # A failed post-create verification may only remove the inode and
            # payload this call created.  A replacement is quarantined.
            if created_info is not None:
                try:
                    _claim_private_lock_at(parent_fd, filename, created_info, payload, "failed-create", allow_incomplete_owned_record=True)
                except AnalysisRunStateError:
                    # A post-create replacement is not ours to delete. Retain
                    # the exact entry as a private claim and expose the same
                    # inode at the canonical name as a durable busy blocker.
                    try:
                        replacement_payload, replacement_info = (
                            _read_private_lock_at(parent_fd, filename)
                        )
                        claim = _claim_private_lock_at(
                            parent_fd,
                            filename,
                            replacement_info,
                            replacement_payload,
                            "failed-create",
                            retain_claim=True,
                        )
                        assert claim is not None
                        try:
                            os.link(
                                claim,
                                filename,
                                src_dir_fd=parent_fd,
                                dst_dir_fd=parent_fd,
                                follow_symlinks=False,
                            )
                            os.fsync(parent_fd)
                        except FileExistsError:
                            pass
                    except (FileNotFoundError, OSError, AnalysisRunStateError):
                        pass
            os.close(parent_fd)
            raise


@dataclass(frozen=True)
class RunDecision:
    action: Literal["started", "recovered", "unchanged"]
    run_id: int
    run_key: str
    status: str
    transition_trace: tuple[str, ...]


class AnalysisRunRepository:
    """Short SQLite transactions over the existing Foundation `analysis_runs` table."""

    _REQUIRED_COLUMNS = frozenset({"id", "run_key", "subject_id", "analysis_kind", "target_start_local_date", "target_end_local_date", "status", "started_at_utc", "completed_at_utc"})

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._finish_capability: object | None = None
        self._verify_schema()

    def _verify_schema(self) -> None:
        rows = list(self._conn.execute("PRAGMA table_info(analysis_runs)"))
        columns = {row[1] for row in rows}
        if not self._REQUIRED_COLUMNS <= columns or "invocation_id" in columns:
            raise AnalysisRunStateError("analysis_runs_schema_incompatible")
        indexes = list(self._conn.execute("SELECT name FROM pragma_index_list(?) WHERE \"unique\"=1", ("analysis_runs",)))
        if not any([part[2] for part in self._conn.execute("SELECT seqno,cid,name FROM pragma_index_info(?) ORDER BY seqno", (row[0],))] == ["run_key"] for row in indexes):
            raise AnalysisRunStateError("analysis_runs_schema_incompatible")
        subject_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(data_subjects)")}
        if not {"id", "subject_key", "is_active"} <= subject_columns:
            raise AnalysisRunStateError("analysis_runs_schema_incompatible")

    def _subject_db_id(self, subject_key: str) -> int:
        row = self._conn.execute("SELECT id FROM data_subjects WHERE subject_key=? AND is_active=1", (subject_key,)).fetchone()
        if row is None:
            raise AnalysisRunStateError("analysis_subject_not_active")
        return int(row[0])

    def _existing_invocation_key(self, invocation_id: str) -> str | None:
        matches: list[str] = []
        for row in self._conn.execute("SELECT run_key FROM analysis_runs ORDER BY id"):
            run_key = str(row[0])
            if not run_key.startswith("analysis:"):
                # Foundation sample and pre-migration run history are immutable
                # compatibility evidence, not malformed Layer 3 run identities.
                continue
            try:
                if parse_analysis_run_key(run_key).invocation_id == invocation_id:
                    matches.append(str(row[0]))
            except AnalysisRunStateError as error:
                raise AnalysisRunStateError("analysis_runs_data_incompatible") from error
        if len(matches) > 1:
            raise AnalysisRunStateError("analysis_invocation_id_ambiguous")
        return matches[0] if matches else None

    def _validate_canonical_row(self, row: sqlite3.Row, *, request: AnalysisRequest | None = None) -> RunKey:
        """Fail closed when a canonical key disagrees with its persisted scope."""
        try:
            key = parse_analysis_run_key(str(row["run_key"]))
            subject = self._conn.execute("SELECT subject_key FROM data_subjects WHERE id=? AND is_active=1", (row["subject_id"],)).fetchone()
            if subject is None or str(subject[0]) != key.subject_key or row["analysis_kind"] != _KIND_BY_MODE[key.mode]: raise ValueError
            pieces = key.value.split(":")
            if key.mode == "daily":
                start_date = datetime.strptime(pieces[3], "%Y-%m-%d").date(); expected = (pieces[3], start_date.fromordinal(start_date.toordinal() + 1).isoformat())
            elif key.mode == "weekly": expected = (pieces[3], pieces[3])
            elif key.mode == "revise_plan":
                expected = (request.effective_local_date, request.effective_local_date) if request else (row["target_start_local_date"], row["target_start_local_date"])
                if not _DATE.fullmatch(str(row["target_start_local_date"])): raise ValueError
            else: expected = (None, None)
            if (row["target_start_local_date"], row["target_end_local_date"]) != expected: raise ValueError
            if row["status"] not in {"started", "succeeded", "failed", "rejected"} or not _valid_utc(row["started_at_utc"]): raise ValueError
            completed = row["completed_at_utc"]
            if row["status"] == "started" and completed is not None: raise ValueError
            if row["status"] != "started" and (not _valid_utc(completed) or str(completed) < str(row["started_at_utc"])): raise ValueError
            if request is not None and key.value != build_analysis_run_key(request).value: raise ValueError
            return key
        except (AnalysisRunStateError, ValueError, TypeError):
            raise AnalysisRunStateError("analysis_runs_data_incompatible") from None

    def preflight_succeeded(self, request: AnalysisRequest) -> RunDecision | None:
        """Read-only immutable-success fast path; never acquires a lock."""

        key = build_analysis_run_key(request)
        prior = self._existing_invocation_key(key.invocation_id)
        if prior is not None and prior != key.value: raise AnalysisRunStateError("analysis_invocation_id_reused")
        row = self._conn.execute("SELECT * FROM analysis_runs WHERE run_key=?", (key.value,)).fetchone()
        if row is None or row["status"] != "succeeded":
            return None
        self._validate_canonical_row(row, request=request)
        return RunDecision("unchanged", int(row["id"]), key.value, "succeeded", ("existing_succeeded",))

    @staticmethod
    def _targets(request: AnalysisRequest) -> tuple[str | None, str | None]:
        if request.mode == "daily": return request.summary_local_date, request.advice_local_date
        if request.mode == "weekly": return request.as_of_local_date, request.as_of_local_date
        if request.mode == "revise_plan": return request.effective_local_date, request.effective_local_date
        return None, None

    def prepare_write(self, request: AnalysisRequest) -> RunDecision:
        key = build_analysis_run_key(request)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            subject_id = self._subject_db_id(key.subject_key)
            prior_key = self._existing_invocation_key(key.invocation_id)
            if prior_key is not None and prior_key != key.value:
                raise AnalysisRunStateError("analysis_invocation_id_reused")
            row = self._conn.execute("SELECT * FROM analysis_runs WHERE run_key=?", (key.value,)).fetchone()
            if row is None:
                start, end = self._targets(request)
                self._conn.execute("INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,target_start_local_date,target_end_local_date,status,started_at_utc) VALUES(?,?,?,?,?,?,?)", (key.value, subject_id, _KIND_BY_MODE[key.mode], start, end, "started", _utc_now()))
                run_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                decision = RunDecision("started", run_id, key.value, "started", ("run_created",))
            elif row["status"] == "succeeded":
                self._validate_canonical_row(row, request=request)
                decision = RunDecision("unchanged", int(row["id"]), key.value, "succeeded", ("existing_succeeded",))
            elif row["status"] == "started":
                self._validate_canonical_row(row, request=request)
                artifacts = self._conn.execute("SELECT 1 FROM analysis_artifacts WHERE generated_by_run_id=? LIMIT 1", (row["id"],)).fetchone()
                trace = "existing_started_with_artifact" if artifacts else "existing_started_recovered"
                decision = RunDecision("unchanged" if artifacts else "recovered", int(row["id"]), key.value, "started", (trace,))
            else:
                raise AnalysisRunStateError("analysis_terminal_run_requires_new_invocation")
            self._conn.execute("COMMIT")
            return decision
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _bind_finish_capability(self, capability: object) -> None:
        if self._finish_capability is not None:
            raise AnalysisRunStateError("analysis_repository_already_bound")
        self._finish_capability = capability

    def _finish_authorized(self, run_id: int, expected_run_key: str, status: Literal["succeeded", "failed", "rejected"], capability: object) -> None:
        if capability is not self._finish_capability:
            raise AnalysisRunStateError("analysis_finish_unauthorized")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute("SELECT * FROM analysis_runs WHERE id=? AND run_key=?", (run_id, expected_run_key)).fetchone()
            if row is None:
                raise AnalysisRunStateError("analysis_run_transition_invalid")
            self._validate_canonical_row(row)
            if row["status"] != "started":
                raise AnalysisRunStateError("analysis_run_transition_invalid")
            updated = self._conn.execute("UPDATE analysis_runs SET status=?,completed_at_utc=? WHERE id=? AND run_key=? AND status='started'", (status, _utc_now(), run_id, expected_run_key)).rowcount
            if updated != 1:
                raise AnalysisRunStateError("analysis_run_transition_invalid")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def status(self, request: AnalysisRequest) -> RunDecision | None:
        """Pure read-only status: no lock, transaction, insert, or mutation."""

        request.validate()
        if request.mode != "status":
            raise AnalysisRunStateError("analysis_status_mode_required")
        self._subject_db_id(request.subject_id)
        if request.run_key is None:
            rows = self._conn.execute("SELECT r.* FROM analysis_runs r JOIN data_subjects s ON s.id=r.subject_id WHERE s.subject_key=? AND s.is_active=1 ORDER BY r.started_at_utc DESC,r.id DESC", (request.subject_id,))
            row = next((candidate for candidate in rows if str(candidate["run_key"]).startswith("analysis:")), None)
            if row is None: return None
            key = self._validate_canonical_row(row)
        else:
            key = parse_analysis_run_key(request.run_key)
            if key.subject_key != request.subject_id:
                raise AnalysisRunStateError("analysis_status_subject_mismatch")
            row = self._conn.execute("SELECT * FROM analysis_runs WHERE run_key=?", (key.value,)).fetchone()
        if row is None:
            return None
        self._validate_canonical_row(row)
        action: Literal["started", "recovered", "unchanged"] = "unchanged" if row["status"] == "succeeded" else "recovered"
        return RunDecision(action, int(row["id"]), key.value, str(row["status"]), ("status_read",))


@dataclass(frozen=True)
class PreparedAnalysisRun:
    """A write decision with the subject lock retained for a future publisher."""

    decision: RunDecision
    lock: SubjectLock | None

    def release(self) -> None:
        if self.lock is not None:
            self.lock.release()


class AnalysisRunCoordinator:
    """Compose the repository with a nonblocking subject write lock.

    Future generation/publication work must retain the returned lock until its
    final short publication transaction; `status` intentionally bypasses it.
    """

    def __init__(self, repository: AnalysisRunRepository, locks: SubjectLockManager) -> None:
        self._repository = repository
        self._locks = locks
        self._finish_capability = object()
        self._repository._bind_finish_capability(self._finish_capability)
        # Store object identity plus an immutable scope snapshot.  The public
        # DTO is intentionally simple, so this registry is the authority for
        # one-shot completion rather than caller-provided fields.
        self._prepared: dict[int, tuple[PreparedAnalysisRun, int, str, str, str, SubjectLock]] = {}

    def begin(self, request: AnalysisRequest) -> PreparedAnalysisRun:
        key = build_analysis_run_key(request)
        # Immutable completion is a read-only fast path.  It must not be held
        # hostage by another subject write lock; lock-time recheck below closes
        # the race for new/started runs.
        existing = self._repository.preflight_succeeded(request)
        if existing is not None:
            return PreparedAnalysisRun(decision=existing, lock=None)
        lock = self._locks.acquire(key.subject_key, key.value)
        try:
            decision = self._repository.prepare_write(request)
        except Exception:
            lock.release()
            raise
        if decision.action == "unchanged":
            lock.release()
            return PreparedAnalysisRun(decision=decision, lock=None)
        prepared = PreparedAnalysisRun(decision=decision, lock=lock)
        self._prepared[id(prepared)] = (prepared, decision.run_id, decision.run_key, decision.action, decision.status, lock)
        return prepared

    def status(self, request: AnalysisRequest) -> RunDecision | None:
        return self._repository.status(request)

    def abort(self, prepared: PreparedAnalysisRun) -> None:
        registered = self._prepared.pop(id(prepared), None)
        if registered is None or registered[0] is not prepared:
            raise AnalysisRunStateError("analysis_prepared_run_unauthorized")
        prepared.release()

    def finish(self, prepared: PreparedAnalysisRun, status: Literal["succeeded", "failed", "rejected"]) -> None:
        if status not in {"succeeded", "failed", "rejected"}:
            raise AnalysisRunStateError("analysis_finish_status_invalid")
        registered = self._prepared.get(id(prepared))
        if registered is None or registered[0] is not prepared:
            raise AnalysisRunStateError("analysis_prepared_run_unauthorized")
        _, run_id, run_key, action, prior_status, registered_lock = registered
        if (
            prepared.lock is not registered_lock
            or prepared.decision.run_id != run_id
            or prepared.decision.run_key != run_key
            or prepared.decision.action != action
            or prepared.decision.status != prior_status
            or prepared.lock is None
            or prepared.lock.released
            or action not in {"started", "recovered"}
            or prior_status != "started"
        ):
            raise AnalysisRunStateError("analysis_prepared_run_lock_required")
        key = parse_analysis_run_key(run_key)
        if prepared.lock.run_key != key.value or key.subject_key != _atom(key.subject_key, "subject"):
            raise AnalysisRunStateError("analysis_prepared_run_scope_mismatch")
        # Identity/scope failures above intentionally leave the capability in
        # the registry so the originating coordinator can abort it.  Once the
        # held lock is claimed, completion is one-shot and the fd is closed by
        # claim/finalize on every path.
        self._prepared.pop(id(prepared), None)
        claim = prepared.lock.claim_for_finish()
        try:
            self._repository._finish_authorized(run_id, key.value, status, self._finish_capability)
        except Exception:
            try:
                prepared.lock.finalize_finish_claim(claim, committed=False)
            except AnalysisRunStateError:
                pass
            raise
        try:
            prepared.lock.finalize_finish_claim(claim, committed=True)
        except AnalysisRunStateError as error:
            raise AnalysisRunStateError("analysis_finish_cleanup_required") from error
