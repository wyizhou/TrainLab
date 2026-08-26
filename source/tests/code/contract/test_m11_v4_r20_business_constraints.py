from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts.schema_validation import validate_payload

SOURCE = Path(__file__).resolve().parents[3]
SCHEMAS = SOURCE / "skills/_shared/schemas"
PROMPTS = SOURCE / "skills/_shared/prompts"
FIXTURES = SOURCE / "tests/code/fixtures"


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DECISION = _load(
    "trainlab_m11_v4_r20_business_constraints_test",
    "skills/training-coach/scripts/weekly_decision_v4.py",
)
MODEL_CONTEXT = _load(
    "trainlab_m11_v4_r20_model_context_test",
    "skills/training-coach/scripts/model_context_v4.py",
)


def _schemas() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    business = json.loads(
        (SCHEMAS / "weekly_model_decision_v1.schema.json").read_text()
    )
    wire = json.loads(
        (SCHEMAS / "weekly_model_decision_v1_codex.schema.json").read_text()
    )
    host = json.loads((SCHEMAS / "weekly_ai_result_v4.schema.json").read_text())
    return business, wire, host


def _decision() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "m11_v4_public_weekly_model_decision_v1.json").read_text()
    )


def _constraint_schema() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "m11_v4_public_business_only_constraints_schema.json").read_text()
    )


def test_all_wire_removed_business_keywords_are_extracted_and_sorted() -> None:
    business = _constraint_schema()
    wire = DECISION.project_wire_schema(business)
    constraints = DECISION.business_only_constraints_from_schemas(business, wire)
    assert {item["keyword"] for item in constraints} == {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "format",
        "minimum",
        "maximum",
    }
    assert constraints == sorted(
        constraints, key=lambda item: (item["json_pointer"], item["keyword"])
    )
    assert not any(item["keyword"] in {"$schema", "$id"} for item in constraints)


def test_v5_prompt_semantics_match_business_wire_and_host() -> None:
    business, wire, host = _schemas()
    prompt = (PROMPTS / "weekly-content-v4-v5.txt").read_bytes()
    expected = DECISION.prompt_semantics_from_schemas(business, wire, host)
    assert expected["schema_version"] == "weekly_prompt_semantics_v2"
    assert DECISION.parse_prompt_semantics(prompt) == expected
    DECISION.require_prompt_schema_semantic_parity(prompt, business, wire, host)
    assert {
        (item["json_pointer"], item["keyword"], item["value"])
        for item in expected["business_only_constraints"]
    } >= {
        (
            "/$defs/rest_course/properties/technique_notes",
            "minItems",
            1,
        ),
        (
            "/$defs/rest_course/properties/stop_conditions",
            "minItems",
            1,
        ),
    }


def test_v5_prompt_is_the_manifest_bound_authoritative_template() -> None:
    contracts = MODEL_CONTEXT.require_authoritative_contracts_v4()
    assert Path(contracts["prompt_template_path"]).name == "weekly-content-v4-v5.txt"
    assert contracts["prompt_template_sha256"] == (
        "57d494eca34ec921e76d6fedbac2b3de2fb729efb1b4defec892a8fd47f33839"
    )


def test_old_prompt_bytes_and_v1_semantics_remain_auditable() -> None:
    expected = {
        "weekly-content-v4-v3.txt": (
            "f0aea3bb5ecb01f608f967cdf1aca2d1e0c276d25fc682060dac9496f422d4b0"
        ),
        "weekly-content-v4-v4.txt": (
            "faae52bcf6a901b63246429f2086a56673435946a64eeaa64044f0962d36ca84"
        ),
    }
    for name, digest in expected.items():
        assert hashlib.sha256((PROMPTS / name).read_bytes()).hexdigest() == digest
    parsed = DECISION.parse_prompt_semantics(
        (PROMPTS / "weekly-content-v4-v4.txt").read_bytes()
    )
    assert parsed["schema_version"] == "weekly_prompt_semantics_v1"


@pytest.mark.parametrize("field", ["technique_notes", "stop_conditions"])
def test_rest_empty_arrays_pass_wire_but_fail_business(field: str) -> None:
    value = _decision()
    rest = value["training_plan"]["days"]["day_4"]
    assert rest["activity_kind"] == "rest"
    rest[field] = []
    assert validate_payload(value, "weekly_model_decision_v1_codex") == []
    assert validate_payload(value, "weekly_model_decision_v1")


def test_synchronized_business_wire_drift_is_rejected_by_prompt_parity() -> None:
    business, _, host = _schemas()
    changed = deepcopy(business)
    changed["$defs"]["text"]["maxLength"] = 200
    changed_wire = DECISION.project_wire_schema(changed)
    prompt = (PROMPTS / "weekly-content-v4-v5.txt").read_bytes()
    with pytest.raises(ValueError, match="weekly_prompt_schema_semantic_parity"):
        DECISION.require_prompt_schema_semantic_parity(
            prompt, changed, changed_wire, host
        )


def test_business_only_constraint_value_drift_is_rejected() -> None:
    business, wire, host = _schemas()
    changed = deepcopy(business)
    changed["$defs"]["rest_course"]["properties"]["technique_notes"]["minItems"] = 2
    changed_wire = DECISION.project_wire_schema(changed)
    prompt = (PROMPTS / "weekly-content-v4-v5.txt").read_bytes()
    with pytest.raises(ValueError, match="weekly_prompt_schema_semantic_parity"):
        DECISION.require_prompt_schema_semantic_parity(
            prompt, changed, changed_wire, host
        )
