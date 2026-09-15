"""Anonymous CRC-valid binary FITs; no private source files or copied metrics."""

from __future__ import annotations

import struct
from typing import Any

from fitdecode.utils import compute_crc

BASE = 1_100_000_000


def message(number: int, fields: list[tuple[int, int, Any]]) -> bytes:
    definitions = bytearray()
    values = bytearray()
    formats = {0: "B", 2: "B", 0x84: "H", 0x85: "i", 0x86: "I"}
    for field, kind, value in fields:
        if kind == 7:
            packed = value.encode() + b"\0"
        else:
            parts = value if isinstance(value, (list, tuple)) else [value]
            packed = struct.pack("<" + formats[kind] * len(parts), *parts)
        definitions.extend([field, len(packed), kind])
        values.extend(packed)
    return (
        bytes([0x40, 0, 0])
        + struct.pack("<H", number)
        + bytes([len(fields)])
        + definitions
        + bytes([0])
        + values
    )


def file_bytes(messages: list[bytes]) -> bytes:
    body = message(0, [(0, 0, 4), (3, 0x86, 87654321)]) + b"".join(messages)
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(body), b".FIT")
    header += struct.pack("<H", compute_crc(header))
    return header + body + struct.pack("<H", compute_crc(header + body))


def session(
    end: int, *, start: int = 0, sport: int = 1, timer: int | None = None
) -> bytes:
    fields = [
        (253, 0x86, BASE + end),
        (2, 0x86, BASE + start),
        (5, 0, sport),
        (7, 0x86, (end - start) * 1000),
    ]
    if timer is not None:
        fields.append((8, 0x86, timer * 1000))
    return message(18, fields)


def record(t: int, distance: float, hr: int, *, extra=()) -> bytes:
    return message(
        20,
        [
            (253, 0x86, BASE + t),
            (5, 0x86, round(distance * 100)),
            (3, 2, hr),
            *extra,
        ],
    )


def lap(start: int, end: int, intensity: int) -> bytes:
    return message(
        19,
        [
            (2, 0x86, BASE + start),
            (253, 0x86, BASE + end),
            (7, 0x86, (end - start) * 1000),
            (23, 0, intensity),
        ],
    )


def event(t: int, event_type: int) -> bytes:
    return message(21, [(253, 0x86, BASE + t), (0, 0, 0), (1, 0, event_type)])


def zones(ref_mesg: int, durations: list[int], *, index: int = 0) -> bytes:
    return message(
        216,
        [
            (0, 0x84, ref_mesg),
            (1, 0x84, index),
            (2, 0x86, [v * 1000 for v in durations]),
        ],
    )


def regular_fit(duration=360, *, sport=1, laps=(), extras=()) -> bytes:
    return file_bytes(
        [record(t, t * 3, 123) for t in range(0, duration + 1, 10)]
        + list(laps)
        + list(extras)
        + [session(duration, sport=sport, timer=duration)]
    )
