"""S5-14 bounded, read-only health probes for the Layer-5 workflow.

The adapter owns no scheduler and never repairs, migrates, synchronizes, or
opens a lower-layer write path.  It reads only Foundation operational metadata
and filesystem metadata, then delegates the bounded persistence/incident work
to :class:`HealthMonitor`.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from .application import HealthWorkflowOutcome
from .contracts import WorkflowRequest
from .health_monitor import HealthMonitor, HealthObservation


_SINGAPORE = ZoneInfo("Asia/Singapore")
_EXPECTED_TABLES = frozenset({
    "foundation_state", "garmin_sync_cursors", "garmin_sync_gaps",
    "analysis_deliveries", "mail_messages", "mail_poll_cursors",
    "scheduler_leases",
})
_BACKLOG_STATES = (
    "queued", "analyzing", "awaiting_analysis", "response_accepted",
    "ready_to_send", "sending", "deferred", "delivery_unknown", "failed",
)


class HealthWorkflowError(ValueError):
    """The fixed health-probe environment is invalid."""


class HealthRepository(Protocol):
    def record_health_check(self, **values: object) -> object: ...
    def latest_health_check_at(self, **values: object) -> datetime | None: ...
    def record_incident(self, **values: object) -> object: ...
    def get_incident(self, incident_key: str) -> object: ...
    def transition_incident(self, incident_key: str, state: str, *, at_utc: datetime) -> object: ...


class HealthAlertService(Protocol):
    def deliver(self, incident_key: str, *, event: str = "open") -> object: ...


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    """Fixed operational thresholds; all metrics remain data-free."""

    minimum_free_percent: int = 10
    minimum_free_inode_percent: int = 10
    maximum_cursor_lag_days: int = 2
    maximum_open_gaps: int = 0
    maximum_delivery_attention: int = 0
    maximum_mail_backlog: int = 0
    sqlite_deep_check_interval_seconds: int = 86_400

    def __post_init__(self) -> None:
        for value in (
            self.minimum_free_percent, self.minimum_free_inode_percent,
            self.maximum_cursor_lag_days, self.maximum_open_gaps,
            self.maximum_delivery_attention, self.maximum_mail_backlog,
            self.sqlite_deep_check_interval_seconds,
        ):
            if type(value) is not int or not 0 <= value <= 100_000_000:
                raise HealthWorkflowError("health_threshold_invalid")
        if self.sqlite_deep_check_interval_seconds < 60:
            raise HealthWorkflowError("health_threshold_invalid")


class HealthWorkflow:
    """Execute the fixed S5-14 probe catalog once.

    Paths are injected by the composition root and are never accepted from a
    ``WorkflowRequest`` or CLI flag.  SQLite is opened in ``mode=ro`` and all
    probe results are counts, timestamps, booleans, or capacity metadata.
    """

    def __init__(
        self,
        *,
        database_path: Path,
        state_directory: Path,
        log_directory: Path,
        repository: HealthRepository,
        clock: Callable[[], datetime],
        storage_directory: Path | None = None,
        thresholds: HealthThresholds | None = None,
        alert_service: HealthAlertService | None = None,
    ) -> None:
        if repository is None or not callable(clock):
            raise HealthWorkflowError("health_dependency_required")
        self._database = Path(database_path)
        self._state_directory = Path(state_directory)
        self._log_directory = Path(log_directory)
        self._storage_directory = Path(storage_directory) if storage_directory is not None else self._database.parent
        self._repository = repository
        self._clock = clock
        self._thresholds = thresholds or HealthThresholds()
        self._alerts = alert_service

    def execute(self, request: WorkflowRequest) -> HealthWorkflowOutcome:
        if type(request) is not WorkflowRequest or request.workflow_kind != "health_check":
            return HealthWorkflowOutcome("failed", "operator_review", errors=(_error("health_request_invalid"),))
        try:
            now = _utc(self._clock())
        except Exception:
            return HealthWorkflowOutcome("failed", "operator_review", errors=(_error("health_clock_invalid"),))

        observations = self._collect(now)
        try:
            summary = HealthMonitor(self._repository).record(observations, checked_at_utc=now)
        except Exception:
            return HealthWorkflowOutcome("failed", "operator_review", errors=(_error("health_persistence_unavailable"),))
        self._deliver_alerts(
            summary.incident_keys, summary.recovered_incident_keys
        )

        warnings = tuple(_warning(item) for item in observations if item.status == "warning")
        errors = tuple(_error(f"health_{item.check_kind}_{item.target_kind}") for item in observations if item.status in {"critical", "unavailable"})
        if summary.status == "ready":
            return HealthWorkflowOutcome("succeeded", "none", incident_ids=summary.incident_keys)
        if summary.status == "warning":
            return HealthWorkflowOutcome("partial", "review_health", incident_ids=summary.incident_keys, warnings=warnings)
        return HealthWorkflowOutcome("attention_required", "operator_review", incident_ids=summary.incident_keys, warnings=warnings, errors=errors)

    def _deliver_alerts(
        self,
        active: tuple[str, ...],
        recovered: tuple[str, ...],
    ) -> None:
        if self._alerts is None:
            return
        for incident_key in active:
            try:
                self._alerts.deliver(incident_key, event="open")
            except Exception:
                # The incident is already durable. Gmail failure must never
                # turn the health probe into a recursive alert storm.
                continue
        for incident_key in recovered:
            try:
                self._alerts.deliver(incident_key, event="recovery")
            except Exception:
                continue

    def _collect(self, now: datetime) -> tuple[HealthObservation, ...]:
        connection: sqlite3.Connection | None = None
        try:
            connection = _readonly_connection(self._database)
            tables = _tables(connection)
            observations = [
                self._foundation(connection, tables),
                self._sqlite_readiness(connection),
            ]
            if self._sqlite_deep_check_due(now):
                observations.append(self._sqlite_integrity(connection))
            if _EXPECTED_TABLES.issubset(tables):
                observations.extend((
                    self._garmin(connection, now),
                    self._analysis(connection),
                    self._mail(connection, now),
                    self._supervisor(connection, now),
                ))
            else:
                for kind, target in (("garmin", "cursor"), ("analysis", "delivery"), ("mail", "backlog"), ("supervisor", "lease")):
                    observations.append(HealthObservation(kind, target, "unavailable", {"schema_available": False}))
        except Exception:
            observations = [
                HealthObservation("foundation", "schema", "unavailable", {"database_available": False}),
                HealthObservation("sqlite", "readiness", "unavailable", {"database_available": False}),
                HealthObservation("garmin", "cursor", "unavailable", {"database_available": False}),
                HealthObservation("analysis", "delivery", "unavailable", {"database_available": False}),
                HealthObservation("mail", "backlog", "unavailable", {"database_available": False}),
                HealthObservation("supervisor", "lease", "unavailable", {"database_available": False}),
            ]
        finally:
            if connection is not None:
                connection.close()
        observations.extend((self._disk(), self._logs(now)))
        return tuple(observations)

    def _foundation(self, conn: sqlite3.Connection, tables: frozenset[str]) -> HealthObservation:
        if not _EXPECTED_TABLES.issubset(tables):
            return HealthObservation("foundation", "schema", "critical", {"expected_table_count": len(_EXPECTED_TABLES), "present_table_count": len(_EXPECTED_TABLES & tables)})
        row = conn.execute("SELECT state,schema_version FROM foundation_state WHERE id=1").fetchone()
        if row is None:
            return HealthObservation("foundation", "schema", "critical", {"state_row_present": False})
        marker_present = (self._state_directory / "foundation-ready.json").is_file()
        ready = row[0] == "ready" and type(row[1]) is int and row[1] >= 1 and marker_present
        return HealthObservation("foundation", "schema", "ready" if ready else "critical", {"ready": ready, "schema_version": int(row[1]) if type(row[1]) is int else 0, "ready_marker_present": marker_present})

    def _sqlite_readiness(self, conn: sqlite3.Connection) -> HealthObservation:
        readable = conn.execute("SELECT 1").fetchone() == (1,)
        journal = conn.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(journal[0]).lower() if journal else "unknown"
        wal = self._database.with_name(f"{self._database.name}-wal")
        ready = readable and journal_mode == "wal"
        return HealthObservation(
            "sqlite",
            "readiness",
            "ready" if ready else "critical",
            {
                "database_readable": readable,
                "journal_mode_wal": journal_mode == "wal",
                "wal_present": wal.is_file(),
            },
        )

    def _sqlite_deep_check_due(self, now: datetime) -> bool:
        latest = self._repository.latest_health_check_at(
            check_kind="sqlite", target_kind="integrity", target_id=None
        )
        if latest is None or latest > now:
            return True
        elapsed = (now - latest).total_seconds()
        return elapsed >= self._thresholds.sqlite_deep_check_interval_seconds

    @staticmethod
    def _sqlite_integrity(conn: sqlite3.Connection) -> HealthObservation:
        try:
            integrity = conn.execute("PRAGMA integrity_check(1)").fetchone()
            foreign_key = conn.execute("PRAGMA foreign_key_check").fetchone()
        except sqlite3.DatabaseError:
            return HealthObservation(
                "sqlite",
                "integrity",
                "unavailable",
                {"integrity_available": False},
                threshold_version="health-v2",
            )
        integrity_ok = integrity is not None and tuple(integrity) == ("ok",)
        foreign_key_ok = foreign_key is None
        return HealthObservation(
            "sqlite",
            "integrity",
            "ready" if integrity_ok and foreign_key_ok else "critical",
            {
                "integrity_ok": integrity_ok,
                "foreign_key_ok": foreign_key_ok,
            },
            threshold_version="health-v2",
        )

    def _disk(self) -> HealthObservation:
        try:
            status = os.statvfs(self._storage_directory)
            free_percent = _percent(status.f_bavail, status.f_blocks)
            inode_percent = _percent(status.f_favail, status.f_files)
            state = "ready" if free_percent >= self._thresholds.minimum_free_percent and inode_percent >= self._thresholds.minimum_free_inode_percent else "critical"
            return HealthObservation("disk", "capacity", state, {"free_percent": free_percent, "free_inode_percent": inode_percent})
        except OSError:
            return HealthObservation("disk", "capacity", "unavailable", {"storage_available": False})

    def _garmin(self, conn: sqlite3.Connection, now: datetime) -> HealthObservation:
        cursor_count, latest = conn.execute("SELECT COUNT(*),MAX(complete_through_local_date) FROM garmin_sync_cursors").fetchone()
        gaps = int(conn.execute("SELECT COUNT(*) FROM garmin_sync_gaps WHERE status IN ('open','deferred')").fetchone()[0])
        lag = _lag_days(latest, now)
        state = "warning" if int(cursor_count) == 0 or gaps > self._thresholds.maximum_open_gaps or lag is None or lag > self._thresholds.maximum_cursor_lag_days else "ready"
        return HealthObservation("garmin", "cursor", state, {"cursor_count": int(cursor_count), "open_gaps": gaps, "lag_days": lag})

    def _analysis(self, conn: sqlite3.Connection) -> HealthObservation:
        total = int(conn.execute("SELECT COUNT(*) FROM analysis_deliveries WHERE status IN ('pending','sending','delivery_unknown','failed')").fetchone()[0])
        state = "warning" if total > self._thresholds.maximum_delivery_attention else "ready"
        return HealthObservation("analysis", "delivery", state, {"attention_count": total})

    def _mail(self, conn: sqlite3.Connection, now: datetime) -> HealthObservation:
        placeholders = ",".join("?" for _ in _BACKLOG_STATES)
        backlog = int(conn.execute(f"SELECT COUNT(*) FROM mail_messages WHERE processing_state IN ({placeholders})", _BACKLOG_STATES).fetchone()[0])
        cursor_count, latest = conn.execute("SELECT COUNT(*),MAX(observed_through_utc) FROM mail_poll_cursors").fetchone()
        cursor_age = _age_seconds(latest, now)
        state = "warning" if backlog > self._thresholds.maximum_mail_backlog or int(cursor_count) == 0 else "ready"
        return HealthObservation("mail", "backlog", state, {"pending_count": backlog, "cursor_count": int(cursor_count), "cursor_age_seconds": cursor_age})

    @staticmethod
    def _supervisor(conn: sqlite3.Connection, now: datetime) -> HealthObservation:
        row = conn.execute("SELECT heartbeat_at_utc,expires_at_utc FROM scheduler_leases WHERE lease_key='supervisor'").fetchone()
        if row is None:
            return HealthObservation("supervisor", "lease", "warning", {"lease_present": False})
        heartbeat_age = _age_seconds(row[0], now)
        active = _future(row[1], now)
        return HealthObservation("supervisor", "lease", "ready" if active else "warning", {"lease_present": True, "lease_active": active, "heartbeat_age_seconds": heartbeat_age})

    def _logs(self, now: datetime) -> HealthObservation:
        try:
            entries = list(self._log_directory.iterdir())
            newest = max((entry.stat().st_mtime for entry in entries if entry.is_file()), default=None)
            age = None if newest is None else max(0, int(now.timestamp() - newest))
            return HealthObservation("logs", "directory", "ready", {"directory_present": True, "file_count": len(entries), "newest_age_seconds": age})
        except OSError:
            return HealthObservation("logs", "directory", "unavailable", {"directory_present": False})


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise HealthWorkflowError("health_database_missing")
    return sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)


def _tables(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HealthWorkflowError("health_clock_invalid")
    return value.astimezone(UTC)


def _percent(numerator: int, denominator: int) -> int:
    return 0 if denominator <= 0 else int(numerator * 100 / denominator)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed.astimezone(UTC)


def _age_seconds(value: object, now: datetime) -> int | None:
    parsed = _parse_utc(value)
    return None if parsed is None else max(0, int((now - parsed).total_seconds()))


def _future(value: object, now: datetime) -> bool:
    parsed = _parse_utc(value)
    return parsed is not None and parsed > now


def _lag_days(value: object, now: datetime) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        cursor = date.fromisoformat(value)
    except ValueError:
        return None
    return max(0, (now.astimezone(_SINGAPORE).date() - cursor).days)


def _warning(item: HealthObservation) -> dict[str, str]:
    return {"code": f"health_{item.check_kind}_{item.target_kind}", "summary": "health check needs review"}


def _error(code: str) -> dict[str, str]:
    return {"code": code, "summary": "health check requires operator review"}
