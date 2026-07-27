"""Pure provider-side contract for a mail-triggered plan revision.

This module deliberately does not open SQLite, invoke another layer, or send
mail.  It validates the immutable identifiers that Layer 4 gives Layer 5 and
the exact revision artifact Layer 5 later returns to Layer 4.  The controller
owns orchestration; this module only makes an unsafe resume fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class MailHandoffError(ValueError):
    """A bounded, public reason that a plan-revision resume is unsafe."""


def _positive(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MailHandoffError(f"mail_handoff_{name}_invalid")
    return value


def _date(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise MailHandoffError(f"mail_handoff_{name}_invalid")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise MailHandoffError(f"mail_handoff_{name}_invalid") from error
    return value


@dataclass(frozen=True, slots=True)
class PlanRevisionReason:
    """The L4-owned reference to one user request for a plan change."""

    subject_id: int
    reason_event_id: int
    triggering_mail_message_id: int
    provider_thread_id: str
    original_plan_id: int
    original_artifact_id: int
    period_start_local_date: str
    period_end_local_date: str

    def __post_init__(self) -> None:
        for name in (
            "subject_id",
            "reason_event_id",
            "triggering_mail_message_id",
            "original_plan_id",
            "original_artifact_id",
        ):
            _positive(getattr(self, name), name)
        if not isinstance(self.provider_thread_id, str) or not self.provider_thread_id:
            raise MailHandoffError("mail_handoff_provider_thread_id_invalid")
        start = _date(self.period_start_local_date, "period_start")
        end = _date(self.period_end_local_date, "period_end")
        if start > end:
            raise MailHandoffError("mail_handoff_period_invalid")

    def pending_dependency(self) -> dict[str, str]:
        """The only DTO L4 exposes before L5 invokes L3.

        ``artifact_id`` means the immutable source artifact L3 must revise;
        it is not an analysis delivery identifier and grants no send ability.
        """
        return {
            "mode": "revise-plan",
            "reason_event_id": str(self.reason_event_id),
            "artifact_id": str(self.original_artifact_id),
        }


@dataclass(frozen=True, slots=True)
class PlanRevisionArtifact:
    """The minimal, controller-supplied description of L3's returned result."""

    artifact_id: int
    subject_id: int
    artifact_kind: str
    analysis_kind: str
    analysis_status: str
    is_current: bool
    reason_event_id: int
    original_plan_id: int
    original_artifact_id: int
    period_start_local_date: str
    period_end_local_date: str

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "subject_id",
            "reason_event_id",
            "original_plan_id",
            "original_artifact_id",
        ):
            _positive(getattr(self, name), name)
        if self.artifact_kind != "weekly_training_plan":
            raise MailHandoffError("mail_handoff_artifact_kind_invalid")
        if self.analysis_kind != "plan_revision":
            raise MailHandoffError("mail_handoff_analysis_kind_invalid")
        if self.analysis_status != "succeeded":
            raise MailHandoffError("mail_handoff_analysis_status_invalid")
        if self.is_current is not True:
            raise MailHandoffError("mail_handoff_artifact_stale")
        start = _date(self.period_start_local_date, "period_start")
        end = _date(self.period_end_local_date, "period_end")
        if start > end:
            raise MailHandoffError("mail_handoff_period_invalid")


@dataclass(frozen=True, slots=True)
class ResumeReplyTarget:
    """The exact thread/message and returned revision safe for L4 to resume."""

    subject_id: int
    provider_thread_id: str
    triggering_mail_message_id: int
    reason_event_id: int
    original_plan_id: int
    original_artifact_id: int
    revised_artifact_id: int


def validate_plan_revision_resume(
    reason: PlanRevisionReason,
    artifact: PlanRevisionArtifact,
) -> ResumeReplyTarget:
    """Return one safe reply target or reject every ownership/staleness mismatch.

    No plan, analysis artifact, delivery, message state, or database row is
    mutated.  In particular, a valid result still does *not* authorize L4 to
    send L3's plan artifact; it only supplies the identity needed for a later
    L4 reply on the triggering thread.
    """
    if not isinstance(reason, PlanRevisionReason) or not isinstance(
        artifact, PlanRevisionArtifact
    ):
        raise MailHandoffError("mail_handoff_dto_invalid")
    if artifact.subject_id != reason.subject_id:
        raise MailHandoffError("mail_handoff_subject_mismatch")
    if artifact.reason_event_id != reason.reason_event_id:
        raise MailHandoffError("mail_handoff_reason_event_mismatch")
    if artifact.original_plan_id != reason.original_plan_id:
        raise MailHandoffError("mail_handoff_original_plan_mismatch")
    if artifact.original_artifact_id != reason.original_artifact_id:
        raise MailHandoffError("mail_handoff_original_artifact_mismatch")
    if (
        artifact.period_start_local_date != reason.period_start_local_date
        or artifact.period_end_local_date != reason.period_end_local_date
    ):
        raise MailHandoffError("mail_handoff_period_mismatch")
    return ResumeReplyTarget(
        subject_id=reason.subject_id,
        provider_thread_id=reason.provider_thread_id,
        triggering_mail_message_id=reason.triggering_mail_message_id,
        reason_event_id=reason.reason_event_id,
        original_plan_id=reason.original_plan_id,
        original_artifact_id=reason.original_artifact_id,
        revised_artifact_id=artifact.artifact_id,
    )
