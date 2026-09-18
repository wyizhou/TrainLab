from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.fit.fit_bytes import T, activity_data, definition, description, developer, frame, message
from trainlab.fit import import_fit_file


def decode(data: bytes) -> Any:
    from trainlab.fit.parser import ProfileFitDecoder

    return ProfileFitDecoder().decode(data)


def named(parsed: Any, fields: dict[str, Any]) -> dict[str, Any]:
    defs = parsed.sensors["field_definitions"]
    return {defs[key]["name"]: value for key, value in fields.items()}


@pytest.mark.parametrize("header_size,zero", [(12, False), (14, False), (14, True), (16, False)])
def test_protocol_headers(header_size: int, zero: bool) -> None:
    data = frame(activity_data(), header_size, zero)
    parsed = decode(data)
    assert len(parsed.records) == 4
    assert parsed.sport == "running"
    assert (parsed.end_time_utc - parsed.start_time_utc).total_seconds() == 19.125
    assert named(parsed, parsed.records[0].metrics["standard"])["heart_rate"] == 0
    assert named(parsed, parsed.records[1].metrics["standard"])["speed"] == 2
    assert named(parsed, parsed.records[2].metrics["standard"])["heart_rate"] is None
    assert "serial_number" not in {v["name"] for v in parsed.sensors["field_definitions"].values()}


def test_sdk_crosscheck_normal() -> None:
    data = frame(activity_data())
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read(
        merge_heart_rates=False
    )
    assert not errors
    parsed = decode(data)
    assert len(parsed.records) == len(messages["record_mesgs"])
    assert (
        named(parsed, parsed.records[1].metrics["standard"])["speed"]
        == messages["record_mesgs"][1]["speed"]
    )
    assert (parsed.end_time_utc - parsed.start_time_utc).total_seconds() == messages[
        "session_mesgs"
    ][0]["total_elapsed_time"]


@pytest.mark.parametrize(
    "case",
    [
        "crc",
        "length",
        "undefined",
        "tail",
        "zero",
        "file_id",
        "session",
        "lap",
        "activity",
        "bad-field-size",
        "bad-base",
        "bad-architecture",
    ],
)
def test_bad_protocol_no_database(tmp_path: Path, case: str) -> None:
    good = frame(activity_data())
    data = good
    if case == "crc":
        data = good[:-1] + bytes([good[-1] ^ 1])
    if case == "length":
        data = good[:-5]
    if case == "undefined":
        data = frame(b"\x0f")
    if case == "tail":
        data = good + good[:-1]
    if case == "zero":
        data = frame(activity_data(count=0))
    if case in {"file_id", "session", "lap", "activity"}:
        data = frame(
            activity_data(omit={"file_id": 0, "session": 18, "lap": 19, "activity": 34}[case])
        )
    if case == "bad-field-size":
        data = frame(activity_data(extra=definition(9, 20, [(5, 3, 0x86)]) + b"\x09\x00\x00\x00"))
    if case == "bad-base":
        data = frame(activity_data(extra=definition(9, 20, [(5, 1, 31)]) + b"\x09\x00"))
    if case == "bad-architecture":
        data = frame(activity_data(extra=b"\x49\x00\x02\x14\x00\x00"))
    p = tmp_path / "input.fit"
    p.write_bytes(data)
    with pytest.raises(ValueError):
        import_fit_file(tmp_path, p)
    assert not (tmp_path / "states/data.db").exists()


def test_chain_order_and_multi_sport() -> None:
    p = decode(frame(activity_data()) + frame(activity_data(sport=2, start=T + 100)))
    assert len(p.records) == 8
    assert p.sport is None
    assert len(p.summary["messages"]) == 2
    assert [m["chain_index"] for m in p.summary["messages"]] == [0, 1]
    assert len({f["definition_index"] for f in p.sensors["field_definitions"].values()}) >= 10


def test_relative_invalid_and_missing_time() -> None:
    p = decode(frame(activity_data(start=123)))
    assert p.start_time_utc is None and p.end_time_utc is None
    assert all(
        r.timestamp_utc is None and r.metrics["time_evidence"]["kind"] == "relative"
        for r in p.records
    )
    extra = message(1, 20, [(253, 4, 0x86), (3, 1, 2)], struct.pack("<IB", 0xFFFFFFFF, 0))
    extra += message(1, 20, [(3, 1, 2)], b"\x00")
    p = decode(frame(activity_data(extra=extra)))
    assert [r.metrics["time_evidence"]["kind"] for r in p.records[-2:]] == ["invalid", "missing"]


def test_developer_same_name_redefinition_and_invalid() -> None:
    extra = developer(0) + developer(1)
    fields = [(253, 4, 0x86), (3, 1, 2)]
    extra += message(
        1, 20, fields, struct.pack("<IBHH", T + 30, 0, 42, 65535), [(0, 2, 0), (0, 2, 1)]
    )
    extra += description(0, scale=2)
    extra += bytes([1]) + struct.pack("<IBHH", T + 31, 1, 42, 0)
    p = decode(frame(activity_data(extra=extra)))
    first, second = (r.metrics["developer"] for r in p.records[-2:])
    assert list(first.values()) == [42, None]
    assert list(second.values()) == [21, 0]
    first_keys = list(first)
    assert first_keys[0] != next(iter(second))
    defs = p.sensors["field_definitions"]
    assert defs[first_keys[0]]["source_ref"] != defs[first_keys[1]]["source_ref"]


def test_unknown_big_integer_byte_array_and_native_segments() -> None:
    extra = message(
        8,
        60000,
        [(0, 8, 0x8F), (1, 3, 13), (2, 4, 0x84)],
        struct.pack("<Q3sHH", 9007199254740993, b"\x01\x02\x03", 0, 65535),
    )
    for n in [101, 225, 312, 313]:
        extra += message(8, n, [(250, 1, 2)], b"\x00")
    p = decode(frame(activity_data(extra=extra)))
    unknown = next(m for m in p.sensors["messages"] if m["message_number"] == 60000)
    assert list(unknown["fields"]["standard"].values()) == [
        {"integer": "9007199254740993"},
        {"bytes_hex": "010203"},
        [0, None],
    ]
    assert [m["message_number"] for m in p.segments["items"]] == [19, 101, 225, 312, 313]


def test_compressed_timestamp_and_components_do_not_overwrite() -> None:
    extra = definition(1, 20, [(253, 4, 0x86), (8, 3, 13), (73, 4, 0x86)])
    packed = (200 | (100 << 12)).to_bytes(3, "little")
    extra += bytes([1]) + struct.pack("<I", T + 31) + packed + struct.pack("<I", 9000)
    extra += bytes([0x80 | (1 << 5) | 1]) + packed + struct.pack("<I", 8000)
    p = decode(frame(activity_data(extra=extra)))
    assert (p.records[-1].timestamp_utc - p.records[-2].timestamp_utc).total_seconds() == 2
    defs = p.sensors["field_definitions"]
    fs = p.records[-2].metrics["standard"]
    speeds = [(defs[k]["origin"], v) for k, v in fs.items() if defs[k]["name"] == "enhanced_speed"]
    assert ("direct", 9) in speeds and ("expanded", 2) in speeds
    assert all(defs[k]["component_of"] in defs for k in fs if defs[k]["origin"] == "expanded")
