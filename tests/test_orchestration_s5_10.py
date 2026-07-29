from __future__ import annotations

from dataclasses import dataclass

from trainlab.orchestration.mail_workflow import (
    MailWorkflow,
    PlanRevisionDependency,
)
from trainlab.orchestration.subprocess_runner import DownstreamResult


def result(receipt: dict, digest: str) -> DownstreamResult:
    return DownstreamResult("accepted", None, receipt, digest * 64, "b" * 64, 0)


def mail_receipt(
    *,
    status: str = "succeeded",
    action: str = "none",
    pending: list | None = None,
    next_retry_at_utc: str | None = None,
) -> dict:
    return {
        "status": status,
        "next_action": action,
        "pending_dependencies": pending or [],
        "next_retry_at_utc": next_retry_at_utc,
    }


@dataclass
class Runner:
    results: list[DownstreamResult]

    def __post_init__(self) -> None:
        self.calls = []

    def run(self, call):
        self.calls.append(call)
        return self.results.pop(0)


class Resolver:
    def resolve(self, **keys):
        assert keys == {"subject_id": 7, "reason_event_id": "91", "original_artifact_id": "51"}
        return PlanRevisionDependency(7, "subject-7", "41", "91", "31", "51", "2026-07-27")


def test_plain_mail_batch_never_invokes_analysis() -> None:
    runner = Runner([result(mail_receipt(), "1")])
    outcome = MailWorkflow(runner, Resolver()).execute(
        subject_id=7, invocation_id="mail-1", max_items=10, deadline_seconds=120
    )
    assert outcome.status == "succeeded"
    assert [call.mode for call in runner.calls] == ["run"]


def test_scheduler_fractional_second_invocation_is_preserved() -> None:
    runner = Runner([result(mail_receipt(), "1")])
    invocation = "20260727T155229.484382Z"
    outcome = MailWorkflow(runner, Resolver()).execute(
        subject_id=7,
        invocation_id=invocation,
        max_items=10,
        deadline_seconds=120,
    )
    assert outcome.status == "succeeded"
    assert runner.calls[0].invocation_id == invocation


def test_foundation_lock_busy_defers_mail_workflow_for_bounded_retry() -> None:
    retry_at = "2026-07-27T00:05:00Z"
    runner = Runner([
        result(mail_receipt(
            status="lock_busy",
            action="continue_poll",
            next_retry_at_utc=retry_at,
        ), "1"),
    ])
    outcome = MailWorkflow(runner, Resolver()).execute(
        subject_id=7,
        invocation_id="mail-lock-busy",
        max_items=10,
        deadline_seconds=120,
    )
    assert outcome.status == "deferred"
    assert outcome.next_action == "continue_poll"
    assert outcome.next_retry_at_utc == retry_at
    assert [call.mode for call in runner.calls] == ["run"]


def test_exact_dependency_revises_once_then_resumes_original_message() -> None:
    runner = Runner([
        result(mail_receipt(action="invoke_analysis", pending=[{
            "mode": "revise-plan", "reason_event_id": "91", "artifact_id": "51",
        }]), "1"),
        result({
            "status": "succeeded", "next_action": "none", "artifact_ids": ["61"],
            "delivery": {"delivery_id": "71"},
        }, "2"),
        result(mail_receipt(), "3"),
    ])
    outcome = MailWorkflow(runner, Resolver()).execute(
        subject_id=7, invocation_id="mail-2", max_items=4, deadline_seconds=60
    )
    assert outcome.status == "succeeded"
    assert outcome.revised_artifact_id == "61"
    assert [call.mode for call in runner.calls] == ["run", "revise_plan", "process"]
    assert runner.calls[1].plan_id == "31"
    assert runner.calls[1].reason_event_id == "91"
    assert runner.calls[2].mail_message_id == "41"
    assert runner.calls[2].dependency_analysis_artifact_ids == ("61",)


def test_partial_analysis_delivery_does_not_resume_mail_early() -> None:
    runner = Runner([
        result(mail_receipt(action="invoke_analysis", pending=[{
            "mode": "revise-plan", "reason_event_id": "91", "artifact_id": "51",
        }]), "1"),
        result({
            "status": "partial", "next_action": "retry_delivery", "artifact_ids": ["61"],
            "delivery": {"delivery_id": "71"},
        }, "2"),
    ])
    outcome = MailWorkflow(runner, Resolver()).execute(
        subject_id=7, invocation_id="mail-3", max_items=4, deadline_seconds=60
    )
    assert outcome.status == "partial"
    assert outcome.next_action == "retry_delivery"
    assert [call.mode for call in runner.calls] == ["run", "revise_plan"]


def test_untrusted_or_mismatched_dependency_fails_closed() -> None:
    class MismatchedResolver:
        def resolve(self, **keys):
            return PlanRevisionDependency(7, "subject-7", "41", "91", "31", "51", "2026-07-27")

    runner = Runner([
        result(mail_receipt(action="invoke_analysis", pending=[{
            "mode": "revise-plan", "reason_event_id": "91", "artifact_id": "52",
        }]), "1"),
    ])
    outcome = MailWorkflow(runner, MismatchedResolver()).execute(
        subject_id=7, invocation_id="mail-4", max_items=4, deadline_seconds=60
    )
    assert outcome.status == "attention_required"
    assert len(runner.calls) == 1
