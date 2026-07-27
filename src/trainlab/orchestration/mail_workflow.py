"""Bounded orchestration for mail-triggered plan revisions.

Layer 5 consumes only validated receipts and trusted identity projections.  It
never reads Gmail, renders a reply, or writes a lower-layer business table.
"""

from __future__ import annotations

import re
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .subprocess_runner import DownstreamCall, DownstreamResult


class MailWorkflowError(ValueError):
    """A dependency or receipt cannot safely cross a layer boundary."""


_POSITIVE = re.compile(r"^[1-9][0-9]{0,18}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _positive(value: object, code: str) -> str:
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(text, str) or _POSITIVE.fullmatch(text) is None:
        raise MailWorkflowError(code)
    return text


def _identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise MailWorkflowError(code)
    return value


@dataclass(frozen=True, slots=True)
class PlanRevisionDependency:
    """Trusted projection resolving L4's minimal pending-dependency receipt."""

    subject_id: int
    analysis_subject_id: str
    mail_message_id: str
    reason_event_id: str
    original_plan_id: str
    original_artifact_id: str
    effective_local_date: str

    def __post_init__(self) -> None:
        _positive(self.subject_id, "mail_workflow_subject_invalid")
        _identifier(self.analysis_subject_id, "mail_workflow_analysis_subject_invalid")
        _identifier(self.mail_message_id, "mail_workflow_message_invalid")
        _positive(self.reason_event_id, "mail_workflow_reason_invalid")
        _positive(self.original_plan_id, "mail_workflow_plan_invalid")
        _positive(self.original_artifact_id, "mail_workflow_source_artifact_invalid")
        if not isinstance(self.effective_local_date, str) or _DATE.fullmatch(self.effective_local_date) is None:
            raise MailWorkflowError("mail_workflow_effective_date_invalid")


class DependencyResolver(Protocol):
    def resolve(
        self,
        *,
        subject_id: int,
        reason_event_id: str,
        original_artifact_id: str,
    ) -> PlanRevisionDependency: ...


class SqlitePlanRevisionResolver:
    """Resolve only stable L1 views/relations through a read-only connection."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)

    def resolve(
        self,
        *,
        subject_id: int,
        reason_event_id: str,
        original_artifact_id: str,
    ) -> PlanRevisionDependency:
        reason = int(_positive(reason_event_id, "mail_workflow_reason_invalid"))
        artifact = int(_positive(
            original_artifact_id, "mail_workflow_source_artifact_invalid"
        ))
        connection = sqlite3.connect(
            f"file:{self._database_path}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT e.id AS reason_event_id,e.mail_message_id,
                       e.structured_payload_json,s.subject_key,
                       a.id AS artifact_id,a.artifact_kind,a.is_current,
                       a.period_start_local_date,a.period_end_local_date,
                       p.id AS plan_id,p.status AS plan_status
                  FROM conversation_events e
                  JOIN data_subjects s ON s.id=e.subject_id AND s.is_active=1
                  JOIN analysis_artifacts a ON a.id=? AND a.subject_id=e.subject_id
                  JOIN training_plans p ON p.analysis_artifact_id=a.id
                 WHERE e.id=? AND e.subject_id=?
                   AND e.event_type='plan_revision_reason_recorded'
                   AND e.mail_message_id IS NOT NULL
                """,
                (artifact, reason, subject_id),
            ).fetchall()
            if len(rows) != 1:
                raise MailWorkflowError("mail_workflow_dependency_not_found")
            row = rows[0]
            try:
                payload = json.loads(row["structured_payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise MailWorkflowError("mail_workflow_dependency_invalid") from exc
            if (
                not isinstance(payload, dict)
                or payload.get("current_plan_id") != row["plan_id"]
                or not isinstance(payload.get("effective_local_date"), str)
                or row["artifact_kind"] != "weekly_training_plan"
                or row["plan_status"] not in {"active", "superseded"}
            ):
                raise MailWorkflowError("mail_workflow_dependency_mismatch")
            return PlanRevisionDependency(
                subject_id,
                str(row["subject_key"]),
                str(row["mail_message_id"]),
                str(row["reason_event_id"]),
                str(row["plan_id"]),
                str(row["artifact_id"]),
                payload["effective_local_date"],
            )
        finally:
            connection.close()


class Runner(Protocol):
    def run(self, call: DownstreamCall) -> DownstreamResult: ...


@dataclass(frozen=True, slots=True)
class MailWorkflowOutcome:
    status: str
    next_action: str
    calls: tuple[DownstreamCall, ...]
    receipt_sha256s: tuple[str, ...]
    revised_artifact_id: str | None = None
    analysis_delivery_id: str | None = None
    error_code: str | None = None


def _accepted(result: DownstreamResult) -> Mapping[str, Any]:
    if result.kind != "accepted" or result.receipt is None:
        raise MailWorkflowError(result.error_code or "mail_workflow_untrusted_receipt")
    return result.receipt


def _pending_dependency(receipt: Mapping[str, Any]) -> tuple[str, str]:
    pending = receipt.get("pending_dependencies")
    if (
        not isinstance(pending, list)
        or len(pending) != 1
        or not isinstance(pending[0], dict)
        or set(pending[0]) != {"mode", "reason_event_id", "artifact_id"}
        or pending[0].get("mode") != "revise-plan"
    ):
        raise MailWorkflowError("mail_workflow_dependency_invalid")
    return (
        _positive(pending[0].get("reason_event_id"), "mail_workflow_reason_invalid"),
        _positive(pending[0].get("artifact_id"), "mail_workflow_source_artifact_invalid"),
    )


class MailWorkflow:
    """Execute one bounded mail batch and at most one plan-revision dependency."""

    def __init__(self, runner: Runner, resolver: DependencyResolver) -> None:
        self._runner = runner
        self._resolver = resolver

    def execute(
        self,
        *,
        subject_id: int,
        invocation_id: str,
        max_items: int,
        deadline_seconds: int,
    ) -> MailWorkflowOutcome:
        _positive(subject_id, "mail_workflow_subject_invalid")
        _identifier(invocation_id, "mail_workflow_invocation_invalid")
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= 10_000
            or not isinstance(deadline_seconds, int)
            or isinstance(deadline_seconds, bool)
            or not 1 <= deadline_seconds <= 10_000
        ):
            raise MailWorkflowError("mail_workflow_limit_invalid")

        calls: list[DownstreamCall] = []
        hashes: list[str] = []
        initial = DownstreamCall(
            "mail", "run", invocation_id, None,
            subject_id=subject_id,
            max_items=max_items,
            deadline_seconds=deadline_seconds,
        )
        calls.append(initial)
        initial_result = self._runner.run(initial)
        try:
            mail_receipt = _accepted(initial_result)
        except MailWorkflowError as error:
            return MailWorkflowOutcome("attention_required", "operator_review", tuple(calls), (), error_code=str(error))
        if initial_result.receipt_sha256 is not None:
            hashes.append(initial_result.receipt_sha256)

        next_action = mail_receipt.get("next_action")
        status = mail_receipt.get("status")
        if next_action != "invoke_analysis":
            return MailWorkflowOutcome(
                "succeeded" if status in {"succeeded", "unchanged"} else str(status),
                str(next_action),
                tuple(calls),
                tuple(hashes),
            )

        try:
            reason_id, source_artifact_id = _pending_dependency(mail_receipt)
            dependency = self._resolver.resolve(
                subject_id=subject_id,
                reason_event_id=reason_id,
                original_artifact_id=source_artifact_id,
            )
            if (
                dependency.subject_id != subject_id
                or dependency.reason_event_id != reason_id
                or dependency.original_artifact_id != source_artifact_id
            ):
                raise MailWorkflowError("mail_workflow_dependency_mismatch")
        except (MailWorkflowError, LookupError, ValueError) as error:
            return MailWorkflowOutcome(
                "attention_required", "operator_review", tuple(calls), tuple(hashes),
                error_code=str(error) or "mail_workflow_dependency_invalid",
            )

        revise = DownstreamCall(
            "analysis", "revise_plan", f"{invocation_id}:revise", None,
            subject_id=dependency.analysis_subject_id,
            plan_id=dependency.original_plan_id,
            reason_event_id=dependency.reason_event_id,
            effective_local_date=dependency.effective_local_date,
        )
        calls.append(revise)
        revision_result = self._runner.run(revise)
        try:
            revision = _accepted(revision_result)
        except MailWorkflowError as error:
            return MailWorkflowOutcome("attention_required", "operator_review", tuple(calls), tuple(hashes), error_code=str(error))
        if revision_result.receipt_sha256 is not None:
            hashes.append(revision_result.receipt_sha256)
        revision_status = revision.get("status")
        if revision_status not in {"succeeded", "unchanged", "partial"}:
            return MailWorkflowOutcome(
                "attention_required" if revision_status in {"rejected", "failed"} else "deferred",
                str(revision.get("next_action") or "operator_review"),
                tuple(calls),
                tuple(hashes),
                error_code=f"analysis_revision_{revision_status}",
            )
        artifact_ids = revision.get("artifact_ids")
        if not isinstance(artifact_ids, list) or len(artifact_ids) != 1:
            return MailWorkflowOutcome("attention_required", "operator_review", tuple(calls), tuple(hashes), error_code="mail_workflow_revision_artifact_invalid")
        revised_artifact_id = _positive(artifact_ids[0], "mail_workflow_revision_artifact_invalid")
        delivery = revision.get("delivery")
        delivery_id = None
        if isinstance(delivery, dict) and delivery.get("delivery_id") is not None:
            delivery_id = _positive(delivery["delivery_id"], "mail_workflow_revision_delivery_invalid")

        # A partial revision with an outstanding L3 delivery is recovered by
        # S5-12 before L4 resumes; L4 must not imply that the plan was delivered.
        if revision_status == "partial":
            return MailWorkflowOutcome(
                "partial", str(revision.get("next_action") or "retry_delivery"),
                tuple(calls), tuple(hashes), revised_artifact_id, delivery_id,
            )

        resume = DownstreamCall(
            "mail", "process", f"{invocation_id}:resume", None,
            subject_id=subject_id,
            mail_message_id=dependency.mail_message_id,
            dependency_analysis_artifact_ids=(revised_artifact_id,),
        )
        calls.append(resume)
        resume_result = self._runner.run(resume)
        try:
            resumed = _accepted(resume_result)
        except MailWorkflowError as error:
            return MailWorkflowOutcome(
                "attention_required", "operator_review", tuple(calls), tuple(hashes),
                revised_artifact_id, delivery_id, str(error),
            )
        if resume_result.receipt_sha256 is not None:
            hashes.append(resume_result.receipt_sha256)
        resumed_status = str(resumed.get("status"))
        return MailWorkflowOutcome(
            "succeeded" if resumed_status in {"succeeded", "unchanged"} else resumed_status,
            str(resumed.get("next_action") or "none"),
            tuple(calls),
            tuple(hashes),
            revised_artifact_id,
            delivery_id,
        )
