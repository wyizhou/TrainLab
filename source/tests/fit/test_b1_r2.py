from __future__ import annotations

import copy
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from tests.fit.fit_bytes import T, activity_data, developer, frame, message
from tests.fit.test_b1_regressions import dump
from trainlab.check_architecture import check_layout
from trainlab.fit import import_fit_file, storage
from trainlab.fit.parser import ProfileFitDecoder


def summary(number: int, omit: int | None = None, invalid: bool = False) -> bytes:
    fields = [(n, 4, 0x86) for n in (253, 2, 7, 8) if n != omit]
    values = {253: T + 20, 2: T, 7: 20000, 8: 17000}
    return message(
        8,
        number,
        fields,
        b"".join(struct.pack("<I", 0xFFFFFFFF if invalid else values[n]) for n, _, _ in fields),
    )


def reject_bytes(tmp_path: Path, content: bytes) -> None:
    p = tmp_path / "bad.fit"
    p.write_bytes(content)
    with pytest.raises(ValueError):
        import_fit_file(tmp_path, p)
    assert not (tmp_path / "states/data.db").exists()
    good = tmp_path / "good.fit"
    good.write_bytes(frame(activity_data()))
    ident = import_fit_file(tmp_path, good)
    with storage.open_database(tmp_path / "states/data.db") as c:
        with c:
            c.execute("INSERT INTO activties_report VALUES(?,NULL,?)", (ident, "全文\n保留"))
            c.execute(
                "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
                ("2030-01-01T00:00:00.000000Z", "周报"),
            )
            c.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("synthetic", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        before = dump(c)
        with pytest.raises(ValueError):
            import_fit_file(tmp_path, p)
        assert dump(c) == before
    assert p.read_bytes() == content


@pytest.mark.parametrize("number", [18, 19])
@pytest.mark.parametrize("missing", [253, 2, 7, 8])
def test_required_summary_presence(tmp_path: Path, number: int, missing: int) -> None:
    reject_bytes(tmp_path, frame(activity_data(omit=number, extra=summary(number, missing))))


@pytest.mark.parametrize("number", [18, 19, 20, 34])
def test_empty_required_message(tmp_path: Path, number: int) -> None:
    reject_bytes(tmp_path, frame(activity_data(omit=number, extra=message(8, number, [], b""))))


@pytest.mark.parametrize("developer_field", [False, True])
def test_invalid_field_number(tmp_path: Path, developer_field: bool) -> None:
    extra = (
        developer(0, number=255) + message(8, 20, [], b"\0\0", [(255, 2, 0)])
        if developer_field
        else message(8, 65000, [(255, 1, 2)], b"\0")
    )
    reject_bytes(tmp_path, frame(activity_data(extra=extra)))


def test_timestamp_alone_is_not_a_sample(tmp_path: Path) -> None:
    reject_bytes(
        tmp_path, frame(activity_data(extra=message(8, 20, [(253, 4, 0x86)], struct.pack("<I", T))))
    )


@pytest.mark.parametrize("kind", ["missing", "invalid", "relative", "absolute"])
@pytest.mark.parametrize("dev", [False, True])
def test_defined_null_and_zero_remain_legal(tmp_path: Path, kind: str, dev: bool) -> None:
    fields = [] if kind == "missing" else [(253, 4, 0x86)]
    raw = {
        "missing": b"",
        "invalid": struct.pack("<I", 0xFFFFFFFF),
        "relative": struct.pack("<I", 0),
        "absolute": struct.pack("<I", 0x10000000),
    }[kind]
    if dev:
        extra = developer(0) + message(8, 20, fields, raw + b"\0\0", [(0, 2, 0)])
    else:
        extra = message(8, 20, fields + [(3, 1, 2)], raw + b"\xff")
    extra += summary(18, invalid=True) + summary(19, invalid=True)
    content = frame(activity_data(omit=34, extra=extra + message(8, 34, [(1, 2, 0x84)], b"\2\0")))
    p = tmp_path / "good.fit"
    p.write_bytes(content)
    import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        metrics = json.loads(
            c.execute("SELECT metrics_json FROM records ORDER BY record_index DESC").fetchone()[0]
        )
        assert metrics["time_evidence"]["kind"] == kind
        assert (0 if dev else None) in metrics["developer" if dev else "standard"].values()
        assert c.execute("SELECT count(*) FROM records").fetchone() == (5,)


@pytest.mark.parametrize("raw", [0, 0x0FFFFFFF, 0x10000000, 0x10000001, 0xFFFFFFFE])
def test_date_time_numeric_domains(tmp_path: Path, raw: int) -> None:
    extra = message(8, 20, [(253, 4, 0x86), (3, 1, 2)], struct.pack("<IB", raw, 0))
    extra += message(8, 65000, [(0, 1, 2)], b"\0")
    p = tmp_path / "time.fit"
    p.write_bytes(frame(activity_data(extra=extra)))
    ident = import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        sensors = json.loads(c.execute("SELECT sensors_json FROM activities").fetchone()[0])
        metrics = json.loads(
            c.execute("SELECT metrics_json FROM records ORDER BY record_index DESC").fetchone()[0]
        )
        defs = sensors["field_definitions"]
        key = next(k for k in metrics["standard"] if defs[k]["field_number"] == 253)
        assert metrics["standard"][key] == metrics["time_evidence"]["raw"] == raw
        assert defs[key]["value_form"] == "raw"
        assert storage.get_activity_facts(c, ident)["activity_id"] == ident


@pytest.mark.parametrize("tail", [[], [0xFFFFFFFF], [0xFFFFFFFF, 11264]])
def test_accumulated_arrays_and_mixed_values(tmp_path: Path, tail: list[int]) -> None:
    values = [10240, 11264] + tail
    extra = message(
        8, 132, [(9, 4 * len(values), 0x86)], struct.pack("<" + "I" * len(values), *values)
    )
    compressed = message(8, 132, [(10, 3, 13)], (0 | (1024 << 12)).to_bytes(3, "little"))
    extra += compressed
    extra += message(8, 132, [(9, 8, 0x86)], struct.pack("<2I", 20480, 21504))
    extra += compressed
    p = tmp_path / "hr.fit"
    p.write_bytes(frame(activity_data(extra=extra)) + frame(activity_data(extra=compressed)))
    import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        sensors = json.loads(c.execute("SELECT sensors_json FROM activities").fetchone()[0])
        defs = sensors["field_definitions"]
        arrays = [
            v
            for m in sensors["messages"]
            for k, v in m["fields"]["standard"].items()
            if defs[k]["name"] == "event_timestamp" and defs[k]["origin"] == "expanded"
        ]
        assert arrays == [[12, 13], [24, 25], [0, 1]]


@pytest.mark.parametrize("components_first", [False, True])
def test_same_message_accumulated_direct_and_expanded(
    tmp_path: Path, components_first: bool
) -> None:
    direct = ((9, 8, 0x86), struct.pack("<2I", 10240, 11264))
    compressed = ((10, 3, 13), (0 | (1024 << 12)).to_bytes(3, "little"))
    parts = [compressed, direct] if components_first else [direct, compressed]
    extra = message(8, 132, [f for f, _ in parts], b"".join(v for _, v in parts))
    extra += message(8, 132, [compressed[0]], compressed[1])
    p = tmp_path / "mixed.fit"
    p.write_bytes(frame(activity_data(extra=extra)))
    import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        sensors = json.loads(c.execute("SELECT sensors_json FROM activities").fetchone()[0])
        defs = sensors["field_definitions"]
        values = [
            v
            for m in sensors["messages"]
            for k, v in m["fields"]["standard"].items()
            if defs[k]["name"] == "event_timestamp"
        ]
        assert [10, 11] in values
        assert [12, 13] in values
        assert values[-1] == [16, 17]


def test_local_datetime_boundary_is_raw(tmp_path: Path) -> None:
    extra = message(8, 34, [(1, 2, 0x84), (5, 4, 0x86)], struct.pack("<HI", 1, 0x10000000))
    p = tmp_path / "local.fit"
    p.write_bytes(frame(activity_data(omit=34, extra=extra)))
    import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        facts = storage.get_activity_facts(
            c, c.execute("SELECT activity_id FROM activities").fetchone()[0]
        )
        defs = facts["field_definitions"]
        for m in facts["basic_json"]["messages"]:
            for k, v in m["fields"]["standard"].items():
                if defs[k]["name"] == "local_timestamp":
                    assert v == 0x10000000 and defs[k]["value_form"] == "raw"


MUTATIONS = [
    "timestamp",
    "timestamp-removed",
    "timestamp-duplicate",
    "timestamp-form",
    "timestamp-unit",
    "timestamp-name",
    "message-name",
    "definition-name",
    "both-names",
    "known-field-name",
    "unknown-name",
    "definition-collision",
    "field-number",
    "component-target",
    "missing-unit",
    "invalid-unit",
    "relative-unit",
    "local-evidence",
]


@pytest.mark.parametrize("case", MUTATIONS)
def test_repository_single_fact_consistency(tmp_path: Path, case: str) -> None:
    content = frame(activity_data(extra=message(8, 65000, [(0, 1, 2)], b"\0")))
    p = tmp_path / "good.fit"
    p.write_bytes(content)
    ident = import_fit_file(tmp_path, p)
    with storage.open_database(tmp_path / "states/data.db") as c:
        baseline = ProfileFitDecoder().decode(content)
        storage.import_activity(c, activity_id="b" * 64, fit_path="base.fit", parsed=baseline)
        with c:
            c.execute("INSERT INTO activties_report VALUES(?,NULL,?)", (ident, "全文"))
            c.execute(
                "INSERT INTO weekly_report(run_time_utc,summary) VALUES(?,?)",
                ("2030-01-01T00:00:00.000000Z", "周全文"),
            )
            c.execute(
                "INSERT INTO config VALUES(?,?,?)",
                ("synthetic", "{}", "2030-01-01T00:00:00.000000Z"),
            )
        v = copy.deepcopy(baseline)
        defs = v.sensors["field_definitions"]
        metrics = v.records[0].metrics
        ts = next(k for k in metrics["standard"] if defs[k]["field_number"] == 253)
        hr = next(k for k in metrics["standard"] if defs[k]["name"] == "heart_rate")
        session = v.summary["messages"][0]
        if case == "timestamp":
            metrics["standard"][ts] += 1
        elif case == "timestamp-removed":
            metrics["standard"].pop(ts)
        elif case == "timestamp-duplicate":
            defs["f999"] = dict(defs[ts])
            metrics["standard"]["f999"] = metrics["standard"][ts]
        elif case == "timestamp-form":
            defs[ts]["value_form"] = "physical"
        elif case == "timestamp-unit":
            defs[ts]["unit"] = "ms"
        elif case == "timestamp-name":
            defs[ts]["name"] = "heart_rate"
        elif case == "message-name":
            session["message_name"] = "record"
        elif case == "definition-name":
            defs[hr]["message_name"] = "session"
        elif case == "both-names":
            session["message_name"] = "invented"
            for d in defs.values():
                if d["message_number"] == 18:
                    d["message_name"] = "invented"
        elif case == "known-field-name":
            defs[hr]["name"] = "power"
        elif case == "unknown-name":
            for d in defs.values():
                if d["message_number"] == 65000:
                    d["message_name"] = "record"
        elif case == "definition-collision":
            for d in defs.values():
                if d["message_number"] == 18:
                    d["definition_index"] = defs[ts]["definition_index"]
        elif case == "field-number":
            defs[hr]["field_number"] = 7
        elif case == "component-target":
            expanded = next(d for d in defs.values() if d["origin"] == "expanded")
            expanded.update(field_number=7, name="power", unit="watts")
        else:
            evidence = metrics["time_evidence"]
            metrics["standard"].pop(ts)
            if case == "missing-unit":
                evidence.update(kind="missing", raw=None, unit="s")
            elif case == "invalid-unit":
                metrics["standard"][ts] = None
                evidence.update(kind="invalid", raw=None, unit=None)
            elif case == "relative-unit":
                metrics["standard"][ts] = 10
                evidence.update(kind="relative", raw=10, unit="ms")
            else:
                metrics["standard"][ts] = T
                evidence.update(kind="local", raw=T, unit="s")
            v = replace(v, records=(replace(v.records[0], timestamp_utc=None), *v.records[1:]))
        before = dump(c)
        with pytest.raises(ValueError):
            storage.import_activity(c, activity_id="c" * 64, fit_path="mutated.fit", parsed=v)
        assert dump(c) == before


BAD_PATHS = [
    ("service.py", "def run(): return 1"),
    ("other/service.py", "x=1"),
    ("tools/build/probe.sh", "exit 0"),
    ("tools/probe.sh", "#!/bin/sh\nexit 0"),
    ("tools/probe", "#!/bin/sh\nexit 0"),
    ("skills/fit-store/run.sh", "exit 0"),
    ("skills/_shared/scripts/probe.py", "import sys\nsys.path = ['x'] + sys.path"),
    ("skills/_shared/scripts/probe.py", "import sys as s\ns.path += ['x']"),
    ("skills/_shared/scripts/probe.py", "from sys import path as p\np.append('x')"),
    ("skills/_shared/scripts/probe.py", "import sys\np = sys.path\np[:] = ['x']"),
    ("skills/_shared/scripts/probe.py", "import sys\ndel sys.path[0]"),
    ("skills/_shared/scripts/probe.py", "import sys\nsetattr(sys, 'path', [])"),
]


@pytest.mark.parametrize("path,content", BAD_PATHS)
def test_architecture_forbidden_mutations(tmp_path: Path, path: str, content: str) -> None:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/contracts.schema.json").write_text("{}")
    check_layout(tmp_path)
    p = tmp_path / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    with pytest.raises(ValueError):
        check_layout(tmp_path)


def test_architecture_readonly_paths_and_approved_resources(tmp_path: Path) -> None:
    files = {
        "schemas/contracts.schema.json": "{}",
        "schemas/__init__.py": "",
        "tools/README.md": "```sh\necho example\n```",
        "tests/test_layout.py": "def test_layout(): pass",
        "frontend/vite.config.ts": "export default {}",
        "skills/_shared/scripts/probe.py": "import sys\np = sys.path\nprint(p[0], sys.path.copy())",
    }
    for path, text in files.items():
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    check_layout(tmp_path)
