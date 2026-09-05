#!/usr/bin/env python3
"""VC-010 model-decision, Host-envelope and Schema-parity contracts."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from copy import deepcopy
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.scripts.structured_outputs_validation import (
    ALLOWED_KEYWORDS,
    require_supported_schema,
)
from skills._shared.state import canonical_json

WIRE_REMOVABLE_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "format",
        "minimum",
        "maximum",
    }
)
DAY_KEYS = tuple(f"day_{index}" for index in range(1, 8))
ACTIVE_PHASES = ("warmup", "main", "recovery", "cooldown")
SOS_TYPES = {"sos_threshold", "sos_cruise_intervals", "sos_hills"}
HARD_TYPES = SOS_TYPES | {"climbing_hard"}
NUMERIC_BPM = re.compile(
    r"(?<![A-Za-z0-9])\d{1,3}(?:\.\d+)?\s*bpm\b", re.ASCII | re.IGNORECASE
)
ZONE_PRESCRIPTION = re.compile(
    r"(?<![A-Za-z0-9])(?:z|zone)\s*[1-5](?![A-Za-z0-9])", re.ASCII | re.IGNORECASE
)
HEART_RATE_PRESCRIPTION = re.compile(r"(?:目标|阈值|最大)心率|心率区间")
PROMPT_SEMANTICS_BEGIN = "TRAINLAB_PROMPT_SEMANTICS_V1_BEGIN"
PROMPT_SEMANTICS_END = "TRAINLAB_PROMPT_SEMANTICS_V1_END"
HOST_FORBIDDEN_FIELD_ORDER = (
    "period",
    "plan_dates",
    "date",
    "status",
    "provider_calls",
    "external_actions",
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("weekly_decision_dependency_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = _load_module(
    "trainlab_weekly_decision_v4_legacy_contract",
    Path(__file__).with_name("content_first_v4.py"),
)


def project_wire_schema(schema: object) -> dict[str, Any]:
    """Create the only permitted Structured Outputs projection."""

    def visit(node: object, path: str) -> object:
        if isinstance(node, list):
            return [visit(item, f"{path}[]") for item in node]
        if not isinstance(node, dict):
            return node
        unknown = set(node) - ALLOWED_KEYWORDS - WIRE_REMOVABLE_KEYWORDS
        if unknown:
            names = ",".join(sorted(unknown))
            raise ValueError(f"weekly_wire_projection_keyword_forbidden:{path}:{names}")
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key in WIRE_REMOVABLE_KEYWORDS:
                continue
            if key in {"properties", "$defs"}:
                if not isinstance(value, dict):
                    raise ValueError(
                        f"weekly_wire_projection_mapping_invalid:{path}.{key}"
                    )
                result[key] = {
                    str(name): visit(child, f"{path}.{key}.{name}")
                    for name, child in value.items()
                }
            else:
                result[key] = visit(value, f"{path}.{key}")
        return result

    projected = visit(schema, "$")
    if not isinstance(projected, dict):
        raise TypeError("weekly_wire_projection_root_invalid")
    require_supported_schema(projected)
    return projected


def require_wire_schema_parity(business_schema: object, wire_schema: object) -> None:
    projected = project_wire_schema(business_schema)
    if projected != wire_schema:
        raise ValueError("weekly_wire_schema_parity_failed")
    require_supported_schema(wire_schema)


def _schema_object(value: object, error: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(error)
    return value


def _schema_string_values(value: object) -> list[str]:
    node = _schema_object(value, "weekly_prompt_schema_topology_invalid")
    enum = node.get("enum")
    if isinstance(enum, list) and enum and all(isinstance(item, str) for item in enum):
        return list(enum)
    const = node.get("const")
    if isinstance(const, str):
        return [const]
    raise ValueError("weekly_prompt_schema_topology_invalid")


def prompt_semantics_from_schemas(
    business_schema: object, host_schema: object
) -> dict[str, Any]:
    """Derive the Prompt's complete machine structure from authoritative schemas."""

    business = _schema_object(business_schema, "weekly_prompt_schema_topology_invalid")
    host = _schema_object(host_schema, "weekly_prompt_schema_topology_invalid")
    properties = _schema_object(
        business.get("properties"), "weekly_prompt_schema_topology_invalid"
    )
    required = business.get("required")
    if (
        business.get("additionalProperties") is not False
        or not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or set(required) != set(properties)
    ):
        raise ValueError("weekly_prompt_schema_topology_invalid")

    definitions = _schema_object(
        business.get("$defs"), "weekly_prompt_schema_topology_invalid"
    )
    training_plan = _schema_object(
        definitions.get("training_plan"), "weekly_prompt_schema_topology_invalid"
    )
    plan_properties = _schema_object(
        training_plan.get("properties"), "weekly_prompt_schema_topology_invalid"
    )
    days = _schema_object(
        plan_properties.get("days"), "weekly_prompt_schema_topology_invalid"
    )
    day_properties = _schema_object(
        days.get("properties"), "weekly_prompt_schema_topology_invalid"
    )
    day_required = days.get("required")
    if (
        days.get("additionalProperties") is not False
        or list(day_properties) != list(DAY_KEYS)
        or day_required != list(DAY_KEYS)
    ):
        raise ValueError("weekly_prompt_schema_topology_invalid")

    topology: tuple[str, ...] | None = None
    for day in DAY_KEYS:
        day_schema = _schema_object(
            day_properties.get(day), "weekly_prompt_schema_topology_invalid"
        )
        choices = day_schema.get("anyOf")
        if not isinstance(choices, list) or not choices:
            raise ValueError("weekly_prompt_schema_topology_invalid")
        refs: list[str] = []
        for choice in choices:
            choice_node = _schema_object(
                choice, "weekly_prompt_schema_topology_invalid"
            )
            if set(choice_node) != {"$ref"} or not isinstance(choice_node["$ref"], str):
                raise ValueError("weekly_prompt_schema_topology_invalid")
            refs.append(choice_node["$ref"])
        current = tuple(refs)
        if topology is None:
            topology = current
        elif current != topology:
            raise ValueError("weekly_prompt_schema_topology_invalid")
    if topology is None:
        raise ValueError("weekly_prompt_schema_topology_invalid")

    variants: dict[str, dict[str, list[str]]] = {}
    for reference in topology:
        prefix = "#/$defs/"
        if not reference.startswith(prefix):
            raise ValueError("weekly_prompt_schema_topology_invalid")
        course = _schema_object(
            definitions.get(reference.removeprefix(prefix)),
            "weekly_prompt_schema_topology_invalid",
        )
        course_properties = _schema_object(
            course.get("properties"), "weekly_prompt_schema_topology_invalid"
        )
        activity_kind_values = _schema_string_values(
            course_properties.get("activity_kind")
        )
        if len(activity_kind_values) != 1:
            raise ValueError("weekly_prompt_schema_topology_invalid")
        activity_kind = activity_kind_values[0]
        steps = _schema_object(
            course_properties.get("steps"), "weekly_prompt_schema_topology_invalid"
        )
        step_properties = _schema_object(
            steps.get("properties"), "weekly_prompt_schema_topology_invalid"
        )
        phase_keys = steps.get("required")
        if (
            steps.get("additionalProperties") is not False
            or not isinstance(phase_keys, list)
            or not all(isinstance(item, str) for item in phase_keys)
            or set(phase_keys) != set(step_properties)
            or activity_kind in variants
        ):
            raise ValueError("weekly_prompt_schema_topology_invalid")
        variants[activity_kind] = {
            "session_types": _schema_string_values(
                course_properties.get("session_type")
            ),
            "phase_keys": list(phase_keys),
        }
    if set(variants) != {"running", "climbing", "rest"}:
        raise ValueError("weekly_prompt_schema_topology_invalid")

    host_properties = _schema_object(
        host.get("properties"), "weekly_prompt_schema_topology_invalid"
    )
    host_required = host.get("required")
    derived_host_fields = (set(host_properties) - {"schema_version", "decision"}) | {
        "date"
    }
    if (
        host.get("additionalProperties") is not False
        or not isinstance(host_required, list)
        or set(host_required) != set(host_properties)
        or derived_host_fields != set(HOST_FORBIDDEN_FIELD_ORDER)
    ):
        raise ValueError("weekly_prompt_schema_topology_invalid")

    return {
        "schema_version": "weekly_prompt_semantics_v1",
        "root_allowed_fields": sorted(properties),
        "root_required_fields": sorted(required),
        "day_slots": list(DAY_KEYS),
        "course_variants": variants,
        "forbidden_host_fields": list(HOST_FORBIDDEN_FIELD_ORDER),
    }


