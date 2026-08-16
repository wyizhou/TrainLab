#!/usr/bin/env python3
"""Validate the small, provider-neutral course contract used by training-coach."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import record_skill_result  # noqa: E402

KINDS = {"running", "climbing", "rest"}
STATUSES = {"candidate", "requires_review", "unsupported_skip"}
PROGRESSION_DIMENSIONS = {"distance", "intensity", "none"}


def validate(value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["course_not_object"]
    items = value.get("items")
    if not isinstance(items, list) or not items:
        return ["course_items_missing"]
    if len(items) != 7:
        errors.append("course_must_cover_seven_days")
    progression_dimension = value.get("progression_dimension")
    if progression_dimension not in PROGRESSION_DIMENSIONS:
        errors.append("progression_dimension_invalid")
    previous_distance = value.get("previous_week_distance_km")
    current_distance = value.get("current_week_distance_km")
    previous_intensity = value.get("previous_week_intensity_score")
    current_intensity = value.get("current_week_intensity_score")
    distance_increased = (
        isinstance(previous_distance, (int, float))
        and isinstance(current_distance, (int, float))
        and current_distance > previous_distance
    )
    intensity_increased = (
        isinstance(previous_intensity, (int, float))
        and isinstance(current_intensity, (int, float))
        and current_intensity > previous_intensity
    )
    if distance_increased and intensity_increased:
        errors.append("progression_two_dimensions")
    if distance_increased and progression_dimension != "distance":
        errors.append("progression_dimension_mismatch")
    if intensity_increased and progression_dimension != "intensity":
        errors.append("progression_dimension_mismatch")
    dates: set[str] = set()
    hard_days: list[date] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item_{index}_not_object")
            continue
        day = item.get("date")
        try:
            parsed = date.fromisoformat(str(day))
        except ValueError:
            errors.append(f"item_{index}_date_invalid")
            continue
        if str(day) in dates:
            errors.append("duplicate_course_date")
        dates.add(str(day))
        kind = item.get("activity_kind")
        if kind not in KINDS:
            errors.append(f"item_{index}_activity_kind_invalid")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            errors.append(f"item_{index}_name_missing")
        if item.get("garmin_mapping_status") not in STATUSES:
            errors.append(f"item_{index}_garmin_mapping_status_invalid")
        if not isinstance(item.get("purpose"), str) or not item["purpose"].strip():
            errors.append(f"item_{index}_purpose_missing")
        rpe = item.get("rpe")
        if (
            not isinstance(rpe, (int, float))
            or isinstance(rpe, bool)
            or not 1 <= rpe <= 10
        ):
            errors.append(f"item_{index}_rpe_invalid")
        if (
            not isinstance(item.get("downgrade_rule"), str)
            or not item["downgrade_rule"].strip()
        ):
            errors.append(f"item_{index}_downgrade_rule_missing")
        stop_conditions = item.get("stop_conditions")
        if (
            not isinstance(stop_conditions, list)
            or not stop_conditions
            or not all(
                isinstance(condition, str) and condition.strip()
                for condition in stop_conditions
            )
        ):
            errors.append(f"item_{index}_stop_conditions_missing")
        if "race_pace_anchor" in item:
            errors.append("race_pace_anchor_without_confirmed_goal")
        load = item.get("load_level")
        if load == "hard":
            hard_days.append(parsed)
        if (
            kind == "running"
            and not isinstance(item.get("duration_minutes"), (int, float))
            and not isinstance(item.get("distance_km"), (int, float))
        ):
            errors.append(f"item_{index}_dose_missing")
        if kind == "climbing" and not isinstance(
            item.get("duration_minutes"), (int, float)
        ):
            errors.append(f"item_{index}_climbing_duration_missing")
        if kind == "rest" and item.get("garmin_mapping_status") != "unsupported_skip":
            errors.append(f"item_{index}_rest_mapping_invalid")
        if (
            kind == "climbing"
            and item.get("garmin_mapping_status") != "unsupported_skip"
        ):
            errors.append(f"item_{index}_climbing_mapping_invalid")
    for left, right in zip(sorted(hard_days), sorted(hard_days)[1:]):
        if (right - left).days < 3:
            errors.append("hard_load_gap_less_than_two_calendar_days")
    if len(hard_days) > 3:
        errors.append("hard_load_count_exceeds_three")
    if dates:
        parsed_dates = sorted(date.fromisoformat(day) for day in dates)
        if len(parsed_dates) == 7 and any(
            right - left != timedelta(days=1)
            for left, right in zip(parsed_dates, parsed_dates[1:])
        ):
            errors.append("course_dates_not_contiguous")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    errors = validate(json.loads(args.input_json.read_text(encoding="utf-8")))
    payload = {"status": "passed" if not errors else "failed", "errors": errors}
    if args.database:
        record_skill_result(
            args.database,
            skill_name="training-coach",
            operation="validate_plan",
            output_kind="training_plan",
            logical_key=f"training-coach:course:{args.input_json.resolve()}",
            payload=payload,
            status="succeeded" if not errors else "failed",
            error_code=errors[0] if errors else None,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
