"""Pure, deterministic S5-05B recovery and reconciliation planning.

This is deliberately an *advice* boundary.  It neither opens the repository nor
starts a process: the executor must persist any resulting transition and perform
the selected status/reconcile call using the immutable invocation already stored
on the step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .state_projection import StepDefinition, StateProjectionError
from .workflow_definition_store import WorkflowDefinitionAggregate


RecoveryAction = Literal[
    "no_action",
    "complete_workflow",
    "start_workflow",
    "resume_workflow",
    "resume_step",
    "wait_retry",
    "wait_parent",
    "reconcile_status",
    "reconcile_analysis_delivery",
    "reconcile_mail_delivery",
    "attention_required",
]
RecoveryReason = Literal[
    "workflow_terminal",
    "workflow_steps_complete",
    "workflow_not_started",
    "workflow_retry_due",
    "step_ready",
    "retry_not_due",
    "retry_due",
    "parent_pending",
    "parent_unresolved",
    "parent_not_successful",
    "dependency_unresolved",
    "deadline_expired",
    "running_status_unknown",
    "analysis_delivery_unknown",
    "mail_delivery_unknown",
    "malformed_state",
]
ParentState = Literal["not_applicable", "pending", "running", "succeeded", "unresolved", "failed"]

_SUCCESSFUL_STEPS = frozenset({"succeeded", "unchanged", "skipped"})
_TERMINAL_WORKFLOWS = frozenset(
    {"succeeded", "partial", "attention_required", "failed", "cancelled"}
)
_DELIVERY_ANALYSIS_MODES = frozenset({"retry_delivery", "reconcile_delivery"})
_DELIVERY_MAIL_MODES = frozenset({"deliver_response", "reconcile"})
_PARENT_STATES = frozenset(
    {"not_applicable", "pending", "running", "succeeded", "unresolved", "failed"}
)


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """All non-persisted recovery observations, supplied explicitly by caller."""

    now_utc: datetime
    parent_state: ParentState = "not_applicable"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """A serializable, side-effect-free next action for one workflow aggregate."""

    workflow_key: str
    action: RecoveryAction
    reason: RecoveryReason
    step_key: str | None
    invocation_id: str | None
    next_retry_at_utc: datetime | None


def _invalid() -> None:
    raise StateProjectionError("recovery_planner_invalid")


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        _invalid()
    if value.utcoffset() != UTC.utcoffset(None):
        _invalid()
    return value


def _decision(
    aggregate: WorkflowDefinitionAggregate,
    action: RecoveryAction,
    reason: RecoveryReason,
    step: StepDefinition | None = None,
    retry: datetime | None = None,
) -> RecoveryDecision:
    return RecoveryDecision(
        workflow_key=aggregate.workflow.workflow_key,
        action=action,
        reason=reason,
        step_key=None if step is None else step.step_key,
        invocation_id=None if step is None else step.invocation_id,
        next_retry_at_utc=retry,
    )


def _parent_gate(
    aggregate: WorkflowDefinitionAggregate,
    context: RecoveryContext,
) -> RecoveryDecision | None:
    has_parent = aggregate.workflow.parent_workflow_run_id is not None
    if not has_parent:
        if context.parent_state != "not_applicable":
            _invalid()
        return None
    if context.parent_state in {"pending", "running"}:
        return _decision(aggregate, "wait_parent", "parent_pending")
    if context.parent_state == "unresolved":
        return _decision(aggregate, "attention_required", "parent_unresolved")
    if context.parent_state != "succeeded":
        return _decision(aggregate, "attention_required", "parent_not_successful")
    return None


def _running_action(step: StepDefinition) -> tuple[RecoveryAction, RecoveryReason]:
    # A send/delivery timeout is never retried from the planner.  It has an
    # exact delivery identity and must use its owner layer's reconcile mode.
    if step.layer_no == 3 and step.tool_mode in _DELIVERY_ANALYSIS_MODES:
        return "reconcile_analysis_delivery", "analysis_delivery_unknown"
    if step.layer_no == 4 and step.tool_mode in _DELIVERY_MAIL_MODES:
        return "reconcile_mail_delivery", "mail_delivery_unknown"
    return "reconcile_status", "running_status_unknown"


def _valid_frontier(steps: tuple[StepDefinition, ...], index: int) -> bool:
    """A resumable frontier has a successful prefix and an untouched suffix."""

    return (
        all(item.domain_state in _SUCCESSFUL_STEPS for item in steps[:index])
        and all(item.domain_state == "pending" for item in steps[index + 1 :])
    )


def _valid_combination(aggregate: WorkflowDefinitionAggregate) -> bool:
    """Reject state combinations that A2's transition ordering cannot create."""

    workflow_state = aggregate.workflow.domain_state
    steps = aggregate.steps
    if workflow_state == "queued":
        return all(step.domain_state == "pending" for step in steps)
    if workflow_state == "deferred":
        frontiers = [
            index
            for index, step in enumerate(steps)
            if step.domain_state in {"deferred", "lock_busy"}
            and _valid_frontier(steps, index)
        ]
        return len(frontiers) == 1
    if workflow_state != "running":
        return True
    running = [
        index for index, step in enumerate(steps) if step.domain_state == "running"
    ]
    if running:
        return len(running) == 1 and _valid_frontier(steps, running[0])
    # A running workflow can crash between its final step transition and its own
    # terminal transition, or while a deferred frontier has not yet changed it.
    frontier = next(
        (index for index, step in enumerate(steps)
         if step.domain_state not in _SUCCESSFUL_STEPS),
        None,
    )
    if frontier is None:
        return True
    return _valid_frontier(steps, frontier)