def parse_prompt_semantics(prompt_bytes: bytes) -> dict[str, Any]:
    """Read the one canonical Prompt semantics block without inference."""

    try:
        prompt = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("weekly_prompt_semantics_invalid") from exc
    begin_count = prompt.count(PROMPT_SEMANTICS_BEGIN)
    end_count = prompt.count(PROMPT_SEMANTICS_END)
    if begin_count == 0 or end_count == 0:
        raise ValueError("weekly_prompt_semantics_missing")
    if begin_count != 1 or end_count != 1:
        raise ValueError("weekly_prompt_semantics_duplicate")
    prefix, remainder = prompt.split(PROMPT_SEMANTICS_BEGIN, 1)
    body, suffix = remainder.split(PROMPT_SEMANTICS_END, 1)
    del prefix, suffix
    if not body.startswith("\n") or not body.endswith("\n"):
        raise ValueError("weekly_prompt_semantics_noncanonical")
    line = body[1:-1]
    if not line or "\n" in line or "\r" in line:
        raise ValueError("weekly_prompt_semantics_noncanonical")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("weekly_prompt_semantics_invalid") from exc
    if not isinstance(value, dict) or validate_payload(
        value, "weekly_prompt_semantics_v1"
    ):
        raise ValueError("weekly_prompt_semantics_invalid")
    if canonical_json(value) != line:
        raise ValueError("weekly_prompt_semantics_noncanonical")
    return value


