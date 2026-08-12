from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trainlab.orchestration import (
    FROZEN_CONTRACT_HASHES,
    ContractSnapshotMismatch,
    ControlledClock,
    FakeAnalysis,
    FakeFoundation,
    FakeGarmin,
    FakeGmailTransport,
    FakeMail,
    FakeReceiptFactory,
    WorkflowReceipt,
    WorkflowRequest,
    WorkflowStepReceipt,
    verify_frozen_contracts,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "harness" / "schemas"
FIXTURE = ROOT / "tests" / "fixtures" / "orchestration" / "s5_00_receipts.json"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text())


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_authority_hashes_match_frozen_s5_00_snapshot() -> None:
    verify_frozen_contracts(ROOT)
    manifest = json.loads((SCHEMAS / "orchestration_interface_manifest.json").read_text())
    assert manifest["contract_hashes"] == dict(FROZEN_CONTRACT_HASHES)


def test_any_authority_hash_mismatch_blocks_work(tmp_path: Path) -> None:
    source = ROOT / "docs" / "layers"
    target = tmp_path / "docs" / "layers"
    target.mkdir(parents=True)
    for name in FROZEN_CONTRACT_HASHES:
        shutil.copy2(source / name, target / name)
    (target / "05-orchestration-monitoring.md").write_text("changed")
    with pytest.raises(ContractSnapshotMismatch, match="05-orchestration-monitoring.md"):
        verify_frozen_contracts(tmp_path)


def test_workflow_request_and_receipt_schemas_are_closed_and_roundtrip() -> None:
    request = WorkflowRequest(
        workflow_kind="morning", subject_id="subject-001", logical_local_date="2026-07-22",
        invocation_id="workflow-001", trigger_kind="scheduled", parent_workflow_run_id=None,
        dependency_ids=(), deadline_at_utc="2026-07-23T00:30:00Z", requested_at_utc="2026-07-23T00:00:00Z",
    ).as_json_dict()
    step = WorkflowStepReceipt("step-001", "garmin", "incremental", "succeeded", "garmin-run-001", "garmin-001", "a" * 64, {"fetched": 1})
    receipt = WorkflowReceipt(
        workflow_run_id="workflow-run-001", workflow_key="morning:subject-001:2026-07-22",
        workflow_kind="morning", status="succeeded", trigger_kind="scheduled",
        scheduled_at_utc="2026-07-23T00:00:00Z", started_at_utc="2026-07-23T00:00:00Z",
        completed_at_utc="2026-07-23T00:01:00Z", logical_local_date="2026-07-22", steps=(step,),
        next_action="none", next_retry_at_utc=None, incident_ids=(), warnings=(), errors=(),
    ).as_json_dict()
    for schema_name, value in (("orchestration_workflow_request.schema.json", request), ("orchestration_workflow_receipt.schema.json", receipt)):
        validator = Draft202012Validator(_schema(schema_name))
        assert not list(validator.iter_errors(value))
        value["unexpected"] = True
        assert list(validator.iter_errors(value))
        value.pop("unexpected")


def test_manifest_locks_modes_statuses_required_fields_and_ownership() -> None:
    manifest = json.loads((SCHEMAS / "orchestration_interface_manifest.json").read_text())
    assert manifest["owner"] == "orchestration"
    assert manifest["layer_owners"] == {
        "foundation": "foundation", "garmin": "garmin_collection", "analysis": "analysis",
        "mail": "mail_agent", "orchestration": "orchestration",
    }
    assert manifest["owned_tables"] == [
        "scheduler_jobs", "scheduler_leases", "orchestrator_runs", "orchestrator_steps",
        "service_health_checks", "operational_incidents", "operational_alert_deliveries",
    ]
    expected = {
        "foundation": (["init", "status", "verify", "migrate"], ["initialized", "already_initialized", "ready", "incompatible", "lock_busy", "failed"]),
        "garmin": (["auth", "full", "incremental", "snapshot", "repair", "audit", "status"], ["succeeded", "partial", "deferred", "failed", "auth_required", "lock_busy"]),
        "analysis": (["daily", "weekly", "revise_plan", "regenerate", "retry_delivery", "reconcile_delivery", "status"], ["succeeded", "unchanged", "partial", "deferred", "rejected", "failed", "lock_busy"]),
        "mail": (["run", "poll", "process", "deliver_response", "reconcile", "status"], ["succeeded", "unchanged", "partial", "deferred", "lock_busy", "auth_required", "rejected", "failed"]),
        "orchestration": (["supervisor_run", "supervisor_doctor", "run_morning", "run_weekly", "run_mail", "run_health_check", "retry", "reconcile", "status"], ["queued", "running", "succeeded", "partial", "deferred", "attention_required", "failed", "cancelled"]),
    }
    for name, (modes, statuses) in expected.items():
        assert manifest["interfaces"][name]["modes"] == modes
        assert manifest["interfaces"][name]["statuses"] == statuses
        assert manifest["interfaces"][name]["request_required"]
        assert manifest["interfaces"][name]["receipt_required"]

    schema_required = {
        "foundation": json.loads((SCHEMAS / "foundation_receipt.schema.json").read_text())["required"],
        "garmin": json.loads((SCHEMAS / "garmin_sync_receipt.schema.json").read_text())["required"],
        "analysis": json.loads((ROOT / "src/trainlab/analysis/schemas/analysis_receipt.schema.json").read_text())["required"],
        "mail": json.loads((SCHEMAS / "mail_receipt.schema.json").read_text())["required"],
        "orchestration": _schema("orchestration_workflow_receipt.schema.json")["required"],
    }
    for name, required in schema_required.items():
        assert manifest["interfaces"][name]["receipt_required"] == required


