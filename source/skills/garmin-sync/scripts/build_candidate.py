#!/usr/bin/env python3
"""Build a new raw-first state candidate from the old DB without changing it.

This is an offline migration helper. It copies only provable selected health
resources and activity originals; all other old bytes remain in the old state
until the caller performs the approved archive/cutover.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    init_database,
    require_lastrowid,
    sha256_file,
    utc_now,
)

HEALTH_RESOURCES = ("sleep", "rhr", "hrv", "heart_rates", "max_metrics", "weigh_ins")


def activity_hash(provider: str, provider_activity_id: str) -> str:
    return hashlib.sha256(
        f"{provider}\0{provider_activity_id}".encode("utf-8")
    ).hexdigest()


def copy_verified(source: Path, destination: Path) -> str:
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"source is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("rb") as source_handle,
        destination.open("xb") as destination_handle,
    ):
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
    os.chmod(destination, 0o600)
    source_sha = sha256_file(source)
    if sha256_file(destination) != source_sha:
        raise ValueError(f"copy hash mismatch: {destination}")
    return source_sha


def relative_source(old_state: Path, relative_path: str) -> Path:
    path = (old_state / relative_path).resolve()
    if old_state.resolve() not in path.parents:
        raise ValueError("old raw path escapes old state")
    return path


def add_raw_file(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    provider: str,
    data_class: str,
    resource_kind: str,
    logical_key: str,
    data_date: str,
    relative_path: str,
    file_format: str,
    byte_size: int,
    sha256: str,
    activity_inventory_id: int | None = None,
    binding_state: str = "not_applicable",
    binding_evidence: dict[str, object] | None = None,
) -> int:
    cursor = connection.execute(
        """INSERT INTO raw_files
        (provider,data_class,resource_kind,logical_key,revision_no,activity_inventory_id,
         activity_binding_state,bound_by_run_id,binding_evidence_json,data_date,relative_path,
         file_format,byte_size,sha256,registered_by_run_id,integrity_state,registered_at_utc,
         last_verified_at_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            provider,
            data_class,
            resource_kind,
            logical_key,
            1,
            activity_inventory_id,
            binding_state,
            run_id if binding_state == "bound" else None,
            canonical_json(binding_evidence) if binding_evidence else None,
            data_date,
            relative_path,
            file_format,
            byte_size,
            sha256,
            run_id,
            "verified",
            utc_now(),
            utc_now(),
        ),
    )
    return require_lastrowid(cursor)


def select_health(
    source_connection: sqlite3.Connection,
    target_connection: sqlite3.Connection,
    old_state: Path,
    candidate_state: Path,
    run_id: int,
) -> dict[str, int]:
    counts = {kind: 0 for kind in HEALTH_RESOURCES}
    selected: dict[tuple[str, str], sqlite3.Row] = {}
    rows = list(
        source_connection.execute(
            """SELECT sr.id, sr.resource_kind, sr.revision_no, sr.is_current, ro.relative_path,
                  ro.size_bytes, ro.sha256, rc.local_date
             FROM source_revisions sr
             JOIN raw_objects ro ON ro.id=sr.raw_object_id
             LEFT JOIN resource_coverage rc ON rc.source_revision_id=sr.id
            WHERE sr.provider='garmin' AND sr.resource_kind IN (?,?,?,?,?,?)
            ORDER BY sr.resource_kind, rc.local_date, sr.revision_no DESC, sr.id DESC""",
            HEALTH_RESOURCES,
        )
    )
    dates_by_revision: dict[int, set[str]] = {}
    row_by_revision: dict[int, sqlite3.Row] = {}
    for row in rows:
        row_by_revision[int(row[0])] = row
        if row[7] is not None:
            dates_by_revision.setdefault(int(row[0]), set()).add(str(row[7]))
    for revision_id, dates in dates_by_revision.items():
        if len(dates) != 1:
            continue
        row = row_by_revision[revision_id]
        key = (str(row[1]), next(iter(dates)))
        previous = selected.get(key)
        if previous is None or int(row[2]) > int(previous[2]):
            selected[key] = row
    for (kind, data_date), row in selected.items():
        source = relative_source(old_state, str(row[4]))
        destination_name = f"{data_date.replace('-', '')}-{kind}-{row[6]}.json"
        destination = candidate_state / "raw/garmin/health" / destination_name
        digest = copy_verified(source, destination)
        if digest != str(row[6]) or destination.stat().st_size != int(row[5]):
            raise ValueError(f"old raw metadata mismatch: {source}")
        add_raw_file(
            target_connection,
            run_id=run_id,
            provider="garmin",
            data_class="health",
            resource_kind=kind,
            logical_key=f"garmin:{kind}:{data_date}",
            data_date=data_date,
            relative_path=f"garmin/health/{destination_name}",
            file_format="json",
            byte_size=destination.stat().st_size,
            sha256=digest,
        )
        counts[kind] += 1
    return counts


