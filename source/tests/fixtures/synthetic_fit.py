"""Deterministic, privacy-safe FIT fixtures built without personal source data."""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fitdecode.utils import compute_crc

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
SYNTHETIC_START = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)

_UINT8 = 0x02
_SINT8 = 0x01
_UINT16 = 0x84
_SINT32 = 0x85
_UINT32 = 0x86
_STRING = 0x07
_BYTE = 0x0D
_ENUM = 0x00

_SPORTS = {
    "Running.fit": (1, 0),
    "Bouldering.fit": (31, 69),
    "Indoor Climbing.fit": (31, 68),
    "Strength.fit": (10, 20),
    "Cycling.fit": (2, 7),
    "Hiking.fit": (17, 0),
}


def _fit_timestamp(value: datetime) -> int:
    return int((value - FIT_EPOCH).total_seconds())


def _text(value: str, size: int) -> bytes:
    encoded = value.encode("ascii")[: size - 1]
    return encoded + bytes(size - len(encoded))


def _definition(
    local_number: int,
    global_number: int,
    fields: tuple[tuple[int, int, int], ...],
    developer_fields: tuple[tuple[int, int, int], ...] = (),
) -> bytes:
    header = 0x40 | local_number | (0x20 if developer_fields else 0)
    result = (
        bytes((header, 0, 0))
        + struct.pack("<H", global_number)
        + bytes((len(fields),))
        + b"".join(bytes(field) for field in fields)
    )
    if developer_fields:
        result += bytes((len(developer_fields),)) + b"".join(
            bytes(field) for field in developer_fields
        )
    return result


def _data(local_number: int, payload: bytes) -> bytes:
    return bytes((local_number,)) + payload


def _developer_messages() -> list[bytes]:
    application_id = bytes(range(16))
    return [
        _definition(0, 207, ((1, 16, _BYTE), (3, 1, _UINT8))),
        _data(0, application_id + bytes((0,))),
        _definition(
            1,
            206,
            (
                (0, 1, _UINT8),
                (1, 1, _UINT8),
                (2, 1, _UINT8),
                (3, 16, _STRING),
                (8, 8, _STRING),
                (14, 2, _UINT16),
            ),
        ),
        _data(
            1,
            bytes((0, 4, _UINT16))
            + _text("dr_gct", 16)
            + _text("ms", 8)
            + struct.pack("<H", 20),
        ),
    ]


def _record_messages(start: datetime, *, developer: bool) -> list[bytes]:
    fields = (
        (253, 4, _UINT32),
        (3, 1, _UINT8),
        (6, 2, _UINT16),
        (5, 4, _UINT32),
        (4, 1, _UINT8),
        (7, 2, _UINT16),
        (13, 1, _SINT8),
    )
    developer_fields = ((4, 2, 0),) if developer else ()
    messages = [_definition(2, 20, fields, developer_fields)]
    start_raw = _fit_timestamp(start)
    for index in range(200):
        standard = struct.pack(
            "<IBHIBHb",
            start_raw + round(index * 4_321 / 199),
            111 + index % 10,
            index * 10,
            index * 10_000,
            80 + index % 5,
            180 + index % 20,
            20,
        )
        developer_value = struct.pack("<H", 293 + index % 7) if developer else b""
        messages.append(_data(2, standard + developer_value))
    return messages


def _lap_message(start: datetime, end: datetime) -> list[bytes]:
    return [
        _definition(
            3,
            19,
            (
                (2, 4, _UINT32),
                (253, 4, _UINT32),
                (7, 4, _UINT32),
                (8, 4, _UINT32),
                (9, 4, _UINT32),
            ),
        ),
        _data(
            3,
            struct.pack(
                "<IIIII",
                _fit_timestamp(start),
                _fit_timestamp(end),
                600_000,
                580_000,
                500_000,
            ),
        ),
    ]


