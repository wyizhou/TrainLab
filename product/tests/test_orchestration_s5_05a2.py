from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration import (
    OrchestrationRepository,
    OrchestrationRepositoryError,
)
from trainlab.orchestration.domain_state_machine import (
    STEP_TERMINAL_STATES,
    STEP_TRANSITIONS,
    WORKFLOW_TERMINAL_STATES,
    WORKFLOW_TRANSITIONS,
    StepTransitionEvent,
    WorkflowTransitionEvent,
    normalize_step_event,
    normalize_workflow_event,
)
from trainlab.orchestration.state_projection import (
    StateProjectionError,
    StepDefinition,
    WorkflowDefinition,
    definition_sha256,
)
from trainlab.orchestration.workflow_definition_store import (
    DOMAIN_EVENTS_VERSION,
    WORKFLOW_STATE_ENVELOPE_VERSION,
)
import trainlab.orchestration.repository as repository_module


STARTED = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
RECEIPT = "f" * 64


def repository(tmp_path: Path) -> tuple[OrchestrationRepository, Path]:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/foundation-ready.json",
        root / "state/locks/foundation.lock",
    )
    receipt = FoundationTool(config).execute(
        FoundationRequest("init", "s5-05a2", "2026-07-24T02:00:00Z")
    )
    assert receipt.status == "initialized"
    return OrchestrationRepository(root / "data.db"), root / "data.db"


def workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        "morning:2026-07-24",
        "morning",
        None,
        "2026-07-24",
        "scheduled",
        STARTED + timedelta(hours=1),
        None,
        STARTED,
        "a" * 64,
        "b" * 64,
        "queued",
    )


def steps() -> tuple[StepDefinition, ...]:
    return (
        StepDefinition(
            "collection",
            0,
            2,
            "incremental",
            "c" * 64,
            "invocation",
            "downstream",
            "pending",
        ),
        StepDefinition(
            "analysis",
            1,
            3,
            "daily",
            "d" * 64,
            None,
            None,
            "pending",
        ),
    )


def start_workflow(
    repo: OrchestrationRepository,
    *,
    seconds: int = 0,
) -> None:
    repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-start",
            "running",
            STARTED + timedelta(seconds=seconds),
            "dispatch_started",
        ),
    )


def step_event(
    event_id: str,
    to_state: str,
    seconds: int,
    *,
    step_key: str = "collection",
) -> StepTransitionEvent:
    values: dict[str, object] = {}
    if to_state in {
        "succeeded",
        "unchanged",
        "partial",
        "auth_required",
        "rejected",
        "failed",
    }:
        values["receipt_sha256"] = RECEIPT
        values["controlled_counts"] = {"fetched": seconds}
    elif to_state == "lock_busy":
        values["receipt_sha256"] = RECEIPT
        values["next_retry_at_utc"] = STARTED + timedelta(seconds=seconds + 30)
    elif to_state == "deferred":
        values["evidence_code"] = "provider_unavailable"
        values["next_retry_at_utc"] = STARTED + timedelta(seconds=seconds + 30)
    elif to_state == "skipped":
        values["evidence_code"] = "deterministic_check"
    return StepTransitionEvent(
        event_id,
        step_key,
        to_state,  # type: ignore[arg-type]
        STARTED + timedelta(seconds=seconds),
        **values,  # type: ignore[arg-type]
    )


