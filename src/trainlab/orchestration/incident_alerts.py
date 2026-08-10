"""S5-15 incident lifecycle and restricted operational-alert delivery.

This module deliberately has no Codex, inbox, thread-reading, or host-specific
Gmail implementation.  Its production boundary names only the current Codex
MCP binding (``gmail`` / ``@artymclabin/gmail-mcp``); a caller must supply that
restricted transport.  The recipient is fixed project configuration and can
never be supplied by a workflow or CLI request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from typing import Callable, Literal, Protocol

from .repository import AlertDeliveryRecord, IncidentRecord, OrchestrationRepository

GMAIL_MCP_SERVER_NAME = "gmail"
GMAIL_MCP_PACKAGE = "@artymclabin/gmail-mcp"

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SEVERITY_LABELS = {
    "info": "信息",
    "warning": "警告",
    "error": "错误",
    "critical": "严重",
}


class OperationalAlertTransport(Protocol):
    """The only Gmail operations allowed for fifth-layer operational alerts."""

    def search_alert(
        self, *, idempotency_key: str, subject: str
    ) -> dict[str, str] | None: ...

    def send_html(
        self, *, recipient: str, idempotency_key: str, subject: str, html: str
    ) -> dict[str, str]: ...

    def apply_trainlab_label(self, provider_message_id: str) -> None: ...


@dataclass(frozen=True)
class GmailMcpAlertBoundary:
    """Immutable, host-independent declaration of the permitted MCP binding."""

    server_name: str = GMAIL_MCP_SERVER_NAME
    package_name: str = GMAIL_MCP_PACKAGE

    def __post_init__(self) -> None:
        if (
            self.server_name != GMAIL_MCP_SERVER_NAME
            or self.package_name != GMAIL_MCP_PACKAGE
        ):
            raise ValueError("operational_alert_gmail_binding_invalid")


@dataclass(frozen=True)
class OperationalAlertResult:
    """Data-free result suitable for an orchestration receipt or audit log."""

    incident_key: str
    event: Literal["open", "recovery"]
    alert_status: str | None
    action: Literal[
        "sent", "already_sent", "suppressed", "unavailable", "delivery_unknown"
    ]
    idempotency_key: str | None
    error_code: str | None = None


def _validate_recipient(value: str) -> str:
    normalized = value.strip().lower()
    if not _EMAIL.fullmatch(normalized):
        raise ValueError("operational_alert_recipient_invalid")
    return normalized


def alert_idempotency_key(incident_key: str, event: Literal["open", "recovery"]) -> str:
    """Return a stable bounded key; occurrence count must never affect it."""

    if event not in {"open", "recovery"}:
        raise ValueError("operational_alert_event_invalid")
    digest = sha256(
        f"operational-alert-v1\0{incident_key}\0{event}".encode()
    ).hexdigest()
    return f"ops-{digest[:60]}"


def render_operational_alert(
    incident: IncidentRecord, *, event: Literal["open", "recovery"]
) -> tuple[str, str]:
    """Render the fixed, payload-free alert subject and HTML.

    Repository-controlled codes are intentionally the only dynamic values.  This
    excludes health values, mail text, plans, prompts, provider URLs and secrets.
    """

    if event not in {"open", "recovery"}:
        raise ValueError("operational_alert_event_invalid")
    state = "已恢复" if event == "recovery" else "需要处理"
    severity = _SEVERITY_LABELS[incident.severity]
    subject = f"[TrainLab][运维][{severity}] {incident.incident_key} {state}"
    action = incident.next_action or "review_incident"
    code = incident.error_code or "not_recorded"
    html = (
        "<html><body><h2>TrainLab 运维告警</h2>"
        f"<p><b>状态：</b>{escape(state)}</p>"
        f"<p><b>时间：</b>{escape(incident.last_seen_at_utc)}</p>"
        f"<p><b>组件：</b>{escape(incident.category)}</p>"
        f"<p><b>严重性：</b>{escape(incident.severity)}</p>"
        f"<p><b>事件：</b>{escape(incident.incident_key)}</p>"
        f"<p><b>错误代码：</b>{escape(code)}</p>"
        f"<p><b>建议动作：</b>{escape(action)}</p>"
        "<p>此邮件不包含健康数据、活动详情、用户邮件、训练计划或凭据。</p>"
        "</body></html>"
    )
    return subject, html


class IncidentManager:
    """Small lifecycle facade around the audited repository state machine."""

    def __init__(self, repository: OrchestrationRepository) -> None:
        self._repository = repository

    def observe(
        self,
        *,
        incident_key: str,
        category: str,
        severity: Literal["info", "warning", "error", "critical"],
        seen_at_utc: datetime,
        error_code: str | None = None,
        next_action: str | None = None,
        related_workflow_run_id: int | None = None,
        related_step_id: int | None = None,
    ) -> IncidentRecord:
        return self._repository.record_incident(
            incident_key=incident_key,
            category=category,
            severity=severity,
            seen_at_utc=seen_at_utc,
            error_code=error_code,
            next_action=next_action,
            related_workflow_run_id=related_workflow_run_id,
            related_step_id=related_step_id,
        )

    def acknowledge(self, incident_key: str, *, at_utc: datetime) -> IncidentRecord:
        return self._repository.transition_incident(
            incident_key, "acknowledged", at_utc=at_utc
        )

    def suppress(self, incident_key: str, *, at_utc: datetime) -> IncidentRecord:
        return self._repository.transition_incident(
            incident_key, "suppressed", at_utc=at_utc
        )

    def resolve(self, incident_key: str, *, at_utc: datetime) -> IncidentRecord:
        return self._repository.transition_incident(
            incident_key, "resolved", at_utc=at_utc
        )


class OperationalAlertService:
    """Idempotent alert/reconcile service with no recursive Gmail-failure alert."""

    def __init__(
        self,
        repository: OrchestrationRepository,
        transport: OperationalAlertTransport,
        *,
        configured_recipient: str,
        boundary: GmailMcpAlertBoundary | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._transport = transport
        self._configured_recipient = _validate_recipient(configured_recipient)
        self._boundary = boundary or GmailMcpAlertBoundary()
        self._clock = clock or (lambda: datetime.now(UTC))

    def deliver(
        self, incident_key: str, *, event: Literal["open", "recovery"] = "open"
    ) -> OperationalAlertResult:
        incident = self._repository.get_incident(incident_key)
        if incident is None:
            raise ValueError("operational_alert_incident_not_found")
        if event == "open" and incident.state == "suppressed":
            return OperationalAlertResult(incident_key, event, None, "suppressed", None)

        key = alert_idempotency_key(incident_key, event)
        subject, html = render_operational_alert(incident, event=event)
        alert = self._repository.create_alert_delivery(
            incident_key=incident_key, idempotency_key=key
        )
        if alert.status in {"sent", "already_sent"}:
            return OperationalAlertResult(
                incident_key, event, alert.status, "already_sent", key
            )
        # Never allow a process that finds a crash-point state to continue into
        # a new provider call.  Reconciliation is the only safe next action.
        if alert.status in {"sending", "delivery_unknown"}:
            return self.reconcile(incident_key, event=event)
        if alert.status == "failed" and alert.error_code == "gmail_not_found":
            return OperationalAlertResult(
                incident_key,
                event,
                alert.status,
                "unavailable",
                key,
                "gmail_not_found",
            )

        try:
            found = self._transport.search_alert(idempotency_key=key, subject=subject)
            if found is not None:
                alert = self._transition_if_needed(key, "already_sent", response=found)
                return OperationalAlertResult(
                    incident_key, event, alert.status, "already_sent", key
                )
        except Exception:
            self._mark_failed_or_unknown(alert, key, unknown=False)
            saved = self._repository.get_alert_delivery(key)
            if saved is None:
                raise ValueError("operational_alert_not_found")
            return OperationalAlertResult(
                incident_key,
                event,
                saved.status,
                "unavailable",
                key,
                "gmail_unavailable",
            )

        alert = self._transition_if_needed(key, "sending")
        try:
            response = self._transport.send_html(
                recipient=self._configured_recipient,
                idempotency_key=key,
                subject=subject,
                html=html,
            )
            message_id = response.get("provider_message_id")
            if not isinstance(message_id, str) or not message_id:
                raise RuntimeError("gmail_send_result_invalid")
            # The provider has accepted the message at this point.  Save its
            # receipt before a subsequent local operation can crash.
            alert = self._transition_if_needed(
                key,
                "delivery_unknown",
                response=response,
                error_code="gmail_receipt_unverified",
            )
            self._transport.apply_trainlab_label(message_id)
        except Exception:
            self._mark_failed_or_unknown(alert, key, unknown=True)
            saved = self._repository.get_alert_delivery(key)
            if saved is None:
                raise ValueError("operational_alert_not_found")
            return OperationalAlertResult(
                incident_key,
                event,
                saved.status,
                "delivery_unknown",
                key,
                "gmail_send_unknown",
            )
        alert = self._transition_if_needed(key, "sent", response=response)
        return OperationalAlertResult(incident_key, event, alert.status, "sent", key)

    def reconcile(
        self, incident_key: str, *, event: Literal["open", "recovery"] = "open"
    ) -> OperationalAlertResult:
        key = alert_idempotency_key(incident_key, event)
        incident = self._repository.get_incident(incident_key)
        if incident is None:
            raise ValueError("operational_alert_incident_not_found")
        subject, _html = render_operational_alert(incident, event=event)
        alert = self._repository.get_alert_delivery(key)
        if alert is None:
            raise ValueError("operational_alert_not_found")
        if alert.status in {"sent", "already_sent"}:
            return OperationalAlertResult(
                incident_key, event, alert.status, "already_sent", key
            )
        if alert.status not in {"sending", "delivery_unknown"}:
            return OperationalAlertResult(
                incident_key,
                event,
                alert.status,
                "unavailable",
                key,
                "reconcile_not_applicable",
            )
        try:
            found = self._transport.search_alert(idempotency_key=key, subject=subject)
        except Exception:
            return OperationalAlertResult(
                incident_key,
                event,
                alert.status,
                "unavailable",
                key,
                "gmail_unavailable",
            )
        if found is not None:
            alert = self._transition_if_needed(key, "already_sent", response=found)
            return OperationalAlertResult(
                incident_key, event, alert.status, "already_sent", key
            )
        if alert.status == "sending":
            alert = self._transition_if_needed(
                key, "delivery_unknown", error_code="gmail_not_found"
            )
            return OperationalAlertResult(
                incident_key,
                event,
                alert.status,
                "delivery_unknown",
                key,
                "gmail_not_found",
            )
        alert = self._transition_if_needed(key, "failed", error_code="gmail_not_found")
        return OperationalAlertResult(
            incident_key,
            event,
            alert.status,
            "delivery_unknown",
            key,
            "gmail_not_found",
        )

    def reconcile_outstanding(self) -> tuple[OperationalAlertResult, ...]:
        """Reconcile ambiguous sends left by a prior process before new work."""

        results: list[OperationalAlertResult] = []
        for incident, alert in self._repository.reconcilable_alert_deliveries():
            open_key = alert_idempotency_key(incident.incident_key, "open")
            recovery_key = alert_idempotency_key(incident.incident_key, "recovery")
            if alert.idempotency_key == open_key:
                event: Literal["open", "recovery"] = "open"
            elif alert.idempotency_key == recovery_key:
                event = "recovery"
            else:
                continue
            results.append(self.reconcile(incident.incident_key, event=event))
        return tuple(results)

    def _mark_failed_or_unknown(
        self, alert: AlertDeliveryRecord, key: str, *, unknown: bool
    ) -> None:
        if alert.status == "pending":
            self._transition_if_needed(
                key,
                "delivery_unknown" if unknown else "failed",
                error_code="gmail_send_unknown" if unknown else "gmail_unavailable",
            )
        elif alert.status == "sending":
            self._transition_if_needed(
                key,
                "delivery_unknown" if unknown else "failed",
                error_code="gmail_send_unknown" if unknown else "gmail_unavailable",
            )

    def _transition_if_needed(
        self,
        key: str,
        status: Literal[
            "sending", "sent", "already_sent", "failed", "delivery_unknown"
        ],
        *,
        response: dict[str, str] | None = None,
        error_code: str | None = None,
    ) -> AlertDeliveryRecord:
        current = self._repository.get_alert_delivery(key)
        if current is None:
            raise ValueError("operational_alert_not_found")
        return self._repository.transition_alert_delivery(
            key,
            status,
            at_utc=self._clock() if status in {"sent", "already_sent"} else None,
            provider_message_id=(response or {}).get("provider_message_id"),
            provider_thread_id=(response or {}).get("provider_thread_id"),
            error_code=error_code,
            error_summary=error_code,
        )
