#!/usr/bin/env python3
"""Deterministic content-first v4 evidence and fixed-plan contracts.

This module has no Provider, database, filesystem or model access.  Daily code
may use it while raw evidence is already in memory; weekly code consumes only
the persisted daily observations that this module produces.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from statistics import fmean, pstdev
from typing import Any, TypeGuard

from skills._shared.scripts.health_contract_v4 import (
    health_raw_file_ids,
    validate_health_facts_vc002,
)
from skills._shared.scripts.schema_validation import validate_payload

SOS_TYPES = {"sos_threshold", "sos_cruise_intervals", "sos_hills"}
HARD_TYPES = SOS_TYPES | {"climbing_hard"}
SESSION_TYPES = {
    "recovery_run",
    "easy_run",
    "long_easy",
    *SOS_TYPES,
    "climbing_technique",
    "climbing_hard",
    "rest",
}
REQUIRED_RUNNING_PHASES = {"warmup", "main", "recovery", "cooldown"}
FORBIDDEN_DYNAMIC_FIELDS = {
    "start_gate",
    "downgrade_rule",
    "downgrade_course",
    "alternative_course",
    "replacement_course",
    "effective_course",
    "adjustment",
}
FORBIDDEN_HEART_RATE_PRESCRIPTIONS = (
    re.compile(r"\b(?:z|zone)\s*[1-5]\b", re.IGNORECASE),
    re.compile(r"\b\d{2,3}\s*bpm\b", re.IGNORECASE),
    re.compile(r"(?:目标|阈值|最大)心率"),
    re.compile(r"心率区间"),
)


def _is_number(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _all_text(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _all_text(item)]
    return [value] if isinstance(value, str) else []


def validate_training_plan_v3(value: object) -> list[str]:
    """Validate the fixed seven-day plan without legacy dynamic-course fields."""

    if not isinstance(value, dict):
        return ["training_plan_not_object"]
    errors: list[str] = []
    if value.get("schema_version") != "training_plan_v3":
        errors.append("training_plan_schema_version_invalid")
    if value.get("status") not in {"succeeded", "blocked"}:
        errors.append("training_plan_status_invalid")
    if value.get("provider_calls") != 0:
        errors.append("provider_calls_must_be_zero")
    progression = value.get("progression_rule")
    if progression not in {"advance", "hold", "deload"}:
        errors.append("progression_rule_invalid")
    if value.get("progression_dimension") not in {"distance", "intensity", "none"}:
        errors.append("progression_dimension_invalid")
    if any(
        pattern.search(text)
        for text in _all_text(value)
        for pattern in FORBIDDEN_HEART_RATE_PRESCRIPTIONS
    ):
        errors.append("heart_rate_prescription_forbidden")

    items = value.get("items")
    if not isinstance(items, list) or len(items) != 7:
        return sorted(set(errors + ["course_must_cover_seven_days"]))

    parsed_dates: list[date] = []
    hard_dates: list[date] = []
    sos_count = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item_{index}_not_object")
            continue
        for forbidden in FORBIDDEN_DYNAMIC_FIELDS:
            if forbidden in item:
                errors.append(f"item_{index}_{forbidden}_forbidden")
        try:
            parsed = date.fromisoformat(str(item.get("date")))
            parsed_dates.append(parsed)
        except ValueError:
            errors.append(f"item_{index}_date_invalid")
            continue
        session_type = item.get("session_type")
        activity_kind = item.get("activity_kind")
        if session_type not in SESSION_TYPES:
            errors.append(f"item_{index}_session_type_invalid")
        if session_type in SOS_TYPES:
            sos_count += 1
        if session_type in HARD_TYPES or item.get("load_level") == "hard":
            hard_dates.append(parsed)
        if session_type == "rest" and activity_kind != "rest":
            errors.append(f"item_{index}_rest_kind_invalid")
        if session_type != "rest" and activity_kind not in {"running", "climbing"}:
            errors.append(f"item_{index}_activity_kind_invalid")
        for field in ("name", "purpose", "feel_guidance"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"item_{index}_{field}_missing")
        rpe_min = item.get("rpe_min")
        rpe_max = item.get("rpe_max")
        if not (
            _is_number(rpe_min)
            and _is_number(rpe_max)
            and 1 <= float(rpe_min) <= float(rpe_max) <= 10
        ):
            errors.append(f"item_{index}_rpe_invalid")
        if not _strings(item.get("technique_notes")):
            errors.append(f"item_{index}_technique_notes_missing")
        if not _strings(item.get("stop_conditions")):
            errors.append(f"item_{index}_stop_conditions_missing")
        steps = item.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"item_{index}_steps_missing")
        else:
            phases = {step.get("phase") for step in steps if isinstance(step, dict)}
            if session_type == "rest":
                if "checklist" not in phases:
                    errors.append(f"item_{index}_rest_checklist_missing")
            elif not REQUIRED_RUNNING_PHASES.issubset(phases):
                errors.append(f"item_{index}_required_phases_missing")

    if len(parsed_dates) == 7:
        if parsed_dates != sorted(parsed_dates) or any(
            later - earlier != timedelta(days=1)
            for earlier, later in zip(parsed_dates, parsed_dates[1:])
        ):
            errors.append("course_dates_not_contiguous")
    if len(hard_dates) > 3:
        errors.append("hard_load_count_exceeds_three")
    for earlier, later in zip(sorted(set(hard_dates)), sorted(set(hard_dates))[1:]):
        if (later - earlier).days < 3:
            errors.append("hard_load_gap_less_than_three_days")
    omission = value.get("sos_omission_reason")
    if progression in {"hold", "advance"} and sos_count != 1:
        errors.append("sos_count_must_equal_one")
    if progression == "deload" and sos_count == 0:
        if not isinstance(omission, dict) or omission.get("reason_code") not in {
            "deload",
            "red_flag",
            "insufficient_recovery",
        }:
            errors.append("sos_omission_reason_missing")
    if sos_count > 1:
        errors.append("sos_count_exceeds_one")
    sos_dates = [
        date.fromisoformat(str(item["date"]))
        for item in items
        if isinstance(item, dict)
        and item.get("session_type") in SOS_TYPES
        and isinstance(item.get("date"), str)
    ]
    schedule_reason = value.get("sos_schedule_reason")
    if sos_dates and sos_dates[0].weekday() != 2:
        if not isinstance(schedule_reason, str) or not schedule_reason.strip():
            errors.append("sos_schedule_reason_missing")
    errors.extend(validate_payload(value, "training_plan_v3"))
    return sorted(set(errors))


def _evidence_ref(activity: dict[str, Any]) -> str:
    return (
        f"activity:{int(activity['activity_inventory_id'])}:"
        f"raw:{int(activity['raw_file_id'])}:{activity['raw_sha256']}"
    )


def _metric_evidence_ref(activity: dict[str, Any], metric_code: str) -> str:
    return f"{_evidence_ref(activity)}:metric:{metric_code}"


def _metric(
    activity: dict[str, Any],
    *,
    code: str,
    status: str,
    value: object,
    unit: str | None,
    method_code: str,
    segment: str,
    exclusions: list[str],
    coverage: float,
    confidence: str,
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "metric_code": code,
        "status": status,
        "value": value,
        "unit": unit,
        "method": {
            "method_code": method_code,
            "method_version": "1.0",
            "segment": segment,
            "exclusions": exclusions,
        },
        "coverage": round(max(0.0, min(1.0, coverage)), 4),
        "confidence": confidence,
        "evidence_refs": [_metric_evidence_ref(activity, code)],
        "limitations": limitations,
    }


def _provider_zone_metric(activity: dict[str, Any]) -> dict[str, Any] | None:
    zones = activity.get("observed_heart_rate_zones")
    if not isinstance(zones, dict):
        return None
    durations = zones.get("durations_seconds")
    definition = zones.get("definition_sha256")
    if (
        zones.get("source") != "fit_session_time_in_hr_zone"
        or zones.get("reference_mesg") != "session"
        or zones.get("reference_index") != 0
        or not isinstance(durations, list)
        or len(durations) != 7
        or not all(_is_number(item) and float(item) >= 0 for item in durations)
        or not isinstance(definition, str)
        or not re.fullmatch(r"[0-9a-f]{64}", definition)
    ):
        return None
    clean = [float(item) for item in durations]
    total = sum(clean)
    value = {
        "durations_seconds": clean,
        "percentages": [round(item / total * 100, 2) for item in clean]
        if total > 0
        else [0.0] * 7,
        "definition_sha256": definition,
        "percentage_source": "derived_from_provider_duration",
    }
    return _metric(
        activity,
        code="provider_hr_zone_duration_v1",
        status="available",
        value=value,
        unit="seconds_and_percent",
        method_code="provider_session_duration_passthrough",
        segment="whole provider session",
        exclusions=[],
        coverage=1.0,
        confidence="high",
        limitations=["仅描述设备已记录的历史分区时长，不用于未来课程处方"],
    )


def _decoupling_metric(activity: dict[str, Any]) -> dict[str, Any]:
    segment = activity.get("steady_segment")
    if not isinstance(segment, dict):
        return _metric(
            activity,
            code="aerobic_decoupling_power_hr_v1",
            status="not_applicable",
            value=None,
            unit="percent",
            method_code="equal_moving_time_power_hr",
            segment="none",
            exclusions=["没有 Host 明确标记的合资格连续稳态段"],
            coverage=0.0,
            confidence="none",
            limitations=["不得用整场均值、速度或心率替代"],
        )
    start = segment.get("start_offset_seconds")
    end = segment.get("end_offset_seconds")
    if not isinstance(start, int) or not isinstance(end, int) or end - start < 1800:
        return _metric(
            activity,
            code="aerobic_decoupling_power_hr_v1",
            status="not_applicable",
            value=None,
            unit="percent",
            method_code="equal_moving_time_power_hr",
            segment=f"{start}-{end}",
            exclusions=["稳态段少于30分钟"],
            coverage=0.0,
            confidence="none",
            limitations=["不满足冻结适用条件"],
        )
    analysis_start = max(start, 600)
    if end - analysis_start < 1800:
        return _metric(
            activity,
            code="aerobic_decoupling_power_hr_v1",
            status="not_applicable",
            value=None,
            unit="percent",
            method_code="equal_moving_time_power_hr",
            segment=f"{analysis_start}-{end}",
            exclusions=["已实际排除活动前10分钟；剩余稳态段少于30分钟"],
            coverage=0.0,
            confidence="none",
            limitations=["不满足冻结适用条件"],
        )
    points = [
        point
        for point in activity.get("sequence", [])
        if isinstance(point, dict)
        and isinstance(point.get("offset_seconds"), int)
        and analysis_start <= point["offset_seconds"] < end
    ]
    resolution = activity.get("sequence_resolution_seconds", 30)
    expected = max(1, math.ceil((end - analysis_start) / int(resolution)))
    pairs: list[tuple[int, float, float]] = []
    for point in points:
        metrics = point.get("metrics")
        if not isinstance(metrics, dict):
            continue
        heart_rate = metrics.get("heart_rate_bpm")
        power = metrics.get("power_watts")
        if (
            _is_number(heart_rate)
            and _is_number(power)
            and heart_rate > 0
            and power > 0
        ):
            pairs.append(
                (int(point["offset_seconds"]), float(heart_rate), float(power))
            )
    coverage = len(pairs) / expected
    if coverage < 0.8 or len(pairs) < 2:
        return _metric(
            activity,
            code="aerobic_decoupling_power_hr_v1",
            status="insufficient_data",
            value=None,
            unit="percent",
            method_code="equal_moving_time_power_hr",
            segment=f"{analysis_start}-{end}",
            exclusions=["缺少配对的功率或心率样本"],
            coverage=coverage,
            confidence="none",
            limitations=["配对覆盖率必须至少80%"],
        )
    midpoint = analysis_start + (end - analysis_start) / 2
    first = [item for item in pairs if item[0] < midpoint]
    second = [item for item in pairs if item[0] >= midpoint]
    if not first or not second:
        status = "insufficient_data"
        decoupling: float | None = None
    else:
        ef_first = fmean(item[2] for item in first) / fmean(item[1] for item in first)
        ef_second = fmean(item[2] for item in second) / fmean(
            item[1] for item in second
        )
        decoupling = round(100 * (ef_first - ef_second) / ef_first, 3)
        status = "available"
    exclusions = ["已实际排除活动前10分钟"]
    exclusions.extend(
        str(item) for item in segment.get("excluded_intervals", []) if str(item)
    )
    return _metric(
        activity,
        code="aerobic_decoupling_power_hr_v1",
        status=status,
        value=decoupling,
        unit="percent",
        method_code="equal_moving_time_power_hr",
        segment=f"{analysis_start}-{end}",
        exclusions=exclusions,
        coverage=coverage,
        confidence="high" if coverage >= 0.95 else "moderate",
        limitations=["只描述同一次合资格稳态跑，不用于推断因果"],
    )


def _repetition_metric(activity: dict[str, Any]) -> dict[str, Any]:
    work_laps = [
        lap
        for lap in activity.get("laps", [])
        if isinstance(lap, dict) and lap.get("lap_role") == "work"
    ]
    if len(work_laps) < 3:
        return _metric(
            activity,
            code="explicit_work_lap_stability_v1",
            status="not_applicable",
            value=None,
            unit=None,
            method_code="explicit_fit_work_laps_cv",
            segment="none",
            exclusions=["少于3个明确标记的work圈段"],
            coverage=0.0,
            confidence="none",
            limitations=["不猜测未标记间歇结构"],
        )
    pace_values: list[float] = []
    for lap in work_laps:
        duration = lap.get("duration_seconds")
        distance = lap.get("distance_m")
        if _is_number(duration) and _is_number(distance) and distance > 0:
            pace_values.append(float(duration) / (float(distance) / 1000))
    if len(pace_values) < 3 or fmean(pace_values) <= 0:
        return _metric(
            activity,
            code="explicit_work_lap_stability_v1",
            status="insufficient_data",
            value=None,
            unit="coefficient_of_variation_percent",
            method_code="explicit_fit_work_laps_cv",
            segment="explicit work laps",
            exclusions=["recovery", "warmup", "cooldown"],
            coverage=len(pace_values) / len(work_laps),
            confidence="none",
            limitations=["有效work圈段不足"],
        )
    cv = pstdev(pace_values) / fmean(pace_values) * 100
    return _metric(
        activity,
        code="explicit_work_lap_stability_v1",
        status="available",
        value={"pace_cv_percent": round(cv, 3), "work_lap_count": len(pace_values)},
        unit="coefficient_of_variation_percent",
        method_code="explicit_fit_work_laps_cv",
        segment="explicit work laps",
        exclusions=["recovery", "warmup", "cooldown"],
        coverage=len(pace_values) / len(work_laps),
        confidence="high" if len(pace_values) == len(work_laps) else "moderate",
        limitations=["只比较同一次活动内明确标记的work圈段"],
    )


def _running_dynamics_metric(activity: dict[str, Any]) -> dict[str, Any]:
    segment = activity.get("steady_segment")
    if not isinstance(segment, dict):
        return _metric(
            activity,
            code="running_dynamics_front_back_v1",
            status="not_applicable",
            value=None,
            unit=None,
            method_code="same_activity_equal_time_halves",
            segment="none",
            exclusions=["没有合资格稳态段"],
            coverage=0.0,
            confidence="none",
            limitations=["不跨地形、天气或活动比较"],
        )
    fields = (
        "cadence_spm",
        "step_length_m",
        "ground_contact_time_ms",
        "vertical_oscillation_mm",
        "vertical_ratio_pct",
        "power_watts",
    )
    start = int(segment.get("start_offset_seconds", 0))
    end = int(segment.get("end_offset_seconds", 0))
    analysis_start = max(start, 600)
    if end - analysis_start < 600:
        return _metric(
            activity,
            code="running_dynamics_front_back_v1",
            status="not_applicable",
            value=None,
            unit="mixed",
            method_code="same_activity_equal_time_halves",
            segment=f"{analysis_start}-{end}",
            exclusions=["已实际排除活动前10分钟；剩余片段不足10分钟"],
            coverage=0.0,
            confidence="none",
            limitations=["不满足冻结适用条件"],
        )
    points = [
        point
        for point in activity.get("sequence", [])
        if isinstance(point, dict)
        and isinstance(point.get("offset_seconds"), int)
        and analysis_start <= point["offset_seconds"] < end
        and isinstance(point.get("metrics"), dict)
    ]
    expected = max(
        1,
        math.ceil(
            max(0, end - analysis_start)
            / int(activity.get("sequence_resolution_seconds", 30))
        ),
    )
    midpoint = analysis_start + (end - analysis_start) / 2
    values: dict[str, dict[str, float]] = {}
    coverages: list[float] = []
    for field in fields:
        first = [
            float(point["metrics"][field])
            for point in points
            if point["offset_seconds"] < midpoint
            and _is_number(point["metrics"].get(field))
        ]
        second = [
            float(point["metrics"][field])
            for point in points
            if point["offset_seconds"] >= midpoint
            and _is_number(point["metrics"].get(field))
        ]
        coverage = (len(first) + len(second)) / expected
        if coverage >= 0.8 and first and second:
            first_mean = fmean(first)
            second_mean = fmean(second)
            values[field] = {
                "first_half": round(first_mean, 3),
                "second_half": round(second_mean, 3),
                "change_percent": round(
                    (second_mean - first_mean) / first_mean * 100, 3
                )
                if first_mean
                else 0.0,
            }
            coverages.append(coverage)
    if not values:
        return _metric(
            activity,
            code="running_dynamics_front_back_v1",
            status="insufficient_data",
            value=None,
            unit="mixed",
            method_code="same_activity_equal_time_halves",
            segment=f"{analysis_start}-{end}",
            exclusions=["低于80%覆盖率的字段"],
            coverage=0.0,
            confidence="none",
            limitations=["没有满足覆盖率的跑姿或功率字段"],
        )
    return _metric(
        activity,
        code="running_dynamics_front_back_v1",
        status="available",
        value=values,
        unit="mixed",
        method_code="same_activity_equal_time_halves",
        segment=f"{analysis_start}-{end}",
        exclusions=["已实际排除活动前10分钟", "停顿", "非稳态段"],
        coverage=min(coverages),
        confidence="moderate",
        limitations=["只报告同次活动前后变化，不套用通用好坏阈值"],
    )


def build_activity_technical_evidence(activity: dict[str, Any]) -> dict[str, Any]:
    """Build bounded metrics from an already-loaded daily activity envelope."""

    required = ("activity_inventory_id", "raw_file_id", "raw_sha256")
    if any(key not in activity for key in required):
        raise ValueError("activity_lineage_incomplete")
    metrics: list[dict[str, Any]] = []
    zones = _provider_zone_metric(activity)
    if zones is not None:
        metrics.append(zones)
    if activity.get("activity_kind") == "running":
        metrics.extend(
            [
                _repetition_metric(activity),
                _decoupling_metric(activity),
                _running_dynamics_metric(activity),
            ]
        )
    climbing_intensity = "not_climbing"
    if activity.get("activity_kind") == "climbing":
        if _is_number(activity.get("provider_training_load")):
            climbing_intensity = "provider_supported"
        elif _is_number(activity.get("user_rpe")):
            climbing_intensity = "user_rpe_supported"
        else:
            climbing_intensity = "intensity_unknown"
    result = {
        "schema_version": "activity_technical_evidence_v1",
        "status": "ready",
        "activity_inventory_id": int(activity["activity_inventory_id"]),
        "raw_file_id": int(activity["raw_file_id"]),
        "raw_sha256": str(activity["raw_sha256"]),
        "climbing_intensity": climbing_intensity,
        "metrics": metrics,
        "provider_calls": 0,
    }
    errors = validate_payload(result, "activity_technical_evidence_v1")
    if errors:
        raise ValueError("activity_technical_evidence_invalid:" + ",".join(errors[:3]))
    return result


def build_daily_completed_observation(
    *,
    report_date: str,
    activity_date: str,
    health_date: str,
    sleep_wake_date: str,
    activities: list[dict[str, Any]],
    expected_activity_count: int,
    health_facts: list[dict[str, Any]],
    expected_health_raw_file_ids: list[int],
    health_analysis_ref: dict[str, Any],
) -> dict[str, Any]:
    """Freeze all daily facts; no plan matching or course advice occurs here."""

    parsed_report = date.fromisoformat(report_date)
    if date.fromisoformat(activity_date) != parsed_report - timedelta(days=1):
        raise ValueError("daily_activity_date_invalid")
    if date.fromisoformat(health_date) != parsed_report - timedelta(days=1):
        raise ValueError("daily_health_date_invalid")
    if date.fromisoformat(sleep_wake_date) != parsed_report:
        raise ValueError("daily_sleep_wake_date_invalid")
    if expected_activity_count != len(activities):
        raise ValueError("daily_activity_inventory_incomplete")
    health_errors = validate_health_facts_vc002(
        health_facts,
        health_date=health_date,
        sleep_wake_date=sleep_wake_date,
    )
    if health_errors:
        raise ValueError("daily_health_contract_invalid:" + ",".join(health_errors[:3]))
    observed_health_raw_file_ids = health_raw_file_ids(health_facts)
    expected_health_raw_file_ids = sorted(set(expected_health_raw_file_ids))
    if expected_health_raw_file_ids != observed_health_raw_file_ids:
        raise ValueError("daily_health_inventory_incomplete")
    normalized: list[dict[str, Any]] = []
    for activity in activities:
        item = deepcopy(activity)
        if item.get("activity_date") != activity_date:
            raise ValueError("daily_activity_cross_date")
        technical = build_activity_technical_evidence(item)
        item["technical_metrics"] = technical["metrics"]
        for field in (
            "sequence",
            "sequence_resolution_seconds",
            "steady_segment",
            "laps",
            "observed_heart_rate_zones",
            "provider_training_load",
            "user_rpe",
        ):
            item.pop(field, None)
        normalized.append(item)
    result = {
        "schema_version": "daily_completed_observation_v1",
        "status": "ready",
        "report_date": report_date,
        "activity_date": activity_date,
        "health_date": health_date,
        "sleep_wake_date": sleep_wake_date,
        "inventory": {
            "expected_count": expected_activity_count,
            "observed_count": len(normalized),
            "complete": True,
        },
        "health_inventory": {
            "expected_raw_file_ids": expected_health_raw_file_ids,
            "observed_raw_file_ids": observed_health_raw_file_ids,
            "complete": True,
        },
        "activities": normalized,
        "health_facts": deepcopy(health_facts),
        "health_analysis_ref": deepcopy(health_analysis_ref),
        "provider_calls": 0,
    }
    errors = validate_payload(result, "daily_completed_observation_v1")
    if errors:
        raise ValueError("daily_completed_observation_invalid:" + ",".join(errors[:3]))
    return result


def daily_health_analysis_v3_from_v2(value: dict[str, Any]) -> dict[str, Any]:
    """Reuse validated health prose while dropping every course-decision field."""

    result = {
        "schema_version": "daily_health_analysis_v3",
        "status": str(value.get("status", "blocked")),
        "report_date": str(value["report_date"]),
        "review_date": str(value["review_date"]),
        "sleep_wake_date": str(value["sleep_wake_date"]),
        "safety": str(value["safety"]),
        "health_summary": str(value["review_health_summary"]),
        "sleep_analysis": str(value.get("sleep_analysis") or value["recovery_summary"]),
        "recovery_analysis": str(value["recovery_summary"]),
        "health_alert": (
            {
                "severity": "red_flag" if value["safety"] == "blocked" else "caution",
                "message": "存在独立健康警告；该警告不会改写已保存的周计划。",
                "blocks_external_execution": value["safety"] == "blocked",
            }
            if value["safety"] != "ready"
            else None
        ),
        "uncertainty": deepcopy(value.get("uncertainty", [])),
        "evidence_refs": sorted(
            {
                int(item["output_id"])
                for item in value.get("evidence_refs", [])
                if isinstance(item, dict) and isinstance(item.get("output_id"), int)
            }
        ),
        "provider_calls": 0,
    }
    if not result["evidence_refs"]:
        raise ValueError("daily_health_evidence_missing")
    errors = validate_payload(result, "daily_health_analysis_v3")
    if errors:
        raise ValueError("daily_health_analysis_v3_invalid:" + ",".join(errors[:3]))
    return result


def fixed_course_v3_from_v2(course: dict[str, Any]) -> dict[str, Any]:
    """Project an original v2 weekly course into the immutable v3 course shape."""

    allowed = {
        "date",
        "activity_kind",
        "session_type",
        "name",
        "purpose",
        "load_level",
        "duration_minutes",
        "distance_km",
        "rpe_min",
        "rpe_max",
        "feel_guidance",
        "steps",
        "technique_notes",
        "stop_conditions",
    }
    result = {key: deepcopy(value) for key, value in course.items() if key in allowed}
    if result.get("session_type") == "rest":
        result["duration_minutes"] = float(result.get("duration_minutes") or 0)
        steps = result.get("steps")
        if not isinstance(steps, list) or not any(
            isinstance(item, dict) and item.get("phase") == "checklist"
            for item in steps
        ):
            result["steps"] = [
                {
                    "phase": "checklist",
                    "name": "恢复安排",
                    "instruction": "不安排主训练，保留日常轻活动。",
                    "end_condition": "当天结束",
                }
            ]
    return result


def _observation_ref(observation: dict[str, Any]) -> dict[str, Any]:
    reference = observation.get("observation_ref")
    if not isinstance(reference, dict):
        reference = observation.get("health_analysis_ref")
    if not isinstance(reference, dict):
        raise ValueError("daily_observation_ref_missing")
    return {
        "report_date": str(observation["report_date"]),
        "activity_date": str(observation["activity_date"]),
        "output_id": int(reference["output_id"]),
        "sha256": str(reference["sha256"]),
    }


def _select_key_runs(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    running = [item for item in activities if item.get("activity_kind") == "running"]

    def score(item: dict[str, Any]) -> tuple[int, float, float, str, int]:
        explicit = any(
            metric.get("metric_code") == "explicit_work_lap_stability_v1"
            and metric.get("status") == "available"
            for metric in item.get("technical_metrics", [])
            if isinstance(metric, dict)
        )
        return (
            0 if explicit else 1,
            -float(item.get("distance_km") or 0),
            -float(item.get("duration_seconds") or 0),
            str(item.get("activity_date")),
            int(item.get("activity_inventory_id", 0)),
        )

    selected = sorted(running, key=score)[:3]
    return [
        {
            "activity_inventory_id": int(item["activity_inventory_id"]),
            "raw_file_id": int(item["raw_file_id"]),
            "raw_sha256": str(item["raw_sha256"]),
        }
        for item in selected
    ]


def build_weekly_training_evidence_v2(
    observations: list[dict[str, Any]],
    *,
    planned_activity_dates: set[str] | None = None,
) -> dict[str, Any]:
    """Aggregate exactly seven complete daily observations without reading raw."""

    if len(observations) != 7:
        raise ValueError("weekly_requires_seven_daily_observations")
    ordered = sorted(observations, key=lambda item: str(item.get("activity_date")))
    activity_dates = [
        date.fromisoformat(str(item["activity_date"])) for item in ordered
    ]
    if any(
        later - earlier != timedelta(days=1)
        for earlier, later in zip(activity_dates, activity_dates[1:])
    ):
        raise ValueError("daily_observation_dates_not_contiguous")
    for item in ordered:
        inventory = item.get("inventory")
        health_inventory = item.get("health_inventory")
        health_errors = validate_health_facts_vc002(
            item.get("health_facts"),
            health_date=str(item.get("health_date")),
            sleep_wake_date=str(item.get("sleep_wake_date")),
        )
        if (
            item.get("schema_version") != "daily_completed_observation_v1"
            or item.get("status") != "ready"
            or item.get("provider_calls") != 0
            or not isinstance(inventory, dict)
            or inventory.get("complete") is not True
            or inventory.get("expected_count") != inventory.get("observed_count")
            or inventory.get("observed_count") != len(item.get("activities", []))
            or not isinstance(health_inventory, dict)
            or health_inventory.get("complete") is not True
            or health_inventory.get("expected_raw_file_ids")
            != health_inventory.get("observed_raw_file_ids")
            or health_raw_file_ids(item.get("health_facts"))
            != health_inventory.get("observed_raw_file_ids")
            or health_errors
        ):
            raise ValueError("daily_observation_incomplete")
    planned = planned_activity_dates or set()
    all_activities: list[dict[str, Any]] = []
    health_days: list[dict[str, Any]] = []
    for observation in ordered:
        health_days.append(
            {
                "health_date": observation["health_date"],
                "sleep_wake_date": observation["sleep_wake_date"],
                "facts": deepcopy(observation["health_facts"]),
                "health_analysis_ref": deepcopy(observation["health_analysis_ref"]),
            }
        )
        for activity in observation["activities"]:
            copied = deepcopy(activity)
            copied["plan_relation"] = (
                "date_only_match"
                if activity["activity_date"] in planned
                else "unplanned"
            )
            all_activities.append(copied)
    all_activities.sort(
        key=lambda item: (
            str(item["activity_date"]),
            int(item["activity_inventory_id"]),
        )
    )
    by_kind = Counter(str(item["activity_kind"]) for item in all_activities)
    total_duration = sum(float(item["duration_seconds"]) for item in all_activities)
    run_distance = sum(
        float(item.get("distance_km") or 0)
        for item in all_activities
        if item.get("activity_kind") == "running"
    )
    activity_day_count = len({item["activity_date"] for item in all_activities})
    result = {
        "schema_version": "weekly_training_evidence_v2",
        "status": "ready",
        "period": {
            "activity_start_date": activity_dates[0].isoformat(),
            "activity_end_date": activity_dates[-1].isoformat(),
            "sleep_wake_start_date": str(ordered[0]["sleep_wake_date"]),
            "sleep_wake_end_date": str(ordered[-1]["sleep_wake_date"]),
        },
        "daily_observation_refs": [_observation_ref(item) for item in ordered],
        "health_days": health_days,
        "all_activities": all_activities,
        "weekly_totals": {
            "activity_count": len(all_activities),
            "activity_days": activity_day_count,
            "no_activity_days": 7 - activity_day_count,
            "duration_seconds": round(total_duration, 3),
            "running_distance_km": round(run_distance, 3),
            "by_activity_kind": dict(sorted(by_kind.items())),
        },
        "key_run_refs": _select_key_runs(all_activities),
        "plan_comparison": {
            "date_only_matches": sum(
                item["plan_relation"] == "date_only_match" for item in all_activities
            ),
            "unplanned_activities": sum(
                item["plan_relation"] == "unplanned" for item in all_activities
            ),
            "comparison_is_secondary": True,
        },
        "raw_reads": 0,
        "provider_calls": 0,
    }
    errors = validate_payload(result, "weekly_training_evidence_v2")
    if errors:
        raise ValueError("weekly_training_evidence_invalid:" + ",".join(errors[:3]))
    return result


def validate_weekly_ai_result_v3(
    value: object, evidence: dict[str, Any] | None = None
) -> list[str]:
    if not isinstance(value, dict):
        return ["weekly_ai_result_not_object"]
    errors = validate_payload(value, "weekly_ai_result_v3")
    errors.extend(validate_training_plan_v3(value.get("training_plan")))
    if value.get("provider_calls") != 0:
        errors.append("provider_calls_must_be_zero")
    if any(
        pattern.search(text)
        for text in _all_text(value)
        for pattern in FORBIDDEN_HEART_RATE_PRESCRIPTIONS
    ):
        errors.append("heart_rate_prescription_forbidden")
    for index, finding in enumerate(value.get("technical_findings", [])):
        if not isinstance(finding, dict) or not finding.get("evidence_refs"):
            errors.append(f"technical_finding_{index}_evidence_missing")
    if evidence is not None:
        allowed_ids = {
            int(item["activity_inventory_id"])
            for item in evidence.get("key_run_refs", [])
            if isinstance(item, dict)
            and isinstance(item.get("activity_inventory_id"), int)
        }
        available_by_activity: dict[int, dict[str, str]] = {}
        reference_owners: dict[str, int] = {}
        for activity in evidence.get("all_activities", []):
            if not isinstance(activity, dict):
                continue
            activity_id = activity.get("activity_inventory_id")
            if not isinstance(activity_id, int) or activity_id not in allowed_ids:
                continue
            available: dict[str, str] = {}
            for metric in activity.get("technical_metrics", []):
                if not isinstance(metric, dict):
                    continue
                metric_code = metric.get("metric_code")
                if not isinstance(metric_code, str):
                    errors.append("technical_evidence_identity_invalid")
                    continue
                expected_reference = _metric_evidence_ref(activity, metric_code)
                references = metric.get("evidence_refs")
                if references != [expected_reference]:
                    errors.append("technical_evidence_identity_invalid")
                    continue
                previous_owner = reference_owners.get(expected_reference)
                if previous_owner is not None and previous_owner != activity_id:
                    errors.append("technical_evidence_identity_invalid")
                    continue
                reference_owners[expected_reference] = activity_id
                if metric.get("status") != "available":
                    continue
                confidence = str(metric.get("confidence"))
                available[expected_reference] = confidence
            available_by_activity[activity_id] = available
        cited_activity_ids: set[int] = set()
        confidence_rank = {"none": 0, "low": 1, "moderate": 2, "high": 3}
        for index, finding in enumerate(value.get("technical_findings", [])):
            if not isinstance(finding, dict):
                continue
            activity_refs = finding.get("activity_refs", [])
            if (
                not isinstance(activity_refs, list)
                or not activity_refs
                or any(
                    not isinstance(item, int) or item not in allowed_ids
                    for item in activity_refs
                )
            ):
                errors.append(f"technical_finding_{index}_activity_not_allowed")
                continue
            if len(activity_refs) != len(set(activity_refs)):
                errors.append(f"technical_finding_{index}_activity_refs_duplicate")
                continue
            cited_activity_ids.update(activity_refs)
            permitted_refs = {
                reference
                for activity_id in activity_refs
                for reference in available_by_activity.get(activity_id, {})
            }
            evidence_refs = finding.get("evidence_refs", [])
            if (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or any(not isinstance(reference, str) for reference in evidence_refs)
            ):
                errors.append(f"technical_finding_{index}_metric_not_available")
                continue
            if len(evidence_refs) != len(set(evidence_refs)):
                errors.append(f"technical_finding_{index}_evidence_refs_duplicate")
                continue
            for activity_id in activity_refs:
                if not any(
                    reference in available_by_activity.get(activity_id, {})
                    for reference in evidence_refs
                ):
                    errors.append(
                        f"technical_finding_{index}_activity_{activity_id}_evidence_missing"
                    )
            if any(
                not isinstance(reference, str) or reference not in permitted_refs
                for reference in evidence_refs
            ):
                errors.append(f"technical_finding_{index}_metric_not_available")
                continue
            host_confidence = min(
                (
                    confidence_rank.get(
                        available_by_activity[activity_id][reference], 0
                    )
                    for reference in evidence_refs
                    for activity_id in activity_refs
                    if reference in available_by_activity.get(activity_id, {})
                ),
                default=0,
            )
            if confidence_rank.get(str(finding.get("confidence")), 0) > host_confidence:
                errors.append(f"technical_finding_{index}_confidence_exceeds_host")
        if len(cited_activity_ids) > 3:
            errors.append("technical_findings_exceed_three_activities")
    return sorted(set(errors))
