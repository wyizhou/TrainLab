"""Owner-only static scheduling configuration and pure job projections for S5-02.

No database, command construction, network call, or scheduler loop exists here.
S5-03 will persist projections; later units decide due-queue and misfire execution.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol
from zoneinfo import ZoneInfo

import yaml
from jsonschema import Draft202012Validator


HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_SECRET_MARKERS = ("secret", "token", "password", "credential", "oauth", "client_id", "client_secret")


class OrchestrationConfigError(RuntimeError):
    """A static configuration candidate cannot safely become active."""


class UtcClock(Protocol):
    """Injectable time source; production wall-clock access belongs to a later Supervisor."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class ConfigurationIncidentEvidence:
    """Data-free evidence for the future incident repository in S5-03."""

    category: Literal["orchestrator_configuration_invalid"]
    error_code: str
    config_path: str
    previous_config_sha256: str | None


@dataclass(frozen=True)
class OrchestrationConfigSnapshot:
    timezone: str
    morning_time: str
    weekly_day: str
    mail_poll_interval_seconds: int
    health_check_interval_seconds: int
    workflow_deadline_seconds: int
    max_parallel_read_checks: int
    lease_ttl_seconds: int
    heartbeat_interval_seconds: int
    daily_misfire_window_hours: int
    weekly_misfire_window_hours: int
    state_lock_path: Path
    temp_root: Path
    log_root: Path
    operational_alerts_enabled: bool
    config_sha256: str


@dataclass(frozen=True)
class ConfigReloadResult:
    applied: bool
    snapshot: OrchestrationConfigSnapshot | None
    incident: ConfigurationIncidentEvidence | None


@dataclass(frozen=True)
class SchedulerJobProjection:
    """Immutable DTO only; S5-02 intentionally does not write ``scheduler_jobs``."""

    job_key: Literal["morning", "weekly", "mail_poll", "health_check"]
    workflow_kind: Literal["morning", "weekly", "mail", "health_check"]
    timezone: str
    schedule_kind: Literal["daily_at", "weekly_at", "interval"]
    next_due_at_utc: datetime
    logical_local_date: str | None
    interval_seconds: int | None
    depends_on_job_key: str | None
    collection_strategy: Literal["own_incremental", "reuse_morning_collection", "none"]
    misfire_window: timedelta | None
    config_sha256: str


class OrchestrationConfigLoader:
    """Read an owner-only YAML file into an immutable, fully validated snapshot."""

    def __init__(self, project_root: Path, *, schema_path: Path | None = None) -> None:
        self._root = project_root.resolve()
        path = schema_path or Path(__file__).resolve().parents[3] / "harness" / "schemas" / "orchestration_config.schema.json"
        self._validator = Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))

    def load(self, config_path: Path) -> OrchestrationConfigSnapshot:
        path = self._validated_config_path(config_path)
        try:
            payload = yaml.safe_load(self._read_stable_config(path))
        except Exception as exc:
            raise OrchestrationConfigError("orchestrator_config_unreadable") from exc
        errors = list(self._validator.iter_errors(payload))
        if errors:
            raise OrchestrationConfigError("orchestrator_config_schema_invalid")
        _reject_secrets(payload)
        values = payload["orchestrator"]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return OrchestrationConfigSnapshot(
            timezone=values["timezone"], morning_time=values["morning_time"], weekly_day=values["weekly_day"],
            mail_poll_interval_seconds=values["mail_poll_interval_seconds"], health_check_interval_seconds=values["health_check_interval_seconds"],
            workflow_deadline_seconds=values["workflow_deadline_seconds"], max_parallel_read_checks=values["max_parallel_read_checks"],
            lease_ttl_seconds=values["lease_ttl_seconds"], heartbeat_interval_seconds=values["heartbeat_interval_seconds"],
            daily_misfire_window_hours=values["daily_misfire_window_hours"], weekly_misfire_window_hours=values["weekly_misfire_window_hours"],
            state_lock_path=self._safe_child(values["state_lock_path"]), temp_root=self._safe_child(values["temp_root"]),
            log_root=self._safe_child(values["log_root"]), operational_alerts_enabled=values["operational_alerts_enabled"],
            config_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def _validated_config_path(self, value: Path) -> Path:
        raw = self._root / value if not value.is_absolute() else Path(os.path.abspath(value))
        try:
            raw.relative_to(self._root)
        except ValueError as exc:
            raise OrchestrationConfigError("orchestrator_config_path_escape") from exc
        # ``self._root`` is normalized once at construction, so callers may pass
        # a deployer-selected root alias.  From that resolved root onward every
        # existing raw component is checked with lstat *before* resolve().
        self._reject_existing_relative_symlinks(raw)
        path = raw.resolve(strict=True)
        if path != self._root and self._root not in path.parents:
            raise OrchestrationConfigError("orchestrator_config_path_escape")
        self._require_secure_ancestors(path)
        return raw

    def _require_secure_ancestors(self, path: Path) -> None:
        current = path
        while True:
            if current.is_symlink():
                raise OrchestrationConfigError("orchestrator_config_symlink_forbidden")
            _require_owner_only(current)
            if current == self._root:
                return
            current = current.parent

    def _reject_existing_relative_symlinks(self, raw: Path) -> None:
        """Reject raw components below the resolved project root without following them."""

        try:
            relative = raw.relative_to(self._root)
        except ValueError as exc:
            raise OrchestrationConfigError("orchestrator_config_path_escape") from exc
        current = self._root
        for part in relative.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise OrchestrationConfigError("orchestrator_config_path_escape")
            current /= part
            try:
                details = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(details.st_mode):
                raise OrchestrationConfigError("orchestrator_config_symlink_forbidden")

    def _read_stable_config(self, path: Path) -> str:
        """Read a final regular file without silently following a swapped leaf."""

        self._reject_existing_relative_symlinks(path)
        before = path.lstat()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise OrchestrationConfigError("orchestrator_config_unreadable") from exc
        try:
            opened = os.fstat(descriptor)
            after = path.lstat()
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                raise OrchestrationConfigError("orchestrator_config_path_changed")
            if not stat.S_ISREG(opened.st_mode):
                raise OrchestrationConfigError("orchestrator_config_unreadable")
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)

    def _safe_child(self, raw: str) -> Path:
        candidate = Path(raw)
        if candidate.is_absolute():
            raise OrchestrationConfigError("orchestrator_config_path_escape")
        if ".." in candidate.parts:
            raise OrchestrationConfigError("orchestrator_config_path_escape")
        current = self._root / candidate
        self._reject_existing_relative_symlinks(current)
        resolved = current.resolve(strict=False)
        if resolved != self._root and self._root not in resolved.parents:
            raise OrchestrationConfigError("orchestrator_config_path_escape")
        return resolved


