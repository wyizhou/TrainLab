from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from skills._shared.scripts.schema_validation import require_valid_payload

SOURCE = Path(__file__).resolve().parents[3]
SCHEMAS = SOURCE / "skills/_shared/schemas"


@pytest.mark.parametrize(
    "schema_name",
    [
        "daily_completed_observation_v1",
        "daily_health_analysis_v3",
        "activity_technical_evidence_v1",
        "weekly_training_evidence_v2",
        "training_plan_v3",
        "weekly_ai_result_v3",
        "daily_reader_content_v1",
        "weekly_reader_content_v1",
        "training_goal_v1",
        "m11_v4_weekly_model_context_v2",
    ],
)
def test_v4_schema_is_registered_and_strict(schema_name: str) -> None:
    path = SCHEMAS / f"{schema_name}.schema.json"
    payload = json.loads(path.read_text())
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["type"] == "object"
    assert payload["additionalProperties"] is False


def test_training_plan_v3_schema_rejects_v2_dynamic_fields() -> None:
    plan: dict[str, object] = {
        "schema_version": "training_plan_v3",
        "status": "succeeded",
        "progression_rule": "hold",
        "progression_dimension": "none",
        "sos_omission_reason": None,
        "sos_schedule_reason": None,
        "items": [],
        "provider_calls": 0,
    }
    with pytest.raises(ValueError):
        require_valid_payload(plan, "training_plan_v3")


def test_weekly_codex_wire_schema_uses_supported_strict_subset() -> None:
    path = SOURCE / "skills/_shared/scripts/structured_outputs_validation.py"
    spec = importlib.util.spec_from_file_location("trainlab_v4_structured", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = json.loads((SCHEMAS / "weekly_ai_result_v3_codex.schema.json").read_text())
    module.require_supported_schema(schema)


def test_context_v1_schema_remains_frozen() -> None:
    import hashlib

    path = SCHEMAS / "m11_v4_weekly_model_context_v1.schema.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "79eb9ef5fbe05d2c09887422e5dd36ffcabbdc7bffc51a392fec966ca6889ff1"
    )