def _climbing_messages(start: datetime, *, indoor: bool) -> list[bytes]:
    fields = (
        (0, 1, _ENUM),
        (1, 4, _UINT32),
        (2, 4, _UINT32),
        (9, 4, _UINT32),
        (13, 2, _UINT16),
        (70, 2, _UINT16),
        (71, 1, _UINT8),
        (72, 1, _UINT8),
        (73, 1, _UINT8),
        (253, 4, _UINT32),
    )
    result = [_definition(4, 312, fields)]
    grades = (3, 4) if indoor else (2, 8)
    for index, grade in enumerate(grades):
        split_start = _fit_timestamp(start) + index * 120
        result.append(
            _data(
                4,
                struct.pack(
                    "<BIIIHHBBB I",
                    9,
                    60_000,
                    55_000,
                    split_start,
                    7 - index * 2,
                    grade,
                    3 if index == 0 else 2,
                    1 + index,
                    1 if indoor or index == 0 else 0,
                    split_start + 60,
                ),
            )
        )
    return result


def _strength_messages(start: datetime) -> list[bytes]:
    result = [
        _definition(
            4,
            27,
            (
                (7, 1, _ENUM),
                (8, 32, _STRING),
                (10, 2, _UINT16),
                (11, 2, _UINT16),
                (254, 2, _UINT16),
            ),
        ),
        _data(
            4,
            bytes((0,))
            + _text("fixture movement alpha", 32)
            + struct.pack("<HHH", 21, 0, 0),
        ),
        _definition(
            5,
            225,
            (
                (0, 4, _UINT32),
                (3, 2, _UINT16),
                (4, 2, _UINT16),
                (5, 1, _UINT8),
                (6, 4, _UINT32),
                (10, 2, _UINT16),
                (11, 2, _UINT16),
                (253, 4, _UINT32),
            ),
        ),
    ]
    start_raw = _fit_timestamp(start)
    result.append(
        _data(
            5,
            struct.pack(
                "<IHHBIHHI", 28_000, 5, 276, 1, start_raw, 0, 0, start_raw + 28
            ),
        )
    )
    result.append(
        _data(
            5,
            struct.pack(
                "<IHHBIHHI", 12_000, 0, 0, 1, start_raw + 28, 1, 0, start_raw + 40
            ),
        )
    )
    result.append(
        _data(
            5,
            struct.pack(
                "<IHHBIHHI", 15_000, 0, 0, 0, start_raw + 40, 2, 0, start_raw + 55
            ),
        )
    )
    result.extend(
        [
            _definition(
                12,
                264,
                ((0, 1, _ENUM), (1, 2, _UINT16), (2, 24, _STRING), (254, 2, _UINT16)),
            ),
            _data(
                12,
                bytes((21,))
                + struct.pack("<H", 0)
                + _text("fixture movement alpha", 24)
                + struct.pack("<H", 0),
            ),
        ]
    )
    return result


def _hiking_messages(start: datetime) -> list[bytes]:
    result = [
        _definition(
            4,
            32,
            (
                (1, 4, _UINT32),
                (2, 4, _SINT32),
                (3, 4, _SINT32),
                (4, 4, _UINT32),
                (5, 1, _ENUM),
                (6, 16, _STRING),
                (254, 2, _UINT16),
            ),
        )
    ]
    start_raw = _fit_timestamp(start)
    for index in range(3):
        latitude = int((0.5 + index * 0.01) * (2**31) / 180)
        longitude = int((0.75 + index * 0.01) * (2**31) / 180)
        result.append(
            _data(
                4,
                struct.pack(
                    "<IiiIB16sH",
                    start_raw + index * 120,
                    latitude,
                    longitude,
                    index * 10_000,
                    0,
                    _text(f"point-{index}", 16),
                    index,
                ),
            )
        )
    return result


