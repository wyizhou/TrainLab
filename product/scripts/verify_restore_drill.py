#!/usr/bin/env python3
"""Execute a generated, isolated Foundation backup restore/rollback drill.

This utility refuses any root outside ``state/test-tmp``.  It never accepts a
user database, raw object, credential, or production state path.  The only
backups it restores are generated, schema-only SQLite databases created during
the current invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator

from tests.foundation_v2_fixture import create_published_v2_database
from trainlab.foundation import (
    FOUNDATION_SCHEMA_VERSION,
    FoundationConfig,
    FoundationRequest,
    FoundationTool,
)
from trainlab.foundation.schema import validate_schema_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = PROJECT_ROOT / "state" / "test-tmp"
PARTITIONS = (
    "valid-current",
    "valid-previous-supported",
    "corrupt-backup",
    "missing-manifest",
    "newer-unsupported-schema",
    "older-unsupported-schema",
    "interrupted-restore",
)
MANIFEST_FIELDS = frozenset(
    {"schema_version", "database_sha256", "foundation_schema_version", "database_kind"}
)


class RestoreDrillError(ValueError):
    """A restore admission or pre-promotion check failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _under_test_root(path: Path) -> Path:
    candidate = path.resolve(strict=False)
    root = TEST_TMP_ROOT.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RestoreDrillError("restore_root_must_be_under_state_test_tmp") from exc
    if candidate == root:
        raise RestoreDrillError("restore_root_must_be_a_child")
    return candidate


def _config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )


def _new_current_database(root: Path) -> Path:
    tool = FoundationTool(_config(root))
    receipt = tool.execute(
        FoundationRequest("init", "restore-drill-current", "2026-08-07T00:00:00Z")
    )
    if not receipt.ready:
        raise RestoreDrillError("generated_current_database_not_ready")
    return root / "data.db"


def _new_v2_database(root: Path) -> Path:
    """Generate a known published v2 fixture; it contains schema only."""
    create_published_v2_database(root)
    return root / "data.db"


def _write_manifest(backup: Path, version: int) -> Path:
    manifest = backup.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "database_sha256": _sha256(backup),
                "foundation_schema_version": version,
                "database_kind": "sanitized_generated",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    return manifest


