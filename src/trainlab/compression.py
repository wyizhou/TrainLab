from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import Settings
from .db import transaction
from .util import atomic_write_json, iso_utc, stable_hash, utc_now

SUMMARY_ALGORITHM_VERSION = 3


def _date_bounds(connection) -> tuple[date | None, date | None]:
    row = connection.execute(
        """SELECT MIN(day) AS minimum, MAX(day) AS maximum FROM (
               SELECT local_date AS day FROM health_records WHERE is_current=1 AND local_date IS NOT NULL
               UNION ALL
               SELECT local_date AS day FROM activities
               UNION ALL
               SELECT reply_local_date AS day FROM feedback_messages
           )"""
    ).fetchone()
    return (date.fromisoformat(row["minimum"]) if row["minimum"] else None, date.fromisoformat(row["maximum"]) if row["maximum"] else None)


def _metric_rows(connection, day: date) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT hr.id AS record_id, hr.sheet_name, hm.metric_key,
                      hm.value_number, hm.value_text, hm.standard_unit
               FROM health_records hr
               JOIN health_metrics hm ON hm.health_record_id=hr.id
               WHERE hr.is_current=1 AND hr.local_date=?
               ORDER BY hr.sheet_name, hm.metric_key""",
            (day.isoformat(),),
        )
    ]


def _activity_rollups(connection, day: date) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    activities = connection.execute(
        """SELECT id, sport_type, start_time_utc, duration_seconds, source_application
           FROM activities WHERE local_date=? ORDER BY start_time_utc""",
        (day.isoformat(),),
    ).fetchall()
    for activity in activities:
        metrics = {
            row["metric_key"]: {"value": row["value_number"] if row["value_number"] is not None else row["value_text"], "unit": row["unit"]}
            for row in connection.execute(
                """SELECT metric_key, value_number, value_text, unit FROM activity_metrics
                   WHERE activity_id=? AND segment_id IS NULL""",
                (activity["id"],),
            )
        }
        output.append(
            {
                "activity_id": activity["id"],
                "sport": activity["sport_type"],
                "start_time_utc": activity["start_time_utc"],
                "duration_seconds": activity["duration_seconds"],
                "source_application": activity["source_application"],
                "metrics": metrics,
            }
        )
    return output


def build_daily_rollup(connection, day: date) -> dict[str, Any]:
    health_rows = _metric_rows(connection, day)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in health_rows:
        grouped.setdefault(row.pop("sheet_name"), []).append(row)
    feedback = [
        {"feedback_id": row["id"], "structured": json.loads(row["structured_json"] or "{}")}
        for row in connection.execute(
            "SELECT id, structured_json FROM feedback_messages WHERE reply_local_date=?",
            (day.isoformat(),),
        )
    ]
    return {
        "local_date": day.isoformat(),
        "health": {key: values for key, values in grouped.items() if key != "Sleep"},
        "sleep": grouped.get("Sleep", []),
        "activities": _activity_rollups(connection, day),
        "feedback": feedback,
        "evidence": {
            "health_record_ids": sorted({row["record_id"] for rows in grouped.values() for row in rows}),
            "activity_ids": [item["activity_id"] for item in _activity_rollups(connection, day)],
            "feedback_ids": [item["feedback_id"] for item in feedback],
        },
    }


def _period_rollup(connection, period_type: str, start: date, end: date, daily: list[dict[str, Any]]) -> dict[str, Any]:
    sport_totals: dict[str, dict[str, float | int]] = {}
    key_sessions: list[dict[str, Any]] = []
    evidence_health: set[int] = set()
    evidence_activities: set[int] = set()
    evidence_feedback: set[int] = set()
    health_values: dict[str, list[float]] = {}
    sleep_values: dict[str, list[float]] = {}
    technique_values: dict[str, dict[str, list[float]]] = {}
    for item in daily:
        evidence_health.update(item["evidence"]["health_record_ids"])
        evidence_activities.update(item["evidence"]["activity_ids"])
        evidence_feedback.update(item["evidence"]["feedback_ids"])
        for rows in item["health"].values():
            for metric in rows:
                if metric["value_number"] is not None:
                    health_values.setdefault(metric["metric_key"], []).append(float(metric["value_number"]))
        for metric in item["sleep"]:
            if metric["value_number"] is not None:
                sleep_values.setdefault(metric["metric_key"], []).append(float(metric["value_number"]))
        for activity in item["activities"]:
            sport = activity["sport"]
            total = sport_totals.setdefault(sport, {"count": 0, "duration_seconds": 0.0, "distance_m": 0.0})
            total["count"] = int(total["count"]) + 1
            total["duration_seconds"] = float(total["duration_seconds"]) + float(activity["duration_seconds"] or 0)
            distance = activity["metrics"].get("total_distance", {}).get("value")
            if isinstance(distance, (int, float)):
                total["distance_m"] = float(total["distance_m"]) + float(distance)
            key_sessions.append(
                {
                    "activity_id": activity["activity_id"],
                    "date": item["local_date"],
                    "sport": sport,
                    "duration_seconds": activity["duration_seconds"],
                    "distance_m": distance,
                }
            )
            retained_technique = {
                "avg_heart_rate",
                "max_heart_rate",
                "avg_running_cadence",
                "avg_power",
                "avg_step_length",
                "avg_vertical_oscillation",
                "avg_vertical_ratio",
                "avg_stance_time",
                "training_load_peak",
            }
            for metric_key, metric in activity["metrics"].items():
                value = metric.get("value")
                if metric_key in retained_technique and isinstance(value, (int, float)):
                    technique_values.setdefault(sport, {}).setdefault(metric_key, []).append(float(value))
    active_facts = [
        dict(row)
        for row in connection.execute(
            """SELECT id, fact_type, fact_key, value_json, effective_local_date, expires_local_date, scope
               FROM user_facts
               WHERE effective_local_date<=? AND (expires_local_date IS NULL OR expires_local_date>=?)
               ORDER BY effective_local_date""",
            (end.isoformat(), start.isoformat()),
        )
    ]
    return {
        "schema_version": SUMMARY_ALGORITHM_VERSION,
        "period_type": period_type,
        "period_start_local": start.isoformat(),
        "period_end_local": end.isoformat(),
        "daily_rollups": daily,
        "sport_totals": sport_totals,
        "key_sessions": key_sessions,
        "health_recovery": {key: _series_summary(values) for key, values in sorted(health_values.items())},
        "technique_trends": {
            sport: {key: _series_summary(values) for key, values in sorted(metrics.items())}
            for sport, metrics in sorted(technique_values.items())
        },
        "sleep_recovery": {
            "days_with_sleep_data": sum(1 for item in daily if item["sleep"]),
            "metrics": {key: _series_summary(values) for key, values in sorted(sleep_values.items())},
        },
        "injuries": [fact for fact in active_facts if fact["fact_type"] == "injury"],
        "feedback": [item for item in daily if item["feedback"]],
        "strength_progress": {"mode": "movement_only"},
        "adherence": {"status": "not_computable_without_plan_log"},
        "anomalies": [],
        "evidence": {
            "health_record_ids": sorted(evidence_health),
            "activity_ids": sorted(evidence_activities),
            "feedback_ids": sorted(evidence_feedback),
            "fact_ids": [fact["id"] for fact in active_facts],
        },
    }


def _series_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "average": round(sum(values) / len(values), 4),
        "minimum": round(min(values), 4),
        "maximum": round(max(values), 4),
        "first": round(values[0], 4),
        "latest": round(values[-1], 4),
    }


def _week_ranges(minimum: date, complete_through: date) -> Iterable[tuple[date, date]]:
    current = minimum - timedelta(days=minimum.weekday())
    while current + timedelta(days=6) <= complete_through:
        yield current, current + timedelta(days=6)
        current += timedelta(days=7)


def _month_ranges(minimum: date, complete_through: date) -> Iterable[tuple[date, date]]:
    current = date(minimum.year, minimum.month, 1)
    while True:
        end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        if end > complete_through:
            break
        yield current, end
        current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)


def _latest_weekly_daily(connection, start: date, end: date) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT ps.summary_json FROM period_summaries ps
           JOIN (
               SELECT period_start_local, period_end_local, MAX(id) AS latest_id
               FROM period_summaries WHERE period_type='weekly'
               GROUP BY period_start_local, period_end_local
           ) latest ON latest.latest_id=ps.id
           WHERE ps.period_end_local>=? AND ps.period_start_local<=?
           ORDER BY ps.period_start_local""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        for daily in json.loads(row["summary_json"]).get("daily_rollups", []):
            if start.isoformat() <= daily["local_date"] <= end.isoformat():
                by_date[daily["local_date"]] = daily
    return [by_date[key] for key in sorted(by_date)]


def _insert_summary(connection, period_type: str, start: date, end: date, source_kind: str, summary: dict[str, Any]) -> bool:
    evidence = summary["evidence"]
    source_hash = stable_hash(
        {"algorithm_version": SUMMARY_ALGORITHM_VERSION, "daily": summary["daily_rollups"], "evidence": evidence}
    )
    exists = connection.execute(
        """SELECT 1 FROM period_summaries
           WHERE period_type=? AND period_start_local=? AND period_end_local=? AND source_hash=?""",
        (period_type, start.isoformat(), end.isoformat(), source_hash),
    ).fetchone()
    if exists:
        return False
    connection.execute(
        """INSERT INTO period_summaries(
               period_type, period_start_local, period_end_local, source_kind,
               summary_json, evidence_json, source_hash, created_at_utc
           ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            period_type,
            start.isoformat(),
            end.isoformat(),
            source_kind,
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            source_hash,
            iso_utc(),
        ),
    )
    return True


