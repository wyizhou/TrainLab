"""Deterministic M10 training-plan to Garmin-preview projection."""

from __future__ import annotations

import re
from typing import Any

TEST_TAG = "E2E-20260818"
PLAN_START = "2026-08-19"
PLAN_END = "2026-08-25"


class M10PlanError(ValueError):
    """Stable deterministic plan projection failure."""


def _format_pace(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    rounded = int(round(float(seconds)))
    return f"{rounded // 60}:{rounded % 60:02d}/km"


def _positive_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _workout_name(name: str) -> str:
    base = name.removesuffix("-GTS")
    return f"{base}-{TEST_TAG}-GTS"


def _is_simple_workout(item: dict[str, Any]) -> bool:
    steps = item.get("steps")
    if not isinstance(steps, list) or len(steps) != 1:
        return False
    step = steps[0]
    if not isinstance(step, dict):
        return False
    text = " ".join(
        (
            str(item.get("name", "")),
            str(step.get("name", "")),
            str(step.get("end_condition", "")),
        )
    ).casefold()
    if re.search(
        r"(?:interval|repeat|recovery\s*jog|warm\s*up|cool\s*down|"
        r"\b\d+\s*[x×]\s*\d+|\d+\s*组|每组|组间|间歇|重复|热身|放松)",
        text,
    ):
        return False
    condition = str(step.get("end_condition", "")).strip().casefold()
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", condition)]
    distance = _positive_number(item.get("distance_km"))
    duration = _positive_number(item.get("duration_minutes"))
    if distance is not None:
        return (
            len(numbers) == 1
            and abs(numbers[0] - distance) < 1e-9
            and ("km" in condition or "公里" in condition)
        )
    if duration is not None:
        return (
            len(numbers) == 1
            and abs(numbers[0] - duration) < 1e-9
            and ("分钟" in condition or "minute" in condition or "min" in condition)
        )
    return False


def _workout_payload(item: dict[str, Any], name: str) -> dict[str, Any]:
    distance = item.get("distance_km")
    duration = item.get("duration_minutes")
    if (
        isinstance(distance, (int, float))
        and not isinstance(distance, bool)
        and distance > 0
    ):
        end_condition = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
        end_value = float(distance) * 1000.0
    elif (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and duration > 0
    ):
        end_condition = {"conditionTypeId": 2, "conditionTypeKey": "time"}
        end_value = float(duration) * 60.0
    else:
        raise M10PlanError("m10_workout_dose_missing")
    pace_min = _positive_number(item.get("pace_min_seconds_per_km"))
    pace_max = _positive_number(item.get("pace_max_seconds_per_km"))
    hr_min = _positive_number(item.get("heart_rate_min_bpm"))
    hr_max = _positive_number(item.get("heart_rate_max_bpm"))
    if pace_min is not None and pace_max is not None:
        target: dict[str, Any] = {
            "targetType": {
                "workoutTargetTypeId": 6,
                "workoutTargetTypeKey": "pace.zone",
            },
            "targetValueOne": 1000.0 / float(pace_max),
            "targetValueTwo": 1000.0 / float(pace_min),
        }
    elif hr_min is not None and hr_max is not None:
        target = {
            "targetType": {
                "workoutTargetTypeId": 4,
                "workoutTargetTypeKey": "heart.rate.zone",
            },
            "targetValueOne": float(hr_min),
            "targetValueTwo": float(hr_max),
        }
    else:
        target = {
            "targetType": {
                "workoutTargetTypeId": 1,
                "workoutTargetTypeKey": "no.target",
            }
        }
    notes = [str(item.get("purpose", "")), str(item.get("downgrade_rule", ""))]
    notes.extend(
        f"{step.get('name')}: {step.get('end_condition')}"
        for step in item.get("steps", [])
        if isinstance(step, dict)
    )
    notes.extend(str(value) for value in item.get("stop_conditions", []))
    description = "；".join(value for value in notes if value)
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": 1,
        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
        "description": description,
        "endCondition": end_condition,
        "endConditionValue": end_value,
        **target,
    }
    return {
        "workoutName": name,
        "description": description,
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                "workoutSteps": [step],
            }
        ],
    }


def normalize_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items = plan.get("items")
    if not isinstance(items, list) or len(items) != 7:
        raise M10PlanError("m10_training_plan_invalid")
    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise M10PlanError("m10_training_plan_invalid")
        day = str(item.get("date", ""))
        if day < PLAN_START or day > PLAN_END:
            raise M10PlanError("m10_training_plan_date_invalid")
        if item.get("activity_kind") != "running":
            continue
        if item.get("garmin_mapping_status") != "candidate":
            continue
        if not _is_simple_workout(item):
            continue
        name = _workout_name(str(item.get("name", "")))
        candidates.append(
            {
                "date": day,
                "name": name,
                "pace_upper": _format_pace(item.get("pace_max_seconds_per_km")),
                "pace_lower": _format_pace(item.get("pace_min_seconds_per_km")),
                "heart_rate_upper": (
                    f"{int(item['heart_rate_max_bpm'])} bpm"
                    if isinstance(item.get("heart_rate_max_bpm"), (int, float))
                    else "—"
                ),
                "heart_rate_lower": (
                    f"{int(item['heart_rate_min_bpm'])} bpm"
                    if isinstance(item.get("heart_rate_min_bpm"), (int, float))
                    else "—"
                ),
                "duration": (
                    f"{float(item['duration_minutes']):g} 分钟"
                    if isinstance(item.get("duration_minutes"), (int, float))
                    else "—"
                ),
                "distance": (
                    f"{float(item['distance_km']):g} km"
                    if isinstance(item.get("distance_km"), (int, float))
                    else "—"
                ),
                "notes": "；".join(
                    value
                    for value in (
                        str(item.get("purpose", "")),
                        str(item.get("downgrade_rule", "")),
                        " / ".join(
                            str(value) for value in item.get("stop_conditions", [])
                        ),
                    )
                    if value
                ),
                "workout_data": _workout_payload(item, name),
            }
        )
    if not candidates or len(candidates) > 4:
        raise M10PlanError("m10_workout_budget_invalid")
    if len({row["name"] for row in candidates}) != len(candidates):
        raise M10PlanError("m10_workout_name_conflict")
    return candidates


def garmin_action_requests(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the exact provider-neutral requests approved for one preview row."""
    name = str(row["name"])
    day = str(row["date"])
    return {
        "create": {
            "m10_phase": "create",
            "name": name,
            "workout_data": row["workout_data"],
        },
        "verify_created": {"m10_phase": "verify_created", "name": name},
        "schedule": {
            "m10_phase": "schedule",
            "name": name,
            "calendar_date": day,
        },
        "verify_scheduled": {
            "m10_phase": "verify_scheduled",
            "name": name,
            "calendar_date": day,
        },
        "unschedule": {
            "m10_phase": "unschedule",
            "name": name,
            "calendar_date": day,
        },
        "verify_absent_after_unschedule": {
            "m10_phase": "verify_absent_after_unschedule",
            "name": name,
            "calendar_date": day,
        },
        "delete": {"m10_phase": "delete", "name": name},
        "verify_absent_after_delete": {
            "m10_phase": "verify_absent_after_delete",
            "name": name,
        },
    }
