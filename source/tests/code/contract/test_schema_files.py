from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SOURCE = Path(__file__).resolve().parents[3]


def test_all_runtime_schemas_are_valid_and_auto_template_matches() -> None:
    schemas = sorted((SOURCE / "skills").rglob("*.schema.json"))
    assert schemas
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    schema = json.loads(
        (SOURCE / "skills/_shared/schemas/auto_result_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (SOURCE / "tests/ai/templates/result.json").read_text(encoding="utf-8")
    )
    assert not list(Draft202012Validator(schema).iter_errors(example))