def select_revision(
    connection: sqlite3.Connection, activity_id: int, kind: str, role: str | None = None
) -> sqlite3.Row | None:
    sql = """SELECT sr.id, sr.resource_kind, sr.provider_object_id, ro.relative_path, ro.size_bytes, ro.sha256
               FROM activity_source_revisions asr
               JOIN source_revisions sr ON sr.id=asr.source_revision_id
               JOIN raw_objects ro ON ro.id=sr.raw_object_id
              WHERE asr.activity_id=? AND sr.resource_kind=?"""
    params: list[object] = [activity_id, kind]
    if role:
        sql += " AND asr.source_role=?"
        params.append(role)
    sql += " ORDER BY sr.revision_no DESC, sr.id DESC LIMIT 1"
    return connection.execute(sql, params).fetchone()


def select_original_by_provider_id(
    connection: sqlite3.Connection, provider_activity_id: str, kind: str
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT sr.id, sr.resource_kind, sr.provider_object_id, ro.relative_path, ro.size_bytes, ro.sha256
             FROM source_revisions sr JOIN raw_objects ro ON ro.id=sr.raw_object_id
            WHERE sr.provider='garmin' AND sr.resource_kind=? AND sr.provider_object_id=?
            ORDER BY sr.revision_no DESC, sr.id DESC LIMIT 1""",
        (kind, provider_activity_id),
    ).fetchone()


def select_activities(
    source_connection: sqlite3.Connection,
    target_connection: sqlite3.Connection,
    old_state: Path,
    candidate_state: Path,
    run_id: int,
) -> dict[str, int]:
    counts = {
        "activities": 0,
        "fit": 0,
        "gpx": 0,
        "tcx": 0,
        "weather": 0,
        "incomplete": 0,
    }
    for activity in source_connection.execute(
        "SELECT id, provider, provider_activity_id, local_date FROM activities WHERE provider='garmin' ORDER BY id"
    ):
        provider_id = str(activity[2])
        data_date = str(activity[3])
        hash_value = activity_hash(str(activity[1]), provider_id)
        fit = select_revision(
            source_connection, int(activity[0]), "activity_fit", "activity_fit"
        )
        gpx = select_original_by_provider_id(
            source_connection, provider_id, "activity_original_gpx"
        )
        tcx = select_original_by_provider_id(
            source_connection, provider_id, "activity_original_tcx"
        )
        weather = select_revision(
            source_connection, int(activity[0]), "activity_weather", "weather_json"
        )
        formats = ["fit"] if fit else []
        if gpx:
            formats.append("gpx")
        if tcx:
            formats.append("tcx")
        if weather:
            formats.append("weather")
        inventory_cursor = target_connection.execute(
            """INSERT INTO activity_inventory
               (provider,provider_activity_id,activity_hash,activity_hash_version,activity_date,
                expected_formats_json,collection_state,weather_state,collection_policy_version,
                first_seen_at_utc,last_seen_at_utc,discovered_by_run_id,updated_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "garmin",
                provider_id,
                hash_value,
                "provider-nul-id-sha256-v1",
                data_date,
                canonical_json(formats),
                "collecting",
                "complete" if weather else "not_available",
                "offline-index-v1",
                utc_now(),
                utc_now(),
                run_id,
                utc_now(),
            ),
        )
        inventory_id = require_lastrowid(inventory_cursor)
        counts["activities"] += 1
        if not fit:
            counts["incomplete"] += 1
        for revision, suffix, kind, key in (
            (fit, "fit", "activity_fit", "fit"),
            (gpx, "gpx", "activity_original_gpx", "gpx"),
            (tcx, "tcx", "activity_original_tcx", "tcx"),
            (weather, "weather.json", "activity_weather", "weather"),
        ):
            if not revision:
                continue
            source = relative_source(old_state, str(revision[3]))
            destination_name = f"{data_date.replace('-', '')}-{hash_value}.{suffix}"
            destination = candidate_state / "raw/garmin/activities" / destination_name
            digest = copy_verified(source, destination)
            if digest != str(revision[5]) or destination.stat().st_size != int(
                revision[4]
            ):
                raise ValueError(f"activity raw metadata mismatch: {source}")
            add_raw_file(
                target_connection,
                run_id=run_id,
                provider="garmin",
                data_class="activity",
                resource_kind=kind,
                logical_key=f"garmin:activity:{hash_value}:{key}",
                data_date=data_date,
                relative_path=f"garmin/activities/{destination_name}",
                file_format="json" if key == "weather" else key,
                byte_size=destination.stat().st_size,
                sha256=digest,
                activity_inventory_id=inventory_id,
                binding_state="bound",
                binding_evidence={
                    "provider": "garmin",
                    "provider_activity_id": provider_id,
                    "activity_hash": hash_value,
                    "hash_version": "provider-nul-id-sha256-v1",
                },
            )
            counts[key] += 1
        target_connection.execute(
            "UPDATE activity_inventory SET collection_state=?, weather_state=?, "
            "last_collection_at_utc=?, last_collection_run_id=?, updated_at_utc=? WHERE id=?",
            (
                "complete" if fit else "incomplete",
                "complete" if weather else "not_available",
                utc_now(),
                run_id,
                utc_now(),
                inventory_id,
            ),
        )
    return counts


