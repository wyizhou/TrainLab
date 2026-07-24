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
from trainlab.orchestration import OrchestrationRepository, OrchestrationRepositoryError
from trainlab.orchestration.state_projection import (
    StateProjectionError,
    StepDefinition,
    WorkflowDefinition,
    definition_sha256,
    encode,
)
from trainlab.orchestration.workflow_definition_store import (
    WORKFLOW_DEFINITION_ENVELOPE_VERSION,
)
import trainlab.orchestration.repository as repository_module


STARTED = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
COMMAND_HASH = "a" * 64
EVIDENCE_HASH = "b" * 64


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
        FoundationRequest("init", "s5-05a1b", "2026-07-24T02:00:00Z")
    )
    assert receipt.status == "initialized"
    return OrchestrationRepository(root / "data.db"), root / "data.db"


def workflow(**changes: object) -> WorkflowDefinition:
    values: dict[str, object] = {
        "workflow_key": "morning:2026-07-24",
        "workflow_kind": "morning",
        "subject_id": None,
        "logical_local_date": "2026-07-24",
        "trigger_kind": "scheduled",
        "deadline_at_utc": STARTED + timedelta(hours=1),
        "parent_workflow_run_id": None,
        "started_at_utc": STARTED,
        "create_command_sha256": COMMAND_HASH,
        "create_evidence_sha256": EVIDENCE_HASH,
        "domain_state": "queued",
    }
    values.update(changes)
    return WorkflowDefinition(**values)  # type: ignore[arg-type]


def steps() -> tuple[StepDefinition, ...]:
    return (
        StepDefinition(
            "foundation",
            0,
            1,
            "verify",
            "c" * 64,
            "foundation-invocation",
            None,
            "pending",
        ),
        StepDefinition(
            "collection",
            1,
            2,
            "incremental",
            "d" * 64,
            "garmin-invocation",
            "garmin-run",
            "pending",
        ),
        StepDefinition(
            "analysis",
            2,
            3,
            "daily",
            "e" * 64,
            None,
            None,
            "pending",
        ),
    )


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def database_snapshot(
    connection: sqlite3.Connection,
) -> tuple[list[tuple], list[tuple]]:
    runs = connection.execute(
        "SELECT * FROM orchestrator_runs ORDER BY id"
    ).fetchall()
    step_rows = connection.execute(
        "SELECT * FROM orchestrator_steps ORDER BY id"
    ).fetchall()
    return runs, step_rows


def test_atomic_create_and_fresh_connection_deep_round_trip(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    created = repo.create_workflow_definition(workflow(), steps())

    assert created.workflow == workflow()
    assert created.steps == steps()
    assert created.definition_sha256 == definition_sha256(workflow(), steps())
    assert created.run_record.status == "started"
    assert [row.status for row in created.step_records] == ["pending"] * 3
    assert [row.ordinal for row in created.step_records] == [0, 1, 2]

    outer = json.loads(created.outer_summary_json)
    assert set(outer) == {"schema_version", "steps", "workflow_definition"}
    assert outer["schema_version"] == "step_summary_v2"
    assert set(outer["steps"]) == {"foundation", "collection", "analysis"}
    assert all(item == {"events": []} for item in outer["steps"].values())
    assert set(outer["workflow_definition"]) == {
        "schema_version",
        "definition_sha256",
        "projection",
    }
    assert (
        outer["workflow_definition"]["schema_version"]
        == WORKFLOW_DEFINITION_ENVELOPE_VERSION
    )
    assert outer["workflow_definition"]["projection"] == json.loads(
        encode(workflow(), steps())
    )
    assert json.loads(created.non_domain_summary_json) == {
        "schema_version": "step_summary_v2",
        "steps": outer["steps"],
    }

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_runs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_steps"
        ).fetchone()[0] == 3

    reopened = OrchestrationRepository(database)
    loaded = reopened.load_workflow_definition(workflow().workflow_key)
    assert loaded == created
    assert reopened.get_workflow(workflow().workflow_key) == created.run_record
    for definition, row in zip(steps(), created.step_records, strict=True):
        assert reopened.get_step(workflow().workflow_key, definition.step_key) == row


