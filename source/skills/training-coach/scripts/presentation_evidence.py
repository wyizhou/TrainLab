"""Build host-only presentation evidence without changing the AI evidence envelope."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload
from skills._shared.state import canonical_json, connect

_ZONE_LABELS = ("低于Z1", "Z1", "Z2", "Z3", "Z4", "Z5", "高于Z5")
_SLEEP_LABELS = {"deep": "深睡", "light": "浅睡", "rem": "REM", "awake": "清醒"}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def presentation_heart_rate_zones(value: object) -> dict[str, Any] | None:
    """Convert provider durations to display percentages; never classify samples."""

    if not isinstance(value, dict):
        return None
    reference_index = value.get("reference_index")
    if (
        value.get("source") != "fit_session_time_in_hr_zone"
        or value.get("reference_mesg") != "session"
        or type(reference_index) is not int
        or reference_index != 0
    ):
        return None
    definition = value.get("definition_sha256")
    durations = value.get("durations_seconds")
    if (
        not isinstance(definition, str)
        or len(definition) != 64
        or any(character not in "0123456789abcdef" for character in definition)
        or not isinstance(durations, list)
        or len(durations) != len(_ZONE_LABELS)
    ):
        return None
    clean = [_number(item) for item in durations]
    if any(item is None or item < 0 for item in clean):
        return None
    values = [float(item) for item in clean if item is not None]
    total = sum(values)
    if total <= 0:
        return None
    return {
        "source": "fit_session_time_in_hr_zone",
        "definition_sha256": definition,
        "percentage_source": "derived_from_provider_duration",
        "segments": [
            {
                "label": label,
                "duration_seconds": round(duration, 3),
                "percentage": round(duration / total * 100, 2),
            }
            for label, duration in zip(_ZONE_LABELS, values)
        ],
    }


def _sleep(context: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        item
        for item in context.get("health", [])
        if isinstance(item, dict)
        and item.get("resource") == "sleep"
        and isinstance(item.get("metrics"), dict)
        and item["metrics"].get("completeness") == "complete"
        and item["metrics"].get("sleep_wake_date") == context.get("sleep_wake_date")
    ]
    if len(candidates) != 1:
        return None
    item = candidates[0]
    metrics = item["metrics"]
    duration = _number(metrics.get("duration_seconds"))
    if (
        not isinstance(item.get("raw_file_id"), int)
        or not isinstance(item.get("sha256"), str)
        or not isinstance(metrics.get("sleep_start"), str)
        or not isinstance(metrics.get("sleep_end"), str)
        or duration is None
        or duration < 0
    ):
        return None
    result: dict[str, Any] = {
        "raw_file_id": int(item["raw_file_id"]),
        "raw_sha256": str(item["sha256"]),
        "start": metrics["sleep_start"],
        "end": metrics["sleep_end"],
        "duration_seconds": duration,
        "completeness": "complete",
    }
    stage_data = metrics.get("sleep_stages")
    stage_durations = (
        stage_data.get("durations_seconds") if isinstance(stage_data, dict) else None
    )
    if isinstance(stage_durations, dict):
        ordered = [_number(stage_durations.get(key)) for key in _SLEEP_LABELS]
        if all(value is not None and value >= 0 for value in ordered):
            values = [float(value) for value in ordered if value is not None]
            total = sum(values)
            if total > 0:
                result["stages"] = [
                    {
                        "label": label,
                        "duration_seconds": round(stage_duration, 3),
                        "percentage": round(stage_duration / total * 100, 2),
                    }
                    for label, stage_duration in zip(_SLEEP_LABELS.values(), values)
                ]
    return result


def _metric(
    context: dict[str, Any],
    *,
    resource: str,
    field: str,
    unit: str,
    observed_date: str,
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in context.get("health", [])
        if isinstance(item, dict)
        and item.get("resource") == resource
        and isinstance(item.get("metrics"), dict)
    ]
    if len(candidates) != 1:
        return None
    item = candidates[0]
    value = _number(item["metrics"].get(field))
    if (
        value is None
        or not isinstance(item.get("raw_file_id"), int)
        or not isinstance(item.get("sha256"), str)
    ):
        return None
    result: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "observed_date": observed_date,
    }
    result["raw_file_id"] = int(item["raw_file_id"])
    result["raw_sha256"] = str(item["sha256"])
    return result


def _recent_metric(context: dict[str, Any], name: str) -> dict[str, Any] | None:
    snapshot = context.get("recent_health_metrics")
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    item = metrics.get(name) if isinstance(metrics, dict) else None
    if not isinstance(item, dict) or item.get("status") != "ready":
        return None
    value = _number(item.get("value"))
    if (
        value is None
        or not isinstance(item.get("unit"), str)
        or not isinstance(item.get("observed_date"), str)
        or not isinstance(item.get("raw_file_id"), int)
        or not isinstance(item.get("sha256"), str)
    ):
        return None
    result: dict[str, Any] = {
        "value": value,
        "unit": str(item["unit"]),
        "observed_date": str(item["observed_date"]),
    }
    result["raw_file_id"] = int(item["raw_file_id"])
    result["raw_sha256"] = str(item["sha256"])
    return result


def _activities(context: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in context.get("activities", []):
        if not isinstance(item, dict) or item.get("status") != "ready":
            continue
        summary = item.get("summary")
        if (
            not isinstance(summary, dict)
            or not isinstance(item.get("activity_inventory_id"), int)
            or not isinstance(item.get("raw_file_id"), int)
            or not isinstance(item.get("raw_sha256"), str)
        ):
            continue
        duration = _number(summary.get("duration_seconds"))
        if duration is None or duration < 0:
            continue
        distance = _number(summary.get("distance_km"))
        activity: dict[str, Any] = {
            "activity_inventory_id": int(item["activity_inventory_id"]),
            "raw_file_id": int(item["raw_file_id"]),
            "raw_sha256": str(item["raw_sha256"]),
            "activity_kind": str(summary.get("activity_kind") or "activity"),
            "distance_km": distance,
            "duration_seconds": duration,
            "pace_seconds_per_km": (
                round(duration / distance, 3)
                if distance is not None and distance > 0
                else None
            ),
            "heart_rate_average_bpm": _number(summary.get("heart_rate_average_bpm")),
            "heart_rate_maximum_bpm": _number(summary.get("heart_rate_maximum_bpm")),
            "heart_rate_series": [],
        }
        for point in item.get("sequence", []):
            if not isinstance(point, dict) or not isinstance(
                point.get("metrics"), dict
            ):
                continue
            offset = point.get("offset_seconds")
            heart_rate = _number(point["metrics"].get("heart_rate_bpm"))
            if isinstance(offset, int) and heart_rate is not None and heart_rate >= 0:
                activity["heart_rate_series"].append(
                    {"offset_seconds": offset, "value": heart_rate}
                )
        zones = presentation_heart_rate_zones(summary.get("observed_heart_rate_zones"))
        if zones is not None:
            activity["observed_heart_rate_zones"] = zones
        result.append(activity)
    return result


def _trend(context: dict[str, Any]) -> dict[str, Any]:
    trend = context.get("recent_trend")
    if not isinstance(trend, dict):
        return {"days_available": 0}
    sleep_value = trend.get("sleep")
    recovery_value = trend.get("recovery")
    running_value = trend.get("running")
    sleep: dict[str, Any] = sleep_value if isinstance(sleep_value, dict) else {}
    recovery: dict[str, Any] = (
        recovery_value if isinstance(recovery_value, dict) else {}
    )
    running: dict[str, Any] = running_value if isinstance(running_value, dict) else {}
    result: dict[str, Any] = {
        "days_available": int(trend.get("days_available", 0)),
        "sleep_average_hours": _number(sleep.get("average_hours")),
        "sleep_insufficient_days": int(sleep.get("insufficient_days", 0)),
        "caution_days": int(recovery.get("caution_days", 0)),
        "rhr_average": _number(recovery.get("rhr_average")),
        "hrv_average": _number(recovery.get("hrv_average")),
        "running_distance_km": max(0.0, _number(running.get("distance_km")) or 0.0),
        "activity_count": max(0, int(running.get("activity_count", 0))),
        "data_gap_count": len(trend.get("data_gaps", []))
        if isinstance(trend.get("data_gaps"), list)
        else 0,
    }
    return result


def _load_daily_result(
    database: Path, output_id: int
) -> tuple[dict[str, Any], str, str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status,"
            "sr.skill_name,sr.operation FROM skill_outputs so "
            "JOIN skill_runs sr ON sr.id=so.skill_run_id WHERE so.id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if (
        row is None
        or str(row[2]) != "daily_ai_result_v2"
        or str(row[3]) != "succeeded"
        or str(row[4]) != "training-coach"
        or str(row[5]) != "daily_coach"
    ):
        raise ValueError("daily_presentation_source_output_invalid")
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise ValueError("daily_presentation_source_output_invalid") from exc
    require_valid_payload(payload, "daily_ai_result_v2")
    content_sha256 = str(row[1])
    if len(content_sha256) != 64:
        raise ValueError("daily_presentation_source_output_invalid")
    payload_sha256 = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return payload, content_sha256, payload_sha256


def build_daily_presentation_evidence(
    database: Path,
    context: dict[str, Any],
    *,
    output_id: int,
) -> dict[str, Any]:
    daily_result, output_sha256, payload_sha256 = _load_daily_result(
        database, output_id
    )
    require_valid_payload(daily_result, "daily_ai_result_v2")
    if (
        context.get("status") != "ready"
        or context.get("errors") not in ([], None)
        or any(
            isinstance(item, dict) and item.get("status") != "ready"
            for item in context.get("activities", [])
        )
    ):
        raise ValueError("daily_presentation_context_blocked")
    for field in ("report_date", "review_date", "sleep_wake_date"):
        if daily_result.get(field) != context.get(field):
            raise ValueError("daily_presentation_context_mismatch")
    payload = {
        "schema_version": "daily_presentation_evidence_v1",
        "status": "ready" if daily_result["status"] == "succeeded" else "blocked",
        "error_code": daily_result.get("error_code"),
        "report_date": daily_result["report_date"],
        "review_date": daily_result["review_date"],
        "sleep_wake_date": daily_result["sleep_wake_date"],
        "safety": daily_result["safety"],
        "source_daily_result": {
            "output_id": output_id,
            "sha256": output_sha256,
            "content_json_sha256": payload_sha256,
        },
        "activities": _activities(context),
        "sleep": _sleep(context),
        "health": {
            "rhr": _metric(
                context,
                resource="rhr",
                field="resting_heart_rate_bpm",
                unit="bpm",
                observed_date=str(daily_result["review_date"]),
            ),
            "hrv": _metric(
                context,
                resource="hrv",
                field="last_night_average",
                unit="ms",
                observed_date=str(daily_result["review_date"]),
            ),
            "vo2_max": _recent_metric(context, "vo2_max"),
            "weight": _recent_metric(context, "weight"),
        },
        "recent_trend": _trend(context),
        "provider_calls": 0,
    }
    require_valid_payload(payload, "daily_presentation_evidence_v1")
    return payload
