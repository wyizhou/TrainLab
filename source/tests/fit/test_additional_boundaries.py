from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import replace
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from tests.fit.fit_bytes import T, activity_data, definition, frame, message
from tests.fit.test_b1_regressions import dump, valid
from tests.fit.test_decoder import named
from trainlab.check_architecture import check_layout
from trainlab.contracts.json_validation import loads, validate
from trainlab.database import read_view
from trainlab.fit import import_fit_file, open_database, storage
from trainlab.fit.parser import ProfileFitDecoder


def test_schema_strict_json_and_nested_extra() -> None:
    for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}']:
        with pytest.raises(ValueError):
            loads(text)
    value = valid()
    facts = {
        "activity_id": "a" * 64,
        "schema_version": 1,
        "basic_json": value.basic,
        "summary_json": value.summary,
        "segments_json": value.segments,
        "field_definitions": value.sensors["field_definitions"],
        "developer_sources": {},
    }
    validate("ActivityFacts", facts)
    facts["summary_json"]["messages"][0]["fields"]["extra"] = 1
    with pytest.raises(ValueError):
        validate("ActivityFacts", facts)


def test_schema_ids_are_exact_and_not_newline_terminated() -> None:
    validate("GetRunningRecordsRequest", {"activity_id": "a" * 64})
    with pytest.raises(ValueError):
        validate("GetRunningRecordsRequest", {"activity_id": "a" * 64 + "\n"})


def test_fieldset_cannot_mix_chain_definitions(tmp_path: Path) -> None:
    from trainlab.fit import import_activity, init_database

    init_database(tmp_path / "db.db")
    value = valid()
    value.sensors["field_definitions"]["f2"] = {
        **value.sensors["field_definitions"]["f0"],
        "chain_index": 1,
    }
    value.records[0].metrics["standard"]["f2"] = 2
    with open_database(tmp_path / "db.db") as c:
        with pytest.raises(ValueError):
            import_activity(c, activity_id="a" * 64, fit_path="a.fit", parsed=value)
        assert c.execute("SELECT count(*) FROM activities").fetchone() == (0,)


def test_record_body_cannot_be_saved_in_default_summary(tmp_path: Path) -> None:
    from trainlab.fit import import_activity, init_database

    init_database(tmp_path / "db.db")
    value = valid()
    value.summary["messages"][0] = {
        "message_index": 0,
        "chain_index": 0,
        "message_number": 20,
        "message_name": "record",
        "fields": {"standard": {"f0": 1}, "developer": {}},
    }
    with open_database(tmp_path / "db.db") as c:
        with pytest.raises(ValueError):
            import_activity(c, activity_id="a" * 64, fit_path="a.fit", parsed=value)
        assert c.execute("SELECT count(*) FROM activities").fetchone() == (0,)


def test_compressed_timestamp_overflow_is_explicit_error() -> None:
    extra = message(1, 20, [(253, 4, 0x86), (3, 1, 2)], struct.pack("<IB", 0xFFFFFFFE, 120))
    extra += bytes([0x80 | (1 << 5) | 1, 123])
    with pytest.raises(ValueError):
        ProfileFitDecoder().decode(frame(activity_data(extra=extra)))


def test_component_accumulation_uses_component_units() -> None:
    extra = message(1, 20, [(5, 4, 0x86)], struct.pack("<I", 10000))
    extra += message(1, 20, [(8, 3, 13)], (200 | (1608 << 12)).to_bytes(3, "little"))
    p = ProfileFitDecoder().decode(frame(activity_data(extra=extra)))
    assert named(p, p.records[-1].metrics["standard"])["distance"] == 100.5


def test_packed_byte_ff_is_not_an_invalid_element() -> None:
    extra = message(1, 20, [(8, 3, 13)], (255 | (1600 << 12)).to_bytes(3, "little"))
    p = ProfileFitDecoder().decode(frame(activity_data(extra=extra)))
    assert named(p, p.records[-1].metrics["standard"])["speed"] == 2.55


