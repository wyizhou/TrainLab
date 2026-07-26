from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trainlab.foundation import (
    LEGACY_V2_ANALYSIS_ARTIFACT_INPUTS_DDL,
    LEGACY_V2_MANIFEST_SHA256,
    LEGACY_V2_SCHEMA_OBJECTS_SHA256,
    FoundationConfig,
    FoundationTool,
    TABLES,
    VIEWS,
)

from .foundation_v1_fixture import UTC, V1_SCHEMA_SUPPORT_SQL, config


def create_published_v2_database(root: Path) -> FoundationTool:
    """Reconstruct the released v2 schema without invoking v3 code."""
    root.mkdir(mode=0o700)
    raw = root / "raw"
    state = root / "state"
    for path in (
        raw, state, raw / "garmin" / "fit", raw / "garmin" / "json",
        raw / "gmail" / "json", raw / "gmail" / "attachments",
        raw / "legacy" / "health_xlsx", raw / "legacy" / "fit",
    ):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    for path in (raw / "garmin", raw / "gmail", raw / "legacy"):
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
        for name, definition in TABLES.items():
            if name == "foundation_state":
                continue
            if name == "analysis_artifact_inputs":
                definition = LEGACY_V2_ANALYSIS_ARTIFACT_INPUTS_DDL
            conn.execute(f"CREATE TABLE {name} ({definition})")
        for name, query in VIEWS.items():
            conn.execute(f"CREATE VIEW {name} AS {query}")
        for statement in V1_SCHEMA_SUPPORT_SQL:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO foundation_state VALUES(1,'ready',?,?,?,?,?)",
            (2, LEGACY_V2_MANIFEST_SHA256, UTC, UTC, "foundation-v2"),
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(1,?,?,?,?)",
            ("foundation_v1", UTC, "foundation-v1", "7cb083146962e9cd07b404d0cd24f2b251977a4c99bc0b83e71a9b743224a63c"),
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(2,?,?,?,?)",
            ("mail_processing_state_v2", UTC, "foundation-v2", LEGACY_V2_MANIFEST_SHA256),
        )
        conn.commit()
        assert FoundationTool._schema_objects_sha256(conn) == LEGACY_V2_SCHEMA_OBJECTS_SHA256
    finally:
        conn.close()
    db_path.chmod(0o600)
    marker = state / "foundation-ready.json"
    marker.write_text(json.dumps({"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True, "initialized_at_utc": UTC}), encoding="utf-8")
    marker.chmod(0o600)
    return FoundationTool(config(root))
