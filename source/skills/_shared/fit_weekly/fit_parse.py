"""Deterministic FIT-only projection; private fields never enter the projection.

Decoded samples stay in memory. SQLite receives only summaries, laps and bounded
segments. Missing timer boundaries never become inferred active time. No health
API, GPS-derived metrics, legacy database, model or Provider is used here.
"""

from __future__ import annotations

import bisect
import io
import json
import math
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitdecode
import jsonschema

from skills._shared.fit_weekly import storage

VERSION = "fit-summary-2"
LOCATION_VERSION = "fit-summary-2"
SCHEMAS = {"fit-summary-1": "fit_activity_v1", LOCATION_VERSION: "fit_activity_v2"}
MAX_GAP = 30.0
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_activity_v1.schema.json"
)
# Values returned by fitdecode are already profile-scaled; do not scale twice.
METRICS = {
    "heart_rate_bpm": (("heart_rate",), "bpm", False),
    "cadence_rpm": (("cadence",), "rpm", False),
    "power_w": (("power",), "W", False),
    "altitude_m": (("enhanced_altitude", "altitude"), "m", True),
    "temperature_c": (("temperature",), "C", True),
    "speed_m_s": (("enhanced_speed", "speed"), "m/s", False),
    "step_length_mm": (("step_length",), "mm", False),
    "vertical_oscillation_mm": (("vertical_oscillation",), "mm", False),
    "stance_time_ms": (("stance_time",), "ms", False),
    "vertical_ratio_percent": (("vertical_ratio",), "%", False),
}
SPORTS = {
    "running",
    "cycling",
    "swimming",
    "hiking",
    "walking",
    "training",
    "rock_climbing",
    "mountaineering",
    "rowing",
    "fitness_equipment",
}
SUBSPORTS = {
    "generic",
    "treadmill",
    "trail",
    "indoor_running",
    "road",
    "indoor_cycling",
    "strength_training",
    "cardio_training",
    "indoor_climbing",
    "bouldering",
    "hiit",
}
ROLES = {
    "interval": "work",
    "recovery": "recovery",
    "rest": "recovery",
    "warmup": "warmup",
    "cooldown": "cooldown",
    "active": "active",
}
PROVIDER_FIELDS = {
    "distance_m": "total_distance",
    "timer_seconds": "total_timer_time",
    "elapsed_seconds": "total_elapsed_time",
    "avg_heart_rate_bpm": "avg_heart_rate",
    "max_heart_rate_bpm": "max_heart_rate",
    "avg_cadence_rpm": "avg_cadence",
    "avg_power_w": "avg_power",
}


