"""One-shot L2-18 runner confined to a disposable E-04 shadow clone."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, cast

import yaml
from jsonschema import Draft202012Validator

from .foundation import FoundationConfig, FoundationRequest, FoundationTool
from .resources import resource_bytes

_INV = re.compile(r"^inv-[0-9a-f]{32}$")
_AUTH = re.compile(r"^authz-[0-9a-f]{32}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RUN = re.compile(r"^gr-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EXIT = {
    "succeeded": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "auth_required": 20,
    "failed": 21,
}
_MODES = (
    "auth",
    "incremental",
    "incremental",
    "snapshot",
    "snapshot",
    "repair",
    "audit",
    "status",
)
_TIMEOUTS = {
    "auth": 300,
    "status": 300,
    "incremental": 3600,
    "snapshot": 3600,
    "repair": 1800,
    "audit": 1800,
}
SMOKE_RUNTIME_ERROR_CODES = frozenset(
    {
        "approved_window_invalid",
        "change_breakdown_identity_invalid",
        "change_breakdown_unsafe",
        "child_execution_failed",
        "child_timeout",
        "clock_invalid",
        "failure_breakdown_run_missing",
        "failure_breakdown_unsafe",
        "foundation_shadow_not_ready",
        "input_changed",
        "input_missing",
        "invocation_ids_invalid",
        "operation_not_succeeded",
        "published_sensitive_path",
        "published_token_copy",
        "receipt_exit_invalid",
        "receipt_identity_invalid",
        "receipt_invalid",
        "receipt_not_single_line",
        "receipt_run_id_duplicate",
        "receipt_schema_invalid",
        "receipt_sensitive",
        "receipt_window_invalid",
        "repeat_not_no_op",
        "request_schema_invalid",
        "smoke_authorization_incomplete",
        "smoke_config_invalid",
        "smoke_result_exists",
        "snapshot_coverage_invalid",
        "snapshot_cursor_advanced",
        "token_cleanup_failed",
        "token_replaced",
        "unsafe_path",
        "unsafe_token_store",
        "workspace_cleanup_failed",
    }
)


class SmokeRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class SmokeRuntimeRequest:
    isolated_root: Path
    production_token_store: Path
    approved_from: str
    approved_through: str
    invocation_ids: tuple[str, ...]
    production_garmin_config: Path
    authorization_id: str
    approved_modes: tuple[str, ...]
    bounded_activity_window_authorized: bool
    e04_backup_receipt_sha256: str
    operator_registered: bool
    shadow_attested: bool
    canonical_owner_unchanged: bool
    timeout_override_seconds: int | None = None


def _fail(code: str) -> None:
    raise SmokeRuntimeError(code)


def _hash(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _semantic_request_hash(value: dict[str, Any]) -> str:
    """Stable request identity: invocation is delivery metadata, not semantics."""
    material = dict(value)
    material["invocation_id"] = None
    return _hash(material)


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, str]]:
    result: dict[str, tuple[int, int, int, int, str]] = {}
    if not root.exists():
        _fail("input_missing")
    for item in [root, *sorted(root.rglob("*"))]:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            _fail("unsafe_path")
        digest = (
            sha256(item.read_bytes()).hexdigest() if stat.S_ISREG(info.st_mode) else ""
        )
        result[str(item.relative_to(root))] = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            digest,
        )
    return result


def _cursor_hash(db: Path) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = [
            tuple(row)
            for row in conn.execute(
                "SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors ORDER BY resource_kind"
            )
        ]
    finally:
        conn.close()
    return _hash(rows)


def _failure_breakdown(db: Path, provider_run_id: str | None) -> dict[str, object]:
    """Return bounded provider-safe aggregates, never object keys or payloads."""
    if provider_run_id is None:
        return {
            "gap_breakdown": [],
            "failed_item_breakdown": [],
            "breakdown_truncated": False,
        }
    if not _RUN.fullmatch(provider_run_id):
        _fail("failure_breakdown_unsafe")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        run = conn.execute(
            "SELECT id FROM garmin_sync_runs WHERE run_id=?",
            (provider_run_id,),
        ).fetchone()
        if run is None:
            _fail("failure_breakdown_run_missing")
        run_pk = int(run[0])
        gap_rows = list(
            conn.execute(
                """SELECT resource_kind,reason_code,status,count(*)
               FROM garmin_sync_gaps AS gap
               WHERE status IN ('open','deferred')
                 AND EXISTS (
                   SELECT 1 FROM garmin_sync_items AS item
                   WHERE item.garmin_sync_run_id=?
                     AND item.resource_kind=gap.resource_kind
                     AND item.logical_object_key=gap.logical_object_key
                     AND item.status IN ('failed','deferred')
                 )
               GROUP BY resource_kind,reason_code,status
               ORDER BY resource_kind,reason_code,status
               LIMIT 50""",
                (run_pk,),
            )
        )
        item_rows = list(
            conn.execute(
                """SELECT resource_kind,coalesce(error_code,'unknown'),count(*)
               FROM garmin_sync_items
               WHERE garmin_sync_run_id=? AND status='failed'
               GROUP BY resource_kind,coalesce(error_code,'unknown')
               ORDER BY resource_kind,coalesce(error_code,'unknown')
               LIMIT 50""",
                (run_pk,),
            )
        )
    finally:
        conn.close()
    safe = re.compile(r"^[a-z0-9_:-]{1,80}$")

    def normalized(
        rows: list[tuple[Any, ...]], include_status: bool
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for row in rows:
            resource, code = str(row[0]), str(row[1])
            if not safe.fullmatch(resource) or not safe.fullmatch(code):
                _fail("failure_breakdown_unsafe")
            entry: dict[str, object] = {
                "resource": resource,
                "code": code,
                "count": int(row[-1]),
            }
            if include_status:
                status_value = str(row[2])
                if status_value not in {"open", "deferred"}:
                    _fail("failure_breakdown_unsafe")
                entry["status"] = status_value
            result.append(entry)
        return result

    return {
        "gap_breakdown": normalized(gap_rows, True),
        "failed_item_breakdown": normalized(item_rows, False),
        "breakdown_truncated": len(gap_rows) == 50 or len(item_rows) == 50,
    }


def _change_breakdown(
    db: Path,
    provider_run_id: str | None,
) -> list[dict[str, object]]:
    """Summarise repeat-run changes without exposing object keys or payloads."""
    if provider_run_id is None or not _RUN.fullmatch(provider_run_id):
        _fail("change_breakdown_identity_invalid")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        run = conn.execute(
            "SELECT id FROM garmin_sync_runs WHERE run_id=?",
            (provider_run_id,),
        ).fetchone()
        if run is None:
            # Injected/offline transports used by the verifier may return a
            # schema-valid receipt without materialising provider run rows.
            # Diagnostics must never replace the primary no-op gate failure.
            return []
        rows = list(
            conn.execute(
                """SELECT resource_kind,status,count(*)
                   FROM garmin_sync_items
                   WHERE garmin_sync_run_id=?
                     AND status IN ('revised','unchanged')
                   GROUP BY resource_kind,status
                   ORDER BY resource_kind,status
                   LIMIT 100""",
                (int(run[0]),),
            )
        )
    finally:
        conn.close()
    safe = re.compile(r"^[a-z0-9_:-]{1,80}$")
    result: list[dict[str, object]] = []
    for resource, status, count in rows:
        resource_value, status_value = str(resource), str(status)
        if not safe.fullmatch(resource_value) or status_value not in {
            "revised",
            "unchanged",
        }:
            _fail("change_breakdown_unsafe")
        result.append(
            {
                "resource": resource_value,
                "status": status_value,
                "count": int(count),
            }
        )
    return result


def _safe(path: Path, directory: bool) -> os.stat_result:
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or bool(stat.S_ISDIR(info.st_mode)) != directory
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        _fail("unsafe_path")
    return info


def _safe_tree(root: Path) -> None:
    _safe(root, True)
    for item in root.rglob("*"):
        _safe(item, item.is_dir())


def _window(start: str, through: str) -> int:
    try:
        days = (date.fromisoformat(through) - date.fromisoformat(start)).days + 1
    except ValueError as exc:
        raise SmokeRuntimeError("approved_window_invalid") from exc
    if not 1 <= days <= 14:
        _fail("approved_window_invalid")
    return days


def _check_request(request: SmokeRuntimeRequest) -> int:
    if (
        not _AUTH.fullmatch(request.authorization_id)
        or set(request.approved_modes) != set(_MODES)
        or request.bounded_activity_window_authorized is not True
        or not _HASH.fullmatch(request.e04_backup_receipt_sha256)
        or request.operator_registered is not True
        or request.shadow_attested is not True
        or request.canonical_owner_unchanged is not True
    ):
        _fail("smoke_authorization_incomplete")
    if (
        len(request.invocation_ids) != 8
        or len(set(request.invocation_ids)) != 8
        or any(not _INV.fullmatch(value) for value in request.invocation_ids)
    ):
        _fail("invocation_ids_invalid")
    return _window(request.approved_from, request.approved_through)


def _copy_token(source: Path, target: Path) -> None:
    _safe(source, True)
    target.mkdir(mode=0o700)
    for item in source.iterdir():
        before = _safe(item, False)
        if stat.S_IMODE(before.st_mode) != 0o600:
            _fail("unsafe_token_store")
        fd = os.open(item, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ):
                _fail("token_replaced")
            out = target / item.name
            out_fd = os.open(
                out,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                while chunk := os.read(fd, 1024 * 1024):
                    os.write(out_fd, chunk)
                os.fsync(out_fd)
            finally:
                os.close(out_fd)
            after = _safe(item, False)
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ):
                _fail("token_replaced")
        finally:
            os.close(fd)


def _request(mode: str, invocation: str, start: str, through: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "health_from_local_date": start if mode in {"repair", "audit"} else None,
        "through_local_date": through
        if mode in {"incremental", "repair", "audit"}
        else None,
        "snapshot_local_date": through if mode == "snapshot" else None,
        "resource_kinds": ["steps"] if mode == "repair" else [],
        "activity_ids": [],
        "repair_strategy": "refetch" if mode == "repair" else None,
        "invocation_id": invocation,
    }


def _verify_shadow(shadow: Path) -> None:
    _safe_tree(shadow)
    config = FoundationConfig(
        shadow,
        shadow / "data.db",
        shadow / "raw",
        shadow / "state",
        shadow / "state/foundation-ready.json",
        shadow / "state/locks/foundation.lock",
    )
    if (
        FoundationTool(config)
        .execute(
            FoundationRequest("verify", "smoke-shadow-verify", "2026-01-01T00:00:00Z")
        )
        .status
        != "ready"
    ):
        _fail("foundation_shadow_not_ready")


def _transport_config(
    path: Path, start: str, through: str, days: int
) -> dict[str, Any]:
    _safe(path, False)
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))["garmin"]
    except Exception as exc:
        raise SmokeRuntimeError("smoke_config_invalid") from exc
    allowed = (
        "region",
        "request_min_interval_ms",
        "request_interval_jitter_ms",
        "request_timeout_seconds",
        "max_attempts",
        "retry_base_seconds",
        "retry_max_seconds",
        "inline_retry_after_max_seconds",
        "rate_limit_fallback_seconds",
        "max_repair_items_per_incremental",
    )
    if not isinstance(value, dict) or any(key not in value for key in allowed):
        _fail("smoke_config_invalid")
    return {key: value[key] for key in allowed} | {
        "history_start_date": start,
        "lookback_days": days,
        "approved_from": start,
        "approved_through": through,
    }


def _write_json(path: Path, value: object) -> None:
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        os.write(
            fd,
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
            + b"\n",
        )
        os.fsync(fd)
    finally:
        os.close(fd)


def _worker_payload(
    workspace: Path, mode: str, request: dict[str, Any], config: dict[str, Any]
) -> Path:
    path = workspace / f"request-{request['invocation_id']}.json"
    _write_json(path, {"mode": mode, "request": request, "config": config})
    return path


def _run_child(
    command: list[str], cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
    )

    def terminate_and_reap() -> None:
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            # communicate drains both pipes; wait makes the reaping guarantee
            # explicit even when a mocked communicate implementation is used.
            try:
                process.communicate()
            except Exception:
                pass
            try:
                process.wait()
            except Exception:
                pass

    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_and_reap()
        raise SmokeRuntimeError("child_timeout") from exc
    except Exception as exc:
        terminate_and_reap()
        raise SmokeRuntimeError("child_execution_failed") from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, "")


def _validate_actual_request(expected: dict[str, Any]) -> None:
    request_schema = json.loads(
        resource_bytes("harness/schemas/garmin_sync_request.schema.json")
    )
    if list(Draft202012Validator(request_schema).iter_errors(expected)):
        _fail("request_schema_invalid")


def _validate_receipt(
    raw: str, mode: str, expected: dict[str, Any], returncode: int, approved_start: str
) -> dict[str, Any]:
    if len(raw.splitlines()) != 1:
        _fail("receipt_not_single_line")
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmokeRuntimeError("receipt_invalid") from exc
    _validate_actual_request(expected)
    schema = json.loads(
        resource_bytes("harness/schemas/garmin_sync_receipt.schema.json")
    )
    if (
        list(Draft202012Validator(schema).iter_errors(receipt))
        or receipt.get("mode") != mode
        or receipt.get("status") not in _EXIT
    ):
        _fail("receipt_schema_invalid")
    run_id = receipt.get("run_id")
    if (mode in {"auth", "status"} and run_id is not None) or (
        mode not in {"auth", "status"}
        and (not isinstance(run_id, str) or not _RUN.fullmatch(run_id))
    ):
        _fail("receipt_identity_invalid")
    for error in receipt.get("errors", []):
        if not re.fullmatch(r"[a-z0-9_]{1,80}", str(error.get("code", ""))):
            _fail("receipt_sensitive")
    expected_start = (
        expected["health_from_local_date"]
        or expected["snapshot_local_date"]
        or (approved_start if mode == "incremental" else None)
    )
    if receipt["effective_range"] != {
        "from": expected_start,
        "through": expected["through_local_date"] or expected["snapshot_local_date"],
    }:
        _fail("receipt_window_invalid")
    if returncode != _EXIT[receipt["status"]]:
        _fail("receipt_exit_invalid")
    return receipt


def run_smoke(
    request: SmokeRuntimeRequest,
    *,
    execute: Callable[..., Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    started_at = monotonic()

    def elapsed(since: float) -> float:
        value = monotonic() - since
        if not math.isfinite(value) or value < 0:
            _fail("clock_invalid")
        return round(value, 3)

    def emit(value: dict[str, object]) -> None:
        if progress is not None:
            progress(value)

    days = _check_request(request)
    root = request.isolated_root.absolute()
    _safe(root, True)
    shadow = root / "foundation-shadow"
    _verify_shadow(shadow)
    production_token_before = _tree_snapshot(request.production_token_store)
    production_config_before = _tree_snapshot(request.production_garmin_config)
    shadow_before = _tree_snapshot(shadow)
    if (root / "smoke-result").exists():
        _fail("smoke_result_exists")
    workspace = Path(tempfile.mkdtemp(prefix=".smoke-", dir=root))
    os.chmod(workspace, 0o700)
    published = False
    try:
        clone = workspace / "foundation"
        shutil.copytree(shadow, clone, copy_function=shutil.copy2)
        _verify_shadow(clone)
        state = clone / "state"
        token = state / "secrets" / "garmin"
        (state / "secrets").mkdir(mode=0o700)
        _copy_token(request.production_token_store, token)
        receipts = workspace / "receipts"
        receipts.mkdir(mode=0o700)
        config = _transport_config(
            request.production_garmin_config,
            request.approved_from,
            request.approved_through,
            days,
        )
        operations: list[dict[str, object]] = []
        seen_runs: set[str] = set()
        snapshot_cursor_before: str | None = None
        snapshot_cursor_after: str | None = None
        repeat_counts: dict[str, dict[str, object]] = {}
        for index, (mode, invocation) in enumerate(
            zip(_MODES, request.invocation_ids), 1
        ):
            actual = "auth" if mode == "auth" else mode
            stage_started = monotonic()
            emit(
                {
                    "event": "stage_started",
                    "stage_index": index,
                    "total_stages": len(_MODES),
                    "mode": actual,
                }
            )
            try:
                item = _request(
                    actual, invocation, request.approved_from, request.approved_through
                )
                _validate_actual_request(item)
                if actual == "snapshot" and snapshot_cursor_before is None:
                    snapshot_cursor_before = _cursor_hash(clone / "data.db")
                payload = _worker_payload(workspace, actual, item, config)
                command = [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "index.py"),
                    "__garmin-smoke-worker",
                    str(payload),
                ]
                completed = (
                    execute(
                        command,
                        cwd=workspace,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=request.timeout_override_seconds or _TIMEOUTS[actual],
                        start_new_session=True,
                        env={},
                    )
                    if execute
                    else _run_child(
                        command,
                        workspace,
                        request.timeout_override_seconds or _TIMEOUTS[actual],
                    )
                )
            except SmokeRuntimeError:
                emit(
                    {
                        "event": "stage_failed",
                        "stage_index": index,
                        "total_stages": len(_MODES),
                        "mode": actual,
                        "duration_seconds": elapsed(stage_started),
                    }
                )
                raise
            except Exception as exc:
                emit(
                    {
                        "event": "stage_failed",
                        "stage_index": index,
                        "total_stages": len(_MODES),
                        "mode": actual,
                        "duration_seconds": elapsed(stage_started),
                    }
                )
                raise SmokeRuntimeError("child_execution_failed") from exc
            try:
                receipt = _validate_receipt(
                    completed.stdout,
                    actual,
                    item,
                    completed.returncode,
                    request.approved_from,
                )
                if actual not in {"auth", "status"}:
                    if receipt["run_id"] in seen_runs:
                        _fail("receipt_run_id_duplicate")
                    seen_runs.add(receipt["run_id"])
                if actual == "snapshot":
                    if receipt["coverage_state"] != "partial":
                        _fail("snapshot_coverage_invalid")
                    snapshot_cursor_after = _cursor_hash(clone / "data.db")
                    if snapshot_cursor_before != snapshot_cursor_after:
                        _fail("snapshot_cursor_advanced")
                summary = {
                    "mode": actual,
                    "invocation_id": invocation,
                    "run_id": receipt["run_id"],
                    "status": receipt["status"],
                    "exit_code": completed.returncode,
                    "request_sha256": _semantic_request_hash(item),
                    "receipt_sha256": _hash(receipt),
                    "effective_range": receipt["effective_range"],
                    "no_op": False,
                    "duration_seconds": elapsed(stage_started),
                }
                if index in {3, 5}:
                    repeat_counts[actual] = receipt["counts"]
                _write_json(receipts / f"{index:02d}.json", summary)
                operations.append(summary)
            except Exception:
                emit(
                    {
                        "event": "stage_failed",
                        "stage_index": index,
                        "total_stages": len(_MODES),
                        "mode": actual,
                        "duration_seconds": elapsed(stage_started),
                    }
                )
                raise
            if receipt["status"] != "succeeded":
                counts = receipt["counts"]
                failure_event = {
                    "event": "stage_failed",
                    "stage_index": index,
                    "total_stages": len(_MODES),
                    "mode": actual,
                    "duration_seconds": summary["duration_seconds"],
                    "status": receipt["status"],
                    "failed_count": counts["failed"],
                    "deferred_count": counts["deferred"],
                    "not_available_count": counts["not_available"],
                    "not_enabled_count": counts["not_enabled"],
                    "open_gap_count": receipt["open_gap_count"],
                    "retry_scheduled": receipt["next_retry_at_utc"] is not None,
                    "error_codes": sorted(
                        {error["code"] for error in receipt["errors"]}
                    ),
                }
                failure_event.update(
                    _failure_breakdown(clone / "data.db", receipt["run_id"])
                )
                emit(failure_event)
                _fail("operation_not_succeeded")
            emit(
                {
                    "event": "stage_completed",
                    "stage_index": index,
                    "total_stages": len(_MODES),
                    "mode": actual,
                    "duration_seconds": summary["duration_seconds"],
                    "status": receipt["status"],
                    "fetched_count": receipt["counts"]["fetched"],
                    "unchanged_count": receipt["counts"]["unchanged"],
                    "revised_count": receipt["counts"]["revised"],
                    "failed_count": receipt["counts"]["failed"],
                    "deferred_count": receipt["counts"]["deferred"],
                }
            )
        shutil.rmtree(token)
        if token.exists():
            _fail("token_cleanup_failed")
        incremental_first, incremental_second = operations[1], operations[2]
        snapshot_first, snapshot_second = operations[3], operations[4]

        def is_no_op(
            first: dict[str, object],
            second: dict[str, object],
            counts: dict[str, object] | None,
        ) -> bool:
            return (
                first["request_sha256"] == second["request_sha256"]
                and second["status"] == "succeeded"
                and counts is not None
                and all(
                    counts.get(key) == 0
                    for key in ("revised", "failed", "deferred", "fetched")
                )
            )

        incremental_no_op = is_no_op(
            incremental_first, incremental_second, repeat_counts.get("incremental")
        )
        snapshot_no_op = is_no_op(
            snapshot_first, snapshot_second, repeat_counts.get("snapshot")
        )
        incremental_second["no_op"] = bool(incremental_no_op)
        snapshot_second["no_op"] = bool(snapshot_no_op)
        no_op = incremental_no_op and snapshot_no_op
        if not no_op:
            emit(
                {
                    "event": "validation_failed",
                    "gate": "repeat_no_op",
                    "incremental_no_op": bool(incremental_no_op),
                    "snapshot_no_op": bool(snapshot_no_op),
                    "incremental_repeat_counts": repeat_counts.get("incremental"),
                    "snapshot_repeat_counts": repeat_counts.get("snapshot"),
                    "incremental_change_breakdown": _change_breakdown(
                        clone / "data.db",
                        cast(str, incremental_second["run_id"]),
                    ),
                    "snapshot_change_breakdown": _change_breakdown(
                        clone / "data.db",
                        cast(str, snapshot_second["run_id"]),
                    ),
                }
            )
            _fail("repeat_not_no_op")
        if (
            _tree_snapshot(request.production_token_store) != production_token_before
            or _tree_snapshot(request.production_garmin_config)
            != production_config_before
            or _tree_snapshot(shadow) != shadow_before
        ):
            _fail("input_changed")
        token_hashes = {row[-1] for row in production_token_before.values() if row[-1]}
        credential_prefix = ("foundation", "state", "secrets", "garmin")
        for item_path in workspace.rglob("*"):
            item_info = item_path.lstat()
            if stat.S_ISLNK(item_info.st_mode):
                _fail("published_sensitive_path")
            relative_parts = item_path.relative_to(workspace).parts
            # The credential boundary is the exact copied token directory,
            # not arbitrary benign filenames containing the English substring
            # "token" (for example provider tokenization metadata).  Renamed
            # credential copies are still rejected by the byte-hash check.
            if relative_parts[: len(credential_prefix)] == credential_prefix:
                _fail("published_sensitive_path")
            if (
                item_path.is_file()
                and sha256(item_path.read_bytes()).hexdigest() in token_hashes
            ):
                _fail("published_token_copy")
        total_elapsed = elapsed(started_at)
        _write_json(
            workspace / "operations.json",
            {
                "schema_version": "1",
                "operations": operations,
                "total_elapsed_seconds": total_elapsed,
                "repeat_no_op": bool(no_op),
                "incremental_repeat_no_op": bool(incremental_no_op),
                "snapshot_repeat_no_op": bool(snapshot_no_op),
                "snapshot_cursor_unchanged": snapshot_cursor_before
                == snapshot_cursor_after,
                "snapshot_cursor_after_sha256": snapshot_cursor_after,
                "snapshot_cursor_before_sha256": snapshot_cursor_before,
            },
        )
        os.replace(workspace, root / "smoke-result")
        published = True
        result = {
            "schema_version": "1",
            "status": "succeeded",
            "operations": operations,
            "total_elapsed_seconds": total_elapsed,
        }
        emit({"event": "smoke_completed", "total_elapsed_seconds": total_elapsed})
        return result
    finally:
        if not published and workspace.exists():
            try:
                shutil.rmtree(workspace)
            except OSError as exc:
                raise SmokeRuntimeError("workspace_cleanup_failed") from exc
            if workspace.exists():
                _fail("workspace_cleanup_failed")


class _BoundedSmokeTransport:
    """Forbid unbounded inventory APIs and enforce the approved activity window."""

    def __init__(
        self, delegate: Any, approved_from: str, approved_through: str
    ) -> None:
        self.delegate, self.approved_from, self.approved_through = (
            delegate,
            approved_from,
            approved_through,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def activity_count(self) -> int:
        raise RuntimeError("unbounded_activity_inventory_forbidden")

    def activity_page(self, _offset: int, _limit: int) -> Any:
        raise RuntimeError("unbounded_activity_inventory_forbidden")

    def list_activities(self, start: str | None, through: str | None) -> Any:
        if (
            start is None
            or through is None
            or start < self.approved_from
            or through > self.approved_through
        ):
            raise RuntimeError("activity_window_outside_approval")
        return self.delegate.list_activities(start, through)


def _worker(path: Path) -> int:
    from .garmin import GarminCollectionTool, GarminConfig, SyncRequest
    from .garmin_client import GarminConnectTransport, TokenStore

    value = json.loads(path.read_text())
    root = path.parent
    foundation = root / "foundation"
    if value.get("mode") not in set(_MODES):
        raise ValueError("smoke_mode_forbidden")
    options = value["config"]
    cfg = GarminConfig(
        foundation / "data.db",
        foundation / "raw",
        foundation / "state",
        options["history_start_date"],
        region=options["region"],
        lookback_days=options["lookback_days"],
        max_repair_items_per_incremental=options["max_repair_items_per_incremental"],
        request_min_interval_ms=options["request_min_interval_ms"],
        request_interval_jitter_ms=options["request_interval_jitter_ms"],
        request_timeout_seconds=options["request_timeout_seconds"],
        max_attempts=options["max_attempts"],
        retry_base_seconds=options["retry_base_seconds"],
        retry_max_seconds=options["retry_max_seconds"],
        inline_retry_after_max_seconds=options["inline_retry_after_max_seconds"],
        rate_limit_fallback_seconds=options["rate_limit_fallback_seconds"],
    )
    delegate = GarminConnectTransport(
        None, None, TokenStore(cfg.state_root / "secrets" / "garmin"), region=cfg.region
    )
    transport = _BoundedSmokeTransport(
        delegate, options["approved_from"], options["approved_through"]
    )
    request = SyncRequest(
        **{
            **value["request"],
            "resource_kinds": tuple(value["request"]["resource_kinds"]),
            "activity_ids": tuple(value["request"]["activity_ids"]),
        }
    )
    receipt = GarminCollectionTool(cfg, transport).execute(request)
    print(receipt.json())
    return _EXIT[receipt.status]
