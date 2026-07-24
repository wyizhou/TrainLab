"""Atomic persistence boundary for S5-05A workflow definitions and events.

The A1a codec remains pure.  This module embeds its canonical projection in the
existing controlled step-summary envelope and validates that projection against
every persisted workflow and step identity column.  S5-05A2 adds only strict
domain transitions and their atomic projections; recovery planning remains
intentionally absent.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Final

from .domain_state_machine import (
    MAX_STEP_EVENTS,
    MAX_WORKFLOW_EVENTS,
    WORKFLOW_TERMINAL_STATES,
    StepEventRecord,
    StepTransitionEvent,
    WorkflowEventRecord,
    WorkflowTransitionEvent,
    normalize_step_event,
    normalize_workflow_event,
    parse_step_history,
    parse_workflow_history,
    step_record_document,
    storage_summary_event,
    workflow_record_document,
)
from .repository import (
    OrchestrationRepository,
    OrchestrationRepositoryError,
    WorkflowRunRecord,
    WorkflowStepRecord,
    _decode_handoff,
)
from .state_projection import (
    MAX_ENCODED_CHARACTERS,
    StateProjectionError,
    StepDefinition,
    WorkflowDefinition,
    _canonical_json,
    _canonical_utc,
    _expect_keys,
    _identifier,
    _invalid,
    _object_without_duplicates,
    _parse_canonical_utc,
    _sha256,
    decode,
    definition_sha256,
    encode,
    step_storage_state,
    workflow_storage_state,
)


WORKFLOW_DEFINITION_ENVELOPE_VERSION: Final = "workflow_definition_v1"
WORKFLOW_STATE_ENVELOPE_VERSION: Final = "workflow_state_v1"
DOMAIN_EVENTS_VERSION: Final = "domain_events_v1"


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionAggregate:
    """Deeply validated database rows and their canonical domain projection."""

    run_record: WorkflowRunRecord
    step_records: tuple[WorkflowStepRecord, ...]
    workflow: WorkflowDefinition
    steps: tuple[StepDefinition, ...]
    definition_sha256: str
    outer_summary_json: str
    non_domain_summary_json: str
    workflow_events: tuple[WorkflowEventRecord, ...] = ()
    step_events: tuple[StepEventRecord, ...] = ()
    scheduler_handoff_lineage_json: str | None = None


@dataclass(frozen=True, slots=True)
class _DecodedSummary:
    workflow: WorkflowDefinition
    steps: tuple[StepDefinition, ...]
    definition_sha256: str
    non_domain_summary_json: str
    workflow_events: tuple[WorkflowEventRecord, ...]
    step_events: tuple[StepEventRecord, ...]
    stateful: bool
    scheduler_handoff_lineage_json: str | None


def _base_step_summary(steps: tuple[StepDefinition, ...]) -> dict[str, object]:
    return {
        "schema_version": "step_summary_v2",
        "steps": {
            step.step_key: {"events": []}
            for step in steps
        },
    }


def _aggregate_summary(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
    scheduler_handoff: dict[str, object] | None = None,
) -> tuple[str, str]:
    projection_json = encode(workflow, steps)
    projection = json.loads(projection_json)
    non_domain = _base_step_summary(steps)
    envelope = {
        "schema_version": WORKFLOW_DEFINITION_ENVELOPE_VERSION,
        "definition_sha256": definition_sha256(workflow, steps),
        "projection": projection,
    }
    if scheduler_handoff is not None:
        envelope["scheduler_handoff"] = scheduler_handoff
    outer = {
        **non_domain,
        "workflow_definition": envelope,
    }
    return _canonical_json(outer), _canonical_json(non_domain)


def _decode_aggregate_summary(
    raw: object,
) -> _DecodedSummary:
    if type(raw) is not str or not raw or len(raw) > MAX_ENCODED_CHARACTERS:
        _invalid()
    try:
        parsed = json.loads(raw, object_pairs_hook=_object_without_duplicates)
    except StateProjectionError:
        raise
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _invalid()
    outer = _expect_keys(
        parsed,
        frozenset({"schema_version", "steps", "workflow_definition"}),
    )
    if outer["schema_version"] != "step_summary_v2":
        _invalid()
    envelope_value = outer["workflow_definition"]
    if type(envelope_value) is not dict:
        _invalid()
    envelope_version = envelope_value.get("schema_version")
    if envelope_version == WORKFLOW_DEFINITION_ENVELOPE_VERSION:
        keys = {"schema_version", "definition_sha256", "projection"}
        if "scheduler_handoff" in envelope_value:
            keys.add("scheduler_handoff")
        envelope = _expect_keys(
            envelope_value,
            frozenset(keys),
        )
        stateful = False
    elif envelope_version == WORKFLOW_STATE_ENVELOPE_VERSION:
        keys = {"schema_version", "definition_sha256", "projection", "events"}
        if "scheduler_handoff" in envelope_value:
            keys.add("scheduler_handoff")
        envelope = _expect_keys(
            envelope_value,
            frozenset(keys),
        )
        stateful = True
    else:
        _invalid()
    envelope_hash = _sha256(envelope["definition_sha256"])
    if type(envelope["projection"]) is not dict:
        _invalid()
    projection_json = _canonical_json(envelope["projection"])
    workflow, steps = decode(projection_json)
    lineage_json: str | None = None
    if "scheduler_handoff" in envelope:
        if type(envelope["scheduler_handoff"]) is not dict:
            _invalid()
        lineage_json = _canonical_json(envelope["scheduler_handoff"])
        handoff = _decode_handoff(lineage_json)
        if handoff is None:
            _invalid()
        if (workflow.create_command_sha256 != handoff["materialization_command_sha256"]
                or workflow.create_evidence_sha256 != handoff["materialization_evidence_sha256"]
                or workflow.workflow_key != handoff["workflow_key"]
                or workflow.workflow_kind != handoff["workflow_kind"]
                or workflow.subject_id != handoff["subject_id"]
                or workflow.logical_local_date != handoff["logical_local_date"]
                or workflow.trigger_kind != handoff["trigger_kind"]
                or (None if workflow.deadline_at_utc is None else _canonical_utc(workflow.deadline_at_utc)) != handoff["deadline_at_utc"]):
            _invalid()
    computed_hash = definition_sha256(workflow, steps)
    if envelope_hash != computed_hash:
        _invalid()

    step_summaries = outer["steps"]
    if type(step_summaries) is not dict:
        _invalid()
    if set(step_summaries) != {step.step_key for step in steps}:
        _invalid()
    for step_definition in steps:
        item = _expect_keys(
            step_summaries[step_definition.step_key],
            frozenset({"events"}),
        )
        if type(item["events"]) is not list:
            _invalid()

    non_domain = {
        "schema_version": outer["schema_version"],
        "steps": step_summaries,
    }
    if raw != _canonical_json(outer):
        _invalid()
    non_domain_json = _canonical_json(non_domain)
    if not stateful:
        expected_outer, expected_non_domain = _aggregate_summary(
            workflow, steps, None if lineage_json is None else json.loads(lineage_json)
        )
        if raw != expected_outer or non_domain_json != expected_non_domain:
            _invalid()
        return _DecodedSummary(
            workflow,
            steps,
            computed_hash,
            expected_non_domain,
            (),
            (),
            False,
            lineage_json,
        )

    events = _expect_keys(
        envelope["events"],
        frozenset({"schema_version", "workflow", "steps"}),
    )
    if events["schema_version"] != DOMAIN_EVENTS_VERSION:
        _invalid()
    event_steps = events["steps"]
    if type(event_steps) is not dict:
        _invalid()
    step_keys = {step.step_key for step in steps}
    if set(event_steps) != step_keys:
        _invalid()
    workflow_events, workflow_state = parse_workflow_history(
        events["workflow"],
        started_at_utc=_canonical_utc(workflow.started_at_utc),
    )
    if workflow_state != workflow.domain_state:
        _invalid()

    all_step_events: list[StepEventRecord] = []
    seen_event_ids = {record.event_id for record in workflow_events}
    if len(seen_event_ids) != len(workflow_events):
        _invalid()
    for step in steps:
        history, state, _ = parse_step_history(
            event_steps[step.step_key],
            step_key=step.step_key,
            workflow_started_at_utc=_canonical_utc(workflow.started_at_utc),
        )
        if state != step.domain_state:
            _invalid()
        for record in history:
            if record.event_id in seen_event_ids:
                _invalid()
            seen_event_ids.add(record.event_id)
        all_step_events.extend(history)
        expected_summary_events = [
            storage_summary_event(record) for record in history
        ]
        if step_summaries[step.step_key]["events"] != expected_summary_events:
            _invalid()
    return _DecodedSummary(
        workflow,
        steps,
        computed_hash,
        non_domain_json,
        workflow_events,
        tuple(all_step_events),
        True,
        lineage_json,
    )


def _stateful_summary(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
    immutable_hash: str,
    workflow_events: tuple[WorkflowEventRecord, ...],
    step_events: tuple[StepEventRecord, ...],
    scheduler_handoff: dict[str, object] | None = None,
) -> tuple[str, str]:
    if (
        immutable_hash != definition_sha256(workflow, steps)
        or len(workflow_events) > MAX_WORKFLOW_EVENTS
    ):
        _invalid()
    events_by_step: dict[str, list[StepEventRecord]] = {
        step.step_key: [] for step in steps
    }
    for event in step_events:
        if event.step_key not in events_by_step:
            _invalid()
        events_by_step[event.step_key].append(event)
    if any(len(history) > MAX_STEP_EVENTS for history in events_by_step.values()):
        _invalid()

    non_domain = {
        "schema_version": "step_summary_v2",
        "steps": {
            step.step_key: {
                "events": [
                    storage_summary_event(event)
                    for event in events_by_step[step.step_key]
                ]
            }
            for step in steps
        },
    }
    envelope = {
        "schema_version": WORKFLOW_STATE_ENVELOPE_VERSION,
        "definition_sha256": immutable_hash,
        "projection": json.loads(encode(workflow, steps)),
        "events": {
            "schema_version": DOMAIN_EVENTS_VERSION,
            "workflow": [
                workflow_record_document(event)
                for event in workflow_events
            ],
            "steps": {
                step.step_key: [
                    step_record_document(event)
                    for event in events_by_step[step.step_key]
                ]
                for step in steps
            },
        },
    }
    if scheduler_handoff is not None:
        envelope["scheduler_handoff"] = scheduler_handoff
    outer = {
        **non_domain,
        "workflow_definition": envelope,
    }
    return _canonical_json(outer), _canonical_json(non_domain)


def _validate_initial_definition(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
) -> str:
    requested_projection = encode(workflow, steps)
    if workflow.domain_state != "queued":
        raise StateProjectionError("workflow_definition_initial_state_invalid")
    if any(step.domain_state != "pending" for step in steps):
        raise StateProjectionError("workflow_definition_initial_state_invalid")
    return requested_projection


def _step_rows_for_run(
    repository: OrchestrationRepository,
    connection: sqlite3.Connection,
    run_id: int,
) -> tuple[WorkflowStepRecord, ...]:
    rows = connection.execute(
        "SELECT id,orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,"
        "request_sha256,invocation_id,downstream_run_id,receipt_sha256,status,"
        "attempt_count,next_retry_at_utc,started_at_utc,completed_at_utc "
        "FROM orchestrator_steps WHERE orchestrator_run_id=? "
        "ORDER BY ordinal ASC,id ASC",
        (run_id,),
    ).fetchall()
    return tuple(repository._step_from_row(row) for row in rows)


def load_persisted_workflow_definition(
    repository: OrchestrationRepository,
    connection: sqlite3.Connection,
    workflow_key: str,
    *,
    missing_none: bool,
    preloaded_run: WorkflowRunRecord | None = None,
) -> WorkflowDefinitionAggregate | None:
    """Connection-bound deep loader used by public repository reads."""

    run = preloaded_run or repository._run_by_key(
        connection,
        workflow_key,
        missing_none=missing_none,
    )
    if run is None:
        return None
    if run.workflow_key != workflow_key:
        _invalid()

    decoded = _decode_aggregate_summary(run.result_summary_json)
    workflow = decoded.workflow
    steps = decoded.steps
    if not decoded.stateful:
        _validate_initial_definition(workflow, steps)
    if type(run.id) is not int or run.id <= 0:
        _invalid()
    expected_deadline = (
        None
        if workflow.deadline_at_utc is None
        else _canonical_utc(workflow.deadline_at_utc)
    )
    immutable_run_values = (
        (run.workflow_key, workflow.workflow_key),
        (run.workflow_kind, workflow.workflow_kind),
        (run.subject_id, workflow.subject_id),
        (run.logical_local_date, workflow.logical_local_date),
        (run.trigger_kind, workflow.trigger_kind),
        (run.deadline_at_utc, expected_deadline),
        (run.parent_workflow_run_id, workflow.parent_workflow_run_id),
        (run.started_at_utc, _canonical_utc(workflow.started_at_utc)),
    )
    if any(actual != expected for actual, expected in immutable_run_values):
        _invalid()
    if run.status != workflow_storage_state(workflow.domain_state):
        _invalid()
    expected_run_completed = (
        None
        if workflow.domain_state in {"queued", "running"}
        else decoded.workflow_events[-1].at_utc
        if decoded.workflow_events
        else None
    )
    if run.completed_at_utc != expected_run_completed:
        _invalid()

    step_rows = _step_rows_for_run(repository, connection, run.id)
    if len(step_rows) != len(steps):
        _invalid()
    for expected, row in zip(steps, step_rows, strict=True):
        if type(row.id) is not int or row.id <= 0:
            _invalid()
        if row.orchestrator_run_id != run.id:
            _invalid()
        immutable_step_values = (
            (row.step_key, expected.step_key),
            (row.ordinal, expected.ordinal),
            (row.layer_no, expected.layer_no),
            (row.tool_mode, expected.tool_mode),
            (row.request_sha256, expected.request_sha256),
            (row.invocation_id, expected.invocation_id),
            (row.downstream_run_id, expected.downstream_run_id),
        )
        if any(actual != wanted for actual, wanted in immutable_step_values):
            _invalid()
        if row.status != step_storage_state(expected.domain_state):
            _invalid()
        history = tuple(
            event
            for event in decoded.step_events
            if event.step_key == expected.step_key
        )
        last = history[-1] if history else None
        first_running = next(
            (event for event in history if event.to_state == "running"),
            None,
        )
        expected_step_completed = (
            None
            if expected.domain_state in {"pending", "running", "deferred"}
            else last.at_utc
            if last is not None
            else None
        )
        if (
            row.receipt_sha256
            != (None if last is None else last.receipt_sha256)
            or row.attempt_count != (0 if last is None else last.attempt)
            or row.next_retry_at_utc
            != (None if last is None else last.next_retry_at_utc)
            or row.started_at_utc
            != (None if first_running is None else first_running.at_utc)
            or row.completed_at_utc != expected_step_completed
        ):
            _invalid()

    return WorkflowDefinitionAggregate(
        run_record=run,
        step_records=step_rows,
        workflow=workflow,
        steps=steps,
        definition_sha256=decoded.definition_sha256,
        outer_summary_json=run.result_summary_json,
        non_domain_summary_json=decoded.non_domain_summary_json,
        workflow_events=decoded.workflow_events,
        step_events=decoded.step_events,
        scheduler_handoff_lineage_json=decoded.scheduler_handoff_lineage_json,
    )


def _same_requested_projection(
    aggregate: WorkflowDefinitionAggregate,
    requested_projection: str,
) -> bool:
    requested_workflow, requested_steps = decode(requested_projection)
    return aggregate.definition_sha256 == definition_sha256(
        requested_workflow,
        requested_steps,
    )


def create_persisted_workflow_definition(
    repository: OrchestrationRepository,
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
) -> WorkflowDefinitionAggregate:
    """Create all definition rows in one transaction or exactly replay them."""

    requested_projection = _validate_initial_definition(workflow, steps)
    existing_run = repository.get_workflow(workflow.workflow_key)
    if existing_run is not None and _decode_handoff(existing_run.result_summary_json) is None:
        existing = repository.load_workflow_definition(workflow.workflow_key)
        if existing is not None:
            if _same_requested_projection(existing, requested_projection):
                return existing
            raise StateProjectionError("workflow_definition_replay_conflict")

    outer_summary, non_domain_summary = _aggregate_summary(workflow, steps)
    try:
        with repository._transaction() as connection:
            raced = repository._run_by_key(
                connection,
                workflow.workflow_key,
                missing_none=True,
            )
            if raced is not None:
                handoff = _decode_handoff(raced.result_summary_json)
                if handoff is not None:
                    expected_deadline = None if workflow.deadline_at_utc is None else _canonical_utc(workflow.deadline_at_utc)
                    if (raced.workflow_kind != workflow.workflow_kind or raced.subject_id != workflow.subject_id
                            or raced.logical_local_date != workflow.logical_local_date or raced.trigger_kind != workflow.trigger_kind
                            or raced.deadline_at_utc != expected_deadline or raced.started_at_utc != _canonical_utc(workflow.started_at_utc)
                            or raced.status != "started" or raced.completed_at_utc is not None
                            or workflow.create_command_sha256 != handoff["materialization_command_sha256"]
                            or workflow.create_evidence_sha256 != handoff["materialization_evidence_sha256"]):
                        raise StateProjectionError("scheduler_handoff_materialization_conflict")
                    bound_outer_summary, _ = _aggregate_summary(workflow, steps, handoff)
                    for step_definition in steps:
                        connection.execute(
                            "INSERT INTO orchestrator_steps (orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,request_sha256,invocation_id,downstream_run_id,status) VALUES (?,?,?,?,?,?,?,?,?)",
                            (raced.id, step_definition.step_key, step_definition.ordinal, step_definition.layer_no,
                             step_definition.tool_mode, step_definition.request_sha256, step_definition.invocation_id,
                             step_definition.downstream_run_id, step_storage_state(step_definition.domain_state)),
                        )
                    connection.execute("UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?", (bound_outer_summary, raced.id))
                    aggregate = load_persisted_workflow_definition(repository, connection, workflow.workflow_key, missing_none=False)
                    if aggregate is None or not _same_requested_projection(aggregate, requested_projection):
                        _invalid()
                    return aggregate
                aggregate = load_persisted_workflow_definition(
                    repository,
                    connection,
                    workflow.workflow_key,
                    missing_none=False,
                    preloaded_run=raced,
                )
                if aggregate is None:
                    _invalid()
                if _same_requested_projection(aggregate, requested_projection):
                    return aggregate
                raise StateProjectionError("workflow_definition_replay_conflict")

            cursor = connection.execute(
                "INSERT INTO orchestrator_runs "
                "(workflow_key,workflow_kind,subject_id,logical_local_date,"
                "trigger_kind,status,deadline_at_utc,parent_workflow_run_id,"
                "started_at_utc,result_summary_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    workflow.workflow_key,
                    workflow.workflow_kind,
                    workflow.subject_id,
                    workflow.logical_local_date,
                    workflow.trigger_kind,
                    workflow_storage_state(workflow.domain_state),
                    None
                    if workflow.deadline_at_utc is None
                    else _canonical_utc(workflow.deadline_at_utc),
                    workflow.parent_workflow_run_id,
                    _canonical_utc(workflow.started_at_utc),
                    non_domain_summary,
                ),
            )
            run_id = cursor.lastrowid
            if type(run_id) is not int or run_id <= 0:
                _invalid()
            for step_definition in steps:
                connection.execute(
                    "INSERT INTO orchestrator_steps "
                    "(orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,"
                    "request_sha256,invocation_id,downstream_run_id,status) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        step_definition.step_key,
                        step_definition.ordinal,
                        step_definition.layer_no,
                        step_definition.tool_mode,
                        step_definition.request_sha256,
                        step_definition.invocation_id,
                        step_definition.downstream_run_id,
                        step_storage_state(step_definition.domain_state),
                    ),
                )
            connection.execute(
                "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",
                (outer_summary, run_id),
            )
            aggregate = load_persisted_workflow_definition(
                repository,
                connection,
                workflow.workflow_key,
                missing_none=False,
            )
            if aggregate is None:
                _invalid()
            if (
                not _same_requested_projection(aggregate, requested_projection)
                or aggregate.non_domain_summary_json != non_domain_summary
            ):
                _invalid()
            return aggregate
    except OrchestrationRepositoryError:
        raise
    except sqlite3.Error as exc:
        raise OrchestrationRepositoryError(
            "workflow_definition_persistence_failed"
        ) from exc


def _required_aggregate(
    repository: OrchestrationRepository,
    connection: sqlite3.Connection,
    workflow_key: str,
) -> WorkflowDefinitionAggregate:
    aggregate = load_persisted_workflow_definition(
        repository,
        connection,
        workflow_key,
        missing_none=False,
    )
    if aggregate is None:
        _invalid()
    return aggregate


def _event_with_id(
    aggregate: WorkflowDefinitionAggregate,
    event_id: str,
) -> WorkflowEventRecord | StepEventRecord | None:
    for record in aggregate.workflow_events:
        if record.event_id == event_id:
            return record
    for record in aggregate.step_events:
        if record.event_id == event_id:
            return record
    return None


def _workflow_replay(
    aggregate: WorkflowDefinitionAggregate,
    event: WorkflowTransitionEvent,
) -> WorkflowDefinitionAggregate | None:
    existing = _event_with_id(aggregate, event.event_id)
    if existing is None:
        return None
    if type(existing) is WorkflowEventRecord:
        try:
            requested = normalize_workflow_event(
                event,
                from_state=existing.from_state,
            )
        except OrchestrationRepositoryError:
            requested = None
        if requested == existing:
            return aggregate
    raise StateProjectionError("workflow_domain_event_conflict")


def _step_replay(
    aggregate: WorkflowDefinitionAggregate,
    event: StepTransitionEvent,
) -> WorkflowDefinitionAggregate | None:
    existing = _event_with_id(aggregate, event.event_id)
    if existing is None:
        return None
    if type(existing) is StepEventRecord:
        prior_attempt = existing.attempt - (
            1 if existing.to_state == "running" else 0
        )
        try:
            requested = normalize_step_event(
                event,
                from_state=existing.from_state,
                prior_attempt=prior_attempt,
            )
        except OrchestrationRepositoryError:
            requested = None
        if requested == existing:
            return aggregate
    raise StateProjectionError("step_domain_event_conflict")


def _validate_new_workflow_event(
    aggregate: WorkflowDefinitionAggregate,
    event: WorkflowTransitionEvent,
) -> WorkflowEventRecord:
    if len(aggregate.workflow_events) >= MAX_WORKFLOW_EVENTS:
        raise StateProjectionError("workflow_domain_event_limit")
    record = normalize_workflow_event(
        event,
        from_state=aggregate.workflow.domain_state,
    )
    if record.to_state in WORKFLOW_TERMINAL_STATES:
        if any(step.domain_state == "running" for step in aggregate.steps):
            raise StateProjectionError(
                "workflow_domain_running_step_unresolved"
            )
        if record.to_state == "succeeded" and any(
            step.domain_state not in {"succeeded", "unchanged", "skipped"}
            for step in aggregate.steps
        ):
            raise StateProjectionError("workflow_domain_steps_incomplete")
    previous_at = (
        aggregate.workflow_events[-1].at_utc
        if aggregate.workflow_events
        else _canonical_utc(aggregate.workflow.started_at_utc)
    )
    previous = _parse_canonical_utc(previous_at)
    current = _parse_canonical_utc(record.at_utc)
    if (
        (aggregate.workflow_events and current <= previous)
        or (not aggregate.workflow_events and current < previous)
    ):
        raise StateProjectionError("workflow_domain_event_time_invalid")
    return record


def _validate_new_step_event(
    aggregate: WorkflowDefinitionAggregate,
    event: StepTransitionEvent,
) -> StepEventRecord:
    if aggregate.workflow.domain_state != "running":
        raise StateProjectionError("step_domain_workflow_state_invalid")
    matching = tuple(
        record
        for record in aggregate.step_events
        if record.step_key == event.step_key
    )
    step = next(
        (item for item in aggregate.steps if item.step_key == event.step_key),
        None,
    )
    if step is None:
        raise OrchestrationRepositoryError("orchestrator_step_not_found")
    if len(matching) >= MAX_STEP_EVENTS:
        raise StateProjectionError("step_domain_event_limit")
    prior_attempt = matching[-1].attempt if matching else 0
    record = normalize_step_event(
        event,
        from_state=step.domain_state,
        prior_attempt=prior_attempt,
    )
    previous_at = (
        matching[-1].at_utc
        if matching
        else _canonical_utc(aggregate.workflow.started_at_utc)
    )
    previous = _parse_canonical_utc(previous_at)
    current = _parse_canonical_utc(record.at_utc)
    if (
        (matching and current <= previous)
        or (not matching and current < previous)
    ):
        raise StateProjectionError("step_domain_event_time_invalid")
    return record


def transition_persisted_workflow(
    repository: OrchestrationRepository,
    workflow_key: str,
    event: WorkflowTransitionEvent,
) -> WorkflowDefinitionAggregate:
    """Append one workflow event and atomically update every projection."""

    if type(event) is not WorkflowTransitionEvent:
        _invalid()
    _identifier(event.event_id)
    existing = repository.load_workflow_definition(workflow_key)
    if existing is None:
        raise OrchestrationRepositoryError("orchestrator_workflow_not_found")
    replayed = _workflow_replay(existing, event)
    if replayed is not None:
        return replayed
    _validate_new_workflow_event(existing, event)

    try:
        with repository._transaction() as connection:
            aggregate = _required_aggregate(
                repository,
                connection,
                workflow_key,
            )
            replayed = _workflow_replay(aggregate, event)
            if replayed is not None:
                return replayed
            record = _validate_new_workflow_event(aggregate, event)
            next_workflow = replace(
                aggregate.workflow,
                domain_state=record.to_state,
            )
            next_events = (*aggregate.workflow_events, record)
            outer_summary, _ = _stateful_summary(
                next_workflow,
                aggregate.steps,
                aggregate.definition_sha256,
                next_events,
                aggregate.step_events,
                None if aggregate.scheduler_handoff_lineage_json is None else json.loads(aggregate.scheduler_handoff_lineage_json),
            )
            completed = (
                None if record.to_state == "running" else record.at_utc
            )
            connection.execute(
                "UPDATE orchestrator_runs SET status=?,completed_at_utc=?,"
                "result_summary_json=? WHERE id=?",
                (
                    workflow_storage_state(record.to_state),
                    completed,
                    outer_summary,
                    aggregate.run_record.id,
                ),
            )
            return _required_aggregate(
                repository,
                connection,
                workflow_key,
            )
    except OrchestrationRepositoryError:
        raise
    except sqlite3.Error as exc:
        raise OrchestrationRepositoryError(
            "workflow_domain_transition_persistence_failed"
        ) from exc


def transition_persisted_step(
    repository: OrchestrationRepository,
    workflow_key: str,
    event: StepTransitionEvent,
) -> WorkflowDefinitionAggregate:
    """Append one step event and atomically update every projection."""

    if type(event) is not StepTransitionEvent:
        _invalid()
    _identifier(event.event_id)
    _identifier(event.step_key)
    existing = repository.load_workflow_definition(workflow_key)
    if existing is None:
        raise OrchestrationRepositoryError("orchestrator_workflow_not_found")
    replayed = _step_replay(existing, event)
    if replayed is not None:
        return replayed
    _validate_new_step_event(existing, event)

    try:
        with repository._transaction() as connection:
            aggregate = _required_aggregate(
                repository,
                connection,
                workflow_key,
            )
            replayed = _step_replay(aggregate, event)
            if replayed is not None:
                return replayed
            record = _validate_new_step_event(aggregate, event)
            next_steps = tuple(
                replace(step, domain_state=record.to_state)
                if step.step_key == record.step_key
                else step
                for step in aggregate.steps
            )
            next_events = (*aggregate.step_events, record)
            outer_summary, _ = _stateful_summary(
                aggregate.workflow,
                next_steps,
                aggregate.definition_sha256,
                aggregate.workflow_events,
                next_events,
                None if aggregate.scheduler_handoff_lineage_json is None else json.loads(aggregate.scheduler_handoff_lineage_json),
            )
            row = next(
                item
                for item in aggregate.step_records
                if item.step_key == record.step_key
            )
            prior_history = tuple(
                item
                for item in aggregate.step_events
                if item.step_key == record.step_key
            )
            first_running = next(
                (
                    item.at_utc
                    for item in (*prior_history, record)
                    if item.to_state == "running"
                ),
                None,
            )
            completed = (
                None
                if record.to_state in {"running", "deferred"}
                else record.at_utc
            )
            connection.execute(
                "UPDATE orchestrator_steps SET status=?,receipt_sha256=?,"
                "attempt_count=?,next_retry_at_utc=?,started_at_utc=?,"
                "completed_at_utc=? WHERE id=?",
                (
                    step_storage_state(record.to_state),
                    record.receipt_sha256,
                    record.attempt,
                    record.next_retry_at_utc,
                    first_running,
                    completed,
                    row.id,
                ),
            )
            connection.execute(
                "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",
                (outer_summary, aggregate.run_record.id),
            )
            return _required_aggregate(
                repository,
                connection,
                workflow_key,
            )
    except OrchestrationRepositoryError:
        raise
    except sqlite3.Error as exc:
        raise OrchestrationRepositoryError(
            "step_domain_transition_persistence_failed"
        ) from exc


__all__ = [
    "DOMAIN_EVENTS_VERSION",
    "WORKFLOW_DEFINITION_ENVELOPE_VERSION",
    "WORKFLOW_STATE_ENVELOPE_VERSION",
    "WorkflowDefinitionAggregate",
]
