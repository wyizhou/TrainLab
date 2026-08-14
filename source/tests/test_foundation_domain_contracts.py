from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.foundation import VIEWS, FoundationConfig, FoundationRequest, FoundationTool


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
        tool(root)
        .execute(FoundationRequest("init", "domain-contract", "2026-07-23T00:00:00Z"))
        .status
        == "initialized"
    )
    conn = sqlite3.connect(root / "data.db")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def base(conn: sqlite3.Connection) -> tuple[int, int, int]:
    conn.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('subject','2026-01-01T00:00:00Z')"
    )
    subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
    conn.execute(
        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            "a" * 64,
            "garmin/fit/a.fit",
            "application/octet-stream",
            1,
            "garmin",
            "activity_fit",
            "2026-01-01T00:00:00Z",
        ),
    )
    raw = conn.execute("SELECT id FROM raw_objects").fetchone()[0]
    conn.execute(
        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,parsed_at_utc) VALUES(?,?,?,?,?,?,?)",
        ("garmin", "activity_fit", "one", 1, raw, "b" * 64, "2026-01-01T00:00:00Z"),
    )
    revision = conn.execute("SELECT id FROM source_revisions").fetchone()[0]
    return subject, raw, revision


def test_raw_revision_coverage_and_health_contracts(tmp_path: Path) -> None:
    conn = database(tmp_path)
    subject, raw, revision = base(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
            ("c" * 64, "../escape", "x", 0, "g", "x", "2026-01-01T00:00:00Z"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
            ("not-a-hash", "g/x", "x", 0, "g", "x", "2026-01-01T00:00:00Z"),
        )
    conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=?", (revision,))
    conn.execute(
        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash) VALUES(?,?,?,?,?,?)",
        ("garmin", "activity_fit", "one", 2, raw, "c" * 64),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash) VALUES(?,?,?,?,?)",
            ("garmin", "activity_fit", "one", 3, "d" * 64),
        )
    for state in (
        "fetched",
        "partial",
        "empty",
        "not_enabled",
        "not_available",
        "forbidden",
        "not_supported",
        "error",
    ):
        conn.execute(
            "INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(?,?,?,?,?,?)",
            (subject, "garmin", state, "2026-01-01", state, "2026-01-01T00:00:00Z"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO resource_coverage(subject_id,provider,resource_kind,availability_state,observed_at_utc) VALUES(?,?,?,?,?)",
            (subject, "garmin", "x", "zero", "2026-01-01T00:00:00Z"),
        )
    conn.execute(
        "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key,value_number,canonical_unit) VALUES(?,?,?,?,?,?)",
        (subject, "2026-01-01T00:00:00Z", "2026-01-01", "heart_rate", 60, "bpm"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key) VALUES(?,?,?,?)",
            (subject, "2026-01-01T00:00:00Z", "2026-01-01", "missing_value"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_text,value_origin) VALUES(1,'bad',1,'two','provider_derived')"
        )
    conn.close()


def test_activity_fit_devices_and_specialty_constraints(tmp_path: Path) -> None:
    conn = database(tmp_path)
    subject, _, revision = base(conn)
    conn.execute(
        "INSERT INTO devices(device_uid_hash,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?)",
        ("d" * 64, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    device = conn.execute("SELECT id FROM devices").fetchone()[0]
    conn.execute(
        "INSERT INTO activities(subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(?,?,?,?,?)",
        (subject, "garmin", "activity", "2026-01-01T00:00:00Z", "2026-01-01"),
    )
    activity = conn.execute("SELECT id FROM activities").fetchone()[0]
    conn.execute(
        "INSERT INTO activity_devices(activity_id,device_id,device_role,source_revision_id) VALUES(?,?,?,?)",
        (activity, device, "heart_rate_sensor", revision),
    )
    conn.execute(
        "INSERT INTO activity_metric_sources(activity_id,metric_key,source_kind,device_id,attribution_method,confidence) VALUES(?,?,?,?,?,?)",
        (activity, "heart_rate", "fit", device, "explicit_device", 0.9),
    )
    conn.execute(
        "INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role) VALUES(?,?,?)",
        (activity, revision, "activity_fit"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role) VALUES(?,?,?)",
            (activity, revision, "wrong"),
        )
    conn.execute(
        "INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,?)",
        (activity, "climb_active", 0, revision),
    )
    segment = conn.execute("SELECT id FROM activity_segments").fetchone()[0]
    conn.execute(
        "INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,extras_json) VALUES(?,?,?,?,?)",
        (activity, revision, "record", 0, json.dumps({"developer": {"index": 1}})),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,extras_json) VALUES(?,?,?,?,?)",
            (activity, revision, "record", 0, "{}"),
        )
    conn.execute(
        "INSERT INTO fit_metric_definitions(source_revision_id,developer_data_index,field_definition_number) VALUES(?,?,?)",
        (revision, 1, 2),
    )
    conn.execute(
        "INSERT INTO activity_aux_messages(activity_id,source_revision_id,global_message_number,message_index,payload_json) VALUES(?,?,?,?,?)",
        (activity, revision, 99, 0, "{}"),
    )
    conn.execute(
        "INSERT INTO fit_unknown_message_catalog(source_revision_id,global_message_number,message_count,field_signature_json) VALUES(?,?,?,?)",
        (revision, 77, 1, "{}"),
    )
    conn.execute(
        "INSERT INTO course_points(activity_id,course_identity,point_index) VALUES(?,?,?)",
        (activity, "route", 0),
    )
    conn.execute(
        "INSERT INTO climbing_routes(segment_id,completed) VALUES(?,1)", (segment,)
    )
    conn.execute(
        "INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,?)",
        (activity, "strength_active", 1, revision),
    )
    strength_segment = conn.execute(
        "SELECT id FROM activity_segments ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO strength_sets(segment_id,repetitions,weight_kg) VALUES(?,?,?)",
        (strength_segment, 0, 0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO course_points(activity_id,course_identity,point_index) VALUES(?,?,?)",
            (activity, "route", 0),
        )
    conn.execute(
        "UPDATE activities SET provider_state='provider_deleted' WHERE id=?",
        (activity,),
    )
    assert conn.execute("SELECT * FROM v_current_activities").fetchall() == []
    conn.close()


def test_mail_analysis_delivery_quality_and_stable_view_contracts(
    tmp_path: Path,
) -> None:
    conn = database(tmp_path)
    subject, _, revision = base(conn)
    conn.execute(
        "INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,?,?)",
        (
            subject,
            "gmail",
            "email",
            "e" * 64,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    identity = conn.execute("SELECT id FROM subject_identities").fetchone()[0]
    conn.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id) VALUES(?,?)",
        (subject, "thread"),
    )
    thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]
    conn.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,labels_json,processing_state) VALUES(?,?,?,?,?,?)",
        (thread, "message", "inbound", "user", "[]", "new"),
    )
    message = conn.execute("SELECT id FROM mail_messages").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role) VALUES(?,?,?,?)",
            (thread, "bad", "sideways", "user"),
        )
    conn.execute(
        "INSERT INTO mail_agent_runs(run_key,invocation_id,subject_id,request_kind,status,started_at_utc) VALUES(?,?,?,?,?,?)",
        ("mail-run", "invoke", subject, "process", "started", "2026-01-01T00:00:00Z"),
    )
    mail_run = conn.execute("SELECT id FROM mail_agent_runs").fetchone()[0]
    conn.execute(
        "INSERT INTO mail_agent_items(mail_agent_run_id,logical_item_kind,logical_item_id,mail_message_id,stage,status) VALUES(?,?,?,?,?,?)",
        (mail_run, "message", "message", message, "discover", "started"),
    )
    conn.execute(
        "INSERT INTO mail_poll_cursors(subject_id,identity_id,stream_kind,updated_at_utc) VALUES(?,?,?,?)",
        (subject, identity, "tracked_threads", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO mail_response_artifacts(subject_id,mail_thread_id,in_reply_to_mail_message_id,response_kind,revision_no,generated_by_mail_agent_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            subject,
            thread,
            message,
            "reply",
            1,
            mail_run,
            "1",
            "{}",
            "visible",
            "f" * 64,
            "2026-01-01T00:00:00Z",
        ),
    )
    response = conn.execute("SELECT id FROM mail_response_artifacts").fetchone()[0]
    conn.execute(
        "INSERT INTO mail_deliveries(idempotency_key,delivery_kind,status,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?)",
        (
            "mail-delivery",
            "mail_response",
            "pending",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    mail_delivery = conn.execute("SELECT id FROM mail_deliveries").fetchone()[0]
    conn.execute(
        "INSERT INTO mail_delivery_artifacts(mail_delivery_id,mail_response_artifact_id,content_role,ordinal) VALUES(?,?,?,?)",
        (mail_delivery, response, "mail_response", 0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO mail_delivery_artifacts(mail_delivery_id,mail_response_artifact_id,content_role,ordinal) VALUES(?,?,?,?)",
            (mail_delivery, response, "mail_response", 0),
        )
    conn.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?,?,?,?)",
        ("analysis-run", subject, "weekly", "succeeded", "2026-01-01T00:00:00Z"),
    )
    analysis_run = conn.execute("SELECT id FROM analysis_runs").fetchone()[0]
    conn.execute(
        "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            subject,
            "weekly_training_plan",
            "2026-01-05",
            "2026-01-11",
            1,
            analysis_run,
            "1",
            "{}",
            "plan",
            "1" * 64,
            "2026-01-01T00:00:00Z",
        ),
    )
    artifact = conn.execute("SELECT id FROM analysis_artifacts").fetchone()[0]
    conn.execute(
        "INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,created_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            subject,
            artifact,
            "2026-01-05",
            "2026-01-11",
            "Asia/Hong_Kong",
            "proposed",
            "2026-01-01T00:00:00Z",
        ),
    )
    plan = conn.execute("SELECT id FROM training_plans").fetchone()[0]
    for index in range(7):
        conn.execute(
            "INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind) VALUES(?,?,date('2026-01-05', ?),?)",
            (plan, index, f"+{index} days", "rest"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind) VALUES(?,?,?,?)",
            (plan, 8, "2026-01-12", "rest"),
        )
    conn.execute(
        "INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            subject,
            "analysis-delivery",
            analysis_run,
            "weekly_report",
            "pending",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    analysis_delivery = conn.execute("SELECT id FROM analysis_deliveries").fetchone()[0]
    conn.execute(
        "INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)",
        (analysis_delivery, artifact, "weekly_plan", 0),
    )
    conn.execute(
        "INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,analysis_artifact_id,mail_response_artifact_id,analysis_delivery_id,mail_delivery_id,trust_level,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            subject,
            "plan_revision_reason_recorded",
            "trainlab",
            "2026-01-01T00:00:00Z",
            artifact,
            response,
            analysis_delivery,
            mail_delivery,
            "system_generated",
            "mail",
        ),
    )
    conn.execute(
        "INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,source_event_id) VALUES(?,?,?,?,?)",
        (subject, "goal", "{}", "long_term", 1),
    )
    fact = conn.execute("SELECT id FROM user_facts").fetchone()[0]
    conn.execute("UPDATE user_facts SET is_active=0 WHERE id=?", (fact,))
    conn.execute(
        "INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,source_event_id) VALUES(?,?,?,?,?)",
        (subject, "goal", "{}", "long_term", 1),
    )
    replacement_fact = conn.execute(
        "SELECT id FROM user_facts ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE user_facts SET superseded_by_fact_id=? WHERE id=?",
        (replacement_fact, fact),
    )
    conn.execute(
        "INSERT INTO daily_health(subject_id,local_date,is_current) VALUES(?,?,0)",
        (subject, "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO daily_health(subject_id,local_date,is_current) VALUES(?,?,1)",
        (subject, "2026-01-01"),
    )
    conn.execute(
        "UPDATE mail_response_artifacts SET is_current=0 WHERE id=?", (response,)
    )
    conn.execute(
        "INSERT INTO mail_response_artifacts(subject_id,mail_thread_id,in_reply_to_mail_message_id,response_kind,revision_no,generated_by_mail_agent_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,supersedes_mail_response_artifact_id,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            subject,
            thread,
            message,
            "reply",
            2,
            mail_run,
            "1",
            "{}",
            "visible 2",
            "2" * 64,
            1,
            response,
            "2026-01-02T00:00:00Z",
        ),
    )
    conn.execute("UPDATE analysis_artifacts SET is_current=0 WHERE id=?", (artifact,))
    conn.execute(
        "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,supersedes_artifact_id,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            subject,
            "weekly_training_plan",
            "2026-01-05",
            "2026-01-11",
            2,
            analysis_run,
            "1",
            "{}",
            "plan 2",
            "2" * 64,
            1,
            artifact,
            "2026-01-02T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO data_quality_issues(entity_type,issue_code,severity,first_seen_at_utc,last_seen_at_utc,status) VALUES(?,?,?,?,?,?)",
        (
            "activity",
            "check",
            "warning",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "open",
        ),
    )
    conn.execute(
        "INSERT INTO data_quality_issues(entity_type,issue_code,severity,first_seen_at_utc,last_seen_at_utc,status) VALUES(?,?,?,?,?,?)",
        (
            "activity",
            "closed",
            "warning",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "resolved",
        ),
    )
    conn.execute(
        "INSERT INTO reconciliation_results(entity_type,field_key,result,checked_at_utc) VALUES(?,?,?,?)",
        ("activity", "distance", "match", "2026-01-01T00:00:00Z"),
    )
    for view in VIEWS:
        conn.execute(f"SELECT * FROM {view} LIMIT 1").fetchall()
    assert (
        conn.execute("SELECT COUNT(*) FROM v_open_data_quality_issues").fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM v_plan_revision_reason_events").fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM v_current_daily_health").fetchone()[0] == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM v_active_user_facts").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM v_current_mail_response_artifacts"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM v_current_analysis_artifacts").fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT trust_class FROM v_analysis_history_context").fetchone()[0]
        == "prior_model_output"
    )
    assert (
        conn.execute(
            "SELECT trust_class FROM v_mail_response_history_context"
        ).fetchone()[0]
        == "prior_model_output"
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM v_current_training_plans").fetchone()[0] == 1
    )
    conn.close()


def test_foundation_v4_has_no_historical_orchestration_objects(tmp_path: Path) -> None:
    conn = database(tmp_path)
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    assert not any(
        "orchestr" in name or "scheduler" in name or "incident" in name
        for name in names
    )
    conn.close()
