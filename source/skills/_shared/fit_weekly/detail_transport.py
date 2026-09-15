"""Lossless, model-readable FIT tables and a public CLI handoff checker.

Only repeated field names/values are factored out. No bin, numeric precision,
missing value, sample count or source binding is discarded. This pure codec is
not a model launcher or proof that a particular model has sufficient context.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from skills._shared.fit_weekly import fit_detail, fit_parse, storage

VERSION = "fit_detail_table_v1"
SCHEMAS = {
    "fit-summary-1": VERSION,
    "fit-summary-2": "fit_detail_table_v2",
    "fit-summary-3": "fit_detail_table_v3",
}
TABLE_FIELDS = {"block_defaults", "block_columns", "block_rows", "detail_sha256"}
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_detail_table_v1.schema.json"
)


def flattened(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result = {}
    for name, child in value.items():
        key = prefix + name
        if isinstance(child, dict):
            result.update(flattened(child, key + "."))
        else:
            result[key] = child
    return result


def pack(body: dict[str, Any]) -> dict[str, Any]:
    fit_detail.validate_result(body)
    rows = [flattened(block) for block in body["blocks"]]
    columns = sorted(rows[0]) if rows else []
    if any(set(row) != set(columns) for row in rows):
        raise ValueError("detail_transport_invalid")
    defaults = {
        key: rows[0][key]
        for key in columns
        if all(
            storage.canonical(row[key]) == storage.canonical(rows[0][key])
            for row in rows
        )
    }
    columns = [key for key in columns if key not in defaults]
    return {
        **{k: v for k, v in body.items() if k != "blocks"},
        "schema_version": SCHEMAS[body["parser_version"]],
        "detail_sha256": storage.digest(storage.canonical(body).encode()),
        "block_defaults": defaults,
        "block_columns": columns,
        "block_rows": [[row[key] for key in columns] for row in rows],
    }


def unpack(table: Any) -> dict[str, Any]:
    try:
        version = fit_parse.require_parser_version(table.get("parser_version", ""))
        registry: Registry = Registry()
        for uri, path in (
            (
                "urn:trainlab:" + fit_detail.SCHEMAS[version],
                fit_detail.schema_path(version),
            ),
            (
                "urn:trainlab:" + fit_parse.SCHEMAS[version],
                fit_parse.schema_path(version),
            ),
        ):
            registry = registry.with_resource(
                uri, Resource.from_contents(json.loads(path.read_text()))
            )
        jsonschema.Draft202012Validator(
            json.loads(
                SCHEMA_PATH.with_name(f"{SCHEMAS[version]}.schema.json").read_text()
            ),
            registry=registry,
        ).validate(table)
        columns, defaults = table["block_columns"], table["block_defaults"]
        if set(columns) & set(defaults):
            raise ValueError("overlap")
        blocks = []
        for row in table["block_rows"]:
            if len(row) != len(columns):
                raise ValueError("width")
            block: dict[str, Any] = {}
            for key, value in {
                **defaults,
                **dict(zip(columns, row, strict=True)),
            }.items():
                parts = key.split(".")
                target = block
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                if parts[-1] in target:
                    raise ValueError("duplicate")
                target[parts[-1]] = value
            blocks.append(block)
        body = {
            **{k: v for k, v in table.items() if k not in TABLE_FIELDS},
            "schema_version": fit_detail.SCHEMAS[version],
            "blocks": blocks,
        }
        # Full original Schema, then canonical repacking: this rejects unknown
        # paths, partial rows, ambiguous defaults and modified source/value SHA.
        if storage.canonical(pack(body)) != storage.canonical(table):
            raise ValueError("binding")
        return body
    except Exception:
        raise ValueError("detail_transport_invalid") from None


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def audit_model_output(text: Any, expected: dict[str, Any]) -> dict[str, Any]:
    """Check a captured public function_call_output, not just an SDK event.

    Only the observed CLI elapsed-time wrapper is removable. Truncation, extra
    prose or a complete but wrong result is an error, never partial success.
    """
    try:
        fit_detail.validate_result(expected)
        if not isinstance(text, str):
            raise ValueError("type")
        wrapper = re.match(r"\AWall time: [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n", text)
        if wrapper:
            text = text[wrapper.end() :]
        actual = unpack(json.loads(text, object_pairs_hook=unique_object))
        canonical = storage.canonical(expected)
        if storage.canonical(actual) != canonical:
            raise ValueError("mismatch")
        return {
            "status": "checked",
            "detail_sha256": storage.digest(canonical.encode()),
            "blocks": len(actual["blocks"]),
            "model_calls": 0,
            "provider_calls": 0,
        }
    except Exception:
        raise ValueError("detail_model_handoff_invalid") from None
