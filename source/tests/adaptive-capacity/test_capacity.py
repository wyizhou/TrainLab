from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.analysis.capacity import assess_weekly_capacity


def _rows() -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    plan_start = date(2026, 8, 10)
    activities: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    identifier = 1
    for offset in range(1, 5):
        start = plan_start - timedelta(days=7 * offset)
        for day_index in range(7):
            local_date = (start + timedelta(days=day_index)).isoformat()
            coverage.append(
                {
                    "id": identifier,
                    "resource_kind": "activity_inventory",
                    "local_date": local_date,
                    "availability_state": "empty",
                    "observed_at_utc": f"2026-08-14T00:00:{identifier:02d}Z",
                }
            )
            identifier += 1
        for day_index in (0, 2, 4, 6):
            local_date = (start + timedelta(days=day_index)).isoformat()
            activities.append(
                {
                    "local_date": local_date,
                    "sport": "running",
                    "provider_state": "active",
                    "distance_m": 10000,
                }
            )
    return tuple(activities), tuple(coverage)


def test_capacity_uses_recent_complete_week_median_and_caps_long_run() -> None:
    activities, coverage = _rows()

    result = assess_weekly_capacity(
        activities=activities,
        coverage=coverage,
        plan_start=date(2026, 8, 10),
        recovery_ready=True,
        adherence_stable=True,
    )

    assert result["status"] == "ready"
    assert result["decision"] == "advance"
    assert result["baseline"]["weekly_km_median"] == 40.0
    assert result["allowed_range"] == {"minimum_km": 40.0, "maximum_km": 44.0}
    assert result["frequency"] == {
        "minimum": 4,
        "maximum": 4,
        "allowed_weekdays": [1, 3, 5, 7],
    }
    assert result["long_run_max_km"] == 11.0
    assert result["race_pace_anchor"] is False


def test_capacity_deloads_without_recovery_and_defers_with_gaps() -> None:
    activities, coverage = _rows()
    deload = assess_weekly_capacity(
        activities=activities,
        coverage=coverage,
        plan_start=date(2026, 8, 10),
        recovery_ready=False,
        adherence_stable=True,
    )
    assert deload["decision"] == "deload"
    assert deload["allowed_range"] == {"minimum_km": 28.0, "maximum_km": 34.0}

    missing = {"2026-08-08", "2026-08-01", "2026-07-25"}
    incomplete = tuple(row for row in coverage if row["local_date"] not in missing)
    deferred = assess_weekly_capacity(
        activities=activities,
        coverage=incomplete,
        plan_start=date(2026, 8, 10),
    )
    assert deferred["status"] == "deferred"
    assert deferred["reason"] == "insufficient_complete_weeks"


def test_capacity_holds_when_adherence_is_not_stable() -> None:
    activities, coverage = _rows()
    result = assess_weekly_capacity(
        activities=activities,
        coverage=coverage,
        plan_start=date(2026, 8, 10),
        recovery_ready=True,
        adherence_stable=False,
    )
    assert result["status"] == "ready"
    assert result["decision"] == "hold"
    assert result["allowed_range"] == {"minimum_km": 36.0, "maximum_km": 42.0}
    assert result["single_change_dimension"] == "none"


def test_capacity_defers_when_recent_activity_lifecycle_is_unresolved() -> None:
    activities, coverage = _rows()
    activities = (
        *activities,
        {
            "local_date": "2026-08-03",
            "sport": "running",
            "provider_state": "provider_deleted",
            "distance_m": 5000,
        },
    )
    result = assess_weekly_capacity(
        activities=activities,
        coverage=coverage,
        plan_start=date(2026, 8, 10),
    )
    assert result["status"] == "deferred"
    assert result["reason"] == "activity_lifecycle_unresolved"
