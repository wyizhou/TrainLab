from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from trainlab.orchestration import production
from trainlab.orchestration.due_scheduler import DueItem


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
