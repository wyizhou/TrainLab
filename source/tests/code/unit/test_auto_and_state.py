from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
from skills._shared.scripts.resolve_slot import resolve_due, resolve_slot  # noqa: E402
from skills._shared.scripts.schema_validation import validate_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    init_database,
    record_skill_result,
)

HKT = ZoneInfo("Asia/Hong_Kong")


def test_noon_slot_boundaries_and_sunday_weekly() -> None:
    before = resolve_slot(datetime(2026, 8, 16, 11, 59, 59, tzinfo=HKT))
    at_noon = resolve_slot(datetime(2026, 8, 16, 12, 0, tzinfo=HKT))
    monday_before = resolve_slot(datetime(2026, 8, 17, 11, 59, 59, tzinfo=HKT))
    monday_noon = resolve_slot(datetime(2026, 8, 17, 12, 0, tzinfo=HKT))
    assert before.slot_date == "2026-08-15"
    assert at_noon.slot_date == "2026-08-16"
    assert at_noon.workflow_keys == ("daily:2026-08-16", "weekly:2026-08-16")
    assert monday_before.workflow_keys == at_noon.workflow_keys
    assert monday_noon.workflow_keys == ("daily:2026-08-17",)
    assert at_noon.slot_end == (datetime(2026, 8, 17, 12, tzinfo=HKT)).isoformat()


def test_missing_database_fails_closed(tmp_path: Path) -> None:
    result = resolve_due(tmp_path / "missing.db", datetime(2026, 8, 16, 12, tzinfo=HKT))
    assert result["status"] == "blocked"
    assert result["error_code"] == "state_missing"


def test_complete_receipt_makes_slot_no_due(tmp_path: Path) -> None:
    database = init_database(tmp_path / "state" / "trainlab.db")
    record_skill_result(
        database,
        skill_name="gmail-sender",
        operation="send_email",
        output_kind="execution_summary",
        logical_key="workflow:daily:2026-08-16",
        payload={
            "schema_version": "workflow_receipt_v1",
            "workflow_key": "daily:2026-08-16",
            "status": "succeeded",
            "outcome": "daily_complete",
            "provider_calls": 0,
        },
    )
    result = resolve_due(database, datetime(2026, 8, 16, 13, 0, tzinfo=HKT))
    assert result["outcome"] == "weekly_due"
    record_skill_result(
        database,
        skill_name="gmail-sender",
        operation="send_email",
        output_kind="execution_summary",
        logical_key="workflow:weekly:2026-08-16",
        payload={
            "schema_version": "workflow_receipt_v1",
            "workflow_key": "weekly:2026-08-16",
            "status": "succeeded",
            "outcome": "daily_weekly_complete",
            "provider_calls": 0,
        },
    )
    assert (
        resolve_due(database, datetime(2026, 8, 16, 13, 0, tzinfo=HKT))["outcome"]
        == "no_due"
    )


def _run(connection: sqlite3.Connection, key: str = "run") -> int:
    return begin_run(
        connection,
        run_key=f"{key}:attempt-1",
        workflow_key="daily:2026-08-16",
        dedupe_key=key,
        skill_name="training-coach",
        operation="daily_coach",
        trigger_kind="manual",
        input_manifest={"key": key},
    )


def test_recursive_triggers_and_replace_cannot_overwrite_output(tmp_path: Path) -> None:
    database = init_database(tmp_path / "state" / "trainlab.db")
    connection = connect(database)
    assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
    run_id = _run(connection, "replace")
    output_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="daily_summary",
        logical_key="replace-output",
        schema_name="daily_summary_v1",
        schema_version="1",
        title_text="original",
        content_json={"value": 1},
        content_text="original",
        lineage=[],
    )
    original = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
    ).fetchone()[0]
    replacement = hashlib.sha256(b"replacement").hexdigest()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT OR REPLACE INTO skill_outputs
               (id,skill_run_id,output_kind,logical_key,revision_no,schema_name,schema_version,
                title_text,content_json,content_text,lineage_json,content_sha256,created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                output_id,
                run_id,
                "daily_summary",
                "replace-output",
                1,
                "daily_summary_v1",
                "1",
                "changed",
                json.dumps({"value": 2}),
                "changed",
                "[]",
                replacement,
                "2026-08-16T00:00:00Z",
            ),
        )
    assert connection.execute("SELECT COUNT(*) FROM skill_outputs").fetchone()[0] == 1
    assert (
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
        ).fetchone()[0]
        == original
    )
    connection.close()


