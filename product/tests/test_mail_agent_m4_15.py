"""M4-15 preparation is offline-only and cannot grant external authority."""

from __future__ import annotations

from trainlab.mail_agent.migration import (
    ExternalAcceptanceGate,
    compare_shadow_snapshots,
    evaluate_cutover,
    evaluate_rollback,
)


def snapshot() -> dict[str, list[dict[str, object]]]:
    return {
        "threads": [{"provider_thread_id": "thread-1", "subject_id": 7, "is_current": True, "body_text": "ignored"}],
        "messages": [{"provider_message_id": "message-1", "provider_thread_id": "thread-1", "processing_state": "sent", "source_revision_id": 4, "body_text": "never reported"}],
        "responses": [{"idempotency_key": "mail:response:1:thread-1", "provider_thread_id": "thread-1", "response_revision_no": 1, "content_sha256": "a" * 64, "is_current": True, "user_visible_text": "ignored"}],
        "deliveries": [{"idempotency_key": "mail:response:1:thread-1", "status": "sent", "provider_message_id": "message-2", "provider_thread_id": "thread-1"}],
        "cursors": [{"cursor_key": "7:gmail:tracked_threads", "observed_through_utc": "2026-07-27T00:00:00Z", "overlap_start_utc": "2026-07-25T00:00:00Z", "state": "complete"}],
    }


def test_identical_sanitized_shadow_snapshots_match() -> None:
    comparison = compare_shadow_snapshots(snapshot(), snapshot())
    assert comparison.matches and comparison.findings == ()


def test_shadow_comparator_reports_thread_message_response_delivery_and_cursor_differences_without_body() -> None:
    old, new = snapshot(), snapshot()
    new["threads"][0]["is_current"] = False
    new["messages"] = []
    new["responses"][0]["response_revision_no"] = 2
    new["deliveries"][0]["status"] = "delivery_unknown"
    new["cursors"][0]["state"] = "partial"
    comparison = compare_shadow_snapshots(old, new)
    assert {finding.entity for finding in comparison.findings} >= {
        "threads:thread-1", "messages:message-1", "responses:mail:response:1:thread-1", "deliveries:mail:response:1:thread-1", "cursors:7:gmail:tracked_threads",
    }
    assert all("ignored" not in finding.summary and "never reported" not in finding.summary for finding in comparison.findings)


def test_duplicate_or_invalid_snapshot_identity_fails_closed() -> None:
    old, new = snapshot(), snapshot()
    new["messages"].append(dict(new["messages"][0]))
    new["cursors"] = [{}]
    codes = {finding.code for finding in compare_shadow_snapshots(old, new).findings}
    assert {"snapshot_identity_duplicate", "snapshot_identity_invalid"} <= codes


def test_cutover_requires_backup_clean_shadow_exactly_one_writer_and_explicit_authorization() -> None:
    shadow = compare_shadow_snapshots(snapshot(), snapshot())
    denied = evaluate_cutover(backup_id="backup-1", shadow=shadow, old_writer_enabled=True, new_writer_enabled=True, acceptance=ExternalAcceptanceGate())
    assert denied.allowed is False
    assert {"single_writer_required", "authorization_read_only_required", "authorization_self_send_required", "authorization_reconcile_required"} <= set(denied.reasons)
    allowed = evaluate_cutover(backup_id="backup-1", shadow=shadow, old_writer_enabled=False, new_writer_enabled=True, acceptance=ExternalAcceptanceGate(True, True, True))
    assert allowed.allowed is True and allowed.reasons == ()


def test_shadow_difference_and_writer_state_block_cutover_and_rollback_needs_stopped_new_writer() -> None:
    old, new = snapshot(), snapshot(); new["deliveries"][0]["status"] = "failed"
    cutover = evaluate_cutover(backup_id=None, shadow=compare_shadow_snapshots(old, new), old_writer_enabled=False, new_writer_enabled=False, acceptance=ExternalAcceptanceGate(True, True, True))
    assert {"backup_required", "shadow_mismatch", "single_writer_required"} <= set(cutover.reasons)
    rollback = evaluate_rollback(backup_id="backup-1", new_writer_enabled=True)
    assert rollback.allowed is False and rollback.reasons == ("new_writer_must_be_stopped",)
