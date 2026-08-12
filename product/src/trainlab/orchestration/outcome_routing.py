"""Pure S5-11 receipt routing and bounded retry advice.

This module deliberately owns no database or subprocess.  The executor passes
in an already schema-validated :class:`DownstreamResult`, persists the returned
decision, and (only when due) invokes the exact typed call it already owns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from .subprocess_runner import DownstreamCall, DownstreamResult


RouteAction = Literal[
    "continue", "partial", "retry", "defer", "reconcile_delivery",
    "attention_required",
]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Explicit, deterministic cross-invocation retry limits."""

    max_attempts: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 900
    lock_busy_delay_seconds: int = 10

    def __post_init__(self) -> None:
        if (type(self.max_attempts) is not int or self.max_attempts < 1
                or type(self.base_delay_seconds) is not int or self.base_delay_seconds < 1
                or type(self.max_delay_seconds) is not int or self.max_delay_seconds < self.base_delay_seconds
                or type(self.lock_busy_delay_seconds) is not int or self.lock_busy_delay_seconds < 1):
            raise ValueError("retry_policy_invalid")


@dataclass(frozen=True, slots=True)
class OutcomeDecision:
    action: RouteAction
    workflow_status: Literal["succeeded", "partial", "deferred", "attention_required"]
    reason: str
    next_retry_at_utc: datetime | None = None
    incident_required: bool = False


_SUCCESS = frozenset({"succeeded", "unchanged"})
_KNOWN = frozenset({"succeeded", "unchanged", "partial", "deferred", "lock_busy", "auth_required", "rejected", "failed"})
_RETRYABLE_FAILURE_CODES = frozenset({
    "rate_limited", "provider_unavailable", "service_unavailable",
    "temporary_failure", "transient_failure", "network_unavailable",
})


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("outcome_time_invalid")
    return value


def _receipt_retry(value: object) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("receipt_next_retry_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("receipt_next_retry_invalid") from error
    return _utc(parsed)


def _retry_at(call: DownstreamCall, now: datetime, attempt_count: int, policy: RetryPolicy, *, lock_busy: bool, lower: datetime | None) -> datetime:
    if attempt_count < 1:
        raise ValueError("retry_attempt_invalid")
    if lock_busy:
        local = now + timedelta(seconds=policy.lock_busy_delay_seconds)
    else:
        delay = min(policy.max_delay_seconds, policy.base_delay_seconds * (2 ** (attempt_count - 1)))
        # A stable tiny jitter avoids synchronized retries, without a clock or RNG.
        key = f"{call.layer}:{call.invocation_id}:{attempt_count}".encode()
        local = now + timedelta(seconds=delay + (sha256(key).digest()[0] % max(1, delay // 5 + 1)))
    return max(local, lower) if lower is not None else local


def _identity_valid(call: DownstreamCall, result: DownstreamResult) -> bool:
    receipt = result.receipt
    if result.kind != "accepted" or receipt is None or receipt.get("mode") != call.mode:
        return False
    # Garmin's frozen public receipt has no invocation_id.  Its date/range and
    # mode identity are already validated by SubprocessRunner before this pure
    # routing stage.
    return call.layer == "garmin" or receipt.get("invocation_id") == call.invocation_id


def _error_codes(receipt: object) -> frozenset[str]:
    if type(receipt) is not dict and not hasattr(receipt, "get"):
        return frozenset()
    errors = receipt.get("errors")  # type: ignore[union-attr]
    if type(errors) is not list:
        return frozenset()
    return frozenset(item.get("code") for item in errors if type(item) is dict and type(item.get("code")) is str)


def route_outcome(
    call: DownstreamCall,
    result: DownstreamResult,
    *,
    now_utc: datetime,
    attempt_count: int,
    policy: RetryPolicy = RetryPolicy(),
) -> OutcomeDecision:
    """Classify one result without reading payload text or creating an invocation.

    Invalid/timeout results and identity/schema failures are intentionally
    attention-required: a send side effect may be unknown and must be reconciled
    through the owning layer rather than retried speculatively.
    """

    now = _utc(now_utc)
    if type(call) is not DownstreamCall or type(result) is not DownstreamResult:
        raise ValueError("outcome_input_invalid")
    if type(attempt_count) is not int or attempt_count < 1:
        raise ValueError("retry_attempt_invalid")
    if result.kind != "accepted" or not _identity_valid(call, result):
        return OutcomeDecision("attention_required", "attention_required", "receipt_untrusted", incident_required=True)
    receipt = result.receipt
    assert receipt is not None
    status = receipt.get("status")
    if status not in _KNOWN:
        return OutcomeDecision("attention_required", "attention_required", "receipt_status_unknown", incident_required=True)
    try:
        lower_retry = _receipt_retry(receipt.get("next_retry_at_utc"))
    except ValueError:
        return OutcomeDecision("attention_required", "attention_required", "receipt_next_retry_invalid", incident_required=True)
    if status in _SUCCESS:
        return OutcomeDecision("continue", "succeeded", "downstream_complete")
    if status == "partial":
        action = receipt.get("next_action")
        if action in {"retry_delivery", "reconcile_delivery"}:
            return OutcomeDecision("reconcile_delivery" if action == "reconcile_delivery" else "partial", "partial", action, lower_retry)
        return OutcomeDecision("partial", "partial", "downstream_partial", lower_retry)
    if status == "deferred":
        if lower_retry is None:
            return OutcomeDecision("attention_required", "attention_required", "deferred_retry_missing", incident_required=True)
        return OutcomeDecision("defer", "deferred", "downstream_deferred", lower_retry)
    if status == "lock_busy":
        if attempt_count >= policy.max_attempts:
            return OutcomeDecision("attention_required", "attention_required", "lock_busy_budget_exhausted", incident_required=True)
        return OutcomeDecision("retry", "deferred", "lock_busy", _retry_at(call, now, attempt_count, policy, lock_busy=True, lower=lower_retry))
    if status in {"auth_required", "rejected"}:
        return OutcomeDecision("attention_required", "attention_required", str(status), incident_required=True)
    # ``failed`` is only retryable from a structured, allow-listed error code.
    if attempt_count >= policy.max_attempts:
        return OutcomeDecision("attention_required", "attention_required", "retry_budget_exhausted", incident_required=True)
    if _error_codes(receipt).isdisjoint(_RETRYABLE_FAILURE_CODES):
        return OutcomeDecision("attention_required", "attention_required", "failed_not_retryable", incident_required=True)
    return OutcomeDecision("retry", "deferred", "failed_retryable", _retry_at(call, now, attempt_count, policy, lock_busy=False, lower=lower_retry))
