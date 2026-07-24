"""S5-04: database-authoritative Supervisor lease and finite lifecycle.

This module deliberately has no scheduler loop, executor, provider call, or
background thread.  A future unit may drive ``Supervisor.heartbeat``; this
unit only makes ownership safe and observable.
"""
from __future__ import annotations

import os
import re
import stat
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

from .repository import OrchestrationRepository, OrchestrationRepositoryError


_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class LeaseError(OrchestrationRepositoryError):
    """A controlled lease/lifecycle failure with no provider detail."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class ProcessProbe(Protocol):
    """Return true only after positively establishing that PID is absent."""

    def is_absent(self, pid: int) -> bool: ...


@dataclass(frozen=True)
class LeaseResult:
    state: str  # active | passive | stopped
    owner_instance_id: str | None
    expires_at_utc: str | None
    cleanup_status: str = "not_applicable"  # deleted | retained | not_applicable


@dataclass(frozen=True)
class _ClaimToken:
    record_id: int
    owner_instance_id: str
    owner_pid: int
    acquired_at_utc: str
    heartbeat_at_utc: str
    expires_at_utc: str


@dataclass(frozen=True)
class _LockEvidence:
    device: int
    inode: int
    uid: int
    mode: int
    nonce_sha256: str


class LeaseManager:
    """Own the one ``scheduler_leases/supervisor`` record by CAS.

    The optional local file is *only* a permission-checked diagnostic marker.
    It never decides ownership, and a process never deletes a marker it did not
    create.  Database expiry plus a positive old-PID-absent result are both
    required for takeover.
    """

    _KEY = "supervisor"

    def __init__(
        self,
        database_path: Path,
        lock_path: Path,
        instance_id: str,
        pid: int,
        clock: Clock,
        probe: ProcessProbe,
        ttl_seconds: int = 90,
    ) -> None:
        if not isinstance(instance_id, str) or not _IDENTITY.fullmatch(instance_id):
            raise LeaseError("lease_instance_id_invalid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise LeaseError("lease_pid_invalid")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise LeaseError("lease_ttl_invalid")
        self.db = Path(database_path)
        self.repository = OrchestrationRepository(self.db)
        self.lock = Path(lock_path)
        self.instance = instance_id
        self.pid = pid
        self.clock = clock
        self.probe = probe
        self.ttl = ttl_seconds
        self._owns_lock = False
        self._evidence: _LockEvidence | None = None
        self._claim: _ClaimToken | None = None

    def acquire(self) -> LeaseResult:
        now = _utc(self.clock.now())
        expiry = now + timedelta(seconds=self.ttl)
        # Existing unknown markers are never modified, but must be safe before
        # a DB claim is attempted.  This keeps an unsafe final object at zero
        # database writes.
        self._preflight_existing_evidence()
        try:
            with self._tx() as conn:
                row = conn.execute(
                    "SELECT id,owner_instance_id,owner_pid,acquired_at_utc,heartbeat_at_utc,expires_at_utc "
                    "FROM scheduler_leases WHERE lease_key=?",
                    (self._KEY,),
                ).fetchone()
                if row is None:
                    acquired = _text(now)
                    heartbeat = acquired
                    expires = _text(expiry)
                    cursor = conn.execute(
                        "INSERT INTO scheduler_leases "
                        "(lease_key,owner_instance_id,owner_pid,acquired_at_utc,heartbeat_at_utc,expires_at_utc) "
                        "VALUES (?,?,?,?,?,?)",
                        (self._KEY, self.instance, self.pid, acquired, heartbeat, expires),
                    )
                    self._claim = _ClaimToken(cursor.lastrowid, self.instance, self.pid, acquired, heartbeat, expires)
                    result = self._active(expiry)
                else:
                    record_id, owner, owner_pid, acquired_text, heartbeat_text, expiry_text = row
                    _validate_lease_row(record_id, owner, owner_pid, acquired_text, heartbeat_text, expiry_text)
                    heartbeat = _parse(heartbeat_text)
                    old_expiry = _parse(expiry_text)
                    # A clock behind an accepted heartbeat, or an expiry implausibly
                    # far forward, is unsafe.  Do not silently shorten/take it over.
                    if now < heartbeat or old_expiry > now + timedelta(seconds=self.ttl * 2):
                        raise LeaseError("lease_clock_anomaly")
                    # Same owner/PID is not sufficient: a new manager is a distinct
                    # lifecycle and must never inherit an unexpired generation.
                    if self._claim is not None:
                        result = self._heartbeat_in_transaction(conn, now, expiry)
                    # Equality is intentionally still live.  The successor must wait
                    # for a strictly expired record, avoiding boundary split brain.
                    elif old_expiry >= now:
                        result = LeaseResult("passive", owner, expiry_text)
                    else:
                        try:
                            absent = self.probe.is_absent(int(owner_pid))
                        except Exception:
                            absent = False
                        if absent is not True:  # present, PID reuse, permission uncertainty
                            result = LeaseResult("passive", owner, expiry_text)
                        else:
                            acquired = _text(now)
                            heartbeat_new = acquired
                            expires = _text(expiry)
                            changed = conn.execute(
                                "UPDATE scheduler_leases SET owner_instance_id=?,owner_pid=?,acquired_at_utc=?,"
                                "heartbeat_at_utc=?,expires_at_utc=? WHERE id=? AND owner_instance_id=? "
                                "AND owner_pid=? AND acquired_at_utc=? AND heartbeat_at_utc=? AND expires_at_utc<?",
                                (self.instance, self.pid, acquired, heartbeat_new, expires, record_id, owner,
                                 owner_pid, acquired_text, heartbeat_text, _text(now)),
                            ).rowcount
                            if changed == 1:
                                # Atomic, bounded takeover audit.  It is intentionally a
                                # health-check row rather than a business incident: only a
                                # generation number/PID and time are retained, never data
                                # or provider payload.  Any failure rolls back the CAS too.
                                conn.execute(
                                    "INSERT INTO service_health_checks "
                                    "(check_kind,target_kind,target_id,status,metrics_json,threshold_version,checked_at_utc) "
                                    "VALUES (?,?,?,?,?,?,?)",
                                    ("lease_takeover", "supervisor", str(record_id), "succeeded",
                                     _takeover_metrics(record_id, owner, owner_pid, acquired_text, heartbeat_text, expiry_text),
                                     "s5_04", _text(now)),
                                )
                                self._claim = _ClaimToken(record_id, self.instance, self.pid, acquired, heartbeat_new, expires)
                                result = self._active(expiry)
                            else:
                                result = LeaseResult("passive", None, None)
        except LeaseError:
            self._release_evidence()
            raise
        except Exception as exc:
            self._release_evidence()
            raise LeaseError("lease_database_unavailable") from exc
        if result.state == "active":
            try:
                self._evidence_lock()
            except Exception as exc:
                try:
                    self.release()
                except Exception as cleanup_exc:
                    raise LeaseError("lease_evidence_compensation_failed") from cleanup_exc
                raise LeaseError("lease_evidence_unavailable") from exc
        return result

    def heartbeat(self) -> LeaseResult:
        if self._claim is None:
            return LeaseResult("passive", None, None)
        now = _utc(self.clock.now())
        expiry = now + timedelta(seconds=self.ttl)
        try:
            with self._tx() as conn:
                return self._heartbeat_in_transaction(conn, now, expiry)
        except LeaseError:
            raise
        except Exception as exc:
            raise LeaseError("lease_database_unavailable") from exc

    def release(self) -> LeaseResult:
        error: Exception | None = None
        try:
            with self._tx() as conn:
                token = self._claim
                if token is not None:
                    changed = conn.execute(
                        "DELETE FROM scheduler_leases WHERE lease_key=? AND id=? AND owner_instance_id=? AND owner_pid=? "
                        "AND acquired_at_utc=? AND heartbeat_at_utc=? AND expires_at_utc=?",
                        (self._KEY, token.record_id, token.owner_instance_id, token.owner_pid,
                         token.acquired_at_utc, token.heartbeat_at_utc, token.expires_at_utc),
                    )
                    if changed.rowcount != 1:
                        raise LeaseError("lease_ownership_lost")
                self._claim = None
        except LeaseError:
            raise
        except Exception as exc:
            error = LeaseError("lease_database_unavailable")
            error.__cause__ = exc
        finally:
            cleanup = self._release_evidence()
        if error:
            raise error
        return LeaseResult("stopped", None, None, cleanup)

    def _heartbeat_in_transaction(self, conn, now: datetime, expiry: datetime) -> LeaseResult:
        token = self._claim
        if token is None:
            return LeaseResult("passive", None, None)
        prior_heartbeat, prior_expiry = _parse(token.heartbeat_at_utc), _parse(token.expires_at_utc)
        if now < prior_heartbeat or prior_expiry > now + timedelta(seconds=self.ttl * 2):
            raise LeaseError("lease_clock_anomaly")
        if prior_expiry < now:
            return LeaseResult("passive", None, None)
        heartbeat_new, expires_new = _text(now), _text(expiry)
        changed = conn.execute(
            "UPDATE scheduler_leases SET heartbeat_at_utc=?,expires_at_utc=? WHERE lease_key=? AND id=? "
            "AND owner_instance_id=? AND owner_pid=? AND acquired_at_utc=? AND heartbeat_at_utc=? "
            "AND expires_at_utc>=? AND expires_at_utc=?",
            (heartbeat_new, expires_new, self._KEY, token.record_id, token.owner_instance_id, token.owner_pid,
             token.acquired_at_utc, token.heartbeat_at_utc, _text(now), token.expires_at_utc),
        ).rowcount
        if changed != 1:
            self._claim = None
            return LeaseResult("passive", None, None)
        self._claim = _ClaimToken(token.record_id, token.owner_instance_id, token.owner_pid,
                                  token.acquired_at_utc, heartbeat_new, expires_new)
        return self._active(expiry)

    def _active(self, expiry: datetime) -> LeaseResult:
        return LeaseResult("active", self.instance, _text(expiry))

    def _tx(self):
        # The S5-03 repository validates the Foundation manifest before every
        # lease transaction.  This is intentionally not a bare sqlite connect.
        return self.repository._transaction()

    def _evidence_lock(self) -> None:
        if self._owns_lock:
            return
        parent = self.lock.parent
        # Foundation owns directory creation.  Never mkdir through an attacker
        # supplied ancestor; require the final lock directory to already exist.
        self._safe_parent(parent)
        try:
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            nonce = secrets.token_bytes(32)
            try:
                fd = os.open(self.lock.name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                try:
                    offset = 0
                    while offset < len(nonce):
                        count = os.write(fd, nonce[offset:])
                        if not isinstance(count, int) or count <= 0:
                            raise LeaseError("lease_evidence_write_failed")
                        offset += count
                    os.fsync(fd)
                    info = os.fstat(fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != len(nonce)):
                        raise LeaseError("lease_evidence_write_failed")
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.read(fd, len(nonce)) != nonce:
                        raise LeaseError("lease_evidence_write_failed")
                finally:
                    os.close(fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            self._evidence = _LockEvidence(info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode), hashlib.sha256(nonce).hexdigest())
            self._owns_lock = True
        except FileExistsError:
            # Existing evidence may belong to a crashed/other process.  Never
            # follow, modify, or remove it; DB CAS remains authoritative.
            self._preflight_existing_evidence()
        except OSError as exc:
            raise LeaseError("lease_evidence_unavailable") from exc

    def _preflight_existing_evidence(self) -> None:
        """Allow only a harmless bounded owner-only regular unknown marker."""
        self._safe_parent(self.lock.parent)
        try:
            parent_fd = os.open(self.lock.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise LeaseError("lease_lock_path_unsafe") from exc
        try:
            try:
                before = os.stat(self.lock.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 4096):
                raise LeaseError("lease_existing_marker_unsafe")
            try:
                fd = os.open(self.lock.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            except OSError as exc:
                raise LeaseError("lease_existing_marker_unsafe") from exc
            try:
                opened = os.fstat(fd)
                # Read validates bounded regular content without interpreting it.
                os.read(fd, 4097)
            finally:
                os.close(fd)
            after = os.stat(self.lock.name, dir_fd=parent_fd, follow_symlinks=False)
            fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode), value.st_size)
            if fingerprint(before) != fingerprint(opened) or fingerprint(before) != fingerprint(after):
                raise LeaseError("lease_existing_marker_unsafe")
        except (OSError, ValueError) as exc:
            if isinstance(exc, LeaseError): raise
            raise LeaseError("lease_existing_marker_unsafe") from exc
        finally:
            os.close(parent_fd)

    def _release_evidence(self) -> str:
        evidence = self._evidence
        if not self._owns_lock or evidence is None:
            return "not_applicable"
        cleanup = "retained"
        try:
            self._safe_parent(self.lock.parent)
            parent_fd = os.open(self.lock.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                before = os.stat(self.lock.name, dir_fd=parent_fd, follow_symlinks=False)
                fd = os.open(self.lock.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    opened = os.fstat(fd)
                    content = os.read(fd, 128)
                finally:
                    os.close(fd)
                after = os.stat(self.lock.name, dir_fd=parent_fd, follow_symlinks=False)
                expected = (evidence.device, evidence.inode, evidence.uid, evidence.mode)
                identities = tuple((item.st_dev, item.st_ino, item.st_uid, stat.S_IMODE(item.st_mode)) for item in (before, opened, after))
                # POSIX exposes no portable unlink-by-verified-fd primitive for
                # regular files: a name can be replaced between this check and
                # unlink.  Diagnostic evidence is never worth deleting an
                # unknown file, so even a perfect match is retained.  DB lease
                # ownership is the sole authority.
                _ = identities == (expected, expected, expected) and hashlib.sha256(content).hexdigest() == evidence.nonce_sha256
            finally:
                os.close(parent_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        finally:
            self._owns_lock = False
            self._evidence = None
        return cleanup

    def _safe_parent(self, parent: Path) -> None:
        """Validate every existing component below the configured DB root.

        Deployment supplies ``database_path`` as an already-resolved trusted
        root.  We intentionally do not make claims about system ancestors such
        as ``/Volumes``; every component from that root to the lock directory is
        required to be a real owner-only directory.
        """
        root = Path(os.path.abspath(self.db.parent))
        candidate = Path(os.path.abspath(parent))
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise LeaseError("lease_lock_path_unsafe") from exc
        current = root
        for component in (Path("."), *relative.parts):
            if component != Path("."):
                current /= component
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise LeaseError("lease_lock_path_unsafe") from exc
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise LeaseError("lease_lock_path_unsafe")


class Supervisor:
    """Finite lifecycle shell; it never starts a workflow in S5-04."""

    def __init__(self, lease: LeaseManager, executor_stop: Callable[[], None] = lambda: None) -> None:
        self.lease = lease
        self.executor_stop = executor_stop
        self.state = "new"
        self.stop_requested = False

    def start(self) -> LeaseResult:
        if self.state != "new":
            raise LeaseError("supervisor_start_invalid")
        result = self.lease.acquire()
        self.state = "active" if result.state == "active" else "passive"
        return result

    def heartbeat(self) -> LeaseResult:
        if self.state != "active" or self.stop_requested:
            return LeaseResult("passive", None, None)
        result = self.lease.heartbeat()
        if result.state != "active":
            self.state = "passive"
        return result

    def request_stop(self, signum: int | None = None) -> None:
        # Deliberately side-effect free and idempotent so a signal handler can
        # call it; actual cleanup occurs at the next safe lifecycle boundary.
        self.stop_requested = True
        if self.state == "active":
            self.state = "stopping"

    def stop(self) -> LeaseResult:
        if self.state == "stopped":
            return LeaseResult("stopped", None, None)
        self.stop_requested = True
        self.state = "stopping"
        executor_error: Exception | None = None
        try:
            self.executor_stop()
        except Exception as exc:
            executor_error = exc
        try:
            released = self.lease.release()
        finally:
            self.state = "stopped"
        if executor_error is not None:
            raise LeaseError("supervisor_executor_cleanup_failed") from executor_error
        return released


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeaseError("lease_clock_invalid")
    return value.astimezone(UTC)


def _text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse(value: object) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise LeaseError("lease_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise LeaseError("lease_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise LeaseError("lease_timestamp_invalid")
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if canonical != value:
        raise LeaseError("lease_timestamp_invalid")
    return parsed.astimezone(UTC)


def _takeover_metrics(record_id: int, owner: str, pid: int, acquired: str, heartbeat: str, expiry: str) -> str:
    """Bounded, non-reversible predecessor-generation audit evidence."""
    source = f"{record_id}\0{owner}\0{pid}\0{acquired}\0{heartbeat}\0{expiry}".encode("utf-8")
    return '{"previous_claim_sha256":"%s"}' % hashlib.sha256(source).hexdigest()


def _validate_lease_row(record_id: object, owner: object, pid: object, acquired: object, heartbeat: object, expiry: object) -> None:
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
        raise LeaseError("lease_row_invalid")
    if not isinstance(owner, str) or not _IDENTITY.fullmatch(owner) or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise LeaseError("lease_row_invalid")
    a, h, e = _parse(acquired), _parse(heartbeat), _parse(expiry)
    if not a <= h <= e:
        raise LeaseError("lease_row_invalid")
