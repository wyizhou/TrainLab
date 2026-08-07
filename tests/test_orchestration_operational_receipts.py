from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.fakes import FakeGmailTransport
from trainlab.orchestration.incident_alerts import (
    IncidentManager,
    OperationalAlertService,
    alert_idempotency_key,
)
from trainlab.orchestration.repository import (
    OrchestrationRepository,
    OrchestrationRepositoryError,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)


def make_service(tmp_path: Path, transport: FakeGmailTransport | None = None):
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
            FoundationRequest("init", "ops-receipt-fixture", "2026-08-07T00:00:00Z")
        )
        .ready
    )
    repository = OrchestrationRepository(root / "data.db")
    incident = IncidentManager(repository).observe(
        incident_key="mail:provider",
        category="mail",
        severity="error",
        seen_at_utc=NOW,
        error_code="provider",
        next_action="review_incident",
    )
    return (
        repository,
        incident,
        OperationalAlertService(
            repository,
            transport or FakeGmailTransport(),
            configured_recipient="owner@example.invalid",
            clock=lambda: NOW,
        ),
    )


def test_pending_send_persists_provider_receipt_and_verified_time(
    tmp_path: Path,
) -> None:
    repository, incident, service = make_service(tmp_path)
    result = service.deliver(incident.incident_key)
    saved = repository.get_alert_delivery(result.idempotency_key)
    assert (result.action, saved.status) == ("sent", "sent")
    assert saved.provider_message_id == "synthetic-alert-message"
    assert saved.sent_at_utc == "2026-08-07T00:00:00Z"
    assert saved.last_verified_at_utc == "2026-08-07T00:00:00Z"


def test_sending_before_provider_call_search_absence_stays_ambiguous(
    tmp_path: Path,
) -> None:
    repository, incident, service = make_service(tmp_path)
    key = alert_idempotency_key(incident.incident_key, "open")
    repository.create_alert_delivery(
        incident_key=incident.incident_key, idempotency_key=key
    )
    repository.transition_alert_delivery(key, "sending")
    result = service.deliver(incident.incident_key)
    assert (result.action, repository.get_alert_delivery(key).status) == (
        "delivery_unknown",
        "delivery_unknown",
    )
    assert not [
        call
        for call in service._transport.operations
        if call["operation"] == "send_html"
    ]


def test_sending_after_provider_call_reconciles_receipt_without_resend(
    tmp_path: Path,
) -> None:
    transport = FakeGmailTransport()
    repository, incident, service = make_service(tmp_path, transport)
    key = alert_idempotency_key(incident.incident_key, "open")
    repository.create_alert_delivery(
        incident_key=incident.incident_key, idempotency_key=key
    )
    repository.transition_alert_delivery(key, "sending")
    transport.known_idempotency_keys.add(key)
    result = service.reconcile(incident.incident_key)
    saved = repository.get_alert_delivery(key)
    assert (result.action, saved.status) == ("already_sent", "already_sent")
    assert saved.provider_message_id and saved.last_verified_at_utc
    assert not [
        call for call in transport.operations if call["operation"] == "send_html"
    ]


def test_delivery_unknown_absence_finishes_non_send_recovery(tmp_path: Path) -> None:
    repository, incident, service = make_service(tmp_path)
    key = alert_idempotency_key(incident.incident_key, "open")
    repository.create_alert_delivery(
        incident_key=incident.incident_key, idempotency_key=key
    )
    repository.transition_alert_delivery(
        key, "delivery_unknown", error_code="gmail_send_unknown"
    )
    result = service.reconcile(incident.incident_key)
    assert (result.action, repository.get_alert_delivery(key).status) == (
        "delivery_unknown",
        "failed",
    )
    assert service.deliver(incident.incident_key).action == "unavailable"
    assert not [
        call
        for call in service._transport.operations
        if call["operation"] == "send_html"
    ]


def test_sent_and_already_sent_are_idempotent_receipted_terminals(
    tmp_path: Path,
) -> None:
    repository, incident, service = make_service(tmp_path)
    first = service.deliver(incident.incident_key)
    saved = repository.get_alert_delivery(first.idempotency_key)
    assert service.deliver(incident.incident_key).action == "already_sent"
    assert (
        repository.transition_alert_delivery(
            first.idempotency_key,
            "sent",
            provider_message_id=saved.provider_message_id,
            at_utc=NOW,
        )
        == saved
    )
    with pytest.raises(OrchestrationRepositoryError, match="receipt_conflict"):
        repository.transition_alert_delivery(
            first.idempotency_key,
            "sent",
            provider_message_id="different",
            at_utc=NOW,
        )


def test_repository_rejects_unreceipted_success(tmp_path: Path) -> None:
    repository, incident, _service = make_service(tmp_path)
    key = alert_idempotency_key(incident.incident_key, "open")
    repository.create_alert_delivery(
        incident_key=incident.incident_key, idempotency_key=key
    )
    repository.transition_alert_delivery(key, "sending")
    with pytest.raises(OrchestrationRepositoryError, match="receipt_required"):
        repository.transition_alert_delivery(key, "sent", at_utc=NOW)


def test_failed_partition_is_not_a_silent_resend_after_ambiguity(
    tmp_path: Path,
) -> None:
    repository, incident, service = make_service(tmp_path)
    key = alert_idempotency_key(incident.incident_key, "open")
    repository.create_alert_delivery(
        incident_key=incident.incident_key, idempotency_key=key
    )
    repository.transition_alert_delivery(key, "delivery_unknown")
    repository.transition_alert_delivery(key, "failed", error_code="gmail_not_found")
    assert service.deliver(incident.incident_key).action == "unavailable"