def number(value: Any, *, signed: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or (not signed and value < 0):
        return None
    return float(value)


def timestamp(value: Any) -> float:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("fit_timestamp_invalid")
    return value.timestamp()


def utc(value: float) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def field(frame: fitdecode.FitDataMessage, name: str) -> Any:
    return frame.get_value(name, fallback=None)


def boundaries(frame: fitdecode.FitDataMessage) -> tuple[float, float]:
    start, end = (
        timestamp(field(frame, "start_time")),
        timestamp(field(frame, "timestamp")),
    )
    if end <= start:
        raise ValueError("fit_time_bounds_invalid")
    return start, end


@dataclass(frozen=True)
class Point:
    time: float
    distance: float | None
    metrics: dict[str, float | None]
    location: tuple[float, float] | None = None
    location_invalid: bool = False


@dataclass
class Decoded:
    sessions: list[dict[str, Any]]
    points: list[Point]
    events: list[tuple[float, bool]]
    laps: list[dict[str, Any]]
    zones: list[dict[str, Any]]


def require_parser_version(value: str | None = None) -> str:
    value = VERSION if value is None else value
    if value not in SCHEMAS:
        raise ValueError("fit_parser_version_invalid")
    return value


def schema_path(version: str) -> Path:
    return SCHEMA_PATH.with_name(
        f"{SCHEMAS[require_parser_version(version)]}.schema.json"
    )


def position(
    frame: fitdecode.FitDataMessage,
) -> tuple[tuple[float, float] | None, bool]:
    names = ("position_lat", "position_long")
    raw = [field(frame, name) for name in names]
    if all(v is None for v in raw):
        return None, False
    coordinates = []
    for name, value, limit in zip(names, raw, (90, 180)):
        numeric = number(value, signed=True)
        if numeric is None:
            return None, True
        units = frame.get_field(name).units
        if units == "semicircles":
            numeric *= 180 / 2**31
        elif units not in {"degrees", "deg"}:
            return None, True
        if not -limit <= numeric <= limit:
            return None, True
        coordinates.append(numeric)
    return (coordinates[0], coordinates[1]), False


def location_summary(
    points: list[Point], start: float, end: float, *, include_end: bool = False
) -> dict[str, Any]:
    selected = [
        p
        for p in points
        if start <= p.time and (p.time < end or include_end and p.time == end)
    ]
    valid = [p for p in selected if p.location is not None]
    invalid = sum(p.location_invalid for p in selected)
    result: dict[str, Any] = {
        "source": "record.position_lat/position_long",
        "coordinate_unit": "degrees",
        "selection": "first_last_actual_samples",
        "status": "available"
        if valid
        else "insufficient_data"
        if invalid
        else "missing",
        "sample_count": len(selected),
        "valid_point_count": len(valid),
        "invalid_point_count": invalid,
        "missing_point_count": len(selected) - len(valid) - invalid,
    }
    for prefix, point in (
        ("first", valid[0] if valid else None),
        ("last", valid[-1] if valid else None),
    ):
        result[prefix + "_time_utc"] = utc(point.time) if point else None
        result[prefix + "_latitude"] = (
            point.location[0] if point and point.location else None
        )
        result[prefix + "_longitude"] = (
            point.location[1] if point and point.location else None
        )
        result[prefix + "_altitude_m"] = point.metrics["altitude_m"] if point else None
        result[prefix + "_distance_m"] = point.distance if point else None
    return result


def session_location_points(decoded: Decoded, index: int) -> list[Point]:
    session = decoded.sessions[index]
    following = decoded.sessions[index + 1 : index + 2]
    # A shared boundary belongs to the next session. A gap or final endpoint
    # remains owned here; continuous sport metrics retain their original samples.
    include_end = not following or following[0]["start"] != session["end"]
    return [
        point
        for point in decoded.points
        if session["start"] <= point.time
        and (
            point.time < session["end"] or include_end and point.time == session["end"]
        )
    ]


def decode(data: bytes, *, parser_version: str | None = None) -> Decoded:
    version = require_parser_version(parser_version)
    storage.require_fit(data)
    result = Decoded([], [], [], [], [])
    with fitdecode.FitReader(
        io.BytesIO(data),
        check_crc=fitdecode.CrcCheck.RAISE,
        error_handling=fitdecode.ErrorHandling.RAISE,
    ) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "session":
                start, end = boundaries(frame)
                sport, sub = field(frame, "sport"), field(frame, "sub_sport")
                result.sessions.append(
                    {
                        "start": start,
                        "end": end,
                        "index": field(frame, "message_index"),
                        "sport": sport if sport in SPORTS else "other",
                        "sub_sport": sub if sub in SUBSPORTS else "other",
                        "provider_summary": {
                            k: number(field(frame, v))
                            for k, v in PROVIDER_FIELDS.items()
                        },
                    }
                )
            elif frame.name == "record":
                t = timestamp(field(frame, "timestamp"))
                metrics = {}
                for key, (sources, _, signed) in METRICS.items():
                    candidates = [
                        number(field(frame, name), signed=signed) for name in sources
                    ]
                    metrics[key] = next((v for v in candidates if v is not None), None)
                location, invalid = (
                    position(frame) if version == LOCATION_VERSION else (None, False)
                )
                result.points.append(
                    Point(
                        t, number(field(frame, "distance")), metrics, location, invalid
                    )
                )
            elif frame.name == "event" and field(frame, "event") == "timer":
                kind = field(frame, "event_type")
                if kind in {
                    "start",
                    "stop",
                    "stop_all",
                    "stop_disable",
                    "stop_disable_all",
                }:
                    result.events.append(
                        (timestamp(field(frame, "timestamp")), kind == "start")
                    )
            elif frame.name == "lap":
                start, end = boundaries(frame)
                result.laps.append(
                    {
                        "start": start,
                        "end": end,
                        "role": ROLES.get(field(frame, "intensity"), "unknown"),
                    }
                )
            elif (
                frame.name == "time_in_zone"
                and field(frame, "reference_mesg") == "session"
            ):
                vector = field(frame, "time_in_hr_zone")
                result.zones.append(
                    {"index": field(frame, "reference_index"), "durations": vector}
                )
    result.sessions.sort(key=lambda s: s["start"])
    if any(a["end"] > b["start"] for a, b in zip(result.sessions, result.sessions[1:])):
        raise ValueError("fit_session_overlap")
    result.points.sort(key=lambda p: p.time)
    unique: list[Point] = []
    for point in result.points:
        if unique and point.time == unique[-1].time:
            if (
                point.distance != unique[-1].distance
                or point.metrics != unique[-1].metrics
            ):
                raise ValueError("fit_record_time_conflict")
            if (
                point.location != unique[-1].location
                or point.location_invalid != unique[-1].location_invalid
            ):
                # Conflicting geography must not discard valid sport statistics.
                unique[-1] = replace(unique[-1], location=None, location_invalid=True)
        else:
            unique.append(point)
    result.points = unique
    return result


def active_intervals(
    s: dict[str, Any], events: list[tuple[float, bool]]
) -> tuple[list[tuple[float, float]], str]:
    start, end = s["start"], s["end"]
    selected = sorted({(t, on) for t, on in events if start <= t <= end})
    # No pause position is invented from a timer total shorter than elapsed time.
    if not selected:
        timer = s["provider_summary"]["timer_seconds"]
        if timer is not None and abs(timer - (end - start)) <= 0.01:
            return [(start, end)], "session_no_pause"
        return [], "unavailable"
    if selected[0] != (start, True) or len({t for t, _ in selected}) != len(selected):
        return [], "unavailable"
    intervals = []
    cursor, active = start, True
    for t, on in selected[1:]:
        if on == active:
            return [], "unavailable"
        if active and t > cursor:
            intervals.append((cursor, t))
        cursor, active = t, on
    if active and cursor < end:
        intervals.append((cursor, end))
    total = sum(b - a for a, b in intervals)
    timer = s["provider_summary"]["timer_seconds"]
    if timer is not None and abs(total - timer) > 1:
        return [], "unavailable"
    return intervals, "timer_events"


def overlap(start: float, end: float, intervals: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, b) - max(start, a)) for a, b in intervals)


