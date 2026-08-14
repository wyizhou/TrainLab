#!/usr/bin/env python3
"""Rebuild a clean Garmin-only Foundation store from an archived store.

The input is opened read-only.  Only rows whose provider identity is Garmin
and their referenced projection tables are copied; analysis, mail, user-fact,
delivery and scheduler history is intentionally left behind in the archive.
No provider or network operation is possible from this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from src.foundation import (  # noqa: E402
    FoundationConfig,
    FoundationRequest,
    FoundationTool,
)

UTC = "2026-01-01T00:00:00Z"
GARMIN_TABLES = (
    "data_subjects",
    "subject_identities",
    "raw_objects",
    "source_revisions",
    "resource_coverage",
    "garmin_sync_runs",
    "garmin_sync_items",
    "garmin_sync_cursors",
    "garmin_sync_gaps",
    "garmin_resource_capabilities",
    "source_field_catalog",
    "devices",
    "activities",
    "activity_devices",
    "activity_metric_sources",
    "daily_health",
    "health_samples",
    "physiology_records",
    "physiology_metrics",
    "sleep_sessions",
    "sleep_stages",
    "body_measurements",
    "activity_source_revisions",
    "activity_segments",
    "activity_samples",
    "fit_metric_definitions",
    "activity_aux_messages",
    "fit_unknown_message_catalog",
    "course_points",
    "climbing_routes",
    "strength_sets",
    "data_quality_issues",
    "reconciliation_results",
)
SUBJECT_TABLES = {
    "resource_coverage",
    "garmin_sync_runs",
    "garmin_sync_cursors",
    "garmin_sync_gaps",
    "garmin_resource_capabilities",
    "daily_health",
    "health_samples",
    "physiology_records",
    "sleep_sessions",
    "body_measurements",
}
ACTIVITY_TABLES = {
    "activity_devices",
    "activity_metric_sources",
    "activity_source_revisions",
    "activity_segments",
    "activity_samples",
    "course_points",
}
REVISION_TABLES = {
    "activity_devices",
    "activity_metric_sources",
    "activity_source_revisions",
    "activity_segments",
    "activity_samples",
    "fit_metric_definitions",
    "activity_aux_messages",
    "fit_unknown_message_catalog",
    "resource_coverage",
    "garmin_sync_items",
    "daily_health",
    "health_samples",
    "physiology_records",
    "sleep_sessions",
    "sleep_stages",
    "body_measurements",
    "data_quality_issues",
    "reconciliation_results",
}


def _config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "runtime",
        root / "runtime" / "foundation-ready.json",
        root / "runtime" / "locks" / "foundation.lock",
    )


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))


def _insert_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    rows: Iterable[sqlite3.Row],
) -> int:
    target_columns = _columns(target, table)
    source_columns = _columns(source, table)
    columns = tuple(column for column in source_columns if column in target_columns)
    if not columns:
        return 0
    placeholders = ",".join("?" for _ in columns)
    statement = (
        f'INSERT OR IGNORE INTO "{table}" ({",".join(columns)}) VALUES ({placeholders})'
    )
    count = 0
    for row in rows:
        target.execute(
            statement, tuple(row[source_columns.index(column)] for column in columns)
        )
        count += 1
    return count


def _garmin_provider(value: object) -> bool:
    return isinstance(value, str) and "garmin" in value.lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _raw_source(legacy_state: Path, relative_path: str) -> Path | None:
    relative = Path(relative_path)
    candidate = legacy_state / relative
    if not candidate.is_file() and relative.parts and relative.parts[0] != "raw":
        candidate = legacy_state / "raw" / relative
    if candidate.is_file() and not candidate.is_symlink():
        return candidate
    backups = legacy_state / "backups"
    if backups.is_dir():
        for backup in sorted(backups.iterdir()):
            candidate = backup / relative
            if (
                not candidate.is_file()
                and relative.parts
                and relative.parts[0] != "raw"
            ):
                candidate = backup / "raw" / relative
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


def _raw_source_from_root(root: Path, relative_path: str) -> Path | None:
    """Resolve one archived raw path without traversing unrelated backups."""
    relative = Path(relative_path)
    candidates = [root / relative]
    if relative.parts and relative.parts[0] != "raw":
        candidates.append(root / "raw" / relative)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def rebuild(legacy_state: Path, output_state: Path) -> dict[str, Any]:
    legacy_state = legacy_state.resolve()
    output_state = output_state.resolve()
    if not (legacy_state / "data.db").is_file():
        raise RuntimeError("legacy_database_missing")
    if output_state.exists():
        raise RuntimeError("candidate_state_already_exists")
    output_state.mkdir(mode=0o700, parents=True)
    os.chmod(output_state, 0o700)
    tool = FoundationTool(_config(output_state))
    init = tool.execute(FoundationRequest("init", "offline-garmin-rebuild", UTC))
    if init.status != "initialized":
        raise RuntimeError("candidate_foundation_init_failed")

    source = sqlite3.connect(f"file:{legacy_state / 'data.db'}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(output_state / "data.db")
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    counts: dict[str, int] = {}
    copied_raw: dict[int, int] = {}
    copied_revisions: set[int] = set()
    copied_activities: set[int] = set()
    copied_segments: set[int] = set()
    copied_sync_runs: set[int] = set()
    copied_sleep_sessions: set[int] = set()
    copied_physiology_records: set[int] = set()
    try:
        subject_rows = source.execute(
            "SELECT * FROM data_subjects ORDER BY id"
        ).fetchall()
        counts["data_subjects"] = _insert_rows(
            source, target, "data_subjects", subject_rows
        )
        subject_ids = {int(row[0]) for row in subject_rows}
        identity_rows = [
            row
            for row in source.execute("SELECT * FROM subject_identities")
            if _garmin_provider(row[2])
        ]
        counts["subject_identities"] = _insert_rows(
            source, target, "subject_identities", identity_rows
        )

        raw_rows = [
            row
            for row in source.execute("SELECT * FROM raw_objects")
            if _garmin_provider(row[5])
        ]
        active_raw_shas = {str(row[1]) for row in raw_rows}
        revisions = [
            row
            for row in source.execute("SELECT * FROM source_revisions")
            if _garmin_provider(row[1])
        ]

        # Raw bytes are the offline source of truth, even when an object has no
        # current revision.  Copy every verified Garmin raw row first; filtering
        # to revision-backed rows would silently drop unreferenced evidence and
        # make the rebuilt store differ from the archived raw tree.
        for raw in raw_rows:
            source_path = _raw_source(legacy_state, str(raw[2]))
            if source_path is None or _sha256(source_path) != str(raw[1]):
                continue
            destination = output_state / str(raw[2])
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(destination.parent, 0o700)
            shutil.copyfile(source_path, destination)
            os.chmod(destination, 0o600)
            target.execute(
                "INSERT OR IGNORE INTO raw_objects VALUES (?,?,?,?,?,?,?,?,?)",
                tuple(raw),
            )
            copied_raw[int(raw[0])] = int(raw[0])

        backup_only_raw = 0
        backup_root = legacy_state / "backups"
        if backup_root.is_dir():
            target_raw_columns = _columns(target, "raw_objects")
            insert_columns = tuple(
                column for column in target_raw_columns if column != "id"
            )
            insert_statement = (
                f'INSERT INTO "raw_objects" ({",".join(insert_columns)}) '
                f"VALUES ({','.join('?' for _ in insert_columns)})"
            )
            for backup_db in sorted(backup_root.rglob("data.db")):
                backup_dir = backup_db.parent
                backup = sqlite3.connect(f"file:{backup_db}?mode=ro", uri=True)
                backup.row_factory = sqlite3.Row
                try:
                    backup_columns = _columns(backup, "raw_objects")
                    if not backup_columns:
                        continue
                    for raw in backup.execute("SELECT * FROM raw_objects"):
                        provider_index = backup_columns.index("provider")
                        sha_index = backup_columns.index("sha256")
                        if not _garmin_provider(raw[provider_index]):
                            continue
                        sha = str(raw[sha_index])
                        if sha in active_raw_shas:
                            continue
                        present = target.execute(
                            "SELECT id FROM raw_objects WHERE sha256=?", (sha,)
                        ).fetchone()
                        if present is not None:
                            active_raw_shas.add(sha)
                            continue
                        relative_index = backup_columns.index("relative_path")
                        source_path = _raw_source_from_root(
                            backup_dir, str(raw[relative_index])
                        )
                        if source_path is None or _sha256(source_path) != sha:
                            continue
                        backup_label = hashlib.sha256(
                            str(backup_db).encode("utf-8")
                        ).hexdigest()[:12]
                        raw_id = int(raw[backup_columns.index("id")])
                        destination = (
                            output_state
                            / "raw"
                            / "backup"
                            / backup_label
                            / f"{raw_id}-{source_path.name}"
                        )
                        destination.parent.mkdir(
                            mode=0o700, parents=True, exist_ok=True
                        )
                        os.chmod(destination.parent, 0o700)
                        shutil.copyfile(source_path, destination)
                        os.chmod(destination, 0o600)
                        values = tuple(
                            raw[backup_columns.index(column)]
                            for column in insert_columns
                        )
                        values = (
                            values[:1]
                            + (str(destination.relative_to(output_state)),)
                            + values[2:]
                        )
                        target.execute(insert_statement, values)
                        active_raw_shas.add(sha)
                        backup_only_raw += 1
                finally:
                    backup.close()
        counts["backup_only_raw_objects"] = backup_only_raw
        counts["raw_objects"] = len(copied_raw) + backup_only_raw
        revision_rows = [
            row for row in revisions if row[5] is None or int(row[5]) in copied_raw
        ]
        counts["source_revisions"] = _insert_rows(
            source, target, "source_revisions", revision_rows
        )
        copied_revisions = {int(row[0]) for row in revision_rows}

        def rows_for(table: str) -> list[sqlite3.Row]:
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            columns = _columns(source, table)
            subject_index = (
                columns.index("subject_id") if "subject_id" in columns else None
            )
            provider_index = (
                columns.index("provider") if "provider" in columns else None
            )
            revision_index = (
                columns.index("source_revision_id")
                if "source_revision_id" in columns
                else None
            )
            selected: list[sqlite3.Row] = []
            for row in rows:
                if (
                    subject_index is not None
                    and int(row[subject_index]) not in subject_ids
                ):
                    continue
                if provider_index is not None and not _garmin_provider(
                    row[provider_index]
                ):
                    continue
                if revision_index is not None:
                    revision_id = row[revision_index]
                    if (
                        revision_id is not None
                        and int(revision_id) not in copied_revisions
                    ):
                        continue
                selected.append(row)
            return selected

        for table in (
            "resource_coverage",
            "garmin_sync_runs",
            "garmin_sync_cursors",
            "garmin_sync_gaps",
            "garmin_resource_capabilities",
            "source_field_catalog",
            "daily_health",
            "health_samples",
            "physiology_records",
            "sleep_sessions",
            "body_measurements",
            "devices",
        ):
            selected = rows_for(table)
            try:
                counts[table] = _insert_rows(source, target, table, selected)
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(f"candidate_insert_failed:{table}") from exc
            if table == "sleep_sessions":
                copied_sleep_sessions = {int(row[0]) for row in selected}
            elif table == "physiology_records":
                copied_physiology_records = {int(row[0]) for row in selected}
            if table == "garmin_sync_runs":
                copied_sync_runs = {int(row[0]) for row in selected}

        activity_columns = _columns(source, "activities")
        provider_index = activity_columns.index("provider")
        activities = [
            row
            for row in source.execute("SELECT * FROM activities")
            if _garmin_provider(row[provider_index])
        ]
        counts["activities"] = _insert_rows(source, target, "activities", activities)
        copied_activities = {int(row[0]) for row in activities}
        activity_rows = {
            "activity_devices",
            "activity_metric_sources",
            "activity_source_revisions",
            "activity_segments",
            "activity_samples",
            "course_points",
        }
        for table in sorted(activity_rows):
            columns = _columns(source, table)
            selected = [
                row
                for row in source.execute(f'SELECT * FROM "{table}"').fetchall()
                if "activity_id" not in columns
                or int(row[columns.index("activity_id")]) in copied_activities
            ]
            try:
                counts[table] = _insert_rows(source, target, table, selected)
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(f"candidate_insert_failed:{table}") from exc
            if table == "activity_segments":
                copied_segments = {int(row[0]) for row in selected}
        for table in (
            "garmin_sync_items",
            "sleep_stages",
            "physiology_metrics",
            "fit_metric_definitions",
            "activity_aux_messages",
            "fit_unknown_message_catalog",
            "climbing_routes",
            "strength_sets",
            "data_quality_issues",
            "reconciliation_results",
        ):
            columns = _columns(source, table)
            selected = []
            for row in source.execute(f'SELECT * FROM "{table}"').fetchall():
                keep = True
                if "garmin_sync_run_id" in columns:
                    keep = (
                        row[columns.index("garmin_sync_run_id")] is None
                        or int(row[columns.index("garmin_sync_run_id")])
                        in copied_sync_runs
                    )
                if "sleep_session_id" in columns:
                    session_id = row[columns.index("sleep_session_id")]
                    keep = (
                        keep
                        and session_id is not None
                        and int(session_id) in copied_sleep_sessions
                    )
                if "physiology_record_id" in columns:
                    record_id = row[columns.index("physiology_record_id")]
                    keep = (
                        keep
                        and record_id is not None
                        and int(record_id) in copied_physiology_records
                    )
                if "segment_id" in columns:
                    segment_id = row[columns.index("segment_id")]
                    keep = (
                        keep
                        and segment_id is not None
                        and int(segment_id) in copied_segments
                    )
                if "parent_segment_id" in columns:
                    parent_id = row[columns.index("parent_segment_id")]
                    keep = keep and (
                        parent_id is None or int(parent_id) in copied_segments
                    )
                for revision_column in (
                    "left_source_revision_id",
                    "right_source_revision_id",
                ):
                    if revision_column in columns:
                        revision_id = row[columns.index(revision_column)]
                        keep = keep and (
                            revision_id is None or int(revision_id) in copied_revisions
                        )
                if "activity_id" in columns:
                    keep = (
                        keep
                        and int(row[columns.index("activity_id")]) in copied_activities
                    )
                if "source_revision_id" in columns:
                    keep = keep and (
                        row[columns.index("source_revision_id")] is None
                        or int(row[columns.index("source_revision_id")])
                        in copied_revisions
                    )
                selected.append(row) if keep else None
            try:
                counts[table] = _insert_rows(source, target, table, selected)
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(f"candidate_insert_failed:{table}") from exc
        # A rebuilt store starts from Garmin facts, coverage and cursors.  The
        # old collector run/item ledger is operational history, not a fact
        # source, and is deliberately left in data-backup with the legacy DB.
        # Clear cursor foreign keys before removing that ledger so the new
        # database cannot accidentally resume an archived invocation.
        target.execute("UPDATE garmin_sync_cursors SET last_run_id=NULL")
        target.execute("DELETE FROM garmin_sync_items")
        target.execute("DELETE FROM garmin_sync_runs")
        counts["garmin_sync_runs"] = 0
        counts["garmin_sync_items"] = 0
        target.commit()
        raw_root = output_state / "raw"
        if raw_root.is_dir():
            for directory in (
                raw_root,
                *[p for p in raw_root.rglob("*") if p.is_dir()],
            ):
                os.chmod(directory, 0o700)
        integrity = [row[0] for row in target.execute("PRAGMA integrity_check")]
        foreign = target.execute("PRAGMA foreign_key_check").fetchone()
        if integrity != ["ok"] or foreign is not None:
            raise RuntimeError("candidate_integrity_failed")
    finally:
        source.close()
        target.close()

    manifest = {
        "schema_version": 1,
        "foundation_schema_version": init.foundation_schema_version,
        "source_kind": "garmin_offline_rebuild",
        "legacy_state_archived": True,
        "counts": counts,
        "legacy_fit_candidates": 0,
        "unresolved_legacy_fit": 0,
        "provider_calls": 0,
        "mail_rows_migrated": 0,
        "analysis_rows_migrated": 0,
        "scheduler_rows_migrated": 0,
    }
    legacy_fit_root = legacy_state / "legacy"
    if legacy_fit_root.is_dir():
        legacy_fit_hashes = {
            _sha256(path)
            for path in legacy_fit_root.rglob("*.fit")
            if path.is_file() and not path.is_symlink()
        }
        manifest["legacy_fit_candidates"] = len(legacy_fit_hashes)
        manifest["unresolved_legacy_fit"] = sum(
            sha not in active_raw_shas for sha in legacy_fit_hashes
        )
    marker = output_state / "runtime" / "rebuild-manifest.json"
    marker.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(marker, 0o600)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-state", type=Path, required=True)
    parser.add_argument("--output-state", type=Path, required=True)
    args = parser.parse_args(argv)
    result = rebuild(args.legacy_state, args.output_state)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
