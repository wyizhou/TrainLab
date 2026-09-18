from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.fit.fit_bytes import activity_data, frame
from tests.fit.test_b1_regressions import dump, valid
from trainlab.contracts.errors import ErrorCode
from trainlab.fit import (
    FitStorageError,
    activity_id_for_fit_bytes,
    get_activity_facts,
    import_activity,
    import_fit_file,
    init_database,
    open_database,
    storage,
)
from trainlab.fit.parser import ProfileFitDecoder


def test_init_database_creates_required_tables_and_keeps_existing_report_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "states/data.db"
    init_database(path)
    with open_database(path) as c:
        import_activity(c, activity_id="a" * 64, fit_path="states/activities/a.fit", parsed=valid())
        c.execute("INSERT INTO activties_report VALUES(?,NULL,?)", ("a" * 64, "全文"))
        c.execute(
            "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
            ("2030-01-01T00:00:00.000000Z", "历史全文"),
        )
        c.execute(
            "INSERT INTO config VALUES(?,?,?)", ("synthetic", "{}", "2030-01-01T00:00:00.000000Z")
        )
    with open_database(path) as c:
        before = dump(c)
    init_database(path)
    with open_database(path) as c:
        assert dump(c) == before
        for name, count in [
            ("activities", 12),
            ("records", 4),
            ("activties_report", 3),
            ("weekly_report", 3),
            ("config", 3),
        ]:
            assert len(c.execute(f"PRAGMA table_info({name})").fetchall()) == count
        assert c.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert c.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_import_fit_file_uses_actual_fit_bytes_sha_and_relative_fit_path(tmp_path: Path) -> None:
    data = frame(activity_data())
    p = tmp_path / "misleading.fit"
    p.write_bytes(data)
    ident = import_fit_file(tmp_path, p)
    assert ident == activity_id_for_fit_bytes(data)
    with open_database(tmp_path / "states/data.db") as c:
        assert c.execute("SELECT activity_id,fit_path FROM activities").fetchone() == (
            ident,
            "misleading.fit",
        )
    assert p.read_bytes() == data


def test_import_activity_keeps_original_record_order_duplicate_timestamps_and_zero_values(
    tmp_path: Path,
) -> None:
    data = frame(activity_data())
    p = tmp_path / "input.fit"
    p.write_bytes(data)
    ident = import_fit_file(tmp_path, p)
    with open_database(tmp_path / "states/data.db") as c:
        rows = c.execute(
            "SELECT record_index,timestamp_utc,metrics_json FROM records ORDER BY record_index"
        ).fetchall()
        assert [r[0] for r in rows] == [0, 1, 2, 3]
        assert rows[1][1] == rows[2][1]
        assert 0 in json.loads(rows[0][2])["standard"].values()
        assert None in json.loads(rows[2][2])["standard"].values()
        with c:
            c.execute("INSERT INTO activties_report VALUES(?,NULL,?)", (ident, "全文"))
        before = dump(c)
        parsed = ProfileFitDecoder().decode(data)
        with pytest.raises(FitStorageError) as error:
            storage.replace_activity(
                c, activity_id=ident, parsed=replace(parsed, records=parsed.records[:1])
            )
        assert error.value.code == ErrorCode.REPARSE_CONFLICT
        assert dump(c) == before


def test_zero_record_fit_is_not_blank_success_and_default_facts_exclude_fourth_class(
    tmp_path: Path,
) -> None:
    p = tmp_path / "zero.fit"
    p.write_bytes(frame(activity_data(count=0)))
    with pytest.raises(ValueError):
        import_fit_file(tmp_path, p)
    assert not (tmp_path / "states/data.db").exists()
    p.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, p)
    with open_database(tmp_path / "states/data.db") as c:
        facts = get_activity_facts(c, ident)
        assert not {"records", "sensors", "sensors_json", "fit_path"} & facts.keys()
        assert facts["segments_json"]["items"][0]["message_number"] == 19
        with pytest.raises(FitStorageError) as error:
            get_activity_facts(c, "f" * 64)
        assert error.value.code == ErrorCode.ACTIVITY_NOT_FOUND


def test_illegal_json_or_sensor_records_rolls_back_existing_activity_and_records(
    tmp_path: Path,
) -> None:
    init_database(tmp_path / "data.db")
    with open_database(tmp_path / "data.db") as c:
        import_activity(c, activity_id="a" * 64, fit_path="a.fit", parsed=valid())
        before = dump(c)
        v = valid()
        v.records[0].metrics["standard"]["f0"] = float("nan")
        with pytest.raises(FitStorageError):
            storage.replace_activity(c, activity_id="a" * 64, parsed=v)
        v = valid()
        v.sensors["records"] = []
        with pytest.raises(FitStorageError):
            import_activity(c, activity_id="b" * 64, fit_path="b.fit", parsed=v)
        assert dump(c) == before


def test_child_constraint_failure_rolls_back_activity_row(tmp_path: Path) -> None:
    init_database(tmp_path / "data.db")
    with open_database(tmp_path / "data.db") as c:
        c.executescript(
            "CREATE TRIGGER fail BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'child failure'); END;"
        )
        with pytest.raises(sqlite3.IntegrityError, match="child failure"):
            import_activity(c, activity_id="a" * 64, fit_path="a.fit", parsed=valid())
        assert c.execute("SELECT count(*) FROM activities").fetchone() == (0,)


def test_invalid_activity_id_path_or_decoder_failure_saves_nothing(tmp_path: Path) -> None:
    p = tmp_path / "bad.fit"
    p.write_bytes(b"not a FIT")
    with pytest.raises(ValueError):
        import_fit_file(tmp_path, p)
    assert not (tmp_path / "states/data.db").exists()
    init_database(tmp_path / "db.db")
    with open_database(tmp_path / "db.db") as c:
        for ident, path in [("bad-id", "a.fit"), ("a" * 64, "../outside.fit")]:
            with pytest.raises(FitStorageError):
                import_activity(c, activity_id=ident, fit_path=path, parsed=valid())
        assert c.execute("SELECT count(*) FROM activities").fetchone() == (0,)


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink"])
def test_fit_path_cannot_escape(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "instance"
    root.mkdir()
    outside = tmp_path / "synthetic.fit"
    outside.write_bytes(frame(activity_data()))
    p = outside if kind == "absolute" else Path("../synthetic.fit")
    if kind == "symlink":
        p = root / "link.fit"
        p.symlink_to(outside)
    with pytest.raises(FitStorageError):
        import_fit_file(root, p)
    assert not (root / "states/data.db").exists()


def test_timezone_normalization_and_naive_rollback(tmp_path: Path) -> None:
    init_database(tmp_path / "data.db")
    with open_database(tmp_path / "data.db") as c:
        v = valid()
        t = datetime(2030, 1, 1, tzinfo=UTC)
        offset = timezone(timedelta(hours=8))
        v.basic["start_time_utc"] = "2030-01-01T00:00:00.000000Z"
        v = replace(v, start_time_utc=t.astimezone(offset))
        import_activity(
            c, activity_id="a" * 64, fit_path="a.fit", parsed=v, parsed_at_utc=t.astimezone(offset)
        )
        assert c.execute("SELECT start_time_utc,parsed_at_utc FROM activities").fetchone() == (
            v.basic["start_time_utc"],
            v.basic["start_time_utc"],
        )
        before = dump(c)
        with pytest.raises(ValueError):
            storage.replace_activity(
                c, activity_id="a" * 64, parsed=replace(v, start_time_utc=t.replace(tzinfo=None))
            )
        assert dump(c) == before
