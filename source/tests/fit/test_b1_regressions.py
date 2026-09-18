from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.fit.fit_bytes import activity_data, frame
from trainlab.contracts.interfaces import validate_payload
from trainlab.fit import (
    ParsedActivity,
    get_activity_facts,
    import_activity,
    import_fit_file,
    initialize_schema,
    storage,
)


def valid() -> ParsedActivity:
    from trainlab.fit.models import ParsedRecord

    field = {
        "message_number": 20,
        "message_name": "record",
        "field_number": 3,
        "name": "heart_rate",
        "base_type": "uint8",
        "unit": "bpm",
        "origin": "direct",
        "source_ref": None,
        "definition_index": 0,
        "chain_index": 0,
        "component_of": None,
        "value_form": "physical",
    }
    session_field = {
        **field,
        "message_number": 18,
        "message_name": "session",
        "definition_index": 1,
        "field_number": 16,
        "name": "avg_heart_rate",
    }
    message = {
        "message_index": 2,
        "chain_index": 0,
        "message_number": 18,
        "message_name": "session",
        "fields": {"standard": {"f1": 100}, "developer": {}},
    }
    return ParsedActivity(
        "running",
        None,
        None,
        None,
        {
            "sport": "running",
            "sub_sport": None,
            "start_time_utc": None,
            "end_time_utc": None,
            "messages": [],
        },
        {"messages": [message]},
        {"items": []},
        {
            "field_definitions": {"f0": field, "f1": session_field},
            "developer_sources": {},
            "messages": [],
        },
        (
            ParsedRecord(
                None,
                {
                    "standard": {"f0": 0},
                    "developer": {},
                    "time_evidence": {"kind": "missing", "raw": None, "unit": None},
                },
            ),
        ),
    )


@pytest.fixture
def db() -> Any:
    c = sqlite3.connect(":memory:")
    initialize_schema(c)
    yield c
    c.close()


def store(c: sqlite3.Connection, value: ParsedActivity | None = None, **kw: Any) -> str:
    return import_activity(
        c,
        activity_id="a" * 64,
        fit_path="states/activities/a.fit",
        parsed=valid() if value is None else value,
        **kw,
    )


def dump(c: sqlite3.Connection) -> list[Any]:
    return [
        c.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
        for name in ("activities", "records", "activties_report", "weekly_report", "config")
    ]


def test_real_fit_default_entry(tmp_path: Path) -> None:
    p = tmp_path / "states/activities/input.fit"
    p.parent.mkdir(parents=True)
    p.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, p)
    with sqlite3.connect(tmp_path / "states/data.db") as c:
        assert c.execute("SELECT count(*) FROM records").fetchone() == (4,)
        facts = get_activity_facts(c, ident)
        validate_payload("ActivityFacts", facts)
        assert facts["basic_json"]["sport"] == "running"


def test_real_fit_long_record_collection(tmp_path: Path) -> None:
    data = frame(activity_data(count=25001))
    p = tmp_path / "long.fit"
    p.write_bytes(data)
    ident = import_fit_file(tmp_path, p)
    with sqlite3.connect(tmp_path / "states/data.db") as c:
        rows = c.execute(
            "SELECT record_index,timestamp_utc FROM records WHERE activity_id=? ORDER BY record_index",
            (ident,),
        ).fetchall()
        assert len(rows) == 25001
        assert [r[0] for r in rows] == list(range(25001))
        assert rows[1][1] == rows[2][1] and rows[3][1] > rows[4][1]
    assert p.read_bytes() == data


def test_approved_layout() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "trainlab").exists()
    assert not list((root / "tools").rglob("*.py"))
    assert list((root / "schemas").glob("*.json"))


def test_valid_schema_default_dictionary(db: sqlite3.Connection) -> None:
    store(db)
    facts = get_activity_facts(db, "a" * 64)
    assert set(facts) == {
        "activity_id",
        "schema_version",
        "basic_json",
        "summary_json",
        "segments_json",
        "field_definitions",
        "developer_sources",
    }
    assert set(facts["field_definitions"]) == {"f1"}
    validate_payload("ActivityFacts", facts)
    with pytest.raises(ValueError):
        validate_payload("ActivityFacts", {**facts, "unapproved": 1})


