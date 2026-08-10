"""Deterministic durable-state failure boundaries using disposable SQLite data."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.domain_state_machine import WorkflowTransitionEvent
from trainlab.orchestration.repository import OrchestrationRepository
from trainlab.orchestration.state_projection import (
    StateProjectionError,
    StepDefinition,
    WorkflowDefinition,
    WorkflowDomainState,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _repository(tmp_path: Path) -> tuple[OrchestrationRepository, Path]:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/foundation-ready.json",
        root / "state/locks/foundation.lock",
    )
    assert (
        FoundationTool(config)
        .execute(
            FoundationRequest(
                "init", "reliability-state-machine", "2026-08-07T00:00:00Z"
            )
        )
        .ready
    )
    return OrchestrationRepository(config.database_path), config.database_path


def _definition(
    key: str = "morning:state-machine",
) -> tuple[WorkflowDefinition, tuple[StepDefinition, ...]]:
    return (
        WorkflowDefinition(
            key,
            "morning",
            None,
            "2026-08-07",
            "scheduled",
            NOW + timedelta(hours=1),
            None,
            NOW,
            "a" * 64,
            "b" * 64,
            "queued",
        ),
        (
            StepDefinition(
                "collection",
                0,
                2,
                "incremental",
                "c" * 64,
                "state-machine-invocation",
                "synthetic-run",
                "pending",
            ),
        ),
    )


def _event(
    event_id: str,
    target: WorkflowDomainState,
    seconds: int,
) -> WorkflowTransitionEvent:
    return WorkflowTransitionEvent(
        event_id,
        target,
        NOW + timedelta(seconds=seconds),
        "deterministic_check",
    )


def test_single_writer_replay_has_one_immutable_definition_and_no_extra_events(
    tmp_path: Path,
) -> None:
    repository, database = _repository(tmp_path)
    workflow, steps = _definition()
    first = repository.create_workflow_definition(workflow, steps)
    replay = repository.create_workflow_definition(workflow, steps)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_runs"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_steps"
        ).fetchone() == (1,)
    assert replay.definition_sha256 == first.definition_sha256
    assert replay.workflow_events == first.workflow_events == ()


def test_crash_before_commit_leaves_no_partial_definition(tmp_path: Path) -> None:
    repository, database = _repository(tmp_path)
    workflow, _steps = _definition("morning:crash-before-commit")
    connection = sqlite3.connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO orchestrator_runs "
            "(workflow_key,workflow_kind,trigger_kind,status,started_at_utc,result_summary_json) "
            "VALUES (?,?,'scheduled','started',?,'{}')",
            (workflow.workflow_key, workflow.workflow_kind, "2026-08-07T00:00:00Z"),
        )
        # A process crash abandons this uncommitted transaction.  Closing is the
        # SQLite crash boundary; a fresh repository must not observe its write.
    finally:
        connection.close()

    assert repository.get_workflow(workflow.workflow_key) is None


def test_crash_after_commit_preserves_recoverable_transition_evidence(
    tmp_path: Path,
) -> None:
    repository, database = _repository(tmp_path)
    workflow, steps = _definition("morning:crash-after-commit")
    repository.create_workflow_definition(workflow, steps)
    repository.transition_workflow_domain(
        workflow.workflow_key, _event("commit-running", "running", 1)
    )

    # A new process has no in-memory state: recovery is exclusively durable.
    recovered = OrchestrationRepository(database).load_workflow_definition(
        workflow.workflow_key
    )
    assert recovered is not None
    assert recovered.workflow.domain_state == "running"
    assert [(item.event_id, item.to_state) for item in recovered.workflow_events] == [
        ("commit-running", "running")
    ]


def test_stale_reader_cannot_overwrite_newer_accepted_state(tmp_path: Path) -> None:
    repository, _database = _repository(tmp_path)
    workflow, steps = _definition("morning:stale-reader")
    repository.create_workflow_definition(workflow, steps)
    stale_snapshot = repository.load_workflow_definition(workflow.workflow_key)
    assert (
        stale_snapshot is not None and stale_snapshot.workflow.domain_state == "queued"
    )

    repository.transition_workflow_domain(
        workflow.workflow_key, _event("new-owner-running", "running", 1)
    )
    with pytest.raises(
        StateProjectionError, match="workflow_domain_transition_invalid"
    ):
        repository.transition_workflow_domain(
            workflow.workflow_key, _event("stale-reader-running", "running", 2)
        )

    current = repository.load_workflow_definition(workflow.workflow_key)
    assert current is not None
    assert [event.event_id for event in current.workflow_events] == [
        "new-owner-running"
    ]
