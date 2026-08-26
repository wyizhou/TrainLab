#!/usr/bin/env python3
"""Deterministic Coaching Utility v2 contracts and safety checks.

This module contains no Provider or database access.  It validates model output,
builds bounded weekly aggregates from already-validated daily outputs, and
creates explicit reader views without changing v1 artifacts.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, timedelta
from typing import Any, TypeGuard

from skills._shared.scripts.reader_safety import (
    validate_narrative_visible_text,
    validate_reader_visible_text,
)

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
REQUIRED_PHASES = {"warmup", "main", "recovery", "cooldown"}
REFERENCE_PACE_TYPES = {"recovery_run", "easy_run", "long_easy"}
PLANNED_COURSE_CONTEXTS = {"verified_original", "test_baseline"}
LAST_NIGHT_HRV_METRIC_NAMES = {
    "hrv_last_night_average",
    "last_night_hrv_average",
    "review_hrv_last_night_average",
    "review_last_night_hrv_average",
    "review_date_hrv_last_night_average",
    "review_date_last_night_hrv_average",
}
FORBIDDEN_PRESCRIPTION_TOKENS = (
    "heart_rate_zone",
    "target_bpm",
    "max_heart_rate",
    "threshold_bpm",
    "最大心率",
    "目标心率",
    "心率区间",
    "乳酸阈值",
    "心率",
)
FORBIDDEN_PRESCRIPTION_PATTERNS = (
    re.compile(r"\b(?:z|zone)\s*[1-5]\b", re.IGNORECASE),
    re.compile(r"\b\d{2,3}\s*bpm\b", re.IGNORECASE),
    re.compile(r"\b(?:maximum|max|target|threshold)\s+heart\s+rate\b", re.IGNORECASE),
)
UNVERIFIED_ADVICE_EXECUTION_PATTERNS = (
    re.compile(r"(?:已|已经)(?:执行|完成|落实).{0,20}(?:降级|调整|建议|改课)"),
    re.compile(r"(?:降级|调整|建议|改课).{0,20}(?:已|已经)(?:执行|完成|落实)"),
    re.compile(
        r"(?:实际|本周)?(?:训练)?负荷.{0,12}(?:比|较|低于|少于|小于).{0,8}"
        r"(?:原计划|计划).{0,8}(?:减少|下降|更低|更少|低|少)?"
    ),
    re.compile(
        r"(?:实际|本周)?(?:训练)?负荷.{0,12}(?:减少|下降|更低|更少).{0,8}"
        r"(?:原计划|计划)"
    ),
)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _contains_forbidden_prescription(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_forbidden_prescription(key)
            or _contains_forbidden_prescription(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_prescription(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(token in lowered for token in FORBIDDEN_PRESCRIPTION_TOKENS) or any(
            pattern.search(value) for pattern in FORBIDDEN_PRESCRIPTION_PATTERNS
        )
    return False


def _nonempty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _iter_text(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _iter_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _iter_text(item)]
    return [value] if isinstance(value, str) else []


def _metric_name_matches(name: str, suffixes: set[str]) -> bool:
    return any(name == suffix or name.endswith(f"_{suffix}") for suffix in suffixes)


def derive_legacy_daily_host_facts(
    legacy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Extract bounded Host facts without conflating different HRV semantics."""

    sleep_hours: float | None = None
    running_distance = 0.0
    activity_count = 0
    metric_names: list[str] = []
    health_facts: dict[str, Any] = {
        "sleep_hours": None,
        "legacy_safety": legacy.get("safety"),
    }
    review_health_parts: list[str] = []
    for metric in legacy.get("bounded_metrics", []):
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name", "")).strip().lower()
        unit = str(metric.get("unit", "")).strip().lower()
        value = metric.get("value")
        metric_names.append(name)
        if not _is_number(value):
            continue
        observed = round(float(value), 2)
        if _metric_name_matches(name, {"main_sleep_duration", "sleep_duration"}):
            sleep_hours = (
                round(observed / 3600, 2)
                if unit in {"s", "seconds"}
                else round(observed, 2)
            )
        if _metric_name_matches(name, {"running_distance"}) and unit == "km":
            running_distance = round(observed, 3)
        if _metric_name_matches(name, {"resting_heart_rate"}) and unit == "bpm":
            health_facts["resting_heart_rate_bpm"] = observed
            review_health_parts.append(f"静息心率 {observed:g} bpm")
        if name in LAST_NIGHT_HRV_METRIC_NAMES and unit == "ms":
            health_facts["hrv_last_night_average_ms"] = observed
            review_health_parts.append(f"昨夜 HRV {observed:g} ms")
        if _metric_name_matches(name, {"weight"}) and unit == "kg":
            health_facts["weight_kg"] = observed
            review_health_parts.append(f"体重记录 {observed:g} kg")
    if any(
        token in name
        for name in metric_names
        for token in (
            "running_distance",
            "climbing_duration",
            "activity_kind",
            "activity_duration",
        )
    ):
        activity_count = 1
    health_facts["sleep_hours"] = sleep_hours
    review_health_summary = (
        "昨日非睡眠健康记录：" + "；".join(review_health_parts) + "。"
        if review_health_parts
        else "昨日非睡眠健康数据未提供有效记录。"
    )
    return (
        health_facts,
        {
            "running_distance_km": running_distance,
            "activity_count": activity_count,
            "hard_load_count": 0,
            "hard_load_classification": "unavailable",
        },
        review_health_summary,
    )