class Series:
    def __init__(
        self, points: list[Point], intervals: list[tuple[float, float]], known: bool
    ):
        self.points, self.intervals, self.known = points, intervals, known
        self.times = [p.time for p in points]

    def aggregate(self, start: float, end: float) -> dict[str, Any]:
        values: dict[str, list[tuple[float, float]]] = {key: [] for key in METRICS}
        covered = distance = distance_seconds = 0.0
        count = max(
            0,
            bisect.bisect_right(self.times, end)
            - bisect.bisect_left(self.times, start),
        )
        left = max(0, bisect.bisect_right(self.times, start) - 1)
        right = min(len(self.points) - 1, bisect.bisect_left(self.times, end))
        for idx in range(left, right):
            p, q = self.points[idx : idx + 2]
            dt = q.time - p.time
            if not self.known or not 0 < dt <= MAX_GAP:
                continue
            duration = overlap(max(start, p.time), min(end, q.time), self.intervals)
            if duration <= 0:
                continue
            covered += duration
            for key, value in p.metrics.items():
                if value is not None:
                    values[key].append((value, duration))
            if (
                p.distance is not None
                and q.distance is not None
                and q.distance >= p.distance
                and overlap(p.time, q.time, self.intervals) == dt
            ):
                distance += (q.distance - p.distance) * duration / dt
                distance_seconds += duration
        metrics = {}
        for key, items in values.items():
            seconds = sum(w for _, w in items)
            metrics[key] = {
                "unit": METRICS[key][1],
                "mean": sum(v * w for v, w in items) / seconds if seconds else None,
                "min": min((v for v, _ in items), default=None),
                "max": max((v for v, _ in items), default=None),
                "covered_seconds": seconds,
            }
        return {
            "elapsed_seconds": end - start,
            "valid_seconds": overlap(start, end, self.intervals)
            if self.known
            else None,
            "sample_count": count,
            "sample_covered_seconds": covered,
            "distance_m": distance if distance_seconds else None,
            "distance_covered_seconds": distance_seconds,
            "pace_seconds_per_km": distance_seconds * 1000 / distance
            if distance > 0
            else None,
            "metrics": metrics,
        }


