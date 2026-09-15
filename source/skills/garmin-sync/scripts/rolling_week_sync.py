#!/usr/bin/env python3
"""Bounded M10 Garmin MCP capture for one fixed rolling seven-day window."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
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

MCP_COMMIT = "3610be6feed93088d85b0f35aba9d7d07c2505a7"
WORKFLOW_KEY = "m10:rolling-week:2026-08-11/2026-08-18"
SYNC_LOGICAL_KEY = "garmin-live:m10:rolling-week:2026-08-11/2026-08-18"
REVIEW_START = date(2026, 8, 11)
REVIEW_END = date(2026, 8, 17)
SLEEP_START = date(2026, 8, 14)
SLEEP_END = date(2026, 8, 18)
REPORT_START = date(2026, 8, 12)
REPORT_END = date(2026, 8, 18)
WALL_SECONDS = 600.0
COLLECTION_SECONDS = 570.0
MAX_TOOL_CALLS = 46
MAX_PROVIDER_ENTRIES = 47
MAX_NEW_ACTIVITIES = 7
MAX_FIT = 7
MAX_WEATHER = 7
MAX_NEW_FILES = 46

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


class RollingSyncError(RuntimeError):
    """A stable fail-closed error for the approved M10 collection."""


def _load_m9() -> Any:
    path = Path(__file__).resolve().parent / "live_sync.py"
    spec = importlib.util.spec_from_file_location("trainlab_m9_live_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("m9_live_sync_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def _base_calls() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for current in _days(SLEEP_START, REVIEW_END):
        value = current.isoformat()
        calls.extend(
            [
                {"tool": "get_rhr_day", "arguments": {"date": value}},
                {
                    "tool": "get_hrv_data",
                    "arguments": {"date": value, "return_timeseries": False},
                },
                {"tool": "get_heart_rates", "arguments": {"date": value}},
                {
                    "tool": "get_vo2max_trend",
                    "arguments": {"start_date": value, "end_date": value},
                },
                {
                    "tool": "get_weigh_ins",
                    "arguments": {"start_date": value, "end_date": value},
                },
            ]
        )
    calls.extend(
        {
            "tool": "get_sleep_data",
            "arguments": {"date": current.isoformat()},
        }
        for current in _days(SLEEP_START, SLEEP_END)
    )
    calls.extend(
        {
            "tool": "get_activities_by_date",
            "arguments": {
                "start_date": current.isoformat(),
                "end_date": current.isoformat(),
                "page": 0,
                "page_size": 10,
            },
        }
        for current in _days(REVIEW_START, REVIEW_END)
    )
    return calls


def approved_request() -> dict[str, Any]:
    return {
        "schema_version": "garmin_rolling_week_request_v1",
        "timezone": "Asia/Hong_Kong",
        "review_start_date": REVIEW_START.isoformat(),
        "review_end_date": REVIEW_END.isoformat(),
        "sleep_start_date": SLEEP_START.isoformat(),
        "sleep_end_date": SLEEP_END.isoformat(),
        "mcp_commit": MCP_COMMIT,
        "base_calls": _base_calls(),
        "optional_tools": ["download_activity_file", "get_activity_weather"],
        "budgets": {
            "mcp_tool_calls": MAX_TOOL_CALLS,
            "provider_entries": MAX_PROVIDER_ENTRIES,
            "inventory_ids_per_day": 10,
            "new_activities": MAX_NEW_ACTIVITIES,
            "fit_files": MAX_FIT,
            "weather_calls": MAX_WEATHER,
            "new_files": MAX_NEW_FILES,
            "wall_seconds": int(WALL_SECONDS),
        },
        "cached_tokens_only": True,
        "retries": 0,
    }


def validate_request(request: dict[str, Any]) -> None:
    try:
        require_valid_payload(request, "garmin_rolling_week_request_v1")
    except ValueError as exc:
        raise RollingSyncError("garmin_rolling_request_invalid") from exc
    if canonical_json(request) != canonical_json(approved_request()):
        raise RollingSyncError("garmin_rolling_request_invalid")


def _call_date(tool: str, arguments: dict[str, Any]) -> str:
    if tool in {"get_vo2max_trend", "get_weigh_ins", "get_activities_by_date"}:
        start = str(arguments.get("start_date", ""))
        end = str(arguments.get("end_date", ""))
        if start != end:
            raise RollingSyncError("garmin_rolling_date_mismatch")
        return start
    return str(arguments.get("date", ""))


def validate_inventory(payload: Any, expected_date: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RollingSyncError("activity_inventory_invalid")
    activities = payload.get("activities")
    if (
        payload.get("has_more") is not False
        or payload.get("page") != 0
        or payload.get("page_size") != 10
        or payload.get("date_range") != {"start": expected_date, "end": expected_date}
        or not isinstance(activities, list)
        or len(activities) > 10
        or payload.get("count") != len(activities)
    ):
        raise RollingSyncError("activity_inventory_incomplete")
    seen: set[int] = set()
    result: list[dict[str, Any]] = []
    for item in activities:
        if not isinstance(item, dict) or isinstance(item.get("id"), bool):
            raise RollingSyncError("activity_inventory_invalid")
        try:
            activity_id = int(str(item["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RollingSyncError("activity_inventory_invalid") from exc
        if activity_id <= 0 or activity_id in seen:
            raise RollingSyncError("activity_inventory_duplicate")
        if str(item.get("start_time", ""))[:10] != expected_date:
            raise RollingSyncError("activity_inventory_date_mismatch")
        seen.add(activity_id)
        result.append({**item, "id": activity_id})
    return result


def _capture_path(root: Path, tool: str, day: str, digest: str) -> tuple[Path, str]:
    folder = "activities" if tool == "get_activities_by_date" else "health"
    resource = RESOURCE_BY_TOOL[tool]
    name = f"{day.replace('-', '')}-mcp_capture.{resource}-{digest}.json"
    relative = f"garmin/{folder}/{name}"
    return root / "state/raw" / relative, relative


def _append_call(connection: Any, run_id: int, payload: dict[str, Any]) -> int:
    require_valid_payload(payload, "garmin_mcp_capture_v2")
    return append_output(
        connection,
        skill_run_id=run_id,
        output_kind="bounded_evidence",
        logical_key=f"garmin-live:m10:call:{payload['call_index']}",
        schema_name="garmin_mcp_capture_v2",
        schema_version="2",
        content_json=payload,
        content_text=canonical_json(payload),
        period_start_date=REVIEW_START.isoformat(),
        period_end_date=SLEEP_END.isoformat(),
    )


def _latest_raw_ids(connection: Any, resource: str, data_date: str) -> list[int]:
    rows = connection.execute(
        "SELECT id FROM raw_files WHERE resource_kind=? AND data_date=? "
        "AND integrity_state='verified' ORDER BY revision_no DESC,id DESC",
        (resource, data_date),
    ).fetchall()
    return [int(row[0]) for row in rows[:1]]


def _daily_windows(
    connection: Any,
    inventory_by_date: dict[str, int],
    inventory_ids_by_date: dict[str, list[int]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for report_day in _days(REPORT_START, REPORT_END):
        review_day = report_day - timedelta(days=1)
        review = review_day.isoformat()
        report = report_day.isoformat()
        raw_ids: set[int] = set()
        for resource in ("rhr", "hrv", "heart_rates", "max_metrics", "weigh_ins"):
            raw_ids.update(_latest_raw_ids(connection, resource, review))
        raw_ids.update(_latest_raw_ids(connection, "sleep", report))
        activity_ids = sorted(set(inventory_ids_by_date.get(review, [])))
        if activity_ids:
            placeholders = ",".join("?" for _ in activity_ids)
            rows = connection.execute(
                f"SELECT id FROM raw_files WHERE activity_inventory_id IN ({placeholders}) "
                "AND integrity_state='verified' AND resource_kind<>'activity_inventory'",
                tuple(activity_ids),
            ).fetchall()
            raw_ids.update(int(row[0]) for row in rows)
        raw_ids.update(_latest_raw_ids(connection, "activity_inventory", review))
        result[report] = {
            "report_date": report,
            "review_date": review,
            "inventory_complete": review in inventory_by_date,
            "inventory_count": int(inventory_by_date.get(review, -1)),
            "raw_file_ids": sorted(raw_ids),
            "activity_inventory_ids": activity_ids,
        }
    return result


def _receipt_closure(connection: Any, root: Path, receipt: dict[str, Any]) -> None:
    raw_root = root / "state/raw"
    for raw_id in receipt.get("raw_file_ids", []):
        row = connection.execute(
            "SELECT relative_path,byte_size,sha256 FROM raw_files WHERE id=?", (raw_id,)
        ).fetchone()
        if row is None:
            raise RollingSyncError("garmin_rolling_reuse_integrity_failed")
        path = raw_root / str(row[0])
        metadata = path.lstat() if path.exists() else None
        if (
            metadata is None
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != int(row[1])
            or sha256_file(path) != str(row[2])
        ):
            raise RollingSyncError("garmin_rolling_reuse_integrity_failed")


def _prior_receipt(
    connection: Any, request_sha: str
) -> tuple[int, dict[str, Any]] | None:
    row = connection.execute(
        "SELECT so.id,so.content_json FROM skill_outputs so JOIN skill_runs sr "
        "ON sr.id=so.skill_run_id WHERE so.logical_key=? "
        "AND so.schema_name='garmin_rolling_week_receipt_v1' AND sr.status='succeeded' "
        "ORDER BY so.revision_no DESC LIMIT 1",
        (SYNC_LOGICAL_KEY,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(str(row[1]))
    if payload.get("request_sha256") != request_sha:
        return None
    return int(row[0]), payload


def _assert_candidate_for_reuse(root: Path, database: Path) -> tuple[Path, Path]:
    """Verify the sealed base and formal fingerprint without reclassifying M10 rows."""
    live = _load_m9()
    absolute_root = Path(os.path.abspath(root))
    absolute_db = Path(os.path.abspath(database))
    runtime_source = Path(__file__).resolve().parents[3]
    repository_root = runtime_source.parent
    marker = absolute_root.parent / "formal-state-fingerprint.json"
    try:
        root_metadata = absolute_root.lstat()
        db_metadata = absolute_db.lstat()
        if (
            absolute_root == runtime_source
            or absolute_root.is_relative_to(runtime_source)
            or absolute_root == repository_root
            or absolute_root.is_relative_to(repository_root)
            or absolute_root.is_symlink()
            or not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.getuid()
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
            or absolute_db != absolute_root / "state/trainlab.db"
            or absolute_db.is_symlink()
            or not stat.S_ISREG(db_metadata.st_mode)
            or db_metadata.st_uid != os.getuid()
            or db_metadata.st_nlink != 1
            or stat.S_IMODE(db_metadata.st_mode) != 0o600
        ):
            raise RollingSyncError("candidate_scope_required")
        marker_payload = json.loads(marker.read_text(encoding="utf-8"))
        before = marker_payload["before"]
        scope = marker_payload["candidate_scope"]
        connection = connect(absolute_db, read_only=True, immutable=True)
        try:
            row = connection.execute(
                "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
                (int(scope["output_id"]),),
            ).fetchone()
        finally:
            connection.close()
        if row is None or str(row[1]) != str(scope["output_sha256"]):
            raise RollingSyncError("candidate_scope_required")
        seed = json.loads(str(row[0]))
        if seed.get("candidate_source") != str(absolute_root):
            raise RollingSyncError("candidate_scope_required")
        live._assert_formal_source_evidence(runtime_source, before, seed)
    except Exception as exc:
        raise RollingSyncError("candidate_scope_required") from exc
    return absolute_root, absolute_db


async def collect(
    request: dict[str, Any],
    source_root: Path,
    database: Path,
    token_dir: Path,
    client_factory: Callable[..., Any],
    *,
    candidate_guard: Callable[[Path, Path], tuple[Path, Path]] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    validate_request(request)
    request_sha = sha256_text(canonical_json(request))
    manifest = {"request_sha256": request_sha, "request": request}
    dedupe = sha256_text(canonical_json(manifest))

    guard = candidate_guard
    if guard is None:
        connection = connect(database, read_only=True, immutable=True)
        try:
            prior = _prior_receipt(connection, request_sha)
        finally:
            connection.close()
        guard = (
            _assert_candidate_for_reuse
            if prior is not None
            else _load_m9()._assert_candidate_scope
        )
    try:
        source_root, database = guard(source_root, database)
    except Exception as exc:
        raise RollingSyncError("candidate_scope_required") from exc

    result: dict[str, Any] = {
        "schema_version": "garmin_rolling_week_receipt_v1",
        "status": "blocked",
        "workflow_key": WORKFLOW_KEY,
        "timezone": "Asia/Hong_Kong",
        "request_sha256": request_sha,
        "token_unchanged": True,
        "provider_entries": 0,
        "mcp_tool_calls": 0,
        "fit_files": 0,
        "weather_calls": 0,
        "new_files": 0,
        "inventory_by_date": {},
        "daily_windows": {},
        "call_output_ids": [],
        "raw_file_ids": [],
        "activity_inventory_ids": [],
        "external_actions": 0,
    }

    live = _load_m9()
    with workflow_lock(database):
        connection = connect(database)
        prior = _prior_receipt(connection, request_sha)
        if prior is not None:
            output_id, payload = prior
            try:
                _receipt_closure(connection, source_root, payload)
            except RollingSyncError:
                connection.close()
                return {**result, "error_code": "garmin_rolling_reuse_integrity_failed"}
            connection.close()
            reused = dict(payload)
            reused["provider_entries"] = 0
            reused["mcp_tool_calls"] = 0
            reused["receipt_output_id"] = output_id
            return reused

        run_id = begin_run(
            connection,
            run_key=f"{dedupe}:attempt-1",
            workflow_key=WORKFLOW_KEY,
            dedupe_key=dedupe,
            skill_name="garmin-sync",
            operation="manual_backfill",
            trigger_kind="manual",
            input_manifest=manifest,
            target_from_date=REVIEW_START.isoformat(),
            target_through_date=SLEEP_END.isoformat(),
        )
        token_shadow: Path | None = None
        token_before: str | None = None
        shadow_before: str | None = None
        staging: Path | None = None
        inventory_ids_by_date: dict[str, list[int]] = {}
        try:
            token_shadow, token_before, shadow_before = live._copy_token_shadow(
                token_dir
            )
            staging = Path(
                tempfile.mkdtemp(prefix=".m10-download-", dir=source_root / "state")
            )
            os.chmod(staging, 0o700)
            remaining = COLLECTION_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise RollingSyncError("garmin_rolling_wall_budget_exceeded")
            async with asyncio.timeout(remaining):
                result["provider_entries"] = 1
                async with client_factory(token_shadow, staging) as client:
                    if await client.list_tools() != ALLOWED_TOOLS:
                        raise RollingSyncError("mcp_tool_allowlist_mismatch")
                    inventories: dict[str, list[dict[str, Any]]] = {}
                    for call in request["base_calls"]:
                        tool = str(call["tool"])
                        arguments = dict(call["arguments"])
                        day = _call_date(tool, arguments)
                        call_started = time.monotonic()
                        result["mcp_tool_calls"] += 1
                        result["provider_entries"] += 1
                        if (
                            result["mcp_tool_calls"] > MAX_TOOL_CALLS
                            or result["provider_entries"] > MAX_PROVIDER_ENTRIES
                        ):
                            raise RollingSyncError("garmin_rolling_budget_exceeded")
                        response = await client.call_tool(tool, arguments)
                        if response.is_error or live._is_error_text(response.payload):
                            raise RollingSyncError("garmin_mcp_call_failed")
                        decoded = live._decode_json(response.payload)
                        missing = decoded is None and live._is_missing_text(
                            response.payload
                        )
                        if decoded is None and not missing:
                            raise RollingSyncError("garmin_mcp_response_invalid")
                        relative = None
                        raw_id = None
                        if decoded is not None:
                            digest = sha256_bytes(response.payload)
                            path, relative = _capture_path(
                                source_root, tool, day, digest
                            )
                            live._write_atomic(path, response.payload)
                            data_class = (
                                "activity"
                                if tool == "get_activities_by_date"
                                else "health"
                            )
                            raw_id = live._insert_raw(
                                connection,
                                run_id=run_id,
                                provider="garmin_mcp",
                                data_class=data_class,
                                resource=RESOURCE_BY_TOOL[tool],
                                logical_key=f"garmin_mcp:{RESOURCE_BY_TOOL[tool]}:{day}",
                                data_date=day,
                                relative_path=relative,
                                file_format="json",
                                byte_size=len(response.payload),
                                digest=digest,
                            )
                            result["raw_file_ids"].append(raw_id)
                            result["new_files"] += 1
                        capture = {
                            "schema_version": "garmin_mcp_capture_v2",
                            "source_type": "mcp_capture",
                            "status": "missing" if missing else "succeeded",
                            "call_index": result["mcp_tool_calls"],
                            "tool": tool,
                            "arguments": arguments,
                            "duration_ms": min(
                                600000, int((time.monotonic() - call_started) * 1000)
                            ),
                            "response_sha256": sha256_bytes(response.payload),
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
                        if tool == "get_activities_by_date":
                            activities = validate_inventory(decoded, day)
                            inventories[day] = activities
                            result["inventory_by_date"][day] = len(activities)

                    missing_activities: list[tuple[int, str, int, str]] = []
                    for day, activities in inventories.items():
                        inventory_ids_by_date[day] = []
                        for item in activities:
                            activity_id = int(item["id"])
                            provider_id = str(activity_id)
                            activity_hash = live._activity_hash(provider_id)
                            row = connection.execute(
                                "SELECT id FROM activity_inventory WHERE provider='garmin' AND provider_activity_id=?",
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
                                        day,
                                        canonical_json(["fit"]),
                                        "discovered",
                                        "not_requested",
                                        "m10-rolling-week-v1",
                                        utc_now(),
                                        utc_now(),
                                        run_id,
                                        utc_now(),
                                    ),
                                )
                                inventory_id = require_lastrowid(cursor)
                                connection.commit()
                            else:
                                inventory_id = int(row[0])
                                connection.execute(
                                    "UPDATE activity_inventory SET last_seen_at_utc=?,updated_at_utc=? WHERE id=?",
                                    (utc_now(), utc_now(), inventory_id),
                                )
                                connection.commit()
                            inventory_ids_by_date[day].append(inventory_id)
                            result["activity_inventory_ids"].append(inventory_id)
                            fit = connection.execute(
                                "SELECT id,relative_path,byte_size,sha256 FROM raw_files "
                                "WHERE activity_inventory_id=? AND file_format='fit' "
                                "AND integrity_state='verified' ORDER BY revision_no DESC LIMIT 1",
                                (inventory_id,),
                            ).fetchone()
                            if fit is None:
                                missing_activities.append(
                                    (activity_id, activity_hash, inventory_id, day)
                                )
                            else:
                                fit_path = source_root / "state/raw" / str(fit[1])
                                if not fit_path.is_file() or sha256_file(
                                    fit_path
                                ) != str(fit[3]):
                                    raise RollingSyncError("existing_fit_invalid")
                                result["raw_file_ids"].append(int(fit[0]))
                    if len(missing_activities) > MAX_NEW_ACTIVITIES:
                        raise RollingSyncError("activity_budget_exceeded")

                    for (
                        activity_id,
                        activity_hash,
                        inventory_id,
                        day,
                    ) in missing_activities:
                        arguments = {
                            "activity_id": activity_id,
                            "format": "fit",
                            "output_dir": str(staging.resolve()),
                        }
                        call_started = time.monotonic()
                        result["mcp_tool_calls"] += 1
                        result["provider_entries"] += 1
                        if (
                            result["mcp_tool_calls"] > MAX_TOOL_CALLS
                            or result["provider_entries"] > MAX_PROVIDER_ENTRIES
                        ):
                            raise RollingSyncError("garmin_rolling_budget_exceeded")
                        response = await client.call_tool(
                            "download_activity_file", arguments
                        )
                        metadata = live._decode_json(response.payload)
                        expected = staging / f"{activity_id}.fit"
                        if (
                            response.is_error
                            or not isinstance(metadata, dict)
                            or not expected.is_file()
                        ):
                            raise RollingSyncError("fit_capture_invalid")
                        if (
                            Path(str(metadata.get("file_path", ""))).resolve()
                            != expected.resolve()
                        ):
                            raise RollingSyncError("fit_capture_invalid")
                        inspection = live.inspect_fit(expected)
                        if not inspection.valid:
                            raise RollingSyncError("fit_capture_invalid")
                        fit_digest = sha256_file(expected)
                        fit_relative = f"garmin/activities/{day.replace('-', '')}-{activity_hash}.fit"
                        destination = source_root / "state/raw" / fit_relative
                        live._write_atomic(destination, expected.read_bytes())
                        fit_raw_id = live._insert_raw(
                            connection,
                            run_id=run_id,
                            provider="garmin",
                            data_class="activity",
                            resource="activity_fit",
                            logical_key=f"garmin:activity:{activity_hash}:fit",
                            data_date=day,
                            relative_path=fit_relative,
                            file_format="fit",
                            byte_size=destination.stat().st_size,
                            digest=fit_digest,
                            inventory_id=inventory_id,
                        )
                        result["fit_files"] += 1
                        result["new_files"] += 1
                        result["raw_file_ids"].append(fit_raw_id)
                        result["call_output_ids"].append(
                            _append_call(
                                connection,
                                run_id,
                                {
                                    "schema_version": "garmin_mcp_capture_v2",
                                    "source_type": "mcp_capture",
                                    "status": "succeeded",
                                    "call_index": result["mcp_tool_calls"],
                                    "tool": "download_activity_file",
                                    "arguments": arguments,
                                    "duration_ms": min(
                                        600000,
                                        int((time.monotonic() - call_started) * 1000),
                                    ),
                                    "response_sha256": sha256_bytes(response.payload),
                                    "response_bytes": len(response.payload),
                                    "media_type": "application/json",
                                    "capture_relative_path": fit_relative,
                                    "raw_file_id": fit_raw_id,
                                    "activity_inventory_id": inventory_id,
                                },
                            )
                        )
                        weather_state = "not_available"
                        if inspection.outdoor:
                            result["mcp_tool_calls"] += 1
                            result["provider_entries"] += 1
                            result["weather_calls"] += 1
                            if (
                                result["weather_calls"] > MAX_WEATHER
                                or result["provider_entries"] > MAX_PROVIDER_ENTRIES
                            ):
                                raise RollingSyncError("garmin_rolling_budget_exceeded")
                            weather_arguments = {"activity_id": activity_id}
                            weather_started = time.monotonic()
                            weather_response = await client.call_tool(
                                "get_activity_weather", weather_arguments
                            )
                            weather = live._decode_json(weather_response.payload)
                            weather_missing = weather is None and live._is_missing_text(
                                weather_response.payload
                            )
                            if weather_response.is_error or (
                                weather is None and not weather_missing
                            ):
                                raise RollingSyncError("garmin_mcp_call_failed")
                            weather_relative = None
                            weather_raw_id = None
                            if weather is not None:
                                weather_digest = sha256_bytes(weather_response.payload)
                                weather_relative = f"garmin/activities/{day.replace('-', '')}-{activity_hash}.mcp_capture.weather.json"
                                weather_path = (
                                    source_root / "state/raw" / weather_relative
                                )
                                live._write_atomic(
                                    weather_path, weather_response.payload
                                )
                                weather_raw_id = live._insert_raw(
                                    connection,
                                    run_id=run_id,
                                    provider="garmin_mcp",
                                    data_class="activity",
                                    resource="activity_weather",
                                    logical_key=f"garmin_mcp:activity:{activity_hash}:weather",
                                    data_date=day,
                                    relative_path=weather_relative,
                                    file_format="json",
                                    byte_size=len(weather_response.payload),
                                    digest=weather_digest,
                                    inventory_id=inventory_id,
                                )
                                result["raw_file_ids"].append(weather_raw_id)
                                result["new_files"] += 1
                                weather_state = "complete"
                            weather_capture = {
                                "schema_version": "garmin_mcp_capture_v2",
                                "source_type": "mcp_capture",
                                "status": "missing" if weather_missing else "succeeded",
                                "call_index": result["mcp_tool_calls"],
                                "tool": "get_activity_weather",
                                "arguments": weather_arguments,
                                "duration_ms": min(
                                    600000,
                                    int((time.monotonic() - weather_started) * 1000),
                                ),
                                "response_sha256": sha256_bytes(
                                    weather_response.payload
                                ),
                                "response_bytes": len(weather_response.payload),
                                "media_type": "application/json"
                                if weather is not None
                                else "text/plain",
                                "capture_relative_path": weather_relative,
                                "activity_inventory_id": inventory_id,
                            }
                            if weather_raw_id is not None:
                                weather_capture["raw_file_id"] = weather_raw_id
                            result["call_output_ids"].append(
                                _append_call(connection, run_id, weather_capture)
                            )
                        connection.execute(
                            "UPDATE activity_inventory SET collection_state='complete',weather_state=?,last_collection_at_utc=?,last_collection_run_id=?,updated_at_utc=? WHERE id=?",
                            (weather_state, utc_now(), run_id, utc_now(), inventory_id),
                        )
                        connection.commit()

            if time.monotonic() - started >= COLLECTION_SECONDS:
                raise RollingSyncError("garmin_rolling_wall_budget_exceeded")
            result["daily_windows"] = _daily_windows(
                connection, result["inventory_by_date"], inventory_ids_by_date
            )
            if any(
                not item["inventory_complete"]
                for item in result["daily_windows"].values()
            ):
                raise RollingSyncError("activity_inventory_incomplete")
            result["raw_file_ids"] = sorted(
                set(result["raw_file_ids"])
                | {
                    raw_id
                    for item in result["daily_windows"].values()
                    for raw_id in item["raw_file_ids"]
                }
            )
            result["activity_inventory_ids"] = sorted(
                set(result["activity_inventory_ids"])
            )
            if result["new_files"] > MAX_NEW_FILES or result["fit_files"] > MAX_FIT:
                raise RollingSyncError("garmin_rolling_budget_exceeded")
            result["status"] = "succeeded"
        except TimeoutError:
            result["error_code"] = "garmin_rolling_wall_budget_exceeded"
        except RollingSyncError as exc:
            result["error_code"] = str(exc)
        except Exception:
            result["error_code"] = "garmin_rolling_session_failed"
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            if token_shadow is not None:
                try:
                    if (
                        shadow_before is None
                        or live._token_fingerprint(token_shadow) != shadow_before
                    ):
                        result["status"] = "blocked"
                        result["error_code"] = "cached_token_refresh_attempted"
                except Exception:
                    result["status"] = "blocked"
                    result["error_code"] = "cached_token_refresh_attempted"
                live._remove_token_shadow(token_shadow)
            if token_before is not None:
                try:
                    result["token_unchanged"] = (
                        live._token_fingerprint(token_dir) == token_before
                    )
                except Exception:
                    result["token_unchanged"] = False
                if not result["token_unchanged"]:
                    result["status"] = "blocked"
                    result["error_code"] = "cached_token_changed"
            if time.monotonic() - started >= WALL_SECONDS:
                result["status"] = "blocked"
                result["error_code"] = "garmin_rolling_wall_budget_exceeded"
            require_valid_payload(result, "garmin_rolling_week_receipt_v1")
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
            receipt_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="sync_summary",
                logical_key=SYNC_LOGICAL_KEY,
                schema_name="garmin_rolling_week_receipt_v1",
                schema_version="1",
                content_json=result,
                content_text=canonical_json(result),
                period_start_date=REVIEW_START.isoformat(),
                period_end_date=SLEEP_END.isoformat(),
                lineage=lineage,
            )
            finish_run(
                connection,
                run_id,
                status="succeeded" if result["status"] == "succeeded" else "blocked",
                error_code=result.get("error_code"),
            )
            result["receipt_output_id"] = receipt_id
            connection.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--token-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    adapter_path = Path(__file__).resolve().parent / "mcp_stdio.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_m10_mcp_stdio", adapter_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("mcp_stdio_module_unavailable")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    result = asyncio.run(
        collect(
            approved_request(),
            args.source_root,
            args.database,
            args.token_dir,
            lambda shadow, staging: adapter.StdioGarminClient(shadow, staging),
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