def exclusion_summary(
    source_connection: sqlite3.Connection,
    target_connection: sqlite3.Connection,
) -> dict[str, object]:
    """Describe excluded historical raw without exposing paths or payloads."""
    selected = {
        (str(row[0]), int(row[1]))
        for row in target_connection.execute("SELECT sha256, byte_size FROM raw_files")
    }
    old_rows = list(
        source_connection.execute(
            "SELECT sha256, size_bytes FROM raw_objects WHERE provider='garmin'"
        )
    )
    old_pairs = {(str(row[0]), int(row[1])) for row in old_rows}
    excluded_pairs = old_pairs - selected
    current_by_kind: dict[str, int] = {}
    for row in source_connection.execute(
        """SELECT sr.resource_kind, ro.sha256, ro.size_bytes
             FROM source_revisions sr JOIN raw_objects ro ON ro.id=sr.raw_object_id
            WHERE sr.provider='garmin' AND sr.is_current=1"""
    ):
        if (str(row[1]), int(row[2])) in excluded_pairs:
            kind = str(row[0])
            current_by_kind[kind] = current_by_kind.get(kind, 0) + 1
    return {
        "old_unique_garmin_sha_size": len(old_pairs),
        "selected_unique_garmin_sha_size": len(old_pairs & selected),
        "excluded_unique_garmin_sha_size": len(excluded_pairs),
        "excluded_current_revision_rows_by_resource": dict(
            sorted(current_by_kind.items())
        ),
        "excluded_policy": [
            "activity_inventory_json",
            "activity_summary_json",
            "activity_auxiliary_json",
            "account_device_profile_json",
            "multi_day_range_json",
            "unresolved_or_unclassified_raw",
        ],
        "excluded_destination": "data-backup/<operation-id>/old-source-state",
        "excluded_bytes_deleted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-state", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    old_state = args.old_state.resolve()
    candidate = args.candidate.resolve()
    if candidate.exists() and any(candidate.iterdir()):
        raise SystemExit("candidate must be a new or empty directory")
    candidate.mkdir(parents=True, exist_ok=True)
    os.chmod(candidate, 0o700)
    candidate_state = candidate / "state"
    for directory in (
        candidate_state,
        candidate_state / "raw",
        candidate_state / "raw/garmin",
        candidate_state / "raw/garmin/health",
        candidate_state / "raw/garmin/activities",
        candidate_state / "backups",
        candidate_state / "backups/sqlite",
        candidate_state / "recovery-quarantine",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    database = candidate_state / "trainlab.db"
    print(
        json.dumps(
            {"stage": "candidate_initialized", "candidate": str(candidate)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    init_database(database)
    old_connection = sqlite3.connect(f"file:{old_state / 'data.db'}?mode=ro", uri=True)
    old_connection.row_factory = sqlite3.Row
    new_connection = connect(database)
    try:
        manifest = {
            "schema_version": "1",
            "operation": "index_existing_raw",
            "source": "old-state-read-only",
        }
        run_id = begin_run(
            new_connection,
            run_key="adhoc0011:index-existing-raw",
            workflow_key="adhoc0011",
            dedupe_key="index-existing-raw",
            skill_name="garmin-sync",
            operation="index_existing_raw",
            trigger_kind="recovery",
            input_manifest=manifest,
        )
        print(json.dumps({"stage": "health_start"}, ensure_ascii=False), flush=True)
        health_counts = select_health(
            old_connection, new_connection, old_state, candidate_state, run_id
        )
        print(
            json.dumps(
                {"stage": "health_done", "counts": health_counts}, ensure_ascii=False
            ),
            flush=True,
        )
        activity_counts = select_activities(
            old_connection, new_connection, old_state, candidate_state, run_id
        )
        print(
            json.dumps(
                {"stage": "activity_done", "counts": activity_counts},
                ensure_ascii=False,
            ),
            flush=True,
        )
        summary = {
            "health": health_counts,
            "activity": activity_counts,
            "external_calls": 0,
            "excluded_history": exclusion_summary(old_connection, new_connection),
        }
        append_output(
            new_connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="adhoc0011:index-existing-raw",
            schema_name="raw_index_summary",
            schema_version="1",
            content_json=summary,
            lineage=[],
        )
        new_connection.execute(
            "UPDATE skill_runs SET status='succeeded', finished_at_utc=?, heartbeat_at_utc=? WHERE id=?",
            (utc_now(), utc_now(), run_id),
        )
        new_connection.commit()
    finally:
        new_connection.close()
        old_connection.close()
    (candidate / "migration-manifest.json").write_text(
        json.dumps(
            {"schema_version": "1", "operation": "adhoc0011", "summary": summary},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(candidate / "migration-manifest.json", 0o600)
    print(
        json.dumps(
            {"candidate": str(candidate), "summary": summary},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