def plan_recovery(
    aggregate: WorkflowDefinitionAggregate,
    context: RecoveryContext,
) -> RecoveryDecision:
    """Return the one conservative next action for a validated aggregate.

    Running work always wins over deadline handling because expiry cannot prove
    that an external side effect did not occur.  No decision creates an
    invocation: ``resume_step`` always carries the persisted invocation ID.
    """

    if type(aggregate) is not WorkflowDefinitionAggregate or type(context) is not RecoveryContext:
        _invalid()
    if context.parent_state not in _PARENT_STATES:
        _invalid()
    now = _utc(context.now_utc)
    steps = aggregate.steps
    if not steps or tuple(sorted(steps, key=lambda item: item.ordinal)) != steps:
        _invalid()
    if not _valid_combination(aggregate):
        return _decision(aggregate, "attention_required", "malformed_state")
    # An interrupted external call is more important than every scheduling gate:
    # neither a deadline nor a missing parent observation disproves its effect.
    running = next((step for step in steps if step.domain_state == "running"), None)
    if running is not None:
        action, reason = _running_action(running)
        return _decision(aggregate, action, reason, running)
    if aggregate.workflow.domain_state in _TERMINAL_WORKFLOWS:
        return _decision(aggregate, "no_action", "workflow_terminal")
    parent = _parent_gate(aggregate, context)
    if parent is not None:
        return parent

    if all(step.domain_state in _SUCCESSFUL_STEPS for step in steps):
        if aggregate.workflow.domain_state == "running":
            return _decision(aggregate, "complete_workflow", "workflow_steps_complete")
        return _decision(aggregate, "attention_required", "malformed_state")

    for index, step in enumerate(steps):
        if step.domain_state in _SUCCESSFUL_STEPS:
            continue
        if any(previous.domain_state not in _SUCCESSFUL_STEPS for previous in steps[:index]):
            return _decision(aggregate, "attention_required", "dependency_unresolved", step)
        if step.domain_state in {"deferred", "lock_busy"}:
            row = aggregate.step_records[index]
            retry = row.next_retry_at_utc
            if retry is None:
                return _decision(aggregate, "attention_required", "malformed_state", step)
            retry_at = _utc(datetime.fromisoformat(retry.replace("Z", "+00:00")))
            if now < retry_at:
                return _decision(aggregate, "wait_retry", "retry_not_due", step, retry_at)
            if aggregate.workflow.deadline_at_utc is not None and now > aggregate.workflow.deadline_at_utc:
                return _decision(aggregate, "attention_required", "deadline_expired", step)
            if aggregate.workflow.domain_state == "deferred":
                # A2 permits a deferred step to resume only after the enclosing
                # workflow has made its own deferred -> running transition.
                return _decision(aggregate, "resume_workflow", "workflow_retry_due", step, retry_at)
            if aggregate.workflow.domain_state != "running":
                return _decision(aggregate, "attention_required", "malformed_state", step)
            return _decision(aggregate, "resume_step", "retry_due", step, retry_at)
        if step.domain_state == "pending":
            if aggregate.workflow.deadline_at_utc is not None and now > aggregate.workflow.deadline_at_utc:
                return _decision(aggregate, "attention_required", "deadline_expired", step)
            if aggregate.workflow.domain_state == "queued":
                return _decision(aggregate, "start_workflow", "workflow_not_started", step)
            if aggregate.workflow.domain_state == "running":
                return _decision(aggregate, "resume_step", "step_ready", step)
            return _decision(aggregate, "attention_required", "malformed_state", step)
        # terminal-but-unsuccessful steps are not safe prerequisites for a new
        # invocation and must be escalated to an explicit operator decision.
        return _decision(aggregate, "attention_required", "dependency_unresolved", step)
    return _decision(aggregate, "no_action", "workflow_terminal")
