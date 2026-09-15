"""Pure fixed-plan conversion and pinned MCP curated semantic readback."""

from __future__ import annotations

import re
from typing import Any

from skills._shared.fit_weekly import storage

SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}
PHASES = {
    "warmup": (1, "warmup"),
    "run": (3, "interval"),
    "work": (3, "interval"),
    "recovery": (4, "recovery"),
    "cooldown": (2, "cooldown"),
}


def ident(value: Any) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(value)):
        raise ValueError("garmin_workout_id_invalid")
    return int(value)


def convert(day: dict[str, Any]) -> dict[str, Any]:
    if day["kind"] != "run" or not isinstance(day["workout"], dict):
        raise ValueError("garmin_running_day_required")
    w = day["workout"]
    description = (
        "目的："
        + w["purpose"]
        + "\n剂量："
        + str(w["dose"]["value"])
        + " "
        + w["dose"]["unit"]
        + "\n技术备注："
        + w["technical_notes"]
        + "\n停止条件："
        + "；".join(w["stop_conditions"])
    )
    result: list[dict[str, Any]] = []
    order = 0
    for group in w["steps"]:
        order += 1
        group_order = order
        nested = []
        for step in group["steps"]:
            order += 1
            phase_id, phase_key = PHASES[step["phase"]]
            if step["unit"] not in ("seconds", "meters"):
                raise ValueError("garmin_step_unit_invalid")
            condition = (2, "time") if step["unit"] == "seconds" else (3, "distance")
            nested.append(
                {
                    "type": "ExecutableStepDTO",
                    "stepOrder": order,
                    "stepType": {"stepTypeId": phase_id, "stepTypeKey": phase_key},
                    "description": f"RPE {step['rpe']}；{step['effort']}；{step['instructions']}",
                    "endCondition": {
                        "conditionTypeId": condition[0],
                        "conditionTypeKey": condition[1],
                    },
                    "endConditionValue": step["value"],
                    "targetType": {
                        "workoutTargetTypeId": 1,
                        "workoutTargetTypeKey": "no.target",
                    },
                }
            )
        if group["repeat"] > 1:
            result.append(
                {
                    "type": "RepeatGroupDTO",
                    "stepOrder": group_order,
                    "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                    "endCondition": {
                        "conditionTypeId": 7,
                        "conditionTypeKey": "iterations",
                    },
                    "numberOfIterations": group["repeat"],
                    "workoutSteps": nested,
                }
            )
        else:
            result.extend(nested)
    dto = {
        "workoutName": f"TrainLab {day['date']} {w['kind']}",
        "description": description,
        "sportType": SPORT,
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": SPORT, "workoutSteps": result}
        ],
    }
    storage.canonical(dto)
    return dto


def verify(value: dict[str, Any], dto: dict[str, Any], workout_id: int) -> None:
    def steps(actual: Any, expected: list[dict[str, Any]]) -> None:
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError("steps")
        for a, e in zip(actual, expected):
            if any(k.startswith(("target_", "secondary_")) for k in a):
                raise ValueError("target")
            required = {
                "order": e["stepOrder"],
                "type": e["stepType"]["stepTypeKey"],
                "end_condition": e["endCondition"]["conditionTypeKey"],
            }
            if "description" in e:
                required["description"] = e["description"]
            if e["type"] == "RepeatGroupDTO":
                required.update(
                    repeat_count=e["numberOfIterations"],
                    step_count=len(e["workoutSteps"]),
                )
                steps(a.get("steps"), e["workoutSteps"])
            else:
                required["end_condition_value"] = e["endConditionValue"]
                if a.get("steps") or a.get("repeat_count"):
                    raise ValueError("extra_steps")
            if any(a.get(k) != v for k, v in required.items()):
                raise ValueError("step_content")

    try:
        if ident(value.get("id")) != workout_id or any(
            value.get(k) != v
            for k, v in {
                "name": dto["workoutName"],
                "description": dto["description"],
                "sport": "running",
                "segment_count": 1,
            }.items()
        ):
            raise ValueError("workout")
        segments = value["segments"]
        expected = dto["workoutSegments"][0]["workoutSteps"]
        if len(segments) != 1 or any(
            segments[0].get(k) != v
            for k, v in {
                "order": 1,
                "sport": "running",
                "step_count": len(expected),
            }.items()
        ):
            raise ValueError("segment")
        steps(segments[0]["steps"], expected)
    except Exception:
        raise ValueError("garmin_workout_readback_mismatch") from None