@pytest.mark.parametrize(
    "case",
    [
        "undefined",
        "source",
        "origin",
        "time",
        "extra",
        "sport",
        "start",
        "integer",
        "object",
        "nan",
        "bytes",
        "component",
        "category",
    ],
)
def test_invalid_from_valid_baseline(db: sqlite3.Connection, case: str) -> None:
    store(db)
    with db:
        db.execute("INSERT INTO activties_report VALUES(?,NULL,?)", ("a" * 64, "完整活动报告"))
        db.execute(
            "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
            ("2030-01-01T00:00:00.000000Z", "完整历史周报"),
        )
        db.execute(
            "INSERT INTO config VALUES(?,?,?)", ("synthetic", "{}", "2030-01-01T00:00:00.000000Z")
        )
    before = dump(db)
    v = copy.deepcopy(valid())
    m = v.records[0].metrics
    defs = v.sensors["field_definitions"]
    if case == "undefined":
        m["standard"]["f99"] = 1
    if case == "source":
        defs["f0"]["source_ref"] = "d404"
    if case == "origin":
        defs["f0"]["origin"] = "invented"
    if case == "time":
        m.pop("time_evidence")
    if case == "extra":
        v.basic["extra"] = True
    if case == "sport":
        v.basic["sport"] = "cycling"
    if case == "start":
        v.basic["start_time_utc"] = "2030-01-01T00:00:00.000000Z"
    if case == "integer":
        m["standard"]["f0"] = 9007199254740993
    if case == "object":
        m["standard"]["f0"] = {"metadata": 1}
    if case == "nan":
        m["standard"]["f0"] = float("nan")
    if case == "bytes":
        m["standard"]["f0"] = b"raw"
    if case == "component":
        defs["f0"]["component_of"] = "f404"
    if case == "category":
        m["developer"]["f0"] = m["standard"].pop("f0")
    with pytest.raises(ValueError):
        store(db, v)
    assert dump(db) == before


def test_same_bytes_keeps_all_values(db: sqlite3.Connection) -> None:
    store(db, parsed_at_utc=datetime(2030, 1, 1, tzinfo=UTC))
    before = dump(db)
    import_activity(
        db,
        activity_id="a" * 64,
        fit_path="states/activities/alias.fit",
        parsed=valid(),
        parsed_at_utc=datetime(2030, 1, 2, tzinfo=UTC),
    )
    assert dump(db) == before


def test_explicit_maintenance_conflict_and_no_change(db: sqlite3.Connection) -> None:
    store(db)
    with db:
        db.execute("INSERT INTO activties_report VALUES(?,NULL,?)", ("a" * 64, "完整报告"))
    before = dump(db)
    v = valid()
    v.records[0].metrics["standard"]["f0"] = 90
    with pytest.raises(ValueError, match="REPARSE_CONFLICT"):
        storage.replace_activity(db, activity_id="a" * 64, parsed=v)
    assert dump(db) == before
    storage.replace_activity(db, activity_id="a" * 64, parsed=valid())
    assert dump(db) == before


@pytest.mark.parametrize("existing", [False, True])
def test_product_child_failure(db: sqlite3.Connection, existing: bool) -> None:
    if existing:
        store(db)
    before = dump(db)
    db.executescript(
        "CREATE TRIGGER fail_child BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'child failure'); END;"
    )
    v = valid()
    v.records[0].metrics["standard"]["f0"] = 1
    with pytest.raises(sqlite3.IntegrityError, match="child failure"):
        if existing:
            storage.replace_activity(db, activity_id="a" * 64, parsed=v)
        else:
            store(db, v)
    assert dump(db) == before


def test_long_records_order_and_time(db: sqlite3.Connection) -> None:
    v = valid()
    from trainlab.fit.models import ParsedRecord

    t = datetime(2030, 1, 1, tzinfo=UTC)
    v.sensors["field_definitions"]["f2"] = {
        **v.sensors["field_definitions"]["f0"],
        "field_number": 253,
        "name": "timestamp",
        "base_type": "uint32",
        "unit": "s",
        "value_form": "raw",
    }
    records = []
    for i in range(25001):
        stamp = t + timedelta(seconds=[20, 3, 20][i % 3])
        raw = int(stamp.timestamp()) - 631065600
        records.append(
            ParsedRecord(
                stamp,
                {
                    "standard": {"f0": i, "f2": raw},
                    "developer": {},
                    "time_evidence": {"kind": "absolute", "raw": raw, "unit": "s"},
                },
            )
        )
    store(db, replace(v, records=tuple(records)))
    rows = db.execute(
        "SELECT record_index,timestamp_utc,metrics_json FROM records ORDER BY record_index"
    ).fetchall()
    assert len(rows) == len(records)
    for i, row in enumerate(rows):
        assert row[0] == i
        stored_stamp = records[i].timestamp_utc
        assert stored_stamp is not None
        assert row[1] == stored_stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        assert json.loads(row[2]) == records[i].metrics
