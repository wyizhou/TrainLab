"""Deterministic weekly running capacity assessment.

This module receives already projected, bounded activity and coverage rows.  It
never reads SQLite, provider data, FIT files, credentials, or model output.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from statistics import median
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from src.resources import resource_bytes

_SCHEMA = json.loads(
    resource_bytes("harness/schemas/weekly_capacity_assessment_v1.schema.json")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_RUNNING_SPORTS = frozenset(
    {"running", "run", "trail_running", "treadmill_running", "track_running"}
)
_COMPLETE_COVERAGE = frozenset({"fetched", "empty", "complete"})
_DEFAULT_WEEKDAYS = (1, 3, 5, 7)


class WeeklyCapacityError(ValueError):
    """A deterministic capacity assessment failure."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _median(values: list[float]) -> float:
    if not values:
        raise WeeklyCapacityError("weekly_capacity_values_missing")
    return float(median(values))


def _latest_coverage(rows: tuple[Mapping[str, Any], ...]) -> dict[str, str]:
    latest: dict[str, tuple[str, int, str]] = {}
    for row in rows:
        if row.get("resource_kind") != "activity_inventory":
            continue
        local_date = row.get("local_date")
        state = row.get("availability_state")
        observed = row.get("observed_at_utc")
        row_id = row.get("id", 0)
        if (
            not isinstance(local_date, str)
            or not isinstance(state, str)
            or not isinstance(observed, str)
            or isinstance(row_id, bool)
            or not isinstance(row_id, int)
        ):
            continue
        previous = latest.get(local_date)
        if previous is None or (observed, row_id) > (previous[0], previous[1]):
            latest[local_date] = (observed, row_id, state)
    return {local_date: value[2] for local_date, value in latest.items()}


def _week_stats(
    activities: tuple[Mapping[str, Any], ...],
    coverage: Mapping[str, str],
    start: date,
) -> dict[str, Any] | None:
    end = start + timedelta(days=6)
    days = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    if any(coverage.get(day) not in _COMPLETE_COVERAGE for day in days):
        return None
    runs: list[Mapping[str, Any]] = []
    for row in activities:
        if row.get("local_date") not in days:
            continue
        sport = row.get("sport")
        if not isinstance(sport, str) or sport.lower() not in _RUNNING_SPORTS:
            continue
        if row.get("provider_state") not in {None, "active", "suspected_missing"}:
            continue
        distance = _number(row.get("distance_m"))
        if distance is None:
            return None
        runs.append(row)
    raw_distances = [_number(row.get("distance_m")) for row in runs]
    if any(value is None for value in raw_distances):
        return None
    distances = [value for value in raw_distances if value is not None]
    distance_km = sum(value or 0.0 for value in distances) / 1000.0
    hard_load_count = sum(
        1
        for row in runs
        if row.get("hansons_session_role")
        in {"long", "tempo", "speed", "running_strength"}
        or row.get("hard_session") is True
    )
    return {
        "start_local_date": start.isoformat(),
        "end_local_date": end.isoformat(),
        "distance_km": round(distance_km, 3),
        "running_count": len(runs),
        "longest_run_km": round(max(distances, default=0.0) / 1000.0, 3),
        "hard_load_count": hard_load_count,
    }


