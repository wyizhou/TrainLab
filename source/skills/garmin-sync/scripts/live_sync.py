#!/usr/bin/env python3
"""Bounded, single-window Garmin MCP capture for M9."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills._shared.scripts import build_m8_candidate as candidate_builder
from skills._shared.scripts.schema_validation import require_valid_payload
from skills._shared.state import (
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    require_lastrowid,
    sha256_bytes,
    sha256_file,
    sha256_text,
    utc_now,
    workflow_lock,
)

monotonic = time.monotonic

MCP_COMMIT = "3610be6feed93088d85b0f35aba9d7d07c2505a7"
WORKFLOW_KEY = "daily:2026-08-17"
SYNC_LOGICAL_KEY = "garmin-live:2026-08-17:sync"
HEALTH_DATE = "2026-08-16"
SLEEP_DATE = "2026-08-17"
WALL_SECONDS = 90.0
FINALIZATION_RESERVE_SECONDS = 15.0
COLLECTION_PHASE_SECONDS = WALL_SECONDS - FINALIZATION_RESERVE_SECONDS

ALLOWED_TOOLS = {
    "download_activity_file",
    "get_activities_by_date",
    "get_activity_weather",
    "get_heart_rates",
    "get_hrv_data",
    "get_rhr_day",
    "get_sleep_data",
    "get_vo2max_trend",
    "get_weigh_ins",
}

BASE_CALLS: list[dict[str, Any]] = [
    {"tool": "get_rhr_day", "arguments": {"date": HEALTH_DATE}},
    {
        "tool": "get_hrv_data",
        "arguments": {"date": HEALTH_DATE, "return_timeseries": False},
    },
    {"tool": "get_heart_rates", "arguments": {"date": HEALTH_DATE}},
    {
        "tool": "get_vo2max_trend",
        "arguments": {"start_date": HEALTH_DATE, "end_date": HEALTH_DATE},
    },
    {
        "tool": "get_weigh_ins",
        "arguments": {"start_date": HEALTH_DATE, "end_date": HEALTH_DATE},
    },
    {"tool": "get_sleep_data", "arguments": {"date": SLEEP_DATE}},
    {
        "tool": "get_activities_by_date",
        "arguments": {
            "start_date": HEALTH_DATE,
            "end_date": HEALTH_DATE,
            "page": 0,
            "page_size": 10,
        },
    },
]

RESOURCE_BY_TOOL = {
    "get_rhr_day": "rhr",
    "get_hrv_data": "hrv",
    "get_heart_rates": "heart_rates",
    "get_vo2max_trend": "max_metrics",
    "get_weigh_ins": "weigh_ins",
    "get_sleep_data": "sleep",
    "get_activities_by_date": "activity_inventory",
    "get_activity_weather": "activity_weather",
}


class FitInspection(NamedTuple):
    valid: bool
    outdoor: bool


class ToolResponse(NamedTuple):
    payload: bytes
    is_error: bool


class LiveSyncError(RuntimeError):
    pass


def _enforce_wall_deadline(
    result: dict[str, Any], start: float, *, limit: float = WALL_SECONDS
) -> bool:
    """Downgrade an unfinished success when the full wall budget is spent."""

    if monotonic() - start < limit:
        return False
    changed = (
        result.get("status") != "blocked"
        or result.get("error_code") != "garmin_live_wall_budget_exceeded"
    )
    result["status"] = "blocked"
    result["error_code"] = "garmin_live_wall_budget_exceeded"
    return changed


def approved_request() -> dict[str, Any]:
    return {
        "schema_version": "garmin_live_request_v1",
        "timezone": "Asia/Hong_Kong",
        "run_date": "2026-08-17",
        "health_activity_date": HEALTH_DATE,
        "sleep_wake_date": SLEEP_DATE,
        "mcp_commit": MCP_COMMIT,
        "garminconnect_version": "0.3.9",
        "mcp_version": "1.29.0",
        "base_calls": BASE_CALLS,
        "optional_tools": ["download_activity_file", "get_activity_weather"],
        "budgets": {
            "mcp_tool_calls": 11,
            "provider_entries": 12,
            "activity_ids": 10,
            "fit_files": 2,
            "weather_calls": 2,
            "new_files": 11,
            "wall_seconds": 90,
        },
        "cached_tokens_only": True,
        "retries": 0,
    }


def validate_request(request: dict[str, Any]) -> None:
    try:
        require_valid_payload(request, "garmin_live_request_v1")
    except ValueError as exc:
        raise ValueError("garmin_live_request_invalid") from exc
    if canonical_json(request) != canonical_json(approved_request()):
        raise ValueError("garmin_live_request_invalid")


def _token_fingerprint(token_dir: Path) -> str:
    if not token_dir.is_dir() or token_dir.is_symlink():
        raise LiveSyncError("cached_token_unavailable")
    root_stat = token_dir.stat(follow_symlinks=False)
    if root_stat.st_uid != os.getuid() or stat.S_IMODE(root_stat.st_mode) & 0o077:
        raise LiveSyncError("cached_token_unsafe")
    records: list[dict[str, Any]] = [
        {
            "path": ".",
            "type": "dir",
            "dev": root_stat.st_dev,
            "inode": root_stat.st_ino,
            "uid": root_stat.st_uid,
            "gid": root_stat.st_gid,
            "mode": stat.S_IMODE(root_stat.st_mode),
            "size": root_stat.st_size,
            "mtime_ns": root_stat.st_mtime_ns,
            "ctime_ns": root_stat.st_ctime_ns,
        }
    ]
    for path in sorted(token_dir.rglob("*")):
        relative = path.relative_to(token_dir).as_posix()
        metadata = path.stat(follow_symlinks=False)
        if path.is_symlink():
            raise LiveSyncError("cached_token_unsafe")
        if path.is_dir():
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
                raise LiveSyncError("cached_token_unsafe")
            records.append(
                {
                    "path": relative,
                    "type": "dir",
                    "dev": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "size": metadata.st_size,
                    "mtime_ns": metadata.st_mtime_ns,
                    "ctime_ns": metadata.st_ctime_ns,
                }
            )
            continue
        if not path.is_file() or metadata.st_nlink != 1:
            raise LiveSyncError("cached_token_unsafe")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise LiveSyncError("cached_token_unsafe")
        records.append(
            {
                "path": relative,
                "type": "file",
                "dev": metadata.st_dev,
                "inode": metadata.st_ino,
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": stat.S_IMODE(metadata.st_mode),
                "size": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "ctime_ns": metadata.st_ctime_ns,
                "sha256": sha256_file(path),
            }
        )
    if not any(item["type"] == "file" for item in records):
        raise LiveSyncError("cached_token_unavailable")
    return sha256_text(canonical_json(records))


def _copy_token_shadow(token_dir: Path) -> tuple[Path, str, str]:
    """Copy validated cached tokens to an ephemeral, non-candidate shadow."""

    original = _token_fingerprint(token_dir)
    shadow = Path(tempfile.mkdtemp(prefix="trainlab-m9-token-shadow-"))
    os.chmod(shadow, 0o700)
    try:
        for source in sorted(token_dir.rglob("*")):
            relative = source.relative_to(token_dir)
            destination = shadow / relative
            metadata = source.lstat()
            if source.is_symlink():
                raise LiveSyncError("cached_token_unsafe")
            if source.is_dir():
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chmod(destination, 0o700)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise LiveSyncError("cached_token_unsafe")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(source.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(destination, 0o400)
        shadow_fingerprint = _token_fingerprint(shadow)
    except Exception:
        shutil.rmtree(shadow, ignore_errors=True)
        raise
    return shadow, original, shadow_fingerprint


def _remove_token_shadow(shadow: Path) -> None:
    for path in sorted(shadow.rglob("*"), reverse=True):
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file() and not path.is_symlink():
            os.chmod(path, 0o600)
    shutil.rmtree(shadow, ignore_errors=True)


def _formal_fingerprint_valid(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "formal_state_fingerprint_v1"
    ):
        return False
    entries = value.get("entries")
    if not isinstance(entries, list) or any(
        not isinstance(item, dict) for item in entries
    ):
        return False
    if entries != sorted(entries, key=lambda item: str(item.get("path", ""))):
        return False
    return (
        value.get("entry_count") == len(entries)
        and value.get("raw_entry_count")
        == sum(1 for item in entries if str(item.get("path", "")).startswith("raw/"))
        and value.get("sha256") == sha256_text(canonical_json(entries))
    )


def _candidate_seed_entries(
    connection: Any, root: Path, raw_max_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT id,relative_path,byte_size,sha256 FROM raw_files WHERE id<=? ORDER BY id",
        (raw_max_id,),
    ).fetchall()
    raw_root = root / "state/raw"
    entries: list[dict[str, Any]] = []
    for row in rows:
        relative = Path(str(row[1]))
        if relative.is_absolute() or ".." in relative.parts:
            raise LiveSyncError("candidate_scope_required")
        path = Path(os.path.abspath(raw_root / relative))
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise LiveSyncError("candidate_scope_required") from exc
        if (
            path.resolve(strict=True) != path
            or not path.is_relative_to(raw_root)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != int(row[2])
            or sha256_file(path) != str(row[3])
        ):
            raise LiveSyncError("candidate_scope_required")
        entries.append(
            {
                "id": int(row[0]),
                "relative_path": relative.as_posix(),
                "byte_size": int(row[2]),
                "sha256": str(row[3]),
            }
        )
    return entries


def _assert_candidate_sidecars_quiescent(database: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if not sidecar.exists() and not sidecar.is_symlink():
            continue
        try:
            metadata = sidecar.lstat()
        except OSError as exc:
            raise LiveSyncError("candidate_scope_required") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (suffix == "-wal" and metadata.st_size != 0)
        ):
            raise LiveSyncError("candidate_scope_required")
    try:
        candidate_builder._assert_candidate_sidecars_quiescent(database)
    except (OSError, ValueError) as exc:
        raise LiveSyncError("candidate_scope_required") from exc


def _assert_formal_source_evidence(
    formal_source: Path,
    expected_fingerprint: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    """Re-read the locked formal state before allowing any Provider entry."""

    try:
        with candidate_builder._formal_state_lock(formal_source):
            current = candidate_builder._formal_state_fingerprint(formal_source)
            formal_seed = candidate_builder._candidate_seed_manifest(formal_source)
    except (OSError, ValueError) as exc:
        raise LiveSyncError("candidate_scope_required") from exc
    if current != expected_fingerprint:
        raise LiveSyncError("candidate_scope_required")
    for key in ("raw_max_id", "raw_count", "raw_bytes", "raw_manifest_sha256"):
        if receipt.get(key) != formal_seed.get(key):
            raise LiveSyncError("candidate_scope_required")


def _assert_candidate_provenance(
    root: Path, db: Path, marker_payload: dict[str, Any]
) -> None:
    before = marker_payload.get("before")
    after = marker_payload.get("after")
    scope = marker_payload.get("candidate_scope")
    runtime_source = Path(__file__).resolve().parents[3]
    repository_root = runtime_source.parent
    if (
        before != after
        or not _formal_fingerprint_valid(before)
        or not isinstance(scope, dict)
        or not isinstance(scope.get("output_id"), int)
        or not isinstance(scope.get("output_sha256"), str)
        or root == runtime_source
        or root.is_relative_to(runtime_source)
        or root == repository_root
        or root.is_relative_to(repository_root)
    ):
        raise LiveSyncError("candidate_scope_required")
    _assert_candidate_sidecars_quiescent(db)
    assert isinstance(before, dict)
    connection = connect(db, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (int(scope["output_id"]),),
        ).fetchone()
        if (
            row is None
            or str(row[1]) != str(scope["output_sha256"])
            or str(row[2]) != "candidate_snapshot_receipt_v1"
            or str(row[3]) != "succeeded"
        ):
            raise LiveSyncError("candidate_scope_required")
        receipt = json.loads(str(row[0]))
        if not isinstance(receipt, dict):
            raise LiveSyncError("candidate_scope_required")
        builder = (
            Path(__file__).resolve().parents[3]
            / "skills/_shared/scripts/build_m8_candidate.py"
        )
        raw_max_id = receipt.get("raw_max_id")
        if (
            receipt.get("schema_version") != "candidate_snapshot_receipt_v1"
            or receipt.get("candidate_source") != str(root)
            or receipt.get("formal_source") != str(runtime_source)
            or receipt.get("formal_fingerprint_sha256") != before.get("sha256")
            or receipt.get("builder_sha256") != sha256_file(builder)
            or isinstance(raw_max_id, bool)
            or not isinstance(raw_max_id, int)
            or raw_max_id < 0
        ):
            raise LiveSyncError("candidate_scope_required")
        _assert_formal_source_evidence(runtime_source, before, receipt)
        entries = _candidate_seed_entries(connection, root, raw_max_id)
        if (
            receipt.get("raw_count") != len(entries)
            or receipt.get("raw_bytes")
            != sum(int(item["byte_size"]) for item in entries)
            or receipt.get("raw_manifest_sha256")
            != sha256_text(canonical_json(entries))
            or max((int(item["id"]) for item in entries), default=0) != raw_max_id
        ):
            raise LiveSyncError("candidate_scope_required")
        expected_request = approved_request()
        expected_manifest = canonical_json(
            {
                "request_sha256": sha256_text(canonical_json(expected_request)),
                "request": expected_request,
            }
        )
        post_seed = connection.execute(
            "SELECT rf.id,sr.skill_name,sr.operation,sr.workflow_key,sr.input_manifest_json,"
            "sr.target_from_date,sr.target_through_date FROM raw_files rf "
            "JOIN skill_runs sr ON sr.id=rf.registered_by_run_id WHERE rf.id>? ORDER BY rf.id",
            (raw_max_id,),
        ).fetchall()
        post_seed_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM raw_files WHERE id>?", (raw_max_id,)
            ).fetchone()[0]
        )
        if len(post_seed) != post_seed_count or any(
            str(row[1]) != "garmin-sync"
            or str(row[2]) != "daily_sync"
            or str(row[3]) != WORKFLOW_KEY
            or str(row[4]) != expected_manifest
            or str(row[5]) != HEALTH_DATE
            or str(row[6]) != SLEEP_DATE
            for row in post_seed
        ):
            raise LiveSyncError("candidate_scope_required")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise LiveSyncError("candidate_scope_required") from exc
    finally:
        connection.close()


def _assert_candidate_scope(source_root: Path, database: Path) -> tuple[Path, Path]:
    root = Path(os.path.abspath(source_root))
    db = Path(os.path.abspath(database))
    expected = root / "state/trainlab.db"
    if db != expected:
        raise LiveSyncError("candidate_scope_required")
    marker = root.parent / "formal-state-fingerprint.json"
    try:
        directory_paths = (
            root.parent,
            root,
            root / "state",
            root / "state/raw",
            root / "state/raw/garmin",
            root / "state/raw/garmin/health",
            root / "state/raw/garmin/activities",
        )
        directory_metadata = [path.lstat() for path in directory_paths]
        db_metadata = db.lstat()
        metadata = marker.lstat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise LiveSyncError("candidate_scope_required") from exc
    if (
        root.resolve(strict=True) != root
        or db.resolve(strict=True) != db
        or any(path.resolve(strict=True) != path for path in directory_paths)
        or any(
            not stat.S_ISDIR(item.st_mode)
            or stat.S_ISLNK(item.st_mode)
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o700
            for item in directory_metadata
        )
        or not stat.S_ISREG(db_metadata.st_mode)
        or stat.S_ISLNK(db_metadata.st_mode)
        or db_metadata.st_uid != os.getuid()
        or db_metadata.st_nlink != 1
        or stat.S_IMODE(db_metadata.st_mode) != 0o600
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or payload.get("schema_version") != "m8_snapshot_receipt_v1"
        or payload.get("formal_state_unchanged") is not True
    ):
        raise LiveSyncError("candidate_scope_required")
    _assert_candidate_provenance(root, db, payload)
    return root, db


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, payload: bytes) -> None:
    if not payload:
        raise LiveSyncError("capture_empty")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = Path(os.path.abspath(path.parent))
    parent_metadata = parent.lstat()
    if (
        parent.resolve(strict=True) != parent
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_ISLNK(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        raise LiveSyncError("capture_path_conflict")
    if path.exists():
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or sha256_file(path) != sha256_bytes(payload)
        ):
            raise LiveSyncError("capture_path_conflict")
        return
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _activity_hash(provider_activity_id: str) -> str:
    return hashlib.sha256(f"garmin\0{provider_activity_id}".encode()).hexdigest()


def _insert_raw(
    connection: Any,
    *,
    run_id: int,
    provider: str,
    data_class: str,
    resource: str,
    logical_key: str,
    data_date: str,
    relative_path: str,
    file_format: str,
    byte_size: int,
    digest: str,
    inventory_id: int | None = None,
) -> int:
    existing = connection.execute(
        "SELECT id,sha256 FROM raw_files WHERE relative_path=?", (relative_path,)
    ).fetchone()
    if existing:
        if str(existing[1]) != digest:
            raise LiveSyncError("raw_path_conflict")
        return int(existing[0])
    previous = connection.execute(
        "SELECT id,revision_no FROM raw_files WHERE logical_key=? ORDER BY revision_no DESC LIMIT 1",
        (logical_key,),
    ).fetchone()
    revision = int(previous[1]) + 1 if previous else 1
    binding_state = (
        "bound"
        if inventory_id is not None
        else ("not_applicable" if data_class == "health" else "unresolved")
    )
    binding = None
    if inventory_id is not None:
        row = connection.execute(
            "SELECT provider,provider_activity_id,activity_hash,activity_hash_version "
            "FROM activity_inventory WHERE id=?",
            (inventory_id,),
        ).fetchone()
        if row is None:
            raise LiveSyncError("activity_binding_missing")
        binding = canonical_json(
            {
                "provider": str(row[0]),
                "provider_activity_id": str(row[1]),
                "activity_hash": str(row[2]),
                "hash_version": str(row[3]),
            }
        )
    cursor = connection.execute(
        """INSERT INTO raw_files
        (provider,data_class,resource_kind,logical_key,revision_no,supersedes_raw_file_id,
         activity_inventory_id,activity_binding_state,bound_by_run_id,binding_evidence_json,
         data_date,relative_path,file_format,byte_size,sha256,registered_by_run_id,
         integrity_state,captured_at_utc,registered_at_utc,last_verified_at_utc)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            provider,
            data_class,
            resource,
            logical_key,
            revision,
            int(previous[0]) if previous else None,
            inventory_id,
            binding_state,
            run_id if inventory_id is not None else None,
            binding,
            data_date,
            relative_path,
            file_format,
            byte_size,
            digest,
            run_id,
            "verified",
            utc_now(),
            utc_now(),
            utc_now(),
        ),
    )
    connection.commit()
    return require_lastrowid(cursor)


