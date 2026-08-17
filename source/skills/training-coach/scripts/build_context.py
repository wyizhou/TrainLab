#!/usr/bin/env python3
"""Compile the smallest evidence envelope that a coach AI may receive."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import canonical_json, connect, sha256_text  # noqa: E402


def _load_parse_module() -> Any:
    path = Path(__file__).resolve().parent / "parse_raw.py"
    spec = importlib.util.spec_from_file_location("trainlab_parse_raw", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("parse_raw_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_activity_module() -> Any:
    path = Path(__file__).resolve().parent / "activity_evidence.py"
    spec = importlib.util.spec_from_file_location("trainlab_activity_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("activity_evidence_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _goal(source_root: Path) -> dict[str, str]:
    path = source_root / "goal.md"
    if not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
        raise ValueError("goal_missing_or_permissions")
    text = path.read_text(encoding="utf-8")
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text}


def _raw_rows(
    database: Path, day: str, *, health: bool | None = None
) -> list[dict[str, Any]]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,resource_kind,file_format,sha256,data_date,"
            "activity_inventory_id FROM raw_files WHERE data_date=? "
            "AND integrity_state='verified' ORDER BY id",
            (day,),
        ).fetchall()
    finally:
        connection.close()
    result = []
    for row in rows:
        is_health = str(row[1]).startswith("garmin/health/")
        if health is not None and is_health != health:
            continue
        result.append(
            {
                "raw_file_id": int(row[0]),
                "relative_path": str(row[1]),
                "resource": str(row[2]),
                "format": str(row[3]),
                "sha256": str(row[4]),
                "data_date": str(row[5]),
                "activity_inventory_id": int(row[6]) if row[6] is not None else None,
            }
        )
    return result


def _health_evidence(
    source_root: Path, rows: list[dict[str, Any]], parser: Any
) -> list[dict[str, Any]]:
    evidence = []
    for row in rows:
        path = source_root / "state/raw" / row["relative_path"]
        parsed = parser.parse_evidence(path)
        metrics = parsed.get("metrics") if isinstance(parsed, dict) else None
        evidence.append(
            {
                "raw_file_id": row["raw_file_id"],
                "sha256": row["sha256"],
                "resource": row["resource"],
                "data_date": row["data_date"],
                "metrics": metrics if isinstance(metrics, dict) else {},
                "parser": parsed.get("parser"),
            }
        )
    return evidence


def _activity_evidence(
    database: Path,
    source_root: Path,
    rows: list[dict[str, Any]],
    activity_module: Any,
    parser: Any,
) -> list[dict[str, Any]]:
    inventory_ids = sorted(
        {
            row["activity_inventory_id"]
            for row in rows
            if row["activity_inventory_id"] is not None
            and row["format"] in {"fit", "gpx", "tcx"}
        }
    )
    result = []
    for inventory_id in inventory_ids:
        try:
            evidence = activity_module.build_activity_evidence(
                database, source_root, int(inventory_id), resolution_seconds=30
            )
            weather = next(
                (
                    row
                    for row in rows
                    if row["activity_inventory_id"] == inventory_id
                    and row["resource"] == "activity_weather"
                ),
                None,
            )
            if weather is not None:
                parsed_weather = parser.parse_evidence(
                    source_root / "state/raw" / weather["relative_path"]
                )
                evidence["weather"] = {
                    "raw_file_id": weather["raw_file_id"],
                    "sha256": weather["sha256"],
                    "metrics": parsed_weather.get("metrics", {}),
                }
            result.append(evidence)
        except ValueError as exc:
            result.append(
                {
                    "status": "blocked",
                    "activity_inventory_id": int(inventory_id),
                    "error_code": str(exc),
                    "provider_calls": 0,
                }
            )
    return result


def _recent_trend(database: Path, report_date: date) -> dict[str, Any]:
    earliest = report_date - timedelta(days=14)
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT content_json,period_start_date,revision_no FROM skill_outputs "
            "WHERE output_kind='daily_summary' AND period_start_date>=? "
            "AND period_start_date<=? ORDER BY period_start_date DESC, revision_no DESC",
            (earliest.isoformat(), (report_date - timedelta(days=1)).isoformat()),
        ).fetchall()
    finally:
        connection.close()
    # A daily summary may have more than one immutable revision.  Select the
    # newest revision for each report date, then compress only the structured
    # metrics; never pass the historical report body to the model.
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            item = json.loads(str(row[0]))
        except json.JSONDecodeError:
            continue
        period = str(row[1])
        if period not in selected:
            selected[period] = item

    ordered = [selected[key] for key in sorted(selected)]
    sleep_hours: list[float] = []
    rhr_values: list[float] = []
    hrv_values: list[float] = []
    caution_days = 0
    running_km = 0.0
    activity_count = 0
    activity_days: set[str] = set()
    for item in ordered:
        if item.get("safety") == "caution":
            caution_days += 1
        summary_has_activity = False
        for metric in item.get("bounded_metrics", []):
            if not isinstance(metric, dict):
                continue
            details = metric.get("metrics")
            if isinstance(details, dict):
                resource = details.get("resource")
                duration = details.get("duration_seconds")
                if resource == "sleep" and isinstance(duration, (int, float)):
                    sleep_hours.append(float(duration) / 3600.0)
                if resource == "rhr":
                    value = details.get("resting_heart_rate_bpm")
                    if isinstance(value, (int, float)):
                        rhr_values.append(float(value))
                if resource == "hrv":
                    value = details.get("last_night_average")
                    if isinstance(value, (int, float)):
                        hrv_values.append(float(value))
                if metric.get("format") in {"fit", "gpx", "tcx"}:
                    summary_has_activity = True
                    distance = details.get("distance_km")
                    if isinstance(distance, (int, float)):
                        running_km += float(distance)
            # AI summaries use an intentionally small name/value contract.  It
            # is still structured evidence, so it can be compressed without
            # reopening the raw files or exposing the historical report body.
            name = str(metric.get("name", "")).lower()
            value = metric.get("value")
            unit = str(metric.get("unit", "")).lower()
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "sleep" in name and "duration" in name:
                    sleep_hours.append(
                        float(value) if unit == "hours" else float(value) / 3600.0
                    )
                if "resting" in name and "heart" in name:
                    rhr_values.append(float(value))
                if "hrv" in name:
                    hrv_values.append(float(value))
                if "distance" in name and unit in {"km", "kilometer", "kilometers"}:
                    running_km += float(value)
                    summary_has_activity = True
            if any(
                token in name
                for token in ("activity_", "review_activity", "running_distance")
            ):
                summary_has_activity = True
        if summary_has_activity:
            activity_count += 1
            summary_date = item.get("review_date", item.get("report_date"))
            if isinstance(summary_date, str):
                activity_days.add(summary_date)

    sleep_days = [
        item.get("report_date")
        for item in ordered
        if isinstance(item.get("report_date"), str)
    ]
    expected_days = {
        (report_date - timedelta(days=offset)).isoformat() for offset in range(1, 15)
    }
    missing_days = sorted(expected_days.difference(sleep_days))
    consecutive_insufficient = 0
    for item in reversed(ordered):
        durations = [
            float(metric["metrics"]["duration_seconds"]) / 3600.0
            for metric in item.get("bounded_metrics", [])
            if isinstance(metric, dict)
            and isinstance(metric.get("metrics"), dict)
            and metric["metrics"].get("resource") == "sleep"
            and isinstance(metric["metrics"].get("duration_seconds"), (int, float))
        ]
        if durations and durations[0] < 7:
            consecutive_insufficient += 1
        else:
            break

    def _change(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        return round(values[-1] - values[0], 3)

    trend = {
        "schema_version": "recent_trend_v1",
        "days_available": len(ordered),
        "sleep": {
            "average_hours": round(sum(sleep_hours) / len(sleep_hours), 2)
            if sleep_hours
            else None,
            "insufficient_days": sum(1 for value in sleep_hours if value < 7),
            "consecutive_insufficient_days": consecutive_insufficient,
        },
        "recovery": {
            "caution_days": caution_days,
            "rhr_average": round(sum(rhr_values) / len(rhr_values), 2)
            if rhr_values
            else None,
            "rhr_change": _change(rhr_values),
            "hrv_average": round(sum(hrv_values) / len(hrv_values), 2)
            if hrv_values
            else None,
            "hrv_change": _change(hrv_values),
        },
        "running": {
            "distance_km": round(running_km, 3),
            "activity_count": activity_count,
            "activity_days": len(activity_days),
        },
        "data_gaps": [f"daily_summary_missing:{day}" for day in missing_days],
    }
    trend["sha256"] = sha256_text(canonical_json(trend))
    return trend


def build_daily_context(
    database: Path, source_root: Path, report_date: date
) -> dict[str, Any]:
    review_date = report_date - timedelta(days=1)
    parser = _load_parse_module()
    activity_module = _load_activity_module()
    review_health = [
        row
        for row in _raw_rows(database, review_date.isoformat(), health=True)
        if row["resource"] != "sleep"
    ]
    sleep_rows = [
        row
        for row in _raw_rows(database, report_date.isoformat(), health=True)
        if row["resource"] == "sleep"
    ]
    review_activity = _raw_rows(database, review_date.isoformat(), health=False)
    health = _health_evidence(source_root, review_health + sleep_rows, parser)
    sleep = [item for item in health if item["resource"] == "sleep"]
    activities = _activity_evidence(
        database, source_root, review_activity, activity_module, parser
    )
    errors: list[str] = []
    if not review_health:
        errors.append("daily_review_health_missing")
    matching_sleep = [
        item
        for item in sleep
        if item["metrics"].get("completeness") == "complete"
        and item["metrics"].get("sleep_wake_date") == report_date.isoformat()
    ]
    if not matching_sleep:
        errors.append("daily_sleep_evidence_missing")
    elif len(matching_sleep) != 1:
        errors.append("daily_sleep_evidence_ambiguous")
    if review_activity and not activities:
        errors.append("daily_activity_evidence_missing")
    return {
        "schema_version": "daily_ai_context_v1",
        "status": "ready" if not errors else "blocked",
        "report_date": report_date.isoformat(),
        "review_date": review_date.isoformat(),
        "sleep_wake_date": report_date.isoformat(),
        "health": health,
        "activities": activities,
        "recent_trend": _recent_trend(database, report_date),
        "goal": _goal(source_root),
        "errors": errors,
        "provider_calls": 0,
    }


def build_weekly_context(
    database: Path, source_root: Path, week_ending: date
) -> dict[str, Any]:
    start = week_ending - timedelta(days=6)
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,content_json,content_sha256,period_start_date FROM skill_outputs "
            "WHERE output_kind='daily_summary' AND period_start_date>=? AND period_start_date<=? "
            "ORDER BY period_start_date",
            (start.isoformat(), week_ending.isoformat()),
        ).fetchall()
    finally:
        connection.close()
    by_date = {str(row[3]): row for row in rows}
    expected = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    missing = [day for day in expected if day not in by_date]
    dailies = []
    for day in expected:
        row = by_date.get(day)
        if row is None:
            continue
        dailies.append(
            {
                "output_id": int(row[0]),
                "sha256": str(row[2]),
                "content": json.loads(str(row[1])),
            }
        )
    return {
        "schema_version": "weekly_ai_context_v1",
        "status": "ready" if not missing else "blocked",
        "period": f"{start.isoformat()}/{week_ending.isoformat()}",
        "daily_reports": dailies,
        "missing_dates": missing,
        "goal": _goal(source_root),
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    target = date.fromisoformat(args.date)
    payload = (
        build_daily_context(args.database, args.source_root, target)
        if args.mode == "daily"
        else build_weekly_context(args.database, args.source_root, target)
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