def assess_weekly_capacity(
    *,
    activities: tuple[Mapping[str, Any], ...],
    coverage: tuple[Mapping[str, Any], ...],
    plan_start: date,
    recovery_ready: bool = True,
    adherence_stable: bool = True,
    available_weekdays: tuple[int, ...] | None = None,
    hard_load_max: int = 3,
    hard_load_min_gap_days: int = 2,
) -> dict[str, Any]:
    """Return the host-owned capacity interval for one Monday plan start."""

    if plan_start.weekday() != 0:
        raise WeeklyCapacityError("weekly_capacity_plan_start_monday_required")
    if hard_load_max < 0 or hard_load_min_gap_days < 0:
        raise WeeklyCapacityError("weekly_capacity_profile_limits_invalid")
    coverage_by_date = _latest_coverage(coverage)
    weeks: list[dict[str, Any]] = []
    for offset in range(1, 5):
        start = plan_start - timedelta(days=7 * offset)
        stats = _week_stats(activities, coverage_by_date, start)
        if stats is not None:
            weeks.append(stats)
    weekdays = tuple(sorted(set(available_weekdays or _DEFAULT_WEEKDAYS)))
    if any(day not in _DEFAULT_WEEKDAYS for day in weekdays):
        raise WeeklyCapacityError("weekly_capacity_weekday_invalid")
    period = {
        "start_local_date": plan_start.isoformat(),
        "end_local_date": (plan_start + timedelta(days=6)).isoformat(),
    }
    if len(weeks) < 2:
        result = {
            "schema_version": "1",
            "status": "deferred",
            "decision": "hold",
            "plan_period": period,
            "complete_weeks": weeks,
            "baseline": {
                "weekly_km_median": 0,
                "frequency_median_floor": 0,
                "longest_run_km_median": 0,
                "hard_load_median_floor": 0,
            },
            "allowed_range": {"minimum_km": 0, "maximum_km": 0},
            "frequency": {
                "minimum": 0,
                "maximum": 0,
                "allowed_weekdays": list(weekdays),
            },
            "long_run_max_km": 0,
            "hard_load": {
                "maximum": hard_load_max,
                "minimum_gap_days": hard_load_min_gap_days,
            },
            "single_change_dimension": "none",
            "race_pace_anchor": False,
            "reason": "insufficient_complete_weeks",
        }
        _validate(result)
        return result

    weekly_km = _median([float(week["distance_km"]) for week in weeks])
    frequency = int(
        math.floor(_median([float(week["running_count"]) for week in weeks]))
    )
    longest = _median([float(week["longest_run_km"]) for week in weeks])
    hard_median = int(
        math.floor(_median([float(week["hard_load_count"]) for week in weeks]))
    )
    decision = "advance" if recovery_ready and adherence_stable else "hold"
    if not recovery_ready:
        decision = "deload"
    multipliers = {
        "advance": (1.0, 1.10),
        "hold": (0.90, 1.05),
        "deload": (0.70, 0.85),
    }
    minimum_multiplier, maximum_multiplier = multipliers[decision]
    minimum_km = round(weekly_km * minimum_multiplier, 3)
    maximum_km = round(weekly_km * maximum_multiplier, 3)
    frequency_max = min(len(weekdays), frequency + 1)
    frequency_min = max(0, frequency - 1) if decision == "deload" else frequency
    long_run_max = round(min(maximum_km * 0.4, longest * 1.10), 3)
    result = {
        "schema_version": "1",
        "status": "ready",
        "decision": decision,
        "plan_period": period,
        "complete_weeks": weeks,
        "baseline": {
            "weekly_km_median": round(weekly_km, 3),
            "frequency_median_floor": frequency,
            "longest_run_km_median": round(longest, 3),
            "hard_load_median_floor": hard_median,
        },
        "allowed_range": {"minimum_km": minimum_km, "maximum_km": maximum_km},
        "frequency": {
            "minimum": frequency_min,
            "maximum": frequency_max,
            "allowed_weekdays": list(weekdays),
        },
        "long_run_max_km": long_run_max,
        "hard_load": {
            "maximum": hard_load_max,
            "minimum_gap_days": hard_load_min_gap_days,
        },
        "single_change_dimension": "volume" if decision == "advance" else "none",
        "race_pace_anchor": False,
        "reason": "complete_recent_weeks_and_recovery_gate",
    }
    _validate(result)
    return result


def _validate(value: dict[str, Any]) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(value), key=lambda error: list(error.absolute_path)
    )
    if errors:
        raise WeeklyCapacityError("weekly_capacity_schema_invalid")