def _device_and_unknown_messages(end: datetime) -> list[bytes]:
    timestamp = _fit_timestamp(end)
    return [
        _definition(
            6,
            23,
            (
                (2, 2, _UINT16),
                (3, 4, _UINT32),
                (4, 2, _UINT16),
                (253, 4, _UINT32),
            ),
        ),
        _data(6, struct.pack("<HIHI", 1, 424_242, 1234, timestamp)),
        _definition(5, 128, ((253, 4, _UINT32),)),
        _data(5, struct.pack("<I", timestamp)),
        _definition(10, 162, ((1, 4, _UINT32), (253, 4, _UINT32))),
        _data(10, struct.pack("<II", timestamp - 1, timestamp)),
        _definition(7, 534, ((253, 4, _UINT32), (2, 2, _UINT16))),
        _data(7, struct.pack("<IH", timestamp, 42)),
    ]


def _session_and_activity_messages(
    start: datetime, end: datetime, sport: int, sub_sport: int, *, running: bool
) -> list[bytes]:
    if running:
        elapsed_raw = 4_321_000
        timer_raw = 4_200_000
        distance_raw = 1_234_500
        calories = 678
    else:
        elapsed_raw = 600_000
        timer_raw = 580_000
        distance_raw = 500_000
        calories = 300
    return [
        _definition(
            8,
            18,
            (
                (2, 4, _UINT32),
                (5, 1, _ENUM),
                (6, 1, _ENUM),
                (253, 4, _UINT32),
                (7, 4, _UINT32),
                (8, 4, _UINT32),
                (9, 4, _UINT32),
                (11, 2, _UINT16),
            ),
        ),
        _data(
            8,
            struct.pack(
                "<IBBIIIIH",
                _fit_timestamp(start),
                sport,
                sub_sport,
                _fit_timestamp(end),
                elapsed_raw,
                timer_raw,
                distance_raw,
                calories,
            ),
        ),
        _definition(9, 34, ((253, 4, _UINT32), (1, 2, _UINT16), (2, 1, _ENUM))),
        _data(9, struct.pack("<IHB", _fit_timestamp(end), 1, 0)),
    ]


def build_synthetic_fit(name: str) -> bytes:
    """Build one deterministic activity FIT selected from the public fixture catalog."""
    try:
        sport, sub_sport = _SPORTS[name]
    except KeyError as exc:
        raise ValueError(f"unknown_synthetic_fit:{name}") from exc
    start = SYNTHETIC_START
    running = name == "Running.fit"
    end = start + timedelta(seconds=4_321 if running else 600)
    body: list[bytes] = []
    if running:
        body.extend(_developer_messages())
    terminal_messages = _session_and_activity_messages(
        start, end, sport, sub_sport, running=running
    )
    body.extend(terminal_messages[:2])
    body.extend(_record_messages(start, developer=running))
    body.extend(_lap_message(start, end))
    if name in {"Bouldering.fit", "Indoor Climbing.fit"}:
        body.extend(_climbing_messages(start, indoor=name == "Indoor Climbing.fit"))
        if name == "Indoor Climbing.fit":
            body.extend(
                [
                    _definition(
                        11,
                        313,
                        ((0, 1, _ENUM), (3, 2, _UINT16), (4, 4, _UINT32)),
                    ),
                    _data(11, struct.pack("<BHI", 9, 2, 120_000)),
                ]
            )
    elif name == "Strength.fit":
        body.extend(_strength_messages(start))
    elif name == "Hiking.fit":
        body.extend(_hiking_messages(start))
    body.extend(_device_and_unknown_messages(end))
    body.extend(terminal_messages[2:])
    data = b"".join(body)
    header = bytearray(struct.pack("<BBHI4s", 14, 0x10, 2100, len(data), b".FIT"))
    header += struct.pack("<H", compute_crc(header))
    result = bytes(header) + data
    return result + struct.pack("<H", compute_crc(result))


SYNTHETIC_FIT_NAMES = tuple(_SPORTS)
SYNTHETIC_FITS = {name: build_synthetic_fit(name) for name in SYNTHETIC_FIT_NAMES}
SYNTHETIC_FIT_SHA256 = {
    name: sha256(content).hexdigest() for name, content in SYNTHETIC_FITS.items()
}
