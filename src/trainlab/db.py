from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .util import iso_utc


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_files (
    id INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    parser_kind TEXT NOT NULL,
    parser_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing','complete','error','superseded')),
    attempts INTEGER NOT NULL DEFAULT 1,
    error_text TEXT,
    first_seen_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    UNIQUE (sha256, parser_kind, parser_version)
);
CREATE INDEX IF NOT EXISTS idx_ingest_files_path ON ingest_files(relative_path, id DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_files_status ON ingest_files(status);

CREATE TABLE IF NOT EXISTS health_records (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES ingest_files(id),
    sheet_name TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    record_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    observed_start_utc TEXT,
    observed_end_utc TEXT,
    local_date TEXT,
    source_name TEXT,
    raw_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    UNIQUE(record_key, revision)
);
CREATE INDEX IF NOT EXISTS idx_health_records_current_date ON health_records(is_current, local_date);

CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY,
    health_record_id INTEGER NOT NULL REFERENCES health_records(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('number','text','boolean','datetime','date','duration','null')),
    value_number REAL,
    value_text TEXT,
    raw_unit TEXT,
    standard_unit TEXT,
    source_name TEXT,
    raw_json TEXT,
    UNIQUE(health_record_id, metric_key, display_name)
);
CREATE INDEX IF NOT EXISTS idx_health_metrics_key ON health_metrics(metric_key, health_record_id);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES ingest_files(id),
    source_key TEXT NOT NULL UNIQUE,
    fit_session_uuid TEXT,
    fallback_fingerprint TEXT NOT NULL,
    sport_type TEXT NOT NULL,
    sport_subtype TEXT,
    start_time_utc TEXT NOT NULL,
    end_time_utc TEXT,
    start_time_local TEXT NOT NULL,
    local_date TEXT NOT NULL,
    duration_seconds REAL,
    source_application TEXT,
    device_name TEXT,
    raw_json TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    technical_reviewed_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_sport_start ON activities(sport_type, start_time_utc DESC);
CREATE INDEX IF NOT EXISTS idx_activities_local_date ON activities(local_date);

CREATE TABLE IF NOT EXISTS activity_segments (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    segment_type TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_time_utc TEXT,
    end_time_utc TEXT,
    duration_seconds REAL,
    raw_json TEXT NOT NULL,
    UNIQUE(activity_id, segment_type, segment_index)
);

CREATE TABLE IF NOT EXISTS activity_metrics (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    segment_id INTEGER REFERENCES activity_segments(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('number','text','boolean','datetime','duration','null')),
    value_number REAL,
    value_text TEXT,
    unit TEXT,
    raw_json TEXT,
    UNIQUE(activity_id, segment_id, metric_key)
);
CREATE INDEX IF NOT EXISTS idx_activity_metrics_activity ON activity_metrics(activity_id, metric_key);

