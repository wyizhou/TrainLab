from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _state(tmp_path: Path):
    state = _module(ROOT / "skills/_shared/state.py", "m8_state_contract")
    return state, state.init_database(tmp_path / "state" / "trainlab.db")


def test_invalid_daily_evidence_ref_is_blocked_and_recorded(tmp_path: Path) -> None:
    state, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_daily_contract",
    )
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "safety": "ready",
        "summary": "bounded",
        "bounded_metrics": [
            {"name": "rhr", "value": 50, "unit": "bpm", "evidence_ref": 999}
        ],
        "stop_conditions": ["出现红旗时停止。"],
        "evidence_refs": [{"raw_file_id": 1, "sha256": "0" * 64, "claim": "rhr"}],
        "provider_calls": 0,
    }
    context = {
        "status": "ready",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "health": [{"raw_file_id": 1, "metrics": {"resource": "rhr"}}],
        "activities": [],
    }
    result = commit.commit(payload, context, database, "daily")
    assert result["status"] == "blocked"
    assert "ai_evidence_ref_invalid" in result["errors"]
    connection = state.connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status,error_code FROM skill_runs WHERE workflow_key='daily:2026-08-12'"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("blocked", "ai_evidence_ref_invalid")


def test_weekly_evidence_must_be_one_of_exact_daily_inputs(tmp_path: Path) -> None:
    _state_module, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_weekly_contract",
    )
    workflow = _module(
        ROOT / "skills/_shared/scripts/offline_workflow.py", "m8_workflow_plan"
    )
    daily = [{"report_date": f"2026-08-{day:02d}"} for day in range(3, 10)]
    plan = workflow._weekly_plan(date(2026, 8, 10), daily)
    payload = {
        "schema_version": "weekly_ai_result_v1",
        "status": "succeeded",
        "period": "2026-08-03/2026-08-09",
        "daily_input_sha256": ["a" * 64] * 7,
        "summary": "bounded",
        "goal_sha256": "b" * 64,
        "evidence_refs": [{"output_id": 999, "sha256": "c" * 64, "claim": "unrelated"}],
        "training_plan": plan,
        "provider_calls": 0,
    }
    context = {
        "status": "ready",
        "period": "2026-08-03/2026-08-09",
        "daily_reports": [
            {"output_id": day, "sha256": "a" * 64, "content": {}} for day in range(1, 8)
        ],
    }
    result = commit.commit(payload, context, database, "weekly")
    assert result["status"] == "blocked"
    assert "weekly_evidence_ref_invalid" in result["errors"]


def test_segment_budget_excludes_main_daily_run(tmp_path: Path) -> None:
    state, database = _state(tmp_path)
    connection = state.connect(database)
    try:
        run_id = state.begin_run(
            connection,
            run_key="main-daily",
            workflow_key="daily:2026-08-12",
            dedupe_key="main-daily",
            skill_name="training-coach",
            operation="daily_coach",
            trigger_kind="skill",
            input_manifest={"mode": "daily"},
        )
        state.finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    sys.path.insert(0, str(ROOT / "skills/training-coach/scripts"))
    segment = _module(
        ROOT / "skills/training-coach/scripts/activity_segment.py",
        "m8_activity_segment_contract",
    )
    assert segment._budget(database, "daily:2026-08-12") == (0, 0)


def test_segment_lock_contention_is_recorded_as_stable_blocked_result(
    tmp_path: Path, monkeypatch
) -> None:
    state, database = _state(tmp_path)
    segment = _module(
        ROOT / "skills/training-coach/scripts/activity_segment.py",
        "m8_activity_segment_lock_contract",
    )

    segment._expected_workflow_key = lambda _database, _inventory_id: "daily:2026-08-12"

    @contextmanager
    def unavailable(_database):
        raise RuntimeError("state_lock_unavailable")
        yield

    monkeypatch.setattr(segment, "workflow_lock", unavailable)
    result = segment.read_segment(
        database,
        tmp_path / "source",
        1,
        0,
        30,
        5,
        "validator",
        "daily:2026-08-12",
    )
    assert result == {
        "schema_version": "activity_segment_v1",
        "status": "blocked",
        "error_code": "state_lock_unavailable",
        "workflow_key": "daily:2026-08-12",
        "activity_inventory_id": 1,
        "reason_code": "validator",
        "provider_calls": 0,
    }
    connection = state.connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status,error_code FROM skill_runs "
            "WHERE workflow_key='daily:2026-08-12'"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("blocked", "state_lock_unavailable")