def test_analysis_and_mail_run_key_are_status_only_optional_selectors() -> None:
    manifest = json.loads((SCHEMAS / "orchestration_interface_manifest.json").read_text())
    for layer in ("analysis", "mail"):
        interface = manifest["interfaces"][layer]
        assert "run_key" not in interface["request_required"]
        assert interface["status_only_optional_selectors"] == {
            "run_key": {
                "type": ["string", "null"], "allowed_modes": ["status"],
                "purpose": "read_only_history_run_selector", "non_status_policy": "reject_when_non_null",
                "excluded_from": ["invocation_id", "stable_write_identity", "run_creation", "run_recovery", "run_mutation"],
            }
        }


def test_deidentified_fakes_replay_only_receipts_and_restricted_gmail_operations() -> None:
    receipts = _fixture()
    fixture_text = FIXTURE.read_text().lower()
    assert "token" not in fixture_text
    assert "heart_rate" not in fixture_text
    assert "mail_body" not in fixture_text
    assert "fit_content" not in fixture_text
    factory = FakeReceiptFactory(receipts)
    first = factory.build("garmin", "incremental")
    second = factory.build("garmin", "incremental")
    first["status"] = "failed"
    assert second["status"] == "succeeded"
    assert FakeFoundation(receipts["foundation"]).execute({"mode": "init"})["status"] == "already_initialized"
    assert FakeGarmin(receipts["garmin"]).execute({"mode": "incremental"})["run_id"] == "garmin-run-001"
    assert FakeAnalysis(receipts["analysis"]).execute({"mode": "daily"})["analysis_run_id"] == "analysis-run-001"
    assert FakeMail(receipts["mail"]).execute({"mode": "run"})["status"] == "unchanged"
    gmail = FakeGmailTransport()
    assert gmail.get_self() == "owner@example.invalid"
    assert not gmail.search_alert("alert-001")
    sent = gmail.send_html_self(idempotency_key="alert-001", subject="[TrainLab][运维]", html="synthetic")
    gmail.apply_trainlab_label(sent["provider_message_id"])
    assert [item["operation"] for item in gmail.operations] == ["get_self", "search_alert", "send_html_self", "apply_trainlab_label"]
    assert not hasattr(gmail, "search_messages") and not hasattr(gmail, "read_thread")


def test_fakes_reject_unknown_modes_statuses_and_non_status_run_key_selectors() -> None:
    receipts = _fixture()
    with pytest.raises(ValueError, match="unsupported_fake_mode"):
        FakeGarmin(receipts["garmin"]).execute({"mode": "unknown"})
    bad_receipts = {"incremental": {**receipts["garmin"]["incremental"], "status": "unknown"}}
    with pytest.raises(ValueError, match="unsupported_fake_status"):
        FakeGarmin(bad_receipts).execute({"mode": "incremental"})
    for fake, write_mode in ((FakeAnalysis(receipts["analysis"]), "daily"), (FakeMail(receipts["mail"]), "run")):
        with pytest.raises(ValueError, match="status_only_selector_non_status"):
            fake.execute({"mode": write_mode, "run_key": "historical-run"})
    analysis_status = {"status": {**receipts["analysis"]["daily"], "mode": "status"}}
    mail_status = {"status": {**receipts["mail"]["run"], "mode": "status"}}
    assert FakeAnalysis(analysis_status).execute({"mode": "status", "run_key": "historical-run"})["mode"] == "status"
    assert FakeMail(mail_status).execute({"mode": "status", "run_key": None})["mode"] == "status"


def test_fakes_and_factory_reject_missing_required_receipt_fields() -> None:
    receipts = _fixture()
    malformed = deepcopy(receipts)
    malformed["foundation"]["init"].pop("created_count")
    with pytest.raises(ValueError, match="fake_receipt_missing_fields:created_count"):
        FakeFoundation(malformed["foundation"]).execute({"mode": "init"})
    malformed = deepcopy(receipts)
    malformed["analysis"]["daily"].pop("output_schema_version")
    with pytest.raises(ValueError, match="fake_receipt_missing_fields:output_schema_version"):
        FakeReceiptFactory(malformed).build("analysis", "daily")


def test_controlled_clock_is_deterministic_and_requires_aware_time() -> None:
    clock = ControlledClock(datetime(2026, 7, 23, tzinfo=timezone.utc))
    assert clock.advance(60).isoformat() == "2026-07-23T00:01:00+00:00"
    with pytest.raises(ValueError, match="timezone_aware_utc_required"):
        ControlledClock(datetime(2026, 7, 23))
