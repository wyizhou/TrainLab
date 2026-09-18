"""SQLite persistence for parsed FIT activities and record messages."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.json_validation import definition_closure, loads, validate
from trainlab.contracts.paths import DATA_DB_PATH
from trainlab.contracts.schema import ddl_statements
from trainlab.contracts.time import format_utc
from trainlab.database import write_gate
from trainlab.fit.models import ParsedActivity
from trainlab.fit.parser import FitDecoder, ProfileFitDecoder

FIT_STORAGE_SCHEMA_VERSION = 1


class FitStorageError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code


def activity_id_for_fit_bytes(fit_bytes: bytes) -> str:
    return hashlib.sha256(fit_bytes).hexdigest()


def open_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        connection.close()
        raise FitStorageError(ErrorCode.DATABASE_UNAVAILABLE, "rollback journal required")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    _foreign_keys(connection)
    with write_gate(), connection:
        for statement in ddl_statements(include_system=True):
            connection.execute(statement)


def init_database(db_path: Path) -> None:
    connection = open_database(db_path)
    try:
        initialize_schema(connection)
    finally:
        connection.close()


def import_fit_file(
    instance_root: Path,
    fit_path: Path,
    decoder: FitDecoder | None = None,
    *,
    db_path: Path | None = None,
    parsed_at_utc: datetime | None = None,
) -> str:
    absolute, relative = _fit_path_inside_instance(instance_root, fit_path)
    content = absolute.read_bytes()
    activity_id = activity_id_for_fit_bytes(content)
    parsed = (ProfileFitDecoder() if decoder is None else decoder).decode(content)
    _validated(parsed)
    database_path = instance_root / DATA_DB_PATH if db_path is None else db_path
    connection = open_database(database_path)
    try:
        initialize_schema(connection)
        import_activity(
            connection,
            activity_id=activity_id,
            fit_path=relative,
            parsed=parsed,
            parsed_at_utc=parsed_at_utc,
        )
    finally:
        connection.close()
    return activity_id


def reparse_fit_file(
    instance_root: Path,
    activity_id: str,
    *,
    decoder: FitDecoder | None = None,
    db_path: Path | None = None,
    parsed_at_utc: datetime | None = None,
) -> str:
    _validate_activity_id(activity_id)
    database_path = instance_root / DATA_DB_PATH if db_path is None else db_path
    connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=rw", uri=True)
    try:
        _foreign_keys(connection)
        row = connection.execute(
            "SELECT fit_path FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone()
        if row is None:
            raise FitStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
        absolute, _ = _fit_path_inside_instance(instance_root, Path(row[0]))
        content = absolute.read_bytes()
        if activity_id_for_fit_bytes(content) != activity_id:
            raise FitStorageError(ErrorCode.SOURCE_CONFLICT, "original SHA mismatch")
        parsed = (ProfileFitDecoder() if decoder is None else decoder).decode(content)
        replace_activity(
            connection, activity_id=activity_id, parsed=parsed, parsed_at_utc=parsed_at_utc
        )
    finally:
        connection.close()
    return activity_id


def _foreign_keys(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise FitStorageError(ErrorCode.DATABASE_UNAVAILABLE, "foreign keys unavailable")
    if connection.execute("PRAGMA journal_mode").fetchone()[0] not in ("delete", "memory"):
        raise FitStorageError(ErrorCode.DATABASE_UNAVAILABLE, "rollback journal required")


def import_activity(
    connection: sqlite3.Connection,
    *,
    activity_id: str,
    fit_path: Path | str,
    parsed: ParsedActivity,
    parsed_at_utc: datetime | None = None,
) -> str:
    _foreign_keys(connection)
    _validate_activity_id(activity_id)
    path = _normalize_relative_fit_path(Path(fit_path)).as_posix()
    payload = _validated(parsed)
    when = format_utc(datetime.now(UTC) if parsed_at_utc is None else parsed_at_utc)
    with write_gate(), connection:
        if connection.execute(
            "SELECT 1 FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone():
            return activity_id
        connection.execute(
            "INSERT INTO activities VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            _activity_row(activity_id, path, when, payload),
        )
        _insert_records(connection, activity_id, payload)
    return activity_id


def replace_activity(
    connection: sqlite3.Connection,
    *,
    activity_id: str,
    parsed: ParsedActivity,
    parsed_at_utc: datetime | None = None,
) -> str:
    _foreign_keys(connection)
    _validate_activity_id(activity_id)
    payload = _validated(parsed)
    when = format_utc(datetime.now(UTC) if parsed_at_utc is None else parsed_at_utc)
    with write_gate(), connection:
        row = connection.execute(
            "SELECT * FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone()
        if row is None:
            raise FitStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
        new = _activity_row(activity_id, row[1], when, payload)
        existing_records = connection.execute(
            "SELECT record_index,timestamp_utc,metrics_json FROM records WHERE activity_id=? ORDER BY record_index",
            (activity_id,),
        ).fetchall()
        same = row[2:7] == new[2:7] and all(
            loads(a) == loads(b) for a, b in zip(row[8:], new[8:], strict=True)
        )
        same = same and [(r[0], r[1], loads(r[2])) for r in existing_records] == [
            (r["record_index"], r["timestamp_utc"], r["metrics_json"]) for r in payload["records"]
        ]
        if same:
            return activity_id
        if connection.execute(
            "SELECT 1 FROM activties_report WHERE activity_id=?", (activity_id,)
        ).fetchone():
            raise FitStorageError(ErrorCode.REPARSE_CONFLICT, "report depends on existing facts")
        connection.execute(
            "UPDATE activities SET sport=?,sub_sport=?,start_time_utc=?,end_time_utc=?,schema_version=?,parsed_at_utc=?,basic_json=?,summary_json=?,segments_json=?,sensors_json=? WHERE activity_id=?",
            (*new[2:], activity_id),
        )
        connection.execute("DELETE FROM records WHERE activity_id=?", (activity_id,))
        _insert_records(connection, activity_id, payload)
    return activity_id


def get_activity_facts(connection: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT schema_version,sport,sub_sport,start_time_utc,end_time_utc,basic_json,summary_json,segments_json,sensors_json FROM activities WHERE activity_id=?",
        (activity_id,),
    ).fetchone()
    if row is None:
        raise FitStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
    if row[0] != FIT_STORAGE_SCHEMA_VERSION:
        raise FitStorageError(ErrorCode.SCHEMA_UNSUPPORTED, "unsupported storage schema")
    basic, summary, segments, sensors = (loads(v) for v in row[5:])
    payload = dict(
        zip(("sport", "sub_sport", "start_time_utc", "end_time_utc"), row[1:5], strict=True)
    )
    payload.update(
        basic_json=basic,
        summary_json=summary,
        segments_json=segments,
        sensors_json=sensors,
        records=[],
    )
    validate("ParsedActivity", payload)
    ids = {
        key
        for m in basic["messages"] + summary["messages"] + segments["items"]
        for category in ("standard", "developer")
        for key in m["fields"][category]
    }
    needed = definition_closure(ids, sensors["field_definitions"])
    definitions = {k: v for k, v in sensors["field_definitions"].items() if k in needed}
    source_ids = {v["source_ref"] for v in definitions.values() if v["source_ref"] is not None}
    result = {
        "activity_id": activity_id,
        "schema_version": row[0],
        "basic_json": basic,
        "summary_json": summary,
        "segments_json": segments,
        "field_definitions": definitions,
        "developer_sources": {
            k: v for k, v in sensors["developer_sources"].items() if k in source_ids
        },
    }
    validate("ActivityFacts", result)
    return result


def _validated(parsed: ParsedActivity) -> dict[str, Any]:
    try:
        payload = {
            "sport": parsed.sport,
            "sub_sport": parsed.sub_sport,
            "start_time_utc": None
            if parsed.start_time_utc is None
            else format_utc(parsed.start_time_utc),
            "end_time_utc": None
            if parsed.end_time_utc is None
            else format_utc(parsed.end_time_utc),
            "basic_json": parsed.basic,
            "summary_json": parsed.summary,
            "segments_json": parsed.segments,
            "sensors_json": parsed.sensors,
            "records": [
                {
                    "record_index": i,
                    "timestamp_utc": None
                    if r.timestamp_utc is None
                    else format_utc(r.timestamp_utc),
                    "metrics_json": r.metrics,
                }
                for i, r in enumerate(parsed.records)
            ],
        }
        validate("ParsedActivity", payload)
        return payload
    except (ValueError, TypeError, OverflowError) as exc:
        raise FitStorageError(ErrorCode.DATA_INVALID, "invalid parsed activity") from exc


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _activity_row(activity_id: str, path: str, when: str, p: dict[str, Any]) -> tuple[Any, ...]:
    return (
        activity_id,
        path,
        p["sport"],
        p["sub_sport"],
        p["start_time_utc"],
        p["end_time_utc"],
        FIT_STORAGE_SCHEMA_VERSION,
        when,
        *(_json(p[k]) for k in ("basic_json", "summary_json", "segments_json", "sensors_json")),
    )


def _insert_records(c: sqlite3.Connection, activity_id: str, p: dict[str, Any]) -> None:
    c.executemany(
        "INSERT INTO records VALUES(?,?,?,?)",
        (
            (activity_id, r["record_index"], r["timestamp_utc"], _json(r["metrics_json"]))
            for r in p["records"]
        ),
    )


def _validate_activity_id(activity_id: str) -> None:
    if (
        not isinstance(activity_id, str)
        or len(activity_id) != 64
        or any(c not in "0123456789abcdef" for c in activity_id)
    ):
        raise FitStorageError(ErrorCode.DATA_INVALID, "invalid SHA-256")


def _fit_path_inside_instance(instance_root: Path, fit_path: Path) -> tuple[Path, Path]:
    root = instance_root.resolve(strict=False)
    absolute = (fit_path if fit_path.is_absolute() else root / fit_path).resolve(strict=False)
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise FitStorageError(
            ErrorCode.INVALID_ARGUMENT, "fit_path must stay inside instance"
        ) from exc
    return absolute, _normalize_relative_fit_path(relative)


def _normalize_relative_fit_path(fit_path: Path) -> Path:
    if fit_path.is_absolute():
        raise FitStorageError(ErrorCode.INVALID_ARGUMENT, "fit_path must be relative")
    normalized = Path(os.path.normpath(fit_path.as_posix()))
    if (
        normalized == Path(".")
        or normalized.parts[0] == ".."
        or normalized.suffix.lower() != ".fit"
    ):
        raise FitStorageError(ErrorCode.INVALID_ARGUMENT, "invalid fit_path")
    return normalized
