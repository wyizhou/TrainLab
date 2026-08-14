from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.foundation import (
    LEGACY_V1_MAIL_MESSAGES_DDL,
    LEGACY_V1_MANIFEST_SHA256,
    LEGACY_V1_SCHEMA_OBJECTS_SHA256,
    LEGACY_V2_ANALYSIS_ARTIFACT_INPUTS_DDL,
    TABLES,
    VIEWS,
    FoundationConfig,
    FoundationTool,
)

# The migration fixtures model the published Singapore-era schema exactly;
# the active schema now uses Hong Kong business time.  Keeping this explicit
# snapshot lets compatibility tests continue to prove admission of the old
# database without weakening the current production contract.
LEGACY_TABLES = dict(TABLES)
LEGACY_TABLES["data_subjects"] = LEGACY_TABLES["data_subjects"].replace(
    "DEFAULT 'Asia/Hong_Kong'", "DEFAULT 'Asia/Singapore'"
)
LEGACY_TABLES["training_plans"] = LEGACY_TABLES["training_plans"].replace(
    "CHECK(timezone='Asia/Hong_Kong')", "CHECK(timezone='Asia/Singapore')"
)


UTC = "2026-07-23T00:00:00Z"
V1_SCHEMA_SUPPORT_SQL = (
    "CREATE INDEX idx_source_revisions_current ON source_revisions(provider,resource_kind,provider_object_id,is_current)",
    "CREATE UNIQUE INDEX ux_source_revision_current ON source_revisions(provider,resource_kind,provider_object_id) WHERE is_current=1",
    "CREATE UNIQUE INDEX ux_activity_source_role_active ON activity_source_revisions(activity_id,source_role) WHERE is_active=1",
    "CREATE UNIQUE INDEX ux_daily_health_current ON daily_health(subject_id,local_date) WHERE is_current=1",
    "CREATE UNIQUE INDEX ux_analysis_artifact_current ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1",
    "CREATE UNIQUE INDEX ux_mail_response_current ON mail_response_artifacts(subject_id,mail_thread_id,response_kind) WHERE is_current=1",
    "CREATE UNIQUE INDEX ux_garmin_sync_gap_unresolved ON garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred')",
    "CREATE INDEX idx_coverage_resource_date ON resource_coverage(resource_kind,local_date)",
    "CREATE INDEX idx_activity_samples_stream ON activity_samples(activity_id,stream_kind,sample_index)",
    "CREATE TRIGGER trg_training_plan_item_window BEFORE INSERT ON training_plan_items FOR EACH ROW WHEN NEW.local_date < (SELECT plan_start_local_date FROM training_plans WHERE id=NEW.training_plan_id) OR NEW.local_date > (SELECT plan_end_local_date FROM training_plans WHERE id=NEW.training_plan_id) BEGIN SELECT RAISE(ABORT,'training_plan_item_outside_plan_window'); END",
    "CREATE TRIGGER trg_training_plan_artifact_insert BEFORE INSERT ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END",
    "CREATE TRIGGER trg_training_plan_artifact_update BEFORE UPDATE OF analysis_artifact_id ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END",
    "CREATE TRIGGER trg_climbing_route_segment_insert BEFORE INSERT ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END",
    "CREATE TRIGGER trg_climbing_route_segment_update BEFORE UPDATE OF segment_id ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END",
    "CREATE TRIGGER trg_strength_set_segment_insert BEFORE INSERT ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END",
    "CREATE TRIGGER trg_strength_set_segment_update BEFORE UPDATE OF segment_id ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END",
)


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )


def create_published_v1_database(root: Path) -> FoundationTool:
    """Reconstruct the released v1 initializer, without invoking v2 code."""
    root.mkdir(mode=0o700)
    raw = root / "raw"
    state = root / "state"
    for path in (
        raw,
        state,
        raw / "garmin" / "fit",
        raw / "garmin" / "json",
        raw / "gmail" / "json",
        raw / "gmail" / "attachments",
        raw / "legacy" / "health_xlsx",
        raw / "legacy" / "fit",
    ):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    db_path = root / "data.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE foundation_state (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL CHECK(state IN ('initializing','ready')), schema_version INTEGER NOT NULL, manifest_sha256 TEXT NOT NULL, initialized_at_utc TEXT, updated_at_utc TEXT NOT NULL, implementation_version TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at_utc TEXT NOT NULL, code_revision TEXT NOT NULL DEFAULT 'foundation-v1', content_sha256 TEXT NOT NULL)"
        )
        for name, definition in LEGACY_TABLES.items():
            if name == "foundation_state":
                continue
            legacy_definition = (
                LEGACY_V1_MAIL_MESSAGES_DDL
                if name == "mail_messages"
                else LEGACY_V2_ANALYSIS_ARTIFACT_INPUTS_DDL
                if name == "analysis_artifact_inputs"
                else definition
            )
            conn.execute(f"CREATE TABLE {name} ({legacy_definition})")
        for name, query in VIEWS.items():
            conn.execute(f"CREATE VIEW {name} AS {query}")
        for statement in V1_SCHEMA_SUPPORT_SQL:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO foundation_state VALUES(1,'ready',?,?,?,?,?)",
            (1, LEGACY_V1_MANIFEST_SHA256, UTC, UTC, "foundation-v1"),
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(1,?,?,?,?)",
            ("foundation_v1", UTC, "foundation-v1", LEGACY_V1_MANIFEST_SHA256),
        )
        conn.commit()
        assert (
            FoundationTool._schema_objects_sha256(conn)
            == LEGACY_V1_SCHEMA_OBJECTS_SHA256
        )
    finally:
        conn.close()
    db_path.chmod(0o600)
    marker = state / "foundation-ready.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_sha256": LEGACY_V1_MANIFEST_SHA256,
                "ready": True,
                "initialized_at_utc": UTC,
            }
        ),
        encoding="utf-8",
    )
    marker.chmod(0o600)
    return FoundationTool(config(root))
