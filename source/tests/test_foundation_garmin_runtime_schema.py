from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.foundation import (
    FoundationConfig,
    FoundationRequest,
    FoundationTool,
    validate_schema_manifest,
)

UTC = "2026-07-23T00:00:00Z"
RUNTIME_TABLES = {
    "garmin_sync_runs",
    "garmin_sync_items",
    "garmin_sync_cursors",
    "garmin_sync_gaps",
    "garmin_resource_capabilities",
}


def tool(root: Path) -> FoundationTool:
    return FoundationTool(
        FoundationConfig(
            root,
            root / "data.db",
            root / "raw",
            root / "state",
            root / "state" / "foundation-ready.json",
            root / "state" / "locks" / "foundation.lock",
        )
    )


def database(tmp_path: Path) -> sqlite3.Connection:
    root = tmp_path / "foundation"
    assert (
        tool(root).execute(FoundationRequest("init", "garmin-schema", UTC)).status
        == "initialized"
    )
    db = sqlite3.connect(root / "data.db")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('synthetic-subject',?)",
        (UTC,),
    )
    return db


def test_foundation_creates_but_never_populates_layer_two_runtime_tables(
    tmp_path: Path,
) -> None:
    root = tmp_path / "foundation"
    instance = tool(root)
    assert (
        instance.execute(FoundationRequest("init", "garmin-empty", UTC)).status
        == "initialized"
    )
    db = sqlite3.connect(root / "data.db")
    try:
        assert RUNTIME_TABLES <= {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in RUNTIME_TABLES
        } == {name: 0 for name in RUNTIME_TABLES}
    finally:
        db.close()


def test_garmin_runtime_idempotency_stage_cursor_gap_and_capability_contracts(
    tmp_path: Path,
) -> None:
    db = database(tmp_path)
    try:
        subject = db.execute("SELECT id FROM data_subjects").fetchone()[0]
        db.execute(
            "INSERT INTO garmin_sync_runs(run_id,invocation_id,subject_id,mode,resource_catalog_version,collector_version,status,started_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            (
                "run-1",
                "invoke-1",
                subject,
                "incremental",
                "catalog-1",
                "collector-1",
                "started",
                UTC,
            ),
        )
        run = db.execute("SELECT id FROM garmin_sync_runs").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_sync_runs(run_id,invocation_id,subject_id,mode,resource_catalog_version,collector_version,status,started_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                (
                    "run-2",
                    "invoke-1",
                    subject,
                    "incremental",
                    "catalog-1",
                    "collector-1",
                    "started",
                    UTC,
                ),
            )
        db.execute(
            "INSERT INTO garmin_sync_items(garmin_sync_run_id,resource_kind,logical_object_key,stage,status) VALUES(?,?,?,?,?)",
            (run, "daily_health", "2026-07-22", "fetch", "fetched"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_sync_items(garmin_sync_run_id,resource_kind,logical_object_key,stage,status) VALUES(?,?,?,?,?)",
                (run, "daily_health", "2026-07-22", "fetch", "fetched"),
            )
        db.execute(
            "INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,complete_through_local_date,catalog_version) VALUES(?,?,?,?,?)",
            (subject, "daily_health", "local_date", "2026-07-22", "catalog-1"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,complete_through_local_date,catalog_version) VALUES(?,?,?,?,?)",
                (subject, "daily_health", "local_date", "2026-07-22", "catalog-1"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,catalog_version) VALUES(?,?,?,?)",
                (subject, "sleep", "attempt", "catalog-1"),
            )
        gap = (
            subject,
            "daily_health",
            "2026-07-22",
            "2026-07-22",
            "2026-07-22",
            "fetch",
            "network",
            "open",
            UTC,
        )
        db.execute(
            "INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,first_seen_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
            gap,
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,first_seen_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                (*gap[:-2], "deferred", UTC),
            )
        db.execute(
            "UPDATE garmin_sync_gaps SET status='resolved',resolved_at_utc=?", (UTC,)
        )
        db.execute(
            "INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,first_seen_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
            gap,
        )
        db.execute(
            "INSERT INTO garmin_resource_capabilities(subject_id,environment_key,resource_kind,capability_state,first_checked_at_utc,last_checked_at_utc) VALUES(?,?,?,?,?,?)",
            (subject, "account-1", "daily_health", "supported", UTC, UTC),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO garmin_resource_capabilities(subject_id,environment_key,resource_kind,capability_state,first_checked_at_utc,last_checked_at_utc) VALUES(?,?,?,?,?,?)",
                (subject, "account-1", "daily_health", "invalid", UTC, UTC),
            )
    finally:
        db.close()


def test_runtime_tables_are_manifest_validated(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    instance = tool(root)
    assert (
        instance.execute(FoundationRequest("init", "garmin-manifest", UTC)).status
        == "initialized"
    )
    db = sqlite3.connect(root / "data.db")
    try:
        manifest = instance._manifest()
        assert RUNTIME_TABLES <= set(manifest["tables"])
        assert validate_schema_manifest(db, manifest) == []
    finally:
        db.close()
