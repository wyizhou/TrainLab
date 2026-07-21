from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Iterable


ZONE_KEYS = ("zone_1", "zone_2", "zone_3", "zone_4", "zone_5")


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def hrr_target_bpm(resting_bpm: float, maximum_bpm: float, percent: float) -> int:
    """Return the inclusive integer lower edge for an HRR percentage."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    if resting_bpm <= 0 or maximum_bpm <= resting_bpm:
        raise ValueError("maximum_bpm must be greater than a positive resting_bpm")
    return math.ceil(resting_bpm + (percent / 100.0) * (maximum_bpm - resting_bpm))


def calculate_hrr_zones(
    resting_bpm: float,
    maximum_bpm: float,
    zone_config: dict[str, Any],
) -> dict[str, dict[str, int | float]]:
    """Build contiguous integer BPM zones from the configured HRR percentages."""
    lower_percentages: list[float] = []
    for key in ZONE_KEYS:
        definition = zone_config.get(key)
        if not isinstance(definition, dict) or "minimum_percent" not in definition:
            raise ValueError(f"missing minimum_percent for {key}")
        lower_percentages.append(float(definition["minimum_percent"]))
    if lower_percentages != sorted(lower_percentages) or lower_percentages[0] != 0:
        raise ValueError("zone minimum percentages must be sorted and start at zero")
    if lower_percentages[-1] >= 100:
        raise ValueError("zone_5 must start below 100 percent HRR")

    lower_bpms = [hrr_target_bpm(resting_bpm, maximum_bpm, value) for value in lower_percentages]
    output: dict[str, dict[str, int | float]] = {}
    for index, key in enumerate(ZONE_KEYS):
        upper_bpm = lower_bpms[index + 1] - 1 if index + 1 < len(lower_bpms) else math.floor(maximum_bpm)
        if upper_bpm < lower_bpms[index]:
            raise ValueError(f"heart-rate reserve is too narrow to form {key}")
        output[key] = {
            "minimum_percent": lower_percentages[index],
            "minimum_bpm": lower_bpms[index],
            "maximum_bpm": upper_bpm,
        }
    return output


def calculate_prescription_targets(
    resting_bpm: float,
    maximum_bpm: float,
    guidance: dict[str, Any],
) -> dict[str, dict[str, int]]:
    """Convert configured prescription percentages to inclusive BPM targets."""
    targets: dict[str, dict[str, int]] = {}
    for key in ZONE_KEYS:
        percentages = guidance[key]["prescription_percent"]
        upper_percent = float(percentages["maximum"])
        upper_bpm = (
            math.floor(maximum_bpm)
            if upper_percent >= 100
            else hrr_target_bpm(resting_bpm, maximum_bpm, upper_percent + 1) - 1
        )
        targets[key] = {
            "minimum_bpm": hrr_target_bpm(resting_bpm, maximum_bpm, float(percentages["minimum"])),
            "maximum_bpm": upper_bpm,
        }
    return targets


def classify_bpm(bpm: float, zones: dict[str, dict[str, int | float]]) -> str:
    """Classify a value without silently extending the supported HR range."""
    if bpm < float(zones["zone_1"]["minimum_bpm"]):
        return "below_zone_1"
    for key in ZONE_KEYS:
        if float(zones[key]["minimum_bpm"]) <= bpm <= float(zones[key]["maximum_bpm"]):
            return key
    return "above_zone_5"


def assess_zone_4_session(
    unlock_policy: dict[str, Any],
    *,
    completed_at: datetime,
    as_of: datetime,
    planned_work_seconds: float,
    completed_work_seconds: float,
    valid_heart_rate_seconds: float,
    zone_4_seconds: float,
    zone_5_seconds: float,
    invalidated_work_seconds: float = 0,
    longest_contiguous_invalid_seconds: float = 0,
    rpe: float | None = None,
    warning_symptom_reported: bool = False,
    acute_injury_reported: bool = False,
    linked_to_trainlab_prescription: bool = True,
) -> dict[str, Any]:
    """Apply the deterministic Zone 4 qualification gates used for Zone 5 unlock."""
    completed_at = _aware(completed_at, "completed_at")
    as_of = _aware(as_of, "as_of")
    if as_of < completed_at:
        raise ValueError("as_of cannot precede completed_at")
    numeric = {
        "planned_work_seconds": planned_work_seconds,
        "completed_work_seconds": completed_work_seconds,
        "valid_heart_rate_seconds": valid_heart_rate_seconds,
        "zone_4_seconds": zone_4_seconds,
        "zone_5_seconds": zone_5_seconds,
        "invalidated_work_seconds": invalidated_work_seconds,
        "longest_contiguous_invalid_seconds": longest_contiguous_invalid_seconds,
    }
    if any(value < 0 for value in numeric.values()) or planned_work_seconds <= 0:
        raise ValueError("durations must be non-negative and planned work must be positive")

    completion = unlock_policy["zone_4_success_completion_gate"]
    intensity = unlock_policy["zone_4_success_intensity_gate"]
    perceived = unlock_policy["zone_4_success_perceived_exertion_gate"]
    observation = unlock_policy["zone_4_success_observation_gate"]
    qualifying = unlock_policy["qualifying_zone_4_session"]
    effective_completed = max(0.0, completed_work_seconds - invalidated_work_seconds)
    completion_fraction = effective_completed / planned_work_seconds
    coverage_fraction = valid_heart_rate_seconds / effective_completed if effective_completed else 0.0
    zone_4_fraction = zone_4_seconds / valid_heart_rate_seconds if valid_heart_rate_seconds else 0.0
    zone_5_fraction = zone_5_seconds / effective_completed if effective_completed else 0.0
    observation_hours = (as_of - completed_at).total_seconds() / 3600
    metrics = {
        "effective_completed_work_seconds": effective_completed,
        "completion_fraction": completion_fraction,
        "valid_heart_rate_coverage_fraction": coverage_fraction,
        "zone_4_fraction_of_valid_heart_rate_time": zone_4_fraction,
        "zone_5_fraction_of_completed_work": zone_5_fraction,
        "observation_hours": observation_hours,
    }
    reasons: list[str] = []

    if warning_symptom_reported or acute_injury_reported:
        return {"status": "rejected", "qualified": False, "reasons": ["reported_safety_blocker"], "metrics": metrics, "completed_at": completed_at}
    if qualifying.get("trainlab_prescription_link_required") and not linked_to_trainlab_prescription:
        reasons.append("not_linked_to_trainlab_zone_4_prescription")
    if completion_fraction < float(completion["minimum_planned_work_fraction_completed"]):
        reasons.append("planned_zone_4_work_below_completion_threshold")
    if longest_contiguous_invalid_seconds > float(
        intensity["maximum_contiguous_invalid_time_within_work_interval_seconds"]
    ) and invalidated_work_seconds <= 0:
        return {
            "status": "indeterminate",
            "qualified": False,
            "reasons": ["invalid_interval_duration_not_supplied"],
            "metrics": metrics,
            "completed_at": completed_at,
        }
    if coverage_fraction < float(intensity["minimum_valid_heart_rate_coverage_fraction"]):
        return {"status": "indeterminate", "qualified": False, "reasons": ["insufficient_heart_rate_coverage"], "metrics": metrics, "completed_at": completed_at}
    if zone_4_fraction < float(intensity["minimum_time_weighted_fraction_in_zone_4"]):
        reasons.append("insufficient_zone_4_time")
    if zone_5_fraction > float(intensity["maximum_time_weighted_fraction_in_zone_5"]):
        reasons.append("excess_zone_5_time_for_controlled_zone_4")
    if rpe is not None:
        if not 0 <= rpe <= 10:
            raise ValueError("rpe must be between 0 and 10")
        if rpe < float(perceived["supportive_rpe_min"]):
            return {"status": "indeterminate", "qualified": False, "reasons": ["rpe_heart_rate_mismatch"], "metrics": metrics, "completed_at": completed_at}
        if rpe > float(perceived["supportive_rpe_max"]):
            reasons.append("rpe_indicates_uncontrolled_zone_4")
    if reasons:
        return {"status": "not_qualifying", "qualified": False, "reasons": reasons, "metrics": metrics, "completed_at": completed_at}
    if observation_hours < float(observation["minimum_observation_hours"]):
        return {"status": "pending_observation", "qualified": False, "reasons": ["observation_window_open"], "metrics": metrics, "completed_at": completed_at}
    return {"status": "qualified", "qualified": True, "reasons": [], "metrics": metrics, "completed_at": completed_at}


def evaluate_zone_5_unlock(
    heart_rate_policy: dict[str, Any],
    session_assessments: Iterable[dict[str, Any]],
    *,
    as_of: datetime,
    active_blockers: Iterable[str] = (),
    last_zone_4_or_zone_5_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate unlock, temporary relock, and evidence expiry without model judgment."""
    as_of = _aware(as_of, "as_of")
    unlock = heart_rate_policy["maximum_heart_rate_source"]["supported_baseline_zone_unlock"]
    relock = heart_rate_policy["zone_5_relock"]
    blockers = sorted(set(active_blockers).intersection(relock["immediate_blockers"]))
    if blockers:
        return {"status": "temporarily_locked", "unlocked": False, "reasons": blockers, "qualifying_sessions": 0}

    qualified = []
    for item in session_assessments:
        if item.get("status") != "qualified" or not item.get("qualified"):
            continue
        completed_at = item.get("completed_at")
        if not isinstance(completed_at, datetime):
            raise ValueError("qualified session assessments require completed_at datetime")
        qualified.append({**item, "completed_at": _aware(completed_at, "completed_at")})
    qualified.sort(key=lambda item: item["completed_at"])
    lapse = relock["authorization_lapse"]
    full_reset_gap = timedelta(days=float(lapse["full_reset_after_days"]))
    reset_index = 0
    for index in range(1, len(qualified)):
        if qualified[index]["completed_at"] - qualified[index - 1]["completed_at"] >= full_reset_gap:
            reset_index = index
    qualified = qualified[reset_index:]
    required = int(unlock["zone_5_required_successful_zone_4_sessions"])
    distinct: list[dict[str, Any]] = []
    minimum_gap = timedelta(hours=float(unlock["zone_5_minimum_hours_between_zone_4_sessions"]))
    for item in qualified:
        if distinct and item["completed_at"].date() == distinct[-1]["completed_at"].date():
            continue
        if distinct and item["completed_at"] - distinct[-1]["completed_at"] < minimum_gap:
            continue
        distinct.append(item)
    if len(distinct) < required:
        return {
            "status": "locked",
            "unlocked": False,
            "reasons": ["insufficient_qualified_zone_4_sessions"],
            "qualifying_sessions": len(distinct),
        }

    latest_evidence = last_zone_4_or_zone_5_at or distinct[-1]["completed_at"]
    latest_evidence = _aware(latest_evidence, "last_zone_4_or_zone_5_at")
    if latest_evidence > as_of:
        raise ValueError("last Zone 4/5 evidence cannot be later than as_of")
    inactivity_days = (as_of - latest_evidence).total_seconds() / 86400
    if inactivity_days >= float(lapse["full_reset_after_days"]):
        return {"status": "expired_full_reset", "unlocked": False, "reasons": ["high_intensity_evidence_expired"], "qualifying_sessions": 0}
    if inactivity_days >= float(lapse["after_days_without_zone_4_or_zone_5"]):
        return {
            "status": "expired_needs_one_zone_4_revalidation",
            "unlocked": False,
            "reasons": ["high_intensity_evidence_stale"],
            "qualifying_sessions": len(distinct),
        }
    return {"status": "unlocked", "unlocked": True, "reasons": [], "qualifying_sessions": len(distinct)}
