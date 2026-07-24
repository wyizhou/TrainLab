from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminRepository,
    SyncReceipt,
    SyncRequest,
)

from .garmin_fakes import DeterministicClock, FakeGarminTransport


def _setup(tmp_path: Path) -> tuple[GarminConfig, GarminCollectionTool]:
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "receipt.json",
        root / "state" / "locks" / "foundation.lock",
    )
    FoundationTool(foundation).execute(
        FoundationRequest("init", "fixture", "2026-01-01T00:00:00Z")
    )
    fit = (Path(__file__).parents[1] / "test_data/new/Running.fit").read_bytes()
    config = GarminConfig(
        foundation.database_path,
        foundation.raw_root,
        foundation.state_root,
        "2026-04-15",
    )
    tool = GarminCollectionTool(
        config,
        FakeGarminTransport(fit),
        sleep=lambda _: None,
        clock=DeterministicClock(datetime(2026, 4, 17)),
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool


def _new_run(
    repository: GarminRepository,
    connection: sqlite3.Connection,
    subject_id: int,
    invocation_id: str,
) -> int:
    receipt = SyncReceipt(mode="incremental")
    return repository.start_run(
        connection,
        SyncRequest("incremental", invocation_id=invocation_id),
        subject_id,
        receipt,
    )


def test_interrupted_item_recovers_without_duplicate_run(tmp_path: Path) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    subject = repository.subject(connection)
    run = _new_run(repository, connection, subject, "resume")
    repository.item(connection, run, "steps", "day-1", "fetch", "pending")
    repository.item(connection, run, "steps", "day-1", "fetch", "running")
    connection.execute(
        """UPDATE garmin_sync_items
           SET next_retry_at_utc='2026-04-18T00:00:00Z'
           WHERE garmin_sync_run_id=?""",
        (run,),
    )

    replay = SyncReceipt(mode="incremental")
    same_run = repository.start_run(
        connection,
        SyncRequest("incremental", invocation_id="resume"),
        subject,
        replay,
    )
    item = connection.execute(
        """SELECT status,completed_at_utc,next_retry_at_utc
           FROM garmin_sync_items WHERE garmin_sync_run_id=?""",
        (run,),
    ).fetchone()
    assert same_run == run
    assert tuple(item) == ("pending", None, None)
    assert (
        connection.execute(
            "SELECT count(*) FROM garmin_sync_runs WHERE invocation_id='resume'"
        ).fetchone()[0]
        == 1
    )

    repository.item(connection, run, "steps", "day-1", "fetch", "running")
    active = connection.execute(
        "SELECT completed_at_utc FROM garmin_sync_items WHERE garmin_sync_run_id=?",
        (run,),
    ).fetchone()
    assert active[0] is None
    repository.item(connection, run, "steps", "day-1", "fetch", "fetched")
    terminal = connection.execute(
        "SELECT completed_at_utc FROM garmin_sync_items WHERE garmin_sync_run_id=?",
        (run,),
    ).fetchone()
    assert terminal[0] is not None
    with pytest.raises(ValueError, match="invalid_item_transition"):
        repository.item(connection, run, "steps", "day-1", "fetch", "pending")
    connection.close()


def test_completed_invocation_replays_full_receipt_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tool = _setup(tmp_path)
    request = SyncRequest(
        "incremental",
        through_local_date="2026-04-15",
        invocation_id="completed",
    )
    first = tool.execute(request)

    def unexpected_network() -> None:
        raise AssertionError("completed replay attempted provider access")

    monkeypatch.setattr(tool.transport, "login", unexpected_network)
    monkeypatch.setattr(tool.transport, "identity", unexpected_network)
    second = tool.execute(request)
    assert asdict(second) == asdict(first)


def test_generated_invocation_is_shared_by_lock_and_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, tool = _setup(tmp_path)
    original = tool._execute_locked
    observed: dict[str, object] = {}

    def inspect_lock(request: SyncRequest, receipt: SyncReceipt) -> SyncReceipt:
        lock = config.state_root / "locks" / "garmin.lock"
        observed.update(json.loads(lock.read_text(encoding="utf-8")))
        observed["request_invocation_id"] = request.invocation_id
        return original(request, receipt)

    monkeypatch.setattr(tool, "_execute_locked", inspect_lock)
    result = tool.execute(
        SyncRequest("incremental", through_local_date="2026-04-15")
    )
    with sqlite3.connect(config.database_path) as connection:
        persisted = connection.execute(
            "SELECT invocation_id FROM garmin_sync_runs WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0]
    assert observed["invocation_id"]
    assert observed["invocation_id"] == observed["request_invocation_id"] == persisted
    assert observed["pid"] == os.getpid()


def test_stale_lock_recovery_requires_dead_pid_and_no_active_run(
    tmp_path: Path,
) -> None:
    config, tool = _setup(tmp_path)
    lock = config.state_root / "locks" / "garmin.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)

    lock.write_text(
        json.dumps({"pid": os.getpid(), "invocation_id": "live"}),
        encoding="utf-8",
    )
    assert tool._recover_stale_lock(lock) is False
    assert lock.exists()

    lock.write_text("{invalid", encoding="utf-8")
    assert tool._recover_stale_lock(lock) is False
    assert lock.exists()

    repository = GarminRepository(config)
    connection = repository.connect()
    subject = repository.subject(connection)
    _new_run(repository, connection, subject, "active")
    connection.close()
    lock.write_text(
        json.dumps({"pid": 999_999_999, "invocation_id": "active"}),
        encoding="utf-8",
    )
    assert tool._recover_stale_lock(lock) is False
    assert lock.exists()

    lock.write_text(
        json.dumps({"pid": 999_999_999, "invocation_id": "orphan"}),
        encoding="utf-8",
    )
    assert tool._recover_stale_lock(lock) is True
    assert not lock.exists()


def test_status_is_read_only(tmp_path: Path) -> None:
    config, tool = _setup(tmp_path)
    before_bytes = config.database_path.read_bytes()
    before_mtime = config.database_path.stat().st_mtime_ns
    assert tool.execute(SyncRequest("status")).status == "succeeded"
    assert config.database_path.read_bytes() == before_bytes
    assert config.database_path.stat().st_mtime_ns == before_mtime


def test_gap_capability_and_continuous_cursor_state_machines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    subject = repository.subject(connection)
    run = _new_run(repository, connection, subject, "state-machines")

    times = iter(
        (
            "2026-04-15T00:00:00Z",
            "2026-04-16T00:00:00Z",
            "2026-04-17T00:00:00Z",
        )
    )
    monkeypatch.setattr("trainlab.garmin.utc_now", lambda: next(times))
    repository.capability(connection, subject, "steps", "supported")
    repository.capability(
        connection,
        subject,
        "steps",
        "not_enabled",
        reason="user_disabled",
        next_probe="2026-04-20T00:00:00Z",
    )
    repository.capability(connection, subject, "steps", "supported")
    capability = connection.execute(
        """SELECT capability_state,reason_code,first_checked_at_utc,
                  last_checked_at_utc,next_probe_at_utc
           FROM garmin_resource_capabilities
           WHERE subject_id=? AND resource_kind='steps'""",
        (subject,),
    ).fetchone()
    assert tuple(capability) == (
        "supported",
        None,
        "2026-04-15T00:00:00Z",
        "2026-04-17T00:00:00Z",
        None,
    )

    monkeypatch.undo()
    repository.coverage(connection, subject, "steps", "2026-04-15", "fetched", None, 1)
    repository.coverage(connection, subject, "steps", "2026-04-16", "partial", None, 1)
    repository.coverage(connection, subject, "steps", "2026-04-17", "fetched", None, 1)
    repository.advance_cursor(connection, subject, "steps", "2026-04-17", run)
    cursor = connection.execute(
        """SELECT complete_through_local_date FROM garmin_sync_cursors
           WHERE subject_id=? AND resource_kind='steps'""",
        (subject,),
    ).fetchone()
    assert cursor[0] == "2026-04-15"

    repository.coverage(connection, subject, "steps", "2026-04-16", "fetched", None, 1)
    repository.gap(
        connection,
        subject,
        "steps",
        "range-gap",
        "2026-04-16",
        "fetch",
        "provider_error",
        deferred=True,
    )
    repository.advance_cursor(connection, subject, "steps", "2026-04-17", run)
    assert (
        connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE subject_id=? AND resource_kind='steps'""",
            (subject,),
        ).fetchone()[0]
        == "2026-04-15"
    )

    repository.resolve_gaps(connection, subject, "steps", "2026-04-16")
    repository.advance_cursor(connection, subject, "steps", "2026-04-17", run)
    assert (
        connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE subject_id=? AND resource_kind='steps'""",
            (subject,),
        ).fetchone()[0]
        == "2026-04-17"
    )
    resolved = connection.execute(
        """SELECT status,resolved_at_utc FROM garmin_sync_gaps
           WHERE logical_object_key='range-gap'"""
    ).fetchone()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at_utc"] is not None

    repository.coverage(connection, subject, "steps", "2026-04-19", "fetched", None, 1)
    repository.advance_cursor(connection, subject, "steps", "2026-04-19", run)
    assert (
        connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE subject_id=? AND resource_kind='steps'""",
            (subject,),
        ).fetchone()[0]
        == "2026-04-17"
    )

    repository.coverage(connection, subject, "stress", "2026-04-15", "error", None, 0)
    repository.advance_cursor(connection, subject, "stress", "2026-04-15", run)
    assert (
        connection.execute(
            """SELECT count(*) FROM garmin_sync_cursors
               WHERE subject_id=? AND resource_kind='stress'""",
            (subject,),
        ).fetchone()[0]
        == 0
    )
    connection.close()