def require_prompt_schema_semantic_parity(
    prompt_bytes: bytes, business_schema: object, host_schema: object
) -> None:
    parsed = parse_prompt_semantics(prompt_bytes)
    expected = prompt_semantics_from_schemas(business_schema, host_schema)
    if parsed != expected:
        raise ValueError("weekly_prompt_schema_semantic_parity_failed")


def _all_text(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _all_text(item)]
    return [value] if isinstance(value, str) else []


def _course_to_legacy(course: dict[str, Any], course_date: str) -> dict[str, Any]:
    steps = course["steps"]
    phases = ("checklist",) if course["activity_kind"] == "rest" else ACTIVE_PHASES
    return {
        "date": course_date,
        "activity_kind": course["activity_kind"],
        "session_type": course["session_type"],
        "name": course["name"],
        "purpose": course["purpose"],
        "load_level": course["load_level"],
        "duration_minutes": course["duration_minutes"],
        "rpe_min": course["rpe_min"],
        "rpe_max": course["rpe_max"],
        "feel_guidance": course["feel_guidance"],
        "steps": [{"phase": phase, **deepcopy(steps[phase])} for phase in phases],
        "technique_notes": deepcopy(course["technique_notes"]),
        "stop_conditions": deepcopy(course["stop_conditions"]),
    }


