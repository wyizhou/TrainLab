#!/usr/bin/env python3
"""Validate a bounded Skill payload against the local Draft 2020-12 schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


def schema_root() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas"


def schema_documents(
    names: tuple[str, ...], root: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Read only named contracts and their local reference closure; never fetch."""
    directory = schema_root() if root is None else root
    documents: dict[str, dict[str, Any]] = {}

    def read(name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name):
            raise ValueError("schema_dependency_invalid")
        if name in documents:
            return
        try:
            path = directory / f"{name}.schema.json"
            if path.is_symlink():
                raise ValueError("linked contract")
            body = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(body, dict):
                raise ValueError("contract must be object")
            Draft202012Validator.check_schema(body)
            documents[name] = body
            visit(body)
        except Exception:
            raise ValueError("schema_dependency_invalid") from None

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"}:
                    if not isinstance(item, str):
                        raise ValueError("schema_dependency_invalid")
                    target = item.split("#", 1)[0]
                    if target:
                        if target.startswith("urn:trainlab:"):
                            target = target.removeprefix("urn:trainlab:")
                        elif target.startswith("https://trainlab.local/schemas/"):
                            target = target.removeprefix(
                                "https://trainlab.local/schemas/"
                            )
                        elif ":" in target or "/" in target or "\\" in target:
                            raise ValueError("schema_dependency_invalid")
                        read(target.removesuffix(".schema.json"))
                else:
                    visit(item)

    for name in names:
        read(name)
    return documents


def validate_payload(
    payload: object, schema_name: str, *, root: Path | None = None
) -> list[str]:
    directory = schema_root() if root is None else root
    schema_path = directory / f"{schema_name}.schema.json"
    if not schema_path.is_file():
        return ["schema_not_found"]
    documents = schema_documents((schema_name,), directory)
    schema = documents[schema_name]
    resources: list[tuple[str, Resource[object]]] = []
    for name, candidate_schema in documents.items():
        resource = Resource.from_contents(
            candidate_schema, default_specification=DRAFT202012
        )
        resources.extend(
            (alias, resource)
            for alias in (
                f"urn:trainlab:{name}",
                f"{name}.schema.json",
                f"https://trainlab.local/schemas/{name}.schema.json",
            )
        )
        identifier = candidate_schema.get("$id")
        if isinstance(identifier, str):
            resources.append((identifier, resource))
    registry = Registry().with_resources(resources)
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
        registry=registry,
    )
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    result = [
        f"{'.'.join(str(part) for part in error.path) or '$'}:{error.validator}"
        for error in errors
    ]
    return sorted(set(result))


def require_valid_payload(payload: Any, schema_name: str) -> None:
    errors = validate_payload(payload, schema_name)
    if errors:
        raise ValueError(f"{schema_name}_invalid:" + ",".join(errors[:3]))
