from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trainlab.orchestration.health_monitor import (
    HealthMonitor,
    HealthMonitorError,
    HealthObservation,
)


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


class Repo:
    def __init__(self):
        self.checks = []
        self.incidents = {}
        self.incident_writes = []

    def record_health_check(self, **values):
        self.checks.append(values)

    def get_incident(self, key):
        return self.incidents.get(key)

    def record_incident(self, **values):
        self.incident_writes.append(values)
        key = values["incident_key"]
        current = self.incidents.get(key)
        count = 1 if current is None else current.occurrence_count + 1
        self.incidents[key] = SimpleNamespace(state="open", occurrence_count=count)

    def transition_incident(self, key, state, *, at_utc):
        self.incidents[key] = SimpleNamespace(
            state=state, occurrence_count=self.incidents[key].occurrence_count
        )


def test_catalog_records_only_metadata_and_deduplicates_incident() -> None:
    repo = Repo()
    monitor = HealthMonitor(repo)
    observations = (
        HealthObservation("foundation", "schema", "ready", {"schema_version": 5}),
        HealthObservation("garmin", "cursor", "warning", {"lag_days": 2, "open_gaps": 1}),
        HealthObservation("mail", "backlog", "critical", {"pending_count": 8}),
    )
    summary = monitor.record(observations, checked_at_utc=NOW)
    assert summary.status == "critical"
    assert summary.incident_keys == ("health:garmin:cursor", "health:mail:backlog")
    assert all(
        row["error_summary"] == "health_check_requires_attention"
        for row in repo.incident_writes
    )
    monitor.record(observations, checked_at_utc=NOW)
    assert repo.incidents["health:garmin:cursor"].occurrence_count == 2
    assert all("payload" not in str(row).lower() for row in repo.checks)


def test_ready_observation_resolves_open_incident() -> None:
    repo = Repo()
    monitor = HealthMonitor(repo)
    monitor.record((HealthObservation("disk", "capacity", "warning", {"free_percent": 8}),), checked_at_utc=NOW)
    monitor.record((HealthObservation("disk", "capacity", "ready", {"free_percent": 48}),), checked_at_utc=NOW)
    assert repo.incidents["health:disk:capacity"].state == "resolved"


@pytest.mark.parametrize("key", ["email", "raw_payload", "prompt_text", "access_token"])
def test_sensitive_or_business_metrics_are_rejected(key: str) -> None:
    with pytest.raises(HealthMonitorError, match="health_metric_forbidden"):
        HealthObservation("analysis", "delivery", "warning", {key: 1})


def test_duplicate_observation_fails_before_ambiguous_second_write() -> None:
    observation = HealthObservation("sqlite", "integrity", "ready", {"ok": True})
    with pytest.raises(HealthMonitorError, match="health_observation_duplicate"):
        HealthMonitor(Repo()).record((observation, observation), checked_at_utc=NOW)
