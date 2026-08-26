#!/usr/bin/env python3
"""Build explicit, human-readable email view models from validated evidence."""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)


class EmailViewError(ValueError):
    """Stable presentation-layer validation failure."""


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _format_number(value: float, digits: int = 1) -> str:
    rounded = round(value, digits)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.{digits}f}"


def _format_duration(seconds: float) -> str:
    total_minutes = max(0, round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def _format_pace(
    distance_km: float | None, duration_seconds: float | None
) -> str | None:
    if not distance_km or distance_km <= 0 or duration_seconds is None:
        return None
    seconds = round(duration_seconds / distance_km)
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}/km"


def _activity_label(kind: str) -> str:
    normalized = kind.lower()
    if "run" in normalized:
        return "跑步"
    if "climb" in normalized or "boulder" in normalized:
        return "攀岩"
    if "walk" in normalized or "hike" in normalized:
        return "步行"
    if "cycle" in normalized or "bike" in normalized:
        return "骑行"
    return "训练活动"


def _metric_card(
    key: str,
    label: str,
    value: str | None,
    *,
    source_refs: list[int],
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value or "暂无数据",
        "missing": value is None,
        "detail": detail,
        "source_refs": source_refs,
    }


def _resource(context: dict[str, Any], resource: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in context.get("health", [])
        if isinstance(item, dict)
        and item.get("resource") == resource
        and isinstance(item.get("metrics"), dict)
    ]
    return matches[0] if len(matches) == 1 else None


def _sleep_card(context: dict[str, Any]) -> dict[str, Any]:
    item = _resource(context, "sleep")
    if item is None:
        return _metric_card("sleep", "主睡眠", None, source_refs=[])
    metrics = item["metrics"]
    duration = _number(metrics.get("duration_seconds"))
    completeness = metrics.get("completeness")
    detail_parts = []
    for key, label in (("sleep_start", "入睡"), ("sleep_end", "醒来")):
        value = metrics.get(key)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                detail_parts.append(f"{label} {parsed:%H:%M}")
            except ValueError:
                pass
    if isinstance(completeness, str):
        detail_parts.append("数据完整" if completeness == "complete" else "数据不完整")
    return _metric_card(
        "sleep",
        "主睡眠",
        _format_duration(duration) if duration is not None else None,
        source_refs=[int(item["raw_file_id"])],
        detail=" · ".join(detail_parts) or None,
    )


def _simple_health_card(
    context: dict[str, Any],
    *,
    resource: str,
    field: str,
    key: str,
    label: str,
    unit: str,
) -> dict[str, Any]:
    item = _resource(context, resource)
    value = _number(item["metrics"].get(field)) if item is not None else None
    return _metric_card(
        key,
        label,
        f"{_format_number(value)} {unit}" if value is not None else None,
        source_refs=[int(item["raw_file_id"])] if item is not None else [],
    )


def _recent_health_card(
    context: dict[str, Any], *, metric: str, key: str, label: str
) -> dict[str, Any]:
    snapshot = context.get("recent_health_metrics")
    try:
        require_valid_payload(snapshot, "recent_health_metrics_v1")
    except ValueError:
        return _metric_card(key, label, None, source_refs=[])
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    item = metrics.get(metric) if isinstance(metrics, dict) else None
    if not isinstance(item, dict) or item.get("status") != "ready":
        return _metric_card(key, label, None, source_refs=[])
    value = _number(item.get("value"))
    raw_id = item.get("raw_file_id")
    observed = item.get("observed_date")
    unit = item.get("unit")
    if (
        value is None
        or not isinstance(raw_id, int)
        or not isinstance(observed, str)
        or not isinstance(unit, str)
    ):
        return _metric_card(key, label, None, source_refs=[])
    return _metric_card(
        key,
        label,
        f"{_format_number(value)} {unit}",
        source_refs=[raw_id],
        detail=f"更新于 {observed}",
    )


