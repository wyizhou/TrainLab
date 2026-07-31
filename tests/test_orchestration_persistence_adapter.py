from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.contracts import (
    WorkflowReceipt,
    WorkflowRequest,
    WorkflowStepReceipt,
)
from trainlab.orchestration.persistence_adapter import (
    RepositoryReceiptStore,
    SqliteSubjectProjection,
)
from trainlab.orchestration.repository import OrchestrationRepository
from trainlab.orchestration import LeaseManager
from trainlab.orchestration.scheduling_config import SchedulerJobProjection


NOW = datetime(2026, 7, 27, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Probe:
    def is_absent(self, _pid: int) -> bool:
        return True


def database(tmp_path: Path) -> Path:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/ready.json", root / "state/locks/foundation.lock",
    )
    assert FoundationTool(config).execute(
        FoundationRequest("init", "persist-fixture", "2026-07-27T00:00:00Z")
    ).status == "initialized"
    connection = sqlite3.connect(config.database_path)
    connection.execute(
        "INSERT INTO data_subjects(subject_key,timezone,is_active,created_at_utc) VALUES(?,?,1,?)",
        ("subject-7", "Asia/Singapore", "2026-07-27T00:00:00Z"),
    )
    connection.commit(); connection.close()
    return config.database_path


def test_receipt_materializes_and_transitions_domain_state(tmp_path: Path) -> None:
    path = database(tmp_path)
    repository = OrchestrationRepository(path)
    request = WorkflowRequest(
        "morning", "subject-7", "2026-07-27", "invoke-1", "manual", None, (),
        "2026-07-27T02:00:00Z", "2026-07-27T00:00:00Z",
    )
    receipt = WorkflowReceipt(
        "run:morning:abc", "morning:abc", "morning", "succeeded", "manual",
        None, "2026-07-27T00:00:00Z", "2026-07-27T00:01:00Z",
        "2026-07-27", (
            WorkflowStepReceipt(
                "daily", "analysis", "daily", "succeeded", "analysis-1",
                "invoke-analysis", "a" * 64, {"artifacts": 1},
            ),
        ), "none", None, (), (), (),
    )
    store = RepositoryReceiptStore(
        repository, SqliteSubjectProjection(path), clock=lambda: NOW
    )
    store.record_orchestration_receipt(request, receipt)
    aggregate = repository.load_workflow_definition("morning:abc")
    assert aggregate is not None
    assert aggregate.workflow.domain_state == "succeeded"
    assert aggregate.steps[0].domain_state == "succeeded"
    store.record_orchestration_receipt(request, receipt)
    assert len(repository.load_workflow_definition("morning:abc").step_events) == 2


def test_deferred_receipt_can_resume_without_redefining_step(tmp_path: Path) -> None:
    path = database(tmp_path)
    repository = OrchestrationRepository(path)
    request = WorkflowRequest(
        "morning", "subject-7", "2026-07-27", "invoke-1", "manual", None, (),
        "2026-07-27T02:00:00Z", "2026-07-27T00:00:00Z",
    )
    step = WorkflowStepReceipt(
        "daily", "analysis", "daily", "deferred", None,
        "invoke-analysis", "a" * 64, {"deferred": 1},
    )
    deferred = WorkflowReceipt(
        "run:morning:abc", "morning:abc", "morning", "deferred", "manual",
        None, "2026-07-27T00:00:00Z", "2026-07-27T00:01:00Z",
        "2026-07-27", (step,), "retry",
        "2026-07-27T00:05:00Z", (), (), (),
    )
    store = RepositoryReceiptStore(
        repository, SqliteSubjectProjection(path), clock=lambda: NOW
    )
    store.record_orchestration_receipt(request, deferred)
    first = repository.load_workflow_definition("morning:abc")
    assert first is not None
    assert first.workflow.domain_state == "deferred"
    assert first.steps[0].domain_state == "deferred"
    store.record_orchestration_receipt(request, deferred)
    replay = repository.load_workflow_definition("morning:abc")
    assert replay is not None
    assert replay.workflow_events == first.workflow_events
    assert replay.step_events == first.step_events

    revised_deferred = WorkflowReceipt(
        "run:morning:abc", "morning:abc", "morning", "deferred", "recovery",
        None, "2026-07-27T00:05:00Z", "2026-07-27T00:05:30Z",
        "2026-07-27", (
            WorkflowStepReceipt(
                "daily", "analysis", "daily", "deferred", None,
                "invoke-analysis", "c" * 64, {"deferred": 2},
            ),
        ), "retry", "2026-07-27T00:07:00Z", (), (), (),
    )
    store.record_orchestration_receipt(request, revised_deferred)
    revised = repository.load_workflow_definition("morning:abc")
    assert revised is not None
    assert revised.workflow.domain_state == "deferred"
    assert revised.steps[0].domain_state == "deferred"
    assert revised.step_events[-1].receipt_sha256 == "c" * 64
    assert revised.step_events[-1].next_retry_at_utc == "2026-07-27T00:07:00Z"
    assert revised.step_events[-1].controlled_counts == (("deferred", 2),)

    resumed_request = WorkflowRequest(
        "morning", "subject-7", "2026-07-27", "invoke-1", "recovery", None, (),
        "2026-07-27T02:00:00Z", "2026-07-27T00:05:00Z",
    )
    succeeded = WorkflowReceipt(
        "run:morning:abc", "morning:abc", "morning", "succeeded", "recovery",
        None, "2026-07-27T00:07:00Z", "2026-07-27T00:08:00Z",
        "2026-07-27", (
            WorkflowStepReceipt(
                "daily", "analysis", "daily", "succeeded", None,
                "invoke-analysis", "b" * 64, {"artifacts": 1},
            ),
        ), "none", None, (), (), (),
    )
    store.record_orchestration_receipt(resumed_request, succeeded)
    final = repository.load_workflow_definition("morning:abc")
    assert final is not None
    assert final.workflow.domain_state == "succeeded"
    assert final.steps[0].domain_state == "succeeded"
    assert [event.to_state for event in final.workflow_events] == [
        "running", "deferred", "running", "deferred", "running", "succeeded",
    ]
    assert [event.to_state for event in final.step_events] == [
        "running", "deferred", "running", "deferred", "running", "succeeded",
    ]


