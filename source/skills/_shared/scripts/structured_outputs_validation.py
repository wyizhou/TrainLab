#!/usr/bin/env python3
"""Validate the narrow JSON Schema subset used by Codex Structured Outputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SUPPORTED_TYPES = {
    "string",
    "number",
    "boolean",
    "integer",
    "object",
    "array",
    "null",
}
ALLOWED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "$defs",
    "$ref",
    "enum",
    "const",
    "anyOf",
}
MAX_OBJECT_PROPERTIES = 5_000
MAX_DEPTH = 10
MAX_STRING_BUDGET = 120_000
MAX_ENUM_VALUES = 1_000
MAX_LARGE_ENUM_STRING_BUDGET = 15_000


class StructuredOutputSchemaError(ValueError):
    """The schema cannot be sent to Codex Structured Outputs."""


def _blocked(path: str, reason: str) -> StructuredOutputSchemaError:
    return StructuredOutputSchemaError(
        f"structured_output_schema_unsupported:{path}:{reason}"
    )


def _types(node: Mapping[str, Any], path: str) -> set[str]:
    raw = node.get("type")
    values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    if not values or any(not isinstance(item, str) for item in values):
        raise _blocked(path, "explicit_type_required")
    result = set(values)
    if len(result) != len(values) or not result.issubset(SUPPORTED_TYPES):
        raise _blocked(path, "type_invalid")
    return result


def _matches_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def require_supported_schema(schema: object) -> None:
    """Fail closed unless *schema* fits TrainLab's documented wire subset."""

    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise _blocked("$", "root_object_required")
    if "anyOf" in schema:
        raise _blocked("$", "root_anyof_forbidden")
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        raise _blocked("$.$defs", "definitions_invalid")

    property_count = 0
    enum_count = 0
    large_enum_string_budget = 0
    string_budget = 0
    active_refs: set[str] = set()

    def visit(
        node: object,
        path: str,
        depth: int,
        property_schema: bool,
        *,
        count_budget: bool,
    ) -> None:
        nonlocal property_count, enum_count, large_enum_string_budget, string_budget
        if depth > MAX_DEPTH:
            raise _blocked(path, "depth_exceeded")
        if not isinstance(node, dict):
            raise _blocked(path, "schema_node_not_object")
        unknown = set(node) - ALLOWED_KEYWORDS
        if unknown:
            raise _blocked(path, "keyword_not_allowed")

        if "$ref" in node:
            if set(node) != {"$ref"} or not isinstance(node["$ref"], str):
                raise _blocked(path, "reference_invalid")
            reference = node["$ref"]
            prefix = "#/$defs/"
            if not reference.startswith(prefix) or "/" in reference[len(prefix) :]:
                raise _blocked(path, "reference_external_or_nested")
            name = reference[len(prefix) :]
            target = definitions.get(name)
            if target is None:
                raise _blocked(path, "reference_missing")
            if reference in active_refs:
                raise _blocked(path, "reference_cycle")
            active_refs.add(reference)
            try:
                # Resolve every occurrence. A global "seen" set would let a shallow
                # first use hide the expanded depth of the same definition later.
                visit(
                    target,
                    f"{path}->$.$defs.{name}",
                    depth + 1,
                    True,
                    count_budget=False,
                )
            finally:
                active_refs.remove(reference)
            return

        if "anyOf" in node:
            branches = node["anyOf"]
            if set(node) != {"anyOf"} or not isinstance(branches, list) or not branches:
                raise _blocked(path, "anyof_invalid")
            for index, branch in enumerate(branches):
                visit(
                    branch,
                    f"{path}.anyOf[{index}]",
                    depth + 1,
                    True,
                    count_budget=count_budget,
                )
            return

        if property_schema or path == "$":
            types = _types(node, path)
        else:
            types = set()

        nested_definitions = node.get("$defs", {})
        if not isinstance(nested_definitions, dict):
            raise _blocked(f"{path}.$defs", "definitions_invalid")
        for name, definition in nested_definitions.items():
            if not isinstance(name, str):
                raise _blocked(f"{path}.$defs", "definition_name_invalid")
            if count_budget:
                string_budget += len(name)
            # Definitions are Schema nodes even when they are not referenced.
            # Linting them here prevents an unused or nested definition from
            # smuggling unsupported keywords into the wire contract.
            visit(
                definition,
                f"{path}.$defs.{name}",
                depth + 1,
                True,
                count_budget=count_budget,
            )

        if "const" in node:
            if not any(_matches_type(node["const"], item) for item in types):
                raise _blocked(path, "const_type_mismatch")
            if count_budget and isinstance(node["const"], str):
                string_budget += len(node["const"])
        if "enum" in node:
            enum = node["enum"]
            if not isinstance(enum, list) or not enum:
                raise _blocked(path, "enum_invalid")
            if any(
                not any(_matches_type(value, item) for item in types) for value in enum
            ):
                raise _blocked(path, "enum_type_mismatch")
            if count_budget:
                enum_count += len(enum)
            enum_strings = sum(len(item) for item in enum if isinstance(item, str))
            if count_budget:
                string_budget += enum_strings
                if len(enum) > 250:
                    large_enum_string_budget += enum_strings

        if "object" in types:
            properties = node.get("properties")
            required = node.get("required")
            if (
                not isinstance(properties, dict)
                or not isinstance(required, list)
                or any(not isinstance(item, str) for item in required)
                or len(required) != len(set(required))
                or set(required) != set(properties)
                or node.get("additionalProperties") is not False
            ):
                raise _blocked(path, "strict_object_required")
            if count_budget:
                property_count += len(properties)
            for name, child in properties.items():
                if not isinstance(name, str):
                    raise _blocked(path, "property_name_invalid")
                if count_budget:
                    string_budget += len(name)
                visit(
                    child,
                    f"{path}.properties.{name}",
                    depth + 1,
                    True,
                    count_budget=count_budget,
                )
        elif any(
            key in node for key in ("properties", "required", "additionalProperties")
        ):
            raise _blocked(path, "object_keywords_without_object")

        if "array" in types:
            if "items" not in node:
                raise _blocked(path, "array_items_required")
            visit(
                node["items"],
                f"{path}.items",
                depth + 1,
                True,
                count_budget=count_budget,
            )
        elif "items" in node:
            raise _blocked(path, "items_without_array")

    visit(schema, "$", 1, True, count_budget=True)
    if property_count > MAX_OBJECT_PROPERTIES:
        raise _blocked("$", "property_limit_exceeded")
    if string_budget > MAX_STRING_BUDGET:
        raise _blocked("$", "string_budget_exceeded")
    if enum_count > MAX_ENUM_VALUES:
        raise _blocked("$", "enum_limit_exceeded")
    if large_enum_string_budget > MAX_LARGE_ENUM_STRING_BUDGET:
        raise _blocked("$", "large_enum_string_budget_exceeded")
