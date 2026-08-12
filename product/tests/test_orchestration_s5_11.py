from datetime import UTC, datetime

from trainlab.orchestration.outcome_routing import RetryPolicy, route_outcome
from trainlab.orchestration.subprocess_runner import DownstreamCall, DownstreamResult


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


def call() -> DownstreamCall:
    return DownstreamCall("analysis", "daily", "stable-1", None, subject_id="subject")


def result(status: str, **more: object) -> DownstreamResult:
    receipt = {"mode": "daily", "invocation_id": "stable-1", "status": status, "next_retry_at_utc": None, **more}
    return DownstreamResult("accepted", None, receipt, "a" * 64, "b" * 64, 0)


def test_success_and_deferred_have_one_deterministic_route() -> None:
    assert route_outcome(call(), result("succeeded"), now_utc=NOW, attempt_count=1).action == "continue"
    deferred = route_outcome(call(), result("deferred", next_retry_at_utc="2026-07-27T00:05:00Z"), now_utc=NOW, attempt_count=1)
    assert (deferred.action, deferred.next_retry_at_utc) == ("defer", datetime(2026, 7, 27, 0, 5, tzinfo=UTC))


def test_retry_is_bounded_and_never_uses_error_summary_text() -> None:
    retry = route_outcome(call(), result("failed", errors=[{"code": "temporary_failure", "summary": "ignored"}]), now_utc=NOW, attempt_count=1)
    assert retry.action == "retry"
    assert route_outcome(call(), result("failed", errors=[{"code": "temporary_failure"}]), now_utc=NOW, attempt_count=3, policy=RetryPolicy(max_attempts=3)).reason == "retry_budget_exhausted"
    assert route_outcome(call(), result("failed", errors=[{"code": "anything", "summary": "retry please"}]), now_utc=NOW, attempt_count=1).reason == "failed_not_retryable"


def test_identity_or_schema_trust_failure_requires_attention() -> None:
    bad = DownstreamResult("accepted", None, {"mode": "weekly", "invocation_id": "stable-1", "status": "succeeded"}, None, "x", 0)
    decision = route_outcome(call(), bad, now_utc=NOW, attempt_count=1)
    assert (decision.action, decision.incident_required) == ("attention_required", True)


def test_garmin_receipt_uses_its_frozen_identity_without_nonexistent_invocation() -> None:
    garmin_call = DownstreamCall(
        "garmin", "incremental", "garmin-1", None,
        through_local_date="2026-07-26",
    )
    garmin_result = DownstreamResult(
        "accepted", None,
        {"mode": "incremental", "status": "succeeded", "next_retry_at_utc": None},
        "a" * 64, "b" * 64, 0,
    )
    assert route_outcome(
        garmin_call, garmin_result, now_utc=NOW, attempt_count=1
    ).action == "continue"