def snapshot(connection: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    return (
        connection.execute("SELECT * FROM orchestrator_runs ORDER BY id").fetchall(),
        connection.execute("SELECT * FROM orchestrator_steps ORDER BY id").fetchall(),
    )


def test_exact_transition_tables_cover_all_states_and_forbid_terminal_revive() -> None:
    assert WORKFLOW_TRANSITIONS == {
        "queued": frozenset({"running", "cancelled"}),
        "running": frozenset(
            {
                "succeeded",
                "partial",
                "deferred",
                "attention_required",
                "failed",
                "cancelled",
            }
        ),
        "deferred": frozenset(
            {"running", "attention_required", "failed", "cancelled"}
        ),
        "succeeded": frozenset(),
        "partial": frozenset(),
        "attention_required": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    }
    assert STEP_TRANSITIONS == {
        "pending": frozenset({"running", "skipped"}),
        "running": frozenset(
            {
                "succeeded",
                "unchanged",
                "partial",
                "deferred",
                "lock_busy",
                "auth_required",
                "rejected",
                "failed",
            }
        ),
        "deferred": frozenset({"running", "failed", "skipped"}),
        "lock_busy": frozenset({"running", "failed", "skipped"}),
        "succeeded": frozenset(),
        "unchanged": frozenset(),
        "partial": frozenset(),
        "auth_required": frozenset(),
        "rejected": frozenset(),
        "failed": frozenset(),
        "skipped": frozenset(),
    }
    assert WORKFLOW_TERMINAL_STATES == {
        "succeeded",
        "partial",
        "attention_required",
        "failed",
        "cancelled",
    }
    assert STEP_TERMINAL_STATES == {
        "succeeded",
        "unchanged",
        "partial",
        "auth_required",
        "rejected",
        "failed",
        "skipped",
    }


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in WORKFLOW_TRANSITIONS.items()
        for target in targets
    ],
)
def test_every_allowed_workflow_transition_normalizes(
    source: str,
    target: str,
) -> None:
    record = normalize_workflow_event(
        WorkflowTransitionEvent(
            "event",
            target,  # type: ignore[arg-type]
            STARTED,
            "receipt_validated",
        ),
        from_state=source,  # type: ignore[arg-type]
    )
    assert (record.from_state, record.to_state) == (source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in WORKFLOW_TRANSITIONS
        for target in WORKFLOW_TRANSITIONS
        if target not in WORKFLOW_TRANSITIONS[source]
    ],
)
def test_every_forbidden_workflow_transition_is_rejected(
    source: str,
    target: str,
) -> None:
    with pytest.raises(
        StateProjectionError,
        match="workflow_domain_transition_invalid",
    ):
        normalize_workflow_event(
            WorkflowTransitionEvent(
                "event",
                target,  # type: ignore[arg-type]
                STARTED,
                "receipt_validated",
            ),
            from_state=source,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in STEP_TRANSITIONS.items()
        for target in targets
    ],
)
def test_every_allowed_step_transition_normalizes(
    source: str,
    target: str,
) -> None:
    event = step_event("event", target, 1)
    record = normalize_step_event(
        event,
        from_state=source,  # type: ignore[arg-type]
        prior_attempt=1,
    )
    assert (record.from_state, record.to_state) == (source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in STEP_TRANSITIONS
        for target in STEP_TRANSITIONS
        if target not in STEP_TRANSITIONS[source]
    ],
)
def test_every_forbidden_step_transition_is_rejected(
    source: str,
    target: str,
) -> None:
    with pytest.raises(
        StateProjectionError,
        match="step_domain_transition_invalid",
    ):
        normalize_step_event(
            step_event("event", target, 1),
            from_state=source,  # type: ignore[arg-type]
            prior_attempt=1,
        )


def test_atomic_workflow_and_step_histories_round_trip_on_fresh_connection(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    created = repo.create_workflow_definition(workflow(), steps())
    immutable_hash = created.definition_sha256

    repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-running-1",
            "running",
            STARTED,
            "dispatch_started",
        ),
    )
    repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-deferred",
            "deferred",
            STARTED + timedelta(seconds=10),
            "dependency_deferred",
        ),
    )
    repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-running-2",
            "running",
            STARTED + timedelta(seconds=20),
            "retry_started",
        ),
    )

    for event in (
        step_event("step-running-1", "running", 1),
        step_event("step-lock", "lock_busy", 2),
        step_event("step-running-2", "running", 3),
        step_event("step-deferred", "deferred", 4),
        step_event("step-running-3", "running", 5),
        step_event("step-unchanged", "unchanged", 6),
    ):
        repo.transition_step_domain(workflow().workflow_key, event)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event(
            "analysis-skipped",
            "skipped",
            7,
            step_key="analysis",
        ),
    )

    final = repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-succeeded",
            "succeeded",
            STARTED + timedelta(seconds=30),
            "all_steps_complete",
        ),
    )
    assert final.definition_sha256 == immutable_hash == definition_sha256(
        workflow(),
        steps(),
    )
    assert final.workflow.domain_state == "succeeded"
    assert final.steps[0].domain_state == "unchanged"
    assert [event.to_state for event in final.workflow_events] == [
        "running",
        "deferred",
        "running",
        "succeeded",
    ]
    assert [event.to_state for event in final.step_events] == [
        "running",
        "lock_busy",
        "running",
        "deferred",
        "running",
        "unchanged",
        "skipped",
    ]
    collection = final.step_records[0]
    assert collection.status == "succeeded"
    assert collection.attempt_count == 3
    assert collection.receipt_sha256 == RECEIPT
    assert collection.next_retry_at_utc is None
    assert collection.started_at_utc == "2026-07-24T02:00:01Z"
    assert collection.completed_at_utc == "2026-07-24T02:00:06Z"
    assert final.run_record.status == "succeeded"
    assert final.run_record.completed_at_utc == "2026-07-24T02:00:30Z"

    outer = json.loads(final.outer_summary_json)
    envelope = outer["workflow_definition"]
    assert envelope["schema_version"] == WORKFLOW_STATE_ENVELOPE_VERSION
    assert envelope["events"]["schema_version"] == DOMAIN_EVENTS_VERSION
    assert envelope["definition_sha256"] == immutable_hash
    assert [event["status"] for event in outer["steps"]["collection"]["events"]] == [
        "running",
        "failed",
        "running",
        "deferred",
        "running",
        "succeeded",
    ]
    reopened = OrchestrationRepository(database)
    assert reopened.load_workflow_definition(workflow().workflow_key) == final
    assert reopened.get_workflow(workflow().workflow_key) == final.run_record
    assert (
        reopened.get_step(workflow().workflow_key, "collection")
        == final.step_records[0]
    )


