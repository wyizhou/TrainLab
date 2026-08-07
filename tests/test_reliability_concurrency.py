"""Threaded ownership races against unique disposable SQLite databases."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration.repository import (
    OrchestrationRepository,
    OrchestrationRepositoryError,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _database(tmp_path: Path) -> Path:
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
            FoundationRequest("init", "reliability-concurrency", "2026-08-07T00:00:00Z")
        )
        .ready
    )
    return config.database_path


def test_competing_writers_have_exactly_one_workflow_owner(tmp_path: Path) -> None:
    database = _database(tmp_path)
    barrier = Barrier(2)

    def claim(owner: str) -> str:
        barrier.wait(timeout=5)
        try:
            OrchestrationRepository(database).create_workflow(
                workflow_key="morning:competing-owner",
                workflow_kind="morning",
                trigger_kind="scheduled",
                started_at_utc=NOW,
            )
        except (OrchestrationRepositoryError, sqlite3.OperationalError) as exc:
            return str(exc)
        return owner

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = tuple(workers.map(claim, ("owner-a", "owner-b")))

    owners = [result for result in results if result in {"owner-a", "owner-b"}]
    assert len(owners) == 1
    assert len(set(results)) == 2
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT workflow_key,status FROM orchestrator_runs "
            "WHERE workflow_key='morning:competing-owner'"
        ).fetchall()
    assert rows == [("morning:competing-owner", "started")]


def test_resource_busy_leaves_no_partial_effect_and_exposes_current_defect(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    blocker = sqlite3.connect(database, timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            OrchestrationRepository(database).create_workflow(
                workflow_key="morning:resource-busy",
                workflow_kind="morning",
                trigger_kind="scheduled",
                started_at_utc=NOW,
            )
    finally:
        blocker.rollback()
        blocker.close()

    assert (
        OrchestrationRepository(database).get_workflow("morning:resource-busy") is None
    )
