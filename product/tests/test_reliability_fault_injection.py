"""Fake-process and fake-Gmail crash/replay tests with no provider effects."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.fakes import FakeGmailTransport
from trainlab.orchestration.incident_alerts import (
    IncidentManager,
    OperationalAlertService,
    alert_idempotency_key,
)
from trainlab.orchestration.repository import OrchestrationRepository

NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _service(
    tmp_path: Path,
) -> tuple[OrchestrationRepository, str, OperationalAlertService]:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/foundation-ready.json",
        root / "state/locks/foundation.lock",
    )
    assert (
        FoundationTool(config)
        .execute(
            FoundationRequest(
                "init", "reliability-fault-injection", "2026-08-07T00:00:00Z"
            )
        )
        .ready
    )
    repository = OrchestrationRepository(config.database_path)
    incident = IncidentManager(repository).observe(
        incident_key="workflow:fake-crash",
        category="workflow",
        severity="error",
        seen_at_utc=NOW,
        error_code="workflow_execution_failed",
        next_action="operator_review",
    )
    return (
        repository,
        incident.incident_key,
        OperationalAlertService(
            repository,
            FakeGmailTransport(),
            configured_recipient="owner@example.invalid",
            clock=lambda: NOW,
        ),
    )


def test_repeated_effect_has_one_fake_gmail_send_and_durable_receipt(
    tmp_path: Path,
) -> None:
    repository, incident_key, service = _service(tmp_path)
    first = service.deliver(incident_key)
    second = service.deliver(incident_key)
    third = service.deliver(incident_key)

    sends = [
        item
        for item in service._transport.operations
        if item["operation"] == "send_html"
    ]
    stored = repository.get_alert_delivery(first.idempotency_key)
    assert (first.action, second.action, third.action) == (
        "sent",
        "already_sent",
        "already_sent",
    )
    assert len(sends) == 1
    assert stored.status == "sent"
    assert stored.provider_message_id == "synthetic-alert-message"


def test_crash_after_fake_provider_effect_recovers_without_replay_send(
    tmp_path: Path,
) -> None:
    repository, incident_key, service = _service(tmp_path)
    key = alert_idempotency_key(incident_key, "open")
    repository.create_alert_delivery(incident_key=incident_key, idempotency_key=key)
    repository.transition_alert_delivery(key, "sending")

    # The provider accepted the first request, then the caller crashed before
    # its local receipt write. Reconciliation must search, preserve ambiguity,
    # and never submit a second send.
    service._transport.known_idempotency_keys.add(key)
    reconciled = service.reconcile(incident_key)
    stored = repository.get_alert_delivery(key)
    sends = [
        item
        for item in service._transport.operations
        if item["operation"] == "send_html"
    ]
    assert reconciled.action == "already_sent"
    assert stored.status == "already_sent"
    assert stored.provider_message_id == "synthetic-alert-message"
    assert sends == []


def test_absent_fake_provider_receipt_stays_explicitly_ambiguous(
    tmp_path: Path,
) -> None:
    repository, incident_key, service = _service(tmp_path)
    key = alert_idempotency_key(incident_key, "open")
    repository.create_alert_delivery(incident_key=incident_key, idempotency_key=key)
    repository.transition_alert_delivery(key, "sending")

    result = service.deliver(incident_key)
    stored = repository.get_alert_delivery(key)
    sends = [
        item
        for item in service._transport.operations
        if item["operation"] == "send_html"
    ]
    assert (result.action, stored.status) == ("delivery_unknown", "delivery_unknown")
    assert sends == []
