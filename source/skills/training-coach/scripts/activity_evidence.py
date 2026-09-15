#!/usr/bin/env python3
"""Build bounded activity evidence from registered FIT/GPX/TCX files.

The output deliberately contains no coordinates, route points, names, or raw
payloads.  FIT/GPX/TCX are parsed locally; the provider is never contacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
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


def _finite_vector(value: object, *, length: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number) or number < 0:
            return None
        result.append(number)
    return result


def _session_zone_summary(candidates: list[dict[str, object]]) -> dict[str, Any] | None:
    """Return only one valid provider session vector; never classify HR samples."""

    if len(candidates) != 1:
        return None
    fields = candidates[0]
    reference_index = fields.get("reference_index")
    if type(reference_index) is not int or reference_index != 0:
        return None
    durations = _finite_vector(fields.get("time_in_hr_zone"), length=7)
    boundaries = _finite_vector(fields.get("hr_zone_high_boundary"), length=6)
    if durations is None or boundaries is None:
        return None
    if any(right <= left for left, right in zip(boundaries, boundaries[1:])):
        return None
    definition_sha256 = hashlib.sha256(
        json.dumps(boundaries, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return {
        "source": "fit_session_time_in_hr_zone",
        "reference_mesg": "session",
        "reference_index": 0,
        "durations_seconds": durations,
        "definition_sha256": definition_sha256,
    }


def _fit_records(
    path: Path, *, include_technical: bool = False
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    try:
        import fitdecode
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ValueError("fitdecode_unavailable") from exc
    records: list[dict[str, object]] = []
    laps = 0
    technical_laps: list[dict[str, object]] = []
    activity_kind: str | None = None
    all_distances: list[float] = []
    session_zone_candidates: list[dict[str, object]] = []
    session_summaries: list[dict[str, object]] = []
    with fitdecode.FitReader(path) as reader:
        for frame in reader:
            name = str(getattr(frame, "name", "")).lower()
            fields = _field_map(frame)
            if name == "lap":
                laps += 1
                if include_technical:
                    intensity = str(fields.get("intensity", "")).strip().lower()
                    role = {
                        "interval": "work",
                        "work": "work",
                        "recovery": "recovery",
                        "rest": "recovery",
                        "warmup": "warmup",
                        "cooldown": "cooldown",
                    }.get(intensity, "unclassified")
                    lap: dict[str, object] = {
                        "lap_index": len(technical_laps),
                        "lap_role": role,
                        "role_source": "fit_lap_intensity"
                        if role != "unclassified"
                        else "unclassified",
                    }
                    for sources, target in (
                        (
                            ("total_timer_time", "total_elapsed_time"),
                            "duration_seconds",
                        ),
                        (("total_distance",), "distance_m"),
                        (("avg_power",), "average_power_watts"),
                        (("avg_cadence",), "average_cadence_spm"),
                        (("avg_heart_rate",), "average_heart_rate_bpm"),
                    ):
                        numeric = next(
                            (
                                _number(fields.get(source))
                                for source in sources
                                if _number(fields.get(source)) is not None
                            ),
                            None,
                        )
                        if numeric is not None:
                            lap[target] = numeric
                    technical_laps.append(lap)
            if name == "sport":
                candidate = fields.get("sport") or fields.get("sub_sport")
                if isinstance(candidate, str) and candidate:
                    activity_kind = candidate
            if name == "session":
                session_summaries.append(fields)
            if name == "time_in_zone":
                reference = str(fields.get("reference_mesg", "")).lower()
                if reference == "session":
                    session_zone_candidates.append(fields)
            if name != "record":
                continue
            timestamp = _timestamp(fields.get("timestamp"))
            if timestamp is None:
                continue
            distance = _number(fields.get("distance"))
            if distance is not None:
                all_distances.append(distance)
            item: dict[str, object] = {"timestamp": timestamp}
            for sources, target in (
                (("heart_rate",), "heart_rate_bpm"),
                (("cadence",), "cadence_spm"),
                (("power",), "power_watts"),
                (("speed", "enhanced_speed"), "speed_mps"),
                (("altitude", "enhanced_altitude"), "elevation_m"),
                (("temperature",), "temperature_c"),
                (("distance",), "distance_m"),
                (("step_length",), "step_length_m"),
                (("stance_time", "ground_contact_time"), "ground_contact_time_ms"),
                (("vertical_oscillation",), "vertical_oscillation_mm"),
                (("vertical_ratio",), "vertical_ratio_pct"),
            ):
                numeric = next(
                    (
                        _number(fields.get(source))
                        for source in sources
                        if _number(fields.get(source)) is not None
                    ),
                    None,
                )
                if numeric is not None:
                    item[target] = numeric
            records.append(item)
    if not records:
        raise ValueError("activity_timestamp_missing")
    duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()  # type: ignore[operator]
    summary: dict[str, Any] = {
        "activity_kind": activity_kind,
        "duration_seconds": round(max(0.0, duration), 3),
        "distance_km": round(max(all_distances) / 1000, 3) if all_distances else None,
        "lap_count": laps,
        "source_format": "fit",
    }
    if len(session_summaries) == 1:
        average = _number(session_summaries[0].get("avg_heart_rate"))
        maximum = _number(session_summaries[0].get("max_heart_rate"))
        if average is not None and average >= 0:
            summary["heart_rate_average_bpm"] = average
        if maximum is not None and maximum >= 0:
            summary["heart_rate_maximum_bpm"] = maximum
    zones = _session_zone_summary(session_zone_candidates)
    if zones is not None:
        summary["observed_heart_rate_zones"] = zones
    if include_technical:
        summary["technical_laps"] = technical_laps
    return records, summary


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
    database: Path,
    source_root: Path,
    inventory_id: int,
    *,
    raw_file_id: int | None = None,
) -> tuple[Path, int, str, str, str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        parameters: tuple[int, ...]
        exact_clause = ""
        if raw_file_id is None:
            parameters = (inventory_id,)
        else:
            exact_clause = "AND id=? "
            parameters = (inventory_id, raw_file_id)
        rows = connection.execute(
            "SELECT id,relative_path,file_format,sha256,data_date,byte_size FROM raw_files "
            "WHERE activity_inventory_id=? AND integrity_state='verified' "
            f"AND file_format IN ('fit','gpx','tcx') {exact_clause}"
            "ORDER BY CASE file_format WHEN 'fit' THEN 0 WHEN 'gpx' THEN 1 ELSE 2 END, "
            "revision_no DESC, id DESC",
            parameters,
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise ValueError(
            "activity_raw_receipt_mismatch"
            if raw_file_id is not None
            else "activity_raw_missing"
        )
    row = rows[0]
    raw_root = Path(os.path.abspath(source_root / "state/raw"))
    relative = Path(str(row[1]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("activity_raw_integrity_invalid")
    path = Path(os.path.abspath(raw_root / relative))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("activity_raw_integrity_invalid") from exc
    if (
        path.resolve(strict=True) != path
        or not path.is_relative_to(raw_root)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != int(row[5])
        or hashlib.sha256(path.read_bytes()).hexdigest() != str(row[3])
    ):
        raise ValueError("activity_raw_integrity_invalid")
    return path, int(row[0]), str(row[2]), str(row[3]), str(row[4])


def build_activity_evidence(
    database: Path,
    source_root: Path,
    inventory_id: int,
    *,
    raw_file_id: int | None = None,
    resolution_seconds: int = 30,
    start_offset_seconds: int | None = None,
    end_offset_seconds: int | None = None,
) -> dict[str, Any]:
    if resolution_seconds not in {1, 5, 30}:
        raise ValueError("activity_resolution_invalid")
    path, raw_file_id, file_format, raw_sha256, data_date = _load_activity(
        database, source_root, inventory_id, raw_file_id=raw_file_id
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


def build_activity_technical_input(
    database: Path,
    source_root: Path,
    inventory_id: int,
    *,
    raw_file_id: int,
) -> dict[str, Any]:
    """Load FIT once during daily evidence construction for v4 technical facts.

    The returned mapping is an internal Host envelope, not an AI or persisted
    raw payload.  It contains no coordinates, route/name fields or raw bytes.
    """

    path, verified_raw_id, file_format, raw_sha256, data_date = _load_activity(
        database, source_root, inventory_id, raw_file_id=raw_file_id
    )
    if file_format != "fit":
        records, summary = _xml_records(path)
        technical_laps: list[dict[str, object]] = []
    else:
        records, summary = _fit_records(path, include_technical=True)
        raw_laps = summary.pop("technical_laps", [])
        technical_laps = raw_laps if isinstance(raw_laps, list) else []
    sequence = _bins(records, 30)
    expected_bins = max(1, math.ceil(float(summary["duration_seconds"]) / 30))
    return {
        "activity_inventory_id": inventory_id,
        "raw_file_id": verified_raw_id,
        "raw_sha256": raw_sha256,
        "activity_date": data_date,
        "activity_kind": str(summary.get("activity_kind") or "activity"),
        "distance_km": summary.get("distance_km"),
        "duration_seconds": float(summary["duration_seconds"]),
        "average_heart_rate_bpm": summary.get("heart_rate_average_bpm"),
        "maximum_heart_rate_bpm": summary.get("heart_rate_maximum_bpm"),
        "coverage": {
            "summary": 1.0,
            "sequence": round(min(1.0, len(sequence) / expected_bins), 4),
        },
        "missing_fields": [],
        "uncertainty": [],
        "sequence_resolution_seconds": 30,
        "sequence": sequence,
        "laps": technical_laps,
        "observed_heart_rate_zones": summary.get("observed_heart_rate_zones"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--activity-inventory-id", type=int, required=True)
    parser.add_argument("--raw-file-id", type=int)
    parser.add_argument("--resolution-seconds", type=int, default=30)
    parser.add_argument("--start-offset-seconds", type=int)
    parser.add_argument("--end-offset-seconds", type=int)
    args = parser.parse_args()
    try:
        payload = build_activity_evidence(
            args.database,
            args.source_root,
            args.activity_inventory_id,
            raw_file_id=args.raw_file_id,
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
    raise SystemExit("legacy_runtime_retired")