def test_failed_schedule_is_preserved_and_manual_child_proves_recovery(
    tmp_path: Path,
) -> None:
    path = database(tmp_path)
    repository = OrchestrationRepository(path)
    store = RepositoryReceiptStore(
        repository, SqliteSubjectProjection(path), clock=lambda: NOW
    )
    scheduled = WorkflowRequest(
        "morning",
        "subject-7",
        "2026-07-27",
        "scheduled-morning",
        "scheduled",
        None,
        (),
        "2026-07-27T02:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    failed_step = WorkflowStepReceipt(
        "daily",
        "analysis",
        "daily",
        "failed",
        None,
        "analysis-failed",
        None,
    )
    failed_receipt = WorkflowReceipt(
        "run:morning:7:2026-07-27",
        "morning:7:2026-07-27",
        "morning",
        "failed",
        "scheduled",
        "2026-07-27T00:00:00Z",
        "2026-07-27T00:00:00Z",
        "2026-07-27T00:01:00Z",
        "2026-07-27",
        (failed_step,),
        "operator_review",
        None,
        (),
        (),
        ({"code": "orchestration_execution_failed"},),
    )
    store.record_orchestration_receipt(scheduled, failed_receipt)
    failed = repository.get_workflow("morning:7:2026-07-27")
    assert failed is not None and failed.status == "failed"
    incident = repository.record_incident(
        incident_key="workflow:failed:morning:scheduled",
        category="workflow",
        severity="error",
        seen_at_utc=NOW + timedelta(minutes=2),
        error_code="workflow_execution_failed",
        next_action="operator_review",
        related_workflow_run_id=failed.id,
    )

    replayed_success = WorkflowReceipt(
        failed_receipt.workflow_run_id,
        failed_receipt.workflow_key,
        "morning",
        "succeeded",
        "recovery",
        None,
        "2026-07-27T00:03:00Z",
        "2026-07-27T00:04:00Z",
        "2026-07-27",
        (
            WorkflowStepReceipt(
                "daily",
                "analysis",
                "daily",
                "succeeded",
                None,
                "analysis-failed",
                "a" * 64,
            ),
        ),
        "none",
        None,
        (),
        (),
        (),
    )
    store.record_orchestration_receipt(scheduled, replayed_success)
    assert repository.get_workflow(failed.workflow_key).status == "failed"

    retry_request = WorkflowRequest(
        "morning",
        "subject-7",
        "2026-07-27",
        "retry-41",
        "manual",
        str(failed.id),
        (),
        "2026-07-28T02:00:00Z",
        "2026-07-28T00:00:00Z",
    )
    retry_receipt = WorkflowReceipt(
        "run:manual:morning:retry-41",
        "manual:morning:retry-41",
        "morning",
        "succeeded",
        "manual",
        None,
        "2026-07-28T00:00:00Z",
        "2026-07-28T00:01:00Z",
        "2026-07-27",
        (
            WorkflowStepReceipt(
                "daily",
                "analysis",
                "daily",
                "succeeded",
                None,
                "analysis-retry",
                "b" * 64,
            ),
        ),
        "none",
        None,
        (),
        (),
        (),
    )
    store.record_orchestration_receipt(retry_request, retry_receipt)
    recovered_run = repository.get_workflow(retry_receipt.workflow_key)
    assert recovered_run is not None
    assert recovered_run.status == "succeeded"
    assert recovered_run.parent_workflow_run_id == failed.id
    recovered = repository.resolve_retryable_workflow_failures(
        recovered_run.workflow_key, at_utc=NOW + timedelta(days=1, minutes=2)
    )
    assert tuple(item.incident_key for item in recovered) == (
        incident.incident_key,
    )
    assert repository.get_workflow(failed.workflow_key).status == "failed"


