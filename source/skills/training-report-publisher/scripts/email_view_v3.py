#!/usr/bin/env python3
"""Build v3 OpenDesign view models from frozen v2 coaching and Host evidence."""

from __future__ import annotations

import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload
from skills._shared.state import canonical_json


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


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


def _raw_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_file_id": int(item["raw_file_id"]),
        "raw_sha256": str(item["raw_sha256"]),
    }


def _health_cards(evidence: dict[str, Any]) -> dict[str, Any]:
    labels = {
        "rhr": "静息心率",
        "hrv": "昨夜 HRV",
        "vo2_max": "VO₂ Max",
        "weight": "体重",
    }
    cards: dict[str, Any] = {}
    for key, label in labels.items():
        item = evidence["health"].get(key)
        cards[key] = (
            {
                "label": label,
                "value": float(item["value"]),
                "unit": str(item["unit"]),
                "observed_date": str(item["observed_date"]),
            }
            if isinstance(item, dict)
            else None
        )
    return cards


def _daily_charts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for activity in evidence["activities"]:
        source_refs = [_raw_ref(activity)]
        zones = activity.get("observed_heart_rate_zones")
        if isinstance(zones, dict):
            charts.append(
                {
                    "chart_type": "stacked_duration",
                    "role": "daily_activity_hr_zones",
                    "title": "历史活动 · 设备记录心率分区",
                    "unit": "seconds",
                    "segments": zones["segments"],
                    "percentage_source": "derived_from_provider_duration",
                    "source_refs": source_refs,
                }
            )
        series = activity.get("heart_rate_series")
        if isinstance(series, list) and len(series) >= 2:
            charts.append(
                {
                    "chart_type": "series",
                    "role": "daily_activity_heart_rate",
                    "title": "历史活动 · 心率变化",
                    "unit": "bpm",
                    "points": [
                        {"x": int(point["offset_seconds"]), "y": float(point["value"])}
                        for point in series
                    ],
                    "source_refs": source_refs,
                }
            )
    sleep = evidence.get("sleep")
    if isinstance(sleep, dict) and isinstance(sleep.get("stages"), list):
        charts.append(
            {
                "chart_type": "stacked_duration",
                "role": "daily_sleep_stages",
                "title": "昨夜睡眠阶段",
                "unit": "seconds",
                "segments": sleep["stages"],
                "percentage_source": "derived_from_provider_duration",
                "source_refs": [_raw_ref(sleep)],
            }
        )
    return charts


