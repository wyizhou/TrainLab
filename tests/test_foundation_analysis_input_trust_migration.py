from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from trainlab.foundation import (
    FOUNDATION_SCHEMA_VERSION,
    LEGACY_V2_MANIFEST_SHA256,
    FoundationRequest,
    FoundationTool,
    validate_schema_manifest,
)

from .foundation_v1_fixture import UTC, config
from .foundation_v2_fixture import create_published_v2_database


def request(mode: str, invocation: str = "analysis-input-v3", target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode, invocation, UTC, target)


def _seed_v2_inputs(root: Path) -> tuple[tuple[object, ...], ...]:
    conn = sqlite3.connect(root / "data.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)", ("migration-subject", UTC))
        subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
        conn.execute(
            "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES(?,?,?,?,?)",
            ("migration-run", subject, "daily", "started", UTC),
        )
        run = conn.execute("SELECT id FROM analysis_runs").fetchone()[0]
        for ordinal, trust in enumerate(("provider_fact", "user_asserted", "derived_statistic", "prior_model_output")):
            conn.execute(
                "INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run, f"role-{ordinal}", "fixture", None, None, "2026-07-01T00:00:00Z", "2026-07-01T23:59:59Z", hashlib.sha256(trust.encode()).hexdigest(), trust, ordinal),
            )
        conn.commit()
        return tuple(conn.execute("SELECT id,analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal FROM analysis_artifact_inputs ORDER BY id"))
    finally:
        conn.close()


def _schema_rows(root: Path) -> tuple[tuple[object, ...], ...]:
    conn = sqlite3.connect(root / "data.db")
    try:
        return tuple(conn.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name NOT IN ('analysis_artifact_inputs','foundation_state','schema_migrations') ORDER BY type,name"))
    finally:
        conn.close()


def test_explicit_v2_to_v3_rebuilds_only_analysis_inputs_and_preserves_every_old_value(tmp_path: Path) -> None:
    root = tmp_path / "v2"
    tool = create_published_v2_database(root)
    before = _seed_v2_inputs(root)
    other_schema_before = _schema_rows(root)
    raw_before = tuple((str(path.relative_to(root / "raw")), path.read_bytes() if path.is_file() else None) for path in [root / "raw", *(root / "raw").rglob("*")])

    assert tool.execute(request("status", "v2-status")).status == "incompatible"
    migrated = tool.execute(request("migrate", "v2-migrate", FOUNDATION_SCHEMA_VERSION))
    assert (migrated.status, migrated.migration_start_version, migrated.migration_end_version, migrated.applied_migration_ids) == ("initialized", 2, 3, [3])

    conn = sqlite3.connect(root / "data.db")
    try:
        after = tuple(conn.execute("SELECT id,analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal FROM analysis_artifact_inputs ORDER BY id"))
        assert after == before
        assert validate_schema_manifest(conn, tool._manifest()) == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is None
        run = conn.execute("SELECT id FROM analysis_runs WHERE run_key='migration-run'").fetchone()[0]
        for ordinal, trust in enumerate(("provider_derived", "provider_predicted", "unknown"), start=10):
            conn.execute("INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?)", (run, trust, "fixture", hashlib.sha256(trust.encode()).hexdigest(), trust, ordinal))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?)", (run, "bad", "fixture", "0" * 64, "not_a_trust_class", 99))
    finally:
        conn.close()
    assert _schema_rows(root) == other_schema_before
    assert tuple((str(path.relative_to(root / "raw")), path.read_bytes() if path.is_file() else None) for path in [root / "raw", *(root / "raw").rglob("*")]) == raw_before
    assert tool.execute(request("verify", "v3-verify")).status == "ready"
    assert tool.execute(request("migrate", "v3-repeat", FOUNDATION_SCHEMA_VERSION)).status == "already_initialized"


def test_v2_admission_rejects_lookalike_before_any_v3_write(tmp_path: Path) -> None:
    root = tmp_path / "forged"
    tool = create_published_v2_database(root)
    db_before = (root / "data.db").read_bytes()
    conn = sqlite3.connect(root / "data.db")
    conn.execute("DROP TABLE analysis_artifact_inputs")
    conn.execute("CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY, trust_class TEXT)")
    conn.commit()
    conn.close()
    receipt = tool.execute(request("migrate", "v2-forged", FOUNDATION_SCHEMA_VERSION))
    assert receipt.status == "incompatible"
    assert json.loads((root / "state" / "foundation-ready.json").read_text())["manifest_sha256"] == LEGACY_V2_MANIFEST_SHA256
    assert sqlite3.connect(root / "data.db").execute("SELECT schema_version FROM foundation_state").fetchone()[0] == 2
    assert db_before != (root / "data.db").read_bytes()  # the deliberate forge, not migration, changed it


def test_v3_transaction_failure_rolls_back_table_and_metadata(tmp_path: Path) -> None:
    root = tmp_path / "rollback"
    create_published_v2_database(root)
    before = _seed_v2_inputs(root)
    marker_before = (root / "state" / "foundation-ready.json").read_bytes()

    def fail(phase: str) -> None:
        if phase == "during_v3_migration_transaction":
            raise RuntimeError("injected")

    receipt = FoundationTool(config(root), failpoint=fail).execute(request("migrate", "v3-rollback", FOUNDATION_SCHEMA_VERSION))
    assert receipt.status == "failed"
    conn = sqlite3.connect(root / "data.db")
    try:
        assert tuple(conn.execute("SELECT id,analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal FROM analysis_artifact_inputs ORDER BY id")) == before
        assert conn.execute("SELECT schema_version,manifest_sha256,implementation_version FROM foundation_state").fetchone() == (2, LEGACY_V2_MANIFEST_SHA256, "foundation-v2")
    finally:
        conn.close()
    assert (root / "state" / "foundation-ready.json").read_bytes() == marker_before