def test_exact_event_replay_is_zero_write_and_changed_identity_conflicts(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    event = step_event("stable-event", "running", 1)
    accepted = repo.transition_step_domain(workflow().workflow_key, event)
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_snapshot = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        assert (
            OrchestrationRepository(database).transition_step_domain(
                workflow().workflow_key,
                event,
            )
            == accepted
        )
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before_snapshot
        assert os.stat(database).st_mtime_ns == before_mtime

        changed = StepTransitionEvent(
            event.event_id,
            event.step_key,
            event.to_state,
            event.at_utc + timedelta(seconds=1),
        )
        with pytest.raises(
            StateProjectionError,
            match="step_domain_event_conflict",
        ):
            repo.transition_step_domain(workflow().workflow_key, changed)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before_snapshot
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


def test_original_definition_create_replay_returns_progressed_aggregate_without_write(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    progressed = repo.transition_step_domain(
        workflow().workflow_key,
        step_event("running", "running", 1),
    )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        replayed = OrchestrationRepository(database).create_workflow_definition(
            workflow(),
            steps(),
        )
        assert replayed == progressed
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


@pytest.mark.parametrize("workflow_state", ["queued", "deferred", "failed"])
def test_new_step_event_requires_running_workflow_and_is_zero_write(
    tmp_path: Path,
    workflow_state: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    if workflow_state != "queued":
        start_workflow(repo)
        repo.transition_workflow_domain(
            workflow().workflow_key,
            WorkflowTransitionEvent(
                f"workflow-{workflow_state}",
                workflow_state,  # type: ignore[arg-type]
                STARTED + timedelta(seconds=1),
                "dependency_not_ready",
            ),
        )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        with pytest.raises(
            StateProjectionError,
            match="step_domain_workflow_state_invalid",
        ):
            repo.transition_step_domain(
                workflow().workflow_key,
                step_event("new-step-event", "running", 2),
            )
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


def test_exact_step_replay_after_workflow_completion_is_zero_write(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("collection-running", "running", 1),
    )
    completed_step = step_event("collection-complete", "succeeded", 2)
    repo.transition_step_domain(workflow().workflow_key, completed_step)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event(
            "analysis-skipped",
            "skipped",
            3,
            step_key="analysis",
        ),
    )
    completed = repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            "workflow-complete",
            "succeeded",
            STARTED + timedelta(seconds=4),
            "all_steps_complete",
        ),
    )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        replayed = repo.transition_step_domain(
            workflow().workflow_key,
            completed_step,
        )
        assert replayed == completed
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