def test_component_repeated_array_complete() -> None:
    extra = message(
        8, 132, [(10, 6, 13)], (100 | (200 << 12) | (300 << 24) | (400 << 36)).to_bytes(6, "little")
    )
    p = ProfileFitDecoder().decode(frame(activity_data(extra=extra)))
    m = next(m for m in p.sensors["messages"] if m["message_number"] == 132)
    values = named(p, m["fields"]["standard"])
    assert len(values["event_timestamp"]) == 4


def test_compressed_header_without_timestamp_in_definition() -> None:
    extra = message(1, 20, [(253, 4, 0x86), (3, 1, 2)], struct.pack("<IB", T + 19, 120))
    extra += definition(1, 20, [(3, 1, 2)]) + bytes([0x80 | (1 << 5) | 21, 123])
    p = ProfileFitDecoder().decode(frame(activity_data(extra=extra)))
    previous = p.records[-2].timestamp_utc
    assert previous is not None
    assert p.records[-1].timestamp_utc == previous.replace(second=21)
    assert named(p, p.records[-1].metrics["standard"])["heart_rate"] == 123


def test_missing_activity_in_second_complete_activity_chain() -> None:
    with pytest.raises(ValueError):
        ProfileFitDecoder().decode(frame(activity_data()) + frame(activity_data(omit=34)))


def test_missing_developer_description_not_silently_skipped() -> None:
    extra = message(1, 20, [(253, 4, 0x86)], struct.pack("<IH", T, 1), [(0, 2, 0)])
    with pytest.raises(ValueError):
        ProfileFitDecoder().decode(frame(activity_data(extra=extra)))


def test_big_endian_and_float_invalid_zero() -> None:
    extra = (
        definition(8, 60001, [(0, 4, 0x88), (1, 2, 0x84)], big=True)
        + b"\x08"
        + bytes.fromhex("ffffffff0000")
    )
    p = ProfileFitDecoder().decode(frame(activity_data(extra=extra)))
    m = next(m for m in p.sensors["messages"] if m["message_number"] == 60001)
    assert list(m["fields"]["standard"].values()) == [None, 0]


def test_nonfinite_float_is_error_not_null() -> None:
    extra = message(8, 60001, [(0, 4, 0x88)], struct.pack("<f", float("inf")))
    with pytest.raises(ValueError):
        ProfileFitDecoder().decode(frame(activity_data(extra=extra)))


def test_duplicate_definition_is_error() -> None:
    extra = definition(8, 20, [(3, 1, 2), (3, 1, 2)]) + b"\x08\x01\x02"
    with pytest.raises(ValueError):
        ProfileFitDecoder().decode(frame(activity_data(extra=extra)))


def test_maintenance_sha_guard_no_change_and_atomic_update(tmp_path: Path) -> None:
    path = tmp_path / "original.fit"
    data = frame(activity_data())
    path.write_bytes(data)
    ident = import_fit_file(tmp_path, path)
    with open_database(tmp_path / "states/data.db") as c:
        before = dump(c)
    storage.reparse_fit_file(tmp_path, ident)
    with open_database(tmp_path / "states/data.db") as c:
        assert dump(c) == before
    path.write_bytes(data + b"changed")
    with pytest.raises(ValueError, match="SOURCE_CONFLICT"):
        storage.reparse_fit_file(tmp_path, ident)
    with open_database(tmp_path / "states/data.db") as c:
        assert dump(c) == before
    path.write_bytes(data)

    class ChangedDecoder:
        def decode(self, content: bytes) -> Any:
            return replace(
                ProfileFitDecoder().decode(content),
                records=ProfileFitDecoder().decode(content).records[:1],
            )

    storage.reparse_fit_file(tmp_path, ident, decoder=ChangedDecoder())
    with open_database(tmp_path / "states/data.db") as c:
        assert c.execute("SELECT count(*) FROM records").fetchone() == (1,)
        assert c.execute("SELECT fit_path FROM activities").fetchone() == ("original.fit",)
        with c:
            c.execute("INSERT INTO activties_report VALUES(?,NULL,?)", (ident, "全文"))
        before = dump(c)
    with pytest.raises(ValueError, match="REPARSE_CONFLICT"):
        storage.reparse_fit_file(tmp_path, ident)
    with open_database(tmp_path / "states/data.db") as c:
        assert dump(c) == before