def build_daily_view_v3(
    daily_result: dict[str, Any], presentation: dict[str, Any]
) -> dict[str, Any]:
    require_valid_payload(daily_result, "daily_ai_result_v2")
    require_valid_payload(presentation, "daily_presentation_evidence_v1")
    if presentation["source_daily_result"]["content_json_sha256"] != _sha(daily_result):
        raise ValueError("daily_presentation_source_payload_mismatch")
    for field in ("report_date", "review_date", "sleep_wake_date", "safety"):
        if daily_result.get(field) != presentation.get(field):
            raise ValueError("daily_presentation_binding_mismatch")
    activities = [
        {
            "label": _activity_label(str(item["activity_kind"])),
            "activity_kind": str(item["activity_kind"]),
            "distance_km": item.get("distance_km"),
            "duration_seconds": float(item["duration_seconds"]),
            "pace_seconds_per_km": item.get("pace_seconds_per_km"),
            "heart_rate_average_bpm": item.get("heart_rate_average_bpm"),
            "heart_rate_maximum_bpm": item.get("heart_rate_maximum_bpm"),
        }
        for item in presentation["activities"]
    ]
    sleep = presentation.get("sleep")
    sleep_card = (
        {
            "start": sleep["start"],
            "end": sleep["end"],
            "duration_seconds": float(sleep["duration_seconds"]),
            "completeness": "complete",
        }
        if isinstance(sleep, dict)
        else None
    )
    charts = (
        _daily_charts(presentation) if daily_result["status"] == "succeeded" else []
    )
    data_limits: list[str] = []
    if daily_result["status"] == "blocked":
        data_limits.append("本次报告已阻断，不展示可执行课程或正常训练图表。")
    else:
        if not presentation["activities"]:
            data_limits.append("昨日没有已验证活动，活动图表不显示。")
        for activity in presentation["activities"]:
            if not isinstance(activity.get("observed_heart_rate_zones"), dict):
                data_limits.append("活动没有合资格的设备分区时长，心率分区图不显示。")
            if len(activity.get("heart_rate_series", [])) < 2:
                data_limits.append("活动心率序列采样不足，变化图不显示。")
        if not isinstance(presentation.get("sleep"), dict) or not isinstance(
            presentation.get("sleep", {}).get("stages"), list
        ):
            data_limits.append("睡眠阶段数据不完整，阶段图不显示。")
        if not charts:
            data_limits.append("图表数据不足；已知单值仍保留在卡片中。")
    data_limits = list(dict.fromkeys(data_limits))
    view = {
        "schema_version": "daily_email_view_v3",
        "kind": "daily",
        "title": f"TrainLab · 每日训练简报 · {daily_result['report_date']}",
        "status": daily_result["status"],
        "error_code": daily_result.get("error_code"),
        "report_date": daily_result["report_date"],
        "review_date": daily_result["review_date"],
        "sleep_wake_date": daily_result["sleep_wake_date"],
        "safety": daily_result["safety"],
        "yesterday_summary": daily_result["yesterday_summary"],
        "review_health_summary": daily_result["review_health_summary"],
        "recovery_summary": daily_result["recovery_summary"],
        "planned_course_context": daily_result["planned_course_context"],
        "planned_course": daily_result["planned_course"],
        "adjustment": daily_result["adjustment"],
        "effective_course": daily_result["effective_course"],
        "decision_reasons": daily_result["decision_reasons"],
        "adjustment_reason_codes": daily_result["adjustment_reason_codes"],
        "stop_conditions": daily_result["stop_conditions"],
        "uncertainty": daily_result["uncertainty"],
        "activity_kpis": activities,
        "sleep_card": sleep_card,
        "health_cards": _health_cards(presentation),
        "charts": charts,
        "data_limits": data_limits,
        "recent_trend": presentation["recent_trend"],
        "evidence_labels": [
            "冻结的 AI 教练结论",
            "已验证的健康与活动展示证据",
            "图表仅使用设备记录或确定性聚合",
        ],
        "source_daily_result": presentation["source_daily_result"],
        "presentation_evidence_sha256": _sha(presentation),
        "provider_calls": 0,
    }
    require_valid_payload(view, "daily_email_view_v3")
    return view


def _series_chart(
    *,
    role: str,
    title: str,
    unit: str,
    values: list[tuple[str, float, list[dict[str, Any]]]],
) -> dict[str, Any] | None:
    if len(values) < 2:
        return None
    refs: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for _day, _value, item_refs in values:
        for ref in item_refs:
            identity = (int(ref["output_id"]), str(ref["output_sha256"]))
            if identity not in seen:
                refs.append(ref)
                seen.add(identity)
    if not refs:
        return None
    return {
        "chart_type": "series",
        "role": role,
        "title": title,
        "unit": unit,
        "points": [{"x": day, "y": value} for day, value, _refs in values],
        "source_refs": refs,
    }


def _metric_values(
    daily: list[dict[str, Any]],
    presentation_refs: list[dict[str, Any]],
    key: str,
) -> list[tuple[str, float, list[dict[str, Any]]]]:
    result = []
    for item, ref in zip(daily, presentation_refs):
        metric = item["health"].get(key)
        if (
            isinstance(metric, dict)
            and isinstance(metric.get("raw_file_id"), int)
            and isinstance(metric.get("raw_sha256"), str)
        ):
            result.append(
                (
                    str(item["report_date"]),
                    float(metric["value"]),
                    [ref],
                )
            )
    return result