def session_laps(
    s: dict[str, Any], laps: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    crossing = any(
        x["start"] < s["end"]
        and x["end"] > s["start"]
        and not (s["start"] <= x["start"] < x["end"] <= s["end"])
        for x in laps
    )
    items = sorted(
        [x for x in laps if s["start"] <= x["start"] < x["end"] <= s["end"]],
        key=lambda x: x["start"],
    )
    if crossing or any(a["end"] > b["start"] for a, b in zip(items, items[1:])):
        return [], True
    return items, False


def windows(
    s: dict[str, Any], laps: list[dict[str, Any]]
) -> tuple[str, list[tuple[float, float, str]]]:
    roles = {x["role"] for x in laps}
    complete = (
        bool(laps)
        and laps[0]["start"] == s["start"]
        and laps[-1]["end"] == s["end"]
        and all(a["end"] == b["start"] for a, b in zip(laps, laps[1:]))
    )
    kind = "unknown"
    if s["sport"] == "running" and complete and "work" in roles:
        if "recovery" in roles:
            kind = "sos_intervals"
        elif {"warmup", "cooldown"} <= roles and sum(
            x["role"] == "work" for x in laps
        ) == 1:
            kind = "sos_continuous"
    ranges = []
    if kind != "unknown":
        for lap in laps:
            if kind == "sos_continuous" and lap["role"] == "work":
                cursor = lap["start"]
                while cursor < lap["end"]:
                    end = min(cursor + 60, lap["end"])
                    ranges.append((cursor, end, "work"))
                    cursor = end
            else:
                ranges.append((lap["start"], lap["end"], lap["role"]))
    else:
        width = 120 if s["sport"] == "running" else 300
        cursor = s["start"]
        while cursor < s["end"]:
            end = min(cursor + width, s["end"])
            ranges.append((cursor, end, "unknown"))
            cursor = end
    return kind, ranges


def session_zones(
    s: dict[str, Any], decoded: Decoded, ref: str, sha: str
) -> dict[str, Any] | None:
    index = (
        s["index"]
        if s["index"] is not None
        else (0 if len(decoded.sessions) == 1 else None)
    )
    if index is None or (
        len(decoded.sessions) > 1
        and sum(x["index"] == index for x in decoded.sessions) != 1
    ):
        return None
    matches = [z for z in decoded.zones if index is not None and z["index"] == index]
    if len(matches) != 1:
        return None
    vector = matches[0]["durations"]
    if not isinstance(vector, (tuple, list)) or not 1 <= len(vector) <= 16:
        return None
    if any(number(v) is None for v in vector):
        return None
    total = sum(vector)
    timer = s["provider_summary"]["timer_seconds"]
    if (
        total <= 0
        or total > (timer if timer is not None else s["end"] - s["start"]) + 1
    ):
        return None
    return {
        "activity_ref": ref,
        "fit_sha256": sha,
        "reference_index": index,
        "source": "time_in_zone.session.time_in_hr_zone",
        "durations_seconds": list(vector),
        "percentages": [v * 100 / total for v in vector],
        "derivation": "derived_from_provider_duration",
    }


def summarize(
    data: bytes, activity_ref: str, fit_sha: str, *, parser_version: str | None = None
) -> dict[str, Any]:
    version = require_parser_version(parser_version)
    storage.require_sha(fit_sha)
    if storage.digest(data) != fit_sha:
        raise ValueError("fit_sha_mismatch")
    if not re.fullmatch(r"[0-9]{1,32}", activity_ref):
        raise ValueError("fit_parse_binding_invalid")
    decoded = decode(data, parser_version=version)
    sessions = []
    for idx, s in enumerate(decoded.sessions):
        intervals, timer_source = active_intervals(s, decoded.events)
        points = [p for p in decoded.points if s["start"] <= p.time <= s["end"]]
        location_points = (
            session_location_points(decoded, idx) if version == LOCATION_VERSION else []
        )
        series = Series(points, intervals, timer_source != "unavailable")
        summary = series.aggregate(s["start"], s["end"])
        if version == LOCATION_VERSION:
            summary["location"] = location_summary(
                location_points, s["start"], s["end"], include_end=True
            )
        laps, conflict = session_laps(s, decoded.laps)
        kind, ranges = windows(s, laps)
        limitations = []
        if timer_source == "unavailable":
            limitations.append("timer_boundaries_unavailable")
        if conflict:
            limitations.append("laps_conflicting")
        if summary["distance_covered_seconds"] < summary["sample_covered_seconds"]:
            limitations.append("distance_reset_or_missing")
        valid = summary["valid_seconds"]
        gap = valid - summary["sample_covered_seconds"] if valid is not None else None
        if gap:
            limitations.append("sample_gaps")

        def block(start: float, end: float, role: str) -> dict[str, Any]:
            return {
                "start_offset_seconds": start - s["start"],
                "end_offset_seconds": end - s["start"],
                "role": role,
                **series.aggregate(start, end),
                **(
                    {
                        "location": location_summary(
                            location_points, start, end, include_end=end == s["end"]
                        )
                    }
                    if version == LOCATION_VERSION
                    else {}
                ),
            }

        sessions.append(
            {
                "session_ordinal": idx + 1,
                "sport": s["sport"],
                "sub_sport": s["sub_sport"],
                "start_utc": utc(s["start"]),
                "end_utc": utc(s["end"]),
                "elapsed_seconds": s["end"] - s["start"],
                "valid_seconds": valid,
                "pause_seconds": s["end"] - s["start"] - valid
                if valid is not None
                else None,
                "sample_covered_seconds": summary["sample_covered_seconds"],
                "gap_seconds": gap,
                "timer_source": timer_source,
                "running_kind": kind,
                "provider_summary": s["provider_summary"],
                "summary": summary,
                "segments": [block(a, b, r) for a, b, r in ranges],
                "laps": [block(x["start"], x["end"], x["role"]) for x in laps],
                "hr_zones": session_zones(s, decoded, activity_ref, fit_sha),
                "limitations": limitations,
            }
        )
    payload = {
        "schema_version": SCHEMAS[version],
        "parser_version": version,
        "activity_ref": activity_ref,
        "fit_sha256": fit_sha,
        "start_utc": sessions[0]["start_utc"],
        "end_utc": sessions[-1]["end_utc"],
        "methods": {
            "continuous_metrics": "left_sample_valid_time_weighted",
            "distance": "linear_between_valid_distance_samples",
            "pace": "distance_covered_seconds_per_km",
            "max_sample_gap_seconds": MAX_GAP,
        },
        "sessions": sessions,
        "provider_calls": 0,
    }
    if version == LOCATION_VERSION:
        points = [
            p
            for p in decoded.points
            if any(s["start"] <= p.time <= s["end"] for s in decoded.sessions)
        ]
        payload["location"] = location_summary(
            points,
            decoded.sessions[0]["start"],
            decoded.sessions[-1]["end"],
            include_end=True,
        )
    validate(payload)
    return payload


def validate(payload: dict[str, Any]) -> None:
    version = require_parser_version(payload.get("parser_version", ""))
    jsonschema.Draft202012Validator(
        json.loads(schema_path(version).read_text()),
        format_checker=jsonschema.FormatChecker(),
    ).validate(payload)


def parse_registered(
    db: sqlite3.Connection,
    root: Path,
    activity_ref: str,
    fit_sha: str,
    *,
    parser_version: str | None = None,
) -> dict[str, Any]:
    version = require_parser_version(parser_version)
    storage.require_instance(db, root)
    storage.require_sha(fit_sha)
    row = db.execute(
        "SELECT f.relative_path,f.byte_size FROM activity_fits a JOIN fits f ON a.fit_sha256=f.sha256 WHERE a.activity_ref=? AND f.sha256=?",
        (activity_ref, fit_sha),
    ).fetchone()
    if row is None or row[0] != f"fits/{fit_sha}.fit":
        raise ValueError("fit_parse_binding_invalid")
    path = root / row[0]
    storage.private_entry(path, nonempty=True)
    data = path.read_bytes()
    if len(data) != row[1] or storage.digest(data) != fit_sha:
        raise ValueError("fit_sha_mismatch")
    payload = summarize(data, activity_ref, fit_sha, parser_version=version)
    storage.put_parse(db, fit_sha, version, payload)
    return payload
