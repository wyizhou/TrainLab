from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts.schema_validation import validate_payload

ROOT = Path(__file__).resolve().parents[3]
V1_SCHEMA = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
V2_SCHEMA = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v2.schema.json"
V1_SHA256 = "b223f5b590e89e840b2581a69dcf942fe91d00cd8b4f42819d3dab352ba6c3f7"
UNSUPPORTED_KEYWORDS = {
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
}


def _succeeded_payload() -> dict[str, Any]:
    return {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "error_code": None,
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "合成日报。",
        "bounded_metrics": [
            {"name": "rhr", "value": 52, "unit": "bpm", "evidence_ref": 1}
        ],
        "stop_conditions": ["出现危险信号时停止。"],
        "evidence_refs": [
            {"raw_file_id": 1, "sha256": "a" * 64, "claim": "合成证据。"}
        ],
        "recent_trend_sha256": "b" * 64,
        "today_course": {},
        "provider_calls": 0,
    }


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _validator():
    path = ROOT / "skills/_shared/scripts/structured_outputs_validation.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_structured_outputs_validation", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_wire_v1_is_preserved_as_failed_attempt_evidence() -> None:
    import hashlib

    assert hashlib.sha256(V1_SCHEMA.read_bytes()).hexdigest() == V1_SHA256


def test_wire_v2_diff_is_only_the_four_explicit_types() -> None:
    v1 = json.loads(V1_SCHEMA.read_text(encoding="utf-8"))
    v2 = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    for field in ("schema_version", "status", "safety", "provider_calls"):
        del v2["properties"][field]["type"]
    assert v2 == v1


def test_codex_wire_schema_uses_supported_strict_subset() -> None:
    schema = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    _validator().require_supported_schema(schema)
    assert schema["type"] == "object"
    for node in _walk(schema):
        if not isinstance(node, dict):
            continue
        assert UNSUPPORTED_KEYWORDS.isdisjoint(node)
        if node.get("type") == "object":
            properties = node.get("properties", {})
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(properties)


@pytest.mark.parametrize(
    "field, expected_type",
    [
        ("schema_version", "string"),
        ("status", "string"),
        ("safety", "string"),
        ("provider_calls", "integer"),
    ],
)
def test_const_and_enum_fields_require_explicit_type(
    field: str, expected_type: str
) -> None:
    schema = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"][field]["type"] == expected_type
    del schema["properties"][field]["type"]
    with pytest.raises(ValueError, match="structured_output_schema_unsupported"):
        _validator().require_supported_schema(schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda schema: schema.update({"anyOf": [{"type": "object"}]}),
        lambda schema: schema["properties"]["summary"].update({"default": "x"}),
        lambda schema: schema["properties"]["summary"].update({"oneOf": []}),
        lambda schema: schema["properties"]["bounded_metrics"].pop("items"),
        lambda schema: schema["properties"]["bounded_metrics"].update(
            {"items": {"$ref": "https://example.invalid/schema"}}
        ),
    ],
)
def test_wire_linter_rejects_unsupported_shapes(mutation: Any) -> None:
    schema = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    mutation(schema)
    with pytest.raises(ValueError, match="structured_output_schema_unsupported"):
        _validator().require_supported_schema(schema)


def test_wire_linter_rejects_missing_reference_and_non_strict_object() -> None:
    missing_ref = {
        "type": "object",
        "additionalProperties": False,
        "required": ["item"],
        "properties": {"item": {"$ref": "#/$defs/missing"}},
        "$defs": {},
    }
    with pytest.raises(ValueError, match="reference_missing"):
        _validator().require_supported_schema(missing_ref)

    non_strict = json.loads(V2_SCHEMA.read_text(encoding="utf-8"))
    non_strict["$defs"]["metric"]["additionalProperties"] = True
    with pytest.raises(ValueError, match="strict_object_required"):
        _validator().require_supported_schema(non_strict)


def test_wire_linter_checks_unused_nested_definitions_and_required_uniqueness() -> None:
    validator = _validator()
    base = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "string"}},
    }

    unused = json.loads(json.dumps(base))
    unused["$defs"] = {"hidden": {"type": "string", "default": "x"}}
    with pytest.raises(ValueError, match="keyword_not_allowed"):
        validator.require_supported_schema(unused)

    nested = json.loads(json.dumps(base))
    nested["properties"]["value"]["$defs"] = {
        "hidden": {"type": "string", "default": "x"}
    }
    with pytest.raises(ValueError, match="keyword_not_allowed"):
        validator.require_supported_schema(nested)

    duplicate_required = json.loads(json.dumps(base))
    duplicate_required["required"] = ["value", "value"]
    with pytest.raises(ValueError, match="strict_object_required"):
        validator.require_supported_schema(duplicate_required)


def test_wire_linter_recomputes_depth_for_each_reference_occurrence() -> None:
    validator = _validator()
    definition = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "string"}},
    }
    deep: dict[str, Any] = {"$ref": "#/$defs/shared"}
    for index in range(9):
        deep = {
            "type": "object",
            "additionalProperties": False,
            "required": [f"level_{index}"],
            "properties": {f"level_{index}": deep},
        }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["shallow", "deep"],
        "properties": {
            "shallow": {"$ref": "#/$defs/shared"},
            "deep": deep,
        },
        "$defs": {"shared": definition},
    }
    with pytest.raises(ValueError, match="depth_exceeded"):
        validator.require_supported_schema(schema)


def test_wire_linter_rejects_depth_property_string_and_enum_limits() -> None:
    validator = _validator()
    leaf: dict[str, Any] = {"type": "string"}
    for index in range(11):
        leaf = {
            "type": "object",
            "additionalProperties": False,
            "required": [f"level_{index}"],
            "properties": {f"level_{index}": leaf},
        }
    with pytest.raises(ValueError, match="depth_exceeded"):
        validator.require_supported_schema(leaf)

    names = [f"field_{index}" for index in range(5_001)]
    too_many_properties = {
        "type": "object",
        "additionalProperties": False,
        "required": names,
        "properties": {name: {"type": "string"} for name in names},
    }
    with pytest.raises(ValueError, match="property_limit_exceeded"):
        validator.require_supported_schema(too_many_properties)

    long_name = "x" * 120_001
    too_many_strings = {
        "type": "object",
        "additionalProperties": False,
        "required": [long_name],
        "properties": {long_name: {"type": "string"}},
    }
    with pytest.raises(ValueError, match="string_budget_exceeded"):
        validator.require_supported_schema(too_many_strings)

    too_many_enum_values = {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice"],
        "properties": {
            "choice": {
                "type": "string",
                "enum": [f"value_{index}" for index in range(1_001)],
            }
        },
    }
    with pytest.raises(ValueError, match="enum_limit_exceeded"):
        validator.require_supported_schema(too_many_enum_values)


def test_codex_wire_payload_must_also_pass_original_business_schema() -> None:
    payload = _succeeded_payload()
    assert validate_payload(payload, "daily_ai_result_codex_v2") == []
    assert validate_payload(payload, "daily_ai_result_v1") == []


def test_original_business_schema_is_not_weakened_by_wire_schema() -> None:
    missing_success_fields = _succeeded_payload()
    del missing_success_fields["bounded_metrics"]
    del missing_success_fields["stop_conditions"]
    assert validate_payload(missing_success_fields, "daily_ai_result_v1")

    blocked_without_error = _succeeded_payload()
    blocked_without_error["status"] = "blocked"
    del blocked_without_error["error_code"]
    assert validate_payload(blocked_without_error, "daily_ai_result_v1")
