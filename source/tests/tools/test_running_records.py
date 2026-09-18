from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.fit.fit_bytes import activity_data, frame
from tests.fit.test_b1_regressions import dump, valid
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import (
    TOOL_CONTRACTS,
    CapacityPolicy,
    ToolAuthorization,
    validate_payload,
)
from trainlab.fit import import_activity, import_fit_file, initialize_schema, open_database
from trainlab.running_records import get_running_records, handle_get_running_records


def auth(*activity_ids: str) -> ToolAuthorization:
    return ToolAuthorization(
        allowed_activity_ids=frozenset(activity_ids), allowed_reference_ids=frozenset()
    )


def query(db_path: Path, activity_id: str, **kw: Any) -> dict[str, Any]:
    return get_running_records(activity_id, db_path=db_path, authorization=auth(activity_id), **kw)


def test_get_running_records_returns_all_running_records_in_original_order(tmp_path: Path) -> None:
    fit_path = tmp_path / "activity.fit"
    fit_path.write_bytes(frame(activity_data()))
    activity_id = import_fit_file(tmp_path, fit_path)
    db_path = tmp_path / "states/data.db"

    result = query(db_path, activity_id)

    assert result["ok"] is True
    assert result["schema_version"] == "fit-records/1"
    assert result["activity_id"] == activity_id
    records = result["data"]["records"]
    assert [record["record_index"] for record in records] == [0, 1, 2, 3]
    assert records[1]["timestamp_utc"] == records[2]["timestamp_utc"]
    assert all("activity_id" not in record for record in records)
    assert isinstance(records[0]["metrics_json"], dict)
    assert 0 in records[0]["metrics_json"]["standard"].values()
    assert result["data"]["field_definitions"]
    validate_payload("GetRunningRecordsResult", result)


def test_request_rejects_extra_parameters_before_database_access(tmp_path: Path) -> None:
    result = handle_get_running_records(
        {"activity_id": "a" * 64, "limit": 1},
        db_path=tmp_path / "missing.db",
        authorization=auth("a" * 64),
    )

    assert result["ok"] is False
    assert result["activity_id"] is None
    assert result["data"] is None
    assert result["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value


def test_authorization_non_running_unknown_missing_and_database_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    running_id = "a" * 64
    cycling_id = "b" * 64
    unknown_id = "c" * 64
    with open_database(db_path) as connection:
        initialize_schema(connection)
        import_activity(connection, activity_id=running_id, fit_path="a.fit", parsed=valid())
        cycling = valid()
        cycling = replace(
            cycling,
            sport="cycling",
            basic={**cycling.basic, "sport": "cycling"},
        )
        import_activity(connection, activity_id=cycling_id, fit_path="b.fit", parsed=cycling)
        unknown = valid()
        unknown = replace(unknown, sport=None, basic={**unknown.basic, "sport": None})
        import_activity(connection, activity_id=unknown_id, fit_path="c.fit", parsed=unknown)

    unauthorized = get_running_records(running_id, db_path=db_path, authorization=auth())
    assert unauthorized["error"]["code"] == ErrorCode.TOOL_NOT_ALLOWED.value

    non_running = get_running_records(cycling_id, db_path=db_path, authorization=auth(cycling_id))
    assert non_running["error"]["code"] == ErrorCode.SPORT_NOT_ALLOWED.value

    unknown_result = get_running_records(unknown_id, db_path=db_path, authorization=auth(unknown_id))
    assert unknown_result["error"]["code"] == ErrorCode.SPORT_UNKNOWN.value

    missing_activity = get_running_records("d" * 64, db_path=db_path, authorization=auth("d" * 64))
    assert missing_activity["error"]["code"] == ErrorCode.ACTIVITY_NOT_FOUND.value

    missing_db = get_running_records("e" * 64, db_path=tmp_path / "missing.db", authorization=auth("e" * 64))
    assert missing_db["error"]["code"] == ErrorCode.DATABASE_UNAVAILABLE.value


def test_bad_json_schema_and_capacity_fail_without_partial_data(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    activity_id = "a" * 64
    with open_database(db_path) as connection:
        initialize_schema(connection)
        import_activity(connection, activity_id=activity_id, fit_path="a.fit", parsed=valid())
        with connection:
            connection.execute(
                "UPDATE records SET metrics_json=? WHERE activity_id=? AND record_index=0",
                ('{"not valid"', activity_id),
            )
    bad_json = query(db_path, activity_id)
    assert bad_json["ok"] is False
    assert bad_json["data"] is None
    assert bad_json["error"]["code"] == ErrorCode.DATA_INVALID.value

    with open_database(db_path) as connection:
        with connection:
            connection.execute("DELETE FROM records WHERE activity_id=?", (activity_id,))
        import_activity(connection, activity_id="b" * 64, fit_path="b.fit", parsed=valid())
    too_large = get_running_records(
        "b" * 64,
        db_path=db_path,
        authorization=auth("b" * 64),
        capacity=CapacityPolicy(storage_bytes_limit=None, model_payload_bytes_limit=1),
    )
    assert too_large["ok"] is False
    assert too_large["data"] is None
    assert too_large["error"]["code"] == ErrorCode.RESOURCE_LIMIT.value


def test_query_is_read_only_and_does_not_touch_reports_or_config(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    activity_id = "a" * 64
    with open_database(db_path) as connection:
        initialize_schema(connection)
        import_activity(connection, activity_id=activity_id, fit_path="a.fit", parsed=valid())
        with connection:
            connection.execute("INSERT INTO activties_report VALUES(?,NULL,?)", (activity_id, "全文"))
            connection.execute(
                "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
                ("2030-01-01T00:00:00.000000Z", "周全文"),
            )
            connection.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("synthetic", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        before = dump(connection)

    result = query(db_path, activity_id)

    with sqlite3.connect(db_path) as connection:
        after = dump(connection)
    assert result["ok"] is True
    assert after == before


def test_tools_index_schema_and_machine_declaration_do_not_drift() -> None:
    readme = Path(__file__).resolve().parents[2].joinpath("tools/README.md").read_text(
        encoding="utf-8"
    )

    assert set(TOOL_CONTRACTS) == {"get_running_records", "read_reference"}
    contract = TOOL_CONTRACTS["get_running_records"]
    assert contract.parameters_schema == "GetRunningRecordsRequest"
    assert contract.result_schema == "GetRunningRecordsResult"
    assert contract.requires_host_authorization is True
    assert {"sql", "path", "database", "limit", "cursor", "metrics", "start_time", "end_time"}.issubset(
        set(contract.forbidden_parameters)
    )
    assert "get_running_records(activity_id)" in readme
    assert "`read_reference(reference_id)`" in readme
    assert "limit" in readme and "cursor" in readme and "SQL" in readme
    validate_payload("GetRunningRecordsRequest", {"activity_id": "a" * 64})
    try:
        validate_payload("GetRunningRecordsRequest", {"activity_id": "a" * 64, "limit": 1})
    except ValueError:
        pass
    else:  # pragma: no cover - defensive assertion for schema drift
        raise AssertionError("extra tool parameter unexpectedly accepted")
