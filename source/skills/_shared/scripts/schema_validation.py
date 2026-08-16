#!/usr/bin/env python3
"""Validate a bounded Skill payload against the local Draft 2020-12 schema."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def schema_root() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas"


def validate_payload(payload: object, schema_name: str) -> list[str]:
    schema_path = schema_root() / f"{schema_name}.schema.json"
    if not schema_path.is_file():
        return ["schema_not_found"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    result = [
        f"{'.'.join(str(part) for part in error.path) or '$'}:{error.validator}"
        for error in errors
    ]
    result.extend(_semantic_date_errors(payload, schema_name))
    return sorted(set(result))


def _semantic_date_errors(payload: object, schema_name: str) -> list[str]:
    """Validate dates embedded in identifiers that JSON Schema sees as strings."""
    if not isinstance(payload, dict):
        return []
    values: list[tuple[str, object]] = []
    if schema_name in {"weekly_summary_v1", "weekly_fitness_review_v1"}:
        values.append(("period", payload.get("period")))
    if schema_name == "workflow_receipt_v1":
        values.append(("workflow_key", payload.get("workflow_key")))
    if schema_name == "auto_result_v1":
        values.extend(
            (f"workflow_refs.{index}", value)
            for index, value in enumerate(payload.get("workflow_refs", []))
        )
    problems: list[str] = []
    for path, value in values:
        if not isinstance(value, str):
            continue
        candidates = (
            value.split("/") if path == "period" else [value.rsplit(":", 1)[-1]]
        )
        if path == "period":
            dates = candidates
        else:
            dates = candidates
        for candidate in dates:
            try:
                date.fromisoformat(candidate)
            except ValueError:
                problems.append(f"{path}:date")
    return problems


def require_valid_payload(payload: Any, schema_name: str) -> None:
    errors = validate_payload(payload, schema_name)
    if errors:
        raise ValueError(f"{schema_name}_invalid:" + ",".join(errors[:3]))
