"""Supported wire grammar, independent of retired daily response schemas."""

from __future__ import annotations

import json
from typing import Any

import pytest

from skills._shared.scripts import structured_outputs_validation

UNSUPPORTED_KEYWORDS = {
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
}


def _validator():
    return structured_outputs_validation


def _schema():
    props = {
        "schema_version": {"type": "string", "const": "public"},
        "status": {"type": "string", "const": "public"},
        "safety": {"type": "string", "enum": ["public"]},
        "provider_calls": {"type": "integer", "const": 0},
        "summary": {"type": "string"},
        "bounded_metrics": {"type": "array", "items": {"$ref": "#/$defs/metric"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
        "$defs": {
            "metric": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {"value": {"type": "number"}},
            }
        },
    }


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_codex_wire_schema_uses_supported_strict_subset() -> None:
    schema = _schema()
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
    schema = _schema()
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
    schema = _schema()
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

    non_strict = _schema()
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
