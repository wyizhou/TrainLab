from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import trainlab.analysis.stable_views as stable_views
from trainlab.analysis.stable_views import StableViewError, StableViewRepository
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


def repository(tmp_path: Path) -> tuple[sqlite3.Connection, StableViewRepository]:
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock"))
    assert tool.execute(FoundationRequest("init", "a3-06", "2026-07-24T00:00:00Z")).ready
    conn = sqlite3.connect(root / "data.db", isolation_level=None)
    conn.execute("INSERT INTO data_subjects(id,subject_key,created_at_utc) VALUES(1,'one','2026-07-24T00:00:00Z')")
    conn.execute("INSERT INTO data_subjects(id,subject_key,created_at_utc) VALUES(2,'two','2026-07-24T00:00:00Z')")
    # The value intentionally looks secret-like so context-gate tests prove it
    # cannot escape through a controlled failure.
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(1,'garmin','account','secret-hmac-never-leak',1,'2026-07-24T00:00:00Z','2026-07-24T00:00:00Z')")
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(1,1,'garmin','one','2026-07-22T01:00:00Z','2026-07-22')")
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(2,2,'garmin','two','2026-07-22T01:00:00Z','2026-07-22')")
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(3,1,'garmin','old','2026-07-01T01:00:00Z','2026-07-01')")
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(1,'garmin','activity_fit','one',1,?,1,'2026-07-22T02:00:00Z')", ("a" * 64,))
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current) VALUES(2,'garmin','x','old',1,?,0)", ("f" * 64,))
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(3,'garmin','activity_summary','one',1,?,1,'2026-07-22T02:00:00Z')", ("c" * 64,))
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,1,'activity_fit',1)")
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,3,'summary_json',1)")
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,2,'legacy_fit',0)")
    conn.executemany("INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,heart_rate_bpm) VALUES(?,?,?,?,?,?)", [(1,1,"record",1,"2026-07-22T01:00:00Z",100),(1,1,"record",2,"2026-07-22T01:01:00Z",110),(1,1,"record",3,"2026-07-22T01:02:00Z",120),(1,2,"record",1,"2026-07-22T01:01:00Z",999),(1,1,"record",4,"2026-07-23T01:00:00Z",888)])
    conn.executemany("INSERT INTO daily_health(subject_id,local_date,values_json,source_revision_id,is_current) VALUES(?,?,?,?,1)", [(1,"2026-07-22","{}",1),(2,"2026-07-22","{}",1),(1,"2026-07-01","{}",1)])
    conn.executemany("INSERT INTO physiology_records(id,subject_id,domain,record_type,effective_at_utc,local_date,value_origin,source_revision_id) VALUES(?,?,?,?,?,?,?,1)", [(1,1,"x","x","2026-07-22T01:00:00Z","2026-07-22","provider_derived"),(2,2,"x","x","2026-07-22T01:00:00Z","2026-07-22","provider_derived"),(3,1,"x","x","2026-07-01T01:00:00Z","2026-07-01","provider_derived")])
    conn.executemany("INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_origin) VALUES(?,?,?,?)", [(1,"m",1,"provider_derived"),(2,"m",2,"provider_derived"),(3,"m",3,"provider_derived")])
    conn.executemany("INSERT INTO sleep_sessions(subject_id,session_type,start_time_utc,end_time_utc,values_json,source_revision_id) VALUES(?,?,?,?,?,1)", [(1,"main_sleep","2026-07-22T01:00:00Z","2026-07-22T08:00:00Z","{}"),(2,"main_sleep","2026-07-22T01:00:00Z","2026-07-22T08:00:00Z","{}"),(1,"main_sleep","2026-07-01T01:00:00Z","2026-07-01T08:00:00Z","{}")])
    conn.executemany("INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(?,?,?,1)", [(1,"lap",0),(2,"lap",0),(3,"lap",0)])
    conn.executemany("INSERT INTO activity_metric_sources(activity_id,metric_key,source_kind,attribution_method) VALUES(?,?,?,?)", [(1,"heart_rate_bpm","device","explicit_device"),(2,"heart_rate_bpm","device","explicit_device"),(3,"heart_rate_bpm","device","explicit_device")])
    conn.executemany("INSERT INTO user_facts(subject_id,fact_key,fact_value_json,scope,is_active) VALUES(?,?,?,?,1)", [(1,"one","{}","long_term"),(2,"two","{}","long_term")])
    conn.executemany("INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?,?,?,?,?)", [(1,"daily-run-1",1,"daily","succeeded","2026-07-22T00:00:00Z"),(2,"daily-run-2",2,"daily","succeeded","2026-07-22T00:00:00Z"),(3,"daily-run-3",1,"daily","succeeded","2026-07-01T00:00:00Z")])
    conn.executemany("INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [(1,1,"weekly_summary","2026-07-22","2026-07-22",1,1,"1","{}","x","b"*64,1,"2026-07-22T00:00:00Z"),(2,2,"weekly_summary","2026-07-22","2026-07-22",1,2,"1","{}","x","c"*64,1,"2026-07-22T00:00:00Z"),(3,1,"weekly_summary","2026-07-01","2026-07-01",1,3,"1","{}","x","d"*64,1,"2026-07-01T00:00:00Z"),(4,1,"weekly_training_plan","2026-07-22","2026-07-28",1,1,"1","{}","x","e"*64,1,"2026-07-22T00:00:00Z")])
    conn.execute("INSERT INTO training_plans(id,subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,created_at_utc) VALUES(1,1,4,'2026-07-22','2026-07-28','Asia/Singapore','active','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind) VALUES(1,0,'2026-07-22','rest')")
    conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(1,'garmin','daily','2026-07-22','fetched','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(1,'garmin','activity_inventory','2026-07-22','fetched','2026-07-22T00:01:00Z')")
    conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(2,'garmin','daily','2026-07-22','fetched','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,catalog_version) VALUES(1,'daily','local_date','1')")
    conn.execute("INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,catalog_version) VALUES(2,'daily','local_date','1')")
    conn.execute("INSERT INTO garmin_sync_gaps(subject_id,resource_kind,window_start_local_date,window_end_local_date,reason_code,status,first_seen_at_utc) VALUES(1,'daily','2026-07-22','2026-07-22','x','open','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO garmin_sync_gaps(subject_id,resource_kind,window_start_local_date,window_end_local_date,reason_code,status,first_seen_at_utc) VALUES(2,'daily','2026-07-22','2026-07-22','x','open','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO data_quality_issues(entity_type,entity_id,issue_code,severity,status,first_seen_at_utc,last_seen_at_utc) VALUES('activity',1,'x','warning','open','2026-07-22T00:00:00Z','2026-07-22T00:00:00Z')")
    conn.execute("INSERT INTO data_quality_issues(entity_type,entity_id,issue_code,severity,status,first_seen_at_utc,last_seen_at_utc) VALUES('activity',2,'x','warning','open','2026-07-22T00:00:00Z','2026-07-22T00:00:00Z')")
    return conn, StableViewRepository(conn)


def test_real_foundation_allowlist_subject_isolation_and_stable_snapshot(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    first = repo.snapshot(1, "2026-07-22", "2026-07-22")
    second = repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert first == second
    assert all(rows for rows in first.views.values())
    assert all(row["subject_id"] == 1 for rows in first.views.values() for row in rows)
    assert [row["provider_activity_id"] for row in first.views["v_current_activities"]] == ["one"]
    assert all("extras_json" not in row and "source_map_json" not in row for rows in first.views.values() for row in rows)
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    assert first.subject_context is not None and first.subject_context.__dict__ == {"subject_id": 1, "timezone": "Asia/Singapore", "provider": "garmin", "identity_kind": "account", "verified": True}
    assert [item.operation for item in first.audit] == [f"view:{name}" for name in first.views] + ["coverage", "cursors", "gaps", "activity_stage", "quality", "facts", "capabilities", "plan_reasons"]
    assert all(item.subject_id == 1 and item.start_local_date == "2026-07-22" and item.end_local_date == "2026-07-22" for item in first.audit)
    assert all("sql" not in item.__dict__ and "payload" not in item.__dict__ for item in first.audit)
    assert all(row.get("subject_id", 1) == 1 for row in [*first.coverage, *first.cursors, *first.gaps, *first.activity_stages, *first.quality_issues, *first.facts])
    with pytest.raises(StableViewError): repo.view("activities", 1, "2026-07-22", "2026-07-22")


def test_activity_stages_project_independent_summary_fit_fallback_and_inventory_evidence(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    first = repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages
    assert len(first) == 1
    stage = first[0]
    assert {"summary_ready", "fit_core_ready", "fallback_ready", "inventory_coverage_state"} <= set(stage)
    assert stage["summary_ready"] == 1 and stage["fit_core_ready"] == 1 and stage["fallback_ready"] == 0
    assert stage["summary_relation_count"] == 1 and stage["fit_relation_count"] == 1
    assert stage["inventory_coverage_state"] == "fetched"
    conn.execute("DELETE FROM resource_coverage WHERE subject_id=1 AND resource_kind='activity_inventory'")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["inventory_coverage_state"] is None
    conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(1,'garmin','activity_inventory','2026-07-22','fetched','2026-07-22T00:01:00Z')")
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(4,'garmin','activity_details_fallback','one',1,?,1,'2026-07-22T02:00:00Z')", ("d" * 64,))
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,4,'details_json_fallback',1)")
    stage = repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]
    assert stage["summary_ready"] == 1 and stage["fit_core_ready"] == 1 and stage["fallback_ready"] == 1


def test_activity_stages_fail_closed_for_unparsed_noncurrent_cross_provider_and_duplicate_roles(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    conn.execute("UPDATE source_revisions SET parsed_at_utc=NULL WHERE id=3")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["summary_ready"] == 0
    conn.execute("UPDATE source_revisions SET parsed_at_utc='2026-07-22T02:00:00Z' WHERE id=3")
    conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=1")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["fit_core_ready"] == 0
    conn.execute("UPDATE source_revisions SET is_current=1,provider='other' WHERE id=1")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["fit_core_ready"] == 0
    conn.execute("DROP INDEX ux_activity_source_role_active")
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(5,'garmin','activity_summary','summary-two',1,?,1,'2026-07-22T02:00:00Z')", ("e" * 64,))
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,5,'summary_json',1)")
    stage = repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]
    assert stage["summary_relation_count"] == 2 and stage["summary_ready"] == 0


def test_activity_stages_require_role_resource_kind_and_provider_activity_identity(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    conn.execute("UPDATE source_revisions SET resource_kind='wrong_summary_kind' WHERE id=3")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["summary_ready"] == 0
    conn.execute("UPDATE source_revisions SET resource_kind='activity_summary',provider_object_id='other-activity' WHERE id=3")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["summary_ready"] == 0
    conn.execute("UPDATE source_revisions SET provider_object_id='one',resource_kind='wrong_fit_kind' WHERE id=1")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["fit_core_ready"] == 0
    conn.execute("UPDATE source_revisions SET resource_kind='activity_fit',provider_object_id='other-activity' WHERE id=1")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["fit_core_ready"] == 0
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(4,'garmin','activity_details_fallback','one',1,?,1,'2026-07-22T02:00:00Z')", ("d" * 64,))
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,4,'details_json_fallback',1)")
    conn.execute("UPDATE source_revisions SET resource_kind='activity_fit' WHERE id=4")
    assert repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages[0]["fallback_ready"] == 0


def test_activity_stages_enforce_subject_date_and_provider_state_boundaries(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(2,'garmin','account','subject-two-secret-hmac',1,'2026-07-24T00:00:00Z','2026-07-24T00:00:00Z')")
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date,provider_state) VALUES(4,2,'garmin','other-subject','2026-07-22T01:00:00Z','2026-07-22','active')")
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(4,3,'summary_json',1)")
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date,provider_state) VALUES(5,1,'garmin','deleted','2026-07-22T01:00:00Z','2026-07-22','provider_deleted')")
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(5,3,'summary_json',1)")
    assert [row["id"] for row in repo.snapshot(1, "2026-07-22", "2026-07-22").activity_stages] == [1]
    second_stages = repo.snapshot(2, "2026-07-22", "2026-07-22").activity_stages
    assert [row["id"] for row in second_stages] == [2, 4]
    # Revision 3 belongs to provider activity "one", not activity 4.
    assert next(row for row in second_stages if row["id"] == 4)["summary_ready"] == 0


def test_technical_samples_require_current_parsed_fit_identity_relation(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    assert repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)["count"] == 3
    # An active non-FIT role cannot authorize an activity sample stream.
    conn.execute("UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=1 AND source_role='summary_json'")
    conn.execute("UPDATE activity_source_revisions SET source_role='summary_json' WHERE activity_id=1 AND source_revision_id=1")
    assert repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)["count"] == 0