def test_missing_definition_load_is_read_only_none(tmp_path: Path) -> None:
    repo, database = repository(tmp_path)
    before_mtime = os.stat(database).st_mtime_ns
    assert repo.load_workflow_definition("missing") is None
    assert os.stat(database).st_mtime_ns == before_mtime
    with pytest.raises(
        OrchestrationRepositoryError,
        match="workflow_definition_key_invalid",
    ):
        repo.load_workflow_definition(None)  # type: ignore[arg-type]


def test_create_uses_one_begin_immediate_for_run_steps_and_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = repository(tmp_path)
    statements: list[str] = []
    real_connect = repo._connect

    def traced_connect() -> sqlite3.Connection:
        connection = real_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repo, "_connect", traced_connect)
    repo.create_workflow_definition(workflow(), steps())
    normalized = [" ".join(item.upper().split()) for item in statements]
    assert normalized.count("BEGIN IMMEDIATE") == 1
    assert sum(item.startswith("INSERT INTO ORCHESTRATOR_RUNS") for item in normalized) == 1
    assert sum(item.startswith("INSERT INTO ORCHESTRATOR_STEPS") for item in normalized) == 3
    assert sum(
        item.startswith("UPDATE ORCHESTRATOR_RUNS SET RESULT_SUMMARY_JSON")
        for item in normalized
    ) == 1


def test_exact_replay_returns_existing_aggregate_without_any_write_or_mtime_change(
    tmp_path: Path,
) -> None:
    repo, database = repository(tmp_path)
    created = repo.create_workflow_definition(workflow(), steps())
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_rows = database_snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        replayed = OrchestrationRepository(database).create_workflow_definition(
            workflow(),
            steps(),
        )
        assert replayed == created
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert database_snapshot(observer) == before_rows
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


def _changed_steps(change: str) -> tuple[StepDefinition, ...]:
    original = list(steps())
    if change == "append":
        original.append(
            StepDefinition(
                "extra",
                3,
                5,
                "check",
                "f" * 64,
                None,
                None,
                "pending",
            )
        )
    elif change == "reorder":
        original = [
            replace(original[1], ordinal=0),
            replace(original[0], ordinal=1),
            original[2],
        ]
    else:
        original[1] = replace(original[1], **{change: {
            "step_key": "changed",
            "layer_no": 4,
            "tool_mode": "repair",
            "request_sha256": "f" * 64,
            "invocation_id": "changed-invocation",
            "downstream_run_id": "changed-run",
        }[change]})
    return tuple(original)


