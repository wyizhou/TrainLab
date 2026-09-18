from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from trainlab.contracts.fit_profile import profile
from trainlab.contracts.json_validation import schema_document
from trainlab.contracts.time import format_utc
from trainlab.fit.models import ParsedActivity, ParsedRecord
from trainlab.fit.profile_fields import FieldMapper, physical
from trainlab.fit.wire import WireMessage, decode_wire

EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
BASIC_MESSAGES = frozenset(schema_document()["x-message-containers"]["basic_json"])
SEGMENT_MESSAGES = frozenset(schema_document()["x-message-containers"]["segments_json"])


class FitDecoder(Protocol):
    def decode(self, fit_bytes: bytes) -> ParsedActivity: ...


def timestamp(raw: Any) -> datetime | None:
    if type(raw) not in (int, float) or raw < 0x10000000:
        return None
    return EPOCH + timedelta(seconds=raw)


def time_evidence(message: WireMessage) -> tuple[datetime | None, dict[str, Any]]:
    fields = {f.number: f for f in message.fields}
    if 253 not in fields:
        return None, {"kind": "missing", "raw": None, "unit": None}
    raw = fields[253].raw
    if raw is None:
        return None, {"kind": "invalid", "raw": None, "unit": "s"}
    if type(raw) not in (int, float):
        raise ValueError("invalid timestamp type")
    stamp = timestamp(raw)
    return stamp, {"kind": "absolute" if stamp is not None else "relative", "raw": raw, "unit": "s"}


def _required(messages: list[WireMessage]) -> None:
    if not messages or messages[0].number != 0:
        raise ValueError("Activity must start with file_id")
    by_number: dict[int, list[dict[int, Any]]] = {}
    for m in messages:
        fields = {f.number: f for f in m.fields}
        if m.number in (18, 19):
            for number in (253, 2, 7, 8):
                if number not in fields or fields[number].base_type != 6:
                    raise ValueError("summary missing required time field")
                if fields[number].raw is not None and type(fields[number].raw) is not int:
                    raise ValueError("invalid summary time field")
        if m.number == 20 and not (set(fields) - {253} or m.developers):
            raise ValueError("record missing sampling fields")
        if m.number == 34 and not fields:
            raise ValueError("empty activity message")
        by_number.setdefault(m.number, []).append({f.number: f.raw for f in m.fields})
        if m.number == 0:
            values = by_number[0][-1]
            if values.get(0) != 4 or values.get(1) is None:
                raise ValueError("not a complete Activity file_id")
    if any(n not in by_number for n in (18, 19, 20, 34)):
        raise ValueError("Activity missing required session/lap/record/activity")
    if len(by_number[19]) < len(by_number[18]):
        raise ValueError("Activity missing session laps")
    for session in by_number[18]:
        if type(session.get(26)) is int and session[26] < 1:
            raise ValueError("session has no laps")
        if type(session.get(26)) is int and session[26] > len(by_number[19]):
            raise ValueError("missing declared laps")
    for chain in {m.chain for m in messages}:
        chain_messages = [m for m in messages if m.chain == chain]
        if chain_messages[0].number != 0:
            raise ValueError("chained FIT missing file_id")
        sessions = sum(m.number == 18 for m in chain_messages)
        numbers = [m.number for m in chain_messages]
        if numbers.count(0) != 1:
            raise ValueError("duplicate file_id")
        if any(n in numbers for n in (18, 19, 20, 34)):
            if any(n not in numbers for n in (18, 19, 20, 34)) or numbers.count(34) != 1:
                raise ValueError("incomplete Activity chain")
        elif not any(n in numbers for n in (132, 78)):
            raise ValueError("empty non-activity chain")
        for m in chain_messages:
            if m.number == 34:
                count = next((f.raw for f in m.fields if f.number == 1), None)
                if type(count) is int and count != sessions:
                    raise ValueError("activity session count mismatch")


class ProfileFitDecoder:
    def decode(self, fit_bytes: bytes) -> ParsedActivity:
        try:
            messages = decode_wire(fit_bytes)
            _required(messages)
            mapper = FieldMapper()
            basic: list[dict[str, Any]] = []
            summary: list[dict[str, Any]] = []
            segments: list[dict[str, Any]] = []
            sensors: list[dict[str, Any]] = []
            records = []
            sports: list[str | None] = []
            sub_sports: list[str | None] = []
            starts: list[datetime | None] = []
            ends: list[datetime | None] = []
            for m in messages:
                fields = mapper.fields(m)
                p = profile(m.number)
                message = {
                    "message_index": m.index,
                    "chain_index": m.chain,
                    "message_number": m.number,
                    "message_name": p["name"],
                    "fields": fields,
                }
                if m.number == 20:
                    stamp, evidence = time_evidence(m)
                    records.append(ParsedRecord(stamp, {**fields, "time_evidence": evidence}))
                elif m.number == 18:
                    summary.append(message)
                    raw = {f.number: f.raw for f in m.fields}
                    values = {n: physical(v, p["fields"].get(n, {})) for n, v in raw.items()}
                    sport = values.get(5)
                    sub = values.get(6)
                    sports.append(sport if isinstance(sport, str) else None)
                    sub_sports.append(sub if isinstance(sub, str) else None)
                    start = timestamp(raw.get(2))
                    elapsed = values.get(7)
                    end = (
                        start + timedelta(seconds=elapsed)
                        if start is not None and isinstance(elapsed, float | int) and elapsed >= 0
                        else None
                    )
                    starts.append(start)
                    ends.append(end)
                elif m.number in SEGMENT_MESSAGES:
                    segments.append(message)
                elif m.number in BASIC_MESSAGES:
                    basic.append(message)
                else:
                    sensors.append(message)
            sport = sports[0] if sports and len(set(sports)) == 1 else None
            sub = sub_sports[0] if sub_sports and len(set(sub_sports)) == 1 else None
            start = (
                min(s for s in starts if s is not None)
                if starts and all(s is not None for s in starts)
                else None
            )
            end = (
                max(e for e in ends if e is not None)
                if ends and all(e is not None for e in ends)
                else None
            )
            return ParsedActivity(
                sport,
                sub,
                start,
                end,
                {
                    "sport": sport,
                    "sub_sport": sub,
                    "start_time_utc": None if start is None else format_utc(start),
                    "end_time_utc": None if end is None else format_utc(end),
                    "messages": basic,
                },
                {"messages": summary},
                {"items": segments},
                {
                    "field_definitions": mapper.definitions,
                    "developer_sources": mapper.sources,
                    "messages": sensors,
                },
                tuple(records),
            )
        except (IndexError, KeyError, TypeError, OverflowError) as exc:
            raise ValueError("invalid FIT structure or Profile value") from exc
