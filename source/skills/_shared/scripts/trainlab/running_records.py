"""Read-only get_running_records tool implementation for ADHOC-0025."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import CapacityPolicy, ToolAuthorization, validate_payload
from trainlab.contracts.json_validation import definition_closure, loads
from trainlab.database import read_view

FIT_RECORDS_SCHEMA_VERSION = "fit-records/1"
FIT_STORAGE_SCHEMA_VERSION = 1


def handle_get_running_records(
    request: Mapping[str, Any],
    *,
    db_path: Path,
    authorization: ToolAuthorization,
    capacity: CapacityPolicy | None = None,
) -> dict[str, Any]:
    """Validate a tool-call payload and return the complete records envelope."""
    request_payload = dict(request)
    try:
        validate_payload("GetRunningRecordsRequest", request_payload)
    except ValueError:
        return _failure(
            ErrorCode.INVALID_ARGUMENT,
            "request must contain exactly activity_id",
            None,
            {"allowed_parameters": ["activity_id"]},
        )
    return get_running_records(
        request_payload["activity_id"],
        db_path=db_path,
        authorization=authorization,
        capacity=capacity,
    )


def get_running_records(
    activity_id: str,
    *,
    db_path: Path,
    authorization: ToolAuthorization,
    capacity: CapacityPolicy | None = None,
) -> dict[str, Any]:
    """Return all stored record samples for one host-authorized running activity."""
    try:
        validate_payload("GetRunningRecordsRequest", {"activity_id": activity_id})
    except ValueError:
        return _failure(ErrorCode.INVALID_ARGUMENT, "invalid activity_id", None)
    if not authorization.can_read_records(activity_id):
        return _failure(ErrorCode.TOOL_NOT_ALLOWED, "activity is not authorized", activity_id)
    try:
        with read_view(db_path) as connection:
            result = _read_records(connection, activity_id)
    except _ToolFailure as failure:
        return _failure(failure.code, failure.message, activity_id, failure.details)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return _failure(
            ErrorCode.DATABASE_UNAVAILABLE,
            "database is unavailable",
            activity_id,
            {"reason": exc.__class__.__name__},
        )
    try:
        validate_payload("GetRunningRecordsResult", result)
        _check_capacity(result, capacity)
    except _ToolFailure as failure:
        return _failure(failure.code, failure.message, activity_id, failure.details)
    except (TypeError, ValueError) as exc:
        return _failure(
            ErrorCode.DATA_INVALID,
            "stored records are invalid",
            activity_id,
            {"reason": exc.__class__.__name__},
        )
    return result


def _read_records(connection: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT sport,schema_version,sensors_json FROM activities WHERE activity_id=?",
        (activity_id,),
    ).fetchone()
    if row is None:
        raise _ToolFailure(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
    sport, schema_version, sensors_text = row
    if schema_version != FIT_STORAGE_SCHEMA_VERSION:
        raise _ToolFailure(ErrorCode.SCHEMA_UNSUPPORTED, "unsupported storage schema")
    if sport is None or sport == "" or sport == "unknown":
        raise _ToolFailure(ErrorCode.SPORT_UNKNOWN, "activity sport is unknown")
    if sport != "running":
        raise _ToolFailure(ErrorCode.SPORT_NOT_ALLOWED, "activity is not running")
    sensors = _load_object(sensors_text)
    definitions = sensors.get("field_definitions")
    sources = sensors.get("developer_sources")
    if not isinstance(definitions, dict) or not isinstance(sources, dict):
        raise _ToolFailure(ErrorCode.DATA_INVALID, "stored field dictionary is invalid")
    rows = connection.execute(
        "SELECT record_index,timestamp_utc,metrics_json FROM records WHERE activity_id=? ORDER BY record_index",
        (activity_id,),
    ).fetchall()
    records = [
        {
            "record_index": record_index,
            "timestamp_utc": timestamp_utc,
            "metrics_json": _load_object(metrics_text),
        }
        for record_index, timestamp_utc, metrics_text in rows
    ]
    used_field_ids = {
        field_id
        for record in records
        for category in ("standard", "developer")
        for field_id in record["metrics_json"].get(category, {})
    }
    try:
        needed = definition_closure(set(used_field_ids), definitions)
    except ValueError as exc:
        raise _ToolFailure(ErrorCode.DATA_INVALID, "record field dictionary is incomplete") from exc
    selected_definitions = {key: value for key, value in definitions.items() if key in needed}
    source_ids = {
        value["source_ref"] for value in selected_definitions.values() if value["source_ref"] is not None
    }
    selected_sources = {key: value for key, value in sources.items() if key in source_ids}
    return {
        "schema_version": FIT_RECORDS_SCHEMA_VERSION,
        "ok": True,
        "activity_id": activity_id,
        "data": {
            "field_definitions": selected_definitions,
            "developer_sources": selected_sources,
            "records": records,
        },
        "error": None,
    }


def _load_object(text: str) -> dict[str, Any]:
    try:
        value = loads(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _ToolFailure(ErrorCode.DATA_INVALID, "stored JSON is invalid") from exc
    if not isinstance(value, dict):
        raise _ToolFailure(ErrorCode.DATA_INVALID, "stored JSON must be an object")
    return value


def _check_capacity(result: dict[str, Any], capacity: CapacityPolicy | None) -> None:
    if capacity is None:
        return
    encoded = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    try:
        capacity.check_model_payload(len(encoded))
    except ValueError as exc:
        raise _ToolFailure(
            ErrorCode.RESOURCE_LIMIT,
            "complete records payload exceeds model capacity",
            {"bytes": len(encoded)},
        ) from exc


def _failure(
    code: ErrorCode,
    message: str,
    activity_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": FIT_RECORDS_SCHEMA_VERSION,
        "ok": False,
        "activity_id": activity_id,
        "data": None,
        "error": {"code": code.value, "message": message, "details": {} if details is None else details},
    }
    validate_payload("GetRunningRecordsResult", result)
    return result


class _ToolFailure(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details
