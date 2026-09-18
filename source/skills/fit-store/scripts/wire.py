from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

from garmin_fit_sdk import CrcCalculator
from garmin_fit_sdk.fit import BASE_TYPE_DEFINITIONS, BASE_TYPE_TO_FIELD_TYPE


@dataclass(frozen=True)
class RawField:
    number: int
    base_type: int
    raw: Any
    encoded: bytes


@dataclass(frozen=True)
class WireMessage:
    index: int
    chain: int
    definition: int
    number: int
    fields: tuple[RawField, ...]
    developers: tuple[tuple[int, int, bytes], ...]
    endian: str


def raw_value(data: bytes, base_type: int, endian: str) -> Any:
    base = BASE_TYPE_DEFINITIONS.get(base_type)
    if base is None or not data or len(data) % base["size"]:
        raise ValueError("invalid FIT field type/size")
    if base_type == 7:
        return data.split(b"\x00", 1)[0].decode("utf-8", errors="strict") or None
    if base_type == 13 and len(data) > 1:
        return None if all(v == 255 for v in data) else list(data)
    values = []
    size = base["size"]
    for i in range(0, len(data), size):
        chunk = data[i : i + size]
        value = struct.unpack(endian + base["type_code"], chunk)[0]
        invalid = (
            int.from_bytes(chunk, "little" if endian == "<" else "big") == base["invalid"]
            if base_type in (8, 9)
            else value == base["invalid"]
        )
        if invalid:
            value = None
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite FIT field")
        values.append(value)
    return values[0] if len(values) == 1 else values


def base_name(base_type: int) -> str:
    return str(BASE_TYPE_TO_FIELD_TYPE[base_type])


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        end = self.pos + size
        if end > len(self.data):
            raise ValueError("truncated FIT data")
        value = self.data[self.pos : end]
        self.pos = end
        return value

    def byte(self) -> int:
        return self.take(1)[0]


def decode_wire(content: bytes) -> list[WireMessage]:
    if not content:
        raise ValueError("empty FIT")
    result: list[WireMessage] = []
    file = Reader(content)
    chain = 0
    definition_index = 0
    while file.pos < len(content):
        header_size = content[file.pos]
        if header_size != 12 and header_size < 14:
            raise ValueError("invalid FIT header length")
        header = file.take(header_size)
        if header[8:12] != b".FIT" or header[1] >> 4 not in (1, 2):
            raise ValueError("invalid FIT header/version")
        if (
            header_size >= 14
            and header[12:14] != b"\x00\x00"
            and CrcCalculator.calculate_crc(header, 0, 14) != 0
        ):
            raise ValueError("FIT header CRC mismatch")
        size = int.from_bytes(header[4:8], "little")
        data = file.take(size)
        crc = file.take(2)
        if CrcCalculator.calculate_crc(header + data + crc, 0, len(header) + len(data) + 2) != 0:
            raise ValueError("FIT file CRC mismatch")
        stream = Reader(data)
        definitions: dict[int, Any] = {}
        last_timestamp: int | None = None
        while stream.pos < len(data):
            h = stream.byte()
            compressed = bool(h & 0x80)
            local = (h >> 5) & 3 if compressed else h & 15
            if not compressed and h & 0x40:
                if h & 0x10 or stream.byte() != 0:
                    raise ValueError("invalid FIT definition header")
                arch = stream.byte()
                if arch not in (0, 1):
                    raise ValueError("invalid FIT architecture")
                endian = "<" if arch == 0 else ">"
                number = struct.unpack(endian + "H", stream.take(2))[0]
                fields = []
                seen = set()
                for _ in range(stream.byte()):
                    num, length, type_id = stream.take(3)
                    base_type = type_id & 31
                    base = BASE_TYPE_DEFINITIONS.get(base_type)
                    if (
                        num == 255
                        or base is None
                        or type_id != (base_type | base["endian_flag"])
                        or length == 0
                        or length % base["size"]
                        or num in seen
                    ):
                        raise ValueError("invalid FIT field definition")
                    seen.add(num)
                    fields.append((num, length, base_type))
                developers = []
                if h & 0x20:
                    seen_dev = set()
                    for _ in range(stream.byte()):
                        num, length, index = stream.take(3)
                        if num == 255 or length == 0 or (index, num) in seen_dev:
                            raise ValueError("invalid developer definition")
                        seen_dev.add((index, num))
                        developers.append((num, length, index))
                definitions[local] = (definition_index, number, fields, developers, endian)
                definition_index += 1
                continue
            if not compressed and h & 0x30:
                raise ValueError("invalid FIT message header")
            if local not in definitions:
                raise ValueError("undefined FIT local message")
            idx, number, fields, developers, endian = definitions[local]
            raws = []
            if compressed:
                if last_timestamp is None or any(
                    num == 253 and (num, length, base) != (253, 4, 6)
                    for num, length, base in fields
                ):
                    raise ValueError("compressed timestamp lacks valid reference")
                timestamp = (last_timestamp & ~31) + (h & 31)
                if timestamp < last_timestamp:
                    timestamp += 32
                if timestamp >= 0xFFFFFFFF:
                    raise ValueError("compressed timestamp overflow")
                raws.append(RawField(253, 6, timestamp, struct.pack(endian + "I", timestamp)))
            for num, length, base_type in fields:
                if compressed and num == 253:
                    continue
                encoded = stream.take(length)
                raws.append(
                    RawField(num, base_type, raw_value(encoded, base_type, endian), encoded)
                )
            for field in raws:
                if field.number == 253 and type(field.raw) is int:
                    last_timestamp = field.raw
            devs = tuple((index, num, stream.take(length)) for num, length, index in developers)
            result.append(WireMessage(len(result), chain, idx, number, tuple(raws), devs, endian))
        chain += 1
    return result
