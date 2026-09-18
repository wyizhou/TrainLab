from __future__ import annotations

import struct

T = 1262390400
Field = tuple[int, int, int]


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def frame(data: bytes, header_size: int = 14, zero_header_crc: bool = False) -> bytes:
    header = struct.pack("<BBHI4s", header_size, 0x20, 2140, len(data), b".FIT")
    if header_size >= 14:
        header += struct.pack("<H", 0 if zero_header_crc else crc16(header))
        header += bytes([1] * (header_size - 14))
    return header + data + struct.pack("<H", crc16(header + data))


def definition(
    local: int,
    number: int,
    fields: list[Field],
    developers: list[Field] | None = None,
    big: bool = False,
) -> bytes:
    return (
        bytes([0x40 | local | (0x20 if developers else 0), 0, int(big)])
        + struct.pack(">H" if big else "<H", number)
        + bytes([len(fields)])
        + b"".join(bytes(f) for f in fields)
        + (bytes([len(developers)]) + b"".join(bytes(f) for f in developers) if developers else b"")
    )


def message(
    local: int,
    number: int,
    fields: list[Field],
    payload: bytes,
    developers: list[Field] | None = None,
) -> bytes:
    return definition(local, number, fields, developers) + bytes([local]) + payload


def activity_data(
    count: int = 4, sport: int = 1, start: int = T, extra: bytes = b"", omit: int | None = None
) -> bytes:
    parts = {
        0: message(
            0, 0, [(0, 1, 0), (1, 2, 0x84), (3, 4, 0x8C)], struct.pack("<BHI", 4, 1, 123456)
        ),
        20: definition(1, 20, [(253, 4, 0x86), (3, 1, 2), (6, 2, 0x84)])
        + b"".join(
            bytes([1])
            + struct.pack(
                "<IBH",
                start + [0, 2, 2, 19][i % 4],
                [0, 120, 255, 130][i % 4],
                [0, 2000, 65535, 3500][i % 4],
            )
            for i in range(count)
        ),
        19: message(
            2,
            19,
            [(254, 2, 0x84), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (253, 4, 0x86)],
            struct.pack("<HIIII", 0, start, 19125, 15000, start + 999),
        ),
        18: message(
            3,
            18,
            [
                (2, 4, 0x86),
                (5, 1, 0),
                (6, 1, 0),
                (7, 4, 0x86),
                (8, 4, 0x86),
                (25, 2, 0x84),
                (26, 2, 0x84),
                (253, 4, 0x86),
            ],
            struct.pack("<IBBIIHHI", start, sport, 0, 19125, 15000, 0, 1, start + 999),
        ),
        34: message(
            4,
            34,
            [(1, 2, 0x84), (253, 4, 0x86), (5, 4, 0x86)],
            struct.pack("<HII", 1, start + 999, start + 999 + 28800),
        ),
    }
    return b"".join(value for key, value in parts.items() if key != omit) + extra


def developer(index: int, number: int = 0, name: str = "same", scale: int = 1) -> bytes:
    return message(5, 207, [(3, 1, 2), (2, 2, 0x84)], struct.pack("<BH", index, 1)) + description(
        index, number, name, scale
    )


def description(index: int, number: int = 0, name: str = "same", scale: int = 1) -> bytes:
    return message(
        6,
        206,
        [(0, 1, 2), (1, 1, 2), (2, 1, 2), (3, 16, 7), (6, 1, 2), (8, 8, 7)],
        struct.pack("<BBB16sB8s", index, number, 0x84, name.encode(), scale, b"ms"),
    )