@pytest.mark.parametrize(
    ("workflow_change", "step_change"),
    [
        ({"workflow_kind": "weekly"}, None),
        ({"subject_id": 99}, None),
        ({"logical_local_date": "2026-07-25"}, None),
        ({"trigger_kind": "manual"}, None),
        ({"deadline_at_utc": STARTED + timedelta(hours=2)}, None),
        ({"parent_workflow_run_id": 99}, None),
        ({"started_at_utc": STARTED + timedelta(seconds=1)}, None),
        ({"create_command_sha256": "f" * 64}, None),
        ({"create_evidence_sha256": "f" * 64}, None),
        (None, "step_key"),
        (None, "layer_no"),
        (None, "tool_mode"),
        (None, "request_sha256"),
        (None, "invocation_id"),
        (None, "downstream_run_id"),
        (None, "append"),
        (None, "reorder"),
    ],
    ids=[
        "workflow-kind",
        "subject",
        "logical-date",
        "trigger",
        "deadline",
        "parent",
        "started",
        "command-hash",
        "evidence-hash",
        "step-key",
        "step-layer",
        "step-tool",
        "step-request-hash",
        "step-invocation",
        "step-downstream",
        "extra-step",
        "step-order",
    ],
)
def test_conflicting_replay_rejects_without_writes(
    tmp_path: Path,
    workflow_change: dict[str, object] | None,
    step_change: str | None,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_rows = database_snapshot(observer)
        before_mtime = os.stat(database).st_mtime_ns
        requested_workflow = workflow(**(workflow_change or {}))
        requested_steps = steps() if step_change is None else _changed_steps(step_change)
        with pytest.raises(
            OrchestrationRepositoryError,
            match="workflow_definition_replay_conflict",
        ):
            OrchestrationRepository(database).create_workflow_definition(
                requested_workflow,
                requested_steps,
            )
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert database_snapshot(observer) == before_rows
        assert os.stat(database).st_mtime_ns == before_mtime
    finally:
        observer.close()


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
            if self.fault == "run_insert" and normalized.startswith(
                "INSERT INTO ORCHESTRATOR_RUNS"
            ):
                raise sqlite3.OperationalError("injected run insert fault")
            if self.fault == "step_insert" and normalized.startswith(
                "INSERT INTO ORCHESTRATOR_STEPS"
            ):
                raise sqlite3.OperationalError("injected step insert fault")
            if self.fault == "summary_update" and normalized.startswith(
                "UPDATE ORCHESTRATOR_RUNS SET RESULT_SUMMARY_JSON"
            ):
                raise sqlite3.OperationalError("injected summary update fault")
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


@pytest.mark.parametrize(
    "fault",
    ["run_insert", "step_insert", "summary_update", "commit"],
)
def test_insert_update_and_commit_faults_fully_roll_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    repo, database = repository(tmp_path)
    real_connect = sqlite3.connect

    def faulty_connect(*args: object, **kwargs: object) -> FaultConnection:
        return FaultConnection(real_connect(*args, **kwargs), fault)

    monkeypatch.setattr(repository_module.sqlite3, "connect", faulty_connect)
    with pytest.raises(
        OrchestrationRepositoryError,
        match="workflow_definition_persistence_failed",
    ):
        repo.create_workflow_definition(workflow(), steps())
    monkeypatch.undo()
    with real_connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_runs"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM orchestrator_steps"
        ).fetchone()[0] == 0


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
            (canonical(document), row[0]),
        )
        connection.commit()


def assert_deep_load_rejected_without_writes(
    database: Path,
    *,
    workflow_key: str = "morning:2026-07-24",
) -> None:
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_rows = database_snapshot(observer)
        with pytest.raises(OrchestrationRepositoryError):
            OrchestrationRepository(database).load_workflow_definition(workflow_key)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert database_snapshot(observer) == before_rows
    finally:
        observer.close()


def _outer_extra(document: dict[str, object]) -> None:
    document["extra"] = None


def _outer_missing(document: dict[str, object]) -> None:
    document.pop("steps")


def _outer_version(document: dict[str, object]) -> None:
    document["schema_version"] = "unknown"


def _envelope_extra(document: dict[str, object]) -> None:
    document["workflow_definition"]["extra"] = None  # type: ignore[index]


def _envelope_missing(document: dict[str, object]) -> None:
    document["workflow_definition"].pop("projection")  # type: ignore[union-attr]


def _envelope_version(document: dict[str, object]) -> None:
    document["workflow_definition"]["schema_version"] = "unknown"  # type: ignore[index]


def _envelope_hash(document: dict[str, object]) -> None:
    document["workflow_definition"]["definition_sha256"] = "f" * 64  # type: ignore[index]


def _envelope_projection_type(document: dict[str, object]) -> None:
    document["workflow_definition"]["projection"] = []  # type: ignore[index]


def _step_summary_extra(document: dict[str, object]) -> None:
    document["steps"]["extra"] = {"events": []}  # type: ignore[index]


