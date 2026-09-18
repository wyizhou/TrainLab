"""Typed parsed FIT model used before database import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, Any]
type JsonArray = list[JsonValue]


@dataclass(frozen=True)
class ParsedRecord:
    timestamp_utc: datetime | None
    metrics: JsonObject


@dataclass(frozen=True)
class ParsedActivity:
    sport: str | None
    sub_sport: str | None
    start_time_utc: datetime | None
    end_time_utc: datetime | None
    basic: JsonObject
    summary: JsonObject
    segments: JsonObject
    sensors: JsonObject
    records: tuple[ParsedRecord, ...]
