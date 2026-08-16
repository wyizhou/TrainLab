#!/usr/bin/env python3
"""Verify a paired SQLite backup and optionally apply an explicit local restore."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.verify_state import _contract_errors  # noqa: E402
from skills._shared.state import connect  # noqa: E402

EXPECTED_TABLES = {
    "skill_runs",
    "activity_inventory",
    "raw_files",
    "skill_outputs",
    "approvals",
    "external_actions",
}
REQUIRED_TRIGGERS = {
    "trg_approval_output_match_insert",
    "trg_approval_output_match_update",
    "trg_external_action_approval_match_insert",
    "trg_external_action_approval_match_update",
    "trg_raw_revision_lineage_insert",
    "trg_raw_revision_lineage_update",
    "trg_output_revision_lineage_insert",
    "trg_output_revision_lineage_update",
    "trg_external_action_approved_insert",
    "trg_external_action_approved_update",
    "trg_activity_hash_insert",
    "trg_activity_hash_update",
    "trg_temporal_skill_runs_insert",
    "trg_temporal_skill_runs_update",
    "trg_temporal_activity_insert",
    "trg_temporal_activity_update",
    "trg_temporal_raw_insert",
    "trg_temporal_raw_update",
    "trg_temporal_output_insert",
    "trg_temporal_output_update",
    "trg_temporal_approval_insert",
    "trg_temporal_approval_update",
    "trg_temporal_action_insert",
    "trg_temporal_action_update",
    "trg_approval_revoke_guard",
    "trg_external_action_approval_scope_insert",
    "trg_external_action_approval_scope_update",
    "trg_raw_append_only_delete",
    "trg_raw_append_only_update",
    "trg_output_append_only_delete",
    "trg_output_append_only_update",
    "trg_approval_append_only_delete",
    "trg_approval_append_only_update",
    "trg_run_input_sha_insert",
    "trg_run_input_sha_update",
    "trg_scope_sha_insert",
    "trg_scope_sha_update",
    "trg_request_sha_insert",
    "trg_request_sha_update",
    "trg_output_sha_insert",
    "trg_output_sha_update",
    "trg_output_lineage_refs_insert",
    "trg_approval_authority_insert",
    "trg_external_action_approval_scope_exact_insert",
    "trg_external_action_approval_scope_exact_update",
    "trg_external_action_semantics_insert",
    "trg_external_action_semantics_update",
    "trg_external_action_append_only_update",
    "trg_external_action_append_only_delete",
    "trg_external_action_terminal_immutability",
    "trg_external_action_status_transition",
    "trg_garmin_delete_ownership_insert",
    "trg_external_action_budget_insert",
    "trg_external_action_revoked_approval_insert",
    "trg_activity_complete_requires_raw",
    "trg_activity_complete_requires_raw_update",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BACKUP_NAME_RE = re.compile(
    r"^trainlab-(?P<stamp>\d{8}T\d{6}Z)-(?P<operation>[A-Za-z0-9._-]+)-(?P<digest>[0-9a-f]{12,64})\.db$"
)
SKILL_VERSIONS = {
    "garmin-sync": "1",
    "training-coach": "1",
    "weekly-fitness-summary": "1",
    "garmin-training-sender": "1",
    "training-report-publisher": "1",
    "gmail-sender": "1",
}


def _manifest_int(value: object, default: int = -1) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _raw_closure(connection: sqlite3.Connection, raw_root: Path) -> list[str]:
    errors: list[str] = []
    if not raw_root.is_dir() or raw_root.is_symlink():
        return ["raw_root_invalid"]
    registered: set[str] = set()
    for row in connection.execute(
        "SELECT relative_path, byte_size, sha256 FROM raw_files"
    ):
        relative = str(row[0])
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or not relative:
            errors.append("raw_path_invalid")
            continue
        path = raw_root.joinpath(*candidate.parts)
        if raw_root.resolve() not in path.resolve(strict=False).parents:
            errors.append("raw_path_invalid")
            continue
        if path.is_symlink() or not path.is_file():
            errors.append("raw_file_missing")
            continue
        registered.add(relative)
        if not SHA256_RE.fullmatch(str(row[2])):
            errors.append("raw_sha_invalid")
        if path.stat().st_mode & 0o777 != 0o600:
            errors.append("raw_file_mode_invalid")
        if path.stat().st_size != int(row[1]) or digest(path) != str(row[2]):
            errors.append("raw_hash_or_size_mismatch")
    for path in raw_root.rglob("*"):
        if path.name == ".gitkeep":
            continue
        if path.is_symlink():
            errors.append("raw_symlink")
        elif path.is_file() and str(path.relative_to(raw_root)) not in registered:
            errors.append("raw_unregistered_file")
        elif path.is_dir() and path.stat().st_mode & 0o777 != 0o700:
            errors.append("raw_directory_mode_invalid")
    return sorted(set(errors))


def _database_errors(database: Path, raw_root: Path) -> list[str]:
    """Validate a database at its final path, including its raw byte closure."""
    errors: list[str] = []
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            errors.append("database_integrity_failed")
        if list(connection.execute("PRAGMA foreign_key_check")):
            errors.append("database_foreign_key_failed")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if tables != EXPECTED_TABLES:
            errors.append("database_tables_invalid")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            errors.append("database_version_invalid")
        strict_ok = all(
            len(row) < 6 or int(row[5]) == 1
            for row in connection.execute("PRAGMA table_list")
            if row[1] in EXPECTED_TABLES
        )
        if not strict_ok:
            errors.append("database_strict_invalid")
        for table in EXPECTED_TABLES:
            if any(
                row[6] != "RESTRICT"
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            ):
                errors.append("database_foreign_key_action_invalid")
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        if not REQUIRED_TRIGGERS.issubset(triggers):
            errors.append("database_triggers_invalid")
        duplicates = connection.execute(
            """SELECT dedupe_key FROM skill_runs
               WHERE status IN ('pending','running','succeeded')
               GROUP BY dedupe_key HAVING COUNT(*) > 1"""
        ).fetchall()
        if duplicates:
            errors.append("database_active_dedupe_duplicate")
        errors.extend(_contract_errors(connection))
        errors.extend(_raw_closure(connection, raw_root))
        connection.close()
    except sqlite3.Error:
        errors.append("database_unreadable")
    return sorted(set(errors))


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _snapshot(
    source: Path, directory: Path, operation: str, backup_type: str
) -> tuple[Path, Path]:
    """Make a paired, hash-suffixed SQLite snapshot in a private directory."""
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    temporary = directory / f".{operation}.db.tmp"
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target = sqlite3.connect(temporary)
    try:
        connection.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
        target.commit()
    finally:
        target.close()
        connection.close()
    os.chmod(temporary, 0o600)
    descriptor = os.open(temporary, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    for suffix in ("-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    digest_value = digest(temporary)
    connection = sqlite3.connect(f"file:{temporary}?mode=ro&immutable=1", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in sorted(EXPECTED_TABLES)
        }
        highest_ids = {
            table: connection.execute(
                f"SELECT COALESCE(MAX(id),0) FROM {table}"
            ).fetchone()[0]
            for table in sorted(EXPECTED_TABLES)
        }
        nonterminal = connection.execute(
            "SELECT COUNT(*) FROM external_actions WHERE status IN "
            "('prepared','in_progress','unknown')"
        ).fetchone()[0]
        raw_summary = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(byte_size),0),"
            "SUM(CASE WHEN integrity_state='verified' THEN 1 ELSE 0 END) "
            "FROM raw_files"
        ).fetchone()
    finally:
        connection.close()
    backup = directory / f"trainlab-{stamp}-{operation}-{digest_value}.db"
    manifest = backup.with_suffix(".manifest.json")
    os.replace(temporary, backup)
    _write_private_json(
        manifest,
        {
            "schema_version": "1",
            "backup_type": backup_type,
            "operation_id": operation,
            "database_sha256": digest_value,
            "database_size": backup.stat().st_size,
            "user_version": 1,
            "table_counts": counts,
            "highest_ids": highest_ids,
            "nonterminal_external_actions": int(nonterminal),
            "raw_index": {
                "file_count": int(raw_summary[0]),
                "byte_size": int(raw_summary[1]),
                "verified_count": int(raw_summary[2] or 0),
            },
            "integrity_check": integrity,
            "foreign_key_errors": len(foreign_keys),
            "raw_validation_level": "index_only",
            "code_version": "ai-skills-runtime-v1",
            "skill_versions": SKILL_VERSIONS,
            "created_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        },
    )
    _fsync_directory(directory)
    return backup, manifest


def verify(
    backup: Path, manifest_path: Path, raw_root: Path
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    manifest: dict[str, object] = {}
    if backup.is_symlink() or not backup.is_file():
        errors.append("backup_not_regular_file")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        errors.append("manifest_not_regular_file")
    filename_match = BACKUP_NAME_RE.fullmatch(backup.name)
    if not filename_match:
        errors.append("backup_filename_invalid")
    if manifest_path != backup.with_suffix(".manifest.json"):
        errors.append("manifest_pair_name_invalid")
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError
        manifest = loaded
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        errors.append("manifest_invalid")
    if backup.exists() and backup.stat().st_mode & 0o777 != 0o600:
        errors.append("backup_mode_invalid")
    if manifest_path.exists() and manifest_path.stat().st_mode & 0o777 != 0o600:
        errors.append("manifest_mode_invalid")
    if not errors:
        actual_digest = digest(backup)
        if _manifest_int(manifest.get("database_size")) != backup.stat().st_size:
            errors.append("backup_size_mismatch")
        if str(manifest.get("database_sha256")) != actual_digest:
            errors.append("backup_hash_mismatch")
        if filename_match and not actual_digest.startswith(
            filename_match.group("digest")
        ):
            errors.append("backup_filename_digest_mismatch")
        if filename_match:
            expected_created = (
                datetime.strptime(filename_match.group("stamp"), "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            if str(manifest.get("created_at_utc")) != expected_created:
                errors.append("backup_filename_time_mismatch")
            if filename_match.group("operation") != str(manifest.get("operation_id")):
                errors.append("backup_operation_mismatch")
        if str(manifest.get("backup_type")) not in {
            "workflow_daily",
            "workflow_weekly",
            "manual",
            "pre_change",
            "external_barrier",
            "pre_restore",
            "post_restore",
        }:
            errors.append("backup_type_invalid")
        if manifest.get("schema_version") != "1":
            errors.append("backup_manifest_schema_invalid")
        if manifest.get("code_version") != "ai-skills-runtime-v1":
            errors.append("backup_code_version_invalid")
        if manifest.get("skill_versions") != SKILL_VERSIONS:
            errors.append("backup_skill_versions_invalid")
        if manifest.get("integrity_check") != "ok":
            errors.append("backup_manifest_integrity_invalid")
        if manifest.get("foreign_key_errors") != 0:
            errors.append("backup_manifest_foreign_keys_invalid")
        if manifest.get("raw_validation_level") not in {"index_only", "full_bytes"}:
            errors.append("backup_raw_validation_level_invalid")
        nonterminal = manifest.get("nonterminal_external_actions")
        if (
            not isinstance(nonterminal, int)
            or isinstance(nonterminal, bool)
            or nonterminal < 0
        ):
            errors.append("backup_nonterminal_count_invalid")
        if _manifest_int(manifest.get("user_version")) != 1:
            errors.append("backup_schema_version_invalid")
    if not errors:
        try:
            connection = sqlite3.connect(f"file:{backup}?mode=ro&immutable=1", uri=True)
            connection.execute("PRAGMA foreign_keys=ON")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            strict_ok = all(
                len(row) < 6 or int(row[5]) == 1
                for row in connection.execute("PRAGMA table_list")
                if row[1] in EXPECTED_TABLES
            )
            triggers = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            sql_text = "".join(
                str(row[0]).replace(" ", "")
                for row in connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type IN ('table','index')"
                )
                if row[0]
            )
            if integrity != "ok":
                errors.append("backup_integrity_failed")
            if foreign_keys:
                errors.append("backup_foreign_key_failed")
            if tables != EXPECTED_TABLES or not strict_ok:
                errors.append("backup_tables_invalid")
            if not REQUIRED_TRIGGERS.issubset(triggers):
                errors.append("backup_triggers_invalid")
            actual_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in sorted(EXPECTED_TABLES)
            }
            if manifest.get("table_counts") != actual_counts:
                errors.append("backup_table_counts_mismatch")
            actual_highest = {
                table: connection.execute(
                    f"SELECT COALESCE(MAX(id),0) FROM {table}"
                ).fetchone()[0]
                for table in sorted(EXPECTED_TABLES)
            }
            if manifest.get("highest_ids") != actual_highest:
                errors.append("backup_highest_ids_mismatch")
            raw_summary = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(byte_size),0),"
                "SUM(CASE WHEN integrity_state='verified' THEN 1 ELSE 0 END) "
                "FROM raw_files"
            ).fetchone()
            expected_raw = {
                "file_count": int(raw_summary[0]),
                "byte_size": int(raw_summary[1]),
                "verified_count": int(raw_summary[2] or 0),
            }
            if manifest.get("raw_index") != expected_raw:
                errors.append("backup_raw_index_mismatch")
            actual_nonterminal = connection.execute(
                "SELECT COUNT(*) FROM external_actions WHERE status IN "
                "('prepared','in_progress','unknown')"
            ).fetchone()[0]
            if manifest.get("nonterminal_external_actions") != actual_nonterminal:
                errors.append("backup_nonterminal_count_mismatch")
            for token in (
                "UNIQUE(dedupe_key,attempt_no)",
                "UNIQUE(logical_key,sha256)",
                "UNIQUE(supersedes_raw_file_id)",
                "UNIQUE(logical_key,content_sha256)",
                "UNIQUE(supersedes_output_id)",
            ):
                if token not in sql_text:
                    errors.append("backup_contract_unique_missing")
            approval_mismatch = connection.execute(
                """SELECT COUNT(*) FROM approvals a JOIN skill_outputs o
                   ON o.id=a.candidate_output_id
                  WHERE a.candidate_output_sha256 <> o.content_sha256"""
            ).fetchone()[0]
            action_mismatch = connection.execute(
                """SELECT COUNT(*) FROM external_actions a JOIN skill_outputs o
                   ON o.id=a.source_output_id
                  WHERE a.source_output_sha256 <> o.content_sha256"""
            ).fetchone()[0]
            if approval_mismatch or action_mismatch:
                errors.append("backup_output_binding_invalid")
            errors.extend(_contract_errors(connection))
            errors.extend(_raw_closure(connection, raw_root))
            connection.close()
        except sqlite3.Error:
            errors.append("backup_unreadable")
    return manifest, sorted(set(errors))


def _apply_restore_legacy(backup: Path, target: Path, operation_id: str) -> Path:
    if backup.stat().st_dev != target.parent.stat().st_dev:
        raise ValueError("restore_cross_device")
    if not target.exists() or target.is_symlink():
        raise ValueError("restore_target_invalid")
    raw_root = target.parent / "raw"
    if _database_errors(target, raw_root):
        raise ValueError("restore_target_precheck_failed")
    lock_path = target.parent / "trainlab.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise ValueError("restore_lock_unavailable") from exc
    quarantine = target.parent / "recovery-quarantine" / operation_id
    quarantine.mkdir(parents=True, exist_ok=False)
    os.chmod(quarantine.parent, 0o700)
    os.chmod(quarantine, 0o700)
    previous = quarantine / "previous-trainlab.db"
    moved_sidecars: list[Path] = []
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.restore.tmp")
    pre_backup = pre_manifest = post_backup = post_manifest = None
    status = "failed_safe"
    errors: list[str] = []
    try:
        pre_backup, pre_manifest = _snapshot(
            target, quarantine, f"{operation_id}-pre-restore", "pre_restore"
        )
        shutil.copyfile(backup, temporary)
        os.chmod(temporary, 0o600)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                "UPDATE skill_runs SET status='interrupted', finished_at_utc=NULL, "
                "error_code='restore_requires_recovery' WHERE status='running'"
            )
            connection.execute(
                "UPDATE external_actions SET status='unknown', finished_at_utc=NULL, "
                "error_code='restore_requires_reconcile' WHERE status IN ('prepared','in_progress')"
            )
            connection.commit()
        finally:
            connection.close()
        for suffix in ("-wal", "-shm"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)
        os.replace(target, previous)
        for suffix in ("-wal", "-shm"):
            old_sidecar = Path(str(target) + suffix)
            if old_sidecar.exists():
                destination = quarantine / old_sidecar.name
                os.replace(old_sidecar, destination)
                moved_sidecars.append(destination)
        os.replace(temporary, target)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        errors = _database_errors(target, raw_root)
        if errors:
            failed_new = quarantine / "failed-new-trainlab.db"
            os.replace(target, failed_new)
            os.replace(previous, target)
            for sidecar in moved_sidecars:
                os.replace(sidecar, target.parent / sidecar.name)
            status = "rolled_back"
        else:
            post_backup, post_manifest = _snapshot(
                target, quarantine, f"{operation_id}-post-restore", "post_restore"
            )
            status = "restored_requires_reconciliation"
    except Exception as exc:
        errors.append(type(exc).__name__)
        if target.exists() and previous.exists():
            failed_new = quarantine / "failed-new-trainlab.db"
            os.replace(target, failed_new)
            os.replace(previous, target)
        if temporary.exists():
            temporary.unlink()
        status = "rolled_back"
    finally:
        receipt = quarantine / "restore.json"
        _write_private_json(
            receipt,
            {
                "schema_version": "1",
                "operation_id": operation_id,
                "status": status,
                "source_backup": backup.name,
                "target": target.name,
                "pre_restore_backup": pre_backup.name if pre_backup else None,
                "pre_restore_manifest": pre_manifest.name if pre_manifest else None,
                "post_restore_backup": post_backup.name if post_backup else None,
                "post_restore_manifest": post_manifest.name if post_manifest else None,
                "errors": sorted(set(errors)),
                "external_actions_reconciled": False,
            },
        )
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    if status == "rolled_back":
        raise ValueError("restore_rolled_back")
    return receipt


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def apply_restore(backup: Path, target: Path, operation_id: str) -> Path:
    """Apply a verified backup with a lock-first, recoverable state machine."""
    if backup.stat().st_dev != target.parent.stat().st_dev:
        raise ValueError("restore_cross_device")
    if target.is_symlink():
        raise ValueError("restore_target_invalid")
    lock_path = target.parent / "trainlab.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise ValueError("restore_lock_unavailable") from exc

    quarantine = target.parent / "recovery-quarantine" / operation_id
    quarantine.mkdir(parents=True, exist_ok=False)
    os.chmod(quarantine.parent, 0o700)
    os.chmod(quarantine, 0o700)
    raw_root = target.parent / "raw"
    previous = quarantine / "previous-trainlab.db"
    moved_sidecars: list[Path] = []
    target_was_moved = False
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.restore.tmp")
    pre_backup = pre_manifest = post_backup = post_manifest = None
    status = "failed_safe"
    errors: list[str] = []

    def move_old_state() -> None:
        nonlocal target_was_moved
        if target.exists():
            os.replace(target, previous)
            target_was_moved = True
        for suffix in ("-wal", "-shm"):
            old_sidecar = Path(str(target) + suffix)
            if old_sidecar.exists():
                destination = quarantine / old_sidecar.name
                os.replace(old_sidecar, destination)
                moved_sidecars.append(destination)
        _fsync_directory(target.parent)

    def restore_old_state() -> None:
        # A failed sidecar restore or directory fsync may invoke this helper a
        # second time. Once ``previous`` is gone, the old database is already
        # back at the target path; do not move it away again.
        if not previous.exists():
            return
        if target.exists():
            failed_new = quarantine / "failed-new-trainlab.db"
            os.replace(target, failed_new)
        for suffix in ("-wal", "-shm"):
            new_sidecar = Path(str(target) + suffix)
            if new_sidecar.exists():
                os.replace(new_sidecar, quarantine / f"failed-new-trainlab.db{suffix}")
        if previous.exists():
            os.replace(previous, target)
        for sidecar in moved_sidecars:
            if sidecar.exists():
                os.replace(sidecar, target.parent / sidecar.name)
        _fsync_directory(target.parent)

    try:
        target_errors = (
            _database_errors(target, raw_root)
            if target.exists()
            else ["target_missing"]
        )
        if not target_errors:
            pre_backup, pre_manifest = _snapshot(
                target, quarantine, f"{operation_id}-pre-restore", "pre_restore"
            )
            verified_pre = verify(pre_backup, pre_manifest, raw_root)[1]
            if verified_pre:
                raise ValueError("pre_restore_backup_invalid")
        else:
            errors.extend(f"target_{error}" for error in target_errors)
        move_old_state()
        shutil.copyfile(backup, temporary)
        os.chmod(temporary, 0o600)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        connection = connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                "UPDATE skill_runs SET status='interrupted', finished_at_utc=NULL, "
                "error_code='restore_requires_recovery' WHERE status='running'"
            )
            connection.execute(
                "UPDATE external_actions SET status='unknown', finished_at_utc=NULL, "
                "error_code='restore_requires_reconcile' WHERE status IN ('prepared','in_progress')"
            )
            connection.commit()
        finally:
            connection.close()
        for suffix in ("-wal", "-shm"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        connection = sqlite3.connect(target)
        try:
            journal_mode = str(
                connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            )
            if journal_mode.lower() != "wal":
                raise ValueError("restore_wal_enable_failed")
            connection.commit()
        finally:
            connection.close()
        _fsync_directory(target.parent)
        final_errors = _database_errors(target, raw_root)
        if final_errors:
            errors.extend(final_errors)
            restore_old_state()
            status = "rolled_back"
        else:
            post_backup, post_manifest = _snapshot(
                target, quarantine, f"{operation_id}-post-restore", "post_restore"
            )
            verified_post = verify(post_backup, post_manifest, raw_root)[1]
            if verified_post:
                errors.extend(verified_post)
                restore_old_state()
                status = "rolled_back"
            else:
                status = "restored_requires_reconciliation"
    except Exception as exc:
        errors.append(type(exc).__name__)
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        if target_was_moved:
            restore_old_state()
        status = "rolled_back"
    finally:
        receipt = quarantine / f"restore-{operation_id}.json"
        _write_private_json(
            receipt,
            {
                "schema_version": "1",
                "operation_id": operation_id,
                "status": status,
                "source_backup": backup.name,
                "target": target.name,
                "pre_restore_backup": pre_backup.name if pre_backup else None,
                "pre_restore_manifest": pre_manifest.name if pre_manifest else None,
                "post_restore_backup": post_backup.name if post_backup else None,
                "post_restore_manifest": post_manifest.name if post_manifest else None,
                "target_was_corrupt_or_missing": bool(errors and not pre_backup),
                "errors": sorted(set(errors)),
                "external_actions_reconciled": False,
            },
        )
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    if status == "rolled_back":
        raise ValueError("restore_rolled_back")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--operation-id", default=None)
    args = parser.parse_args()
    backup = args.backup.resolve()
    manifest_path = (args.manifest or backup.with_suffix(".manifest.json")).resolve()
    raw_root = (args.raw_root or backup.parent.parent.parent / "raw").resolve()
    manifest, errors = verify(backup, manifest_path, raw_root)
    receipt = None
    if args.apply and not errors:
        if args.target is None or not args.operation_id:
            errors.append("restore_target_and_operation_required")
        else:
            receipt = str(
                apply_restore(backup, args.target.resolve(), args.operation_id)
            )
    result = {
        "status": "passed" if not errors else "failed",
        "backup": str(backup),
        "manifest": str(manifest_path),
        "raw_root": str(raw_root),
        "restore_applied": bool(receipt),
        "restore_receipt": receipt,
        "errors": sorted(set(errors)),
        "manifest_schema_version": manifest.get("schema_version"),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
