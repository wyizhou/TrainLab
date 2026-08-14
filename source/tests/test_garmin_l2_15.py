"""L2-15 collection quality facts stay deterministic, safe and read-only."""

from __future__ import annotations

import sqlite3

from src.garmin_catalog import CATALOG_VERSION, RESOURCE_CATALOG
from src.garmin_quality import collection_integrity_facts, week_readiness


def _database(tmp_path):
    path = tmp_path / "quality.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, timezone TEXT, is_active INTEGER);
        CREATE TABLE garmin_resource_capabilities(id INTEGER PRIMARY KEY, subject_id INTEGER, environment_key TEXT, resource_kind TEXT, capability_state TEXT, last_checked_at_utc TEXT);
        CREATE TABLE resource_coverage(id INTEGER PRIMARY KEY, subject_id INTEGER, provider TEXT, resource_kind TEXT, local_date TEXT, availability_state TEXT, record_count INTEGER, observed_at_utc TEXT);
        CREATE TABLE garmin_sync_cursors(id INTEGER PRIMARY KEY, subject_id INTEGER, resource_kind TEXT, complete_through_local_date TEXT, cursor_grain TEXT, catalog_version TEXT);
        CREATE TABLE garmin_sync_gaps(id INTEGER PRIMARY KEY, subject_id INTEGER, resource_kind TEXT, logical_object_key TEXT, window_start_local_date TEXT, window_end_local_date TEXT, status TEXT);
        CREATE TABLE activities(id INTEGER PRIMARY KEY, subject_id INTEGER, provider TEXT, local_date TEXT, provider_state TEXT);
        CREATE TABLE source_revisions(id INTEGER PRIMARY KEY, resource_kind TEXT, is_current INTEGER, parsed_at_utc TEXT);
        CREATE TABLE activity_source_revisions(activity_id INTEGER, source_revision_id INTEGER, source_role TEXT, is_active INTEGER);
        CREATE TABLE data_quality_issues(entity_type TEXT, entity_id INTEGER, severity TEXT, status TEXT);
        CREATE TABLE sleep_sessions(id INTEGER PRIMARY KEY, subject_id INTEGER, start_time_utc TEXT, end_time_utc TEXT);
        CREATE TABLE sleep_stages(sleep_session_id INTEGER, start_time_utc TEXT, end_time_utc TEXT);
        CREATE TABLE activity_samples(activity_id INTEGER, source_revision_id INTEGER, stream_kind TEXT, sample_index INTEGER, timestamp_utc TEXT);
        CREATE TABLE reconciliation_results(entity_type TEXT, entity_id INTEGER, result TEXT);
        """
    )
    conn.execute("INSERT INTO data_subjects VALUES(1,'Asia/Hong_Kong',1)")
    for spec in RESOURCE_CATALOG.values():
        if not (spec.cursor_eligible and spec.scope in {"daily", "range"}):
            continue
        conn.execute(
            "INSERT INTO garmin_resource_capabilities(subject_id,environment_key,resource_kind,capability_state,last_checked_at_utc) VALUES(1,'global',?,'supported','2026-07-24T00:00:00Z')",
            (spec.resource_kind,),
        )
        conn.execute(
            "INSERT INTO garmin_sync_cursors(subject_id,resource_kind,complete_through_local_date,cursor_grain,catalog_version) VALUES(1,?,'2026-07-20','local_date',?)",
            (spec.resource_kind, CATALOG_VERSION),
        )
        for day in range(14, 21):
            conn.execute(
                "INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,record_count,observed_at_utc) VALUES(1,'garmin',?,?,'fetched',1,'2026-07-21T00:00:00Z')",
                (spec.resource_kind, f"2026-07-{day}"),
            )
    conn.commit()
    conn.close()
    return path


def test_ready_and_read_only(tmp_path):
    path = _database(tmp_path)
    before = path.read_bytes()
    result = week_readiness(str(path), 1, "2026-07-20")
    assert result.state == "ready"
    assert result.evidence_version == "garmin-quality-v1"
    assert result.blockers == () and result.warnings == ()
    assert path.read_bytes() == before


def test_new_completed_coverage_replaces_snapshot_partial(tmp_path):
    path = _database(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,record_count,observed_at_utc) VALUES(1,'garmin','steps','2026-07-20','partial',0,'2026-07-20T01:00:00Z')"
    )
    conn.execute(
        "INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,record_count,observed_at_utc) VALUES(1,'garmin','steps','2026-07-20','fetched',1,'2026-07-21T01:00:00Z')"
    )
    conn.commit()
    conn.close()
    assert week_readiness(str(path), 1, "2026-07-20").state == "ready"


def test_gap_and_activity_stage_block_without_payload_leak(tmp_path):
    path = _database(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO garmin_sync_gaps VALUES(1,1,'steps','PRIVATE-HEALTH-PAYLOAD','2026-07-20','2026-07-20','open')"
    )
    conn.execute("INSERT INTO activities VALUES(9,1,'garmin','2026-07-20','active')")
    conn.execute(
        "INSERT INTO source_revisions VALUES(1,'activity_summary',1,'2026-07-20T00:00:00Z')"
    )
    conn.execute("INSERT INTO activity_source_revisions VALUES(9,1,'summary_json',1)")
    conn.commit()
    conn.close()
    result = week_readiness(str(path), 1, "2026-07-20")
    assert result.state == "blocked"
    assert {reason.code for reason in result.blockers} >= {
        "gap_open",
        "activity_fit_or_fallback_incomplete",
    }
    assert "PRIVATE" not in repr(result)


def test_optional_capability_warns_but_required_unavailable_blocks(tmp_path):
    path = _database(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE garmin_resource_capabilities SET capability_state='not_supported' WHERE resource_kind='floors'"
    )
    conn.commit()
    conn.close()
    assert week_readiness(str(path), 1, "2026-07-20").state == "ready_with_warnings"
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE garmin_resource_capabilities SET capability_state='not_supported' WHERE resource_kind='steps'"
    )
    conn.commit()
    conn.close()
    assert week_readiness(str(path), 1, "2026-07-20").state == "blocked"


def test_subject_isolation_and_integrity_facts(tmp_path):
    path = _database(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO data_subjects VALUES(2,'Asia/Hong_Kong',1)")
    # An unscoped / other-subject activity issue must not poison subject 1.
    conn.execute("INSERT INTO activities VALUES(20,2,'garmin','2026-07-20','active')")
    conn.execute("INSERT INTO data_quality_issues VALUES('activity',20,'error','open')")
    conn.execute(
        "INSERT INTO sleep_sessions VALUES(1,1,'2026-07-20T00:00:00Z','2026-07-20T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO sleep_stages VALUES(1,'2026-07-19T23:59:00Z','2026-07-20T01:00:00Z')"
    )
    conn.commit()
    conn.close()
    assert week_readiness(str(path), 1, "2026-07-20").state == "ready"
    facts = collection_integrity_facts(str(path), 1, "2026-07-20")
    assert any(fact.check == "sleep_stage_outside_session" for fact in facts)


def test_integrity_facts_do_not_leak_an_old_sleep_error_into_current_week(tmp_path):
    path = _database(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO sleep_sessions VALUES(1,1,'2026-06-01T00:00:00Z','2026-06-01T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO sleep_stages VALUES(1,'2026-05-31T23:59:00Z','2026-06-01T01:00:00Z')"
    )
    conn.commit()
    conn.close()
    assert all(
        fact.check != "sleep_stage_outside_session"
        for fact in collection_integrity_facts(str(path), 1, "2026-07-20")
    )


def test_database_failure_is_conservative_and_sanitized(tmp_path):
    path = _database(tmp_path)
    # Remove a required table after setup: evaluation must not expose SQLite text.
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE resource_coverage")
    conn.commit()
    conn.close()
    result = week_readiness(str(path), 1, "2026-07-20")
    assert result.state == "blocked"
    assert result.blockers[0].code == "quality_evaluation_failed"
    assert "no such table" not in repr(result)