def ensure_summaries(settings: Settings, connection, *, as_of: datetime | None = None) -> dict[str, Any]:
    timezone = ZoneInfo(settings.timezone)
    local_now = (as_of or utc_now()).astimezone(timezone)
    complete_through = local_now.date() - timedelta(days=1)
    minimum, maximum = _date_bounds(connection)
    state_path = settings.path("state_directory") / "compression_state.json"
    status: dict[str, Any] = {
        "checked_at_utc": iso_utc(),
        "complete_through_local": complete_through.isoformat(),
        "generated": {},
        "latest_data_date": maximum.isoformat() if maximum else None,
    }
    if minimum is None:
        atomic_write_json(state_path, status)
        return status
    enabled = {item["kind"]: item for item in settings.compression.get("periods", []) if item.get("enabled", True)}
    with transaction(connection):
        if "day" in enabled:
            generated = 0
            current = minimum
            while current <= complete_through:
                summary = _period_rollup(connection, "daily", current, current, [build_daily_rollup(connection, current)])
                generated += int(_insert_summary(connection, "daily", current, current, "raw_rollups", summary))
                current += timedelta(days=1)
            status["generated"]["daily"] = generated
        if "week" in enabled:
            generated = 0
            for start, end in _week_ranges(minimum, complete_through):
                daily = [build_daily_rollup(connection, start + timedelta(days=index)) for index in range(7)]
                summary = _period_rollup(connection, "weekly", start, end, daily)
                generated += int(_insert_summary(connection, "weekly", start, end, "raw_rollups", summary))
            status["generated"]["weekly"] = generated
        if "month" in enabled:
            generated = 0
            for start, end in _month_ranges(minimum, complete_through):
                daily = _latest_weekly_daily(connection, start, end)
                expected_days = (end - start).days + 1
                if len(daily) != expected_days:
                    continue
                summary = _period_rollup(connection, "monthly", start, end, daily)
                generated += int(_insert_summary(connection, "monthly", start, end, "weekly_daily_rollups", summary))
            status["generated"]["monthly"] = generated
    status["last_success_at_utc"] = iso_utc()
    status["period_config_hash"] = stable_hash(settings.compression)
    atomic_write_json(state_path, status)
    return status
