"""Controlled SQLite storage for activity and weekly AI report summaries."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import CapacityPolicy, validate_payload
from trainlab.contracts.time import format_utc
from trainlab.database import write_gate


class ReportStorageError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code


def save_activity_report(
    connection: sqlite3.Connection,
    *,
    activity_id: str,
    summary: str,
    capacity: CapacityPolicy | None = None,
) -> dict[str, Any]:
    """Save the current full activity report text for one existing activity."""
    _foreign_keys(connection)
    with write_gate(), connection:
        row = connection.execute(
            "SELECT start_time_utc FROM activities WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        if row is None:
            raise ReportStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
        payload = {
            "activity_id": activity_id,
            "start_time_utc": row[0],
            "summary": summary,
        }
        _validate("ActivityReportSave", payload)
        _check_summary_capacity(summary, capacity)
        connection.execute(
            """
            INSERT INTO activties_report(activity_id,start_time_utc,summary) VALUES(?,?,?)
            ON CONFLICT(activity_id) DO UPDATE SET
                start_time_utc=excluded.start_time_utc,
                summary=excluded.summary
            """,
            (payload["activity_id"], payload["start_time_utc"], payload["summary"]),
        )
        return payload


def get_activity_report(connection: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT activity_id,start_time_utc,summary FROM activties_report WHERE activity_id=?",
        (activity_id,),
    ).fetchone()
    if row is None:
        raise ReportStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "activity report not found")
    payload = {"activity_id": row[0], "start_time_utc": row[1], "summary": row[2]}
    _validate("ActivityReportSave", payload)
    return payload


def save_weekly_report(
    connection: sqlite3.Connection,
    *,
    run_time_utc: datetime,
    summary: str,
    capacity: CapacityPolicy | None = None,
) -> dict[str, Any]:
    """Append one full weekly report text using the supplied run-time anchor T."""
    _foreign_keys(connection)
    payload = {"run_time_utc": format_utc(run_time_utc), "summary": summary}
    _validate("WeeklyReportSave", payload)
    _check_summary_capacity(summary, capacity)
    with write_gate(), connection:
        cursor = connection.execute(
            "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
            (payload["run_time_utc"], payload["summary"]),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise ReportStorageError(ErrorCode.DATA_INVALID, "weekly report id unavailable")
        return {"id": row_id, **payload}


def get_weekly_report(connection: sqlite3.Connection, report_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT id,run_time_utc,summary FROM weekly_report WHERE id=?",
        (report_id,),
    ).fetchone()
    if row is None:
        raise ReportStorageError(ErrorCode.ACTIVITY_NOT_FOUND, "weekly report not found")
    payload = {"run_time_utc": row[1], "summary": row[2]}
    _validate("WeeklyReportSave", payload)
    return {"id": row[0], **payload}


def _foreign_keys(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ReportStorageError(ErrorCode.DATABASE_UNAVAILABLE, "foreign keys unavailable")


def _check_summary_capacity(summary: str, capacity: CapacityPolicy | None) -> None:
    if capacity is None:
        return
    try:
        capacity.check_storage(len(summary.encode("utf-8")))
    except ValueError as exc:
        raise ReportStorageError(ErrorCode.RESOURCE_LIMIT, "summary exceeds storage capacity") from exc


def _validate(schema_name: str, payload: dict[str, Any]) -> None:
    try:
        validate_payload(schema_name, payload)
    except ValueError as exc:
        raise ReportStorageError(ErrorCode.DATA_INVALID, "invalid report payload") from exc