def test_failed_run_gets_a_new_attempt_but_success_reuses(tmp_path: Path) -> None:
    database = init_database(tmp_path / "state" / "trainlab.db")
    connection = connect(database)
    first = _run(connection, "retry")
    finish_run(connection, first, status="failed", error_code="test_failure")
    second = _run(connection, "retry")
    assert second != first
    assert (
        connection.execute(
            "SELECT attempt_no FROM skill_runs WHERE id=?", (second,)
        ).fetchone()[0]
        == 2
    )
    finish_run(connection, second, status="succeeded")
    third = _run(connection, "retry")
    assert third == second
    connection.close()


def test_run_identity_is_frozen_and_lease_is_recorded(tmp_path: Path) -> None:
    database = init_database(tmp_path / "state" / "trainlab.db")
    connection = connect(database)
    run_id = _run(connection, "identity")
    lease = connection.execute(
        "SELECT lease_expires_at_utc FROM skill_runs WHERE id=?", (run_id,)
    ).fetchone()[0]
    assert lease is not None
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE skill_runs SET workflow_key='weekly:2026-08-16' WHERE id=?",
            (run_id,),
        )
    connection.close()


def test_schema_rejects_invalid_dates_and_unbounded_raw_fields() -> None:
    evidence = {
        "schema_version": "bounded_evidence_v1",
        "status": "ready",
        "window": {"from_date": "2026-99-99", "through_date": "2026-08-16"},
        "evidence": [
            {
                "relative_path": "state/raw/garmin/health/20260816-sleep.json",
                "data_date": "2026-08-16",
                "format": "json",
                "bytes": 1,
                "sha256": "0" * 64,
                "evidence": {"parser": "json", "raw_points": [1, 2, 3]},
            }
        ],
        "file_count": 1,
        "raw_values_included": False,
        "provider_calls": 0,
    }
    errors = validate_payload(evidence, "bounded_evidence_v1")
    assert any("additionalProperties" in error for error in errors)
    assert any("format" in error for error in errors)


def test_successful_daily_requires_bounded_metrics() -> None:
    payload = {
        "schema_version": "daily_summary_v1",
        "status": "succeeded",
        "report_date": "2026-08-16",
        "review_date": "2026-08-15",
        "sleep_wake_date": "2026-08-16",
        "summary": "x",
        "safety": "ready",
        "provider_calls": 0,
    }
    assert any(
        "required" in error for error in validate_payload(payload, "daily_summary_v1")
    )


def test_embedded_workflow_dates_reject_impossible_calendar_days() -> None:
    weekly = {
        "schema_version": "weekly_fitness_review_v1",
        "status": "succeeded",
        "period": "2026-02-31/2026-03-07",
        "daily_summary_count": 7,
        "evidence_consistency": "verified",
        "provider_calls": 0,
    }
    receipt = {
        "schema_version": "workflow_receipt_v1",
        "status": "succeeded",
        "outcome": "daily_complete",
        "workflow_key": "daily:2026-02-31",
        "provider_calls": 0,
    }
    auto = {
        "schema_version": "auto_result_v1",
        "status": "succeeded",
        "outcome": "no_due",
        "timezone": "Asia/Hong_Kong",
        "observed_at_hk": "2026-08-16T12:00:00+08:00",
        "slot_date": "2026-08-16",
        "slot_start": "2026-08-16T12:00:00+08:00",
        "slot_end": "2026-08-17T12:00:00+08:00",
        "workflow_refs": ["daily:2026-02-31"],
        "skill_run_ids": [],
        "output_ids": [],
        "external_action_ids": [],
        "provider_calls": 0,
        "next_slot_at": "2026-08-17T12:00:00+08:00",
        "warnings": [],
    }
    assert any(
        "date" in error
        for error in validate_payload(weekly, "weekly_fitness_review_v1")
    )
    assert any(
        "date" in error for error in validate_payload(receipt, "workflow_receipt_v1")
    )
    assert any("date" in error for error in validate_payload(auto, "auto_result_v1"))
