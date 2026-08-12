"""Offline receipt-schema and cross-layer contract regression matrix."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

import trainlab.orchestration.subprocess_runner as runner_module
from trainlab.orchestration.contracts import WorkflowReceipt, WorkflowStepReceipt
from trainlab.orchestration.subprocess_runner import DownstreamCall

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "orchestration" / "s5_00_receipts.json"
SCHEMAS = {
    "foundation": ROOT / "harness" / "schemas" / "foundation_receipt.schema.json",
    "garmin": ROOT / "harness" / "schemas" / "garmin_sync_receipt.schema.json",
    "analysis": ROOT
    / "src"
    / "trainlab"
    / "analysis"
    / "schemas"
    / "analysis_receipt.schema.json",
    "mail": ROOT / "harness" / "schemas" / "mail_receipt.schema.json",
    "orchestration": ROOT
    / "harness"
    / "schemas"
    / "orchestration_workflow_receipt.schema.json",
}


def _schema(name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        json.loads(SCHEMAS[name].read_text(encoding="utf-8")),
        format_checker=jsonschema.FormatChecker(),
    )


def _downstream_receipt(layer: str) -> dict[str, object]:
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if layer == "foundation":
        return fixture["foundation"]["init"]
    if layer == "garmin":
        return fixture["garmin"]["incremental"]
    if layer == "analysis":
        value = fixture["analysis"]["daily"]
        value.update(
            run_key="analysis:subject-1:daily:default:analysis-daily-001",
            target_periods={
                "summary": None,
                "advice": None,
                "review": None,
                "plan": None,
            },
            status_snapshot=None,
            content_same=None,
            delivery={
                "delivery_id": "analysis-delivery-001",
                "status": "sent",
                "artifact_ids": ["artifact-001"],
                "provider_message_id": None,
                "provider_thread_id": None,
                "error": None,
            },
        )
        return value
    value = fixture["mail"]["run"]
    value.update(poll_state=[], run_key="mail:1:run:mail-run-001")
    return value


@pytest.mark.parametrize("layer", ("foundation", "garmin", "analysis", "mail"))
def test_each_lower_layer_synthetic_receipt_validates_its_production_schema(
    layer: str,
) -> None:
    errors = list(_schema(layer).iter_errors(_downstream_receipt(layer)))
    assert errors == []


@pytest.mark.parametrize(
    ("layer", "call"),
    (
        (
            "foundation",
            DownstreamCall("foundation", "init", "foundation-bootstrap-001", None),
        ),
        (
            "garmin",
            DownstreamCall(
                "garmin", "incremental", None, None, through_local_date="2026-07-22"
            ),
        ),
        (
            "analysis",
            DownstreamCall(
                "analysis", "daily", "analysis-daily-001", None, subject_id="subject-1"
            ),
        ),
        ("mail", DownstreamCall("mail", "run", "mail-run-001", None, subject_id=1)),
    ),
)
def test_cross_layer_receipts_pass_schema_identity_and_exit_validation(
    layer: str, call: DownstreamCall
) -> None:
    receipt = _downstream_receipt(layer)
    exit_code = runner_module._EXIT_BY_LAYER[layer][receipt["status"]]
    accepted, digest = runner_module._validate_receipt(call, receipt, exit_code)
    assert accepted == receipt
    assert isinstance(digest, str) and len(digest) == 64


def _workflow_receipt() -> dict[str, object]:
    receipt = WorkflowReceipt(
        workflow_run_id="workflow-1",
        workflow_key="morning:subject-1:2026-08-07",
        workflow_kind="morning",
        status="succeeded",
        trigger_kind="scheduled",
        scheduled_at_utc="2026-08-07T01:00:00Z",
        started_at_utc="2026-08-07T01:00:01Z",
        completed_at_utc="2026-08-07T01:00:02Z",
        logical_local_date="2026-08-07",
        steps=(
            WorkflowStepReceipt(
                step_id="garmin-incremental",
                layer="garmin",
                mode="incremental",
                status="succeeded",
                downstream_run_id="garmin-1",
                downstream_invocation_id=None,
                receipt_sha256="a" * 64,
                counts={"fetched": 0},
            ),
        ),
        next_action="none",
        next_retry_at_utc=None,
        incident_ids=(),
        warnings=(),
        errors=(),
    )
    return receipt.as_json_dict()


@pytest.mark.parametrize(
    ("partition", "mutation", "valid"),
    (
        ("valid", lambda value: value, True),
        ("invalid", lambda value: value.update(status="not-a-status"), False),
        ("empty", lambda value: value.update(steps=[]), True),
        ("missing", lambda value: value.pop("workflow_key"), False),
        ("minimum", lambda value: value.update(workflow_key="x"), True),
        (
            "maximum",
            lambda value: value.update(warnings=[{"code": "x", "summary": "a" * 200}]),
            True,
        ),
        (
            "just-outside",
            lambda value: value.update(warnings=[{"code": "x", "summary": "a" * 201}]),
            False,
        ),
    ),
)
def test_workflow_receipt_schema_declared_boundary_partitions(
    partition: str, mutation, valid: bool
) -> None:
    receipt = deepcopy(_workflow_receipt())
    mutation(receipt)
    errors = list(_schema("orchestration").iter_errors(receipt))
    assert (errors == []) is valid
    assert partition
