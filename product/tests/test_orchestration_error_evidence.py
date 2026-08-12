"""Regression coverage for bounded downstream error evidence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.analysis_workflows import MorningWorkflowService
from trainlab.orchestration.application import OrchestrationTool
from trainlab.orchestration.contracts import WorkflowRequest
from trainlab.orchestration.evidence_codes import downstream_failure_evidence
from trainlab.orchestration.incident_alerts import render_operational_alert
from trainlab.orchestration.persistence_adapter import (
    RepositoryReceiptStore,
    SqliteSubjectProjection,
)
from trainlab.orchestration.repository import OrchestrationRepository
from trainlab.orchestration.subprocess_runner import DownstreamResult
from trainlab.orchestration.workflow_incidents import WorkflowIncidentCoordinator

NOW = datetime(2026, 7, 27, tzinfo=UTC)
REQUEST = WorkflowRequest(
    "morning",
    "subject-7",
    "2026-07-27",
    "error-evidence",
    "scheduled",
    None,
    (),
    "2026-07-27T01:00:00Z",
    "2026-07-27T00:00:00Z",
)


class Subjects:
    def is_active(self, subject_id: str) -> bool:
        return subject_id == "subject-7"

    def workflow_identity(self, subject_id: str) -> str:
        assert subject_id == "subject-7"
        return "7"


class CapturingStore:
    def record_orchestration_receipt(self, request, receipt) -> None:
        assert request is REQUEST
        self.receipt = receipt


class Results:
    def __init__(self, values: list[DownstreamResult]) -> None:
        self._values = values

    def run(self, _call) -> DownstreamResult:
        return self._values.pop(0)


def _accepted(receipt: dict[str, object]) -> DownstreamResult:
    return DownstreamResult("accepted", None, receipt, "a" * 64, "b" * 64, 0)


def _garmin(mode: str) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "succeeded",
        "run_id": "collection-1",
        "coverage_state": "complete",
        "open_gap_count": 0,
        "counts": {"not_available": 0, "not_enabled": 0},
        "next_retry_at_utc": None,
    }


def _analysis() -> dict[str, object]:
    return {"mode": "daily", "status": "succeeded", "next_retry_at_utc": None}


def _tool(result: DownstreamResult) -> tuple[OrchestrationTool, CapturingStore]:
    store = CapturingStore()
    values = [result]
    if result.kind == "accepted" and result.receipt is not None:
        values += [
            _accepted(_garmin("snapshot")),
            _accepted(_garmin("audit")),
            _accepted(_analysis()),
        ]
    return (
        OrchestrationTool(
            clock=lambda: NOW,
            subject_authorizer=Subjects(),
            receipt_store=store,
            morning=MorningWorkflowService(Results(values)),
        ),
        store,
    )


def _repository(tmp_path: Path) -> tuple[OrchestrationRepository, Path]:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/ready.json",
        root / "state/locks/foundation.lock",
    )
    assert (
        FoundationTool(config)
        .execute(FoundationRequest("init", "error-evidence", "2026-07-27T00:00:00Z"))
        .status
        == "initialized"
    )
    connection = sqlite3.connect(config.database_path)
    connection.execute(
        "INSERT INTO data_subjects(subject_key,timezone,is_active,created_at_utc) VALUES(?,?,1,?)",
        ("subject-7", "Asia/Hong_Kong", "2026-07-27T00:00:00Z"),
    )
    connection.commit()
    connection.close()
    return OrchestrationRepository(config.database_path), config.database_path


@pytest.mark.parametrize(
    ("partition", "result", "expected_code"),
    (
        (
            "transient-start",
            DownstreamResult(
                "untrusted", "process_start_failed", None, None, "b" * 64, None
            ),
            "process_start_failed",
        ),
        (
            "permanent-start",
            DownstreamResult(
                "untrusted", "process_start_failed", None, None, "b" * 64, None
            ),
            "process_start_failed",
        ),
        (
            "timeout",
            DownstreamResult(
                "timeout_unknown", "process_timeout_unknown", None, None, "b" * 64, None
            ),
            "process_timeout_unknown",
        ),
        (
            "provider-unavailable",
            DownstreamResult(
                "untrusted",
                "interface_manifest_unavailable",
                None,
                None,
                "b" * 64,
                None,
            ),
            "interface_manifest_unavailable",
        ),
        (
            "malformed-receipt",
            DownstreamResult(
                "untrusted", "receipt_schema_invalid", None, None, "b" * 64, 20
            ),
            "receipt_schema_invalid",
        ),
        (
            "unknown-exception",
            DownstreamResult("untrusted", "token=secret", None, None, "b" * 64, None),
            "downstream_execution_failed",
        ),
    ),
)
def test_no_receipt_error_partitions_keep_only_the_safe_code_everywhere(
    tmp_path: Path,
    partition: str,
    result: DownstreamResult,
    expected_code: str,
) -> None:
    tool, _ = _tool(result)
    receipt = tool.execute(REQUEST)

    assert partition
    assert receipt.status == "failed"
    assert receipt.errors == (
        {"code": expected_code, "summary": "workflow could not be completed safely"},
    )
    assert "secret" not in str(receipt.as_json_dict())

    repository, database_path = _repository(tmp_path)
    RepositoryReceiptStore(
        repository, SqliteSubjectProjection(database_path)
    ).record_orchestration_receipt(REQUEST, receipt)
    aggregate = repository.load_workflow_definition(receipt.workflow_key)
    assert aggregate is not None
    assert aggregate.step_events[-1].evidence_code == expected_code

    events = WorkflowIncidentCoordinator(repository).observe(
        workflow_key=receipt.workflow_key,
        workflow_kind="morning",
        outcome=receipt.as_json_dict(),
        seen_at_utc=NOW,
    )
    assert events is not None and events.opened
    incident = repository.get_incident(events.opened[0])
    assert incident.error_code == incident.error_summary == expected_code
    _, alert_html = render_operational_alert(incident, event="open")
    assert expected_code in alert_html
    assert "secret" not in alert_html


def test_accepted_receipts_have_no_failure_code_and_persist_receipt_evidence(
    tmp_path: Path,
) -> None:
    tool, _ = _tool(_accepted(_garmin("incremental")))
    receipt = tool.execute(REQUEST)

    assert receipt.status == "succeeded"
    assert receipt.errors == ()
    repository, database_path = _repository(tmp_path)
    RepositoryReceiptStore(
        repository, SqliteSubjectProjection(database_path)
    ).record_orchestration_receipt(REQUEST, receipt)
    aggregate = repository.load_workflow_definition(receipt.workflow_key)
    assert aggregate is not None
    assert {
        event.evidence_code
        for event in aggregate.step_events
        if event.to_state != "running"
    } == {"receipt_received"}


def test_accepted_result_without_receipt_is_redacted_not_process_start_failed() -> None:
    tool, _ = _tool(DownstreamResult("accepted", None, None, None, "b" * 64, 0))
    receipt = tool.execute(REQUEST)

    assert receipt.errors[0]["code"] == downstream_failure_evidence(None)
    assert receipt.errors[0]["code"] != "process_start_failed"
