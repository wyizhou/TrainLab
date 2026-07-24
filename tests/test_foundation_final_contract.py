from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


def tool(root: Path) -> FoundationTool:
    return FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock"))


def conn(tmp_path: Path) -> sqlite3.Connection:
    root = tmp_path / "foundation"
    assert tool(root).execute(FoundationRequest("init", "final-contract", "2026-07-23T00:00:00Z")).status == "initialized"
    db = sqlite3.connect(root / "data.db"); db.execute("PRAGMA foreign_keys=ON")
    db.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('s','2026-01-01T00:00:00Z')")
    return db


def revision(db: sqlite3.Connection, number: int, current: int) -> int:
    raw_hash = f"{number:x}" * 64
    db.execute("INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)", (raw_hash[:64], f"synthetic/{number}", "x", 0, "synthetic", "x", "2026-01-01T00:00:00Z"))
    db.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,is_current) VALUES(?,?,?,?,?,?,?)", ("synthetic", "x", "object", number, db.execute("SELECT last_insert_rowid()").fetchone()[0], ("a" * 63 + str(number)), current))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_active_source_role_and_specialty_projection_guards(tmp_path: Path) -> None:
    db = conn(tmp_path); subject = db.execute("SELECT id FROM data_subjects").fetchone()[0]
    old, current = revision(db, 1, 0), revision(db, 2, 1)
    db.execute("INSERT INTO activities(subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(?,?,?,?,?)", (subject, "synthetic", "a", "2026-01-01T00:00:00Z", "2026-01-01")); activity = db.execute("SELECT id FROM activities").fetchone()[0]
    db.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, old, "activity_fit"))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, current, "activity_fit"))
    db.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,0)", (activity, current, "activity_fit"))
    db.execute("INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,?)", (activity, "lap", 0, current)); lap = db.execute("SELECT id FROM activity_segments").fetchone()[0]
    db.execute("INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,?)", (activity, "climb_active", 1, current)); climb = db.execute("SELECT id FROM activity_segments ORDER BY id DESC LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,?)", (activity, "strength_rest", 2, current)); strength = db.execute("SELECT id FROM activity_segments ORDER BY id DESC LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO climbing_routes(segment_id) VALUES(?)", (lap,))
    db.execute("INSERT INTO climbing_routes(segment_id) VALUES(?)", (climb,))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO strength_sets(segment_id) VALUES(?)", (lap,))
    db.execute("INSERT INTO strength_sets(segment_id) VALUES(?)", (strength,))
    db.close()


def test_current_health_views_accept_current_and_manual_only(tmp_path: Path) -> None:
    db = conn(tmp_path); subject = db.execute("SELECT id FROM data_subjects").fetchone()[0]
    old, current = revision(db, 1, 0), revision(db, 2, 1)
    for source in (old, current, None):
        db.execute("INSERT INTO physiology_records(subject_id,domain,record_type,value_origin,source_revision_id) VALUES(?,?,?,?,?)", (subject, "x", "x", "unknown", source)); record = db.execute("SELECT id FROM physiology_records ORDER BY id DESC LIMIT 1").fetchone()[0]
        db.execute("INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_origin) VALUES(?,?,?,?)", (record, "x", 1, "unknown"))
        db.execute("INSERT INTO sleep_sessions(subject_id,session_type,start_time_utc,end_time_utc,source_revision_id) VALUES(?,?,?,?,?)", (subject, "nap", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", source))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO physiology_records(subject_id,domain,record_type,value_origin) VALUES(?,?,?,?)", (subject, "x", "x", "invented"))
    assert db.execute("SELECT COUNT(*) FROM v_current_physiology_records").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM v_current_physiology_metrics").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM v_current_sleep_sessions").fetchone()[0] == 2
    db.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,trust_level,created_by) VALUES(?,?,?,?,?,?)", (subject, "later", "user", "2026-01-02T00:00:00Z", "untrusted_content", "test"))
    db.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,trust_level,created_by) VALUES(?,?,?,?,?,?)", (subject, "earlier", "user", "2026-01-01T00:00:00Z", "untrusted_content", "test"))
    assert [row[0] for row in db.execute("SELECT event_type FROM v_conversation_context")] == ["earlier", "later"]
    db.close()


