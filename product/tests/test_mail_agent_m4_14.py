"""M4-14A provider contract: pure, offline, and controller-independent."""

from __future__ import annotations

from dataclasses import replace

import pytest

from trainlab.mail_agent.handoff import (
    MailHandoffError,
    PlanRevisionArtifact,
    PlanRevisionReason,
    validate_plan_revision_resume,
)


def reason() -> PlanRevisionReason:
    return PlanRevisionReason(
        subject_id=7,
        reason_event_id=91,
        triggering_mail_message_id=41,
        provider_thread_id="thread-9",
        original_plan_id=31,
        original_artifact_id=51,
        period_start_local_date="2026-07-27",
        period_end_local_date="2026-08-02",
    )


def artifact() -> PlanRevisionArtifact:
    return PlanRevisionArtifact(
        artifact_id=61,
        subject_id=7,
        artifact_kind="weekly_training_plan",
        analysis_kind="plan_revision",
        analysis_status="succeeded",
        is_current=True,
        reason_event_id=91,
        original_plan_id=31,
        original_artifact_id=51,
        period_start_local_date="2026-07-27",
        period_end_local_date="2026-08-02",
    )


def test_reason_exposes_only_frozen_pending_dependency_dto() -> None:
    pending = reason().pending_dependency()
    assert pending == {
        "mode": "revise-plan",
        "reason_event_id": "91",
        "artifact_id": "51",
    }
    assert "delivery_id" not in pending
    assert "recipient" not in pending


def test_matching_revision_returns_only_exact_original_thread_reply_target() -> None:
    target = validate_plan_revision_resume(reason(), artifact())
    assert target.provider_thread_id == "thread-9"
    assert target.triggering_mail_message_id == 41
    assert target.revised_artifact_id == 61
    assert target.reason_event_id == 91


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"subject_id": 8}, "mail_handoff_subject_mismatch"),
        ({"reason_event_id": 92}, "mail_handoff_reason_event_mismatch"),
        ({"original_plan_id": 32}, "mail_handoff_original_plan_mismatch"),
        ({"original_artifact_id": 52}, "mail_handoff_original_artifact_mismatch"),
        ({"period_end_local_date": "2026-08-09"}, "mail_handoff_period_mismatch"),
    ],
)
def test_resume_rejects_cross_subject_or_exact_dependency_mismatch(
    changed: dict[str, object], code: str
) -> None:
    with pytest.raises(MailHandoffError, match=code):
        validate_plan_revision_resume(reason(), replace(artifact(), **changed))


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"is_current": False}, "mail_handoff_artifact_stale"),
        ({"analysis_status": "partial"}, "mail_handoff_analysis_status_invalid"),
        ({"analysis_kind": "weekly"}, "mail_handoff_analysis_kind_invalid"),
        ({"artifact_kind": "weekly_summary"}, "mail_handoff_artifact_kind_invalid"),
    ],
)
def test_resume_rejects_stale_or_non_revision_analysis_artifacts(
    changed: dict[str, object], code: str
) -> None:
    with pytest.raises(MailHandoffError, match=code):
        replace(artifact(), **changed)


def test_handoff_module_has_no_database_or_external_service_surface() -> None:
    import trainlab.mail_agent.handoff as handoff

    source = open(handoff.__file__, encoding="utf-8").read()
    for forbidden in ("sqlite3", "gmail", "codex", "subprocess", "analysis_deliveries"):
        assert forbidden not in source.lower()