@pytest.mark.parametrize("column,value", (("resource_kind", "wrong_fit_kind"), ("provider_object_id", "other-activity")))
def test_technical_samples_reject_wrong_fit_revision_identity(tmp_path: Path, column: str, value: str) -> None:
    conn, repo = repository(tmp_path)
    conn.execute(f"UPDATE source_revisions SET {column}=? WHERE id=1", (value,))
    assert repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)["count"] == 0


def test_technical_samples_reject_cross_activity_reused_fit_revision(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(4,2,'garmin','other-activity','2026-07-22T01:00:00Z','2026-07-22')")
    conn.execute("INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(4,1,'activity_fit',1)")
    conn.execute("INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,heart_rate_bpm) VALUES(4,1,'record',1,'2026-07-22T01:00:00Z',333)")
    assert repo.technical_samples(2, 4, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)["count"] == 0


def test_fixed_projections_exclude_sensitive_or_raw_fields_and_limits_are_strict(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    snapshot = repo.snapshot(1, "2026-07-22", "2026-07-22")
    forbidden = {"extras_json", "source_map_json", "raw_value_json", "payload_json", "body_text", "identity_hmac", "latitude", "longitude", "token", "password"}
    rows = [row for values in snapshot.views.values() for row in values]
    rows.extend([*snapshot.coverage, *snapshot.cursors, *snapshot.gaps, *snapshot.activity_stages, *snapshot.quality_issues, *snapshot.facts, *snapshot.capabilities, *snapshot.plan_reasons])
    assert not any(forbidden & set(row) for row in rows)
    for limit in (True, -1, 0, 501, 1.0, "1"):
        with pytest.raises(StableViewError):
            repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22", limit=limit)  # type: ignore[arg-type]
    for limit in (True, -1, 0, 101, 1.0, "1"):
        with pytest.raises(StableViewError):
            repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=limit)  # type: ignore[arg-type]


def test_snapshot_rejects_invalid_scope_and_restores_transaction_state(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    with pytest.raises(StableViewError): repo.snapshot(True, "2026-07-22", "2026-07-22")
    with pytest.raises(StableViewError): repo.snapshot(1, "bad", "2026-07-22")
    with pytest.raises(StableViewError): repo.view("v_current_activities", 1, "2026-07-23", "2026-07-22")
    for limit in (True, 1.5, "1"):
        with pytest.raises(StableViewError): repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22", limit=limit)  # type: ignore[arg-type]
    conn.execute("BEGIN")
    with pytest.raises(StableViewError, match="caller_transaction_active"):
        repo.snapshot(1, "2026-07-22", "2026-07-22")
    conn.execute("ROLLBACK")
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unverified", "wrong_kind", "wrong_provider", "other_subject", "inactive", "timezone", "malformed"])
def test_snapshot_subject_context_fails_closed_without_audit_or_sensitive_error(tmp_path: Path, mutation: str) -> None:
    conn, repo = repository(tmp_path)
    if mutation == "missing": conn.execute("DELETE FROM subject_identities WHERE subject_id=1")
    elif mutation == "duplicate": conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(1,'garmin','account','second-secret-hmac',1,'2026-07-24T00:00:00Z','2026-07-24T00:00:00Z')")
    elif mutation == "unverified": conn.execute("UPDATE subject_identities SET is_verified=0 WHERE subject_id=1")
    elif mutation == "wrong_kind": conn.execute("UPDATE subject_identities SET identity_kind='device' WHERE subject_id=1")
    elif mutation == "wrong_provider": conn.execute("UPDATE subject_identities SET provider='other' WHERE subject_id=1")
    elif mutation == "other_subject":
        conn.execute("DELETE FROM subject_identities WHERE subject_id=1")
        conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(2,'garmin','account','other-subject-secret-hmac',1,'2026-07-24T00:00:00Z','2026-07-24T00:00:00Z')")
    elif mutation == "inactive": conn.execute("UPDATE data_subjects SET is_active=0 WHERE id=1")
    elif mutation == "timezone": conn.execute("UPDATE data_subjects SET timezone='UTC' WHERE id=1")
    else:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE subject_identities SET is_verified=2 WHERE subject_id=1")
        conn.execute("PRAGMA ignore_check_constraints=OFF")
    before = conn.total_changes
    with pytest.raises(StableViewError, match="subject_context_invalid") as error: repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert repo._audit == [] and conn.total_changes == before and not conn.in_transaction
    assert "secret-hmac-never-leak" not in str(error.value)


def test_snapshot_uses_one_file_backed_read_generation_despite_writer_commit(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    database_path = conn.execute("PRAGMA database_list").fetchone()[2]
    # WAL permits the writer to commit while the repository holds its read
    # transaction.  The hook runs after the first snapshot read, before any
    # allowlist view or auxiliary projection is read.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.create_function("caller_owned_snapshot_function", 0, lambda: "unchanged")
    writer = sqlite3.connect(database_path, isolation_level=None)
    try:
        def commit_next_generation() -> None:
            writer.execute("UPDATE activities SET name='new-generation' WHERE id=1")
            writer.execute("UPDATE resource_coverage SET availability_state='empty' WHERE subject_id=1")

        repo._snapshot_after_subject_context = commit_next_generation  # type: ignore[method-assign]
        snapshot = repo.snapshot(1, "2026-07-22", "2026-07-22")
        assert snapshot.views["v_current_activities"][0]["name"] is None
        assert snapshot.coverage[0]["availability_state"] == "fetched"
        assert writer.execute("SELECT name FROM activities WHERE id=1").fetchone()[0] == "new-generation"
        assert writer.execute("SELECT availability_state FROM resource_coverage WHERE subject_id=1").fetchone()[0] == "empty"
        assert conn.execute("SELECT caller_owned_snapshot_function()").fetchone()[0] == "unchanged"
    finally:
        writer.close()


@pytest.mark.parametrize("fault", ("commit", "rollback", "pragma_restore"))
def test_snapshot_restores_caller_connection_for_transaction_and_restore_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    before = conn.total_changes
    original_execute = repo._execute

    def injected_execute(sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        normalized = sql.strip().upper()
        if fault == "commit" and normalized == "COMMIT":
            raise sqlite3.OperationalError("injected commit failure")
        if fault == "rollback" and "V_CURRENT_DAILY_HEALTH" in normalized:
            raise sqlite3.OperationalError("injected read failure")
        if fault == "rollback" and normalized == "ROLLBACK":
            raise sqlite3.OperationalError("injected rollback failure")
        if fault == "pragma_restore" and normalized == "PRAGMA QUERY_ONLY=0":
            raise sqlite3.OperationalError("injected pragma restore failure")
        return original_execute(sql, params)

    monkeypatch.setattr(repo, "_execute", injected_execute)
    expected = "restore_failed" if fault in {"rollback", "pragma_restore"} else "read_failed"
    with pytest.raises(StableViewError, match=expected):
        repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert repo._audit == [] and conn.total_changes == before
    assert conn.row_factory is factory and not conn.in_transaction
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize("operation", ("view", "technical"))
@pytest.mark.parametrize("prior_query_only", (0, 1))
def test_standalone_reads_preserve_caller_state_on_success(
    tmp_path: Path, operation: str, prior_query_only: int
) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    conn.execute(f"PRAGMA query_only={prior_query_only}")
    if operation == "view":
        result = repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22")
        assert result[0]["subject_id"] == 1
    else:
        result = repo.technical_samples(
            1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3
        )
        assert result["count"] == 3
    assert conn.row_factory is factory and not conn.in_transaction
    assert conn.execute("PRAGMA query_only").fetchone() == (prior_query_only,)
    assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize("operation", ("view", "technical"))
def test_standalone_reads_reject_caller_transaction_without_state_change(tmp_path: Path, operation: str) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    trace: list[str] = []
    conn.execute("BEGIN")
    conn.set_trace_callback(trace.append)
    try:
        with pytest.raises(StableViewError, match="caller_transaction_active"):
            if operation == "view":
                repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22")
            else:
                repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)
        assert conn.row_factory is factory and conn.in_transaction
        assert not any("PRAGMA QUERY_ONLY" in sql.upper() for sql in trace)
    finally:
        conn.execute("ROLLBACK")
        conn.set_trace_callback(None)


@pytest.mark.parametrize("operation", ("view", "technical"))
@pytest.mark.parametrize("fault", ("sql", "commit", "rollback", "pragma_restore", "factory_restore"))
def test_standalone_reads_fail_closed_and_restore_or_report_untrusted_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, fault: str
) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    before = conn.total_changes
    original_execute, original_set_factory = repo._execute, repo._set_row_factory

    def injected_execute(sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        normalized = sql.strip().upper()
        is_query = "V_CURRENT_ACTIVITIES" in normalized if operation == "view" else "ACTIVITY_SAMPLES" in normalized
        if fault in {"sql", "rollback"} and is_query:
            raise sqlite3.OperationalError("injected query failure")
        if fault == "commit" and normalized == "COMMIT":
            raise sqlite3.OperationalError("injected commit failure")
        if fault == "rollback" and normalized == "ROLLBACK":
            raise sqlite3.OperationalError("injected rollback failure")
        if fault == "pragma_restore" and normalized == "PRAGMA QUERY_ONLY=0":
            raise sqlite3.OperationalError("injected pragma restore failure")
        return original_execute(sql, params)

    def injected_set_factory(value: object) -> None:
        if fault == "factory_restore" and value is factory:
            raise RuntimeError("injected row factory restore failure")
        original_set_factory(value)

    monkeypatch.setattr(repo, "_execute", injected_execute)
    monkeypatch.setattr(repo, "_set_row_factory", injected_set_factory)
    expected = "restore_failed" if fault in {"rollback", "pragma_restore", "factory_restore"} else "read_failed"
    with pytest.raises(StableViewError, match=expected):
        if operation == "view":
            repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22")
        else:
            repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=3)
    assert repo._audit == [] and conn.total_changes == before and not conn.in_transaction
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    # A failed row-factory restore is intentionally surfaced as untrusted
    # state rather than being hidden.  SQLite is nevertheless still usable.
    assert (conn.row_factory is sqlite3.Row) if fault == "factory_restore" else (conn.row_factory is factory)
    assert conn.execute("SELECT 1").fetchone() is not None


def test_constructor_and_failures_preserve_external_row_factory(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    assert conn.row_factory is factory
    repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22")
    assert conn.row_factory is factory
    before = conn.total_changes
    conn.execute("DROP VIEW v_current_daily_health")
    with pytest.raises(StableViewError): repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert conn.total_changes == before and conn.row_factory is factory and not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0
    assert conn.execute("SELECT 1").fetchone() == (1,)


def test_view_aux_and_total_limits_fail_without_partial_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, repo = repository(tmp_path)
    factory = lambda cursor, row: tuple(row)
    conn.row_factory = factory
    for index in range(2, 5):
        conn.execute("INSERT INTO activities(id,subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(?,1,'garmin',?,'2026-07-22T02:00:00Z','2026-07-22')", (index + 10, f"limit-{index}"))
    with pytest.raises(StableViewError, match="limit_exceeded"):
        repo.view("v_current_activities", 1, "2026-07-22", "2026-07-22", limit=2)
    assert repo._audit == []
    monkeypatch.setattr(stable_views, "_MAX_AUX_ROWS", 1)
    with pytest.raises(StableViewError, match="limit_exceeded"):
        repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert repo._audit == [] and not conn.in_transaction and conn.row_factory is factory
    monkeypatch.setattr(stable_views, "_MAX_AUX_ROWS", 500)
    monkeypatch.setattr(stable_views, "_MAX_SNAPSHOT_ROWS", 1)
    with pytest.raises(StableViewError, match="total_limit_exceeded"):
        repo.snapshot(1, "2026-07-22", "2026-07-22")
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0 and conn.row_factory is factory


def test_technical_samples_are_current_subject_scoped_and_bounded(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    result = repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=2)
    assert result == {"activity_id": 1, "metric": "heart_rate_bpm", "start_utc": "2026-07-22T00:00:00Z", "end_utc": "2026-07-22T02:00:00Z", "count": 2, "minimum": 100.0, "maximum": 110.0, "latest": 110.0, "truncated": True}
    assert repo._audit[-1].__dict__ == {
        "operation": "technical_samples",
        "subject_id": 1,
        "start_local_date": "2026-07-22T00:00:00Z",
        "end_local_date": "2026-07-22T02:00:00Z",
        "row_count": 3,
    }
    assert "value" not in repo._audit[-1].__dict__ and "payload" not in repo._audit[-1].__dict__
    empty = repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T03:00:00Z", "2026-07-22T04:00:00Z", limit=2)
    assert empty["count"] == 0 and empty["minimum"] is None and not empty["truncated"]
    assert repo.technical_samples(2, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=2)["count"] == 0
    fractional = repo.technical_samples(
        1,
        1,
        "heart_rate_bpm",
        "2026-07-22T00:00:00.000001Z",
        "2026-07-22T02:00:00.123456Z",
        limit=3,
    )
    assert fractional["count"] == 3 and not fractional["truncated"]
    assert fractional["start_utc"] == "2026-07-22T00:00:00.000001Z"
    assert fractional["end_utc"] == "2026-07-22T02:00:00.123456Z"
    _, just_before_second = stable_views._utc("2026-07-22T01:00:00.999999Z")
    _, following_second = stable_views._utc("2026-07-22T01:00:01Z")
    assert just_before_second < following_second
    factory = lambda cursor, row: tuple(row); conn.row_factory = factory
    conn.execute("DROP TABLE activity_samples")
    with pytest.raises(StableViewError): repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T02:00:00Z", limit=2)
    assert repo._audit == []
    assert conn.row_factory is factory and not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0 and conn.execute("SELECT 1").fetchone() == (1,)


def test_technical_samples_canonicalize_mixed_seconds_and_exclude_bad_storage(tmp_path: Path) -> None:
    conn, repo = repository(tmp_path)
    conn.executemany(
        "INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,heart_rate_bpm) VALUES(?,?,?,?,?,?)",
        [
            (1, 1, "record", 10, "2026-07-22T01:00:00.000001Z", 101),
            (1, 1, "record", 11, "2026-07-22T01:00:00.500000Z", 150),
            (1, 1, "record", 12, "2026-07-22T01:00:01Z", 102),
            # Stored timestamp validation is fail-closed: malformed values do
            # not affect range membership, ordering, limits or statistics.
            (1, 1, "record", 13, "2026-07-22T01:00:00.1234567Z", 999),
            (1, 1, "record", 14, "2026-02-30T01:00:00Z", 998),
            (1, 1, "record", 15, "2026-07-22T01:00:00Z' OR 1=1 --", 997),
        ],
    )
    endpoints = repo.technical_samples(
        1, 1, "heart_rate_bpm", "2026-07-22T01:00:00.000001Z", "2026-07-22T01:00:00.500000Z", limit=4
    )
    assert endpoints == {
        "activity_id": 1,
        "metric": "heart_rate_bpm",
        "start_utc": "2026-07-22T01:00:00.000001Z",
        "end_utc": "2026-07-22T01:00:00.500000Z",
        "count": 2,
        "minimum": 101.0,
        "maximum": 150.0,
        "latest": 150.0,
        "truncated": False,
    }
    bounded = repo.technical_samples(
        1, 1, "heart_rate_bpm", "2026-07-22T01:00:00Z", "2026-07-22T01:00:01Z", limit=3
    )
    assert bounded["count"] == 3 and bounded["minimum"] == 100.0
    assert bounded["maximum"] == 150.0 and bounded["latest"] == 150.0 and bounded["truncated"]
    all_points = repo.technical_samples(
        1, 1, "heart_rate_bpm", "2026-07-22T01:00:00Z", "2026-07-22T01:00:01Z", limit=4
    )
    assert all_points["count"] == 4 and all_points["latest"] == 102.0 and not all_points["truncated"]


@pytest.mark.parametrize("metric", ("heart_rate_bpm", "cadence_rpm", "power_w", "speed_mps", "altitude_m", "temperature_c"))
def test_technical_samples_exclude_non_numeric_metric_storage(tmp_path: Path, metric: str) -> None:
    conn, repo = repository(tmp_path)
    # This is a caller-owned function name used to prove the repository no
    # longer registers, replaces or unregisters connection functions.
    conn.create_function("trainlab_sample_utc_key", 1, lambda value: "caller-owned")
    assert conn.execute("SELECT trainlab_sample_utc_key('x')").fetchone()[0] == "caller-owned"
    sql = f"INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,{metric}) VALUES(?,?,?,?,?,?)"
    conn.executemany(
        sql,
        [
            (1, 1, "record", 100, "2026-07-22T01:10:00Z", 1),
            (1, 1, "record", 101, "2026-07-22T01:10:01Z", 2.5),
            (1, 1, "record", 102, "2026-07-22T01:10:02Z", 0),
            (1, 1, "record", 103, "2026-07-22T01:10:03Z", "PRIVATE_METRIC"),
            (1, 1, "record", 104, "2026-07-22T01:10:04Z", sqlite3.Binary(b"PRIVATE_METRIC")),
            (1, 1, "record", 105, "2026-07-22T01:10:05Z", float("inf")),
            (1, 1, "record", 106, "2026-07-22T01:10:06Z", float("nan")),
            (1, 1, "record", 107, "2026-07-22T01:10:07Z", float("-inf")),
        ],
    )
    short = repo.technical_samples(1, 1, metric, "2026-07-22T01:10:00Z", "2026-07-22T01:10:07Z", limit=2)
    assert short["count"] == 2 and short["minimum"] == 1.0 and short["maximum"] == 2.5
    assert short["latest"] == 2.5 and short["truncated"]
    full = repo.technical_samples(1, 1, metric, "2026-07-22T01:10:00Z", "2026-07-22T01:10:07Z", limit=3)
    assert full["count"] == 3 and full["minimum"] == 0.0 and full["maximum"] == 2.5
    assert full["latest"] == 0.0 and not full["truncated"]
    assert all("PRIVATE_METRIC" not in str(item) for item in repo._audit)
    assert conn.execute("SELECT trainlab_sample_utc_key('x')").fetchone()[0] == "caller-owned"
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0


def test_technical_samples_defensively_reject_unexpected_aggregate_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, repo = repository(tmp_path)
    repo._audit.append(stable_views.QueryAudit("technical_samples", 1, "a", "b", 1))
    monkeypatch.setattr(repo, "_read", lambda *args, **kwargs: ({"value": "PRIVATE_METRIC"},))
    with pytest.raises(StableViewError, match="analysis_sample_value_invalid") as error:
        repo.technical_samples(1, 1, "heart_rate_bpm", "2026-07-22T01:00:00Z", "2026-07-22T01:00:01Z", limit=1)
    assert "PRIVATE_METRIC" not in str(error.value) and repo._audit == []


@pytest.mark.parametrize(
    "subject,activity,metric,start,end,limit",
    [
        (True, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (0, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (-1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1.0, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        ("1", 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, True, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 0, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "unknown", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, True, "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, ["heart_rate_bpm"], "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22 00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00+00:00", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00,123456Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.000000Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.1Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.12Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.123Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.1234Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.12345Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00.1234567Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-02-30T00:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", None, "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T01:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T02:00:00Z", "2026-07-22T01:00:00Z", 1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", True),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 0),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", -1),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", 1.0),
        (1, 1, "heart_rate_bpm", "2026-07-22T00:00:00Z", "2026-07-22T01:00:00Z", "1"),
    ],
)
def test_technical_samples_reject_invalid_before_query(tmp_path: Path, subject: object, activity: object, metric: object, start: object, end: object, limit: object) -> None:
    conn, repo = repository(tmp_path); before = conn.total_changes; trace: list[str] = []; conn.set_trace_callback(trace.append)
    with pytest.raises(StableViewError): repo.technical_samples(subject, activity, metric, start, end, limit=limit)  # type: ignore[arg-type]
    assert repo._audit == [] and conn.total_changes == before and not any("activity_samples" in sql.lower() for sql in trace)