def _validate_backup(backup: Path, manifest: Path) -> int:
    if not backup.is_file() or not manifest.is_file():
        raise RestoreDrillError("backup_or_manifest_missing")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreDrillError("backup_manifest_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != MANIFEST_FIELDS:
        raise RestoreDrillError("backup_manifest_shape_invalid")
    if (
        payload.get("schema_version") != "1"
        or payload.get("database_kind") != "sanitized_generated"
    ):
        raise RestoreDrillError("backup_manifest_unrecognized")
    version = payload.get("foundation_schema_version")
    if type(version) is not int or version not in {
        FOUNDATION_SCHEMA_VERSION - 1,
        FOUNDATION_SCHEMA_VERSION,
    }:
        raise RestoreDrillError("backup_schema_version_unsupported")
    if payload.get("database_sha256") != _sha256(backup):
        raise RestoreDrillError("backup_checksum_mismatch")
    return version


def _validate_database(database: Path, version: int, source_root: Path) -> None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise RestoreDrillError("restore_integrity_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RestoreDrillError("restore_foreign_key_failed")
        tool = FoundationTool(_config(source_root))
        paths = tool._paths(source_root)
        if version == FOUNDATION_SCHEMA_VERSION:
            if validate_schema_manifest(connection, tool._manifest()):
                raise RestoreDrillError("restore_current_schema_failed")
        elif tool._published_v2_source_error(connection, paths) is not None:
            raise RestoreDrillError("restore_previous_schema_failed")
    except sqlite3.DatabaseError as exc:
        raise RestoreDrillError("restore_sqlite_invalid") from exc
    finally:
        connection.close()


def restore_backup(
    backup: Path,
    manifest: Path,
    destination: Path,
    source_root: Path,
    *,
    interrupt_before_promotion: bool = False,
) -> Path:
    """Restore only after complete admission; an interruption never promotes."""
    version = _validate_backup(backup, manifest)
    staging = destination.with_name(f".{destination.name}.staging-{uuid4().hex}")
    try:
        shutil.copyfile(backup, staging)
        staging.chmod(0o600)
        _validate_database(staging, version, source_root)
        if interrupt_before_promotion:
            raise RestoreDrillError("restore_interrupted_before_promotion")
        os.replace(staging, destination)
        return destination
    finally:
        staging.unlink(missing_ok=True)


def run_drill(output_root: Path) -> dict[str, object]:
    root = _under_test_root(output_root)
    if root.exists():
        raise RestoreDrillError("restore_output_root_must_not_exist")
    root.mkdir(parents=True, mode=0o700)
    current_root, previous_root = root / "current", root / "previous"
    backups, promoted = root / "backups", root / "promoted"
    backups.mkdir(mode=0o700)
    promoted.mkdir(mode=0o700)
    current = _new_current_database(current_root)
    previous = _new_v2_database(previous_root)
    current_backup, previous_backup = (
        backups / "current.sqlite",
        backups / "previous.sqlite",
    )
    shutil.copyfile(current, current_backup)
    shutil.copyfile(previous, previous_backup)
    current_manifest = _write_manifest(current_backup, FOUNDATION_SCHEMA_VERSION)
    previous_manifest = _write_manifest(previous_backup, FOUNDATION_SCHEMA_VERSION - 1)

    target = promoted / "active.sqlite"
    restore_backup(current_backup, current_manifest, target, current_root)
    _validate_database(target, FOUNDATION_SCHEMA_VERSION, current_root)
    baseline_digest = _sha256(target)
    restore_backup(previous_backup, previous_manifest, target, previous_root)
    _validate_database(target, FOUNDATION_SCHEMA_VERSION - 1, previous_root)

    corrupt = backups / "corrupt.sqlite"
    corrupt.write_bytes(b"not a sqlite database")
    corrupt_manifest = _write_manifest(corrupt, FOUNDATION_SCHEMA_VERSION)
    for candidate, manifest, expected in (
        (corrupt, corrupt_manifest, "restore_sqlite_invalid"),
        (
            current_backup,
            backups / "missing.manifest.json",
            "backup_or_manifest_missing",
        ),
    ):
        try:
            restore_backup(candidate, manifest, target, current_root)
        except RestoreDrillError as exc:
            if str(exc) != expected:
                raise
        else:
            raise RestoreDrillError("invalid_restore_was_promoted")

    for version in (FOUNDATION_SCHEMA_VERSION + 1, FOUNDATION_SCHEMA_VERSION - 2):
        incompatible = backups / f"incompatible-{version}.manifest.json"
        payload = json.loads(current_manifest.read_text(encoding="utf-8"))
        payload["foundation_schema_version"] = version
        incompatible.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        try:
            restore_backup(current_backup, incompatible, target, current_root)
        except RestoreDrillError as exc:
            if str(exc) != "backup_schema_version_unsupported":
                raise
        else:
            raise RestoreDrillError("unsupported_restore_was_promoted")
    before_interruption = _sha256(target)
    try:
        restore_backup(
            current_backup,
            current_manifest,
            target,
            current_root,
            interrupt_before_promotion=True,
        )
    except RestoreDrillError as exc:
        if str(exc) != "restore_interrupted_before_promotion":
            raise
    else:
        raise RestoreDrillError("interrupted_restore_was_promoted")
    if _sha256(target) != before_interruption or baseline_digest == "":
        raise RestoreDrillError("interrupted_restore_changed_target")
    return {
        "schema_version": "1",
        "receipt_kind": "restore_drill",
        "run_id": f"restore-drill-{uuid4().hex}",
        "status": "succeeded",
        "database_kind": "sanitized_generated",
        "partitions": list(PARTITIONS),
        "checks": {
            "integrity": True,
            "foreign_keys": True,
            "schema": True,
            "manifest": True,
            "promotion": True,
        },
        "external_effects": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_restore_drill")
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = run_drill(args.output_root)
    schema = json.loads(
        (PROJECT_ROOT / "harness/schemas/restore_drill_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