def validate_weekly_advisory_language(
    value: object, *, execution_evidence_available: bool = False
) -> list[str]:
    """Reject claims that daily advice was executed without Host completion facts."""

    if execution_evidence_available:
        return []
    combined = " ".join(_iter_text(value))
    if any(
        pattern.search(combined) for pattern in UNVERIFIED_ADVICE_EXECUTION_PATTERNS
    ):
        return ["unverified_adjustment_execution_claim"]
    return []


def validate_training_plan_v2(value: object) -> list[str]:
    """Return stable errors for a versioned seven-day plan."""

    if not isinstance(value, dict):
        return ["course_not_object"]
    errors: list[str] = []
    if value.get("schema_version") != "training_plan_v2":
        errors.append("training_plan_schema_version_invalid")
    if value.get("provider_calls") != 0:
        errors.append("provider_calls_must_be_zero")
    if value.get("progression_rule") not in {"advance", "hold", "deload"}:
        errors.append("progression_rule_invalid")
    if value.get("progression_dimension") not in {"distance", "intensity", "none"}:
        errors.append("progression_dimension_invalid")
    if _contains_forbidden_prescription(value):
        errors.append("heart_rate_prescription_forbidden")

    items = value.get("items")
    if not isinstance(items, list) or len(items) != 7:
        return sorted(set(errors + ["course_must_cover_seven_days"]))

    parsed_dates: list[date] = []
    hard_dates: list[date] = []
    sos_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item_{index}_not_object")
            continue
        try:
            parsed = date.fromisoformat(str(item.get("date")))
            parsed_dates.append(parsed)
        except ValueError:
            errors.append(f"item_{index}_date_invalid")
            continue
        session_type = item.get("session_type")
        if session_type not in SESSION_TYPES:
            errors.append(f"item_{index}_session_type_invalid")
        if session_type in SOS_TYPES:
            sos_items.append(item)
        if session_type in HARD_TYPES or item.get("load_level") == "hard":
            hard_dates.append(parsed)
        if not isinstance(item.get("purpose"), str) or not item["purpose"].strip():
            errors.append(f"item_{index}_purpose_missing")
        rpe_min = item.get("rpe_min")
        rpe_max = item.get("rpe_max")
        if not (
            _is_number(rpe_min)
            and _is_number(rpe_max)
            and 1 <= float(rpe_min) <= float(rpe_max) <= 10
        ):
            errors.append(f"item_{index}_rpe_invalid")
        if (
            not isinstance(item.get("feel_guidance"), str)
            or not item["feel_guidance"].strip()
        ):
            errors.append(f"item_{index}_feel_guidance_missing")
        raw_steps = item.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        phases = {step.get("phase") for step in steps if isinstance(step, dict)}
        if not REQUIRED_PHASES.issubset(phases):
            errors.append(f"item_{index}_required_phases_missing")
        if not _nonempty_strings(item.get("start_gate")):
            errors.append(f"item_{index}_start_gate_missing")
        if not _nonempty_strings(item.get("technique_notes")):
            errors.append(f"item_{index}_technique_notes_missing")
        if (
            not isinstance(item.get("downgrade_rule"), str)
            or not item["downgrade_rule"].strip()
        ):
            errors.append(f"item_{index}_downgrade_rule_missing")
        if not _nonempty_strings(item.get("stop_conditions")):
            errors.append(f"item_{index}_stop_conditions_missing")
        if item.get("activity_kind") == "running" and not (
            _is_number(item.get("duration_minutes"))
            or _is_number(item.get("distance_km"))
        ):
            errors.append(f"item_{index}_dose_missing")
        reference = item.get("reference_pace")
        if reference is not None:
            if session_type in SOS_TYPES:
                errors.append("sos_reference_pace_forbidden")
            elif session_type not in REFERENCE_PACE_TYPES:
                errors.append(f"item_{index}_reference_pace_not_applicable")
            elif (
                not isinstance(reference, dict)
                or reference.get("schema_version") != "comparable_pace_reference_v1"
            ):
                errors.append(f"item_{index}_reference_pace_invalid")

    if len(set(parsed_dates)) != len(parsed_dates):
        errors.append("duplicate_course_date")
    if len(parsed_dates) == 7:
        ordered = sorted(parsed_dates)
        if any(
            right - left != timedelta(days=1)
            for left, right in zip(ordered, ordered[1:])
        ):
            errors.append("course_dates_not_contiguous")
    hard_dates = sorted(set(hard_dates))
    if len(hard_dates) > 3:
        errors.append("hard_load_count_exceeds_three")
    if any((right - left).days < 3 for left, right in zip(hard_dates, hard_dates[1:])):
        errors.append("hard_load_gap_less_than_three_days")

    rule = value.get("progression_rule")
    if rule in {"hold", "advance"} and len(sos_items) != 1:
        errors.append("sos_count_must_equal_one")
    if rule == "deload" and not sos_items:
        reason = value.get("sos_omission_reason")
        if reason is None:
            errors.append("sos_omission_reason_missing")
        elif not (
            isinstance(reason, dict)
            and reason.get("reason_code")
            in {"deload", "red_flag", "insufficient_recovery"}
            and isinstance(reason.get("explanation"), str)
            and reason["explanation"].strip()
            and isinstance(reason.get("evidence_refs"), list)
            and bool(reason["evidence_refs"])
            and all(
                isinstance(ref, int) and not isinstance(ref, bool) and ref > 0
                for ref in reason["evidence_refs"]
            )
        ):
            errors.append("sos_omission_reason_invalid")
    if len(sos_items) == 1:
        sos_date = date.fromisoformat(str(sos_items[0]["date"]))
        if sos_date.weekday() != 2:
            reason = value.get("sos_schedule_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append("sos_non_wednesday_reason_missing")
    return sorted(set(errors))


def validate_observed_health_facts(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["observed_health_facts_not_object"]
    forbidden_keys = {
        "heart_rate_zone",
        "target_bpm",
        "max_heart_rate",
        "threshold_bpm",
    }
    return (
        ["heart_rate_prescription_forbidden"] if forbidden_keys & value.keys() else []
    )


def validate_daily_adjustment(
    planned: object,
    effective: object,
    adjustment: str,
    *,
    safety: str = "ready",
    adjustment_reason_codes: list[str] | None = None,
) -> list[str]:
    if not isinstance(planned, dict) or not isinstance(effective, dict):
        return ["daily_course_not_object"]
    errors: list[str] = []
    if _contains_forbidden_prescription(planned) or _contains_forbidden_prescription(
        effective
    ):
        errors.append("heart_rate_prescription_forbidden")
    for label, course in (("planned", planned), ("effective", effective)):
        steps = course.get("steps")
        phases = (
            {step.get("phase") for step in steps if isinstance(step, dict)}
            if isinstance(steps, list)
            else set()
        )
        if not REQUIRED_PHASES.issubset(phases):
            errors.append(f"daily_{label}_course_required_phases_missing")
    if adjustment not in {"as_planned", "modified", "rest", "blocked", "unavailable"}:
        errors.append("daily_adjustment_invalid")
    if planned.get("date") != effective.get("date"):
        errors.append("daily_course_date_changed")
    for field in ("duration_minutes", "distance_km", "rpe_min", "rpe_max"):
        old = planned.get(field)
        new = effective.get(field)
        if _is_number(old) and _is_number(new) and float(new) > float(old):
            errors.append("daily_course_dose_increased")
    planned_hard = planned.get("session_type") in HARD_TYPES
    effective_hard = effective.get("session_type") in HARD_TYPES
    if effective_hard and not planned_hard:
        errors.append("daily_course_intensity_increased")
    if (
        planned.get("session_type") in SOS_TYPES
        and effective.get("session_type") not in SOS_TYPES
        and safety == "caution"
        and not (
            {"red_flag", "insufficient_recovery"} & set(adjustment_reason_codes or [])
        )
    ):
        errors.append("sos_downgrade_evidence_missing")
    if adjustment == "as_planned" and planned != effective:
        errors.append("as_planned_course_changed")
    return sorted(set(errors))


def build_daily_evidence_rollup_v1(
    context: dict[str, Any],
    planned_course: dict[str, Any],
    *,
    plan_output_id: int,
    plan_sha256: str,
    planned_course_context: str,
) -> dict[str, Any]:
    """Strip an existing bounded context to the v2 facts the coach may see."""

    if context.get("status") != "ready":
        raise ValueError("daily_context_not_ready")
    if planned_course_context not in PLANNED_COURSE_CONTEXTS:
        raise ValueError("planned_course_context_invalid")
    health = []
    for item in context.get("health", []):
        if not isinstance(item, dict):
            continue
        health.append(
            {
                "resource": item.get("resource"),
                "data_date": item.get("data_date"),
                "metrics": deepcopy(item.get("metrics", {})),
                "evidence_ref": {
                    "raw_file_id": item.get("raw_file_id"),
                    "sha256": item.get("sha256"),
                },
            }
        )
    activities = []
    for item in context.get("activities", []):
        if not isinstance(item, dict):
            continue
        activities.append(
            {
                "activity_inventory_id": item.get("activity_inventory_id"),
                "data_date": item.get("data_date"),
                "summary": deepcopy(item.get("summary", {})),
                "observed_heart_rate": deepcopy(item.get("observed_heart_rate", {})),
                "evidence_ref": {
                    "raw_file_id": item.get("raw_file_id"),
                    "sha256": item.get("raw_sha256"),
                },
            }
        )
    return {
        "schema_version": "daily_evidence_rollup_v1",
        "status": "ready",
        "report_date": context.get("report_date"),
        "review_date": context.get("review_date"),
        "sleep_wake_date": context.get("sleep_wake_date"),
        "health": health,
        "activities": activities,
        "recent_trend": deepcopy(context.get("recent_trend", {})),
        "recent_health_metrics": deepcopy(context.get("recent_health_metrics", {})),
        "planned_course_ref": {
            "output_id": plan_output_id,
            "sha256": plan_sha256,
        },
        "planned_course_context": planned_course_context,
        "planned_course": deepcopy(planned_course),
        "comparable_pace_reference": deepcopy(context.get("comparable_pace_reference")),
        "provider_calls": 0,
    }


def build_daily_view_v2(
    *,
    report_date: str,
    safety: str,
    planned_course: dict[str, Any],
    effective_course: dict[str, Any],
    adjustment: str,
    yesterday_summary: str,
    recovery_summary: str,
    decision_reasons: list[str],
    adjustment_reason_codes: list[str],
    evidence_labels: list[str],
    planned_course_context: str,
    review_health_summary: str,
) -> dict[str, Any]:
    if planned_course_context not in PLANNED_COURSE_CONTEXTS:
        raise ValueError("planned_course_context_invalid")
    if not review_health_summary.strip():
        raise ValueError("review_health_summary_missing")
    health_summary = review_health_summary
    reader_errors = validate_reader_visible_text(
        {
            "planned_course": planned_course,
            "effective_course": effective_course,
        }
    )
    reader_errors += validate_narrative_visible_text(
        {
            "yesterday_summary": yesterday_summary,
            "recovery_summary": recovery_summary,
            "review_health_summary": health_summary,
            "decision_reasons": decision_reasons,
            "evidence_labels": evidence_labels,
        }
    )
    if reader_errors:
        raise ValueError(reader_errors[0])
    errors = validate_daily_adjustment(
        planned_course,
        effective_course,
        adjustment,
        safety=safety,
        adjustment_reason_codes=adjustment_reason_codes,
    )
    if errors:
        raise ValueError(errors[0])
    return {
        "schema_version": "daily_email_view_v2",
        "report_date": report_date,
        "safety": safety,
        "yesterday_summary": yesterday_summary,
        "recovery_summary": recovery_summary,
        "review_health_summary": health_summary,
        "planned_course_context": planned_course_context,
        "planned_course": deepcopy(planned_course),
        "adjustment": adjustment,
        "effective_course": deepcopy(effective_course),
        "decision_reasons": list(decision_reasons),
        "adjustment_reason_codes": list(adjustment_reason_codes),
        "evidence_labels": list(evidence_labels),
        "provider_calls": 0,
    }


def build_weekly_digest_v1(
    dailies: list[dict[str, Any]], history: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(dailies) != 7 or any(
        item.get("schema_version") != "daily_ai_result_v2" for item in dailies
    ):
        raise ValueError("weekly_requires_exactly_seven_v2_dailies")
    if len(history) > 4 or any(
        item.get("schema_version") != "weekly_ai_result_v2" for item in history
    ):
        raise ValueError("weekly_history_invalid")
    dates = [date.fromisoformat(str(item["report_date"])) for item in dailies]
    if any(right - left != timedelta(days=1) for left, right in zip(dates, dates[1:])):
        raise ValueError("weekly_daily_dates_not_contiguous")
    loads = [item.get("daily_load", {}) for item in dailies]
    health = [item.get("health_observations", {}) for item in dailies]
    sleep_values = [
        item.get("sleep_hours")
        for item in health
        if _is_number(item.get("sleep_hours"))
    ]
    return {
        "schema_version": "weekly_evidence_digest_v1",
        "period": f"{dates[0].isoformat()}/{dates[-1].isoformat()}",
        "daily_count": 7,
        "daily_refs": [deepcopy(item["evidence_refs"][0]) for item in dailies],
        "health_summary": {
            "sleep_average_hours": round(sum(sleep_values) / len(sleep_values), 2)
            if sleep_values
            else None,
            "caution_days": sum(item.get("safety") == "caution" for item in dailies),
            "blocked_days": sum(item.get("safety") == "blocked" for item in dailies),
        },
        "activity_summary": {
            "running_distance_km": round(
                sum(float(item.get("running_distance_km", 0)) for item in loads), 3
            ),
            "activity_count": sum(int(item.get("activity_count", 0)) for item in loads),
            "hard_load_count": sum(
                int(item.get("hard_load_count", 0)) for item in loads
            ),
        },
        "history_count": len(history),
        "provider_calls": 0,
    }


def build_weekly_view_v2(
    *,
    period: str,
    status: str,
    health_summary: str,
    activity_summary: str,
    insights: list[dict[str, str]],
    plan: dict[str, Any],
    uncertainty: list[str],
    execution_evidence_available: bool = False,
) -> dict[str, Any]:
    reader_errors = validate_reader_visible_text({"training_plan": plan})
    reader_errors += validate_narrative_visible_text(
        {
            "health_summary": health_summary,
            "activity_summary": activity_summary,
            "insights": insights,
            "uncertainty": uncertainty,
        }
    )
    if reader_errors:
        raise ValueError(reader_errors[0])
    advisory_errors = validate_weekly_advisory_language(
        {
            "health_summary": health_summary,
            "activity_summary": activity_summary,
            "insights": insights,
            "uncertainty": uncertainty,
        },
        execution_evidence_available=execution_evidence_available,
    )
    if advisory_errors:
        raise ValueError(advisory_errors[0])
    plan_errors = validate_training_plan_v2(plan)
    if plan_errors:
        raise ValueError(plan_errors[0])
    if not 3 <= len(insights) <= 5:
        raise ValueError("weekly_insight_count_invalid")
    for insight in insights:
        if not all(
            isinstance(insight.get(key), str) and insight[key].strip()
            for key in ("observation", "meaning", "action")
        ):
            raise ValueError("weekly_insight_invalid")
    return {
        "schema_version": "weekly_email_view_v2",
        "period": period,
        "status": status,
        "health_summary": health_summary,
        "activity_summary": activity_summary,
        "insights": deepcopy(insights),
        "training_plan": deepcopy(plan),
        "uncertainty": list(uncertainty),
        "provider_calls": 0,
    }
