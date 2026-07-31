from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from trainlab.orchestration import production
from trainlab.orchestration.due_scheduler import DueItem
from trainlab.orchestration.recovery_planner import RecoveryDecision
from trainlab.orchestration.workflow_incidents import WorkflowIncidentCoordinator


@pytest.mark.parametrize("alerts_enabled", [False, True])
def test_doctor_uses_loaded_configuration_for_alert_gate(
    tmp_path, monkeypatch, alerts_enabled: bool
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/trainlab.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mail": {"recipient_email": "owner@example.com"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    monkeypatch.setattr(
        production, "verify_frozen_contracts", lambda _root: None
    )
    monkeypatch.setattr(
        production.FoundationConfig,
        "load",
        lambda _root: SimpleNamespace(database_path=tmp_path / "data.db"),
    )
    monkeypatch.setattr(
        production,
        "FoundationTool",
        lambda _config: SimpleNamespace(
            execute=lambda _request: SimpleNamespace(ready=True)
        ),
    )
    monkeypatch.setattr(
        production,
        "OrchestrationConfigLoader",
        lambda _root: SimpleNamespace(
            load=lambda _path: SimpleNamespace(
                operational_alerts_enabled=alerts_enabled
            )
        ),
    )
    monkeypatch.setattr(
        production.ProductionOrchestrationApplication,
        "_active_subject",
        staticmethod(lambda _path: (1, "subject-1")),
    )
    monkeypatch.setattr(
        production,
        "inspect_gmail_environment",
        lambda: SimpleNamespace(code="gmail_mcp_available"),
    )

    result = production.ProductionOrchestrationApplication(tmp_path).doctor()

    assert result["status"] == "ready"
    assert result["checks"]["configuration"] == "ready"
    assert ("alert_recipient" in result["checks"]) is alerts_enabled


