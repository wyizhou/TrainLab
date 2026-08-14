"""M4-11 recovery policy is deterministic, finite, and offline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.mail_agent.recovery import (
    DeliveryCandidate,
    MailRecoveryError,
    RetryPolicy,
    decide_retry,
    reconcile_unknown_delivery,
    recover_label_only,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def test_retry_uses_injected_jitter_with_bounded_exponential_backoff() -> None:
    decision = decide_retry(
        error_kind="network",
        attempt_count=2,
        now=NOW,
        deadline=NOW + timedelta(minutes=5),
        policy=RetryPolicy(base_delay_seconds=4, max_delay_seconds=30),
        jitter=lambda: 0.25,
    )
    assert decision.action == "retry"
    assert decision.next_retry_at_utc == "2026-07-27T00:00:10Z"
    assert decision.resend_allowed is False


@pytest.mark.parametrize(
    ("retry_after", "deadline_seconds", "action", "code"),
    [
        (30, 60, "retry", "retry_scheduled"),
        (121, 600, "deferred", "rate_limited"),
        (30, 10, "deferred", "deadline_would_be_exceeded"),
    ],
)
def test_429_respects_inline_wait_and_deadline(
    retry_after: int, deadline_seconds: int, action: str, code: str
) -> None:
    decision = decide_retry(
        error_kind="rate_limited",
        attempt_count=1,
        now=NOW,
        deadline=NOW + timedelta(seconds=deadline_seconds),
        retry_after_seconds=retry_after,
    )
    assert (decision.action, decision.code) == (action, code)


def test_401_refreshes_once_then_requires_auth_and_403_is_rejected() -> None:
    initial = decide_retry(
        error_kind="auth", attempt_count=1, now=NOW, deadline=NOW + timedelta(seconds=1)
    )
    repeated = decide_retry(
        error_kind="auth",
        attempt_count=1,
        now=NOW,
        deadline=NOW + timedelta(seconds=1),
        auth_refresh_attempted=True,
    )
    forbidden = decide_retry(
        error_kind="forbidden",
        attempt_count=1,
        now=NOW,
        deadline=NOW + timedelta(seconds=1),
    )
    assert (initial.action, initial.code) == ("refresh_auth", "refresh_auth_once")
    assert (repeated.action, repeated.code) == ("auth_required", "auth_required")
    assert (forbidden.action, forbidden.code) == ("rejected", "forbidden")


def test_deadline_and_budget_stop_retry_without_looping() -> None:
    deadline = decide_retry(
        error_kind="timeout", attempt_count=1, now=NOW, deadline=NOW
    )
    budget = decide_retry(
        error_kind="server",
        attempt_count=5,
        now=NOW,
        deadline=NOW + timedelta(minutes=1),
    )
    assert (deadline.action, deadline.code) == ("deferred", "deadline_reached")
    assert (budget.action, budget.code) == ("failed", "retry_budget_exhausted")


def test_unknown_delivery_requires_exactly_one_run_and_thread_match_and_never_resends() -> (
    None
):
    one = reconcile_unknown_delivery(
        expected_run_id="run-1",
        expected_thread_id="thread-1",
        candidates=(DeliveryCandidate("message-1", "thread-1", "run-1"),),
    )
    none = reconcile_unknown_delivery(
        expected_run_id="run-1",
        expected_thread_id="thread-1",
        candidates=(DeliveryCandidate("message-2", "thread-2", "run-1"),),
    )
    many = reconcile_unknown_delivery(
        expected_run_id="run-1",
        expected_thread_id="thread-1",
        candidates=(
            DeliveryCandidate("message-1", "thread-1", "run-1"),
            DeliveryCandidate("message-2", "thread-1", "run-1"),
        ),
    )
    assert (one.action, one.provider_message_id, one.resend_allowed) == (
        "record_sent",
        "message-1",
        False,
    )
    assert (none.action, none.code, none.resend_allowed) == (
        "operator_review",
        "delivery_not_found",
        False,
    )
    assert (many.action, many.code, many.resend_allowed) == (
        "operator_review",
        "duplicate_delivery_conflict",
        False,
    )


def test_label_only_recovery_never_sends_again() -> None:
    sent = recover_label_only(delivery_status="sent", provider_message_id="message-1")
    unknown = recover_label_only(
        delivery_status="delivery_unknown", provider_message_id="message-1"
    )
    assert (sent.action, sent.code, sent.resend_allowed) == (
        "apply_label",
        "label_pending",
        False,
    )
    assert (unknown.action, unknown.code, unknown.resend_allowed) == (
        "operator_review",
        "label_recovery_evidence_missing",
        False,
    )


def test_invalid_jitter_is_rejected_before_scheduling() -> None:
    with pytest.raises(MailRecoveryError, match="mail_recovery_jitter_invalid"):
        decide_retry(
            error_kind="network",
            attempt_count=1,
            now=NOW,
            deadline=NOW + timedelta(minutes=1),
            jitter=lambda: 1.0,
        )
