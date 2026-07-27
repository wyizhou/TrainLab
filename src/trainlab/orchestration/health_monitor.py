"""Read-only health observation catalog with bounded operational persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol


class HealthMonitorError(ValueError):
    pass


CHECK_KINDS = frozenset({
    "foundation", "sqlite", "disk", "garmin", "analysis", "mail", "supervisor", "logs",
})
HEALTH_STATUSES = frozenset({"ready", "warning", "critical", "unavailable"})
_METRIC = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")
_FORBIDDEN_METRIC_PARTS = ("body", "payload", "prompt", "token", "password", "email", "content")


@dataclass(frozen=True, slots=True)
class HealthObservation:
    check_kind: str
    target_kind: str
    status: str
    metrics: Mapping[str, int | float | bool | str | None]
    target_id: str | None = None
    threshold_version: str = "health-v1"

    def __post_init__(self) -> None:
        if self.check_kind not in CHECK_KINDS:
            raise HealthMonitorError("health_check_kind_invalid")
        if not isinstance(self.target_kind, str) or _METRIC.fullmatch(self.target_kind) is None:
            raise HealthMonitorError("health_target_kind_invalid")
        if self.status not in HEALTH_STATUSES:
            raise HealthMonitorError("health_status_invalid")
        if self.target_id is not None and (
            not isinstance(self.target_id, str) or _SAFE_TEXT.fullmatch(self.target_id) is None
        ):
            raise HealthMonitorError("health_target_id_invalid")
        if not isinstance(self.metrics, Mapping) or len(self.metrics) > 32:
            raise HealthMonitorError("health_metrics_invalid")
        for key, value in self.metrics.items():
            if (
                not isinstance(key, str)
                or _METRIC.fullmatch(key) is None
                or any(part in key for part in _FORBIDDEN_METRIC_PARTS)
            ):
                raise HealthMonitorError("health_metric_forbidden")
            if isinstance(value, str) and _SAFE_TEXT.fullmatch(value) is None:
                raise HealthMonitorError("health_metric_text_invalid")
            if value is not None and not isinstance(value, (int, float, bool, str)):
                raise HealthMonitorError("health_metric_value_invalid")


class HealthRepository(Protocol):
    def record_health_check(self, **values): ...
    def record_incident(self, **values): ...
    def get_incident(self, incident_key: str): ...
    def transition_incident(self, incident_key: str, state: str, *, at_utc: datetime): ...


@dataclass(frozen=True, slots=True)
class HealthCheckSummary:
    status: str
    ready: int
    warning: int
    critical: int
    unavailable: int
    incident_keys: tuple[str, ...]
    recovered_incident_keys: tuple[str, ...] = ()


class HealthMonitor:
    """Persist already-computed metadata; probes remain read-only adapters."""

    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    def record(
        self,
        observations: tuple[HealthObservation, ...],
        *,
        checked_at_utc: datetime,
    ) -> HealthCheckSummary:
        if not observations:
            raise HealthMonitorError("health_observations_required")
        seen: set[tuple[str, str, str | None]] = set()
        counts = {key: 0 for key in HEALTH_STATUSES}
        incidents: list[str] = []
        recovered: list[str] = []
        for observation in observations:
            if not isinstance(observation, HealthObservation):
                raise HealthMonitorError("health_observation_invalid")
            identity = (observation.check_kind, observation.target_kind, observation.target_id)
            if identity in seen:
                raise HealthMonitorError("health_observation_duplicate")
            seen.add(identity)
            self._repository.record_health_check(
                check_kind=observation.check_kind,
                target_kind=observation.target_kind,
                target_id=observation.target_id,
                status=observation.status,
                metrics=dict(observation.metrics),
                threshold_version=observation.threshold_version,
                checked_at_utc=checked_at_utc,
            )
            counts[observation.status] += 1
            incident_key = f"health:{observation.check_kind}:{observation.target_kind}"
            if observation.target_id is not None:
                incident_key += f":{observation.target_id}"
            existing = self._repository.get_incident(incident_key)
            if observation.status == "ready":
                if existing is not None and existing.state in {"open", "acknowledged"}:
                    self._repository.transition_incident(
                        incident_key, "resolved", at_utc=checked_at_utc
                    )
                    recovered.append(incident_key)
                continue
            severity = {
                "warning": "warning",
                "critical": "critical",
                "unavailable": "error",
            }[observation.status]
            self._repository.record_incident(
                incident_key=incident_key,
                category="health",
                severity=severity,
                seen_at_utc=checked_at_utc,
                error_code=f"{observation.check_kind}_{observation.status}",
                error_summary="health check requires attention",
                next_action="operator_review" if severity == "critical" else "retry",
            )
            incidents.append(incident_key)
        overall = (
            "critical" if counts["critical"] else
            "unavailable" if counts["unavailable"] else
            "warning" if counts["warning"] else "ready"
        )
        return HealthCheckSummary(
            overall, counts["ready"], counts["warning"], counts["critical"],
            counts["unavailable"], tuple(incidents), tuple(recovered),
        )