@pytest.mark.parametrize("step_state", ["pending", "running", "failed"])
def test_workflow_success_requires_every_step_successful_or_skipped(
    tmp_path: Path,
    step_state: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    if step_state != "pending":
        repo.transition_step_domain(
            workflow().workflow_key,
            step_event("collection-running", "running", 1),
        )
    if step_state == "failed":
        repo.transition_step_domain(
            workflow().workflow_key,
            step_event("collection-failed", "failed", 2),
        )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        expected = (
            "workflow_domain_running_step_unresolved"
            if step_state == "running"
            else "workflow_domain_steps_incomplete"
        )
        with pytest.raises(StateProjectionError, match=expected):
            repo.transition_workflow_domain(
                workflow().workflow_key,
                WorkflowTransitionEvent(
                    "premature-success",
                    "succeeded",
                    STARTED + timedelta(seconds=10),
                    "all_steps_complete",
                ),
            )
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


@pytest.mark.parametrize(
    "terminal_state",
    ["succeeded", "partial", "attention_required", "failed", "cancelled"],
)
def test_running_step_blocks_every_terminal_workflow_transition(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("collection-running", "running", 1),
    )
    with sqlite3.connect(database) as observer:
        before = snapshot(observer)
        with pytest.raises(
            StateProjectionError,
            match="workflow_domain_running_step_unresolved",
        ):
            repo.transition_workflow_domain(
                workflow().workflow_key,
                WorkflowTransitionEvent(
                    f"workflow-{terminal_state}",
                    terminal_state,  # type: ignore[arg-type]
                    STARTED + timedelta(seconds=2),
                    "terminal_requested",
                ),
            )
        assert snapshot(observer) == before


@pytest.mark.parametrize("outcome", ["deferred", "failed", "cancelled"])
def test_pre_step_dependency_defer_fail_and_cancel_remain_valid(
    tmp_path: Path,
    outcome: str,
) -> None:
    repo, _ = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    aggregate = repo.transition_workflow_domain(
        workflow().workflow_key,
        WorkflowTransitionEvent(
            f"workflow-{outcome}",
            outcome,  # type: ignore[arg-type]
            STARTED + timedelta(seconds=1),
            "dependency_not_ready",
        ),
    )
    assert aggregate.workflow.domain_state == outcome
    assert all(step.domain_state == "pending" for step in aggregate.steps)


@pytest.mark.parametrize(
    "change",
    ["timestamp", "state", "evidence"],
)
def test_workflow_event_identity_change_is_conflict_and_zero_write(
    tmp_path: Path,
    change: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    event = WorkflowTransitionEvent(
        "workflow-event",
        "running",
        STARTED,
        "dispatch_started",
    )
    accepted = repo.transition_workflow_domain(workflow().workflow_key, event)
    changed = replace(
        event,
        **{
            "timestamp": {"at_utc": STARTED + timedelta(seconds=1)},
            "state": {"to_state": "cancelled"},
            "evidence": {"evidence_code": "different_evidence"},
        }[change],
    )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        assert (
            repo.transition_workflow_domain(workflow().workflow_key, event)
            == accepted
        )
        with pytest.raises(
            StateProjectionError,
            match="workflow_domain_event_conflict",
        ):
            repo.transition_workflow_domain(workflow().workflow_key, changed)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


@pytest.mark.parametrize(
    "change",
    ["timestamp", "state", "evidence", "receipt", "retry", "counts", "step"],
)
def test_step_event_identity_evidence_change_is_conflict_and_zero_write(
    tmp_path: Path,
    change: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("running", "running", 1),
    )
    event = replace(
        step_event("stable-lock", "lock_busy", 2),
        controlled_counts={"deferred": 1},
    )
    repo.transition_step_domain(workflow().workflow_key, event)
    changed = replace(
        event,
        **{
            "timestamp": {"at_utc": STARTED + timedelta(seconds=3)},
            "state": {"to_state": "deferred"},
            "evidence": {"evidence_code": "provider_unavailable"},
            "receipt": {"receipt_sha256": "e" * 64},
            "retry": {
                "next_retry_at_utc": STARTED + timedelta(seconds=40)
            },
            "counts": {"controlled_counts": {"deferred": 2}},
            "step": {"step_key": "analysis"},
        }[change],
    )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        with pytest.raises(
            StateProjectionError,
            match="step_domain_event_conflict",
        ):
            repo.transition_step_domain(workflow().workflow_key, changed)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


@pytest.mark.parametrize(
    "event",
    [
        StepTransitionEvent(
            "missing-receipt",
            "collection",
            "succeeded",
            STARTED + timedelta(seconds=1),
        ),
        StepTransitionEvent(
            "forbidden-receipt",
            "collection",
            "running",
            STARTED + timedelta(seconds=1),
            receipt_sha256=RECEIPT,
        ),
        StepTransitionEvent(
            "missing-retry",
            "collection",
            "lock_busy",
            STARTED + timedelta(seconds=2),
            receipt_sha256=RECEIPT,
        ),
        StepTransitionEvent(
            "stale-retry",
            "collection",
            "lock_busy",
            STARTED + timedelta(seconds=2),
            receipt_sha256=RECEIPT,
            next_retry_at_utc=STARTED + timedelta(seconds=2),
        ),
        StepTransitionEvent(
            "terminal-partial-retry",
            "collection",
            "partial",
            STARTED + timedelta(seconds=2),
            receipt_sha256=RECEIPT,
            next_retry_at_utc=STARTED + timedelta(seconds=30),
        ),
        StepTransitionEvent(
            "forbidden-evidence",
            "collection",
            "skipped",
            STARTED + timedelta(seconds=1),
            evidence_code="receipt_received",
        ),
    ],
)
def test_missing_and_forbidden_receipt_retry_evidence_roll_back(
    tmp_path: Path,
    event: StepTransitionEvent,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    if event.to_state != "skipped":
        repo.transition_step_domain(
            workflow().workflow_key,
            step_event("running", "running", 0),
        )
    with sqlite3.connect(database) as observer:
        before = snapshot(observer)
        with pytest.raises(StateProjectionError):
            repo.transition_step_domain(workflow().workflow_key, event)
        assert snapshot(observer) == before


def test_partial_retry_evidence_is_rejected_without_any_write(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("collection-running", "running", 1),
    )
    invalid = StepTransitionEvent(
        "partial-with-retry",
        "collection",
        "partial",
        STARTED + timedelta(seconds=2),
        receipt_sha256=RECEIPT,
        next_retry_at_utc=STARTED + timedelta(seconds=30),
    )
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before = snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        with pytest.raises(
            StateProjectionError,
            match="step_domain_event_payload_invalid",
        ):
            repo.transition_step_domain(workflow().workflow_key, invalid)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert snapshot(observer) == before
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


def test_fixed_no_retry_deferred_evidence_remains_valid(
    tmp_path: Path,
) -> None:
    repo, _ = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("collection-running", "running", 1),
    )
    aggregate = repo.transition_step_domain(
        workflow().workflow_key,
        StepTransitionEvent(
            "collection-deferred-no-retry",
            "collection",
            "deferred",
            STARTED + timedelta(seconds=2),
            evidence_code="process_timeout",
        ),
    )
    event = aggregate.step_events[-1]
    assert event.to_state == "deferred"
    assert event.evidence_code == "process_timeout"
    assert event.next_retry_at_utc is None
    assert aggregate.step_records[0].next_retry_at_utc is None


def test_stale_or_out_of_order_time_and_duplicate_cross_scope_id_are_rejected(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("shared-id", "running", 2),
    )
    with sqlite3.connect(database) as observer:
        before = snapshot(observer)
        with pytest.raises(
            StateProjectionError,
            match="step_domain_event_time_invalid",
        ):
            repo.transition_step_domain(
                workflow().workflow_key,
                step_event("stale", "deferred", 2),
            )
        with pytest.raises(
            StateProjectionError,
            match="workflow_domain_event_conflict",
        ):
            repo.transition_workflow_domain(
                workflow().workflow_key,
                WorkflowTransitionEvent(
                    "shared-id",
                    "running",
                    STARTED + timedelta(seconds=3),
                    "dispatch_started",
                ),
            )
        assert snapshot(observer) == before


def mutate_summary(
    database: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT id,result_summary_json FROM orchestrator_runs"
        ).fetchone()
        document = json.loads(row[1])
        mutation(document)
        connection.execute(
            "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",
            (
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                row[0],
            ),
        )
        connection.commit()


def _tamper_event_from(document: dict[str, object]) -> None:
    document["workflow_definition"]["events"]["steps"]["collection"][0][  # type: ignore[index]
        "from_state"
    ] = "deferred"


def _tamper_event_time(document: dict[str, object]) -> None:
    document["workflow_definition"]["events"]["steps"]["collection"][1][  # type: ignore[index]
        "at_utc"
    ] = "2026-07-24T02:00:01Z"


def _tamper_projection_state(document: dict[str, object]) -> None:
    document["workflow_definition"]["projection"]["steps"][0][  # type: ignore[index]
        "domain_state"
    ] = "partial"


def _tamper_summary_mirror(document: dict[str, object]) -> None:
    document["steps"]["collection"]["events"][1]["attempt"] = 9  # type: ignore[index]


def _tamper_duplicate_id(document: dict[str, object]) -> None:
    document["workflow_definition"]["events"]["steps"]["collection"][1][  # type: ignore[index]
        "event_id"
    ] = "step-running"


@pytest.mark.parametrize(
    "mutation",
    [
        _tamper_event_from,
        _tamper_event_time,
        _tamper_projection_state,
        _tamper_summary_mirror,
        _tamper_duplicate_id,
    ],
)
def test_event_history_envelope_and_cross_projection_tampering_fails_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("step-running", "running", 1),
    )
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("step-failed", "failed", 2),
    )
    mutate_summary(database, mutation)
    observer = sqlite3.connect(database)
    try:
        before = snapshot(observer)
        with pytest.raises(OrchestrationRepositoryError):
            OrchestrationRepository(database).load_workflow_definition(
                workflow().workflow_key
            )
        assert snapshot(observer) == before
    finally:
        observer.close()


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        (
            "UPDATE orchestrator_steps SET status='deferred' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET attempt_count=9 "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET receipt_sha256=? "
            "WHERE step_key='collection'",
            ("e" * 64,),
        ),
        (
            "UPDATE orchestrator_steps SET next_retry_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:10:00Z",),
        ),
        (
            "UPDATE orchestrator_steps SET started_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:00:09Z",),
        ),
        (
            "UPDATE orchestrator_steps SET completed_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:00:09Z",),
        ),
    ],
)
def test_state_attempt_receipt_retry_and_timestamp_row_tampering_fails_closed(
    tmp_path: Path,
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("running", "running", 1),
    )
    repo.transition_step_domain(
        workflow().workflow_key,
        step_event("partial", "partial", 2),
    )
    with sqlite3.connect(database) as connection:
        connection.execute(statement, parameters)
        connection.commit()
    with pytest.raises(OrchestrationRepositoryError):
        OrchestrationRepository(database).load_workflow_definition(
            workflow().workflow_key
        )