def _append_call(connection: Any, run_id: int, payload: dict[str, Any]) -> int:
    require_valid_payload(payload, "garmin_mcp_capture_v1")
    return append_output(
        connection,
        skill_run_id=run_id,
        output_kind="bounded_evidence",
        logical_key=f"garmin-live:2026-08-17:call:{payload['call_index']}",
        schema_name="garmin_mcp_capture_v1",
        schema_version="1",
        content_json=payload,
        content_text=canonical_json(payload),
        period_start_date=HEALTH_DATE,
        period_end_date=SLEEP_DATE,
    )


def _capture_path(source_root: Path, tool: str, digest: str) -> tuple[Path, str]:
    resource = RESOURCE_BY_TOOL[tool]
    day = SLEEP_DATE if tool == "get_sleep_data" else HEALTH_DATE
    folder = "health" if tool != "get_activities_by_date" else "activities"
    name = f"{day.replace('-', '')}-mcp_capture.{resource}-{digest}.json"
    relative = f"garmin/{folder}/{name}"
    return source_root / "state/raw" / relative, relative


def _decode_json(payload: bytes) -> Any | None:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _is_missing_text(payload: bytes) -> bool:
    text = payload.decode("utf-8", errors="replace").strip().lower()
    return text.startswith("no ") and (" found " in text or " returned " in text)


