from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from trainlab.orchestration.recovery_planner import RecoveryContext, plan_recovery
from trainlab.orchestration.repository import WorkflowRunRecord, WorkflowStepRecord
from trainlab.orchestration.state_projection import StepDefinition, WorkflowDefinition
from trainlab.orchestration.workflow_definition_store import WorkflowDefinitionAggregate


NOW = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)


def aggregate(
    *,
    workflow_state: str = "running",
    step_states: tuple[str, ...] = ("pending", "pending"),
    modes: tuple[str, ...] = ("incremental", "daily"),
    layers: tuple[int, ...] = (2, 3),
    parent: int | None = None,
    deadline: datetime | None = NOW + timedelta(hours=1),
    retry: datetime | None = None,
) -> WorkflowDefinitionAggregate:
    workflow = WorkflowDefinition(
        "morning:subject:2026-07-24", "morning", 1, "2026-07-24", "recovery",
        deadline, parent, NOW - timedelta(minutes=1), "a" * 64, "b" * 64,
        workflow_state,  # type: ignore[arg-type]
    )
    steps = tuple(
        StepDefinition(
            f"step-{index}", index, layers[index], modes[index], "c" * 64,
            f"persisted-{index}", None, state,  # type: ignore[arg-type]
        )
        for index, state in enumerate(step_states)
    )
    run = WorkflowRunRecord(1, workflow.workflow_key, "morning", 1, "2026-07-24", "recovery", "started", None, parent, "2026-07-24T02:59:00Z", None, "{}")
    records = tuple(
        WorkflowStepRecord(index + 1, 1, step.step_key, index, step.layer_no, step.tool_mode,
            step.request_sha256, step.invocation_id, None, None, "running", 1,
            None if state not in {"deferred", "lock_busy"} or retry is None else retry.isoformat().replace("+00:00", "Z"), None, None)
        for index, (step, state) in enumerate(zip(steps, step_states, strict=True))
    )
    return WorkflowDefinitionAggregate(run, records, workflow, steps, "d" * 64, "{}", "{}")


def decision(**kwargs: object):
    return plan_recovery(aggregate(**kwargs), RecoveryContext(NOW))


def test_unknown_running_never_fails_or_reinvokes_and_uses_persisted_identity() -> None:
    result = decision(step_states=("running", "pending"))
    assert (result.action, result.reason, result.invocation_id) == (
        "reconcile_status", "running_status_unknown", "persisted-0"
    )


@pytest.mark.parametrize(
    ("layer", "mode", "action", "reason"),
    [
        (3, "retry_delivery", "reconcile_analysis_delivery", "analysis_delivery_unknown"),
        (3, "reconcile_delivery", "reconcile_analysis_delivery", "analysis_delivery_unknown"),
        (4, "deliver_response", "reconcile_mail_delivery", "mail_delivery_unknown"),
        (4, "reconcile", "reconcile_mail_delivery", "mail_delivery_unknown"),
    ],
)
def test_delivery_timeout_is_exactly_reconciled(layer: int, mode: str, action: str, reason: str) -> None:
    result = decision(step_states=("running",), layers=(layer,), modes=(mode,))
    assert (result.action, result.reason) == (action, reason)


def test_terminal_and_verified_success_do_not_rerun() -> None:
    assert decision(workflow_state="succeeded").action == "no_action"
    assert decision(step_states=("succeeded", "pending")).step_key == "step-1"


def test_final_step_committed_before_workflow_terminal_is_deterministically_closed() -> None:
    result = decision(step_states=("succeeded", "unchanged"))
    assert (result.action, result.reason, result.step_key) == (
        "complete_workflow", "workflow_steps_complete", None
    )


def test_deferred_and_lock_busy_obey_persisted_retry_and_deadline() -> None:
    future = NOW + timedelta(minutes=2)
    waiting = decision(step_states=("deferred",), retry=future)
    assert (waiting.action, waiting.reason, waiting.next_retry_at_utc) == ("wait_retry", "retry_not_due", future)
    due = decision(workflow_state="deferred", step_states=("lock_busy",), retry=NOW - timedelta(seconds=1))
    assert (due.action, due.reason, due.invocation_id) == ("resume_workflow", "workflow_retry_due", "persisted-0")
    resumed = decision(step_states=("lock_busy",), retry=NOW - timedelta(seconds=1))
    assert (resumed.action, resumed.reason) == ("resume_step", "retry_due")
    expired = decision(step_states=("deferred",), retry=NOW - timedelta(seconds=1), deadline=NOW - timedelta(seconds=1))
    assert expired.reason == "deadline_expired"


def test_parent_deadline_and_dependency_are_conservative() -> None:
    child = aggregate(parent=9)
    assert plan_recovery(child, RecoveryContext(NOW, "running")).action == "wait_parent"
    assert plan_recovery(child, RecoveryContext(NOW, "unresolved")).reason == "parent_unresolved"
    expired = decision(deadline=NOW - timedelta(seconds=1))
    assert (expired.action, expired.reason) == ("attention_required", "deadline_expired")
    blocked = decision(step_states=("failed", "pending"))
    assert (blocked.action, blocked.reason) == ("attention_required", "dependency_unresolved")


def test_running_unknown_precedes_expired_deadline_and_unresolved_parent() -> None:
    value = aggregate(parent=9, deadline=NOW - timedelta(seconds=1), step_states=("running", "pending"))
    result = plan_recovery(value, RecoveryContext(NOW, "unresolved"))
    assert (result.action, result.reason) == ("reconcile_status", "running_status_unknown")


@pytest.mark.parametrize(
    ("workflow_state", "step_states", "expected"),
    [
        ("queued", ("pending", "pending"), "start_workflow"),
        ("running", ("pending", "pending"), "resume_step"),
        ("deferred", ("deferred", "pending"), "wait_retry"),
        ("deferred", ("pending", "pending"), "attention_required"),
        ("queued", ("succeeded", "pending"), "attention_required"),
    ],
)
def test_workflow_step_combinations_never_suggest_an_illegal_step_transition(
    workflow_state: str, step_states: tuple[str, ...], expected: str,
) -> None:
    retry = NOW + timedelta(minutes=1) if "deferred" in step_states else None
    assert decision(workflow_state=workflow_state, step_states=step_states, retry=retry).action == expected


@pytest.mark.parametrize(
    ("workflow_state", "step_states"),
    [
        ("queued", ("succeeded", "pending")),
        ("running", ("running", "running")),
        ("running", ("pending", "running")),
        ("deferred", ("pending", "pending")),
        ("deferred", ("deferred", "succeeded")),
    ],
)
def test_impossible_a2_state_combinations_fail_closed_without_external_action(
    workflow_state: str, step_states: tuple[str, ...],
) -> None:
    result = decision(
        workflow_state=workflow_state,
        step_states=step_states,
        retry=NOW - timedelta(seconds=1),
    )
    assert (result.action, result.reason) == ("attention_required", "malformed_state")


def test_exact_repeat_is_value_equal_and_planner_never_mutates_aggregate() -> None:
    value = aggregate(step_states=("running", "pending"))
    before = value
    first = plan_recovery(value, RecoveryContext(NOW))
    second = plan_recovery(value, RecoveryContext(NOW))
    assert first == second
    assert value == before


def test_malformed_context_and_missing_retry_fail_closed() -> None:
    with pytest.raises(Exception, match="recovery_planner_invalid"):
        plan_recovery(aggregate(), RecoveryContext(NOW, "oops"))  # type: ignore[arg-type]
    assert decision(step_states=("deferred",)).reason == "malformed_state"
