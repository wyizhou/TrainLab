from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from .foundation_v1_fixture import create_published_v1_database
from trainlab.foundation import (
    FOUNDATION_SCHEMA_VERSION,
    LEGACY_V1_MANIFEST_SHA256,
    LEGACY_V2_MANIFEST_SHA256,
    MAIL_PROCESSING_STATES,
    FoundationConfig,
    FoundationRequest,
    FoundationTool,
    validate_schema_manifest,
)


UTC = "2026-07-23T00:00:00Z"


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def request(mode: str, target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode, f"mail-processing-{mode}", UTC, target)


def test_fresh_init_accepts_frozen_states_legacy_values_and_rejects_invalid(tmp_path: Path) -> None:
    root = tmp_path / "fresh"; instance = FoundationTool(config(root))
    assert instance.execute(request("init")).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('fresh-subject',?)", (UTC,))
        subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
        conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id) VALUES(?,?)", (subject, "fresh-thread"))
        thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]
        assert conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role) VALUES(?,?,?,?)", (thread, "default", "inbound", "user")).rowcount == 1
        assert conn.execute("SELECT processing_state FROM mail_messages WHERE provider_message_id='default'").fetchone()[0] == "discovered"
        for index, state in enumerate(MAIL_PROCESSING_STATES):
            conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,processing_state) VALUES(?,?,?,?,?)", (thread, f"state-{index}", "inbound", "user", state))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,processing_state) VALUES(?,?,?,?,?)", (thread, "invalid", "inbound", "user", "not_a_frozen_state"))
    finally:
        conn.close()


def test_explicit_v1_migration_preserves_rows_is_idempotent_and_init_never_upgrades(tmp_path: Path) -> None:
    root = tmp_path / "legacy"; instance = create_published_v1_database(root)
    seed = sqlite3.connect(root / "data.db")
    seed.execute("PRAGMA foreign_keys=ON")
    seed.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('legacy-subject',?)", (UTC,))
    subject = seed.execute("SELECT id FROM data_subjects").fetchone()[0]
    seed.execute("INSERT INTO mail_threads(subject_id,provider_thread_id) VALUES(?,?)", (subject, "legacy-thread"))
    thread = seed.execute("SELECT id FROM mail_threads").fetchone()[0]
    seed.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,body_text,body_sha256,processing_state) VALUES(?,?,?,?,?,?,?)", (thread, "legacy-message", "inbound", "user", "legacy body", hashlib.sha256(b"legacy body").hexdigest(), "new"))
    seed.commit(); seed.close()
    db_before = (root / "data.db").read_bytes()
    historical_mode = (root / "raw" / "garmin").stat().st_mode & 0o777
    assert historical_mode == 0o755
    assert instance.execute(request("status")).status == "incompatible"
    assert instance.execute(request("verify")).status == "incompatible"
    assert (root / "raw" / "garmin").stat().st_mode & 0o777 == historical_mode
    before = instance.execute(request("init"))
    assert before.status == "incompatible" and before.next_action == "explicit_migrate"
    assert (root / "data.db").read_bytes() == db_before
    # Published v1 created these intermediate directories with the process
    migrated = instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION))
    assert migrated.status == "initialized" and migrated.ready
    assert all((root / "raw" / name).stat().st_mode & 0o777 == 0o700 for name in ("garmin", "gmail", "legacy"))
    assert migrated.migration_start_version == 1 and migrated.migration_end_version == FOUNDATION_SCHEMA_VERSION
    conn = sqlite3.connect(root / "data.db")
    try:
        assert conn.execute("SELECT body_text,processing_state FROM mail_messages WHERE provider_message_id='legacy-message'").fetchone() == ("legacy body", "new")
        assert conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,), (3,)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert validate_schema_manifest(conn, instance._manifest()) == []
    finally:
        conn.close()
    assert instance.execute(request("init")).status == "already_initialized"
    before_second = (root / "data.db").read_bytes()
    repeated = instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION))
    assert repeated.status == "already_initialized"
    assert (root / "data.db").read_bytes() == before_second


@pytest.mark.parametrize("mutation", ("marker", "migration", "ddl", "extra_object", "missing_view"))
def test_only_exact_published_v1_is_admitted_before_any_database_write(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / mutation; instance = create_published_v1_database(root)
    marker = root / "state" / "foundation-ready.json"
    if mutation == "marker":
        marker.write_text(json.dumps({"schema_version": 1, "manifest_sha256": "forged", "ready": True, "initialized_at_utc": UTC}), encoding="utf-8")
        marker.chmod(0o600)
    else:
        conn = sqlite3.connect(root / "data.db")
        if mutation == "migration":
            conn.execute("UPDATE schema_migrations SET content_sha256='forged' WHERE version=1")
        elif mutation == "ddl":
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute("UPDATE sqlite_master SET sql=replace(sql,\"DEFAULT 'new'\",\"DEFAULT 'forged'\") WHERE type='table' AND name='mail_messages'")
            conn.execute("PRAGMA writable_schema=OFF")
        elif mutation == "extra_object":
            conn.execute("CREATE TABLE forged_extra (id INTEGER)")
        else:
            conn.execute("DROP VIEW v_current_mail_messages")
        conn.commit(); conn.close()
    before_db = (root / "data.db").read_bytes()
    before_marker = marker.read_bytes()
    receipt = instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert (root / "data.db").read_bytes() == before_db
    assert marker.read_bytes() == before_marker


def test_marker_republish_requires_completed_verified_v3_database(tmp_path: Path) -> None:
    root = tmp_path / "republish"; instance = create_published_v1_database(root)
    assert instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION)).status == "initialized"
    marker = root / "state" / "foundation-ready.json"
    legacy_marker = json.dumps({"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True, "initialized_at_utc": UTC}).encode()
    marker.write_bytes(legacy_marker); marker.chmod(0o600)
    repaired = instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION))
    assert repaired.status == "initialized" and repaired.warnings[0]["code"] == "migration_marker_republished"
    marker.write_bytes(legacy_marker); marker.chmod(0o600)
    conn = sqlite3.connect(root / "data.db"); conn.execute("CREATE TABLE v2_forged_extra (id INTEGER)"); conn.commit(); conn.close()
    rejected = instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION))
    assert rejected.status == "incompatible" and marker.read_bytes() == legacy_marker