def _compatibility_result(
    decision: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    period = evidence["period"]
    start = date.fromisoformat(str(period["sleep_wake_end_date"])) + timedelta(days=1)
    plan = decision["training_plan"]
    items = [
        _course_to_legacy(
            plan["days"][key], (start + timedelta(days=index)).isoformat()
        )
        for index, key in enumerate(DAY_KEYS)
    ]
    return {
        "schema_version": "weekly_ai_result_v3",
        "status": "succeeded",
        "period": f"{period['activity_start_date']}/{period['activity_end_date']}",
        "week_conclusion": decision["week_conclusion"],
        "health_review": decision["health_review"],
        "all_activity_review": decision["all_activity_review"],
        "technical_findings": deepcopy(decision["technical_findings"]),
        "plan_comparison": decision["plan_comparison"],
        "climbing_and_combined_load": decision["climbing_and_combined_load"],
        "progression_decision": decision["progression_decision"],
        "training_plan": {
            "schema_version": "training_plan_v3",
            "status": "succeeded",
            "progression_rule": plan["progression_rule"],
            "progression_dimension": plan["progression_dimension"],
            "sos_omission_reason": deepcopy(plan["sos_omission_reason"]),
            "sos_schedule_reason": plan["sos_schedule_reason"],
            "items": items,
            "provider_calls": 0,
        },
        "uncertainty": deepcopy(decision["uncertainty"]),
        "evidence_refs": deepcopy(decision["evidence_refs"]),
        "provider_calls": 0,
    }


def validate_weekly_model_decision_v1(
    value: object, evidence: dict[str, Any]
) -> list[str]:
    errors = validate_payload(value, "weekly_model_decision_v1")
    if not isinstance(value, dict) or errors:
        return sorted(set(errors or ["weekly_model_decision_not_object"]))
    if any(
        pattern.search(text)
        for text in _all_text(value)
        for pattern in (NUMERIC_BPM, ZONE_PRESCRIPTION, HEART_RATE_PRESCRIPTION)
    ):
        errors.append("model_heart_rate_text_forbidden")
    legacy = _compatibility_result(value, evidence)
    legacy_errors = LEGACY.validate_weekly_ai_result_v3(legacy, evidence)
    for error in legacy_errors:
        if error == "heart_rate_prescription_forbidden":
            errors.append("model_heart_rate_text_forbidden")
        else:
            errors.append(error)
    if value.get("progression_decision") != value["training_plan"].get(
        "progression_rule"
    ):
        errors.append("progression_decision_mismatch")
    return sorted(set(errors))


def assemble_weekly_ai_result_v4(
    decision: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    evidence = context.get("weekly_evidence")
    dates = context.get("next_plan_dates")
    if not isinstance(evidence, dict) or not isinstance(dates, list) or len(dates) != 7:
        raise ValueError("weekly_host_context_invalid")
    decision_errors = validate_weekly_model_decision_v1(decision, evidence)
    if decision_errors:
        raise ValueError(
            "weekly_model_decision_invalid:" + ",".join(decision_errors[:3])
        )
    parsed = [date.fromisoformat(str(item)) for item in dates]
    if any(later - earlier != timedelta(days=1) for earlier, later in pairwise(parsed)):
        raise ValueError("weekly_host_plan_dates_invalid")
    period = evidence["period"]
    result = {
        "schema_version": "weekly_ai_result_v4",
        "status": "succeeded",
        "period": {
            "activity_start_date": str(period["activity_start_date"]),
            "activity_end_date": str(period["activity_end_date"]),
            "sleep_wake_start_date": str(period["sleep_wake_start_date"]),
            "sleep_wake_end_date": str(period["sleep_wake_end_date"]),
            "plan_start_date": parsed[0].isoformat(),
            "plan_end_date": parsed[-1].isoformat(),
        },
        "plan_dates": {
            key: parsed[index].isoformat() for index, key in enumerate(DAY_KEYS)
        },
        "decision": deepcopy(decision),
        "provider_calls": 0,
        "external_actions": 0,
    }
    errors = validate_weekly_ai_result_v4(result, evidence, context)
    if errors:
        raise ValueError("weekly_ai_result_v4_invalid:" + ",".join(errors[:3]))
    return result


def validate_weekly_ai_result_v4(
    value: object,
    evidence: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    errors = validate_payload(value, "weekly_ai_result_v4")
    if not isinstance(value, dict) or errors:
        return sorted(set(errors or ["weekly_ai_result_v4_not_object"]))
    errors.extend(validate_weekly_model_decision_v1(value["decision"], evidence))
    expected_period = evidence["period"]
    dates = [str(item) for item in context.get("next_plan_dates", [])]
    expected_plan_dates = (
        {key: dates[index] for index, key in enumerate(DAY_KEYS)}
        if len(dates) == 7
        else {}
    )
    if value.get("plan_dates") != expected_plan_dates:
        errors.append("weekly_host_plan_dates_mismatch")
    expected = {
        **expected_period,
        "plan_start_date": dates[0] if dates else "",
        "plan_end_date": dates[-1] if dates else "",
    }
    if value.get("period") != expected:
        errors.append("weekly_host_period_mismatch")
    days = value["decision"]["training_plan"]["days"]
    sos_keys = [key for key in DAY_KEYS if days[key]["session_type"] in SOS_TYPES]
    schedule_reason = value["decision"]["training_plan"]["sos_schedule_reason"]
    if sos_keys:
        sos_date = date.fromisoformat(expected_plan_dates[sos_keys[0]])
        if sos_date.weekday() != 2 and not (
            isinstance(schedule_reason, str) and schedule_reason.strip()
        ):
            errors.append("sos_non_wednesday_reason_missing")
    return sorted(set(errors))


def load_and_require_repository_schema_parity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "_shared/schemas"
    prompt_path = (
        Path(__file__).resolve().parents[2] / "_shared/prompts/weekly-content-v4-v4.txt"
    )
    business = json.loads(
        (root / "weekly_model_decision_v1.schema.json").read_text(encoding="utf-8")
    )
    wire = json.loads(
        (root / "weekly_model_decision_v1_codex.schema.json").read_text(
            encoding="utf-8"
        )
    )
    host = json.loads(
        (root / "weekly_ai_result_v4.schema.json").read_text(encoding="utf-8")
    )
    require_wire_schema_parity(business, wire)
    require_prompt_schema_semantic_parity(prompt_path.read_bytes(), business, host)
    return {
        "business_path": root / "weekly_model_decision_v1.schema.json",
        "wire_path": root / "weekly_model_decision_v1_codex.schema.json",
        "host_path": root / "weekly_ai_result_v4.schema.json",
        "prompt_path": prompt_path,
        "business_schema": business,
        "wire_schema": wire,
        "host_schema": host,
    }