CREATE TABLE IF NOT EXISTS sensor_samples (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    timestamp_utc TEXT NOT NULL,
    sample_index INTEGER NOT NULL,
    metric_key TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('number','text','boolean')),
    value_number REAL,
    value_text TEXT,
    unit TEXT,
    raw_json TEXT,
    UNIQUE(activity_id, sample_index, metric_key)
);
CREATE INDEX IF NOT EXISTS idx_sensor_samples_activity_time ON sensor_samples(activity_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS feedback_messages (
    id INTEGER PRIMARY KEY,
    gmail_message_id TEXT NOT NULL UNIQUE,
    gmail_thread_id TEXT NOT NULL,
    in_reply_to_run_id TEXT,
    received_at_utc TEXT NOT NULL,
    reply_local_date TEXT NOT NULL,
    subject TEXT,
    body_text TEXT NOT NULL,
    structured_json TEXT,
    processed_at_utc TEXT,
    injection_risk INTEGER NOT NULL DEFAULT 0 CHECK (injection_risk IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_feedback_unprocessed ON feedback_messages(processed_at_utc, received_at_utc);

CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY,
    fact_type TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    effective_local_date TEXT NOT NULL,
    expires_local_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    scope TEXT NOT NULL CHECK (scope IN ('temporary','long_term')),
    source_feedback_id INTEGER REFERENCES feedback_messages(id),
    created_at_utc TEXT NOT NULL,
    superseded_by_id INTEGER REFERENCES user_facts(id)
);
CREATE INDEX IF NOT EXISTS idx_user_facts_active ON user_facts(is_active, fact_type, effective_local_date);

CREATE TABLE IF NOT EXISTS period_summaries (
    id INTEGER PRIMARY KEY,
    period_type TEXT NOT NULL,
    period_start_local TEXT NOT NULL,
    period_end_local TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(period_type, period_start_local, period_end_local, source_hash)
);
CREATE INDEX IF NOT EXISTS idx_period_summaries_period ON period_summaries(period_type, period_end_local DESC);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    slot TEXT NOT NULL CHECK (slot IN ('morning','evening','manual','watchdog')),
    scheduled_local_date TEXT NOT NULL,
    scheduled_local_time TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    runner TEXT,
    status TEXT NOT NULL CHECK (status IN ('started','sent','failed','skipped')),
    input_hash TEXT,
    result_json TEXT,
    error_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_schedule ON analysis_runs(scheduled_local_date, slot);

CREATE TABLE IF NOT EXISTS mail_deliveries (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    gmail_message_id TEXT,
    gmail_thread_id TEXT,
    recipient TEXT NOT NULL,
    label TEXT NOT NULL,
    subject TEXT NOT NULL,
    transport TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','sent','failed')),
    sent_at_utc TEXT,
    error_text TEXT,
    mime_headers_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mail_thread ON mail_deliveries(gmail_thread_id);

CREATE TABLE IF NOT EXISTS video_checks (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('valid','invalid','unknown')),
    http_status INTEGER,
    final_url TEXT,
    details TEXT,
    UNIQUE(url, checked_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_video_checks_url ON video_checks(url, checked_at_utc DESC);

CREATE TABLE IF NOT EXISTS strength_e1rm_candidates (
    id INTEGER PRIMARY KEY,
    exercise_key TEXT NOT NULL,
    evidence_activity_id INTEGER REFERENCES activities(id),
    weight_kg REAL NOT NULL,
    reps INTEGER NOT NULL,
    calculated_e1rm_kg REAL NOT NULL,
    to_failure INTEGER NOT NULL CHECK (to_failure IN (0,1)),
    status TEXT NOT NULL CHECK (status IN ('pending','supported','rejected')),
    reason TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE(exercise_key, evidence_activity_id, weight_kg, reps)
);
CREATE INDEX IF NOT EXISTS idx_e1rm_exercise ON strength_e1rm_candidates(exercise_key, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS strength_baselines (
    exercise_key TEXT PRIMARY KEY,
    e1rm_kg REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    source_candidate_id INTEGER NOT NULL REFERENCES strength_e1rm_candidates(id),
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER REFERENCES ingest_files(id),
    entity_kind TEXT NOT NULL,
    entity_key TEXT,
    issue_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error')),
    details_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    resolved_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_quality_open ON data_quality_issues(resolved_at_utc, severity, created_at_utc);
"""


def connect(path: Path, *, busy_timeout_ms: int = 10_000) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def migrate(connection: sqlite3.Connection) -> None:
    # sqlite3.executescript manages its own transaction boundary.
    connection.executescript(SCHEMA_SQL)
    with transaction(connection):
        row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        current = int(row["version"] or 0)
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema {current} is newer than supported schema {SCHEMA_VERSION}")
        if current < 1:
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc, description) VALUES(?,?,?)",
                (1, iso_utc(), "Initial generic health, activity, feedback, summary and audit schema"),
            )


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        "ingest_files",
        "health_records",
        "health_metrics",
        "activities",
        "activity_segments",
        "activity_metrics",
        "sensor_samples",
        "feedback_messages",
        "user_facts",
        "period_summaries",
        "analysis_runs",
        "mail_deliveries",
        "video_checks",
        "strength_e1rm_candidates",
        "strength_baselines",
        "data_quality_issues",
    ]
    return {name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in names}