def test_operator_retry_parent_must_match_subject_kind_and_logical_date(
    tmp_path: Path,
) -> None:
    path = database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO data_subjects"
            "(subject_key,timezone,is_active,created_at_utc) VALUES(?,?,1,?)",
            ("subject-8", "Asia/Singapore", "2026-07-27T00:00:00Z"),
        )
        connection.commit()
    repository = OrchestrationRepository(path)
    parent = repository.create_workflow(
        workflow_key="morning:7:2026-07-27",
        workflow_kind="morning",
        trigger_kind="scheduled",
        subject_id=1,
        logical_local_date="2026-07-27",
        started_at_utc=NOW,
    )
    parent = repository.transition_workflow(
        parent.workflow_key,
        "failed",
        at_utc=NOW + timedelta(minutes=1),
    )
    store = RepositoryReceiptStore(
        repository, SqliteSubjectProjection(path), clock=lambda: NOW
    )

    def retry(kind: str, subject: str, logical: str) -> WorkflowRequest:
        return WorkflowRequest(
            kind,
            subject,
            logical,
            f"retry-{kind}-{subject}-{logical}",
            "manual",
            str(parent.id),
            (),
            "2026-07-28T02:00:00Z",
            "2026-07-28T00:00:00Z",
        )

    assert store.permits_operator_retry(
        retry("morning", "subject-7", "2026-07-27")
    )
    assert not store.permits_operator_retry(
        retry("morning", "subject-8", "2026-07-27")
    )
    assert not store.permits_operator_retry(
        retry("morning", "subject-7", "2026-07-26")
    )
    assert not store.permits_operator_retry(
        retry("weekly", "subject-7", "2026-07-27")
    )

def test_scheduler_handoff_is_materialized_and_completed_by_exact_receipt(
    tmp_path: Path,
) -> None:
    path = database(tmp_path)
    repository = OrchestrationRepository(path)
    projection = SchedulerJobProjection(
        "health_check", "health_check", "Asia/Singapore", "interval", NOW,
        None, 60, None, "none", None, "a" * 64,
    )
    repository.upsert_scheduler_job(
        projection, is_enabled=True, updated_at_utc=NOW
    )
    lease = LeaseManager(
        path, path.parent / "state/locks/supervisor.lock",
        "host-one", 101, Clock(), Probe(), 90,
    )
    assert lease.acquire().state == "active"
    workflow_key = "health-check:host-one:20260727T000000.000000Z"
    assert repository.claim_scheduler_due(
        job_key="health_check",
        due_at_utc=NOW,
        next_due_at_utc=NOW + timedelta(seconds=60),
        now_utc=NOW,
        owner_instance_id="host-one",
        owner_pid=101,
        workflow_key=workflow_key,
        workflow_kind="health_check",
        trigger_kind="scheduled",
        subject_id=None,
        logical_local_date=None,
        deadline_at_utc=NOW + timedelta(hours=1),
    )
    request = WorkflowRequest(
        "health_check", None, None,
        "host-one:20260727T000000.000000Z", "scheduled", None, (),
        "2026-07-27T01:00:00Z", "2026-07-27T00:00:00Z",
    )
    receipt = WorkflowReceipt(
        f"run:{workflow_key}", workflow_key, "health_check", "succeeded",
        "scheduled", "2026-07-27T00:00:00Z",
        "2026-07-27T00:00:00Z", "2026-07-27T00:00:01Z", None, (
            WorkflowStepReceipt(
                "health_check", "orchestration", "health_check", "succeeded",
                None, "host-one:20260727T000000.000000Z", "b" * 64,
                {"incidents": 0, "warnings": 0, "errors": 0},
            ),
        ),
        "none", None, (), (), (),
    )

    RepositoryReceiptStore(
        repository, SqliteSubjectProjection(path), clock=lambda: NOW
    ).record_orchestration_receipt(request, receipt)

    aggregate = repository.load_workflow_definition(workflow_key)
    assert aggregate is not None
    assert aggregate.workflow.domain_state == "succeeded"
    assert aggregate.scheduler_handoff_lineage_json is not None
    assert repository.get_workflow(workflow_key).status == "succeeded"
    assert lease.release().state == "stopped"
