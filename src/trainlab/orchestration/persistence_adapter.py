"""Persist public orchestration receipts through the Layer-5 domain model."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .contracts import WorkflowReceipt, WorkflowRequest, WorkflowStepReceipt
from .domain_state_machine import StepTransitionEvent, WorkflowTransitionEvent
from .evidence_codes import (
    DOWNSTREAM_FAILURE_EVIDENCE_CODES,
    downstream_failure_evidence,
)
from .repository import OrchestrationRepository
from .state_projection import StepDefinition, WorkflowDefinition


class OrchestrationPersistenceError(RuntimeError):
    pass


def _parse_utc(value: str | None) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OrchestrationPersistenceError("orchestration_persistence_time_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise OrchestrationPersistenceError(
            "orchestration_persistence_time_invalid"
        ) from exc
    if parsed.utcoffset() != UTC.utcoffset(None):
        raise OrchestrationPersistenceError("orchestration_persistence_time_invalid")
    return parsed.astimezone(UTC)


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class SqliteSubjectProjection:
    """Read-only subject lookup used by the composition root and receipt store."""

    def __init__(self, database_path: Path) -> None:
        self._path = Path(database_path)

    def is_active(self, subject_id: str) -> bool:
        return self.resolve(subject_id) is not None

    def workflow_identity(self, subject_id: str) -> str:
        value = self.resolve(subject_id)
        if value is None:
            raise OrchestrationPersistenceError(
                "orchestration_persistence_subject_invalid"
            )
        return str(value)

    def resolve(self, subject_id: str | None) -> int | None:
        if subject_id is None:
            return None
        connection = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        try:
            if subject_id.isdecimal() and int(subject_id) > 0:
                row = connection.execute(
                    "SELECT id FROM data_subjects WHERE id=? AND is_active=1",
                    (int(subject_id),),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id FROM data_subjects WHERE subject_key=? AND is_active=1",
                    (subject_id,),
                ).fetchone()
            return None if row is None else int(row[0])
        finally:
            connection.close()


class RepositoryReceiptStore:
    """Materialize immutable definitions then append exact domain events."""

    def __init__(
        self,
        repository: OrchestrationRepository,
        subjects: SqliteSubjectProjection,
        *,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._subjects = subjects
        self._clock = clock

    def permits_operator_retry(self, request: WorkflowRequest) -> bool:
        """Validate a manual retry parent before any lower-layer execution."""
        if (
            request.trigger_kind != "manual"
            or request.workflow_kind not in {"morning", "weekly"}
            or request.parent_workflow_run_id is None
            or not request.parent_workflow_run_id.isdecimal()
            or int(request.parent_workflow_run_id) <= 0
            or request.subject_id is None
            or request.logical_local_date is None
        ):
            return False
        subject = self._subjects.resolve(request.subject_id)
        if subject is None:
            return False
        try:
            parent = self._repository.get_workflow_by_id(
                int(request.parent_workflow_run_id)
            )
        except Exception:
            return False
        return bool(
            parent is not None
            and parent.status == "failed"
            and parent.workflow_kind == request.workflow_kind
            and parent.subject_id == subject
            and parent.logical_local_date == request.logical_local_date
        )

    def record_orchestration_receipt(
        self, request: WorkflowRequest, receipt: WorkflowReceipt
    ) -> None:
        if receipt.workflow_key != receipt.workflow_run_id.removeprefix("run:"):
            raise OrchestrationPersistenceError(
                "orchestration_persistence_identity_invalid"
            )
        handoff = self._repository.get_scheduler_handoff(receipt.workflow_key)
        # A scheduler claim first creates a handoff-only run row.  It is not a
        # malformed workflow definition; the exact receipt below materializes
        # that row atomically while preserving its scheduler lineage.
        existing = (
            None
            if handoff is not None
            else self._repository.load_workflow_definition(receipt.workflow_key)
        )
        started = (
            _parse_utc(handoff.workflow.started_at_utc)
            if handoff is not None
            else _parse_utc(receipt.started_at_utc)
        )
        subject = self._subjects.resolve(request.subject_id)
        if request.subject_id is not None and subject is None:
            raise OrchestrationPersistenceError(
                "orchestration_persistence_subject_invalid"
            )
        parent = None
        if request.parent_workflow_run_id is not None:
            if (
                not request.parent_workflow_run_id.isdecimal()
                or int(request.parent_workflow_run_id) <= 0
            ):
                raise OrchestrationPersistenceError(
                    "orchestration_persistence_parent_invalid"
                )
            if request.trigger_kind == "manual" and not self.permits_operator_retry(
                request
            ):
                raise OrchestrationPersistenceError(
                    "orchestration_persistence_parent_invalid"
                )
            parent = int(request.parent_workflow_run_id)
        command_hash = (
            handoff.materialization_command_sha256
            if handoff
            else _digest(request.as_json_dict())
        )
        evidence_hash = (
            handoff.materialization_evidence_sha256
            if handoff
            else _digest(
                {
                    "workflow_key": receipt.workflow_key,
                    "invocation_id": request.invocation_id,
                }
            )
        )
        workflow = WorkflowDefinition(
            receipt.workflow_key,
            receipt.workflow_kind,
            subject,
            receipt.logical_local_date,
            request.trigger_kind,
            _parse_utc(request.deadline_at_utc),
            parent,
            started,
            command_hash,
            evidence_hash,
            "queued",
        )
        steps = tuple(
            self._definition(item, index) for index, item in enumerate(receipt.steps)
        )
        if existing is None:
            aggregate = self._repository.create_workflow_definition(workflow, steps)
        else:
            self._validate_replay_identity(existing, workflow, steps)
            aggregate = existing
            if aggregate.workflow.domain_state in {
                "succeeded",
                "partial",
                "attention_required",
                "failed",
                "cancelled",
            }:
                return
            if self._matches_receipt(aggregate, receipt):
                return
        completed_attempts = sum(
            event.to_state == "running" for event in aggregate.workflow_events
        )
        attempt = (
            max(1, completed_attempts)
            if aggregate.workflow.domain_state == "running"
            else completed_attempts + 1
        )
        event_prefix = f"{request.invocation_id}:attempt:{attempt}"
        prior_times = [
            aggregate.workflow.started_at_utc,
            *(_parse_utc(item.at_utc) for item in aggregate.workflow_events),
            *(_parse_utc(item.at_utc) for item in aggregate.step_events),
        ]
        cursor = max(_parse_utc(receipt.completed_at_utc), *prior_times)
        if aggregate.workflow_events or aggregate.step_events:
            cursor += timedelta(microseconds=1)
        if aggregate.workflow.domain_state in {"queued", "deferred"}:
            aggregate = self._repository.transition_workflow_domain(
                receipt.workflow_key,
                WorkflowTransitionEvent(
                    f"{event_prefix}:workflow:running",
                    "running",
                    cursor,
                    "executor_started",
                ),
            )
        for item in receipt.steps:
            current = next(
                step for step in aggregate.steps if step.step_key == item.step_id
            )
            if current.domain_state in {
                "succeeded",
                "unchanged",
                "partial",
                "auth_required",
                "rejected",
                "failed",
                "skipped",
            }:
                continue
            if item.status == "pending":
                continue
            cursor += timedelta(microseconds=1)
            if item.status == "skipped":
                aggregate = self._repository.transition_step_domain(
                    receipt.workflow_key,
                    StepTransitionEvent(
                        f"{event_prefix}:{item.step_id}:skipped",
                        item.step_id,
                        "skipped",
                        cursor,
                        evidence_code="deterministic_check",
                    ),
                )
                continue
            if current.domain_state != "running":
                aggregate = self._repository.transition_step_domain(
                    receipt.workflow_key,
                    StepTransitionEvent(
                        f"{event_prefix}:{item.step_id}:running",
                        item.step_id,
                        "running",
                        cursor,
                    ),
                )
                cursor += timedelta(microseconds=1)
            evidence = None if item.receipt_sha256 else self._failure_evidence(receipt)
            retry = (
                _parse_utc(receipt.next_retry_at_utc)
                if (
                    item.status in {"deferred", "lock_busy"}
                    and receipt.next_retry_at_utc
                )
                else None
            )
            aggregate = self._repository.transition_step_domain(
                receipt.workflow_key,
                StepTransitionEvent(
                    f"{event_prefix}:{item.step_id}:{item.status}",
                    item.step_id,
                    item.status,
                    cursor,
                    receipt_sha256=item.receipt_sha256,
                    evidence_code=evidence,
                    next_retry_at_utc=retry,
                    controlled_counts=item.counts,
                ),
            )
        if aggregate.workflow.domain_state == "running":
            cursor += timedelta(microseconds=1)
            self._repository.transition_workflow_domain(
                receipt.workflow_key,
                WorkflowTransitionEvent(
                    f"{event_prefix}:workflow:{receipt.status}",
                    receipt.status,
                    cursor,
                    "workflow_receipt",
                ),
            )

    @staticmethod
    def _failure_evidence(receipt: WorkflowReceipt) -> str:
        """Select the receipt's fixed safe code for a no-receipt transition."""
        for error in receipt.errors:
            if (
                isinstance(error, dict)
                and error.get("code") in DOWNSTREAM_FAILURE_EVIDENCE_CODES
            ):
                return str(error["code"])
        return downstream_failure_evidence(None)

    @classmethod
    def _matches_receipt(cls, existing, receipt: WorkflowReceipt) -> bool:
        if (
            existing.workflow.domain_state != receipt.status
            or not receipt.steps
            or len(existing.steps) != len(receipt.steps)
        ):
            return False
        histories = {
            step.step_key: tuple(
                event
                for event in existing.step_events
                if event.step_key == step.step_key
            )
            for step in existing.steps
        }
        for current, requested in zip(existing.steps, receipt.steps, strict=True):
            if (
                current.step_key != requested.step_id
                or current.domain_state != requested.status
            ):
                return False
            history = histories[current.step_key]
            last = history[-1] if history else None
            if requested.status == "pending":
                if last is not None:
                    return False
                continue
            if last is None:
                return False
            expected_retry = (
                receipt.next_retry_at_utc
                if requested.status in {"deferred", "lock_busy"}
                else None
            )
            if (
                last.receipt_sha256 != requested.receipt_sha256
                or last.evidence_code
                != (
                    "receipt_received"
                    if requested.receipt_sha256 is not None
                    else cls._failure_evidence(receipt)
                )
                or last.next_retry_at_utc != expected_retry
                or last.controlled_counts != tuple(sorted(requested.counts.items()))
            ):
                return False
        return True

    @staticmethod
    def _validate_replay_identity(existing, workflow, steps) -> None:
        actual_workflow = existing.workflow
        if (
            actual_workflow.workflow_key != workflow.workflow_key
            or actual_workflow.workflow_kind != workflow.workflow_kind
            or actual_workflow.subject_id != workflow.subject_id
            or actual_workflow.logical_local_date != workflow.logical_local_date
            or len(existing.steps) != len(steps)
        ):
            raise OrchestrationPersistenceError(
                "orchestration_persistence_replay_conflict"
            )
        actual_steps = tuple(
            (
                item.step_key,
                item.ordinal,
                item.layer_no,
                item.tool_mode,
                item.request_sha256,
                item.invocation_id,
                item.downstream_run_id,
            )
            for item in existing.steps
        )
        requested_steps = tuple(
            (
                item.step_key,
                item.ordinal,
                item.layer_no,
                item.tool_mode,
                item.request_sha256,
                item.invocation_id,
                item.downstream_run_id,
            )
            for item in steps
        )
        if actual_steps != requested_steps:
            raise OrchestrationPersistenceError(
                "orchestration_persistence_replay_conflict"
            )

    @staticmethod
    def _definition(item: WorkflowStepReceipt, ordinal: int) -> StepDefinition:
        layer_no = {
            "foundation": 1,
            "garmin": 2,
            "analysis": 3,
            "mail": 4,
            "orchestration": 5,
        }[item.layer]
        return StepDefinition(
            item.step_id,
            ordinal,
            layer_no,
            item.mode,
            _digest(
                {
                    "step_id": item.step_id,
                    "layer": item.layer,
                    "mode": item.mode,
                    "downstream_invocation_id": item.downstream_invocation_id,
                    "downstream_run_id": item.downstream_run_id,
                }
            ),
            item.downstream_invocation_id,
            item.downstream_run_id,
            "pending",
        )