def test_blocked_context_is_persisted_without_an_ai_payload(tmp_path: Path) -> None:
    state, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_blocked_context",
    )
    result = commit.commit(
        {},
        {
            "status": "blocked",
            "report_date": "2026-08-16",
            "review_date": "2026-08-15",
            "errors": ["daily_review_and_sleep_evidence_missing"],
        },
        database,
        "daily",
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "daily_review_and_sleep_evidence_missing"
    connection = state.connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status,error_code FROM skill_runs "
            "WHERE workflow_key='daily:2026-08-16'"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("blocked", "daily_review_and_sleep_evidence_missing")


def test_daily_metric_units_allow_deterministic_seconds_conversion(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_unit_conversion",
    )
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "safety": "ready",
        "summary": "bounded",
        "bounded_metrics": [
            {
                "name": "climbing_duration",
                "value": 153.683,
                "unit": "min",
                "evidence_ref": 1,
            }
        ],
        "stop_conditions": ["出现红旗时停止。"],
        "evidence_refs": [{"raw_file_id": 1, "sha256": "0" * 64, "claim": "climbing"}],
        "provider_calls": 0,
    }
    context = {
        "status": "ready",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "health": [],
        "activities": [{"raw_file_id": 1, "summary": {"duration_seconds": 9221}}],
    }
    commit._raw_sha_map = lambda _database: {1: "0" * 64}
    errors = commit._validate_daily(payload, context, database)
    assert "ai_metric_not_in_evidence" not in errors


def test_daily_metric_cannot_borrow_value_from_another_raw_file(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_evidence_binding",
    )
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "safety": "ready",
        "summary": "bounded",
        "bounded_metrics": [
            {"name": "rhr", "value": 90, "unit": "bpm", "evidence_ref": 1}
        ],
        "stop_conditions": ["出现红旗时停止。"],
        "evidence_refs": [{"raw_file_id": 1, "sha256": "0" * 64, "claim": "rhr"}],
        "recent_trend_sha256": "a" * 64,
        "provider_calls": 0,
    }
    context = {
        "status": "ready",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "health": [
            {
                "raw_file_id": 1,
                "metrics": {"resource": "rhr", "resting_heart_rate_bpm": 50},
            },
            {
                "raw_file_id": 2,
                "metrics": {"resource": "rhr", "resting_heart_rate_bpm": 90},
            },
        ],
        "activities": [],
        "recent_trend": {"sha256": "a" * 64},
    }
    commit._raw_sha_map = lambda _database: {1: "0" * 64, 2: "1" * 64}
    errors = commit._validate_daily(payload, context, database)
    assert "ai_metric_not_in_evidence" in errors


def test_weekly_goal_hash_and_invalid_plan_are_blocked_and_recorded(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    commit = _module(
        ROOT / "skills/training-coach/scripts/commit_ai_result.py",
        "m8_commit_weekly_lineage",
    )
    payload = {
        "schema_version": "weekly_ai_result_v1",
        "status": "succeeded",
        "period": "2026-08-03/2026-08-09",
        "daily_input_sha256": ["a" * 64] * 7,
        "summary": "bounded",
        "goal_sha256": "b" * 64,
        "evidence_refs": [{"output_id": 1, "sha256": "a" * 64, "claim": "daily"}],
        "training_plan": {},
        "provider_calls": 0,
    }
    context = {
        "status": "ready",
        "period": "2026-08-03/2026-08-09",
        "daily_reports": [{"output_id": 1, "sha256": "a" * 64}],
        "goal": {"sha256": "c" * 64},
    }
    result = commit.commit(payload, context, database, "weekly")
    assert result["status"] == "blocked"
    assert "weekly_goal_sha_mismatch" in result["errors"]
    assert "training_plan_invalid" in result["errors"]
    connection = state.connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status,error_code FROM skill_runs WHERE workflow_key=?",
            ("weekly:2026-08-09",),
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("blocked", "training_plan_invalid")
