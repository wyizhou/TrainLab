#!/usr/bin/env python3
"""Create bounded raw-file evidence; never print raw payloads or FIT samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from skills._shared.state import connect, record_skill_result  # noqa: E402


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files_for(root: Path, day: date) -> list[Path]:
    if not root.is_dir():
        return []
    prefix = day.strftime("%Y%m%d") + "-"
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.name.startswith(prefix)
    )


def json_shape(value: Any, *, depth: int = 0) -> dict[str, Any]:
    """Return structure only; never expose scalar raw values."""
    if depth >= 2:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)[:40]
        return {
            "type": "object",
            "key_count": len(value),
            "keys": keys,
            "truncated_keys": len(value) > len(keys),
        }
    if isinstance(value, list):
        item_types = sorted({type(item).__name__ for item in value[:40]})
        return {
            "type": "array",
            "length": len(value),
            "item_types": item_types,
            "truncated_items": len(value) > 40,
        }
    return {"type": type(value).__name__}


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "minimum": min(values),
        "maximum": max(values),
        "average": round(sum(values) / len(values), 3),
    }


def _walk_numbers(value: Any, values: list[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        values.append(float(value))
    elif isinstance(value, dict):
        for child in value.values():
            _walk_numbers(child, values)
    elif isinstance(value, list):
        for child in value[:10000]:
            _walk_numbers(child, values)


def _find_named(value: Any, names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower().replace("_", "") in names:
                found.append(child)
            found.extend(_find_named(child, names))
    elif isinstance(value, list):
        for child in value[:1000]:
            found.extend(_find_named(child, names))
    return found


def _json_metrics(value: Any, resource: str) -> dict[str, Any]:
    numbers: list[float] = []
    _walk_numbers(value, numbers)
    metrics: dict[str, Any] = {
        "resource": resource,
        "numeric_summary": _numeric_summary(numbers),
        "uncertainty": "bounded_aggregate",
    }
    aliases = {
        "rhr": "resting_heart_rate",
        "heart_rates": "heart_rate",
        "hrv": "hrv",
        "spo2": "spo2",
        "max_metrics": "vo2_max",
        "weigh_ins": "weight",
    }
    if resource in aliases:
        metrics["metric"] = aliases[resource]
        metrics["aggregate"] = _numeric_summary(numbers)
    if resource == "sleep":
        durations = _find_named(value, {"duration", "durationseconds", "sleeptime"})
        starts = _find_named(value, {"starttime", "sleepstart", "bedtime"})
        ends = _find_named(value, {"endtime", "waketime", "wake"})
        stages = _find_named(value, {"levels", "stages", "sleeplevels"})
        if durations:
            metrics["duration_seconds"] = next(
                (item for item in durations if isinstance(item, (int, float))), None
            )
        if starts and isinstance(starts[0], str):
            metrics["sleep_start"] = starts[0]
        if ends and isinstance(ends[0], str):
            metrics["sleep_end"] = ends[0]
        if stages:
            metrics["stage_group_count"] = sum(
                len(item) if isinstance(item, list) else 1 for item in stages
            )
        metrics["completeness"] = "complete" if starts and ends else "partial"
    return metrics


def _xml_metrics(path: Path, root: ET.Element) -> dict[str, Any]:
    points = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"trkpt", "Trackpoint"}:
            points.append(element)
    coordinates: list[tuple[float, float]] = []
    for point in points:
        try:
            coordinates.append((float(point.attrib["lat"]), float(point.attrib["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    distance_km = 0.0
    for left, right in zip(coordinates, coordinates[1:]):
        lat1, lon1 = map(math.radians, left)
        lat2, lon2 = map(math.radians, right)
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        distance_km += 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))
    times = [
        child.text
        for point in points
        for child in point
        if child.tag.rsplit("}", 1)[-1] in {"time", "Time"} and child.text
    ]
    duration_seconds: float | None = None
    if len(times) >= 2:
        try:
            parsed = [
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                for value in times
            ]
            if all(item.tzinfo is not None for item in parsed):
                duration_seconds = (
                    parsed[-1].astimezone(timezone.utc)
                    - parsed[0].astimezone(timezone.utc)
                ).total_seconds()
            else:
                duration_seconds = (parsed[-1] - parsed[0]).total_seconds()
        except ValueError:
            duration_seconds = None
    return {
        "trackpoint_count": len(points),
        "time_point_count": len(times),
        "distance_km": round(distance_km, 3),
        "duration_seconds": duration_seconds,
        "duration_available": len(times) >= 2,
        "uncertainty": "structure_only",
        "source_name": path.suffix.lower()[1:],
    }


def parse_evidence(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            resource = path.name[9:].removesuffix(".json").rsplit("-", 1)[0]
            return {
                "parser": "json",
                "shape": json_shape(value),
                "metrics": _json_metrics(value, resource),
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"parser": "json", "error_code": "raw_json_invalid"}
    if suffix in {".gpx", ".tcx"}:
        try:
            root = ET.parse(path).getroot()
            return {
                "parser": suffix[1:],
                "root_tag": root.tag.rsplit("}", 1)[-1],
                "element_count": sum(1 for _ in root.iter()),
                "metrics": _xml_metrics(path, root),
            }
        except (OSError, ET.ParseError):
            return {"parser": suffix[1:], "error_code": "raw_xml_invalid"}
    if suffix == ".fit":
        try:
            import fitdecode

            message_count = 0
            message_types: set[str] = set()
            numeric_values: list[float] = []
            field_values: dict[str, list[float]] = {}
            text_values: dict[str, list[str]] = {}
            with fitdecode.FitReader(path) as reader:
                for frame in reader:
                    message_count += 1
                    if message_count > 100_000:
                        return {
                            "parser": "fitdecode",
                            "message_count": message_count,
                            "truncated": True,
                        }
                    name = getattr(frame, "name", None)
                    if name:
                        message_types.add(str(name))
                    for field in getattr(frame, "fields", ()):
                        value = getattr(field, "value", None)
                        if isinstance(value, (int, float)) and not isinstance(
                            value, bool
                        ):
                            numeric_values.append(float(value))
                            field_values.setdefault(
                                str(getattr(field, "name", "value")), []
                            ).append(float(value))
                        elif isinstance(value, str):
                            text_values.setdefault(
                                str(getattr(field, "name", "value")), []
                            ).append(value)
            normalized_fields = {
                name.lower().replace(" ", "_"): values
                for name, values in field_values.items()
            }

            def _numeric_field(*names: str) -> list[float]:
                for name in names:
                    values = normalized_fields.get(name)
                    if values:
                        return values
                return []

            distance_values = _numeric_field("distance", "total_distance")
            duration_values = _numeric_field(
                "total_elapsed_time", "total_timer_time", "elapsed_time", "timer_time"
            )
            average_hr = _numeric_field("avg_heart_rate", "average_heart_rate")
            maximum_hr = _numeric_field("max_heart_rate", "maximum_heart_rate")
            distance_km = max(distance_values) / 1000 if distance_values else None
            duration_seconds = max(duration_values) if duration_values else None
            activity_kind = None
            for name, values in text_values.items():
                if name.lower().replace(" ", "_") in {"sport", "sub_sport"} and values:
                    activity_kind = values[-1]
                    break
            lap_count = sum(1 for name in message_types if name.lower() == "lap")
            activity_metrics: dict[str, Any] = {
                "numeric_summary": _numeric_summary(numeric_values),
                "field_counts": {
                    name: len(values)
                    for name, values in sorted(field_values.items())[:40]
                },
                "uncertainty": "bounded_aggregate",
            }
            if distance_km is not None:
                activity_metrics["distance_km"] = round(distance_km, 3)
            if duration_seconds is not None:
                activity_metrics["duration_seconds"] = duration_seconds
            if distance_km and duration_seconds and duration_seconds > 0:
                activity_metrics["pace_seconds_per_km"] = round(
                    duration_seconds / distance_km, 2
                )
            if average_hr:
                activity_metrics["heart_rate_average"] = round(
                    sum(average_hr) / len(average_hr), 2
                )
            if maximum_hr:
                activity_metrics["heart_rate_maximum"] = max(maximum_hr)
            if activity_kind:
                activity_metrics["activity_kind"] = activity_kind
            if lap_count:
                activity_metrics["lap_count"] = lap_count
            return {
                "parser": "fitdecode",
                "message_count": message_count,
                "message_types": sorted(message_types)[:40],
                "metrics": activity_metrics,
            }
        except (OSError, ValueError, RuntimeError, ImportError):
            return {"parser": "fitdecode", "error_code": "raw_fit_unavailable"}
        except Exception:  # fitdecode exposes version-specific parse exceptions.
            return {"parser": "fitdecode", "error_code": "raw_fit_unavailable"}
    return {"parser": "none", "error_code": "raw_format_unsupported"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    if args.days < 1 or args.days > 14:
        raise SystemExit("days must be between 1 and 14")
    target = date.fromisoformat(args.date)
    health_root = args.source_root / "state/raw/garmin/health"
    activity_root = args.source_root / "state/raw/garmin/activities"
    records: list[dict[str, object]] = []
    for offset in range(args.days):
        day = target - timedelta(days=offset)
        for path in files_for(health_root, day) + files_for(activity_root, day):
            record: dict[str, object] = {
                "relative_path": str(path.relative_to(args.source_root)),
                "data_date": day.isoformat(),
                "format": path.suffix.lstrip(".") or "unknown",
                "bytes": path.stat().st_size,
                "sha256": digest(path),
                "evidence": parse_evidence(path),
            }
            if args.database and args.database.is_file():
                connection = connect(args.database, read_only=True, immutable=True)
                try:
                    row = connection.execute(
                        "SELECT id FROM raw_files WHERE relative_path=? AND sha256=?",
                        (record["relative_path"], record["sha256"]),
                    ).fetchone()
                finally:
                    connection.close()
                if row:
                    record["raw_file_id"] = int(row[0])
            records.append(record)
    payload = {
        "schema_version": "bounded_evidence_v1",
        "status": "ready" if records else "blocked",
        "window": {
            "from_date": (target - timedelta(days=args.days - 1)).isoformat(),
            "through_date": target.isoformat(),
        },
        "evidence": records,
        "file_count": len(records),
        "raw_values_included": False,
        "provider_calls": 0,
    }
    if not records:
        payload["error_code"] = "bounded_evidence_no_files"
    require_valid_payload(payload, "bounded_evidence_v1")
    if args.database:
        record_skill_result(
            args.database,
            skill_name="training-coach",
            operation="weekly_coach" if args.days > 1 else "daily_coach",
            output_kind="bounded_evidence",
            logical_key=f"training-coach:raw:{args.date}:{args.days}",
            payload=payload,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