class FaultConnection:
    def __init__(self, connection: sqlite3.Connection, fault: str) -> None:
        self.connection = connection
        self.fault = fault
        self.in_transaction = False

    def execute(self, statement: str, parameters: object = ()) -> object:
        normalized = " ".join(statement.upper().split())
        if normalized == "BEGIN IMMEDIATE":
            self.in_transaction = True
        elif self.in_transaction:
            if self.fault == "step_update" and normalized.startswith(
                "UPDATE ORCHESTRATOR_STEPS SET"
            ):
                raise sqlite3.OperationalError("injected step update fault")
            if self.fault == "summary_update" and normalized.startswith(
                "UPDATE ORCHESTRATOR_RUNS SET RESULT_SUMMARY_JSON"
            ):
                raise sqlite3.OperationalError("injected summary update fault")
            if self.fault == "workflow_update" and normalized.startswith(
                "UPDATE ORCHESTRATOR_RUNS SET STATUS="
            ):
                raise sqlite3.OperationalError("injected workflow update fault")
        return self.connection.execute(statement, parameters)

    def commit(self) -> None:
        if self.fault == "commit":
            raise sqlite3.OperationalError("injected commit fault")
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self.connection, name)


@pytest.mark.parametrize("fault", ["step_update", "summary_update", "commit"])
def test_transition_update_and_commit_faults_fully_roll_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    start_workflow(repo)
    with sqlite3.connect(database) as connection:
        before = snapshot(connection)
    real_connect = sqlite3.connect

    def faulty_connect(*args: object, **kwargs: object) -> FaultConnection:
        return FaultConnection(real_connect(*args, **kwargs), fault)

    monkeypatch.setattr(repository_module.sqlite3, "connect", faulty_connect)
    with pytest.raises(
        OrchestrationRepositoryError,
        match="step_domain_transition_persistence_failed",
    ):
        repo.transition_step_domain(
            workflow().workflow_key,
            step_event("running", "running", 1),
        )
    monkeypatch.undo()
    with real_connect(database) as connection:
        assert snapshot(connection) == before


def test_workflow_update_fault_fully_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    with sqlite3.connect(database) as connection:
        before = snapshot(connection)
    real_connect = sqlite3.connect

    def faulty_connect(*args: object, **kwargs: object) -> FaultConnection:
        return FaultConnection(real_connect(*args, **kwargs), "workflow_update")

    monkeypatch.setattr(repository_module.sqlite3, "connect", faulty_connect)
    with pytest.raises(
        OrchestrationRepositoryError,
        match="workflow_domain_transition_persistence_failed",
    ):
        repo.transition_workflow_domain(
            workflow().workflow_key,
            WorkflowTransitionEvent(
                "running",
                "running",
                STARTED,
                "dispatch_started",
            ),
        )
    monkeypatch.undo()
    with real_connect(database) as connection:
        assert snapshot(connection) == before
