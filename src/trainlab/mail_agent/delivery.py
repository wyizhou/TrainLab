"""Offline-testable delivery orchestration for immutable Mail Agent replies.

The service is purposely wired through narrow protocols.  It neither creates a
Gmail transport nor exposes a recipient/query/tool surface.  A composition
root introduced by the CLI/application-service unit supplies the existing
restricted ``GmailMCPAdapter`` and a repository implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .gmail_adapter import GmailAdapterError, SendReceipt
from .renderer import MailRenderError, RenderedMail, render_mail_response

DeliveryStatus = Literal[
    "sent", "already_sent", "label_pending", "delivery_unknown", "rejected"
]


class MailDeliveryError(RuntimeError):
    """Stable, content-free failure that never includes a provider response."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AcceptedDeliveryTarget:
    """A repository-verified, exact immutable response eligible for sending."""

    subject_id: int
    response_artifact_id: int
    response_kind: str
    user_visible_text: str
    delivery_id: int
    idempotency_key: str
    provider_thread_id: str
    in_reply_to_provider_message_id: str
    delivery_status: str
    thread_verified: bool
    authenticated_self_verified: bool
    structured_content: object = None
    original_subject: str = ""
    generated_at_utc: str = ""


@dataclass(frozen=True, slots=True)
class MailDeliveryResult:
    delivery_id: int
    response_artifact_id: int
    status: DeliveryStatus
    next_action: str
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    error_code: str | None = None


class RestrictedMailDeliveryAdapter(Protocol):
    """The only provider capabilities the delivery service can invoke."""

    def search_run_id(
        self, *, run_id: str, max_results: int = 10
    ) -> tuple[dict[str, Any], ...]: ...

    def send_html_recipient(
        self,
        *,
        run_id: str,
        subject: str,
        plain_text: str,
        html: str,
        thread_id: str | None = None,
        in_reply_to_provider_message_id: str | None = None,
    ) -> SendReceipt: ...

    def apply_trainlab_label(
        self, *, message_id: str | None, thread_id: str | None
    ) -> None: ...


class MailDeliveryStore(Protocol):
    """Persistence boundary; implementations must use short transactions."""

    def load_accepted_delivery_target(
        self, *, subject_id: int, response_artifact_id: int
    ) -> AcceptedDeliveryTarget | None: ...

    def mark_delivery_sending(self, target: AcceptedDeliveryTarget) -> None: ...

    def mark_delivery_sent(
        self,
        target: AcceptedDeliveryTarget,
        *,
        status: Literal["sent", "already_sent"],
        provider_message_id: str,
        provider_thread_id: str,
    ) -> None: ...

    def mark_delivery_unknown(
        self, target: AcceptedDeliveryTarget, *, error_code: str
    ) -> None: ...

    def mark_label_pending(
        self,
        target: AcceptedDeliveryTarget,
        *,
        provider_message_id: str,
        provider_thread_id: str,
        status: Literal["sent", "already_sent"],
    ) -> None: ...

    def mark_delivery_conflict(
        self, target: AcceptedDeliveryTarget, *, error_code: str
    ) -> None: ...


def _safe_adapter_code(error: Exception) -> str:
    if isinstance(error, GmailAdapterError):
        environment_mapping = {
            "gmail_reply_auth_required": "auth_required",
            "gmail_reply_forbidden": "forbidden",
            "gmail_reply_rate_limited": "rate_limited",
            "gmail_reply_timeout": "gmail_transport_failed",
            "gmail_reply_transport_error": "gmail_transport_failed",
            "gmail_reply_provider_error": "gmail_transport_failed",
        }
        code = environment_mapping.get(error.code, error.code)
        allowed = {
            "auth_required",
            "forbidden",
            "rate_limited",
            "gmail_transport_failed",
            "gmail_send_result_invalid",
            "gmail_adapter_not_prepared",
        }
        return code if code in allowed else "gmail_delivery_provider_failed"
    return "gmail_delivery_provider_failed"


def _provider_identifiers(match: dict[str, Any]) -> tuple[str | None, str | None]:
    # The restricted adapter's search DTO may be mapping-version specific.
    # Accept only the two explicit IDs, never infer them from headers/subject.
    message_id = match.get("message_id")
    thread_id = match.get("thread_id")
    return (
        message_id if isinstance(message_id, str) and message_id else None,
        thread_id if isinstance(thread_id, str) and thread_id else None,
    )