def _weekly_charts(
    daily: list[dict[str, Any]], presentation_refs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    charts: list[dict[str, Any]] = []
    limits: list[str] = []
    sleep_values = [
        (
            str(item["report_date"]),
            float(item["sleep"]["duration_seconds"]) / 3600,
            [presentation_refs[index]],
        )
        for index, item in enumerate(daily)
        if isinstance(item.get("sleep"), dict)
    ]
    candidates = [
        _series_chart(
            role="weekly_sleep",
            title="七日睡眠时长",
            unit="hours",
            values=sleep_values,
        ),
        _series_chart(
            role="weekly_rhr",
            title="七日静息心率",
            unit="bpm",
            values=_metric_values(daily, presentation_refs, "rhr"),
        ),
        _series_chart(
            role="weekly_hrv",
            title="七日昨夜 HRV",
            unit="ms",
            values=_metric_values(daily, presentation_refs, "hrv"),
        ),
    ]
    for chart in candidates:
        if chart is not None:
            charts.append(chart)
    for label, count in (
        ("睡眠", len(sleep_values)),
        (
            "静息心率",
            len(_metric_values(daily, presentation_refs, "rhr")),
        ),
        ("HRV", len(_metric_values(daily, presentation_refs, "hrv"))),
    ):
        if count < 7:
            limits.append(f"{label}趋势仅包含 {count}/7 日已知值，缺失日期不补零。")

    distance_values: list[tuple[str, float, list[dict[str, Any]]]] = []
    duration_values: list[tuple[str, float, list[dict[str, Any]]]] = []
    zone_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, item in enumerate(daily):
        activities = item["activities"]
        running_distance = 0.0
        activity_duration = 0.0
        day_ref = presentation_refs[index]
        for activity in activities:
            if "run" in str(activity["activity_kind"]).lower():
                running_distance += float(activity.get("distance_km") or 0)
            activity_duration += float(activity["duration_seconds"]) / 60
            zones = activity.get("observed_heart_rate_zones")
            if isinstance(zones, dict):
                zone_items.append((zones, day_ref))
        # Keep all seven dates in the chart, including verified zero-activity days.
        # Every contributing activity remains represented in the chart lineage.
        distance_values.append((str(item["report_date"]), running_distance, [day_ref]))
        duration_values.append((str(item["report_date"]), activity_duration, [day_ref]))
    for chart in (
        _series_chart(
            role="weekly_running_distance",
            title="七日跑量",
            unit="km",
            values=distance_values,
        ),
        _series_chart(
            role="weekly_activity_duration",
            title="七日活动时长",
            unit="minutes",
            values=duration_values,
        ),
    ):
        if chart is not None:
            charts.append(chart)

    definitions = {str(item[0]["definition_sha256"]) for item in zone_items}
    if zone_items and len(definitions) == 1:
        labels = [str(item["label"]) for item in zone_items[0][0]["segments"]]
        totals = [0.0] * len(labels)
        zone_refs: list[dict[str, Any]] = []
        for zones, ref in zone_items:
            if [str(item["label"]) for item in zones["segments"]] != labels:
                totals = []
                break
            for index, segment in enumerate(zones["segments"]):
                totals[index] += float(segment["duration_seconds"])
            zone_refs.append(ref)
        total = sum(totals)
        if totals and total > 0:
            charts.append(
                {
                    "chart_type": "stacked_duration",
                    "role": "weekly_activity_hr_zones",
                    "title": "本周设备记录心率分区",
                    "unit": "seconds",
                    "segments": [
                        {
                            "label": label,
                            "duration_seconds": round(value, 3),
                            "percentage": round(value / total * 100, 2),
                        }
                        for label, value in zip(labels, totals)
                    ],
                    "percentage_source": "derived_from_provider_duration",
                    "source_refs": zone_refs,
                }
            )
    elif zone_items:
        limits.append("本周活动使用了不同的设备心率分区定义，因此不聚合周心率分区。")
    else:
        limits.append("本周没有合资格的设备心率分区时长，周分区图不显示。")
    if not charts:
        limits.append("图表数据不足；已知周汇总仍保留为文字与 KPI。")
    # A weekly chart is a deterministic result of the exact seven persisted
    # daily presentation outputs. Missing values affect points, not lineage.
    for chart in charts:
        chart["source_refs"] = [dict(ref) for ref in presentation_refs]
    return charts, list(dict.fromkeys(limits))


def build_weekly_view_v3(
    weekly_result: dict[str, Any],
    daily_presentation: list[dict[str, Any]],
    daily_presentation_outputs: list[dict[str, Any]],
    source_weekly_result: dict[str, Any],
) -> dict[str, Any]:
    require_valid_payload(weekly_result, "weekly_ai_result_v2")
    if len(daily_presentation) != 7:
        raise ValueError("weekly_presentation_daily_count_invalid")
    for item in daily_presentation:
        require_valid_payload(item, "daily_presentation_evidence_v1")
    if len(daily_presentation_outputs) != 7 or source_weekly_result.get(
        "content_json_sha256"
    ) != _sha(weekly_result):
        raise ValueError("weekly_presentation_output_binding_invalid")
    start_text, end_text = str(weekly_result["period"]).split("/")
    start = date.fromisoformat(start_text)
    expected = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    if [str(item["report_date"]) for item in daily_presentation] != expected:
        raise ValueError("weekly_presentation_dates_invalid")
    output_refs: list[dict[str, Any]] = []
    for day, presentation, output in zip(
        expected, daily_presentation, daily_presentation_outputs
    ):
        if (
            output.get("report_date") != day
            or not isinstance(output.get("output_id"), int)
            or not isinstance(output.get("sha256"), str)
            or output.get("content_json_sha256") != _sha(presentation)
        ):
            raise ValueError("weekly_presentation_output_binding_invalid")
        output_refs.append(
            {
                "output_id": int(output["output_id"]),
                "output_sha256": str(output["sha256"]),
            }
        )
    source_refs = [
        {
            "output_id": item["source_daily_result"]["output_id"],
            "sha256": item["source_daily_result"]["sha256"],
        }
        for item in daily_presentation
    ]
    if source_refs != weekly_result["daily_input_refs"]:
        raise ValueError("weekly_presentation_source_binding_invalid")

    activity_count = sum(len(item["activities"]) for item in daily_presentation)
    running_distance = sum(
        float(activity.get("distance_km") or 0)
        for item in daily_presentation
        for activity in item["activities"]
        if "run" in str(activity["activity_kind"]).lower()
    )
    activity_minutes = sum(
        float(activity["duration_seconds"]) / 60
        for item in daily_presentation
        for activity in item["activities"]
    )
    sleep_hours = [
        float(item["sleep"]["duration_seconds"]) / 3600
        for item in daily_presentation
        if isinstance(item.get("sleep"), dict)
    ]
    charts, data_limits = _weekly_charts(daily_presentation, output_refs)
    if weekly_result["status"] == "blocked":
        charts = []
        data_limits.insert(
            0, "本次周报已阻断，不展示推进决策、正常图表或七日可执行计划。"
        )
    view = {
        "schema_version": "weekly_email_view_v3",
        "kind": "weekly",
        "title": f"TrainLab · 每周总结 · {start_text}~{end_text}",
        "status": weekly_result["status"],
        "error_code": weekly_result.get("error_code"),
        "period": weekly_result["period"],
        "progression_rule": weekly_result["progression_rule"],
        "health_summary": weekly_result["health_summary"],
        "activity_summary": weekly_result["activity_summary"],
        "weekly_kpis": {
            "daily_count": 7,
            "caution_days": sum(
                1 for item in daily_presentation if item["safety"] == "caution"
            ),
            "activity_count": activity_count,
            "running_distance_km": round(running_distance, 3),
            "activity_duration_minutes": round(activity_minutes, 1),
            "average_sleep_hours": round(sum(sleep_hours) / len(sleep_hours), 2)
            if sleep_hours
            else None,
        },
        "week_comparison": {
            "status": "unavailable",
            "summary": "没有同口径的上一周展示证据，本周只展示实测绝对值。",
        },
        "charts": charts,
        "data_limits": list(dict.fromkeys(data_limits)),
        "insights": [
            {key: item[key] for key in ("observation", "meaning", "action")}
            for item in weekly_result["insights"]
        ],
        "training_plan": weekly_result["training_plan"],
        "uncertainty": weekly_result["uncertainty"],
        "daily_presentation_refs": [
            {
                "report_date": item["report_date"],
                "presentation_sha256": _sha(item),
                "source_daily_result": item["source_daily_result"],
                "presentation_output": {
                    "output_id": int(output["output_id"]),
                    "sha256": str(output["sha256"]),
                },
            }
            for item, output in zip(daily_presentation, daily_presentation_outputs)
        ],
        "source_weekly_result": {
            "output_id": int(source_weekly_result["output_id"]),
            "sha256": str(source_weekly_result["sha256"]),
            "content_json_sha256": str(source_weekly_result["content_json_sha256"]),
        },
        "provider_calls": 0,
    }
    require_valid_payload(view, "weekly_email_view_v3")
    return view