def test_mail_workflow_uses_configured_workflow_deadline(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    def tool_factory(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    monkeypatch.setattr(production, "OrchestrationTool", tool_factory)
    foundation = SimpleNamespace(
        database_path=tmp_path / "data.db",
        state_root=tmp_path / "state",
        data_root=tmp_path,
    )
    config = SimpleNamespace(
        operational_alerts_enabled=False,
        workflow_deadline_seconds=3600,
        log_root=tmp_path / "logs",
    )

    production.ProductionOrchestrationApplication(tmp_path)._tool(
        foundation, config, object(), object()
    )

    assert captured["mail_deadline_seconds"] == 900


@pytest.mark.parametrize(
    ("kind", "workflow_key", "expected_subject", "expected_invocation"),
    (
        (
            "mail",
            "mail-poll:7:20260727T155229.484382Z",
            "7",
            "20260727T155229.484382Z",
        ),
        (
            "health_check",
            "health-check:host-84245:20260727T155229.484382Z",
            None,
            "host-84245:20260727T155229.484382Z",
        ),
    ),
)
def test_interval_due_preserves_scheduler_workflow_identity(
    tmp_path, monkeypatch, kind, workflow_key, expected_subject,
    expected_invocation,
) -> None:
    captured = {}

    class Tool:
        def execute(self, request):
            captured["request"] = request
            return SimpleNamespace(as_json_dict=lambda: {"status": "succeeded"})

    foundation = SimpleNamespace(database_path=tmp_path / "data.db")
    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    app = production.ProductionOrchestrationApplication(tmp_path)
    monkeypatch.setattr(
        app,
        "_components",
        lambda: (foundation, SimpleNamespace(workflow_deadline_seconds=3600), object(), object()),
    )
    monkeypatch.setattr(app, "_active_subject", lambda _path: (7, "subject-7"))
    monkeypatch.setattr(app, "_tool", lambda *_args: Tool())
    due = datetime(2026, 7, 27, 15, 52, 29, 484382, tzinfo=UTC)
    item = DueItem(
        "mail_poll" if kind == "mail" else "health_check",
        workflow_key,
        kind,
        "scheduled",
        due,
        due + timedelta(seconds=60),
        None,
        due + timedelta(hours=1),
    )

    assert app._execute_due(item) == {"status": "succeeded"}
    request = captured["request"]
    assert request.subject_id == expected_subject
    assert request.invocation_id == expected_invocation


def test_due_mail_recovery_reexecutes_persisted_workflow_identity(
    tmp_path, monkeypatch
) -> None:
    captured = {}
    started = datetime(2026, 7, 29, 2, 3, 10, tzinfo=UTC)
    retry_at = started + timedelta(minutes=5)
    deadline = started + timedelta(hours=1)
    workflow_key = "mail-poll:7:20260729T020310.724913Z"

    class Tool:
        def execute(self, request):
            captured["request"] = request
            return SimpleNamespace(
                as_json_dict=lambda: {
                    "status": "succeeded",
                    "workflow_key": workflow_key,
                }
            )

    workflow = SimpleNamespace(
        workflow_kind="mail",
        logical_local_date=None,
        trigger_kind="scheduled",
        parent_workflow_run_id=None,
        deadline_at_utc=deadline,
        started_at_utc=started,
    )
    repository = SimpleNamespace(
        load_workflow_definition=lambda key: (
            SimpleNamespace(workflow=workflow) if key == workflow_key else None
        )
    )
    foundation = SimpleNamespace(database_path=tmp_path / "data.db")
    config = SimpleNamespace(workflow_deadline_seconds=3600)
    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    app = production.ProductionOrchestrationApplication(tmp_path)
    monkeypatch.setattr(
        app,
        "_components",
        lambda: (foundation, config, repository, object()),
    )
    monkeypatch.setattr(app, "_active_subject", lambda _path: (7, "subject-7"))
    monkeypatch.setattr(app, "_tool", lambda *_args: Tool())
    monkeypatch.setattr(
        app,
        "reconcile",
        lambda _key: (_ for _ in ()).throw(
            AssertionError("resumable recovery must execute, not only inspect")
        ),
    )
    decision = RecoveryDecision(
        workflow_key,
        "resume_workflow",
        "workflow_retry_due",
        "mail:0",
        "20260729T020310.724913Z",
        retry_at,
    )
    item = DueItem(
        "recovery",
        workflow_key,
        "recovery",
        "recovery",
        retry_at,
        None,
        None,
        deadline,
        decision,
    )

    result = app._execute_due(item)

    assert result["status"] == "succeeded"
    request = captured["request"]
    assert request.workflow_kind == "mail"
    assert request.subject_id == "7"
    assert request.invocation_id == "20260729T020310.724913Z"
    assert request.trigger_kind == "scheduled"
    assert request.requested_at_utc == "2026-07-29T02:03:10Z"
    assert request.deadline_at_utc == "2026-07-29T03:03:10Z"


def test_completed_failed_workflow_creates_safe_deduplicated_incident() -> None:
    item = DueItem(
        "morning", "morning:7:2026-07-29", "morning", "scheduled",
        datetime(2026, 7, 28, 23, tzinfo=UTC), None, "2026-07-29", None,
    )
    calls: list[dict[str, object]] = []
    repository = SimpleNamespace(
        get_workflow=lambda key: (
            SimpleNamespace(id=41, workflow_kind="morning")
            if key == item.workflow_key
            else None
        ),
        record_incident=lambda **values: calls.append(values),
    )

    events = WorkflowIncidentCoordinator(repository).observe(
        workflow_key=item.workflow_key,
        workflow_kind=item.workflow_kind,
        outcome={"status": "failed", "errors": [{"code": "untrusted"}]},
        seen_at_utc=datetime(2026, 7, 28, 23, 36, tzinfo=UTC),
    )

    assert events is not None
    assert events.opened == (
        "workflow:failed:morning:5a38501f5c035749e5f701bcc925850b",
    )
    assert events.recovered == ()

    assert calls == [{
        "incident_key": "workflow:failed:morning:"
        "5a38501f5c035749e5f701bcc925850b",
        "category": "workflow", "severity": "error",
        "seen_at_utc": datetime(2026, 7, 28, 23, 36, tzinfo=UTC),
        "error_code": "workflow_execution_failed",
        "error_summary": "workflow_execution_failed",
        "next_action": "operator_review", "related_workflow_run_id": 41,
    }]


def test_deferred_mail_workflow_does_not_create_operational_incident() -> None:
    item = DueItem(
        "mail_poll",
        "mail-poll:7:20260729T020310.724913Z",
        "mail",
        "scheduled",
        datetime(2026, 7, 29, 2, 3, 10, tzinfo=UTC),
        None,
        None,
        datetime(2026, 7, 29, 2, 8, 10, tzinfo=UTC),
    )
    calls: list[dict[str, object]] = []
    repository = SimpleNamespace(
        get_workflow=lambda key: SimpleNamespace(id=42),
        record_incident=lambda **values: calls.append(values),
    )

    events = WorkflowIncidentCoordinator(repository).observe(
        workflow_key=item.workflow_key,
        workflow_kind=item.workflow_kind,
        outcome={
            "status": "deferred",
            "next_action": "continue_poll",
            "next_retry_at_utc": "2026-07-29T02:08:10Z",
        },
        seen_at_utc=datetime(2026, 7, 29, 2, 3, 11, tzinfo=UTC),
    )

    assert events is None
    assert calls == []


def test_operator_retry_executes_a_new_child_attempt(
    tmp_path, monkeypatch
) -> None:
    captured = {}
    failed = SimpleNamespace(
        id=41,
        status="failed",
        workflow_kind="morning",
        subject_id=7,
        logical_local_date="2026-07-26",
    )

    class Repository:
        def get_workflow_by_id(self, run_id):
            return failed if run_id == 41 else None

        def get_workflow(self, _workflow_key):
            return None

    class Tool:
        def execute(self, request):
            captured["request"] = request
            workflow_key = f"manual:morning:{request.invocation_id}"
            return SimpleNamespace(
                workflow_key=workflow_key,
                workflow_kind="morning",
                as_json_dict=lambda: {
                    "workflow_key": workflow_key,
                    "workflow_kind": "morning",
                    "status": "succeeded",
                },
            )

    class Coordinator:
        def __init__(self, repository):
            captured["coordinator_repository"] = repository

        def observe(self, **values):
            captured["observation"] = values
            return None

    repository = Repository()
    foundation = SimpleNamespace(database_path=tmp_path / "data.db")
    config = SimpleNamespace(
        workflow_deadline_seconds=3600,
        operational_alerts_enabled=False,
    )
    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    monkeypatch.setattr(production, "WorkflowIncidentCoordinator", Coordinator)
    app = production.ProductionOrchestrationApplication(tmp_path)
    monkeypatch.setattr(
        app,
        "_components",
        lambda: (foundation, config, repository, object()),
    )
    monkeypatch.setattr(app, "_active_subject", lambda _path: (7, "subject-7"))
    monkeypatch.setattr(app, "_tool", lambda *_args: Tool())
    monkeypatch.setattr(app, "_alert_service", lambda *_args: None)

    result = app.retry("41")

    request = captured["request"]
    assert result["status"] == "succeeded"
    assert request.workflow_kind == "morning"
    assert request.subject_id == "subject-7"
    assert request.logical_local_date == "2026-07-26"
    assert request.trigger_kind == "manual"
    assert request.parent_workflow_run_id == "41"
    assert request.invocation_id.startswith("retry-41-")
    assert captured["observation"]["workflow_key"].startswith(
        "manual:morning:retry-41-"
    )


@pytest.mark.parametrize(
    "workflow",
    (
        None,
        SimpleNamespace(
            id=41,
            status="succeeded",
            workflow_kind="morning",
            subject_id=7,
            logical_local_date="2026-07-26",
        ),
        SimpleNamespace(
            id=41,
            status="failed",
            workflow_kind="mail",
            subject_id=7,
            logical_local_date=None,
        ),
    ),
)
def test_operator_retry_rejects_nonrecoverable_workflows(
    tmp_path, monkeypatch, workflow
) -> None:
    repository = SimpleNamespace(
        get_workflow_by_id=lambda _run_id: workflow,
        get_workflow=lambda _key: workflow,
    )
    foundation = SimpleNamespace(database_path=tmp_path / "data.db")
    config = SimpleNamespace(workflow_deadline_seconds=3600)
    monkeypatch.setattr(production, "project_root", lambda _root: tmp_path)
    app = production.ProductionOrchestrationApplication(tmp_path)
    monkeypatch.setattr(
        app,
        "_components",
        lambda: (foundation, config, repository, object()),
    )
    monkeypatch.setattr(app, "_active_subject", lambda _path: (7, "subject-7"))

    assert app.retry("41") == {
        "schema_version": "1",
        "status": "rejected",
        "error_code": "workflow_not_recoverable",
    }
