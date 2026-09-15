#!/usr/bin/env python3
"""Compile the smallest evidence envelope that a coach AI may receive."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
)


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
            "activity_inventory_id,byte_size FROM raw_files WHERE data_date=? "
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
                "byte_size": int(row[7]),
            }
        )
    return result


def _raw_rows_between(
    database: Path, start_date: str, through_date: str, resources: tuple[str, ...]
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in resources)
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,resource_kind,file_format,sha256,data_date,"
            "revision_no,activity_inventory_id,byte_size FROM raw_files "
            "WHERE data_date>=? AND data_date<=? AND integrity_state='verified' "
            f"AND resource_kind IN ({placeholders}) "
            "ORDER BY data_date DESC,revision_no DESC,id DESC",
            (start_date, through_date, *resources),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "raw_file_id": int(row[0]),
            "relative_path": str(row[1]),
            "resource": str(row[2]),
            "format": str(row[3]),
            "sha256": str(row[4]),
            "data_date": str(row[5]),
            "revision_no": int(row[6]),
            "activity_inventory_id": int(row[7]) if row[7] is not None else None,
            "byte_size": int(row[8]),
        }
        for row in rows
        if str(row[1]).startswith("garmin/health/")
    ]


def _verified_raw_path(source_root: Path, row: dict[str, Any]) -> Path:
    raw_root = Path(os.path.abspath(source_root / "state/raw"))
    relative = Path(str(row["relative_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("raw_evidence_integrity_invalid")
    path = Path(os.path.abspath(raw_root / relative))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("raw_evidence_integrity_invalid") from exc
    if (
        path.resolve(strict=True) != path
        or not path.is_relative_to(raw_root)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != int(row["byte_size"])
        or hashlib.sha256(path.read_bytes()).hexdigest() != str(row["sha256"])
    ):
        raise ValueError("raw_evidence_integrity_invalid")
    return path


def _health_evidence(
    source_root: Path, rows: list[dict[str, Any]], parser: Any
) -> list[dict[str, Any]]:
    evidence = []
    for row in rows:
        path = _verified_raw_path(source_root, row)
        parsed = parser.parse_evidence(
            path,
            resource_override=str(row["resource"]),
            expected_date_override=str(row["data_date"]),
        )
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


def _has_substantive_health_metric(item: dict[str, Any]) -> bool:
    metrics = item.get("metrics")
    if not isinstance(metrics, dict):
        return False
    for name in (
        "resting_heart_rate_bpm",
        "last_night_average",
        "weekly_average",
        "last_night_5_min_high",
        "median",
        "average",
        "vo2_max",
        "weight",
    ):
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    sample_count = metrics.get("sample_count")
    if isinstance(sample_count, int) and not isinstance(sample_count, bool):
        if sample_count > 0:
            return True
    aggregate = metrics.get("aggregate")
    return (
        isinstance(aggregate, dict)
        and isinstance(aggregate.get("count"), int)
        and not isinstance(aggregate.get("count"), bool)
        and int(aggregate["count"]) > 0
    )


def _missing_recent_health_metric(
    *, resource: str, unit: str, lookback_days: int
) -> dict[str, Any]:
    return {
        "resource": resource,
        "status": "missing",
        "value": None,
        "unit": unit,
        "observed_date": None,
        "age_days": None,
        "selection_kind": None,
        "lookback_days": lookback_days,
        "raw_file_id": None,
        "sha256": None,
    }


def _select_recent_health_metric(
    source_root: Path,
    rows: list[dict[str, Any]],
    parser: Any,
    *,
    report_date: date,
    review_date: date,
    resource: str,
    field: str,
    unit: str,
    lookback_days: int,
) -> dict[str, Any]:
    """Select the newest verified, correctly dated value inside a fixed window."""

    earliest = review_date - timedelta(days=lookback_days - 1)
    candidates = sorted(
        (
            row
            for row in rows
            if row.get("resource") == resource
            and earliest.isoformat()
            <= str(row.get("data_date"))
            <= review_date.isoformat()
        ),
        key=lambda row: (
            str(row["data_date"]),
            int(row.get("revision_no", 1)),
            int(row["raw_file_id"]),
        ),
        reverse=True,
    )
    for row in candidates:
        try:
            path = _verified_raw_path(source_root, row)
            parsed = parser.parse_evidence(
                path,
                resource_override=resource,
                expected_date_override=str(row["data_date"]),
            )
        except (OSError, ValueError):
            continue
        metrics = parsed.get("metrics") if isinstance(parsed, dict) else None
        if not isinstance(metrics, dict) or metrics.get("unit") != unit:
            continue
        value = metrics.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            continue
        observed = date.fromisoformat(str(row["data_date"]))
        return {
            "resource": resource,
            "status": "ready",
            "value": float(value),
            "unit": unit,
            "observed_date": observed.isoformat(),
            "age_days": (report_date - observed).days,
            "selection_kind": "exact_date"
            if observed == review_date
            else "latest_prior",
            "lookback_days": lookback_days,
            "raw_file_id": int(row["raw_file_id"]),
            "sha256": str(row["sha256"]),
        }
    return _missing_recent_health_metric(
        resource=resource, unit=unit, lookback_days=lookback_days
    )


def _recent_health_metrics(
    database: Path, source_root: Path, report_date: date, parser: Any
) -> dict[str, Any]:
    review_date = report_date - timedelta(days=1)
    earliest = review_date - timedelta(days=29)
    rows = _raw_rows_between(
        database,
        earliest.isoformat(),
        review_date.isoformat(),
        ("max_metrics", "weigh_ins"),
    )
    payload = {
        "schema_version": "recent_health_metrics_v1",
        "status": "ready",
        "report_date": report_date.isoformat(),
        "review_date": review_date.isoformat(),
        "metrics": {
            "vo2_max": _select_recent_health_metric(
                source_root,
                rows,
                parser,
                report_date=report_date,
                review_date=review_date,
                resource="max_metrics",
                field="vo2_max",
                unit="ml/kg/min",
                lookback_days=30,
            ),
            "weight": _select_recent_health_metric(
                source_root,
                rows,
                parser,
                report_date=report_date,
                review_date=review_date,
                resource="weigh_ins",
                field="weight",
                unit="kg",
                lookback_days=14,
            ),
        },
        "provider_calls": 0,
    }
    require_valid_payload(payload, "recent_health_metrics_v1")
    return payload


def record_recent_health_metrics(
    evidence_database: Path,
    evidence_source_root: Path,
    target_database: Path,
    report_date: date,
) -> dict[str, Any]:
    """Persist a deterministic snapshot without invoking AI or a Provider."""

    parser = _load_parse_module()
    payload = _recent_health_metrics(
        evidence_database, evidence_source_root, report_date, parser
    )
    manifest = {
        "schema_version": "recent_health_metrics_input_v1",
        "report_date": report_date.isoformat(),
        "review_date": payload["review_date"],
        "payload_sha256": sha256_text(canonical_json(payload)),
        "source_refs": [
            {
                "raw_file_id": item["raw_file_id"],
                "sha256": item["sha256"],
            }
            for item in payload["metrics"].values()
            if item["status"] == "ready"
        ],
        "provider_calls": 0,
    }
    digest = sha256_text(canonical_json(manifest))
    connection = connect(target_database)
    try:
        run_id = begin_run(
            connection,
            run_key=(
                f"training-report-publisher:recent-health:{report_date}:"
                f"{digest}:attempt-1"
            ),
            workflow_key=f"daily:{report_date.isoformat()}",
            dedupe_key=digest,
            skill_name="training-report-publisher",
            operation="render_daily",
            trigger_kind="manual",
            input_manifest=manifest,
            input_sha256=digest,
            target_from_date=report_date.isoformat(),
            target_through_date=report_date.isoformat(),
        )
        existing = connection.execute(
            "SELECT id,content_sha256 FROM skill_outputs WHERE skill_run_id=? "
            "AND schema_name='recent_health_metrics_v1' ORDER BY id",
            (run_id,),
        ).fetchall()
        if len(existing) == 1:
            return {
                "output_id": int(existing[0][0]),
                "output_sha256": str(existing[0][1]),
                "payload": payload,
            }
        if existing:
            raise ValueError("recent_health_metrics_output_ambiguous")
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="bounded_evidence",
            logical_key=f"training-coach:recent-health:{report_date.isoformat()}",
            schema_name="recent_health_metrics_v1",
            schema_version="1",
            content_json=payload,
            content_text=canonical_json(payload),
            lineage=[
                {
                    "raw_file_id": item["raw_file_id"],
                    "raw_sha256": item["sha256"],
                }
                for item in manifest["source_refs"]
            ],
            period_start_date=report_date.isoformat(),
            period_end_date=report_date.isoformat(),
        )
        finish_run(connection, run_id, status="succeeded")
        row = connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("recent_health_metrics_output_missing")
        return {
            "output_id": output_id,
            "output_sha256": str(row[0]),
            "payload": payload,
        }
    finally:
        connection.close()


def _activity_evidence(
    database: Path,
    source_root: Path,
    rows: list[dict[str, Any]],
    activity_module: Any,
    parser: Any,
    *,
    allowed_raw_ids: set[int] | None = None,
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
            activity_rows = [
                row for row in rows if row["activity_inventory_id"] == inventory_id
            ]
            for row in activity_rows:
                _verified_raw_path(source_root, row)
            media_rows = [
                row for row in activity_rows if row["format"] in {"fit", "gpx", "tcx"}
            ]
            if not media_rows:
                raise ValueError("activity_raw_missing")
            selected_raw_file_id: int | None = None
            selected_media: dict[str, Any] | None = None
            if allowed_raw_ids is not None:
                if len(media_rows) != 1:
                    raise ValueError("activity_raw_receipt_ambiguous")
                selected_media = media_rows[0]
                selected_raw_file_id = int(selected_media["raw_file_id"])
            evidence = activity_module.build_activity_evidence(
                database,
                source_root,
                int(inventory_id),
                raw_file_id=selected_raw_file_id,
                resolution_seconds=30,
            )
            if selected_media is not None and (
                evidence.get("raw_file_id") != selected_media["raw_file_id"]
                or evidence.get("raw_sha256") != selected_media["sha256"]
            ):
                raise ValueError("activity_raw_receipt_mismatch")
            weather = next(
                (row for row in activity_rows if row["resource"] == "activity_weather"),
                None,
            )
            if weather is not None:
                parsed_weather = parser.parse_evidence(
                    _verified_raw_path(source_root, weather),
                    resource_override="activity_weather",
                    expected_date_override=str(weather["data_date"]),
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


def _live_receipt(
    database: Path, output_id: int, report_date: date
) -> tuple[dict[str, Any], str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[2]) != "garmin_live_sync_receipt_v1":
        raise ValueError("garmin_live_sync_receipt_missing")
    if str(row[3]) != "succeeded":
        raise ValueError("garmin_live_sync_receipt_incomplete")
    receipt = json.loads(str(row[0]))
    if (
        receipt.get("status") != "succeeded"
        or receipt.get("workflow_key") != f"daily:{report_date.isoformat()}"
        or receipt.get("inventory_complete") is not True
    ):
        raise ValueError("garmin_live_sync_receipt_incomplete")
    return receipt, str(row[1])


def _rolling_receipt(
    database: Path, output_id: int, report_date: date
) -> tuple[dict[str, Any], dict[str, Any], str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[2]) != "garmin_rolling_week_receipt_v1":
        raise ValueError("garmin_rolling_sync_receipt_missing")
    if str(row[3]) != "succeeded":
        raise ValueError("garmin_rolling_sync_receipt_incomplete")
    receipt = json.loads(str(row[0]))
    windows = receipt.get("daily_windows")
    window = windows.get(report_date.isoformat()) if isinstance(windows, dict) else None
    if (
        receipt.get("status") != "succeeded"
        or receipt.get("workflow_key") != "m10:rolling-week:2026-08-11/2026-08-18"
        or not isinstance(window, dict)
        or window.get("report_date") != report_date.isoformat()
        or window.get("inventory_complete") is not True
    ):
        raise ValueError("garmin_rolling_sync_receipt_incomplete")
    return receipt, window, str(row[1])


def build_daily_context(
    database: Path,
    source_root: Path,
    report_date: date,
    *,
    live_sync_output_id: int | None = None,
    rolling_sync_output_id: int | None = None,
) -> dict[str, Any]:
    review_date = report_date - timedelta(days=1)
    parser = _load_parse_module()
    activity_module = _load_activity_module()
    receipt: dict[str, Any] | None = None
    receipt_sha: str | None = None
    allowed_raw_ids: set[int] | None = None
    receipt_window: dict[str, Any] | None = None
    if live_sync_output_id is not None and rolling_sync_output_id is not None:
        raise ValueError("multiple_live_sync_receipts")
    if rolling_sync_output_id is not None:
        receipt, receipt_window, receipt_sha = _rolling_receipt(
            database, rolling_sync_output_id, report_date
        )
        allowed_raw_ids = {
            int(value)
            for value in receipt_window.get("raw_file_ids", [])
            if isinstance(value, int) and not isinstance(value, bool)
        }
    elif live_sync_output_id is not None:
        receipt, receipt_sha = _live_receipt(database, live_sync_output_id, report_date)
        allowed_raw_ids = {
            int(value)
            for value in receipt.get("raw_file_ids", [])
            if isinstance(value, int) and not isinstance(value, bool)
        }

    review_health = [
        row
        for row in _raw_rows(database, review_date.isoformat(), health=True)
        if row["resource"] not in {"sleep", "max_metrics", "weigh_ins"}
        and (allowed_raw_ids is None or row["raw_file_id"] in allowed_raw_ids)
    ]
    sleep_rows = [
        row
        for row in _raw_rows(database, report_date.isoformat(), health=True)
        if row["resource"] == "sleep"
        and (allowed_raw_ids is None or row["raw_file_id"] in allowed_raw_ids)
    ]
    review_activity = [
        row
        for row in _raw_rows(database, review_date.isoformat(), health=False)
        if row["resource"] != "activity_inventory"
        and (allowed_raw_ids is None or row["raw_file_id"] in allowed_raw_ids)
    ]
    # A-014 explicitly authorizes only these two bounded historical lookups.
    # Other health evidence remains bound to the exact daily receipt/date above.
    recent_health = _recent_health_metrics(database, source_root, report_date, parser)
    selected_recent = [
        {
            "raw_file_id": item["raw_file_id"],
            "sha256": item["sha256"],
            "resource": item["resource"],
            "data_date": item["observed_date"],
            "metrics": {
                "resource": item["resource"],
                "metric": key,
                key: item["value"],
                "unit": item["unit"],
                "observed_date": item["observed_date"],
                "age_days": item["age_days"],
                "selection_kind": item["selection_kind"],
            },
            "parser": "recent_health_metrics_v1",
        }
        for key, item in recent_health["metrics"].items()
        if item["status"] == "ready"
    ]
    health = (
        _health_evidence(source_root, review_health + sleep_rows, parser)
        + selected_recent
    )
    sleep = [item for item in health if item["resource"] == "sleep"]
    activities = _activity_evidence(
        database,
        source_root,
        review_activity,
        activity_module,
        parser,
        allowed_raw_ids=allowed_raw_ids,
    )
    errors: list[str] = []
    review_health_evidence = [
        item for item in health if item.get("resource") != "sleep"
    ]
    if not any(_has_substantive_health_metric(item) for item in review_health_evidence):
        errors.append("daily_review_health_missing")
    ambiguous_sleep = any(
        item["metrics"].get("metric") == "main_sleep_ambiguous" for item in sleep
    )
    matching_sleep = [
        item
        for item in sleep
        if item["metrics"].get("completeness") == "complete"
        and item["metrics"].get("sleep_wake_date") == report_date.isoformat()
    ]
    if ambiguous_sleep:
        errors.append("daily_sleep_evidence_ambiguous")
    elif not matching_sleep:
        errors.append("daily_sleep_evidence_missing")
    elif len(matching_sleep) != 1:
        errors.append("daily_sleep_evidence_ambiguous")
    if review_activity and not activities:
        errors.append("daily_activity_evidence_missing")
    if receipt is not None:
        inventory_source = receipt_window if receipt_window is not None else receipt
        expected_inventory = int(inventory_source.get("inventory_count", -1))
        if expected_inventory < 0 or len(activities) != expected_inventory:
            errors.append("daily_activity_inventory_mismatch")
        if any(item.get("status") == "blocked" for item in activities):
            errors.append("daily_activity_evidence_blocked")
    result = {
        "schema_version": "daily_ai_context_v1",
        "status": "ready" if not errors else "blocked",
        "report_date": report_date.isoformat(),
        "review_date": review_date.isoformat(),
        "sleep_wake_date": report_date.isoformat(),
        "health": health,
        "activities": activities,
        "recent_health_metrics": recent_health,
        "recent_trend": _recent_trend(database, report_date),
        "goal": _goal(source_root),
        "errors": errors,
        "provider_calls": 0,
    }
    if receipt is not None and receipt_sha is not None:
        receipt_output_id = (
            rolling_sync_output_id
            if rolling_sync_output_id is not None
            else live_sync_output_id
        )
        if receipt_output_id is None:
            raise RuntimeError("garmin_live_sync_output_id_missing")
        result["live_sync"] = {
            "output_id": int(receipt_output_id),
            "sha256": receipt_sha,
            "inventory_complete": True,
            "inventory_count": int(
                (receipt_window if receipt_window is not None else receipt)[
                    "inventory_count"
                ]
            ),
        }
    return result


def build_weekly_context(
    database: Path,
    source_root: Path,
    week_ending: date,
    *,
    required_daily_output_ids: list[int] | None = None,
) -> dict[str, Any]:
    start = week_ending - timedelta(days=6)
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT so.id,so.content_json,so.content_sha256,so.period_start_date "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.output_kind='daily_summary' AND so.schema_name='daily_ai_result_v1' "
            "AND sr.status='succeeded' AND sr.skill_name='training-coach' "
            "AND sr.operation='daily_coach' AND so.period_start_date>=? "
            "AND so.period_start_date<=? ORDER BY so.period_start_date,so.id",
            (start.isoformat(), week_ending.isoformat()),
        ).fetchall()
    finally:
        connection.close()
    by_date: dict[str, Any] = {}
    required_ids = (
        set(required_daily_output_ids)
        if required_daily_output_ids is not None
        else None
    )
    for row in rows:
        if required_ids is not None and int(row[0]) not in required_ids:
            continue
        day = str(row[3])
        if day in by_date:
            if required_ids is not None:
                raise ValueError("weekly_daily_output_ambiguous")
        by_date[day] = row
    expected = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    missing = [day for day in expected if day not in by_date]
    if required_daily_output_ids is not None and (
        len(required_daily_output_ids) != 7
        or len(set(required_daily_output_ids)) != 7
        or {int(row[0]) for row in by_date.values()} != set(required_daily_output_ids)
    ):
        raise ValueError("weekly_daily_output_mismatch")
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
    raise SystemExit("legacy_runtime_retired")