def _step_summary_missing(document: dict[str, object]) -> None:
    document["steps"].pop("collection")  # type: ignore[union-attr]


def _step_summary_event(document: dict[str, object]) -> None:
    document["steps"]["collection"]["events"].append({})  # type: ignore[index]


def _projection_unknown_key(document: dict[str, object]) -> None:
    document["workflow_definition"]["projection"]["unknown"] = None  # type: ignore[index]


@pytest.mark.parametrize(
    "mutation",
    [
        _outer_extra,
        _outer_missing,
        _outer_version,
        _envelope_extra,
        _envelope_missing,
        _envelope_version,
        _envelope_hash,
        _envelope_projection_type,
        _step_summary_extra,
        _step_summary_missing,
        _step_summary_event,
        _projection_unknown_key,
    ],
    ids=lambda mutation: mutation.__name__.removeprefix("_"),
)
def test_outer_envelope_and_non_domain_summary_tampering_fails_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    mutate_summary(database, mutation)
    assert_deep_load_rejected_without_writes(database)


@pytest.mark.parametrize("tamper", ["whitespace", "duplicate-key"])
def test_noncanonical_or_duplicate_outer_json_fails_closed(
    tmp_path: Path,
    tamper: str,
) -> None:
    repo, database = repository(tmp_path)
    created = repo.create_workflow_definition(workflow(), steps())
    raw = created.outer_summary_json
    if tamper == "whitespace":
        corrupted = " " + raw
    else:
        corrupted = raw.replace(
            "{",
            '{"schema_version":"step_summary_v2",',
            1,
        )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE orchestrator_runs SET result_summary_json=?",
            (corrupted,),
        )
        connection.commit()
    assert_deep_load_rejected_without_writes(database)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("workflow_kind", "weekly"),
        ("subject_id", 99),
        ("logical_local_date", "2026-07-25"),
        ("trigger_kind", "manual"),
        ("deadline_at_utc", "2026-07-24T04:00:00Z"),
        ("parent_workflow_run_id", 99),
        ("started_at_utc", "2026-07-24T02:00:01Z"),
        ("status", "failed"),
        ("completed_at_utc", "2026-07-24T02:00:01Z"),
    ],
)
def test_immutable_run_and_storage_column_tampering_fails_closed(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            f"UPDATE orchestrator_runs SET {column}=?",
            (value,),
        )
        connection.commit()
    assert_deep_load_rejected_without_writes(database)


