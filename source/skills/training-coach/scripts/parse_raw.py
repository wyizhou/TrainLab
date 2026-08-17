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
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from skills._shared.state import connect, record_skill_result  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")


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


def _normalize_key(value: object) -> str:
    return str(value).lower().replace("_", "").replace("-", "")


def _resource_from_filename(path: Path) -> str:
    """Map the persisted filename to a controlled semantic resource name."""
    name = path.name
    if name.endswith(".weather.json"):
        return "activity_weather"
    tail = name[9:] if len(name) >= 9 and name[8] == "-" else name
    resource = tail.removesuffix(".json").rsplit("-", 1)[0]
    return "activity_weather" if resource == "weather" else resource


def _numbers(value: Any) -> list[float]:
    numbers: list[float] = []
    _walk_numbers(value, numbers)
    return numbers


def _first_number(value: Any, names: set[str]) -> float | None:
    for item in _find_named(value, names):
        numbers = _numbers(item)
        if numbers:
            return numbers[0]
    return None


def _first_text(value: Any, names: set[str]) -> str | None:
    for item in _find_named(value, names):
        if isinstance(item, str) and item.strip():
            return item
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sleep_metrics(value: Any) -> dict[str, Any]:
    sleep_dtos = _find_named(value, {"dailysleepdto"})
    source = next((item for item in sleep_dtos if isinstance(item, dict)), value)
    starts = _find_named(
        source,
        {
            "sleepstarttimestampgmt",
            "sleepstarttimestamp",
            "sleepstart",
            "starttime",
            "bedtime",
            "startgmt",
        },
    )
    ends = _find_named(
        source,
        {
            "sleependtimestampgmt",
            "sleependtimestamp",
            "sleepend",
            "endtime",
            "waketime",
            "wake",
            "endgmt",
        },
    )
    start_value = next(
        (item for item in starts if _parse_timestamp(item) is not None), None
    )
    end_value = next(
        (item for item in ends if _parse_timestamp(item) is not None), None
    )
    start = _parse_timestamp(start_value)
    end = _parse_timestamp(end_value)
    duration = _first_number(
        source,
        {"sleeptimeseconds", "durationseconds", "duration", "sleeptime"},
    )
    if duration is None and start is not None and end is not None and end > start:
        duration = (end - start).total_seconds()
    stages = _find_named(value, {"levels", "stages", "sleeplevels", "sleepstages"})
    metrics: dict[str, Any] = {
        "resource": "sleep",
        "uncertainty": "named_fields",
        "completeness": "complete"
        if start is not None
        and end is not None
        and duration is not None
        and end > start
        else "partial",
    }
    if start is not None:
        metrics["sleep_start"] = start.isoformat().replace("+00:00", "Z")
    if end is not None:
        metrics["sleep_end"] = end.isoformat().replace("+00:00", "Z")
    if duration is not None and duration >= 0:
        metrics["duration_seconds"] = round(duration, 3)
    if end is not None:
        metrics["sleep_wake_date"] = end.astimezone(HKT).date().isoformat()
    if stages:
        metrics["stage_group_count"] = sum(
            len(item) if isinstance(item, list) else 1 for item in stages
        )
    return metrics


def _heart_rate_points(value: Any) -> list[float]:
    """Extract HR values without treating timestamps as heart-rate samples."""
    points: list[float] = []
    for item in _find_named(
        value,
        {"heartratevalues", "heartratesamples", "heartratereadings", "readings"},
    ):
        if isinstance(item, dict):
            for key, child in item.items():
                if _normalize_key(key) in {
                    "heartrate",
                    "heartratebpm",
                    "bpm",
                    "value",
                    "averageheartrate",
                }:
                    points.extend(_numbers(child))
        elif isinstance(item, list):
            for point in item:
                if isinstance(point, dict):
                    points.extend(_heart_rate_points(point))
                elif isinstance(point, (list, tuple)):
                    numeric = _numbers(point)
                    if numeric:
                        points.append(numeric[-1])
                elif isinstance(point, (int, float)) and not isinstance(point, bool):
                    points.append(float(point))
    return [item for item in points if 20 <= item <= 260]


