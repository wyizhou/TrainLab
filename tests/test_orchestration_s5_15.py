from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.fakes import FakeGmailTransport
from trainlab.orchestration.incident_alerts import (
    GmailMcpAlertBoundary,
    IncidentManager,
    OperationalAlertService,
    alert_idempotency_key,
    render_operational_alert,
)
from trainlab.orchestration.repository import OrchestrationRepository


NOW = datetime(2026, 7, 27, tzinfo=UTC)


def repository(tmp_path: Path) -> OrchestrationRepository:
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock"))
    assert tool.execute(FoundationRequest("init", "s5-15-fixture", "2026-07-27T00:00:00Z")).status == "initialized"
    return OrchestrationRepository(root / "data.db")


def service(tmp_path: Path, transport: FakeGmailTransport | None = None):
    repo = repository(tmp_path)
    manager = IncidentManager(repo)
    incident = manager.observe(incident_key="database:busy", category="database", severity="error", seen_at_utc=NOW, error_code="busy", next_action="retry")
    return repo, manager, incident, OperationalAlertService(repo, transport or FakeGmailTransport(), configured_recipient="owner@example.invalid")


def test_incident_deduplicates_lifecycle_and_alert_open_is_idempotent(tmp_path: Path) -> None:
    repo, manager, incident, alerts = service(tmp_path)
    duplicate = manager.observe(incident_key=incident.incident_key, category="database", severity="warning", seen_at_utc=NOW + timedelta(minutes=1), error_code="busy")
    assert duplicate.id == incident.id and duplicate.occurrence_count == 2
    first = alerts.deliver(incident.incident_key)
    second = alerts.deliver(incident.incident_key)
    assert (first.action, second.action) == ("sent", "already_sent")
    assert repo.get_alert_delivery(first.idempotency_key).status == "sent"
    sends = [x for x in alerts._transport.operations if x["operation"] == "send_html"]
    assert len(sends) == 1 and sends[0]["recipient"] == "owner@example.invalid"
    assert manager.acknowledge(incident.incident_key, at_utc=NOW + timedelta(minutes=2)).state == "acknowledged"
    assert manager.resolve(incident.incident_key, at_utc=NOW + timedelta(minutes=3)).state == "resolved"
    recovery = alerts.deliver(incident.incident_key, event="recovery")
    assert recovery.action == "sent" and recovery.idempotency_key != first.idempotency_key


def test_suppression_and_fixed_config_recipient_preserve_local_incident(tmp_path: Path) -> None:
    repo, manager, incident, alerts = service(tmp_path)
    manager.suppress(incident.incident_key, at_utc=NOW + timedelta(seconds=1))
    assert alerts.deliver(incident.incident_key).action == "suppressed"
    reopened = manager.observe(incident_key=incident.incident_key, category="database", severity="error", seen_at_utc=NOW + timedelta(seconds=2))
    configured = OperationalAlertService(
        repo, FakeGmailTransport(self_email="other@example.invalid"),
        configured_recipient="owner@example.invalid",
    )
    result = configured.deliver(reopened.incident_key)
    assert result.action == "sent" and repo.get_incident(reopened.incident_key).state == "open"


def test_send_unknown_reconciles_without_duplicate_send(tmp_path: Path) -> None:
    class LabelFails(FakeGmailTransport):
        def apply_trainlab_label(self, provider_message_id: str) -> None:
            super().apply_trainlab_label(provider_message_id)
            raise RuntimeError("label interrupted")

    repo, _, incident, alerts = service(tmp_path, LabelFails())
    unknown = alerts.deliver(incident.incident_key)
    assert unknown.action == "delivery_unknown" and repo.get_alert_delivery(unknown.idempotency_key).status == "delivery_unknown"
    resolved = alerts.reconcile(incident.incident_key)
    assert resolved.action == "already_sent" and repo.get_alert_delivery(unknown.idempotency_key).status == "already_sent"
    assert len([x for x in alerts._transport.operations if x["operation"] == "send_html"]) == 1


def test_fixed_gmail_boundary_and_payload_free_template(tmp_path: Path) -> None:
    _, _, incident, _ = service(tmp_path)
    assert GmailMcpAlertBoundary().server_name == "gmail"
    subject, html = render_operational_alert(incident, event="open")
    assert "[TrainLab][运维]" in subject and "database:busy" in html
    forbidden = ("token", "Health", "FIT", "用户邮件正文", "训练计划正文")
    assert not any(value in html for value in forbidden)
    assert alert_idempotency_key("database:busy", "open") == alert_idempotency_key("database:busy", "open")
