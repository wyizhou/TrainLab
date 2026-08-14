from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from src.analysis.contracts import AnalysisRequest
from src.analysis.status import AnalysisStatusQueryService

NOW = "2026-07-26T00:00:00Z"


def request(run_key: str | None = None, subject: str = "subject_a") -> AnalysisRequest:
    return AnalysisRequest.from_dict(
        {
            "schema_version": "1",
            "mode": "status",
            "subject_id": subject,
            "invocation_id": None,
            "run_key": run_key,
            "summary_local_date": None,
            "advice_local_date": None,
            "as_of_local_date": None,
            "plan_id": None,
            "reason_event_id": None,
            "effective_local_date": None,
            "artifact_id": None,
            "delivery_id": None,
            "regeneration_reason_code": None,
            "requested_at_utc": NOW,
        }
    )


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, subject_key TEXT, is_active INTEGER);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY, run_key TEXT, subject_id INTEGER, status TEXT, started_at_utc TEXT, completed_at_utc TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY, subject_id INTEGER, artifact_kind TEXT, period_start_local_date TEXT, period_end_local_date TEXT, revision_no INTEGER, is_current INTEGER, user_visible_text TEXT, structured_content_json TEXT);
    CREATE TABLE training_plans(id INTEGER PRIMARY KEY, subject_id INTEGER, plan_start_local_date TEXT, plan_end_local_date TEXT, status TEXT, created_at_utc TEXT, objective_json TEXT, constraints_json TEXT);
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY, subject_id INTEGER, status TEXT, updated_at_utc TEXT, provider_message_id TEXT, provider_thread_id TEXT, error_summary TEXT, delivery_kind TEXT, created_at_utc TEXT);
    CREATE TABLE analysis_delivery_artifacts(analysis_delivery_id INTEGER, analysis_artifact_id INTEGER, ordinal INTEGER);
    CREATE TABLE data_quality_issues(id INTEGER PRIMARY KEY, entity_type TEXT, entity_id INTEGER, issue_code TEXT, severity TEXT, status TEXT, details_json TEXT);
    CREATE VIEW v_current_analysis_artifacts AS SELECT * FROM analysis_artifacts WHERE is_current=1;
    CREATE VIEW v_current_training_plans AS SELECT * FROM training_plans WHERE status IN ('proposed','active');
    CREATE VIEW v_open_data_quality_issues AS SELECT * FROM data_quality_issues WHERE status IN ('open','acknowledged');
    INSERT INTO data_subjects VALUES(1,'subject_a',1),(2,'subject_b',1);
    INSERT INTO analysis_runs VALUES
      (11,'analysis:subject_a:daily:2026-07-24:one',1,'succeeded','2026-07-25T00:00:00Z','2026-07-25T00:01:00Z'),
      (12,'analysis:subject_a:weekly:2026-07-25:two',1,'rejected','2026-07-26T00:00:00Z','2026-07-26T00:01:00Z'),
      (21,'analysis:subject_b:daily:2026-07-24:other',2,'failed','2026-07-26T01:00:00Z','2026-07-26T01:01:00Z');
    INSERT INTO analysis_artifacts VALUES
      (101,1,'daily_summary','2026-07-24','2026-07-24',2,1,'SECRET DAILY BODY','{"secret":"daily"}'),
      (102,1,'weekly_summary','2026-07-18','2026-07-24',1,1,'SECRET WEEKLY BODY','{"secret":"weekly"}'),
      (201,2,'daily_summary','2026-07-24','2026-07-24',1,1,'OTHER SUBJECT BODY','{"secret":"other"}');
    INSERT INTO training_plans VALUES
      (301,1,'2026-07-25','2026-07-31','active','2026-07-25T00:02:00Z','{"objective":"private"}','{"constraint":"private"}'),
      (401,2,'2026-07-25','2026-07-31','active','2026-07-25T00:02:00Z','{"objective":"other"}','{}');
    INSERT INTO analysis_deliveries VALUES
      (501,1,'failed','2026-07-26T00:02:00Z','provider-a','thread-a','SECRET DELIVERY ERROR','daily_report','2026-07-26T00:02:00Z'),
      (502,1,'delivery_unknown','2026-07-26T00:03:00Z','provider-new','thread-new','SECRET UNKNOWN ERROR','weekly_report','2026-07-26T00:03:00Z'),
      (601,2,'pending','2026-07-26T00:04:00Z','provider-b','thread-b','OTHER DELIVERY ERROR','daily_report','2026-07-26T00:04:00Z');
    INSERT INTO analysis_delivery_artifacts VALUES(501,101,0),(502,102,0),(601,201,0);
    INSERT INTO data_quality_issues VALUES
      (1,'analysis_run',12,'analysis_input_blocked','error','open','{"secret":"no"}'),
      (2,'analysis_run',21,'other_subject_blocker','error','open','{"secret":"other"}'),
      (3,'analysis_run',11,'ignored_warning','warning','open','{}');
    """)
    return conn


def test_status_is_select_only_and_returns_only_subject_safe_summary() -> None:
    conn = database()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    receipt = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(request())
    payload = receipt.as_dict()
    assert receipt.status == "succeeded" and receipt.next_action == "reconcile_delivery"
    assert payload["analysis_run_id"] == "12"
    snapshot = payload["status_snapshot"]
    assert snapshot == {
        "selected_run": {
            "id": "12",
            "run_key": "analysis:subject_a:weekly:2026-07-25:two",
            "status": "rejected",
            "started_at_utc": "2026-07-26T00:00:00Z",
            "completed_at_utc": "2026-07-26T00:01:00Z",
        },
        "current_artifacts": [
            {
                "id": "101",
                "kind": "daily_summary",
                "period_start_local_date": "2026-07-24",
                "period_end_local_date": "2026-07-24",
                "revision_no": 2,
            },
            {
                "id": "102",
                "kind": "weekly_summary",
                "period_start_local_date": "2026-07-18",
                "period_end_local_date": "2026-07-24",
                "revision_no": 1,
            },
        ],
        "current_plan": {
            "id": "301",
            "start_local_date": "2026-07-25",
            "end_local_date": "2026-07-31",
            "status": "active",
        },
        "latest_delivery": {"id": "502", "status": "delivery_unknown"},
        "delivery_counts": {"pending": 0, "delivery_unknown": 1, "failed": 1},
        "actionable_delivery_ids": {
            "retry_delivery": ["501"],
            "reconcile_delivery": ["502"],
        },
        "recent_terminal_at_utc": {
            "succeeded": "2026-07-25T00:01:00Z",
            "failed": None,
            "rejected": "2026-07-26T00:01:00Z",
            "deferred": None,
        },
        "quality_blocker_codes": ["analysis_input_blocked"],
        "deferred_history_supported": False,
    }
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    encoded = json.dumps(payload, sort_keys=True)
    for secret in (
        "SECRET",
        "provider-",
        "thread-",
        "private",
        "other_subject",
        "details_json",
        "objective_json",
        "structured_content_json",
        "user_visible_text",
    ):
        assert secret not in encoded
    receipt.validate()


def test_selected_absent_or_foreign_run_never_leaks_another_subject() -> None:
    conn = database()
    service = AnalysisStatusQueryService(conn, clock=lambda: NOW)
    absent = service.execute(request("analysis:subject_a:daily:2020-01-01:none"))
    foreign = service.execute(request("analysis:subject_b:daily:2026-07-24:other"))
    assert (
        absent.status_snapshot is not None
        and absent.status_snapshot["selected_run"] is None
    )
    assert (
        foreign.status_snapshot is not None
        and foreign.status_snapshot["selected_run"] is None
    )
    assert foreign.artifact_ids == ("101", "102")
    assert foreign.delivery is not None and foreign.delivery.delivery_id == "502"


def test_later_terminal_delivery_supersedes_only_retryable_older_delivery() -> None:
    conn = database()
    conn.execute(
        "INSERT INTO analysis_deliveries VALUES"
        "(503,1,'pending','2026-07-26T00:04:00Z',NULL,NULL,NULL,'plan_revision','2026-07-26T00:04:00Z'),"
        "(504,1,'sent','2026-07-26T00:05:00Z','provider-sent','thread-sent',NULL,'plan_revision','2026-07-26T00:05:00Z'),"
        "(505,1,'delivery_unknown','2026-07-26T00:01:00Z',NULL,NULL,'SECRET UNKNOWN','plan_revision','2026-07-26T00:01:00Z')"
    )
    receipt = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(request())
    snapshot = receipt.status_snapshot
    assert snapshot is not None
    assert snapshot["delivery_counts"] == {
        "pending": 0,
        "delivery_unknown": 2,
        "failed": 1,
    }
    assert snapshot["actionable_delivery_ids"] == {
        "retry_delivery": ["501"],
        "reconcile_delivery": ["502", "505"],
    }


def test_status_selects_latest_nonoverlapping_plan_and_rejects_overlap() -> None:
    conn = database()
    conn.execute(
        "INSERT INTO training_plans VALUES(302,1,'2026-08-01','2026-08-07','active',"
        "'2026-08-01T00:02:00Z','{}','{}')"
    )
    receipt = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(request())
    assert receipt.status == "succeeded"
    assert receipt.status_snapshot is not None
    assert receipt.status_snapshot["current_plan"] == {
        "id": "302",
        "start_local_date": "2026-08-01",
        "end_local_date": "2026-08-07",
        "status": "active",
    }

    conn.execute(
        "INSERT INTO training_plans VALUES(303,1,'2026-08-05','2026-08-11','active',"
        "'2026-08-05T00:02:00Z','{}','{}')"
    )
    failed = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(request())
    assert failed.status == "failed"
    assert failed.errors[0].code == "analysis_status_unavailable"


def test_status_schema_requires_bounded_snapshot_and_failure_is_redacted() -> None:
    conn = database()
    receipt = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(request())
    receipt.validate()
    bad = dict(receipt.status_snapshot or {})
    bad["deferred_history_supported"] = True
    try:
        replace(receipt, status_snapshot=bad).validate()
    except Exception as error:
        assert "analysis_receipt_schema_invalid" in str(error)
    else:
        raise AssertionError(
            "status snapshot contract accepted an unsupported deferred history"
        )
    failed = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(
        request(subject="unknown")
    )
    assert (
        failed.status == "failed"
        and failed.errors[0].summary == "analysis status is unavailable"
    )
    assert (
        failed.status_snapshot is not None
        and failed.status_snapshot["selected_run"] is None
    )


def test_status_module_has_no_forbidden_runtime_capability_imports() -> None:
    source = open("src/analysis/status.py", encoding="utf-8").read()
    for forbidden in (
        "runner",
        "gmail",
        "context",
        "harness",
        "lock",
        "Codex",
        "Gmail",
    ):
        assert f".{forbidden}" not in source