def _date_token(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            try:
                date.fromisoformat(text)
            except ValueError:
                return None
            return text
        if len(text) == 8 and text.isdigit():
            try:
                return datetime.strptime(text, "%Y%m%d").date().isoformat()
            except ValueError:
                return None
    parsed = _parse_timestamp(value)
    return parsed.astimezone(HKT).date().isoformat() if parsed else None


def _weight_for_date(value: Any, expected_date: str | None) -> float | None:
    """Read only a dated Garmin weight measurement and normalize to kg."""
    if expected_date is None:
        return None
    weight_keys = {
        "weight",
        "weightkg",
        "weightinkg",
        "weightgrams",
        "weightvalue",
    }
    date_keys = {
        "summarydate",
        "calendardate",
        "localdate",
        "measurementdate",
        "date",
    }
    candidates: list[float] = []

    def walk(
        node: Any, inherited_date: str | None = None, blocked: bool = False
    ) -> None:
        if isinstance(node, dict):
            normalized = {_normalize_key(key): child for key, child in node.items()}
            node_date = next(
                (
                    _date_token(child)
                    for key, child in normalized.items()
                    if key in date_keys
                ),
                None,
            )
            if node_date is not None and node_date != expected_date:
                return
            effective_date = node_date or inherited_date
            for key, child in normalized.items():
                child_blocked = blocked or any(
                    token in key for token in ("previous", "next", "trend", "average")
                )
                if (
                    effective_date == expected_date
                    and not child_blocked
                    and key in weight_keys
                    and isinstance(child, (int, float))
                    and not isinstance(child, bool)
                ):
                    number = float(child)
                    if math.isfinite(number):
                        candidates.append(number)
                if isinstance(child, (dict, list)):
                    walk(child, effective_date, child_blocked)
        elif isinstance(node, list):
            for child in node[:1000]:
                walk(child, inherited_date, blocked)

    walk(value)
    if not candidates:
        return None
    raw = candidates[-1]
    kg = raw / 1000.0 if raw > 300 else raw
    return round(kg, 3) if 30 <= kg <= 300 else None


def _json_metrics(
    value: Any, resource: str, *, expected_date: str | None = None
) -> dict[str, Any]:
    """Return resource-specific aggregates; never average unrelated JSON numbers."""
    if resource == "sleep":
        return _sleep_metrics(value)

    metrics: dict[str, Any] = {
        "resource": resource,
        "uncertainty": "named_fields",
    }
    if resource == "rhr":
        resting = _first_number(
            value,
            {
                "restingheartrate",
                "restingheartratevalue",
                "wellnessrestingheartrate",
                "value",
            },
        )
        metrics["metric"] = "resting_heart_rate"
        if resting is not None:
            metrics["resting_heart_rate_bpm"] = resting
        return metrics
    if resource == "hrv":
        metrics["metric"] = "hrv"
        for output, names in {
            "last_night_average": {"lastnightavg", "lastnightaverage"},
            "weekly_average": {"weeklyavg", "weeklyaverage"},
            "last_night_5_min_high": {"lastnight5minhigh"},
        }.items():
            number = _first_number(value, names)
            if number is not None:
                metrics[output] = number
        return metrics
    if resource == "heart_rates":
        points = _heart_rate_points(value)
        explicit_average = _first_number(
            value, {"averageheartrate", "heartrateaverage", "dailyaverage"}
        )
        metrics["metric"] = "heart_rate"
        metrics["sample_count"] = len(points)
        if points:
            metrics["aggregate"] = _numeric_summary(points)
            metrics["median"] = round(sorted(points)[len(points) // 2], 3)
        if explicit_average is not None:
            metrics["average"] = explicit_average
        resting = _first_number(value, {"restingheartrate", "restingheartratevalue"})
        if resting is not None:
            metrics["resting_heart_rate_bpm"] = resting
        return metrics
    if resource == "max_metrics":
        number = _first_number(
            value, {"vo2maxprecisevalue", "vo2maxvalue", "vo2max", "vo2maxprecise"}
        )
        metrics["metric"] = "vo2_max"
        if number is not None:
            metrics["vo2_max"] = number
        return metrics
    if resource == "weigh_ins":
        number = _weight_for_date(value, expected_date)
        metrics["metric"] = "weight"
        if number is not None:
            metrics["weight"] = number
            metrics["unit"] = "kg"
        return metrics
    if resource == "activity_weather" or resource == "weather":
        metrics["resource"] = "activity_weather"
        for output, names in {
            "temperature": {"temperature", "temperaturec", "temp"},
            "humidity": {"humidity", "relativehumidity"},
            "wind_speed": {"windspeed", "windvelocity"},
        }.items():
            number = _first_number(value, names)
            if number is not None:
                metrics[output] = number
        metrics["units"] = "provider_unspecified"
        return metrics
    return metrics


def _xml_metrics(path: Path, root: ET.Element) -> dict[str, Any]:
    points = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"trkpt", "Trackpoint"}:
            points.append(element)
    coordinates: list[tuple[float, float]] = []
    explicit_distances: list[float] = []
    for point in points:
        lat = point.attrib.get("lat")
        lon = point.attrib.get("lon")
        if lat is None or lon is None:
            position = next(
                (
                    child
                    for child in point.iter()
                    if child.tag.rsplit("}", 1)[-1] == "Position"
                ),
                None,
            )
            if position is not None:
                values = {
                    child.tag.rsplit("}", 1)[-1]: child.text
                    for child in position.iter()
                }
                lat = values.get("LatitudeDegrees")
                lon = values.get("LongitudeDegrees")
        try:
            if lat is not None and lon is not None:
                coordinates.append((float(lat), float(lon)))
        except (TypeError, ValueError):
            pass
        for child in point.iter():
            if child.tag.rsplit("}", 1)[-1] in {"DistanceMeters", "Distance"}:
                try:
                    explicit_distances.append(float(str(child.text)))
                except (TypeError, ValueError):
                    pass
    distance_km = 0.0
    for left, right in zip(coordinates, coordinates[1:]):
        lat1, lon1 = map(math.radians, left)
        lat2, lon2 = map(math.radians, right)
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        distance_km += 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))
    if explicit_distances:
        distance_km = max(distance_km, max(explicit_distances) / 1000.0)
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
            resource = _resource_from_filename(path)
            expected_date = None
            if len(path.name) >= 8 and path.name[:8].isdigit():
                try:
                    expected_date = (
                        datetime.strptime(path.name[:8], "%Y%m%d").date().isoformat()
                    )
                except ValueError:
                    expected_date = None
            return {
                "parser": "json",
                "shape": json_shape(value),
                "metrics": _json_metrics(value, resource, expected_date=expected_date),
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
