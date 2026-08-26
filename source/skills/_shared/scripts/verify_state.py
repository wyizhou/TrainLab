#!/usr/bin/env python3
"""Read-only verification for the six-table raw-first runtime state contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_fingerprint import formal_state_content_fingerprint  # noqa: E402

from state import EXPECTED_TABLES, connect, state_path  # noqa: E402

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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
    "trg_output_append_only_insert",
    "trg_raw_append_only_insert",
    "trg_approval_append_only_insert",
    "trg_external_action_append_only_insert",
    "trg_skill_run_append_only_insert",
    "trg_skill_run_identity_immutable",
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


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_raw_path(raw_root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not relative:
        return None
    path = raw_root.joinpath(*candidate.parts)
    if raw_root.resolve() not in path.resolve(strict=False).parents:
        return None
    for parent in (raw_root, *path.relative_to(raw_root).parents):
        if parent.is_symlink():
            return None
    if path.is_symlink():
        return None
    return path


def _raw_errors(connection, state_root: Path) -> list[str]:
    errors: list[str] = []
    raw_root = state_root / "raw"
    rows = connection.execute(
        "SELECT relative_path,byte_size,sha256,data_date FROM raw_files"
    ).fetchall()
    registered: set[str] = set()
    for row in rows:
        relative = str(row[0])
        path = _safe_raw_path(raw_root, relative)
        if path is None or not path.is_file():
            errors.append("raw_path_invalid")
            continue
        registered.add(relative)
        if not SHA256_RE.fullmatch(str(row[2])) or not DATE_RE.fullmatch(str(row[3])):
            errors.append("raw_metadata_invalid")
        if path.stat().st_size != int(row[1]) or _digest(path) != str(row[2]):
            errors.append("raw_hash_or_size_mismatch")
    if raw_root.exists():
        for path in raw_root.rglob("*"):
            if path.name == ".gitkeep":
                continue
            if path.is_symlink():
                errors.append("raw_symlink")
            elif path.is_file() and str(path.relative_to(raw_root)) not in registered:
                errors.append("raw_unregistered_file")
            elif path.is_dir() and (path.stat().st_mode & 0o777) != 0o700:
                errors.append("raw_directory_mode_invalid")
            elif path.is_file() and (path.stat().st_mode & 0o777) != 0o600:
                errors.append("raw_file_mode_invalid")
    else:
        errors.append("raw_root_missing")
    return sorted(set(errors))


def _valid_date(value: object | None) -> bool:
    if value is None:
        return True
    try:
        text = str(value)
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _valid_utc(value: object | None) -> bool:
    if value is None:
        return True
    try:
        datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def _json_hash(value: object) -> str:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return ""
    return hashlib.sha256(
        json.dumps(
            parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _output_hash(row) -> str:
    try:
        content = json.loads(row[2]) if row[2] is not None else None
        lineage = json.loads(row[5])
    except (TypeError, json.JSONDecodeError):
        return ""
    payload = {
        "title": row[1],
        "json": content,
        "text": row[3],
        "html": row[4],
        "lineage": lineage,
    }
    return _json_hash(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _valid_external_semantics(provider: object, action: object, entity: object) -> bool:
    return (
        (provider == "gmail" and action == "gmail_send" and entity == "email")
        or (
            provider == "sites"
            and action == "sites_publish"
            and entity == "site_snapshot"
        )
        or (
            provider == "garmin"
            and entity == "workout"
            and action
            in {
                "garmin_workout_adopt",
                "garmin_workout_create",
                "garmin_workout_verify",
                "garmin_workout_delete",
            }
        )
        or (
            provider == "garmin"
            and entity == "calendar_entry"
            and action in {"garmin_calendar_schedule", "garmin_calendar_unschedule"}
        )
    )


def _contract_errors(connection) -> list[str]:
    errors: list[str] = []
    for row in connection.execute(
        "SELECT target_from_date,target_through_date,created_at_utc,started_at_utc,"
        "heartbeat_at_utc,lease_expires_at_utc,finished_at_utc,input_manifest_json,input_sha256 "
        "FROM skill_runs"
    ):
        if not all(_valid_date(value) for value in row[:2]) or not all(
            _valid_utc(value) for value in row[2:7]
        ):
            errors.append("skill_run_temporal_invalid")
        if _json_hash(row[7]) != row[8]:
            errors.append("run_input_sha256_mismatch")
    for row in connection.execute(
        "SELECT provider,provider_activity_id,activity_hash,activity_hash_version,"
        "activity_date,first_seen_at_utc,last_seen_at_utc,last_collection_at_utc,"
        "updated_at_utc FROM activity_inventory"
    ):
        expected = hashlib.sha256(f"{row[0]}\0{row[1]}".encode()).hexdigest()
        if row[2] != expected or row[3] != "provider-nul-id-sha256-v1":
            errors.append("activity_hash_invalid")
        if not _valid_date(row[4]) or not all(_valid_utc(value) for value in row[5:]):
            errors.append("activity_temporal_invalid")
    for row in connection.execute(
        "SELECT id FROM activity_inventory WHERE collection_state='complete'"
    ):
        if not connection.execute(
            "SELECT 1 FROM raw_files WHERE activity_inventory_id=? "
            "AND integrity_state='verified' AND file_format IN ('fit','gpx','tcx')",
            (row[0],),
        ).fetchone():
            errors.append("activity_complete_without_verified_raw")
    for row in connection.execute(
        "SELECT id,data_class,activity_binding_state,activity_inventory_id,bound_by_run_id,"
        "binding_evidence_json,data_date,captured_at_utc,registered_at_utc,last_verified_at_utc "
        "FROM raw_files"
    ):
        if (
            row[1] == "health"
            and row[1:]
            and (
                row[2] != "not_applicable"
                or row[3] is not None
                or row[4] is not None
                or row[5] is not None
            )
        ):
            errors.append("raw_health_binding_invalid")
        if row[1] == "activity":
            bound = row[2] == "bound"
            if bound != all(value is not None for value in row[3:6]):
                errors.append("raw_activity_binding_invalid")
        if not _valid_date(row[6]) or not all(_valid_utc(value) for value in row[7:]):
            errors.append("raw_temporal_invalid")
    for table, columns in (
        ("skill_outputs", ("period_start_date", "period_end_date", "created_at_utc")),
        ("approvals", ("decided_at_utc", "valid_from_utc", "valid_until_utc")),
        (
            "external_actions",
            (
                "prepared_at_utc",
                "started_at_utc",
                "finished_at_utc",
                "last_reconciled_at_utc",
            ),
        ),
    ):
        for row in connection.execute(f"SELECT {','.join(columns)} FROM {table}"):
            date_count = 2 if table == "skill_outputs" else 0
            if not all(_valid_date(value) for value in row[:date_count]) or not all(
                _valid_utc(value) for value in row[date_count:]
            ):
                errors.append(f"{table}_temporal_invalid")
    for table, key in (
        ("raw_files", "supersedes_raw_file_id"),
        ("skill_outputs", "supersedes_output_id"),
    ):
        for row in connection.execute(
            f"SELECT child.logical_key,child.revision_no,parent.logical_key,parent.revision_no "
            f"FROM {table} child JOIN {table} parent ON parent.id=child.{key}"
        ):
            if row[0] != row[2] or row[1] != int(row[3]) + 1:
                errors.append("revision_lineage_invalid")
    for row in connection.execute(
        "SELECT id,title_text,content_json,content_text,content_html,lineage_json,content_sha256 "
        "FROM skill_outputs"
    ):
        if _output_hash(row) != row[6]:
            errors.append("output_content_sha256_mismatch")
        try:
            lineage = json.loads(row[5])
        except (TypeError, json.JSONDecodeError):
            errors.append("output_lineage_invalid")
            continue
        if not isinstance(lineage, list):
            errors.append("output_lineage_invalid")
            continue
        for item in lineage:
            if not isinstance(item, dict):
                errors.append("output_lineage_invalid")
                continue
            raw_id = item.get("raw_file_id", item.get("raw_id"))
            raw_sha = item.get("raw_sha256")
            output_id = item.get("output_id", item.get("report_output_id"))
            output_sha = item.get("output_sha256")
            input_sha = item.get("input_sha256")
            if raw_id is None and output_id is None and input_sha is None:
                errors.append("output_lineage_invalid")
            if input_sha is not None and (
                not isinstance(input_sha, str) or not SHA256_RE.fullmatch(input_sha)
            ):
                errors.append("output_lineage_invalid")
            if raw_id is not None and (
                not isinstance(raw_id, int)
                or not isinstance(raw_sha, str)
                or connection.execute(
                    "SELECT sha256 FROM raw_files WHERE id=?", (raw_id,)
                ).fetchone()
                is None
                or connection.execute(
                    "SELECT sha256 FROM raw_files WHERE id=?", (raw_id,)
                ).fetchone()[0]
                != raw_sha
            ):
                errors.append("output_lineage_invalid")
            if output_id is not None and (
                not isinstance(output_id, int)
                or not isinstance(output_sha, str)
                or connection.execute(
                    "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
                ).fetchone()
                is None
                or connection.execute(
                    "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
                ).fetchone()[0]
                != output_sha
            ):
                errors.append("output_lineage_invalid")
    for row in connection.execute(
        "SELECT scope_json,scope_sha256,authority_kind,decision,valid_from_utc,"
        "valid_until_utc,scope_kind,supersedes_approval_id,authority_approval_id "
        "FROM approvals"
    ):
        if _json_hash(row[0]) != row[1]:
            errors.append("approval_scope_sha256_mismatch")
        try:
            scope = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            errors.append("approval_scope_invalid")
            continue
        if (
            not isinstance(scope, dict)
            or not all(
                isinstance(scope.get(key), str)
                for key in (
                    "provider",
                    "action_kind",
                    "entity_kind",
                    "target_key",
                    "scope_kind",
                )
            )
            or not isinstance(scope.get("budget"), dict)
            or scope.get("scope_kind") != row[6]
        ):
            errors.append("approval_scope_invalid")
        budget = scope.get("budget") if isinstance(scope, dict) else None
        max_actions = budget.get("max_actions") if isinstance(budget, dict) else None
        if (
            isinstance(max_actions, bool)
            or not isinstance(max_actions, int)
            or max_actions < 1
        ):
            errors.append("approval_budget_invalid")
        if row[3] == "revoked" and row[7] is None:
            errors.append("approval_revoke_lineage_invalid")
        if row[2] == "scheduled_ai" and row[8] is None:
            errors.append("scheduled_ai_authority_invalid")
        if not _valid_utc(row[4]) or (row[5] is not None and not _valid_utc(row[5])):
            errors.append("approval_temporal_invalid")
    for row in connection.execute(
        "SELECT request_json,request_sha256,source_output_id,source_output_sha256,approval_id,provider,"
        "action_kind,entity_kind,target_key,status FROM external_actions"
    ):
        if not _valid_external_semantics(row[5], row[6], row[7]):
            errors.append("external_action_semantics_invalid")
        if _json_hash(row[0]) != row[1]:
            errors.append("external_action_request_sha256_mismatch")
        output = connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (row[2],)
        ).fetchone()
        approval = connection.execute(
            "SELECT decision,valid_from_utc,valid_until_utc,scope_json,authority_kind,"
            "authority_approval_id,scope_kind "
            "FROM approvals WHERE id=?",
            (row[4],),
        ).fetchone()
        if output is None or row[3] != output[0] or approval is None:
            errors.append("external_action_binding_invalid")
            continue
        if (
            approval[0] != "approved"
            or not _valid_utc(approval[1])
            or (approval[2] is not None and not _valid_utc(approval[2]))
        ):
            errors.append("external_action_approval_invalid")
        try:
            scope = json.loads(approval[3])
            if (
                not isinstance(scope, dict)
                or any(
                    scope.get(key) != value
                    for key, value in (
                        ("provider", row[5]),
                        ("action_kind", row[6]),
                        ("entity_kind", row[7]),
                        ("target_key", row[8]),
                    )
                )
                or scope.get("scope_kind") != approval[6]
            ):
                errors.append("external_action_scope_invalid")
            if approval[4] == "scheduled_ai":
                authority = connection.execute(
                    "SELECT authority_kind,decision,valid_from_utc,valid_until_utc,scope_json,scope_kind "
                    "FROM approvals WHERE id=?",
                    (approval[5],),
                ).fetchone()
                if (
                    authority is None
                    or authority[0] != "user_explicit"
                    or authority[1] != "approved"
                    or not _valid_utc(authority[2])
                    or (authority[3] is not None and not _valid_utc(authority[3]))
                ):
                    errors.append("scheduled_ai_authority_invalid")
                else:
                    try:
                        authority_scope = json.loads(authority[4])
                    except (TypeError, json.JSONDecodeError):
                        authority_scope = None
                    if not isinstance(authority_scope, dict) or any(
                        authority_scope.get(key) != value
                        for key, value in (
                            ("provider", row[5]),
                            ("action_kind", row[6]),
                            ("entity_kind", row[7]),
                            ("target_key", row[8]),
                            ("scope_kind", approval[6]),
                        )
                    ):
                        errors.append("scheduled_ai_authority_scope_invalid")
        except (TypeError, json.JSONDecodeError):
            errors.append("external_action_scope_invalid")
    for row in connection.execute(
        "SELECT target_external_id,provider_object_name FROM external_actions "
        "WHERE provider='garmin' AND action_kind='garmin_workout_delete'"
    ):
        target_external_id, object_name = row
        owner = connection.execute(
            "SELECT owner.id FROM external_actions owner "
            "JOIN external_actions unschedule "
            "ON unschedule.related_action_id=owner.id "
            "AND unschedule.provider='garmin' "
            "AND unschedule.entity_kind='calendar_entry' "
            "AND unschedule.action_kind='garmin_calendar_unschedule' "
            "AND unschedule.status IN ('succeeded','already_done') "
            "WHERE owner.provider='garmin' "
            "AND owner.action_kind IN ('garmin_workout_create','garmin_workout_adopt') "
            "AND owner.status IN ('succeeded','already_done') "
            "AND owner.result_external_id=? AND owner.provider_object_name=? "
            "AND owner.provider_object_name=? "
            "AND substr(owner.provider_object_name,-4)='-GTS'",
            (target_external_id, object_name, object_name),
        ).fetchone()
        if (
            not isinstance(target_external_id, str)
            or not isinstance(object_name, str)
            or not object_name.endswith("-GTS")
            or owner is None
        ):
            errors.append("garmin_delete_ownership_invalid")
    for row in connection.execute(
        "SELECT a.approval_id, json_extract(p.scope_json,'$.budget.max_actions') "
        "FROM external_actions a JOIN approvals p ON p.id=a.approval_id "
        "GROUP BY a.approval_id"
    ):
        action_count = connection.execute(
            "SELECT COUNT(*) FROM external_actions WHERE approval_id=?", (row[0],)
        ).fetchone()[0]
        if not isinstance(row[1], int) or action_count > row[1]:
            errors.append("external_action_budget_exceeded")
    for row in connection.execute(
        "SELECT a.id FROM external_actions a JOIN approvals revoked "
        "ON revoked.supersedes_approval_id=a.approval_id "
        "AND revoked.decision='revoked'"
    ):
        errors.append("external_action_approval_revoked")
    for row in connection.execute(
        "SELECT data_class,activity_binding_state,activity_inventory_id,bound_by_run_id,binding_evidence_json "
        "FROM raw_files WHERE data_class='activity'"
    ):
        if row[1] == "unresolved" and any(value is not None for value in row[2:]):
            errors.append("raw_unresolved_binding_invalid")
        if row[1] == "bound" and not all(value is not None for value in row[2:]):
            errors.append("raw_bound_binding_invalid")
    now = datetime.now(timezone.utc)
    for row in connection.execute(
        "SELECT a.decision,a.valid_until_utc,a.scope_json,e.provider "
        "FROM external_actions e JOIN approvals a ON a.id=e.approval_id"
    ):
        if row[0] != "approved":
            errors.append("external_action_approval_invalid")
        if row[1] is not None and _valid_utc(row[1]):
            expiry = datetime.strptime(str(row[1]), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if expiry <= now:
                errors.append("external_action_approval_expired")
        try:
            scope = json.loads(row[2])
            if isinstance(scope, dict) and scope.get("provider") not in (None, row[3]):
                errors.append("external_action_scope_invalid")
        except (TypeError, json.JSONDecodeError):
            errors.append("external_action_scope_invalid")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    database = (args.database or state_path()).resolve()
    errors: list[str] = []
    connection = connect(database, read_only=True, immutable=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_list = list(connection.execute("PRAGMA table_list"))
        strict_ok = all(
            len(row) < 6 or int(row[5]) == 1
            for row in table_list
            if row[1] in EXPECTED_TABLES
        )
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        sql_text = "\n".join(
            str(row[0])
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table','index')"
            )
            if row[0]
        ).replace(" ", "")
        for table in sorted(EXPECTED_TABLES):
            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
                if row[6] != "RESTRICT":
                    errors.append("foreign_key_action_invalid")
        if tables != EXPECTED_TABLES:
            errors.append("schema_tables_invalid")
        if version != 1:
            errors.append("schema_version_invalid")
        if integrity != "ok":
            errors.append("integrity_check_failed")
        if foreign_keys:
            errors.append("foreign_key_check_failed")
        if not strict_ok:
            errors.append("strict_table_missing")
        if not REQUIRED_TRIGGERS.issubset(triggers):
            errors.append("cross_table_trigger_missing")
        for token in (
            "UNIQUE(dedupe_key,attempt_no)",
            "UNIQUE(logical_key,sha256)",
            "UNIQUE(supersedes_raw_file_id)",
            "UNIQUE(logical_key,content_sha256)",
            "UNIQUE(supersedes_output_id)",
        ):
            if token not in sql_text:
                errors.append("contract_unique_missing")
        duplicate_active = connection.execute(
            """SELECT dedupe_key FROM skill_runs
               WHERE status IN ('pending','running','succeeded')
               GROUP BY dedupe_key HAVING COUNT(*) > 1"""
        ).fetchall()
        if duplicate_active:
            errors.append("active_dedupe_duplicate")
        content_fingerprint: dict[str, object] | None = None
        if tables == EXPECTED_TABLES:
            errors.extend(_raw_errors(connection, database.parent))
            try:
                content_fingerprint = formal_state_content_fingerprint(database)
            except ValueError as exc:
                errors.append(str(exc))
        else:
            errors.append("raw_check_skipped_schema_invalid")
        approval_mismatches = connection.execute(
            """SELECT COUNT(*) FROM approvals a JOIN skill_outputs o ON o.id=a.candidate_output_id
               WHERE a.candidate_output_sha256 <> o.content_sha256"""
        ).fetchone()[0]
        action_mismatches = connection.execute(
            """SELECT COUNT(*) FROM external_actions a JOIN skill_outputs o ON o.id=a.source_output_id
               WHERE a.source_output_sha256 <> o.content_sha256"""
        ).fetchone()[0]
        if approval_mismatches or action_mismatches:
            errors.append("output_hash_binding_invalid")
        errors.extend(_contract_errors(connection))
        payload = {
            "database": str(database),
            "tables": sorted(tables),
            "expected_tables": sorted(EXPECTED_TABLES),
            "schema_exact": tables == EXPECTED_TABLES,
            "user_version": version,
            "strict_tables": strict_ok,
            "integrity_check": integrity,
            "foreign_key_errors": len(foreign_keys),
            "contract_errors": sorted(set(errors)),
            "formal_state_content_fingerprint": content_fingerprint,
            "counts": {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in sorted(EXPECTED_TABLES & tables)
            },
        }
    finally:
        connection.close()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
