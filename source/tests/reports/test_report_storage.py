from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tests.fit.test_b1_regressions import dump, valid
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import TOOL_CONTRACTS, CapacityPolicy
from trainlab.contracts.time import NO_ACTIVITY_WEEKLY_SUMMARY, format_utc, weekly_window
from trainlab.fit import ParsedActivity, import_activity, initialize_schema
from trainlab.reports import (
    ReportStorageError,
    get_activity_report,
    get_weekly_report,
    save_activity_report,
    save_weekly_report,
)


def memory_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    return connection


def parsed_with_start(start: datetime | None) -> ParsedActivity:
    parsed = valid()
    text = None if start is None else format_utc(start)
    return replace(
        parsed,
        start_time_utc=start,
        basic={**parsed.basic, "start_time_utc": text},
    )


def add_activity(
    connection: sqlite3.Connection,
    activity_id: str = "a" * 64,
    *,
    start: datetime | None = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC),
) -> str:
    return import_activity(
        connection,
        activity_id=activity_id,
        fit_path=f"{activity_id[:8]}.fit",
        parsed=parsed_with_start(start),
    )


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def test_activity_report_saves_three_columns_activity_start_and_full_text() -> None:
    connection = memory_db()
    try:
        start = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
        activity_id = add_activity(connection, start=start)
        null_start_id = add_activity(connection, "b" * 64, start=None)
        original_fit_summary = connection.execute(
            "SELECT summary_json FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone()[0]
        original_records = connection.execute(
            "SELECT * FROM records WHERE activity_id=? ORDER BY record_index", (activity_id,)
        ).fetchall()
        summary = "中文总结\n\n| 项目 | 值 |\n|---|---|\nSELECT * FROM activties_report;"

        saved = save_activity_report(connection, activity_id=activity_id, summary=summary)
        loaded = get_activity_report(connection, activity_id)
        save_activity_report(connection, activity_id=activity_id, summary="第二版全文\n仍然完整")
        null_saved = save_activity_report(connection, activity_id=null_start_id, summary="无开始时间全文")

        assert table_columns(connection, "activties_report") == (
            "activity_id",
            "start_time_utc",
            "summary",
        )
        assert saved == {
            "activity_id": activity_id,
            "start_time_utc": format_utc(start),
            "summary": summary,
        }
        assert loaded == saved
        assert connection.execute(
            "SELECT activity_id,start_time_utc,summary FROM activties_report WHERE activity_id=?",
            (activity_id,),
        ).fetchone() == (activity_id, format_utc(start), "第二版全文\n仍然完整")
        assert connection.execute(
            "SELECT count(*) FROM activties_report WHERE activity_id=?", (activity_id,)
        ).fetchone() == (1,)
        assert null_saved["start_time_utc"] is None
        assert connection.execute(
            "SELECT summary_json FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone()[0] == original_fit_summary
        assert connection.execute(
            "SELECT * FROM records WHERE activity_id=? ORDER BY record_index", (activity_id,)
        ).fetchall() == original_records
    finally:
        connection.close()


@pytest.mark.parametrize("summary", ["", "   \n\t"])
def test_activity_report_rejects_blank_text_and_rolls_back(summary: str) -> None:
    connection = memory_db()
    try:
        activity_id = add_activity(connection)
        before = dump(connection)

        with pytest.raises(ReportStorageError) as error:
            save_activity_report(connection, activity_id=activity_id, summary=summary)

        assert error.value.code == ErrorCode.DATA_INVALID
        assert dump(connection) == before
    finally:
        connection.close()


def test_activity_report_errors_are_atomic_and_do_not_touch_other_tables() -> None:
    connection = memory_db()
    try:
        activity_id = add_activity(connection)
        with connection:
            connection.execute(
                "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
                ("2030-01-01T00:00:00.000000Z", "周全文"),
            )
            connection.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("report", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        before = dump(connection)

        with pytest.raises(ReportStorageError) as missing:
            save_activity_report(connection, activity_id="b" * 64, summary="全文")
        with pytest.raises(ReportStorageError) as too_large:
            save_activity_report(
                connection,
                activity_id=activity_id,
                summary="超过容量",
                capacity=CapacityPolicy(storage_bytes_limit=1, model_payload_bytes_limit=None),
            )
        connection.execute(
            """
            CREATE TRIGGER fail_activity_report
            BEFORE INSERT ON activties_report
            BEGIN SELECT RAISE(ABORT,'activity report failure'); END;
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="activity report failure"):
            save_activity_report(connection, activity_id=activity_id, summary="触发失败")

        assert missing.value.code == ErrorCode.ACTIVITY_NOT_FOUND
        assert too_large.value.code == ErrorCode.RESOURCE_LIMIT
        assert dump(connection) == before
    finally:
        connection.close()


def test_weekly_report_saves_three_columns_same_anchor_and_full_text() -> None:
    connection = memory_db()
    try:
        activity_id = add_activity(connection)
        save_activity_report(connection, activity_id=activity_id, summary="活动全文")
        with connection:
            connection.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("weekly", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        before_activity_rows = connection.execute("SELECT * FROM activities").fetchall()
        before_record_rows = connection.execute("SELECT * FROM records").fetchall()
        run_time_local = datetime(2030, 1, 8, 11, 0, tzinfo=timezone(timedelta(hours=8)))
        expected_run_time = "2030-01-08T03:00:00.000000Z"
        summary = "周总结\n\n- 跑步\n\n```sql\nSELECT 1;\n```"

        first = save_weekly_report(connection, run_time_utc=run_time_local, summary=summary)
        second = save_weekly_report(connection, run_time_utc=run_time_local, summary=NO_ACTIVITY_WEEKLY_SUMMARY)
        loaded = get_weekly_report(connection, first["id"])
        with connection:
            connection.execute("DELETE FROM weekly_report WHERE id=?", (second["id"],))
        third = save_weekly_report(connection, run_time_utc=run_time_local, summary="第三份")
        window_start, window_end = weekly_window(run_time_local)

        assert table_columns(connection, "weekly_report") == ("id", "run_time_utc", "summary")
        assert first == {"id": 1, "run_time_utc": expected_run_time, "summary": summary}
        assert loaded == first
        assert second["id"] == 2
        assert third["id"] == 3
        assert (window_end - window_start).days == 7
        assert format_utc(window_end) == expected_run_time
        rows = connection.execute(
            "SELECT run_time_utc,summary FROM weekly_report ORDER BY id"
        ).fetchall()
        assert rows == [(expected_run_time, summary), (expected_run_time, "第三份")]
        assert connection.execute("SELECT * FROM activities").fetchall() == before_activity_rows
        assert connection.execute("SELECT * FROM records").fetchall() == before_record_rows
        assert get_activity_report(connection, activity_id)["summary"] == "活动全文"
    finally:
        connection.close()


@pytest.mark.parametrize("summary", ["", "  \n"])
def test_weekly_report_rejects_blank_text_and_rolls_back(summary: str) -> None:
    connection = memory_db()
    try:
        before = dump(connection)
        with pytest.raises(ReportStorageError) as error:
            save_weekly_report(
                connection,
                run_time_utc=datetime(2030, 1, 1, tzinfo=UTC),
                summary=summary,
            )
        assert error.value.code == ErrorCode.DATA_INVALID
        assert dump(connection) == before
    finally:
        connection.close()


def test_weekly_report_errors_are_atomic_and_do_not_add_tools() -> None:
    connection = memory_db()
    try:
        activity_id = add_activity(connection)
        save_activity_report(connection, activity_id=activity_id, summary="活动全文")
        before = dump(connection)

        with pytest.raises(ValueError, match="timezone-aware"):
            save_weekly_report(
                connection,
                run_time_utc=datetime(2030, 1, 1),  # noqa: DTZ001 - verifies naive time rejection
                summary="naive",
            )
        with pytest.raises(ReportStorageError) as too_large:
            save_weekly_report(
                connection,
                run_time_utc=datetime(2030, 1, 1, tzinfo=UTC),
                summary="超过容量",
                capacity=CapacityPolicy(storage_bytes_limit=1, model_payload_bytes_limit=None),
            )
        connection.execute(
            """
            CREATE TRIGGER fail_weekly_report
            BEFORE INSERT ON weekly_report
            BEGIN SELECT RAISE(ABORT,'weekly report failure'); END;
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="weekly report failure"):
            save_weekly_report(
                connection,
                run_time_utc=datetime(2030, 1, 1, tzinfo=UTC),
                summary="触发失败",
            )

        assert too_large.value.code == ErrorCode.RESOURCE_LIMIT
        assert dump(connection) == before
        assert set(TOOL_CONTRACTS) == {"get_running_records", "read_reference"}
    finally:
        connection.close()