class AtomicConfigStore:
    """Replace the in-memory active snapshot only after complete candidate validation."""

    def __init__(self, loader: OrchestrationConfigLoader, config_path: Path) -> None:
        self._loader = loader
        self._config_path = config_path
        self._active: OrchestrationConfigSnapshot | None = None

    @property
    def active(self) -> OrchestrationConfigSnapshot | None:
        return self._active

    def reload(self) -> ConfigReloadResult:
        previous = self._active
        try:
            candidate = self._loader.load(self._config_path)
        except OrchestrationConfigError as exc:
            return ConfigReloadResult(False, previous, ConfigurationIncidentEvidence("orchestrator_configuration_invalid", str(exc), str(self._config_path), None if previous is None else previous.config_sha256))
        self._active = candidate
        return ConfigReloadResult(True, candidate, None)


class SchedulingProjectionService:
    """Pure Hong Kong-time projection calculations; no wall-clock or storage access."""

    def project(self, snapshot: OrchestrationConfigSnapshot, now_utc: datetime) -> tuple[SchedulerJobProjection, ...]:
        now = _utc(now_utc)
        morning = _next_daily_morning(now)
        weekly = _next_monday_morning(now)
        return (
            SchedulerJobProjection("morning", "morning", snapshot.timezone, "daily_at", morning, _local_date(morning), None, None, "own_incremental", timedelta(hours=snapshot.daily_misfire_window_hours), snapshot.config_sha256),
            SchedulerJobProjection("weekly", "weekly", snapshot.timezone, "weekly_at", weekly, _local_date(weekly), None, "morning", "reuse_morning_collection", timedelta(hours=snapshot.weekly_misfire_window_hours), snapshot.config_sha256),
            SchedulerJobProjection("mail_poll", "mail", snapshot.timezone, "interval", now + timedelta(seconds=snapshot.mail_poll_interval_seconds), None, snapshot.mail_poll_interval_seconds, None, "none", None, snapshot.config_sha256),
            SchedulerJobProjection("health_check", "health_check", snapshot.timezone, "interval", now + timedelta(seconds=snapshot.health_check_interval_seconds), None, snapshot.health_check_interval_seconds, None, "none", None, snapshot.config_sha256),
        )

    def project_from_clock(self, snapshot: OrchestrationConfigSnapshot, clock: UtcClock) -> tuple[SchedulerJobProjection, ...]:
        """Project from an injected clock, preserving deterministic test control."""
        return self.project(snapshot, clock.now())

    @staticmethod
    def logical_local_date(now_utc: datetime) -> str:
        return _local_date(_utc(now_utc))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_aware_utc_required")
    return value.astimezone(UTC)


def _local_date(value: datetime) -> str:
    return value.astimezone(HONG_KONG).date().isoformat()


def _next_daily_morning(now_utc: datetime) -> datetime:
    local = now_utc.astimezone(HONG_KONG)
    due = datetime.combine(local.date(), time(9, 0), HONG_KONG)
    if local > due:
        due += timedelta(days=1)
    return due.astimezone(UTC)


def _next_monday_morning(now_utc: datetime) -> datetime:
    local = now_utc.astimezone(HONG_KONG)
    days = (0 - local.weekday()) % 7
    due = datetime.combine(local.date() + timedelta(days=days), time(9, 0), HONG_KONG)
    if local > due:
        due += timedelta(days=7)
    return due.astimezone(UTC)


# Compatibility name for callers that imported the old private helper.  The
# projection itself is now unambiguously Monday at 09:00 Hong Kong time.
_next_sunday_morning = _next_monday_morning


def _require_owner_only(path: Path) -> None:
    details = path.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise OrchestrationConfigError("orchestrator_config_not_owner_only")


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in _SECRET_MARKERS):
                raise OrchestrationConfigError("orchestrator_config_secret_forbidden")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)
