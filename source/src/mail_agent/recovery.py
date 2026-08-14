"""Pure M4-11 retry and delivery-recovery decisions.

The delivery adapter and repository apply the returned decisions.  This module
never calls Gmail, sleeps, writes storage, or turns an unknown send into a new
send attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

RecoveryAction = Literal[
    "retry",
    "refresh_auth",
    "deferred",
    "auth_required",
    "rejected",
    "failed",
    "record_sent",
    "operator_review",
    "apply_label",
]


class MailRecoveryError(ValueError):
    """A bounded invalid-input error; it contains no provider response text."""


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MailRecoveryError(f"mail_recovery_{name}_invalid")
    return value.astimezone(timezone.utc)


def _id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise MailRecoveryError(f"mail_recovery_{name}_invalid")
    return value


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    inline_retry_after_max_seconds: int = 120

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts < 1
            or not isinstance(self.base_delay_seconds, (int, float))
            or self.base_delay_seconds <= 0
            or not isinstance(self.max_delay_seconds, (int, float))
            or self.max_delay_seconds < self.base_delay_seconds
            or not isinstance(self.inline_retry_after_max_seconds, int)
            or isinstance(self.inline_retry_after_max_seconds, bool)
            or self.inline_retry_after_max_seconds < 0
        ):
            raise MailRecoveryError("mail_recovery_policy_invalid")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    action: RecoveryAction
    code: str
    next_retry_at_utc: str | None = None
    resend_allowed: bool = False


def decide_retry(
    *,
    error_kind: Literal[
        "timeout", "network", "server", "rate_limited", "auth", "forbidden", "other"
    ],
    attempt_count: int,
    now: datetime,
    deadline: datetime,
    policy: RetryPolicy = RetryPolicy(),
    retry_after_seconds: int | None = None,
    auth_refresh_attempted: bool = False,
    jitter: Callable[[], float] = lambda: 0.0,
) -> RetryDecision:
    """Choose one finite action for a read/write operation.

    ``resend_allowed`` is intentionally always false for this generic path:
    delivery sends are retried only from an established ``pending`` state by
    the delivery service.  ``delivery_unknown`` must use reconciliation below.
    """
    if error_kind not in {
        "timeout",
        "network",
        "server",
        "rate_limited",
        "auth",
        "forbidden",
        "other",
    }:
        raise MailRecoveryError("mail_recovery_error_kind_invalid")
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or attempt_count < 1
    ):
        raise MailRecoveryError("mail_recovery_attempt_count_invalid")
    current, limit = _utc(now, "now"), _utc(deadline, "deadline")
    if limit <= current:
        return RetryDecision("deferred", "deadline_reached")
    if error_kind == "forbidden":
        return RetryDecision("rejected", "forbidden")
    if error_kind == "auth":
        return (
            RetryDecision("auth_required", "auth_required")
            if auth_refresh_attempted
            else RetryDecision("refresh_auth", "refresh_auth_once")
        )
    if attempt_count >= policy.max_attempts:
        return RetryDecision("failed", "retry_budget_exhausted")
    if retry_after_seconds is not None:
        if (
            not isinstance(retry_after_seconds, int)
            or isinstance(retry_after_seconds, bool)
            or retry_after_seconds < 0
        ):
            raise MailRecoveryError("mail_recovery_retry_after_invalid")
        wait_seconds = float(retry_after_seconds)
        if retry_after_seconds > policy.inline_retry_after_max_seconds:
            return RetryDecision(
                "deferred",
                "rate_limited",
                _stamp(current + timedelta(seconds=wait_seconds)),
            )
    else:
        if error_kind not in {"timeout", "network", "server", "rate_limited"}:
            return RetryDecision("failed", "unrecoverable_error")
        random = jitter()
        if not isinstance(random, (int, float)) or not 0.0 <= random < 1.0:
            raise MailRecoveryError("mail_recovery_jitter_invalid")
        raw = policy.base_delay_seconds * (2 ** (attempt_count - 1))
        wait_seconds = min(policy.max_delay_seconds, raw * (1.0 + float(random)))
    retry_at = current + timedelta(seconds=wait_seconds)
    if retry_at > limit:
        return RetryDecision("deferred", "deadline_would_be_exceeded", _stamp(retry_at))
    return RetryDecision("retry", "retry_scheduled", _stamp(retry_at))


@dataclass(frozen=True, slots=True)
class DeliveryCandidate:
    provider_message_id: str
    provider_thread_id: str
    run_id: str

    def __post_init__(self) -> None:
        _id(self.provider_message_id, "provider_message_id")
        _id(self.provider_thread_id, "provider_thread_id")
        _id(self.run_id, "run_id")


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    action: Literal["record_sent", "operator_review"]
    code: str
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    resend_allowed: bool = False


def reconcile_unknown_delivery(
    *,
    expected_run_id: str,
    expected_thread_id: str,
    candidates: tuple[DeliveryCandidate, ...],
) -> ReconcileDecision:
    """Resolve an unknown send only when Gmail evidence has one exact match."""
    run_id, thread_id = (
        _id(expected_run_id, "expected_run_id"),
        _id(expected_thread_id, "expected_thread_id"),
    )
    if not isinstance(candidates, tuple) or any(
        not isinstance(item, DeliveryCandidate) for item in candidates
    ):
        raise MailRecoveryError("mail_recovery_candidates_invalid")
    matches = tuple(
        item
        for item in candidates
        if item.run_id == run_id and item.provider_thread_id == thread_id
    )
    if len(matches) == 1:
        match = matches[0]
        return ReconcileDecision(
            "record_sent",
            "delivery_reconciled",
            match.provider_message_id,
            match.provider_thread_id,
        )
    if not matches:
        return ReconcileDecision("operator_review", "delivery_not_found")
    return ReconcileDecision("operator_review", "duplicate_delivery_conflict")


@dataclass(frozen=True, slots=True)
class LabelRecoveryDecision:
    action: Literal["apply_label", "operator_review"]
    code: str
    provider_message_id: str | None
    resend_allowed: bool = False


def recover_label_only(
    *, delivery_status: str, provider_message_id: str | None
) -> LabelRecoveryDecision:
    """Retry a missing label without resending an already-confirmed response."""
    if delivery_status not in {
        "sent",
        "already_sent",
        "delivery_unknown",
        "pending",
        "failed",
    }:
        raise MailRecoveryError("mail_recovery_delivery_status_invalid")
    if (
        delivery_status in {"sent", "already_sent"}
        and isinstance(provider_message_id, str)
        and provider_message_id
    ):
        return LabelRecoveryDecision(
            "apply_label", "label_pending", provider_message_id
        )
    return LabelRecoveryDecision(
        "operator_review", "label_recovery_evidence_missing", None
    )
