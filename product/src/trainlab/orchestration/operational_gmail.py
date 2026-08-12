"""Current-environment Gmail MCP adapter for data-free operational alerts."""

from __future__ import annotations

from trainlab.integrations.gmail_delivery import (
    GmailDeliveryError,
    GmailDeliveryGateway,
)


class CurrentEnvironmentOperationalGmail:
    """Expose only the four operations admitted by ``OperationalAlertService``."""

    def __init__(self, configured_recipient: str) -> None:
        self._gateway = GmailDeliveryGateway(configured_recipient)
        self._last_delivery_message_id: str | None = None

    def search_alert(
        self, *, idempotency_key: str, subject: str
    ) -> dict[str, str] | None:
        receipt = self._gateway.reconcile(
            subject=subject, idempotency_key=idempotency_key
        )
        self._last_delivery_message_id = receipt.provider_message_id
        if receipt.status != "already_sent" or receipt.provider_message_id is None:
            return None
        result = {"provider_message_id": receipt.provider_message_id}
        provider_thread_id = getattr(receipt, "provider_thread_id", None)
        if provider_thread_id is not None:
            result["provider_thread_id"] = provider_thread_id
        return result

    def send_html(
        self,
        *,
        recipient: str,
        idempotency_key: str,
        subject: str,
        html: str,
    ) -> dict[str, str]:
        # GmailDeliveryGateway owns recipient validation and never accepts a
        # caller-selected address after construction.
        receipt = self._gateway.deliver(
            subject=subject,
            idempotency_key=idempotency_key,
            plain_text="TrainLab 运维告警。请查看 HTML 正文。",
            html=html,
        )
        if receipt.provider_message_id is None:
            raise GmailDeliveryError(
                "gmail_delivery_protocol_invalid",
                may_have_sent=receipt.status in {"sent", "already_sent"},
            )
        self._last_delivery_message_id = receipt.provider_message_id
        result = {"provider_message_id": receipt.provider_message_id}
        provider_thread_id = getattr(receipt, "provider_thread_id", None)
        if provider_thread_id is not None:
            result["provider_thread_id"] = provider_thread_id
        return result

    def apply_trainlab_label(self, provider_message_id: str) -> None:
        # The reused restricted gateway applies TrainLab before returning.
        if provider_message_id != self._last_delivery_message_id:
            raise GmailDeliveryError("gmail_delivery_message_identity_invalid")
