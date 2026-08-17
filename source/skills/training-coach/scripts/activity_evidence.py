#!/usr/bin/env python3
"""Build bounded activity evidence from registered FIT/GPX/TCX files.

The output deliberately contains no coordinates, route points, names, or raw
payloads.  FIT/GPX/TCX are parsed locally; the provider is never contacted.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import connect  # noqa: E402


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    elif not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _field_map(frame: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in getattr(frame, "fields", ()):
        name = str(getattr(field, "name", "")).lower().replace(" ", "_")
        if name:
            result[name] = getattr(field, "value", None)
    return result


def _fit_records(path: Path) -> tuple[list[dict[str, object]], dict[str, Any]]:
    try:
        import fitdecode
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ValueError("fitdecode_unavailable") from exc
    records: list[dict[str, object]] = []
    laps = 0
    activity_kind: str | None = None
    all_distances: list[float] = []
    with fitdecode.FitReader(path) as reader:
        for frame in reader:
            name = str(getattr(frame, "name", "")).lower()
            fields = _field_map(frame)
            if name == "lap":
                laps += 1
            if name == "sport":
                candidate = fields.get("sport") or fields.get("sub_sport")
                if isinstance(candidate, str) and candidate:
                    activity_kind = candidate
            if name != "record":
                continue
            timestamp = _timestamp(fields.get("timestamp"))
            if timestamp is None:
                continue
            distance = _number(fields.get("distance"))
            if distance is not None:
                all_distances.append(distance)
            item: dict[str, object] = {"timestamp": timestamp}
            for source, target in {
                "heart_rate": "heart_rate_bpm",
                "cadence": "cadence_spm",
                "power": "power_watts",
                "speed": "speed_mps",
                "altitude": "elevation_m",
                "temperature": "temperature_c",
                "distance": "distance_m",
            }.items():
                numeric = _number(fields.get(source))
                if numeric is not None:
                    item[target] = numeric
            records.append(item)
    if not records:
        raise ValueError("activity_timestamp_missing")
    duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()  # type: ignore[operator]
    return records, {
        "activity_kind": activity_kind,
        "duration_seconds": round(max(0.0, duration), 3),
        "distance_km": round(max(all_distances) / 1000, 3) if all_distances else None,
        "lap_count": laps,
        "source_format": "fit",
    }


def _xml_records(path: Path) -> tuple[list[dict[str, object]], dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("activity_xml_invalid") from exc
    records: list[dict[str, object]] = []
    previous_coordinate: tuple[float, float] | None = None
    cumulative_distance = 0.0
    last_explicit_distance: float | None = None
    for point in root.iter():
        tag = point.tag.rsplit("}", 1)[-1]
        if tag not in {"trkpt", "Trackpoint"}:
            continue
        timestamp: datetime | None = None
        for child in point.iter():
            if child.tag.rsplit("}", 1)[-1] in {"time", "Time"}:
                timestamp = _timestamp(child.text)
                break
        if timestamp is None:
            continue
        lat = _number(point.attrib.get("lat"))
        lon = _number(point.attrib.get("lon"))
        if lat is None or lon is None:
            position = [
                child
                for child in point.iter()
                if child.tag.rsplit("}", 1)[-1] == "Position"
            ]
            if position:
                values = {
                    child.tag.rsplit("}", 1)[-1]: child.text
                    for child in position[0].iter()
                }
                lat = _number(values.get("LatitudeDegrees"))
                lon = _number(values.get("LongitudeDegrees"))
        coordinate = (lat, lon) if lat is not None and lon is not None else None
        if coordinate is not None and previous_coordinate is not None:
            lat1, lon1 = map(math.radians, previous_coordinate)
            lat2, lon2 = map(math.radians, coordinate)
            haversine = (
                math.sin((lat2 - lat1) / 2) ** 2
                + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
            )
            cumulative_distance += (
                6371 * 1000 * 2 * math.asin(math.sqrt(min(1.0, haversine)))
            )
        if coordinate is not None:
            previous_coordinate = coordinate
        explicit_distance = next(
            (
                _number(child.text)
                for child in point.iter()
                if point is not child
                and child.tag.rsplit("}", 1)[-1] in {"DistanceMeters", "Distance"}
                and _number(child.text) is not None
            ),
            None,
        )
        if explicit_distance is not None:
            last_explicit_distance = explicit_distance
        distance_m = (
            last_explicit_distance
            if last_explicit_distance is not None
            else cumulative_distance
        )
        records.append({"timestamp": timestamp, "distance_m": distance_m})
    if not records:
        raise ValueError("activity_timestamp_missing")
    distance_value = records[-1].get("distance_m")
    distance_km = max(
        0.0,
        float(distance_value) / 1000
        if isinstance(distance_value, (int, float))
        else 0.0,
    )
    duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()  # type: ignore[operator]
    return records, {
        "activity_kind": "running" if path.suffix.lower() == ".gpx" else None,
        "duration_seconds": round(max(0.0, duration), 3),
        "distance_km": round(distance_km, 3),
        "lap_count": 0,
        "source_format": path.suffix.lower()[1:],
    }


def _bins(records: list[dict[str, object]], resolution: int) -> list[dict[str, Any]]:
    start = records[0]["timestamp"]
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        offset = int((record["timestamp"] - start).total_seconds())  # type: ignore[operator]
        grouped[offset // resolution * resolution].append(record)
    sequence: list[dict[str, Any]] = []
    for offset in sorted(grouped):
        items = grouped[offset]
        metrics: dict[str, float] = {}
        for key in {
            key
            for item in items
            for key in item
            if key not in {"timestamp", "distance_m"}
        }:
            values = [_number(item.get(key)) for item in items]
            clean = [value for value in values if value is not None]
            if clean:
                metrics[key] = round(sum(clean) / len(clean), 3)
        distances = [_number(item.get("distance_m")) for item in items]
        clean_distances = [value for value in distances if value is not None]
        if clean_distances:
            metrics["distance_m"] = round(max(clean_distances), 3)
        sequence.append(
            {"offset_seconds": offset, "sample_count": len(items), "metrics": metrics}
        )
    return sequence


def _load_activity(
    database: Path, source_root: Path, inventory_id: int
) -> tuple[Path, int, str, str, str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,file_format,sha256,data_date FROM raw_files "
            "WHERE activity_inventory_id=? AND integrity_state='verified' "
            "AND file_format IN ('fit','gpx','tcx') ORDER BY CASE file_format "
            "WHEN 'fit' THEN 0 WHEN 'gpx' THEN 1 ELSE 2 END, id",
            (inventory_id,),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise ValueError("activity_raw_missing")
    row = rows[0]
    path = source_root / "state/raw" / str(row[1])
    if not path.is_file() or path.is_symlink():
        raise ValueError("activity_raw_unavailable")
    return path, int(row[0]), str(row[2]), str(row[3]), str(row[4])


def build_activity_evidence(
    database: Path,
    source_root: Path,
    inventory_id: int,
    *,
    resolution_seconds: int = 30,
    start_offset_seconds: int | None = None,
    end_offset_seconds: int | None = None,
) -> dict[str, Any]:
    if resolution_seconds not in {1, 5, 30}:
        raise ValueError("activity_resolution_invalid")
    path, raw_file_id, file_format, raw_sha256, data_date = _load_activity(
        database, source_root, inventory_id
    )
    if file_format == "fit":
        records, summary = _fit_records(path)
    else:
        records, summary = _xml_records(path)
    total_duration = float(summary["duration_seconds"])
    start = 0 if start_offset_seconds is None else start_offset_seconds
    end = int(total_duration) if end_offset_seconds is None else end_offset_seconds
    if start < 0 or end <= start or end > max(int(total_duration) + 1, 1):
        raise ValueError("activity_segment_range_invalid")
    selected = [
        item
        for item in records
        if start
        <= int((item["timestamp"] - records[0]["timestamp"]).total_seconds())  # type: ignore[operator]
        < end
    ]
    if not selected:
        raise ValueError("activity_segment_empty")
    sequence = _bins(selected, resolution_seconds)
    summary = dict(summary)
    summary["duration_seconds"] = (
        round(end - start, 3) if start or end != int(total_duration) else total_duration
    )
    return {
        "schema_version": "activity_overview_v1"
        if resolution_seconds == 30
        else "activity_segment_v1",
        "status": "ready",
        "activity_inventory_id": inventory_id,
        "raw_file_id": raw_file_id,
        "raw_sha256": raw_sha256,
        "data_date": data_date,
        "format": file_format,
        "summary": summary,
        "sequence_resolution_seconds": resolution_seconds,
        "sequence": sequence,
        "gps_included": False,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--activity-inventory-id", type=int, required=True)
    parser.add_argument("--resolution-seconds", type=int, default=30)
    parser.add_argument("--start-offset-seconds", type=int)
    parser.add_argument("--end-offset-seconds", type=int)
    args = parser.parse_args()
    try:
        payload = build_activity_evidence(
            args.database,
            args.source_root,
            args.activity_inventory_id,
            resolution_seconds=args.resolution_seconds,
            start_offset_seconds=args.start_offset_seconds,
            end_offset_seconds=args.end_offset_seconds,
        )
    except ValueError as exc:
        payload = {
            "schema_version": "activity_overview_v1"
            if args.resolution_seconds == 30
            else "activity_segment_v1",
            "status": "blocked",
            "error_code": str(exc),
            "provider_calls": 0,
        }
    require_valid_payload(payload, payload["schema_version"])
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
