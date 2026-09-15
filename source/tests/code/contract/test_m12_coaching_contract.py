from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_coaching_factory")


def test_schema_wire_prompt_same_source():
    from skills._shared.fit_weekly import coaching_contract, codex_output

    for stage in ("plan", "summary"):
        schema = coaching_contract.schema(stage)
        assert coaching_contract.wire(stage) == codex_output.wire_schema(schema)
        assert (
            json.loads(coaching_contract.prompt(stage).split("BUSINESS_SCHEMA\n")[1])
            == schema
        )
        coaching_contract.check(stage)


def test_prompt_drift_rejected(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import coaching_contract

    monkeypatch.setattr(coaching_contract, "PROMPTS", tmp_path)
    (tmp_path / "fit-running-plan-v1.txt").write_text("different")
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("plan")


def test_unknown_business_version_rejected():
    from skills._shared.fit_weekly import coaching

    with pytest.raises(ValueError, match="coaching_version_unknown"):
        coaching.validator(Path("/unused"))(
            {"schema_version": "future"}, {"stage": "plan"}
        )


def test_adapter_prompt_gets_host_facts_and_rejects_drift(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import (
        coaching_contract,
        command_adapter,
        model_job,
        stage_context,
        weekly_context,
    )

    contexts = importlib.import_module("test_m12_weekly_context")
    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    materials = weekly_context.freeze(
        root, contexts.fixture.END, validate_report=contexts.valid_report
    )
    payload = stage_context.project(materials, "plan")
    spec = {
        "instructions": "Synthetic instruction",
        "prompt_prefix": coaching_contract.prompt("plan"),
        "request": {
            "stage": "plan",
            "payload": payload,
            "response_schema": coaching_contract.schema("plan"),
        },
    }
    prompt = command_adapter.files(spec)["prompt.txt"].decode()
    facts = json.loads(prompt.split("HOST_FACTS\n")[1].split("\nSTAGE_PAYLOAD\n")[0])
    assert {row["sport"] for row in facts["inventory"]} == {"running"}
    assert facts["plan_dates"] == payload["next_plan_dates"]
    bad = model_job.clone(spec)
    bad["prompt_prefix"] += " drift"
    with pytest.raises(ValueError, match="coaching_runtime_prompt_invalid"):
        command_adapter.files(bad)
    bad = model_job.clone(spec)
    bad["request"]["response_schema"]["description"] = "drift"
    with pytest.raises(ValueError, match="coaching_runtime_prompt_invalid"):
        command_adapter.files(bad)


def test_legacy_policy_requires_explicit_saved_stage_and_version():
    from skills._shared.fit_weekly import coaching

    accepted = []

    def saved_policy(output, payload):
        assert output == {"saved": "original"}
        accepted.append(payload["stage"])

    validate = coaching.validator(
        Path("/unused"),
        legacy={("plan", "fit_weekly_stage_input_v1", None): saved_policy},
    )
    validate(
        {"saved": "original"},
        {"schema_version": "fit_weekly_stage_input_v1", "stage": "plan"},
    )
    for stage in ("summary", None):
        with pytest.raises(ValueError, match="coaching_version_unknown"):
            validate(
                {"saved": "original"},
                {"schema_version": "fit_weekly_stage_input_v1", "stage": stage},
            )
    assert accepted == ["plan"]


@pytest.fixture
def business_documents(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import coaching_contract
    from skills._shared.scripts import schema_validation

    original = schema_validation.schema_root()
    for name in coaching_contract.VERSIONS.values():
        filename = name + ".schema.json"
        (tmp_path / filename).write_bytes((original / filename).read_bytes())
    monkeypatch.setattr(schema_validation, "schema_root", lambda: tmp_path)

    def edit(stage, update):
        path = tmp_path / (coaching_contract.VERSIONS[stage] + ".schema.json")
        document = json.loads(path.read_text())
        update(document)
        path.write_text(json.dumps(document))

    return edit


@pytest.mark.parametrize(
    "reference",
    [
        "urn:trainlab:fit_running_plan_v1#/$defs/evidence",
        "fit_running_plan_v1.schema.json#/$defs/evidence",
        "https://trainlab.local/schemas/fit_running_plan_v1.schema.json#/$defs/evidence",
    ],
)
def test_declared_reference_changes_schema_wire_and_rejects_stale_prompt(
    business_documents, reference
):
    from skills._shared.fit_weekly import coaching_contract

    before = coaching_contract.schema("summary")
    wire_before = coaching_contract.wire("summary")
    business_documents(
        "summary", lambda body: body["$defs"]["claim"].update({"$ref": reference})
    )
    after = coaching_contract.schema("summary")
    assert after != before
    assert after["properties"]["core_conclusions"]["items"]["required"] == [
        "source",
        "activity_ref",
        "fit_sha256",
        "session_ordinal",
        "period_end_utc",
        "request_sha256",
        "path",
        "value",
    ]
    assert coaching_contract.wire("summary") != wire_before
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("summary")


def test_cross_document_reference_retains_its_own_local_reference_context(
    business_documents,
):
    from skills._shared.fit_weekly import coaching_contract

    def change_plan(body):
        body["$defs"]["evidence"]["description"] = "Evidence from the plan document"

    def change_summary(body):
        body["$defs"]["evidence"] = {"type": "string", "const": "summary decoy"}

    business_documents("plan", change_plan)
    business_documents("summary", change_summary)
    claim = coaching_contract.schema("summary")["properties"]["core_conclusions"][
        "items"
    ]
    assert claim["properties"]["evidence"]["items"]["type"] == "object"
    assert claim["properties"]["evidence"]["items"]["description"] == (
        "Evidence from the plan document"
    )
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("summary")


def test_local_reference_uses_actual_definition_and_escaped_pointer(business_documents):
    from skills._shared.fit_weekly import coaching_contract

    def change(body):
        body["$defs"]["a/b~c"] = {"type": "string", "const": "declared local target"}
        body["$defs"]["claim"] = {"$ref": "#/$defs/a~1b~0c"}

    business_documents("summary", change)
    claim = coaching_contract.schema("summary")["properties"]["core_conclusions"][
        "items"
    ]
    assert claim == {"type": "string", "const": "declared local target"}
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("summary")


@pytest.mark.parametrize(
    "replacement",
    [
        {"$ref": "urn:trainlab:fit_running_plan_v1#/$defs/missing"},
        {"$ref": "#/$defs/claim"},
        {"$ref": "#"},
        {"$ref": "#/$defs/claim/~2"},
        {"$ref": "https://example.invalid/schema.json#/$defs/claim"},
        {"$ref": "file:///tmp/schema.json#/$defs/claim"},
        {"$ref": "urn:trainlab:fit_running_plan_v1#/$defs/claim", "maxProperties": 0},
        {"$dynamicRef": "#/$defs/claim"},
        {"$id": "urn:trainlab:fit_running_plan_v1", "$ref": "#/$defs/claim"},
    ],
)
def test_invalid_or_unsupported_reference_stops_preparation(
    business_documents, replacement
):
    from skills._shared.fit_weekly import coaching_contract

    business_documents(
        "summary", lambda body: body["$defs"].update({"claim": replacement})
    )
    with pytest.raises(ValueError):
        coaching_contract.schema("summary")
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("summary")


def test_cross_document_reference_cycle_is_rejected(business_documents):
    from skills._shared.fit_weekly import coaching_contract

    business_documents(
        "plan",
        lambda body: body["$defs"].update(
            {"claim": {"$ref": "urn:trainlab:fit_sports_summary_v1#/$defs/claim"}}
        ),
    )
    with pytest.raises(ValueError):
        coaching_contract.schema("summary")
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("summary")