def test_maintenance_failure_keeps_old_database(tmp_path: Path) -> None:
    p = tmp_path / "original.fit"
    p.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, p)
    with open_database(tmp_path / "states/data.db") as c:
        with c:
            c.execute(
                "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
                ("2030-01-01T00:00:00.000000Z", "完整历史周报"),
            )
            c.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("synthetic", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        before = dump(c)
        c.executescript(
            "CREATE TRIGGER fail BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'child failure'); END;"
        )

    class ChangedDecoder:
        def decode(self, content: bytes) -> Any:
            parsed = ProfileFitDecoder().decode(content)
            return replace(parsed, records=parsed.records[:2])

    with pytest.raises(sqlite3.IntegrityError, match="child failure"):
        storage.reparse_fit_file(tmp_path, ident, decoder=ChangedDecoder())
    with open_database(tmp_path / "states/data.db") as c:
        assert dump(c) == before


def test_read_view_blocks_writer_and_has_no_sidecars(tmp_path: Path) -> None:
    from trainlab.database import write_gate

    p = tmp_path / "a.fit"
    p.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, p)
    db = tmp_path / "states/data.db"
    before = db.read_bytes()
    errors = []

    def writer() -> None:
        try:
            with write_gate(timeout=0.01):
                pass
        except ValueError as exc:
            errors.append(str(exc))

    with read_view(db) as view:
        assert view.execute("SELECT activity_id FROM activities").fetchone() == (ident,)
        with pytest.raises(sqlite3.OperationalError):
            view.execute("DELETE FROM activities")
        thread = Thread(target=writer)
        thread.start()
        thread.join()
        assert errors == ["RUN_BUSY"]
    assert db.read_bytes() == before
    assert sorted(x.name for x in db.parent.iterdir()) == ["data.db"]


def test_architecture_negative_cases(tmp_path: Path) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "contracts.schema.json").write_text("{}")
    check_layout(tmp_path)
    bad = tmp_path / "trainlab"
    bad.mkdir()
    with pytest.raises(ValueError):
        check_layout(tmp_path)
    bad.rmdir()
    script = tmp_path / "skills/_shared/scripts/bad.py"
    script.parent.mkdir(parents=True)
    script.write_text('import sys\nsys.path.insert(0, "x")')
    with pytest.raises(ValueError):
        check_layout(tmp_path)


def test_component_dictionary_closure_and_sources(tmp_path: Path) -> None:
    p = tmp_path / "a.fit"
    p.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, p)
    with open_database(tmp_path / "states/data.db") as c:
        v = valid()
        d = v.sensors["field_definitions"]["f1"]
        d.update(field_number=18, name="avg_cadence", unit="rpm")
        v.sensors["field_definitions"]["f2"] = {
            **d,
            "origin": "expanded",
            "component_of": "f1",
            "name": "avg_running_cadence",
            "unit": "strides/min",
        }
        v.summary["messages"][0]["fields"]["standard"] = {"f2": 12}
        storage.replace_activity(c, activity_id=ident, parsed=v)
        facts = storage.get_activity_facts(c, ident)
        assert set(facts["field_definitions"]) == {"f1", "f2"}
        assert facts["developer_sources"] == {}
        assert "records" not in json.dumps(facts)


def test_single_file_multisession_not_first_running() -> None:
    data = activity_data(omit=34)
    data += message(
        8,
        19,
        [(254, 2, 0x84), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (253, 4, 0x86)],
        struct.pack("<HIIII", 1, T + 20, 10000, 10000, T + 30),
    )
    data += message(
        8,
        18,
        [(5, 1, 0), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (253, 4, 0x86)],
        struct.pack("<BIIII", 2, T + 20, 10000, 10000, T + 30),
    )
    data += message(8, 34, [(1, 2, 0x84)], struct.pack("<H", 2))
    p = ProfileFitDecoder().decode(frame(data))
    assert p.sport is None and len(p.summary["messages"]) == 2
    assert p.end_time_utc is not None and p.start_time_utc is not None
    assert (p.end_time_utc - p.start_time_utc).total_seconds() == 30