class MailResponseDeliveryService:
    """Deliver one already accepted response, with preflight idempotency only.

    Unknown provider outcomes deliberately stop here.  M4-11 owns provider
    reconciliation and retry policy, so this service never sends a second time
    after any send-side exception.
    """

    def __init__(
        self, store: MailDeliveryStore, adapter: RestrictedMailDeliveryAdapter
    ) -> None:
        self._store = store
        self._adapter = adapter

    def deliver(
        self, *, subject_id: int, response_artifact_id: int
    ) -> MailDeliveryResult:
        target = self._store.load_accepted_delivery_target(
            subject_id=subject_id, response_artifact_id=response_artifact_id
        )
        if target is None:
            raise MailDeliveryError("mail_delivery_target_not_found")
        self._validate_target(target, subject_id, response_artifact_id)

        if target.delivery_status in {"sent", "already_sent"}:
            return MailDeliveryResult(
                target.delivery_id, target.response_artifact_id, "already_sent", "none"
            )
        if target.delivery_status == "delivery_unknown":
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "delivery_unknown",
                "reconcile_delivery",
            )
        # A message may have been sent but not labelled.  Applying the label is
        # a recovery action, never permission to submit a second send request.
        if target.delivery_status == "label_pending":
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "label_pending",
                "reconcile_delivery",
            )
        # This unit deliberately contains no retry policy.  Only a fresh,
        # accepted pending delivery is sendable; M4-11 decides if a failed
        # record becomes pending again after persistent evidence is checked.
        if target.delivery_status != "pending":
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "rejected",
                "operator_review",
                error_code="mail_delivery_state_not_sendable",
            )
        try:
            rendered = render_mail_response(
                response_artifact_id=target.response_artifact_id,
                response_kind=target.response_kind,
                user_visible_text=target.user_visible_text,
                delivery_run_id=target.idempotency_key,
                structured_content=target.structured_content,
                original_subject=target.original_subject,
                generated_at_utc=target.generated_at_utc,
            )
        except MailRenderError as error:
            self._store.mark_delivery_conflict(target, error_code=str(error))
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "rejected",
                "operator_review",
                error_code=str(error),
            )
        return self._preflight_or_send(target, rendered)

    @staticmethod
    def _validate_target(
        target: AcceptedDeliveryTarget, subject_id: int, response_artifact_id: int
    ) -> None:
        if (
            target.subject_id != subject_id
            or target.response_artifact_id != response_artifact_id
            or not target.thread_verified
            or not target.authenticated_self_verified
            or not isinstance(target.in_reply_to_provider_message_id, str)
            or not target.in_reply_to_provider_message_id
            or target.idempotency_key
            != f"mail:response:{response_artifact_id}:{target.provider_thread_id}"
        ):
            raise MailDeliveryError("mail_delivery_target_invalid")

    def _preflight_or_send(
        self, target: AcceptedDeliveryTarget, rendered: RenderedMail
    ) -> MailDeliveryResult:
        try:
            matches = self._adapter.search_run_id(run_id=rendered.delivery_run_id)
        except Exception as error:
            code = _safe_adapter_code(error)
            self._store.mark_delivery_unknown(target, error_code=code)
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "delivery_unknown",
                "reconcile_delivery",
                error_code=code,
            )
        if len(matches) > 1:
            self._store.mark_delivery_conflict(
                target, error_code="duplicate_delivery_conflict"
            )
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "rejected",
                "operator_review",
                error_code="duplicate_delivery_conflict",
            )
        if len(matches) == 1:
            message_id, thread_id = _provider_identifiers(matches[0])
            if message_id is None or thread_id != target.provider_thread_id:
                self._store.mark_delivery_conflict(
                    target, error_code="delivery_preflight_mismatch"
                )
                return MailDeliveryResult(
                    target.delivery_id,
                    target.response_artifact_id,
                    "rejected",
                    "operator_review",
                    error_code="delivery_preflight_mismatch",
                )
            return self._label_existing(target, message_id, thread_id)
        return self._send_once(target, rendered)

    def _label_existing(
        self, target: AcceptedDeliveryTarget, message_id: str, thread_id: str
    ) -> MailDeliveryResult:
        try:
            self._adapter.apply_trainlab_label(
                message_id=message_id, thread_id=thread_id
            )
        except Exception:
            self._store.mark_label_pending(
                target,
                provider_message_id=message_id,
                provider_thread_id=thread_id,
                status="already_sent",
            )
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "label_pending",
                "reconcile_delivery",
                provider_message_id=message_id,
                provider_thread_id=thread_id,
            )
        self._store.mark_delivery_sent(
            target,
            status="already_sent",
            provider_message_id=message_id,
            provider_thread_id=thread_id,
        )
        return MailDeliveryResult(
            target.delivery_id,
            target.response_artifact_id,
            "already_sent",
            "none",
            provider_message_id=message_id,
            provider_thread_id=thread_id,
        )

    def _send_once(
        self, target: AcceptedDeliveryTarget, rendered: RenderedMail
    ) -> MailDeliveryResult:
        self._store.mark_delivery_sending(target)
        try:
            receipt = self._adapter.send_html_recipient(
                run_id=rendered.delivery_run_id,
                subject=rendered.subject,
                plain_text=rendered.plain_text,
                html=rendered.html,
                thread_id=target.provider_thread_id,
                in_reply_to_provider_message_id=target.in_reply_to_provider_message_id,
            )
        except Exception as error:
            code = _safe_adapter_code(error)
            self._store.mark_delivery_unknown(target, error_code=code)
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "delivery_unknown",
                "reconcile_delivery",
                error_code=code,
            )
        if (
            not receipt.provider_message_id
            or receipt.provider_thread_id != target.provider_thread_id
        ):
            self._store.mark_delivery_unknown(
                target, error_code="gmail_send_receipt_mismatch"
            )
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "delivery_unknown",
                "reconcile_delivery",
                error_code="gmail_send_receipt_mismatch",
            )
        status: Literal["sent", "already_sent"] = (
            "already_sent" if receipt.already_sent else "sent"
        )
        try:
            self._adapter.apply_trainlab_label(
                message_id=receipt.provider_message_id,
                thread_id=receipt.provider_thread_id,
            )
        except Exception:
            self._store.mark_label_pending(
                target,
                provider_message_id=receipt.provider_message_id,
                provider_thread_id=receipt.provider_thread_id,
                status=status,
            )
            return MailDeliveryResult(
                target.delivery_id,
                target.response_artifact_id,
                "label_pending",
                "reconcile_delivery",
                provider_message_id=receipt.provider_message_id,
                provider_thread_id=receipt.provider_thread_id,
            )
        self._store.mark_delivery_sent(
            target,
            status=status,
            provider_message_id=receipt.provider_message_id,
            provider_thread_id=receipt.provider_thread_id,
        )
        return MailDeliveryResult(
            target.delivery_id,
            target.response_artifact_id,
            status,
            "none",
            provider_message_id=receipt.provider_message_id,
            provider_thread_id=receipt.provider_thread_id,
        )
