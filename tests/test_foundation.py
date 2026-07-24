from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
import json

from jsonschema import Draft202012Validator
from trainlab.foundation import FOUNDATION_SCHEMA_VERSION, TABLES, VIEWS, FoundationConfig, FoundationRequest, FoundationTool
from trainlab.cli import _parser


def request(mode: str, root: Path, target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode=mode, invocation_id=f"test-{mode}", requested_at_utc="2026-07-23T00:00:00Z", target_schema_version=target)


def foundation_tool(root: Path) -> FoundationTool:
    return FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock"))


def test_init_creates_full_schema_and_views(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = foundation_tool(root)
    receipt = tool.execute(request("init", root))
    assert receipt.status == "initialized"
    assert receipt.ready
    assert receipt.foundation_schema_version == FOUNDATION_SCHEMA_VERSION
    db = sqlite3.connect(root / "data.db")
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert set(TABLES) <= names
    assert set(VIEWS) <= names
    assert (root / "state" / "foundation-ready.json").exists()
    assert (root / "raw" / "garmin" / "fit").is_dir()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_init_is_strict_noop_and_read_modes_do_not_write(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = foundation_tool(root)
    assert tool.execute(request("init", root)).status == "initialized"
    db_path = root / "data.db"
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert tool.execute(request("init", root)).status == "already_initialized"
    assert tool.execute(request("status", root)).status == "ready"
    assert tool.execute(request("verify", root)).status == "ready"
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert before == after


def test_explicit_migrate_and_incompatible_roots(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = foundation_tool(root)
    assert tool.execute(request("init", root)).status == "initialized"
    assert tool.execute(request("migrate", root, FOUNDATION_SCHEMA_VERSION)).status == "already_initialized"
    assert tool.execute(request("migrate", root, FOUNDATION_SCHEMA_VERSION + 1)).status == "incompatible"
    bad = tmp_path / "bad"
    bad.mkdir()
    sqlite3.connect(bad / "data.db").close()
    assert foundation_tool(bad).execute(request("init", bad)).status == "incompatible"


def test_key_constraints_and_delivery_ownership_tables(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = foundation_tool(root)
    assert tool.execute(request("init", root)).status == "initialized"
    db = sqlite3.connect(root / "data.db")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('s','2026-01-01T00:00:00Z')")
    subject = db.execute("SELECT id FROM data_subjects").fetchone()[0]
    db.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,payload_hash) VALUES('g','x','1',1,?)", ("a" * 64,))
    revision = db.execute("SELECT id FROM source_revisions").fetchone()[0]
    db.execute("INSERT INTO activities(subject_id,provider,provider_activity_id,start_time_utc,local_date) VALUES(?,?,?,?,?)", (subject,'garmin','a','2026-01-01T00:00:00Z','2026-01-01'))
    activity = db.execute("SELECT id FROM activities").fetchone()[0]
    db.execute("INSERT INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,extras_json) VALUES(?,?,?,?,?)", (activity,revision,'fit',0,'{}'))
    for table in ("analysis_deliveries", "mail_deliveries", "operational_alert_deliveries"):
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    with __import__("pytest").raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES('x','../escape','x',0,'x','x','t')")


def test_explicit_backup_and_rebuild_are_isolated(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = foundation_tool(root)
    assert tool.execute(request("init", root)).status == "initialized"
    backup = tool.backup_database(tmp_path / "backup" / "data.db")
    copied = sqlite3.connect(backup)
    assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copied.close()
    rebuilt = tool.rebuild_into(tmp_path / "rebuilt")
    assert rebuilt != root
    assert foundation_tool(rebuilt).execute(request("verify", rebuilt)).status == "ready"


def test_authenticated_encrypted_backup_restore_and_tamper(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    instance = foundation_tool(root)
    assert instance.execute(request("init", root)).status == "initialized"
    key = b"k" * 32
    encrypted = instance.backup_encrypted(tmp_path / "secure.tlfb", lambda: key)
    restored = FoundationTool.restore_encrypted(encrypted, tmp_path / "restored.db", key)
    original = sqlite3.connect(root / "data.db")
    copy = sqlite3.connect(restored)
    assert original.execute("SELECT COUNT(*) FROM sqlite_master").fetchone() == copy.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    original.close(); copy.close()
    with __import__("pytest").raises(Exception):
        FoundationTool.restore_encrypted(encrypted, tmp_path / "wrong.db", b"x" * 32)
    tampered = tmp_path / "tampered.tlfb"
    data = bytearray(encrypted.read_bytes()); data[-1] ^= 1; tampered.write_bytes(data)
    with __import__("pytest").raises(Exception):
        FoundationTool.restore_encrypted(tampered, tmp_path / "tampered.db", key)
    with __import__("pytest").raises(FileExistsError):
        FoundationTool.restore_encrypted(encrypted, restored, key)


def test_contract_field_coverage_and_read_only_modes(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    instance = foundation_tool(root)
    assert instance.execute(request("init", root)).status == "initialized"
    db = root / "data.db"
    before = {path.name: (path.stat().st_mtime_ns, path.stat().st_size) for path in root.rglob("*") if path.is_file()}
    assert instance.execute(request("status", root)).status == "ready"
    assert instance.execute(request("verify", root)).status == "ready"
    after = {path.name: (path.stat().st_mtime_ns, path.stat().st_size) for path in root.rglob("*") if path.is_file()}
    assert before == after
    conn = sqlite3.connect(db)
    required = {
        "analysis_runs": {"analysis_kind", "target_start_local_date"},
        "scheduler_jobs": {"workflow_kind", "timezone", "schedule_spec_json", "is_enabled", "updated_at_utc"},
        "scheduler_leases": {"owner_instance_id", "owner_pid", "acquired_at_utc"},
        "orchestrator_runs": {"parent_workflow_run_id"},
        "orchestrator_steps": {"step_key", "ordinal", "layer_no", "tool_mode", "request_sha256", "receipt_sha256"},
        "service_health_checks": {"check_kind", "target_kind", "target_id", "metrics_json"},
        "operational_incidents": {"related_workflow_run_id", "related_step_id", "error_code", "error_summary"},
        "operational_alert_deliveries": {"operational_incident_id", "error_code", "error_summary"},
    }
    for table, columns in required.items():
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert columns <= actual


def test_ready_missing_object_or_unsafe_permission_is_not_repaired(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    instance = foundation_tool(root)
    assert instance.execute(request("init", root)).status == "initialized"
    (root / "raw" / "garmin" / "fit").rmdir()
    assert instance.execute(request("init", root)).status == "incompatible"
    assert not (root / "raw" / "garmin" / "fit").exists()
    other = tmp_path / "other"
    instance = foundation_tool(other)
    assert instance.execute(request("init", other)).status == "initialized"
    (other / "data.db").chmod(0o644)
    assert instance.execute(request("verify", other)).status == "incompatible"


def test_active_and_stale_lock_semantics(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    instance = foundation_tool(root)
    lock = root / "state" / "locks" / "foundation.lock"
    lock.parent.mkdir(parents=True)
    root.chmod(0o700)
    (root / "state").chmod(0o700)
    lock.parent.chmod(0o700)
    lock.write_text(json.dumps({"pid": __import__("os").getpid()}))
    lock.chmod(0o600)
    assert instance.execute(request("init", root)).status == "lock_busy"
    lock.write_text(json.dumps({"pid": 99999999, "uid": __import__("os").getuid(), "started_at_utc": "2026-07-23T00:00:00Z"}))
    lock.chmod(0o600)
    assert instance.execute(request("init", root)).status == "initialized"
    assert (root / "state" / "foundation-lock-recoveries.jsonl").exists()


def test_public_request_and_receipt_schemas(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request_schema = json.loads((root / "harness/schemas/foundation_request.schema.json").read_text())
    receipt_schema = json.loads((root / "harness/schemas/foundation_receipt.schema.json").read_text())
    payload = {"mode": "init", "invocation_id": "i", "requested_at_utc": "2026-07-23T00:00:00Z", "target_schema_version": None}
    assert not list(Draft202012Validator(request_schema).iter_errors(payload))
    assert list(Draft202012Validator(request_schema).iter_errors({**payload, "data_root": "/tmp"}))
    receipt = foundation_tool(tmp_path / "schema").execute(request("init", tmp_path / "schema"))
    assert not list(Draft202012Validator(receipt_schema).iter_errors(json.loads(receipt.json())))


def test_cli_has_only_fixed_foundation_shape() -> None:
    parser = _parser()
    assert parser.parse_args(["foundation", "init"]).foundation_mode == "init"
    assert parser.parse_args(["foundation", "migrate", "--target-version", "1"]).target_version == 1
    with __import__("pytest").raises(SystemExit):
        parser.parse_args(["foundation", "--data-root", "/tmp", "init"])


def test_versioned_owner_config_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    config = FoundationConfig.load(root)
    assert config.data_root == (root / "state/foundation").resolve()


def test_manual_section_715_manifest_matches_sqlite(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    assert foundation_tool(root).execute(request("init", root)).status == "initialized"
    manifest = json.loads((Path(__file__).resolve().parents[1] / "harness/schemas/foundation_schema_manifest.json").read_text())
    conn = sqlite3.connect(root / "data.db")
    actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(manifest["tables"]) == actual
    for table, spec in manifest["tables"].items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert set(spec["columns"]) <= columns
        foreign = {row[3]: row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
        for column, target in spec.get("fk", {}).items():
            assert foreign[column] == target