def _is_error_text(payload: bytes) -> bool:
    return (
        payload.decode("utf-8", errors="replace").strip().lower().startswith("error ")
    )


def inspect_fit(path: Path) -> FitInspection:
    try:
        import fitdecode

        messages = 0
        outdoor = False
        with fitdecode.FitReader(path) as reader:
            for frame in reader:
                messages += 1
                for field in getattr(frame, "fields", ()):
                    if str(getattr(field, "name", "")) in {
                        "position_lat",
                        "position_long",
                    }:
                        outdoor = True
        return FitInspection(messages > 0, outdoor)
    except Exception:
        return FitInspection(False, False)


def _prior_receipt(
    connection: Any, request_sha: str
) -> tuple[int, dict[str, Any]] | None:
    row = connection.execute(
        "SELECT so.id,so.content_json FROM skill_outputs so "
        "JOIN skill_runs sr ON sr.id=so.skill_run_id "
        "WHERE so.logical_key=? AND so.schema_name='garmin_live_sync_receipt_v1' "
        "AND sr.status='succeeded' "
        "ORDER BY so.revision_no DESC LIMIT 1",
        (SYNC_LOGICAL_KEY,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(str(row[1]))
    if payload.get("request_sha256") != request_sha:
        return None
    return int(row[0]), payload


def _reused_receipt(output_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["status"] = "reused"
    payload["provider_entries"] = 0
    payload["mcp_tool_calls"] = 0
    payload["receipt_output_id"] = output_id
    return payload


def _assert_receipt_raw_closure(
    connection: Any, source_root: Path, payload: dict[str, Any]
) -> None:
    raw_ids = payload.get("raw_file_ids")
    if (
        not isinstance(raw_ids, list)
        or any(
            isinstance(value, bool) or not isinstance(value, int) for value in raw_ids
        )
        or len(set(raw_ids)) != len(raw_ids)
    ):
        raise LiveSyncError("garmin_live_reuse_integrity_failed")
    if not raw_ids:
        return
    placeholders = ",".join("?" for _ in raw_ids)
    rows = connection.execute(
        "SELECT id,relative_path,byte_size,sha256 FROM raw_files "
        f"WHERE id IN ({placeholders}) AND integrity_state='verified' ORDER BY id",
        tuple(raw_ids),
    ).fetchall()
    if len(rows) != len(raw_ids):
        raise LiveSyncError("garmin_live_reuse_integrity_failed")
    raw_root = source_root / "state/raw"
    for row in rows:
        relative = Path(str(row[1]))
        if relative.is_absolute() or ".." in relative.parts:
            raise LiveSyncError("garmin_live_reuse_integrity_failed")
        path = Path(os.path.abspath(raw_root / relative))
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise LiveSyncError("garmin_live_reuse_integrity_failed") from exc
        if (
            path.resolve(strict=True) != path
            or not path.is_relative_to(raw_root)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != int(row[2])
            or sha256_file(path) != str(row[3])
        ):
            raise LiveSyncError("garmin_live_reuse_integrity_failed")


def _consumed_authorization(
    output_id: int | None,
    request_sha: str,
    *,
    error_code: str = "garmin_live_authorization_consumed",
) -> dict[str, Any]:
    result = {
        "schema_version": "garmin_live_sync_receipt_v1",
        "status": "blocked",
        "workflow_key": WORKFLOW_KEY,
        "timezone": "Asia/Hong_Kong",
        "run_date": "2026-08-17",
        "health_activity_date": HEALTH_DATE,
        "sleep_wake_date": SLEEP_DATE,
        "request_sha256": request_sha,
        "token_unchanged": True,
        "provider_entries": 0,
        "mcp_tool_calls": 0,
        "activity_ids": 0,
        "fit_files": 0,
        "weather_calls": 0,
        "new_files": 0,
        "inventory_complete": False,
        "inventory_count": 0,
        "call_output_ids": [],
        "raw_file_ids": [],
        "activity_inventory_ids": [],
        "external_actions": 0,
        "error_code": error_code,
    }
    if output_id is not None:
        result["receipt_output_id"] = output_id
    return result


def _client_instance(
    factory: Callable[..., Any], token_shadow: Path, download_dir: Path
) -> Any:
    parameters = inspect.signature(factory).parameters.values()
    supports_arguments = (
        any(item.kind is inspect.Parameter.VAR_POSITIONAL for item in parameters)
        or len(tuple(parameters)) >= 2
    )
    return factory(token_shadow, download_dir) if supports_arguments else factory()


async def collect(
    request: dict[str, Any],
    source_root: Path,
    database: Path,
    token_dir: Path,
    client_factory: Callable[..., Any],
) -> dict[str, Any]:
    start = monotonic()
    validate_request(request)
    source_root, database = _assert_candidate_scope(source_root, database)
    if monotonic() - start >= WALL_SECONDS:
        raise LiveSyncError("garmin_live_wall_budget_exceeded")
    request_sha = sha256_text(canonical_json(request))
    manifest = {"request_sha256": request_sha, "request": request}
    dedupe = sha256_text(canonical_json(manifest))

    result: dict[str, Any] = {
        "schema_version": "garmin_live_sync_receipt_v1",
        "status": "blocked",
        "workflow_key": WORKFLOW_KEY,
        "timezone": "Asia/Hong_Kong",
        "run_date": "2026-08-17",
        "health_activity_date": HEALTH_DATE,
        "sleep_wake_date": SLEEP_DATE,
        "request_sha256": request_sha,
        "token_unchanged": True,
        "provider_entries": 0,
        "mcp_tool_calls": 0,
        "activity_ids": 0,
        "fit_files": 0,
        "weather_calls": 0,
        "new_files": 0,
        "inventory_complete": False,
        "inventory_count": 0,
        "call_output_ids": [],
        "raw_file_ids": [],
        "activity_inventory_ids": [],
        "external_actions": 0,
    }

    with workflow_lock(database):
        connection = connect(database)
        prior = _prior_receipt(connection, request_sha)
        if prior is not None:
            output_id, payload = prior
            if payload.get("status") == "succeeded":
                try:
                    _assert_receipt_raw_closure(connection, source_root, payload)
                except LiveSyncError:
                    connection.close()
                    return _consumed_authorization(
                        output_id,
                        request_sha,
                        error_code="garmin_live_reuse_integrity_failed",
                    )
                connection.close()
                return _reused_receipt(output_id, payload)
            connection.close()
            return _consumed_authorization(output_id, request_sha)
        prior_run = connection.execute(
            "SELECT id FROM skill_runs WHERE dedupe_key=? ORDER BY attempt_no DESC LIMIT 1",
            (dedupe,),
        ).fetchone()
        if prior_run is not None:
            connection.close()
            return _consumed_authorization(None, request_sha)
        run_id = begin_run(
            connection,
            run_key=f"{dedupe}:attempt-1",
            workflow_key=WORKFLOW_KEY,
            dedupe_key=dedupe,
            skill_name="garmin-sync",
            operation="daily_sync",
            trigger_kind="manual",
            input_manifest=manifest,
            target_from_date=HEALTH_DATE,
            target_through_date=SLEEP_DATE,
        )
        token_before: str | None = None
        token_shadow: Path | None = None
        shadow_before: str | None = None
        staging: Path | None = None
        active_call: dict[str, Any] | None = None
        collection_succeeded = False
        try:
            token_shadow, token_before, shadow_before = _copy_token_shadow(token_dir)
            staging = Path(
                tempfile.mkdtemp(prefix=".m9-download-", dir=source_root / "state")
            )
            os.chmod(staging, 0o700)
            inventory: dict[str, Any] | None = None
            # Leave a fixed local-only reserve for token verification,
            # temporary-file cleanup and the immutable SQLite receipt.  The
            # public contract remains 90 seconds; Provider work is stopped
            # earlier so finalization is inside that same budget.
            remaining = COLLECTION_PHASE_SECONDS - (monotonic() - start)
            if remaining <= 0:
                raise LiveSyncError("garmin_live_wall_budget_exceeded")
            async with asyncio.timeout(remaining):
                # The fixed MCP guard performs exactly one profile Provider
                # request during __aenter__.  Account for it conservatively
                # before entering so an initialization failure cannot be
                # recorded as zero Provider entries.
                result["provider_entries"] = 1
                async with _client_instance(
                    client_factory, token_shadow, staging
                ) as client:
                    tools = await client.list_tools()
                    if tools != set(ALLOWED_TOOLS):
                        raise LiveSyncError("mcp_tool_allowlist_mismatch")
                    for call in BASE_CALLS:
                        tool = str(call["tool"])
                        arguments = dict(call["arguments"])
                        call_start = monotonic()
                        result["mcp_tool_calls"] += 1
                        result["provider_entries"] += 1
                        active_call = {
                            "tool": tool,
                            "arguments": arguments,
                            "started": call_start,
                            "response": None,
                        }
                        try:
                            response: ToolResponse = await client.call_tool(
                                tool, arguments
                            )
                            active_call["response"] = response.payload
                        except Exception as exc:
                            payload = {
                                "schema_version": "garmin_mcp_capture_v1",
                                "source_type": "mcp_capture",
                                "status": "failed",
                                "call_index": result["mcp_tool_calls"],
                                "tool": tool,
                                "arguments": arguments,
                                "duration_ms": min(
                                    90000, int((monotonic() - call_start) * 1000)
                                ),
                                "response_sha256": sha256_bytes(b""),
                                "response_bytes": 0,
                                "media_type": "text/plain",
                                "capture_relative_path": None,
                                "error_code": "garmin_mcp_call_failed",
                            }
                            result["call_output_ids"].append(
                                _append_call(connection, run_id, payload)
                            )
                            active_call = None
                            raise LiveSyncError("garmin_mcp_call_failed") from exc
                        if response.is_error:
                            raise LiveSyncError("garmin_mcp_call_failed")
                        response_sha = sha256_bytes(response.payload)
                        decoded = _decode_json(response.payload)
                        missing = decoded is None and _is_missing_text(response.payload)
                        if _is_error_text(response.payload) or (
                            isinstance(decoded, dict) and "error" in decoded
                        ):
                            raise LiveSyncError("garmin_mcp_call_failed")
                        if decoded is None and not missing:
                            raise LiveSyncError("garmin_mcp_response_invalid")
                        raw_id = None
                        relative = None
                        if decoded is not None:
                            path, relative = _capture_path(
                                source_root, tool, response_sha
                            )
                            _write_atomic(path, response.payload)
                            data_class = (
                                "activity"
                                if tool == "get_activities_by_date"
                                else "health"
                            )
                            raw_id = _insert_raw(
                                connection,
                                run_id=run_id,
                                provider="garmin_mcp",
                                data_class=data_class,
                                resource=RESOURCE_BY_TOOL[tool],
                                logical_key=f"garmin_mcp:{RESOURCE_BY_TOOL[tool]}:{SLEEP_DATE if tool == 'get_sleep_data' else HEALTH_DATE}",
                                data_date=SLEEP_DATE
                                if tool == "get_sleep_data"
                                else HEALTH_DATE,
                                relative_path=relative,
                                file_format="json",
                                byte_size=len(response.payload),
                                digest=response_sha,
                            )
                            result["raw_file_ids"].append(raw_id)
                            result["new_files"] += 1
                        capture = {
                            "schema_version": "garmin_mcp_capture_v1",
                            "source_type": "mcp_capture",
                            "status": "missing" if missing else "succeeded",
                            "call_index": result["mcp_tool_calls"],
                            "tool": tool,
                            "arguments": arguments,
                            "duration_ms": min(
                                90000, int((monotonic() - call_start) * 1000)
                            ),
                            "response_sha256": response_sha,
                            "response_bytes": len(response.payload),
                            "media_type": "application/json"
                            if decoded is not None
                            else "text/plain",
                            "capture_relative_path": relative,
                        }
                        if raw_id is not None:
                            capture["raw_file_id"] = raw_id
                        result["call_output_ids"].append(
                            _append_call(connection, run_id, capture)
                        )
                        active_call = None
                        if tool == "get_activities_by_date":
                            inventory = decoded if isinstance(decoded, dict) else None

                    if inventory is None:
                        raise LiveSyncError("activity_inventory_invalid")
                    activities = inventory.get("activities")
                    date_range = inventory.get("date_range")
                    if inventory.get("has_more") is not False:
                        raise LiveSyncError("activity_inventory_incomplete")
                    if not isinstance(date_range, dict) or date_range != {
                        "start": HEALTH_DATE,
                        "end": HEALTH_DATE,
                    }:
                        raise LiveSyncError("activity_inventory_date_mismatch")
                    if not isinstance(activities, list) or len(activities) > 10:
                        raise LiveSyncError("activity_budget_exceeded")
                    if inventory.get("page") != 0 or inventory.get("page_size") != 10:
                        raise LiveSyncError("activity_inventory_page_mismatch")
                    if int(inventory.get("count", -1)) != len(activities):
                        raise LiveSyncError("activity_inventory_count_mismatch")
                    result["activity_ids"] = len(activities)
                    result["inventory_count"] = len(activities)

                    validated_activities: list[tuple[int, str]] = []
                    seen_activity_ids: set[int] = set()
                    for item in activities:
                        if (
                            not isinstance(item, dict)
                            or item.get("id") is None
                            or isinstance(item.get("id"), bool)
                        ):
                            raise LiveSyncError("activity_inventory_invalid")
                        try:
                            activity_id = int(str(item["id"]))
                        except (TypeError, ValueError) as exc:
                            raise LiveSyncError("activity_inventory_invalid") from exc
                        if activity_id <= 0:
                            raise LiveSyncError("activity_inventory_invalid")
                        if activity_id in seen_activity_ids:
                            raise LiveSyncError("activity_inventory_duplicate")
                        seen_activity_ids.add(activity_id)
                        start_time = str(item.get("start_time", ""))
                        if start_time[:10] != HEALTH_DATE:
                            raise LiveSyncError("activity_inventory_date_mismatch")
                        validated_activities.append((activity_id, str(activity_id)))

                    missing_activities: list[tuple[int, str, int]] = []
                    for activity_id, provider_id in validated_activities:
                        activity_hash = _activity_hash(provider_id)
                        row = connection.execute(
                            "SELECT id,collection_state FROM activity_inventory WHERE provider='garmin' AND provider_activity_id=?",
                            (provider_id,),
                        ).fetchone()
                        if row is None:
                            cursor = connection.execute(
                                """INSERT INTO activity_inventory
                                (provider,provider_activity_id,activity_hash,activity_hash_version,activity_date,
                                 expected_formats_json,collection_state,weather_state,collection_policy_version,
                                 first_seen_at_utc,last_seen_at_utc,discovered_by_run_id,updated_at_utc)
                                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    "garmin",
                                    provider_id,
                                    activity_hash,
                                    "provider-nul-id-sha256-v1",
                                    HEALTH_DATE,
                                    canonical_json(["fit"]),
                                    "discovered",
                                    "not_requested",
                                    "m9-bounded-live-v1",
                                    utc_now(),
                                    utc_now(),
                                    run_id,
                                    utc_now(),
                                ),
                            )
                            inventory_id = require_lastrowid(cursor)
                            connection.commit()
                            missing_activities.append(
                                (activity_id, activity_hash, inventory_id)
                            )
                        else:
                            inventory_id = int(row[0])
                            connection.execute(
                                "UPDATE activity_inventory SET last_seen_at_utc=?,updated_at_utc=? WHERE id=?",
                                (utc_now(), utc_now(), inventory_id),
                            )
                            connection.commit()
                            fit = connection.execute(
                                "SELECT id,relative_path,byte_size,sha256 FROM raw_files "
                                "WHERE activity_inventory_id=? AND file_format='fit' "
                                "AND integrity_state='verified' ORDER BY revision_no DESC LIMIT 1",
                                (inventory_id,),
                            ).fetchone()
                            if fit is None:
                                missing_activities.append(
                                    (activity_id, activity_hash, inventory_id)
                                )
                            else:
                                fit_path = source_root / "state/raw" / str(fit[1])
                                fit_metadata = (
                                    fit_path.lstat() if fit_path.exists() else None
                                )
                                if (
                                    fit_metadata is None
                                    or fit_path.is_symlink()
                                    or not stat.S_ISREG(fit_metadata.st_mode)
                                    or fit_metadata.st_uid != os.getuid()
                                    or fit_metadata.st_nlink != 1
                                    or stat.S_IMODE(fit_metadata.st_mode) != 0o600
                                    or fit_metadata.st_size != int(fit[2])
                                    or sha256_file(fit_path) != str(fit[3])
                                ):
                                    raise LiveSyncError("existing_fit_invalid")
                                result["raw_file_ids"].append(int(fit[0]))
                        result["activity_inventory_ids"].append(inventory_id)
                    if len(missing_activities) > 2:
                        raise LiveSyncError("activity_budget_exceeded")

                    for activity_id, activity_hash, inventory_id in missing_activities:
                        arguments = {
                            "activity_id": activity_id,
                            "format": "fit",
                            "output_dir": str(staging.resolve()),
                        }
                        fit_start = monotonic()
                        result["mcp_tool_calls"] += 1
                        result["provider_entries"] += 1
                        active_call = {
                            "tool": "download_activity_file",
                            "arguments": arguments,
                            "started": fit_start,
                            "response": None,
                        }
                        response = await client.call_tool(
                            "download_activity_file", arguments
                        )
                        active_call["response"] = response.payload
                        if response.is_error or _is_error_text(response.payload):
                            raise LiveSyncError("garmin_mcp_call_failed")
                        metadata = _decode_json(response.payload)
                        expected = staging / f"{activity_id}.fit"
                        expected_metadata = (
                            expected.lstat() if expected.exists() else None
                        )
                        if (
                            not isinstance(metadata, dict)
                            or str(metadata.get("format")) != "fit"
                            or int(metadata.get("activity_id", -1)) != activity_id
                            or Path(str(metadata.get("file_path", ""))).resolve()
                            != expected.resolve()
                            or not expected.is_file()
                            or expected.is_symlink()
                            or expected_metadata is None
                            or not stat.S_ISREG(expected_metadata.st_mode)
                            or expected_metadata.st_uid != os.getuid()
                            or expected_metadata.st_nlink != 1
                            or expected_metadata.st_size <= 0
                        ):
                            raise LiveSyncError("fit_capture_invalid")
                        os.chmod(expected, 0o600)
                        inspection = inspect_fit(expected)
                        if not inspection.valid:
                            raise LiveSyncError("fit_capture_invalid")
                        fit_digest = sha256_file(expected)
                        fit_name = f"{HEALTH_DATE.replace('-', '')}-{activity_hash}.fit"
                        fit_relative = f"garmin/activities/{fit_name}"
                        fit_destination = source_root / "state/raw" / fit_relative
                        _write_atomic(fit_destination, expected.read_bytes())
                        fit_raw_id = _insert_raw(
                            connection,
                            run_id=run_id,
                            provider="garmin",
                            data_class="activity",
                            resource="activity_fit",
                            logical_key=f"garmin:activity:{activity_hash}:fit",
                            data_date=HEALTH_DATE,
                            relative_path=fit_relative,
                            file_format="fit",
                            byte_size=fit_destination.stat().st_size,
                            digest=fit_digest,
                            inventory_id=inventory_id,
                        )
                        result["raw_file_ids"].append(fit_raw_id)
                        result["new_files"] += 1
                        result["fit_files"] += 1
                        capture = {
                            "schema_version": "garmin_mcp_capture_v1",
                            "source_type": "mcp_capture",
                            "status": "succeeded",
                            "call_index": result["mcp_tool_calls"],
                            "tool": "download_activity_file",
                            "arguments": arguments,
                            "duration_ms": min(
                                90000,
                                int((monotonic() - fit_start) * 1000),
                            ),
                            "response_sha256": sha256_bytes(response.payload),
                            "response_bytes": len(response.payload),
                            "media_type": "application/json",
                            "capture_relative_path": fit_relative,
                            "raw_file_id": fit_raw_id,
                            "activity_inventory_id": inventory_id,
                        }
                        result["call_output_ids"].append(
                            _append_call(connection, run_id, capture)
                        )
                        active_call = None

                        weather_state = "not_available"
                        if inspection.outdoor:
                            weather_arguments = {"activity_id": activity_id}
                            weather_start = monotonic()
                            result["mcp_tool_calls"] += 1
                            result["provider_entries"] += 1
                            active_call = {
                                "tool": "get_activity_weather",
                                "arguments": weather_arguments,
                                "started": weather_start,
                                "response": None,
                            }
                            weather_response = await client.call_tool(
                                "get_activity_weather", weather_arguments
                            )
                            active_call["response"] = weather_response.payload
                            result["weather_calls"] += 1
                            weather_decoded = _decode_json(weather_response.payload)
                            weather_missing = (
                                weather_decoded is None
                                and _is_missing_text(weather_response.payload)
                            )
                            if (
                                weather_response.is_error
                                or _is_error_text(weather_response.payload)
                                or (weather_decoded is None and not weather_missing)
                            ):
                                raise LiveSyncError("garmin_mcp_call_failed")
                            weather_relative = None
                            weather_raw_id = None
                            if weather_decoded is not None:
                                weather_sha = sha256_bytes(weather_response.payload)
                                weather_name = f"{HEALTH_DATE.replace('-', '')}-{activity_hash}.mcp_capture.weather.json"
                                weather_relative = f"garmin/activities/{weather_name}"
                                weather_path = (
                                    source_root / "state/raw" / weather_relative
                                )
                                _write_atomic(weather_path, weather_response.payload)
                                weather_raw_id = _insert_raw(
                                    connection,
                                    run_id=run_id,
                                    provider="garmin_mcp",
                                    data_class="activity",
                                    resource="activity_weather",
                                    logical_key=f"garmin_mcp:activity:{activity_hash}:weather",
                                    data_date=HEALTH_DATE,
                                    relative_path=weather_relative,
                                    file_format="json",
                                    byte_size=len(weather_response.payload),
                                    digest=weather_sha,
                                    inventory_id=inventory_id,
                                )
                                result["raw_file_ids"].append(weather_raw_id)
                                result["new_files"] += 1
                                weather_state = "complete"
                            weather_capture = {
                                "schema_version": "garmin_mcp_capture_v1",
                                "source_type": "mcp_capture",
                                "status": "missing" if weather_missing else "succeeded",
                                "call_index": result["mcp_tool_calls"],
                                "tool": "get_activity_weather",
                                "arguments": weather_arguments,
                                "duration_ms": min(
                                    90000,
                                    int((monotonic() - weather_start) * 1000),
                                ),
                                "response_sha256": sha256_bytes(
                                    weather_response.payload
                                ),
                                "response_bytes": len(weather_response.payload),
                                "media_type": "application/json"
                                if weather_decoded is not None
                                else "text/plain",
                                "capture_relative_path": weather_relative,
                                "activity_inventory_id": inventory_id,
                            }
                            if weather_raw_id is not None:
                                weather_capture["raw_file_id"] = weather_raw_id
                            result["call_output_ids"].append(
                                _append_call(connection, run_id, weather_capture)
                            )
                            active_call = None
                        connection.execute(
                            "UPDATE activity_inventory SET collection_state='complete',weather_state=?,last_collection_at_utc=?,last_collection_run_id=?,updated_at_utc=? WHERE id=?",
                            (weather_state, utc_now(), run_id, utc_now(), inventory_id),
                        )
                        connection.commit()

            if monotonic() - start >= COLLECTION_PHASE_SECONDS:
                raise LiveSyncError("garmin_live_wall_budget_exceeded")
            result["inventory_complete"] = True
            collection_succeeded = True
        except TimeoutError:
            result["error_code"] = "garmin_live_wall_budget_exceeded"
        except LiveSyncError as exc:
            result["error_code"] = str(exc)
        except Exception:
            result["error_code"] = "garmin_mcp_session_failed"
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            if token_shadow is not None:
                try:
                    shadow_unchanged = (
                        shadow_before is not None
                        and _token_fingerprint(token_shadow) == shadow_before
                    )
                except LiveSyncError:
                    shadow_unchanged = False
                if not shadow_unchanged:
                    result["status"] = "blocked"
                    result["error_code"] = "cached_token_refresh_attempted"
                _remove_token_shadow(token_shadow)
            if token_before is not None:
                try:
                    result["token_unchanged"] = (
                        _token_fingerprint(token_dir) == token_before
                    )
                except LiveSyncError:
                    result["token_unchanged"] = False
                if not result["token_unchanged"]:
                    result["status"] = "blocked"
                    result["error_code"] = "cached_token_changed"

            if active_call is not None:
                raw_response = active_call.get("response")
                response_bytes = (
                    raw_response if isinstance(raw_response, bytes) else b""
                )
                failed_capture = {
                    "schema_version": "garmin_mcp_capture_v1",
                    "source_type": "mcp_capture",
                    "status": "failed",
                    "call_index": result["mcp_tool_calls"],
                    "tool": str(active_call["tool"]),
                    "arguments": dict(active_call["arguments"]),
                    "duration_ms": min(
                        90000,
                        int((monotonic() - float(active_call["started"])) * 1000),
                    ),
                    "response_sha256": sha256_bytes(response_bytes),
                    "response_bytes": len(response_bytes),
                    "media_type": "text/plain",
                    "capture_relative_path": None,
                    "error_code": str(
                        result.get("error_code", "garmin_mcp_call_failed")
                    ),
                }
                result["call_output_ids"].append(
                    _append_call(connection, run_id, failed_capture)
                )

            # Cleanup and token verification are part of the frozen 90-second
            # wall budget.  Never publish a successful receipt once the full
            # local finalization reserve has been consumed.
            if not _enforce_wall_deadline(
                result, start, limit=COLLECTION_PHASE_SECONDS
            ) and (collection_succeeded and "error_code" not in result):
                result["status"] = "succeeded"

            require_valid_payload(result, "garmin_live_sync_receipt_v1")
            lineage = [
                {
                    "output_id": output_id,
                    "output_sha256": str(
                        connection.execute(
                            "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                            (output_id,),
                        ).fetchone()[0]
                    ),
                }
                for output_id in result["call_output_ids"]
            ]

            def append_receipt() -> int:
                return append_output(
                    connection,
                    skill_run_id=run_id,
                    output_kind="sync_summary",
                    logical_key=SYNC_LOGICAL_KEY,
                    schema_name="garmin_live_sync_receipt_v1",
                    schema_version="1",
                    content_json=result,
                    content_text=canonical_json(result),
                    period_start_date=HEALTH_DATE,
                    period_end_date=SLEEP_DATE,
                    lineage=lineage,
                )

            receipt_id = append_receipt()
            if _enforce_wall_deadline(result, start):
                require_valid_payload(result, "garmin_live_sync_receipt_v1")
                receipt_id = append_receipt()
            final_status = "succeeded" if result["status"] == "succeeded" else "blocked"
            finish_run(
                connection,
                run_id,
                status=final_status,
                error_code=result.get("error_code"),
            )
            result["receipt_output_id"] = receipt_id
            connection.close()
    return result


def main() -> int:
    import argparse
    import importlib.util

    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--token-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    adapter_path = Path(__file__).resolve().parent / "mcp_stdio.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_live_mcp_stdio", adapter_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("mcp_stdio_module_unavailable")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    request = approved_request()
    try:
        result = asyncio.run(
            collect(
                request,
                args.source_root,
                args.database,
                args.token_dir,
                lambda shadow_tokens, download_dir: adapter.StdioGarminClient(
                    shadow_tokens,
                    download_dir,
                ),
            )
        )
    except (LiveSyncError, ValueError) as exc:
        result = _consumed_authorization(None, sha256_text(canonical_json(request)))
        result["error_code"] = str(exc)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"succeeded", "reused"} else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