@pytest.mark.parametrize(
    ("mutation", "parameters"),
    [
        (
            "DELETE FROM orchestrator_steps WHERE step_key=?",
            ("collection",),
        ),
        (
            "INSERT INTO orchestrator_steps "
            "(orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,"
            "request_sha256,status) "
            "SELECT id,'extra',3,5,'check',?,'pending' FROM orchestrator_runs",
            ("f" * 64,),
        ),
        (
            "UPDATE orchestrator_steps SET ordinal=CASE ordinal "
            "WHEN 0 THEN 1 WHEN 1 THEN 0 ELSE ordinal END",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET step_key='changed' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET layer_no=4 WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET tool_mode='repair' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET request_sha256=? "
            "WHERE step_key='collection'",
            ("f" * 64,),
        ),
        (
            "UPDATE orchestrator_steps SET invocation_id='changed' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET downstream_run_id='changed' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET status='running' "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET attempt_count=1 "
            "WHERE step_key='collection'",
            (),
        ),
        (
            "UPDATE orchestrator_steps SET receipt_sha256=? "
            "WHERE step_key='collection'",
            ("f" * 64,),
        ),
        (
            "UPDATE orchestrator_steps SET next_retry_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:30:00Z",),
        ),
        (
            "UPDATE orchestrator_steps SET started_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:00:00Z",),
        ),
        (
            "UPDATE orchestrator_steps SET completed_at_utc=? "
            "WHERE step_key='collection'",
            ("2026-07-24T02:00:00Z",),
        ),
    ],
    ids=[
        "missing-step",
        "extra-step",
        "reordered-ordinals",
        "step-key",
        "layer",
        "tool",
        "request-hash",
        "invocation",
        "downstream",
        "storage-state",
        "attempt",
        "receipt",
        "retry",
        "started",
        "completed",
    ],
)
def test_missing_extra_reordered_and_tampered_step_rows_fail_closed(
    tmp_path: Path,
    mutation: str,
    parameters: tuple[object, ...],
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    with sqlite3.connect(database) as connection:
        connection.execute(mutation, parameters)
        connection.commit()
    assert_deep_load_rejected_without_writes(database)


def _workflow_domain_state(document: dict[str, object]) -> None:
    projection = document["workflow_definition"]["projection"]  # type: ignore[index]
    projection["workflow"]["domain_state"] = "running"  # type: ignore[index]


def _step_domain_state(document: dict[str, object]) -> None:
    projection = document["workflow_definition"]["projection"]  # type: ignore[index]
    projection["steps"][1]["domain_state"] = "running"  # type: ignore[index]


def _projection_definition_hash(document: dict[str, object]) -> None:
    projection = document["workflow_definition"]["projection"]  # type: ignore[index]
    projection["definition_sha256"] = "f" * 64  # type: ignore[index]


def _projection_immutable_field(document: dict[str, object]) -> None:
    projection = document["workflow_definition"]["projection"]  # type: ignore[index]
    projection["workflow"]["create_command_sha256"] = "f" * 64  # type: ignore[index]


@pytest.mark.parametrize(
    "mutation",
    [
        _workflow_domain_state,
        _step_domain_state,
        _projection_definition_hash,
        _projection_immutable_field,
    ],
)
def test_domain_state_and_definition_hash_tampering_fails_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    mutate_summary(database, mutation)
    assert_deep_load_rejected_without_writes(database)


@pytest.mark.parametrize("operation", ["workflow", "step-create", "step-transition"])
def test_a1b_aggregate_refuses_transition_paths_reserved_for_a2(
    tmp_path: Path,
    operation: str,
) -> None:
    repo, database = repository(tmp_path)
    repo.create_workflow_definition(workflow(), steps())
    observer = sqlite3.connect(database)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_rows = database_snapshot(observer)
        if operation == "workflow":
            call = lambda: repo.transition_workflow(
                workflow().workflow_key,
                "succeeded",
                at_utc=STARTED + timedelta(seconds=1),
            )
        elif operation == "step-create":
            call = lambda: repo.create_step(
                workflow_key=workflow().workflow_key,
                step_key="extra",
                ordinal=3,
                layer_no=5,
                tool_mode="check",
                request_sha256="f" * 64,
            )
        else:
            call = lambda: repo.transition_step(
                workflow_key=workflow().workflow_key,
                step_key="collection",
                status="running",
                at_utc=STARTED,
            )
        with pytest.raises(
            OrchestrationRepositoryError,
            match="workflow_definition_transition_not_implemented",
        ):
            call()
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
        assert database_snapshot(observer) == before_rows
    finally:
        observer.close()


@pytest.mark.parametrize(
    ("workflow_state", "step_state"),
    [
        ("running", "pending"),
        ("succeeded", "pending"),
        ("queued", "running"),
        ("queued", "succeeded"),
    ],
)
def test_creation_accepts_only_initial_states_until_a2(
    tmp_path: Path,
    workflow_state: str,
    step_state: str,
) -> None:
    repo, database = repository(tmp_path)
    requested_steps = list(steps())
    requested_steps[0] = replace(
        requested_steps[0],
        domain_state=step_state,
    )
    with pytest.raises(StateProjectionError, match="initial_state_invalid"):
        repo.create_workflow_definition(
            workflow(domain_state=workflow_state),
            tuple(requested_steps),
        )
    with sqlite3.connect(database) as connection:
        assert database_snapshot(connection) == ([], [])
