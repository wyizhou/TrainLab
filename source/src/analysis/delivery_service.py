"""A3-16 one-shot delivery and recovery orchestration.

The service joins the provider-independent SQLite state machine to the
route-specific Gmail gateway.  It never regenerates analysis output and never
accepts arbitrary recipients, provider tools, subjects, or bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol

from ..integrations.gmail_delivery import GmailDeliveryError, GmailDeliveryReceipt
from .delivery import AnalysisDeliveryRepository, AnalysisDeliveryState

DeliveryMode = Literal["retry_delivery", "reconcile_delivery"]


class _Gateway(Protocol):
    def deliver(
        self, *, subject: str, idempotency_key: str, plain_text: str, html: str
    ) -> GmailDeliveryReceipt: ...

    def reconcile(
        self, *, subject: str, idempotency_key: str
    ) -> GmailDeliveryReceipt: ...


@dataclass(frozen=True)
class DeliveryExecution:
    delivery_id: int
    status: str
    provider_message_id: str | None
    provider_thread_id: str | None
    error_code: str | None
    next_action: Literal["none", "retry_delivery", "reconcile_delivery"]


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _execution(state: AnalysisDeliveryState) -> DeliveryExecution:
    if state.status in {"sent", "already_sent"}:
        next_action: Literal["none", "retry_delivery", "reconcile_delivery"] = "none"
    elif state.status in {"sending", "delivery_unknown"}:
        next_action = "reconcile_delivery"
    else:
        next_action = "retry_delivery"
    return DeliveryExecution(
        delivery_id=state.delivery_id,
        status=state.status,
        provider_message_id=state.provider_message_id,
        provider_thread_id=state.provider_thread_id,
        error_code=state.error_code,
        next_action=next_action,
    )


class AnalysisDeliveryService:
    """Execute exactly one retry or reconcile attempt for one delivery ID."""

    def __init__(
        self,
        repository: AnalysisDeliveryRepository,
        gateway: _Gateway,
        *,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    def execute(self, delivery_id: int, mode: DeliveryMode) -> DeliveryExecution:
        if mode not in {"retry_delivery", "reconcile_delivery"}:
            raise ValueError("analysis_delivery_mode_invalid")
        pending = self._repository.load_pending(delivery_id)
        state = self._repository.read_state(delivery_id, subject_id=pending.subject_id)
        if state.status in {"sent", "already_sent"}:
            return _execution(state)
        rendered = self._repository.load_rendered(
            delivery_id, subject_id=pending.subject_id
        )
        if mode == "reconcile_delivery":
            return self._reconcile(
                pending.subject_id, state, pending.idempotency_key, rendered.subject
            )
        if state.status in {"sending", "delivery_unknown"}:
            return _execution(state)

        self._repository.claim_for_send(pending.subject_id, delivery_id)
        try:
            receipt = self._gateway.deliver(
                subject=rendered.subject,
                idempotency_key=pending.idempotency_key,
                plain_text=rendered.plain_text,
                html=rendered.html,
            )
        except GmailDeliveryError as error:
            if (
                error.may_have_sent
                or error.code == "gmail_delivery_idempotency_ambiguous"
            ):
                updated = self._repository.record_delivery_unknown(
                    pending.subject_id,
                    delivery_id,
                    provider_message_id=error.provider_message_id,
                    provider_thread_id=error.provider_thread_id,
                    error_code=self._safe_error_code(error.code),
                )
            else:
                updated = self._repository.record_failed(
                    pending.subject_id,
                    delivery_id,
                    error_code=self._safe_error_code(error.code),
                )
            return _execution(updated)
        now = self._clock()
        if receipt.status == "sent":
            updated = self._repository.record_sent(
                pending.subject_id,
                delivery_id,
                provider_message_id=self._message_id(receipt),
                provider_thread_id=receipt.provider_thread_id,
                sent_at_utc=now,
                last_verified_at_utc=now,
            )
        elif receipt.status == "already_sent":
            updated = self._repository.record_search_match(
                pending.subject_id,
                delivery_id,
                provider_message_id=self._message_id(receipt),
                provider_thread_id=receipt.provider_thread_id,
                sent_at_utc=self._provider_sent_at(receipt),
                last_verified_at_utc=now,
            )
        else:
            raise RuntimeError("analysis_delivery_gateway_receipt_invalid")
        return _execution(updated)

    def _reconcile(
        self,
        subject_id: int,
        state: AnalysisDeliveryState,
        idempotency_key: str,
        subject: str,
    ) -> DeliveryExecution:
        try:
            receipt = self._gateway.reconcile(
                subject=subject, idempotency_key=idempotency_key
            )
        except GmailDeliveryError as error:
            if state.status == "sending":
                state = self._repository.record_delivery_unknown(
                    subject_id,
                    state.delivery_id,
                    provider_message_id=error.provider_message_id,
                    provider_thread_id=error.provider_thread_id,
                    error_code=self._safe_error_code(error.code),
                )
            return _execution(state)
        if receipt.status == "not_found":
            if state.status == "sending":
                state = self._repository.record_delivery_unknown(
                    subject_id,
                    state.delivery_id,
                    error_code="analysis_delivery_reconcile_not_found",
                )
            return _execution(state)
        if receipt.status != "already_sent":
            raise RuntimeError("analysis_delivery_gateway_receipt_invalid")
        updated = self._repository.record_search_match(
            subject_id,
            state.delivery_id,
            provider_message_id=self._message_id(receipt),
            provider_thread_id=receipt.provider_thread_id,
            sent_at_utc=self._provider_sent_at(receipt),
            last_verified_at_utc=self._clock(),
        )
        return _execution(updated)

    @staticmethod
    def _safe_error_code(code: str) -> str:
        # Repository codes intentionally stay in the analysis namespace.
        suffix = code.removeprefix("gmail_")
        candidate = f"analysis_delivery_{suffix}"
        if len(candidate) > 120:
            return "analysis_delivery_provider_failed"
        return candidate

    @staticmethod
    def _message_id(receipt: GmailDeliveryReceipt) -> str:
        if receipt.provider_message_id is None:
            raise RuntimeError("analysis_delivery_gateway_receipt_invalid")
        return receipt.provider_message_id

    @staticmethod
    def _provider_sent_at(receipt: GmailDeliveryReceipt) -> str:
        if receipt.provider_sent_at_utc is None:
            raise RuntimeError("analysis_delivery_gateway_receipt_invalid")
        return receipt.provider_sent_at_utc
