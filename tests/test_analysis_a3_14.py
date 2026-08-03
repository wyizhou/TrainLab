from __future__ import annotations

import sqlite3
from hashlib import sha256
import json

import pytest

from trainlab.analysis.delivery import (
    AnalysisDeliveryError,
    AnalysisDeliveryFactory,
    render_delivery,
)
from trainlab.analysis.publisher import AnalysisPublisher


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT NOT NULL,subject_id INTEGER NOT NULL,analysis_kind TEXT NOT NULL,status TEXT NOT NULL,harness_version TEXT,input_schema_version TEXT,output_schema_version TEXT,context_snapshot_json TEXT,context_snapshot_sha256 TEXT,generator_metadata_json TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY,subject_id INTEGER NOT NULL,artifact_kind TEXT NOT NULL,period_start_local_date TEXT NOT NULL,period_end_local_date TEXT NOT NULL,revision_no INTEGER NOT NULL,generated_by_run_id INTEGER NOT NULL,schema_version TEXT NOT NULL,structured_content_json TEXT NOT NULL,user_visible_text TEXT NOT NULL,content_sha256 TEXT NOT NULL,is_current INTEGER NOT NULL,supersedes_artifact_id INTEGER,created_at_utc TEXT NOT NULL, UNIQUE(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no));
    CREATE UNIQUE INDEX current_artifact ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1;
    CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY,analysis_run_id INTEGER,input_role TEXT,source_entity_type TEXT,source_entity_id INTEGER,source_revision_id INTEGER,source_window_start_utc TEXT,source_window_end_utc TEXT,input_sha256 TEXT,trust_class TEXT,ordinal INTEGER,UNIQUE(analysis_run_id,ordinal));
    CREATE TABLE analysis_artifact_relations(id INTEGER PRIMARY KEY,from_artifact_id INTEGER,to_artifact_id INTEGER,relation_type TEXT,created_at_utc TEXT,UNIQUE(from_artifact_id,to_artifact_id,relation_type));
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY,subject_id INTEGER NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,analysis_run_id INTEGER NOT NULL,delivery_kind TEXT NOT NULL,status TEXT NOT NULL,provider_message_id TEXT,provider_thread_id TEXT,sent_at_utc TEXT,last_verified_at_utc TEXT,error_code TEXT,error_summary TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL);
    CREATE TABLE analysis_delivery_artifacts(id INTEGER PRIMARY KEY,analysis_delivery_id INTEGER NOT NULL,analysis_artifact_id INTEGER NOT NULL,content_role TEXT NOT NULL,ordinal INTEGER NOT NULL,UNIQUE(analysis_delivery_id,analysis_artifact_id,content_role));
    INSERT INTO data_subjects VALUES(1);
    INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(1,'analysis:1:daily:2026-07-24:one',1,'daily','started');
    """)
    return connection


def accepted() -> dict[str, object]:
    return {"run_key": "analysis:1:daily:2026-07-24:one", "subject_id": 1, "mode": "daily", "status": "accepted", "artifacts": [
        {"artifact_kind": "daily_summary", "period": {"start_local_date": "2026-07-23", "end_local_date": "2026-07-23"}, "structured_content": {"overall_state": "稳定", "data_completeness": "partial", "decision_factors": ["活动记录未确认"], "activity_evidence": "unconfirmed", "plan_evidence": "available"}, "user_visible_text": "昨日恢复稳定。"},
        {"artifact_kind": "daily_training_advice", "period": {"start_local_date": "2026-07-24", "end_local_date": "2026-07-24"}, "structured_content": {"primary_item": {"activity_kind": "running", "hansons_session_role": "easy", "course_type": "easy", "warmup": "轻柔热身", "main_set": "轻松跑", "cooldown": "逐步放松", "planned_duration_minutes": 30, "prescribed_rpe": 4, "target_bpm_range": None, "stop_conditions": ["acute_pain"]}, "configured_difficulty_level": 2, "selected_session_difficulty_level": 2, "difficulty_adjustment_reason": None, "confidence": "一般", "confidence_reason": "数据有限", "data_limitation": None}, "user_visible_text": "今日轻松训练。"},
    ]}


def manifest() -> list[dict[str, object]]:
    return [{"ordinal": 0, "input_role": "quality_state", "source_entity_type": "data_quality_issue", "source_entity_id": "quality:1", "source_revision_id": "quality-gate:synthetic", "source_window": {"start_local_date": "2026-07-23", "end_local_date": "2026-07-24"}, "input_sha256": "a" * 64, "trust_class": "derived_statistic"}]


def published(connection: sqlite3.Connection):
    input_manifest = manifest()
    snapshot = {"input_manifest": input_manifest}
    evidence = {
        "harness_version": "harness-v1", "input_schema_version": "1", "output_schema_version": "1",
        "context_snapshot_json": snapshot,
        "context_snapshot_sha256": sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "generator_metadata_json": {"runner": "codex-exec", "attempt": 1},
    }
    return AnalysisPublisher(connection, clock=lambda: "2026-07-24T00:00:00Z").publish(run_id=1, accepted=accepted(), input_manifest=input_manifest, run_evidence=evidence)


def test_accepted_artifacts_commit_before_pending_delivery_and_render_is_ephemeral():
    connection = database()
    receipt = published(connection)
    pending, rendered = AnalysisDeliveryFactory(connection, clock=lambda: "2026-07-24T00:01:00Z").prepare(publish_receipt=receipt, delivery_kind="daily_report")
    assert pending.delivery_kind == "daily_report" and pending.delivery_id > 0
    assert connection.execute("SELECT status FROM analysis_deliveries").fetchone()[0] == "pending"
    assert connection.execute("SELECT count(*) FROM analysis_delivery_artifacts").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 2
    assert rendered.subject == "TrainLab｜每日训练简报｜2026年7月24日"
    assert rendered.plain_text.startswith("每日训练简报\n日期：2026年7月24日\n\n昨日回顾\n")
    assert "\n今日安排\n" in rendered.plain_text
    assert "TrainLab 分析报告" not in rendered.plain_text
    assert "Run-ID:" not in rendered.plain_text
    assert "<h1" in rendered.html
    assert "每日训练简报" in rendered.html
    assert "昨日状态与今日安排" in rendered.html
    assert "analysis:1:daily" not in rendered.html
    assert all(marker not in rendered.html for marker in ("data-field=", "data-repeat=", "data-optional=", "data-variant=", "data-od-id="))
    assert "body" not in {row[1] for row in connection.execute("PRAGMA table_info(analysis_deliveries)")}


def test_same_exact_revision_is_idempotent_and_does_not_duplicate_pending_delivery():
    connection = database()
    receipt = published(connection)
    factory = AnalysisDeliveryFactory(connection)
    first = factory.create_pending(publish_receipt=receipt, delivery_kind="daily_report")
    second = factory.create_pending(publish_receipt=receipt, delivery_kind="daily_report")
    assert second.delivery_id == first.delivery_id and second.idempotency_key == first.idempotency_key
    assert connection.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM analysis_delivery_artifacts").fetchone()[0] == 2


def test_pending_delivery_can_join_a_caller_owned_atomic_transaction():
    connection = database()
    receipt = published(connection)
    factory = AnalysisDeliveryFactory(connection)
    with pytest.raises(Exception, match="transaction_required"):
        factory.create_pending_in_transaction(
            publish_receipt=receipt, delivery_kind="daily_report"
        )
    connection.execute("BEGIN IMMEDIATE")
    pending = factory.create_pending_in_transaction(
        publish_receipt=receipt, delivery_kind="daily_report"
    )
    connection.execute("ROLLBACK")
    assert pending.delivery_id > 0
    assert connection.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0] == 0


def test_delivery_remains_bound_to_exact_revision_after_current_drifts():
    connection = database()
    receipt = published(connection)
    pending = AnalysisDeliveryFactory(connection).create_pending(publish_receipt=receipt, delivery_kind="daily_report")
    connection.execute("UPDATE analysis_artifacts SET is_current=0 WHERE id=?", (receipt.artifact_ids["daily_summary"],))
    connection.execute("INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(1,'daily_summary','2026-07-23','2026-07-23',2,1,'1','{}','new current','b',1,'2026-07-24T01:00:00Z')")
    rows = connection.execute("SELECT analysis_artifact_id FROM analysis_delivery_artifacts WHERE analysis_delivery_id=? ORDER BY ordinal", (pending.delivery_id,)).fetchall()
    assert [row[0] for row in rows] == [receipt.artifact_ids["daily_summary"], receipt.artifact_ids["daily_training_advice"]]
    assert "昨日恢复稳定。" in render_delivery(pending).plain_text


def test_html_renderer_escapes_untrusted_text_and_emits_no_links_or_remote_content():
    connection = database()
    receipt = published(connection)
    connection.execute("UPDATE analysis_artifacts SET user_visible_text=? WHERE id=?", ("<script>alert(1)</script><img src='https://bad.invalid/x'> <a href='https://bad.invalid'>x</a>", receipt.artifact_ids["daily_summary"]))
    connection.commit()
    pending = AnalysisDeliveryFactory(connection).create_pending(publish_receipt=receipt, delivery_kind="daily_report")
    rendered = render_delivery(pending)
    assert "<script" not in rendered.html and "<img" not in rendered.html and "<a " not in rendered.html
    assert "<a href=" not in rendered.html and "<img src=" not in rendered.html
    assert "&lt;script&gt;" in rendered.html and "https://bad.invalid" in rendered.html


def test_render_failure_does_not_roll_back_published_artifacts_or_pending_delivery():
    connection = database()
    receipt = published(connection)
    def broken_renderer(_pending):
        raise RuntimeError("render failed")
    with pytest.raises(RuntimeError, match="render failed"):
        AnalysisDeliveryFactory(connection).prepare(publish_receipt=receipt, delivery_kind="daily_report", renderer=broken_renderer)
    assert connection.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 2
    assert connection.execute("SELECT status FROM analysis_deliveries").fetchone()[0] == "pending"


def test_weekly_report_binds_exact_summary_and_plan_revisions() -> None:
    connection = database()
    connection.execute(
        "UPDATE analysis_runs SET run_key='analysis:1:weekly:2026-07-26:one',"
        "analysis_kind='weekly' WHERE id=1"
    )
    connection.executemany(
        "INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,"
        "period_start_local_date,period_end_local_date,revision_no,"
        "generated_by_run_id,schema_version,structured_content_json,"
        "user_visible_text,content_sha256,is_current,created_at_utc) "
            "VALUES(?,1,?,?,?,?,1,'1',?,?,?,1,'2026-07-26T00:00:00Z')",
        (
            (
                11, "weekly_summary", "2026-07-19", "2026-07-25", 1,
                json.dumps({"summary": "本周稳定。"}), "本周总结。", "b" * 64,
            ),
            (
                12, "weekly_training_plan", "2026-07-26", "2026-08-01", 1,
                json.dumps({"period": {"start_local_date": "2026-07-26", "end_local_date": "2026-08-01"}, "timezone": "Asia/Hong_Kong", "objective": {}, "constraints": {}, "items": [{"item_index": i, "local_date": f"2026-07-{26 + i:02d}" if i < 6 else "2026-08-01", "activity_kind": "rest", "prescription": {"activity_kind": "rest"}, "rationale_text": "恢复", "stop_conditions": []} for i in range(7)]}), "未来七天计划。", "c" * 64,
            ),
        ),
    )
    receipt = {
        "run_id": 1,
        "artifact_ids": {
            "weekly_summary": 11,
            "weekly_training_plan": 12,
        },
    }
    connection.commit()
    pending = AnalysisDeliveryFactory(connection).create_pending(
        publish_receipt=receipt, delivery_kind="weekly_report"
    )
    assert [item.content_role for item in pending.artifacts] == [
        "weekly_summary",
        "weekly_plan",
    ]
    rendered = render_delivery(pending)
    assert "每周总结" in rendered.plain_text
    assert "未来七天计划" in rendered.plain_text
    assert rendered.plain_text.startswith("每周训练报告\n日期：2026年7月26日")
    assert "每周训练报告" in rendered.html
    assert "先稳定恢复，再延续训练节奏" not in rendered.html
    assert "Run-ID:" not in rendered.plain_text
    assert "Idempotency-Key:" not in rendered.html


def test_rest_day_omits_running_steps_and_malformed_structured_content_fails_closed() -> None:
    connection = database()
    receipt = published(connection)
    rest = {"primary_item": {"activity_kind": "rest"}, "configured_difficulty_level": 2, "selected_session_difficulty_level": 1, "difficulty_adjustment_reason": "恢复优先", "confidence": "一般", "confidence_reason": "恢复优先", "data_limitation": None}
    connection.execute("UPDATE analysis_artifacts SET structured_content_json=? WHERE id=?", (json.dumps(rest), receipt.artifact_ids["daily_training_advice"]))
    connection.commit()
    rendered = render_delivery(AnalysisDeliveryFactory(connection).create_pending(publish_receipt=receipt, delivery_kind="daily_report"))
    assert "休息日" in rendered.html
    assert "热身</td>" not in rendered.html and "主训练</td>" not in rendered.html and "放松</td>" not in rendered.html
    connection.execute("UPDATE analysis_artifacts SET structured_content_json='[' WHERE id=?", (receipt.artifact_ids["daily_summary"],))
    connection.commit()
    with pytest.raises(Exception, match="artifact_content_invalid"):
        AnalysisDeliveryFactory(connection).create_pending(publish_receipt=receipt, delivery_kind="daily_report")


def test_plan_revision_uses_weekly_design_for_only_its_existing_plan_items() -> None:
    connection = database()
    connection.execute("UPDATE analysis_runs SET run_key='analysis:1:weekly:2026-07-26:revision',analysis_kind='weekly' WHERE id=1")
    plan = {"period": {"start_local_date": "2026-07-26", "end_local_date": "2026-08-01"}, "timezone": "Asia/Hong_Kong", "objective": {}, "constraints": {}, "items": [
        {"item_index": index, "local_date": f"2026-07-{26 + index:02d}" if index < 6 else "2026-08-01", "activity_kind": "rest", "prescription": {"activity_kind": "rest"}, "rationale_text": "修订后恢复", "stop_conditions": []}
        for index in range(7)
    ]}
    connection.execute("INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(12,1,'weekly_training_plan','2026-07-26','2026-08-01',1,1,'1',?,'修订计划。',?,1,'2026-07-26T00:00:00Z')", (json.dumps(plan), "c" * 64))
    connection.commit()
    pending = AnalysisDeliveryFactory(connection).create_pending(publish_receipt={"run_id": 1, "artifact_ids": {"weekly_training_plan": 12}}, delivery_kind="plan_revision")
    rendered = render_delivery(pending)
    assert rendered.subject == "TrainLab｜训练计划更新｜2026年7月26日"
    assert "训练计划修订" in rendered.html and rendered.html.count("修订后恢复") == 7
    assert all(marker not in rendered.html for marker in ("data-field=", "data-repeat=", "data-optional=", "data-variant=", "data-od-id="))
    first = pending.artifacts[0].structured_content_json["items"][0]
    first["activity_kind"] = "running"
    first["prescription"] = {
        "activity_kind": "running",
        "hansons_session_role": "easy",
        "course_type": "easy",
        "warmup": "gentle_warmup",
        "main_set": "talk_test_easy",
        "cooldown": "gentle_cooldown",
        "planned_duration_minutes": 30,
        "prescribed_rpe": 4,
        "target_bpm_range": None,
        "stop_conditions": ["chest_pain"],
    }
    first["stop_conditions"] = ["acute_pain"]
    rendered = render_delivery(pending)
    assert "出现胸痛" in rendered.html
    assert "出现急性疼痛" not in rendered.html
    first["prescription"]["course_type"] = "intervals"
    with pytest.raises(AnalysisDeliveryError, match="artifact_content_invalid"):
        render_delivery(pending)


def test_delivery_fails_closed_for_missing_daily_contract_and_weekly_date_gap() -> None:
    connection = database()
    receipt = published(connection)
    summary_id = receipt.artifact_ids["daily_summary"]
    content = json.loads(
        connection.execute(
            "SELECT structured_content_json FROM analysis_artifacts WHERE id=?",
            (summary_id,),
        ).fetchone()[0]
    )
    content.pop("plan_evidence")
    connection.execute(
        "UPDATE analysis_artifacts SET structured_content_json=? WHERE id=?",
        (json.dumps(content), summary_id),
    )
    connection.commit()
    pending = AnalysisDeliveryFactory(connection).create_pending(
        publish_receipt=receipt, delivery_kind="daily_report"
    )
    with pytest.raises(AnalysisDeliveryError, match="artifact_content_invalid"):
        render_delivery(pending)

    connection = database()
    connection.execute(
        "UPDATE analysis_runs SET run_key='analysis:1:weekly:2026-07-26:gap' WHERE id=1"
    )
    plan = {
        "period": {
            "start_local_date": "2026-07-26",
            "end_local_date": "2026-08-01",
        },
        "timezone": "Asia/Hong_Kong",
        "objective": {},
        "constraints": {},
        "items": [
            {
                "item_index": index,
                "local_date": (
                    "2026-08-01"
                    if index == 5
                    else (
                        f"2026-07-{26 + index:02d}"
                        if index < 6
                        else "2026-07-31"
                    )
                ),
                "activity_kind": "rest",
                "prescription": {"activity_kind": "rest"},
                "rationale_text": "恢复",
                "stop_conditions": [],
            }
            for index in range(7)
        ],
    }
    connection.execute(
        "INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,"
        "period_end_local_date,revision_no,generated_by_run_id,schema_version,"
        "structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) "
        "VALUES(12,1,'weekly_training_plan','2026-07-26','2026-08-01',1,1,'1',"
        "?,'计划。',?,1,'2026-07-26T00:00:00Z')",
        (json.dumps(plan), "c" * 64),
    )
    connection.commit()
    pending = AnalysisDeliveryFactory(connection).create_pending(
        publish_receipt={
            "run_id": 1,
            "artifact_ids": {"weekly_training_plan": 12},
        },
        delivery_kind="plan_revision",
    )
    with pytest.raises(AnalysisDeliveryError, match="artifact_content_invalid"):
        render_delivery(pending)
