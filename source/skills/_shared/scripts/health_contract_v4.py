#!/usr/bin/env python3
"""VC-002 health-state semantics shared by the v4 builder and runner."""

from __future__ import annotations

from datetime import date

from skills._shared.scripts.schema_validation import validate_payload

HEALTH_METRIC_CODES = (
    "sleep:main_sleep",
    "rhr:resting_heart_rate",
    "hrv:hrv",
    "heart_rates:heart_rate",
    "max_metrics:vo2_max",
    "weigh_ins:weight",
)
EXACT_HEALTH_METRICS = {
    "rhr:resting_heart_rate",
    "hrv:hrv",
    "heart_rates:heart_rate",
}
RECENT_LIMITS = {"max_metrics:vo2_max": 30, "weigh_ins:weight": 14}


def _fact_schema_errors(fact: object, index: int) -> list[str]:
    return [
        f"health_fact_{index}_schema:{error}"
        for error in validate_payload(fact, "health_fact_v2")
    ]


def validate_health_facts_vc002(
    facts: object, *, health_date: str, sleep_wake_date: str
) -> list[str]:
    """Validate exactly six stateful health facts and their date semantics."""

    if not isinstance(facts, list):
        return ["health_facts_list_required"]
    errors: list[str] = []
    if len(facts) != len(HEALTH_METRIC_CODES):
        errors.append("health_fact_count_invalid")
    codes: list[str] = []
    for index, fact in enumerate(facts):
        errors.extend(_fact_schema_errors(fact, index))
        if not isinstance(fact, dict):
            continue
        code = fact.get("metric_code")
        if isinstance(code, str):
            codes.append(code)
        if (
            isinstance(code, str)
            and fact.get("status") == "missing"
            and fact.get("reason_code") == "outside_lookback"
            and code not in RECENT_LIMITS
        ):
            errors.append(f"{code}_missing_reason_invalid")
        if fact.get("status") != "available" or not isinstance(code, str):
            continue
        observed_text = fact.get("observed_date")
        if not isinstance(observed_text, str):
            continue
        try:
            observed = date.fromisoformat(observed_text)
            review = date.fromisoformat(health_date)
            wake = date.fromisoformat(sleep_wake_date)
        except ValueError:
            errors.append(f"health_fact_{index}_date_invalid")
            continue
        value = fact.get("value")
        if code == "sleep:main_sleep":
            if observed != wake or not isinstance(value, dict):
                errors.append("sleep_observed_date_invalid")
            elif value.get("sleep_wake_date") != sleep_wake_date:
                errors.append("sleep_wake_date_lineage_invalid")
        elif code in EXACT_HEALTH_METRICS:
            if observed != review:
                errors.append(f"{code}_exact_date_invalid")
        elif code in RECENT_LIMITS:
            age_days = (review - observed).days
            if age_days < 0 or age_days > RECENT_LIMITS[code]:
                errors.append(f"{code}_lookback_invalid")
            if not isinstance(value, dict):
                continue
            expected_selection = "exact_date" if age_days == 0 else "latest_prior"
            if (
                value.get("observed_date") != observed_text
                or value.get("age_days") != age_days
                or value.get("selection_kind") != expected_selection
            ):
                errors.append(f"{code}_freshness_invalid")
    if len(codes) != len(set(codes)):
        errors.append("health_metric_code_duplicate")
    if set(codes) != set(HEALTH_METRIC_CODES):
        errors.append("health_metric_code_set_invalid")
    return sorted(set(errors))


def health_raw_file_ids(facts: object) -> list[int]:
    """Return the unique raw IDs represented by available/insufficient facts."""

    if not isinstance(facts, list):
        return []
    return sorted(
        {
            int(reference["raw_file_id"])
            for fact in facts
            if isinstance(fact, dict)
            for reference in fact.get("raw_refs", [])
            if isinstance(reference, dict)
            and isinstance(reference.get("raw_file_id"), int)
        }
    )
