from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from trainlab.orchestration import production


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
