"""M4-13 audit checks use synthetic data and never call external services."""

from __future__ import annotations

from copy import deepcopy

from src.mail_agent.audit import audit_mail_persistence, audit_privacy


def _snapshot() -> dict[str, list[dict[str, object]]]:
    digest = "a" * 64
    return {
        "responses": [
            {
                "id": 1,
                "subject_id": 7,
                "mail_thread_id": 9,
                "response_kind": "reply",
                "revision_no": 1,
                "generated_by_mail_agent_run_id": 11,
                "content_sha256": digest,
                "is_current": 1,
                "supersedes_mail_response_artifact_id": None,
            }
        ],
        "deliveries": [
            {
                "id": 3,
                "idempotency_key": "mail:response:1:9",
                "status": "sent",
                "mail_message_id": 12,
                "provider_thread_id": "thread-9",
                "sent_at_utc": "2026-07-27T00:00:00Z",
                "last_verified_at_utc": "2026-07-27T00:00:01Z",
            }
        ],
        "delivery_artifacts": [
            {
                "mail_delivery_id": 3,
                "mail_response_artifact_id": 1,
                "content_role": "mail_response",
                "ordinal": 0,
            }
        ],
        "response_inputs": [
            {"mail_agent_run_id": 11, "ordinal": 0, "input_sha256": digest}
        ],
    }


def test_clean_synthetic_receipt_errors_and_log_text_pass_privacy_audit() -> None:
    report = audit_privacy(
        receipt={
            "status": "partial",
            "errors": [{"code": "rate_limited", "summary": "request deferred"}],
        },
        errors=({"code": "timeout", "summary": "retry later"},),
        log_like_text=("mail item completed",),
        forbidden_bodies=("private message body",),
    )
    assert report.ok and report.findings == ()


def test_privacy_audit_flags_secret_full_body_and_hidden_reasoning_without_echoing_value() -> (
    None
):
    report = audit_privacy(
        receipt={
            "error": "Bearer secret-value",
            "detail": "private message body",
            "meta": "<analysis>hidden</analysis>",
        },
        forbidden_bodies=("private message body",),
    )
    assert {item.code for item in report.findings} == {
        "secret_exposed",
        "full_body_exposed",
        "hidden_reasoning_exposed",
    }
    assert all(
        "secret-value" not in item.summary
        and "private message body" not in item.summary
        for item in report.findings
    )


def test_valid_response_delivery_revision_and_input_snapshot_passes() -> None:
    snapshot = _snapshot()
    report = audit_mail_persistence(**snapshot)
    assert report.ok and report.findings == ()


def test_audit_detects_current_revision_lineage_idempotency_and_input_invariants() -> (
    None
):
    snapshot = deepcopy(_snapshot())
    snapshot["responses"].append(
        {
            "id": 2,
            "subject_id": 7,
            "mail_thread_id": 9,
            "response_kind": "reply",
            "revision_no": 2,
            "generated_by_mail_agent_run_id": 12,
            "content_sha256": "bad",
            "is_current": 1,
            "supersedes_mail_response_artifact_id": 999,
        }
    )
    snapshot["deliveries"].append(
        {"id": 4, "idempotency_key": "mail:response:1:9", "status": "sent"}
    )
    snapshot["response_inputs"] = [
        {"mail_agent_run_id": 11, "ordinal": 1, "input_sha256": "bad"}
    ]
    report = audit_mail_persistence(**snapshot)
    assert {item.code for item in report.findings} >= {
        "response_current_ambiguous",
        "response_content_hash_invalid",
        "response_lineage_invalid",
        "delivery_idempotency_duplicate",
        "delivery_evidence_missing",
        "response_input_lineage_invalid",
    }


def test_delivery_must_have_one_exact_mail_response_relation() -> None:
    snapshot = _snapshot()
    snapshot["delivery_artifacts"] = []
    report = audit_mail_persistence(**snapshot)
    assert any(item.code == "delivery_lineage_invalid" for item in report.findings)