def _activities(
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    activities: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    for item in context.get("activities", []):
        if not isinstance(item, dict) or item.get("status") != "ready":
            continue
        summary = item.get("summary")
        if not isinstance(summary, dict):
            continue
        distance = _number(summary.get("distance_km"))
        duration = _number(summary.get("duration_seconds"))
        kind = str(summary.get("activity_kind") or "activity")
        activity = {
            "kind": kind,
            "label": _activity_label(kind),
            "distance": f"{_format_number(distance)} km"
            if distance is not None
            else None,
            "duration": _format_duration(duration) if duration is not None else None,
            "pace": _format_pace(distance, duration),
            "lap_count": int(summary["lap_count"])
            if isinstance(summary.get("lap_count"), int)
            and not isinstance(summary.get("lap_count"), bool)
            else None,
            "source_refs": [int(item["raw_file_id"])]
            if isinstance(item.get("raw_file_id"), int)
            else [],
        }
        activities.append(activity)
        points = []
        for point in item.get("sequence", []):
            if not isinstance(point, dict) or not isinstance(
                point.get("metrics"), dict
            ):
                continue
            x_value = _number(point.get("offset_seconds"))
            y_value = _number(point["metrics"].get("heart_rate_bpm"))
            if x_value is not None and y_value is not None:
                points.append({"x": int(x_value), "y": y_value})
        if len(points) >= 2:
            charts.append(
                {
                    "role": "daily_activity_heart_rate",
                    "title": f"{activity['label']}心率变化",
                    "unit": "bpm",
                    "points": points,
                    "source_refs": activity["source_refs"],
                }
            )
    return activities, charts


def _validated_course(
    plan: dict[str, Any] | None, report_date: str
) -> dict[str, Any] | None:
    if not isinstance(plan, dict) or plan.get("status") != "succeeded":
        return None
    try:
        require_valid_payload(plan, "training_plan_v1")
    except ValueError:
        return None
    matches = [
        item
        for item in plan.get("items", [])
        if isinstance(item, dict) and item.get("date") == report_date
    ]
    if len(matches) != 1:
        return None
    return _presentation_course(matches[0])


def _presentation_course(item: dict[str, Any]) -> dict[str, Any]:
    """Select course facts while normalizing reader-facing safety prose."""

    result = {
        key: item.get(key)
        for key in (
            "date",
            "activity_kind",
            "name",
            "purpose",
            "load_level",
            "distance_km",
            "duration_minutes",
            "pace_min_seconds_per_km",
            "pace_max_seconds_per_km",
            "heart_rate_min_bpm",
            "heart_rate_max_bpm",
            "rpe",
            "garmin_mapping_status",
        )
        if item.get(key) is not None
    }
    kind = str(item.get("activity_kind"))
    if kind == "rest":
        result["downgrade_rule"] = "继续休息，不补偿错过的训练。"
        result["stop_conditions"] = ["出现明显不适时继续休息并评估恢复情况。"]
    else:
        result["downgrade_rule"] = "恢复不足或状态明显变差时，改为休息。"
        result["stop_conditions"] = ["出现疼痛、胸闷、眩晕或异常气短时立即停止训练。"]
    return result


def _daily_evidence(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    # AI claims remain in the strict source result. The presentation contract carries
    # only Host-derived labels so arbitrary engineering text cannot reach the email.
    refs: list[dict[str, Any]] = [
        {
            "id": int(item["raw_file_id"]),
            "sha256": str(item["sha256"]),
            "claim": "已验证健康或活动来源",
        }
        for item in payload.get("evidence_refs", [])
        if isinstance(item, dict)
    ]
    by_id: dict[int, dict[str, Any]] = {item["id"]: item for item in refs}
    for item in context.get("health", []):
        if not isinstance(item, dict):
            continue
        raw_id = item.get("raw_file_id")
        sha256 = item.get("sha256")
        resource = item.get("resource")
        if isinstance(raw_id, int) and isinstance(sha256, str):
            label = {
                "sleep": "主睡眠",
                "rhr": "静息心率",
                "hrv": "心率变异性",
                "heart_rates": "全天心率",
                "max_metrics": "最大摄氧量",
                "weigh_ins": "体重",
            }.get(str(resource), "健康")
            existing = by_id.get(raw_id)
            if existing is not None and existing["sha256"] != sha256:
                raise EmailViewError("daily_email_evidence_sha_mismatch")
            by_id[raw_id] = {
                "id": raw_id,
                "sha256": sha256,
                "claim": f"{label}证据",
            }
    snapshot = context.get("recent_health_metrics")
    snapshot_metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    if isinstance(snapshot_metrics, dict):
        for key, label in (("vo2_max", "最大摄氧量"), ("weight", "体重")):
            item = snapshot_metrics.get(key)
            if not isinstance(item, dict) or item.get("status") != "ready":
                continue
            raw_id = item.get("raw_file_id")
            sha256 = item.get("sha256")
            if isinstance(raw_id, int) and isinstance(sha256, str):
                existing = by_id.get(raw_id)
                if existing is not None and existing["sha256"] != sha256:
                    raise EmailViewError("daily_email_evidence_sha_mismatch")
                by_id[raw_id] = {
                    "id": raw_id,
                    "sha256": sha256,
                    "claim": f"{label}证据",
                }
    for item in context.get("activities", []):
        if not isinstance(item, dict) or item.get("status") != "ready":
            continue
        raw_id = item.get("raw_file_id")
        sha256 = item.get("raw_sha256")
        if isinstance(raw_id, int) and isinstance(sha256, str):
            existing = by_id.get(raw_id)
            if existing is not None and existing["sha256"] != sha256:
                raise EmailViewError("daily_email_evidence_sha_mismatch")
            summary = item.get("summary")
            kind = (
                str(summary.get("activity_kind") or "activity")
                if isinstance(summary, dict)
                else "activity"
            )
            by_id[raw_id] = {
                "id": raw_id,
                "sha256": sha256,
                "claim": f"{_activity_label(kind)}活动证据",
            }
    merged = [by_id[key] for key in sorted(by_id)]
    return {"count": len(merged), "refs": merged}


def _daily_presentation_summary(
    *,
    status: str,
    activities: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    course: dict[str, Any] | None,
) -> str:
    """Summarize validated fields without copying arbitrary AI prose."""

    if status == "blocked":
        return "关键证据不完整，本次日报已阻断；请先补齐数据，再决定今天的训练安排。"
    activity = "昨日没有已验证活动"
    if activities:
        first = activities[0]
        detail = "、".join(
            str(value)
            for value in (first.get("distance"), first.get("duration"))
            if value
        )
        activity = f"昨日完成{first['label']}" + (f"（{detail}）" if detail else "")
        if len(activities) > 1:
            activity += f"等 {len(activities)} 项活动"
    sleep = metrics["sleep"]
    sleep_text = (
        f"主睡眠 {sleep['value']}" if not sleep["missing"] else "主睡眠数据缺失"
    )
    if status == "caution":
        guidance = "恢复信号提示谨慎，今天优先恢复或低负荷安排，并遵守停止条件。"
    elif course is not None:
        guidance = f"恢复信号稳定，今天可按已验证课程“{course['name']}”执行。"
    else:
        guidance = "恢复信号稳定；今天没有已验证课程，请按当前状态保守安排。"
    return f"{activity}；{sleep_text}。{guidance}"


def _weekly_presentation_summary(
    *,
    blocked: bool,
    decision: str | None,
    daily_count: int,
    caution_days: int,
    running_distance_km: float,
) -> str:
    """Describe the validated weekly state and decision in reader-facing terms."""

    if blocked:
        return "周总结所需证据不完整，本次不生成下周计划；请先补齐缺失日报。"
    decision_text = {
        "advance": "下周按已验证计划小幅进阶，且一次只增加一个负荷维度",
        "hold": "下周按已验证计划维持当前负荷",
        "deload": "下周按已验证计划降低负荷并优先恢复",
    }[str(decision)]
    return (
        f"本周汇总 {daily_count} 份日报，其中 {caution_days} 天需要谨慎，"
        f"跑步合计 {_format_number(running_distance_km, 2)} 公里；{decision_text}。"
    )


def _daily_presentation_stop_conditions(status: str) -> list[str]:
    """Keep safety meaning while excluding arbitrary evidence identifiers."""

    conditions = ["出现疼痛、胸闷、眩晕或异常气短时立即停止训练。"]
    if status == "blocked":
        conditions.append("关键证据补齐前，不执行高负荷训练。")
    elif status == "caution":
        conditions.append("热身后仍明显疲劳或恢复不足时，取消训练并改为休息。")
    else:
        conditions.append("状态明显差于预期时，降低训练负荷或改为休息。")
    return conditions


def _require_source_ref_closure(view: dict[str, Any]) -> None:
    evidence = view.get("evidence")
    refs = evidence.get("refs") if isinstance(evidence, dict) else None
    if not isinstance(refs, list):
        raise EmailViewError("email_evidence_invalid")
    evidence_ids = {
        int(item["id"])
        for item in refs
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    used: set[int] = set()
    metrics = view.get("metrics")
    if isinstance(metrics, dict):
        for item in metrics.values():
            if isinstance(item, dict):
                used.update(int(value) for value in item.get("source_refs", []))
    for collection in (view.get("activities", []), view.get("charts", [])):
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    used.update(int(value) for value in item.get("source_refs", []))
    if not used.issubset(evidence_ids):
        raise EmailViewError("email_evidence_reference_missing")


def build_daily_view(
    payload: dict[str, Any],
    context: dict[str, Any],
    validated_training_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a daily view without exposing arbitrary payload keys."""

    require_valid_payload(payload, "daily_ai_result_v1")
    report_date = str(payload["report_date"])
    if (
        context.get("report_date") != report_date
        or context.get("review_date") != payload.get("review_date")
        or context.get("sleep_wake_date") != payload.get("sleep_wake_date")
    ):
        raise EmailViewError("daily_email_context_mismatch")
    status = "blocked" if payload["status"] == "blocked" else str(payload["safety"])
    activities, charts = _activities(context)
    course = (
        _validated_course(validated_training_plan, report_date)
        if status != "blocked"
        else None
    )
    trend = context.get("recent_trend")
    if not isinstance(trend, dict):
        trend = {}
    metrics = {
        "sleep": _sleep_card(context),
        "rhr": _simple_health_card(
            context,
            resource="rhr",
            field="resting_heart_rate_bpm",
            key="rhr",
            label="静息心率",
            unit="bpm",
        ),
        "hrv": _simple_health_card(
            context,
            resource="hrv",
            field="last_night_average",
            key="hrv",
            label="昨夜 HRV",
            unit="ms",
        ),
        "vo2_max": _recent_health_card(
            context,
            metric="vo2_max",
            key="vo2_max",
            label="VO₂ Max",
        ),
        "weight": _recent_health_card(
            context,
            metric="weight",
            key="weight",
            label="体重",
        ),
    }
    view = {
        "schema_version": "daily_email_view_v1",
        "kind": "daily",
        "title": f"TrainLab · 每日训练简报 · {report_date}",
        "period": report_date,
        "review_date": str(payload["review_date"]),
        "sleep_wake_date": str(payload["sleep_wake_date"]),
        "status": status,
        "error_code": payload.get("error_code"),
        "summary": _daily_presentation_summary(
            status=status, activities=activities, metrics=metrics, course=course
        ),
        "stop_conditions": _daily_presentation_stop_conditions(status),
        "metrics": metrics,
        "activities": activities,
        "today_course": course,
        "course_notice": None if course is not None else "今日未安排已验证课程",
        "recent_trend": {
            key: trend.get(key)
            for key in ("days_available", "sleep", "recovery", "running", "data_gaps")
        },
        "charts": charts if status != "blocked" else [],
        "extra_sections": [],
        "evidence": _daily_evidence(payload, context),
        "provider_calls": 0,
    }
    _require_source_ref_closure(view)
    require_valid_payload(view, "daily_email_view_v1")
    return view


def _convert_unit(value: float, source_unit: str, target_unit: str) -> float | None:
    normalized = source_unit.lower().replace(" ", "_")
    aliases = {
        "hours": {"hour", "hours", "h"},
        "minutes": {"minute", "minutes", "min"},
        "seconds": {"second", "seconds", "s"},
        "km": {"km", "kilometer", "kilometers"},
        "meters": {"m", "meter", "meters"},
        "bpm": {"bpm"},
        "ms": {"ms", "millisecond", "milliseconds"},
    }
    source = next(
        (name for name, values in aliases.items() if normalized in values), None
    )
    if source is None:
        return None
    if source == target_unit:
        return value
    conversions = {
        ("seconds", "hours"): value / 3600,
        ("minutes", "hours"): value / 60,
        ("seconds", "minutes"): value / 60,
        ("hours", "minutes"): value * 60,
        ("meters", "km"): value / 1000,
    }
    return conversions.get((source, target_unit))


def _named_metric(
    content: dict[str, Any], names: tuple[str, ...], *, target_unit: str
) -> float | None:
    for item in content.get("bounded_metrics", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).lower().replace(" ", "_")
        if any(candidate in name for candidate in names):
            value = _number(item.get("value"))
            unit = item.get("unit")
            if value is not None and isinstance(unit, str):
                converted = _convert_unit(value, unit, target_unit)
                if converted is not None:
                    return converted
    return None


def _series(
    dailies: list[dict[str, Any]],
    *,
    names: tuple[str, ...],
    role: str,
    title: str,
    unit: str,
) -> dict[str, Any] | None:
    points = []
    refs = []
    for item in dailies:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, dict):
            continue
        value = _named_metric(content, names, target_unit=unit)
        day = content.get("report_date")
        if value is None or not isinstance(day, str):
            continue
        points.append({"x": day, "y": value})
        if isinstance(item.get("output_id"), int):
            refs.append(int(item["output_id"]))
    if len(points) < 2:
        return None
    return {
        "role": role,
        "title": title,
        "unit": unit,
        "points": points,
        "source_refs": refs,
    }


def build_weekly_view(
    payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Create a weekly view from exactly seven validated daily summaries."""

    require_valid_payload(payload, "weekly_ai_result_v1")
    if context.get("period") != payload.get("period"):
        raise EmailViewError("weekly_email_context_mismatch")
    dailies = context.get("daily_reports")
    if not isinstance(dailies, list) or len(dailies) != 7:
        raise EmailViewError("weekly_email_daily_count_invalid")
    actual_sha = [
        item.get("sha256") if isinstance(item, dict) else None for item in dailies
    ]
    if actual_sha != payload.get("daily_input_sha256"):
        raise EmailViewError("weekly_email_daily_lineage_mismatch")
    blocked = payload["status"] == "blocked"
    plan = payload.get("training_plan")
    if not blocked:
        if not isinstance(plan, dict):
            raise EmailViewError("weekly_email_plan_missing")
        require_valid_payload(plan, "training_plan_v1")
        decision: str | None = str(plan["progression_rule"])
        progression_dimension: str | None = str(plan["progression_dimension"])
        plan_items: list[dict[str, Any]] = [
            _presentation_course(item) for item in plan["items"]
        ]
    else:
        decision = None
        progression_dimension = None
        plan_items = []
    charts = [
        chart
        for chart in (
            _series(
                dailies,
                names=("sleep_duration",),
                role="weekly_sleep",
                title="七日睡眠时长",
                unit="hours",
            ),
            _series(
                dailies,
                names=("resting_heart_rate",),
                role="weekly_rhr",
                title="七日静息心率",
                unit="bpm",
            ),
            _series(
                dailies,
                names=("hrv",),
                role="weekly_hrv",
                title="七日 HRV",
                unit="ms",
            ),
            _series(
                dailies,
                names=("activity_duration",),
                role="weekly_activity_duration",
                title="七日活动时长",
                unit="minutes",
            ),
        )
        if chart is not None
    ]
    period = str(payload["period"])
    start, end = period.split("/", 1)
    daily_contents = [item["content"] for item in dailies if isinstance(item, dict)]
    caution_days = sum(
        1
        for item in daily_contents
        if isinstance(item, dict) and item.get("safety") == "caution"
    )
    distance_values = [
        value
        for item in daily_contents
        if isinstance(item, dict)
        for value in [_named_metric(item, ("running_distance",), target_unit="km")]
        if value is not None
    ]
    daily_by_id = {
        int(item["output_id"]): item
        for item in dailies
        if isinstance(item, dict) and isinstance(item.get("output_id"), int)
    }
    refs = []
    for item in payload.get("evidence_refs", []):
        if not isinstance(item, dict):
            continue
        output_id = int(item["output_id"])
        daily = daily_by_id.get(output_id)
        content = daily.get("content") if isinstance(daily, dict) else None
        if not isinstance(daily, dict) or not isinstance(content, dict):
            raise EmailViewError("weekly_email_evidence_lineage_mismatch")
        sha256 = str(item["sha256"])
        if daily.get("sha256") != sha256:
            raise EmailViewError("weekly_email_evidence_sha_mismatch")
        refs.append(
            {
                "id": output_id,
                "sha256": sha256,
                "claim": f"{content['report_date']} 日报",
            }
        )
    daily_ids = {
        int(item["output_id"])
        for item in dailies
        if isinstance(item, dict) and isinstance(item.get("output_id"), int)
    }
    if daily_ids != {item["id"] for item in refs}:
        raise EmailViewError("weekly_email_evidence_lineage_mismatch")
    view = {
        "schema_version": "weekly_email_view_v1",
        "kind": "weekly",
        "title": f"TrainLab · 每周总结 · {start}~{end}",
        "period": period,
        "status": "blocked" if blocked else "ready",
        "error_code": payload.get("error_code"),
        "decision": decision,
        "progression_dimension": progression_dimension,
        "summary": _weekly_presentation_summary(
            blocked=blocked,
            decision=decision,
            daily_count=len(dailies),
            caution_days=caution_days,
            running_distance_km=round(sum(distance_values), 2),
        ),
        "stats": {
            "daily_count": len(dailies),
            "caution_days": caution_days,
            "running_distance_km": round(sum(distance_values), 2),
        },
        "plan_items": plan_items,
        "charts": [] if blocked else charts,
        "extra_sections": [],
        "evidence": {"count": len(refs), "refs": refs},
        "provider_calls": 0,
    }
    _require_source_ref_closure(view)
    require_valid_payload(view, "weekly_email_view_v1")
    return view