def test_delivery_trust_plan_and_reconcile_contracts(tmp_path: Path) -> None:
    db = conn(tmp_path); subject = db.execute("SELECT id FROM data_subjects").fetchone()[0]
    current = revision(db, 1, 1)
    db.execute("INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?,?,?,?)", ("run", subject, "weekly", "succeeded", "2026-01-01T00:00:00Z")); run = db.execute("SELECT id FROM analysis_runs").fetchone()[0]
    for kind in ("daily_summary", "weekly_training_plan"):
        db.execute("INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (subject, kind, "2026-01-01", "2026-01-07", 1, run, "1", '{}', kind, hashlib.sha256(kind.encode()).hexdigest(), "2026-01-01T00:00:00Z"))
    daily, weekly = [row[0] for row in db.execute("SELECT id FROM analysis_artifacts ORDER BY id")]
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,created_at_utc) VALUES(?,?,?,?,?,?,?)", (subject, daily, "2026-01-01", "2026-01-07", "Asia/Singapore", "proposed", "2026-01-01T00:00:00Z"))
    db.execute("INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,created_at_utc) VALUES(?,?,?,?,?,?,?)", (subject, weekly, "2026-01-01", "2026-01-07", "Asia/Singapore", "proposed", "2026-01-01T00:00:00Z"))
    db.execute("INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?)", (subject, "delivery", run, "weekly_report", "pending", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")); delivery = db.execute("SELECT id FROM analysis_deliveries").fetchone()[0]
    db.execute("INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)", (delivery, weekly, "weekly_plan", 0))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)", (delivery, weekly, "weekly_plan", 1))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)", (delivery, weekly, "wrong", 2))
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?)", (run, "x", "x", "x", "wrong", 0))
    db.execute("INSERT INTO mail_agent_runs(run_key,invocation_id,subject_id,request_kind,status,started_at_utc) VALUES(?,?,?,?,?,?)", ("mail", "mail-invocation", subject, "process", "succeeded", "2026-01-01T00:00:00Z")); mail_run = db.execute("SELECT id FROM mail_agent_runs").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO mail_response_inputs(mail_agent_run_id,input_role,source_entity_type,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?)", (mail_run, "x", "x", "x", "wrong", 0))
    db.execute("INSERT INTO mail_response_artifacts(subject_id,response_kind,revision_no,generated_by_mail_agent_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?)", (subject, "reply", 1, mail_run, "1", '{}', "x", "b" * 64, "2026-01-01T00:00:00Z")); response = db.execute("SELECT id FROM mail_response_artifacts").fetchone()[0]
    db.execute("INSERT INTO mail_deliveries(idempotency_key,delivery_kind,status,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?)", ("mail-delivery", "mail_response", "pending", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")); mail_delivery = db.execute("SELECT id FROM mail_deliveries").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO mail_delivery_artifacts(mail_delivery_id,mail_response_artifact_id,content_role,ordinal) VALUES(?,?,?,?)", (mail_delivery, response, "wrong", 0))
    db.execute("INSERT INTO reconciliation_results(entity_type,field_key,left_source_revision_id,right_source_revision_id,absolute_difference,relative_difference,result,checked_at_utc) VALUES(?,?,?,?,?,?,?,?)", ("x", "x", current, current, 0, 0, "match", "2026-01-01T00:00:00Z"))
    assert {row[1] for row in db.execute("PRAGMA table_info(reconciliation_results)")} >= {"absolute_difference", "relative_difference"}
    db.close()


def test_plain_backup_is_read_only_on_source(tmp_path: Path) -> None:
    root = tmp_path / "foundation"; instance = tool(root)
    assert instance.execute(FoundationRequest("init", "backup-readonly", "2026-07-23T00:00:00Z")).status == "initialized"
    before = {path.relative_to(root): ("dir", path.stat().st_mtime_ns) if path.is_dir() else ("file", path.read_bytes(), path.stat().st_mtime_ns) for path in [root, *root.rglob("*")]}
    target = tmp_path / "copy" / "data.db"
    instance.backup_database(target)
    after = {path.relative_to(root): ("dir", path.stat().st_mtime_ns) if path.is_dir() else ("file", path.read_bytes(), path.stat().st_mtime_ns) for path in [root, *root.rglob("*")]}
    assert after == before
    assert not [path for path in root.rglob("*") if path.name in {"data.db-wal", "data.db-shm"}]
