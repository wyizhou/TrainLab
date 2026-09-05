#!/usr/bin/env python3
"""Shared reader content model renderers for content-first v4.

The HTML intentionally has no brand styling, cards, images or email MIME.  It
is a flat content-review artifact generated from the same model as Markdown.
"""

from __future__ import annotations

import hashlib
import html
import json
from copy import deepcopy
from typing import Any

from skills._shared.scripts.schema_validation import validate_payload

DAILY_SECTION_ORDER = (
    "completed_activities",
    "health_recovery",
    "fixed_course",
    "limitations_alerts",
)
WEEKLY_SECTION_ORDER = (
    "week_conclusion",
    "health_recovery",
    "all_activities",
    "technical_review",
    "plan_comparison",
    "combined_load",
    "fixed_plan",
)
VIEWPORTS = (375, 390, 430, 600, 672)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _seconds(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "时长缺失"
    minutes = round(float(value) / 60)
    return f"{minutes} 分钟"


def _distance(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "距离未记录"
    return f"{float(value):.1f} km"


def _activity_line(activity: dict[str, Any]) -> str:
    kind = {
        "running": "跑步",
        "climbing": "攀岩",
        "rest": "休息",
    }.get(str(activity.get("activity_kind")), "其他运动")
    return f"{kind}｜{_distance(activity.get('distance_km'))}｜{_seconds(activity.get('duration_seconds'))}"


def _lineage_text(raw_file_id: object, raw_sha256: object) -> str:
    if not isinstance(raw_file_id, int) or not isinstance(raw_sha256, str):
        return "来源缺失"
    return f"raw {raw_file_id} / SHA {raw_sha256[:12]}"


def _activity_line_v2(activity: dict[str, Any]) -> str:
    activity_date = activity.get("activity_date")
    activity_summary = _activity_line(activity)
    parts = [
        f"{activity_date}｜{activity_summary}"
        if isinstance(activity_date, str)
        else activity_summary
    ]
    average = activity.get("average_heart_rate_bpm")
    maximum = activity.get("maximum_heart_rate_bpm")
    if isinstance(average, (int, float)):
        parts.append(f"平均心率 {average:g} bpm")
    if isinstance(maximum, (int, float)):
        parts.append(f"最高心率 {maximum:g} bpm")
    parts.append(_lineage_text(activity.get("raw_file_id"), activity.get("raw_sha256")))
    return "｜".join(parts)


def _course_lines(course: dict[str, Any]) -> tuple[list[str], list[str]]:
    paragraphs = [
        f"{course['name']}｜目的：{course['purpose']}｜RPE {course['rpe_min']}–{course['rpe_max']}。",
        f"体感说明：{course['feel_guidance']}",
    ]
    items = [
        f"{step['name']}：{step['instruction']}（结束条件：{step['end_condition']}）"
        for step in course.get("steps", [])
    ]
    items.extend(f"技术备注：{item}" for item in course.get("technique_notes", []))
    items.extend(f"停止条件：{item}" for item in course.get("stop_conditions", []))
    return paragraphs, items


def build_daily_reader_content_v1(
    observation: dict[str, Any],
    health_analysis: dict[str, Any],
    *,
    planned_course: dict[str, Any],
    planned_course_ref: dict[str, Any],
    charts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Join objective facts, health analysis and one byte-bound fixed course."""

    if planned_course_ref.get("course_sha256") != _canonical_sha256(planned_course):
        raise ValueError("planned_course_sha_mismatch")
    if planned_course.get("date") != observation.get("report_date"):
        raise ValueError("planned_course_date_mismatch")
    activities = observation.get("activities", [])
    activity_paragraphs = (
        ["昨日没有已登记活动。"]
        if not activities
        else [f"昨日共记录 {len(activities)} 项运动，以下仅列客观事实。"]
    )
    activity_items = [_activity_line(item) for item in activities]
    health_paragraphs = [
        str(health_analysis["health_summary"]),
        str(health_analysis["sleep_analysis"]),
        str(health_analysis["recovery_analysis"]),
    ]
    course_paragraphs, course_items = _course_lines(planned_course)
    limitations = list(health_analysis.get("uncertainty", []))
    alert = health_analysis.get("health_alert")
    if isinstance(alert, dict):
        limitations.append(str(alert["message"]))
    if not limitations:
        limitations.append("本日报只使用已登记证据；没有额外数据缺口。")
    result = {
        "schema_version": "daily_reader_content_v1",
        "status": "ready",
        "title": f"TrainLab 日报 {observation['report_date']}",
        "report_date": str(observation["report_date"]),
        "activity_date": str(observation["activity_date"]),
        "sleep_wake_date": str(observation["sleep_wake_date"]),
        "fixed_course_ref": deepcopy(planned_course_ref),
        "sections": [
            {
                "section_code": "completed_activities",
                "heading": "昨日全部运动",
                "paragraphs": activity_paragraphs,
                "items": activity_items,
            },
            {
                "section_code": "health_recovery",
                "heading": "健康、睡眠与恢复",
                "paragraphs": health_paragraphs,
                "items": [],
            },
            {
                "section_code": "fixed_course",
                "heading": "今日固定课程",
                "paragraphs": course_paragraphs,
                "items": course_items,
            },
            {
                "section_code": "limitations_alerts",
                "heading": "数据缺失与安全警告",
                "paragraphs": limitations,
                "items": [],
            },
        ],
        "charts": deepcopy(charts or []),
        "provider_calls": 0,
    }
    _validate_reader_content(result)
    return result


def build_weekly_reader_content_v1(
    weekly_result: dict[str, Any],
    evidence: dict[str, Any],
    *,
    charts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    activities = evidence.get("all_activities", [])
    technical_items = [
        f"{item['observation']}｜解释：{item['interpretation']}｜对计划的含义：{item['planning_implication']}｜置信度：{item['confidence']}"
        for item in weekly_result.get("technical_findings", [])
    ]
    plan_items: list[str] = []
    for course in weekly_result["training_plan"]["items"]:
        plan_items.append(
            f"{course['date']}｜{course['name']}｜RPE {course['rpe_min']}–{course['rpe_max']}｜{course['purpose']}"
        )
        plan_items.extend(
            f"  {step['name']}：{step['instruction']}（{step['end_condition']}）"
            for step in course.get("steps", [])
        )
        plan_items.extend(
            f"  技术备注：{item}" for item in course.get("technique_notes", [])
        )
        plan_items.extend(
            f"  停止条件：{item}" for item in course.get("stop_conditions", [])
        )
    period = evidence["period"]
    plan_dates = [item["date"] for item in weekly_result["training_plan"]["items"]]
    result = {
        "schema_version": "weekly_reader_content_v1",
        "status": "ready",
        "title": f"TrainLab 周报 {period['activity_start_date']}～{period['activity_end_date']}",
        "activity_period": f"{period['activity_start_date']}~{period['activity_end_date']}",
        "sleep_wake_period": f"{period['sleep_wake_start_date']}~{period['sleep_wake_end_date']}",
        "plan_period": f"{plan_dates[0]}~{plan_dates[-1]}",
        "sections": [
            {
                "section_code": "week_conclusion",
                "heading": "结论先行",
                "paragraphs": [str(weekly_result["week_conclusion"])],
                "items": [],
            },
            {
                "section_code": "health_recovery",
                "heading": "全周健康与恢复",
                "paragraphs": [str(weekly_result["health_review"])],
                "items": [],
            },
            {
                "section_code": "all_activities",
                "heading": "全部实际运动",
                "paragraphs": [str(weekly_result["all_activity_review"])],
                "items": [_activity_line(item) for item in activities],
            },
            {
                "section_code": "technical_review",
                "heading": "重点课程技术复盘",
                "paragraphs": [],
                "items": technical_items or ["没有满足适用条件的技术指标。"],
            },
            {
                "section_code": "plan_comparison",
                "heading": "计划与实际简短对比",
                "paragraphs": [str(weekly_result["plan_comparison"])],
                "items": [],
            },
            {
                "section_code": "combined_load",
                "heading": "跑步、攀岩和恢复联合判断",
                "paragraphs": [str(weekly_result["climbing_and_combined_load"])],
                "items": [],
            },
            {
                "section_code": "fixed_plan",
                "heading": "唯一固定的七天下周计划",
                "paragraphs": [
                    f"进展选择：{weekly_result['progression_decision']}。计划一经周报生成即固定，是否执行由用户依据体感自行决定。"
                ],
                "items": plan_items,
            },
        ],
        "charts": deepcopy(charts or []),
        "provider_calls": 0,
    }
    _validate_reader_content(result)
    return result


def _historical_health_lines(evidence: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for health_day in evidence.get("health_days", []):
        if not isinstance(health_day, dict):
            continue
        for fact in health_day.get("facts", []):
            if not isinstance(fact, dict) or fact.get("status") != "available":
                continue
            code = fact.get("metric_code")
            if code != "rhr:resting_heart_rate":
                continue
            value = fact.get("value")
            refs = fact.get("raw_refs")
            if not isinstance(value, dict) or not isinstance(refs, list) or not refs:
                continue
            bpm = value.get("resting_heart_rate_bpm")
            ref = refs[0] if isinstance(refs[0], dict) else {}
            if isinstance(bpm, (int, float)):
                items.append(
                    f"{fact.get('observed_date')}｜RHR {bpm:g} bpm｜"
                    + _lineage_text(ref.get("raw_file_id"), ref.get("raw_sha256"))
                )
    return items


def _decision_course_lines(course: dict[str, Any], course_date: str) -> list[str]:
    lines = [
        f"{course_date}｜{course['name']}｜RPE {course['rpe_min']}–{course['rpe_max']}｜{course['purpose']}"
    ]
    phases = (
        ("checklist",)
        if course["activity_kind"] == "rest"
        else ("warmup", "main", "recovery", "cooldown")
    )
    for phase in phases:
        step = course["steps"][phase]
        lines.append(
            f"  {step['name']}：{step['instruction']}（{step['end_condition']}）"
        )
    lines.extend(f"  技术备注：{item}" for item in course["technique_notes"])
    lines.extend(f"  停止条件：{item}" for item in course["stop_conditions"])
    return lines


def build_weekly_reader_content_v2(
    weekly_result: dict[str, Any],
    evidence: dict[str, Any],
    *,
    charts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render model prose plus Host-owned historical heart-rate facts."""

    decision = weekly_result["decision"]
    activities = evidence.get("all_activities", [])
    technical_items = [
        f"{item['observation']}｜解释：{item['interpretation']}｜对计划的含义：{item['planning_implication']}｜置信度：{item['confidence']}"
        for item in decision.get("technical_findings", [])
    ]
    plan_items: list[str] = []
    for key in (f"day_{index}" for index in range(1, 8)):
        plan_items.extend(
            _decision_course_lines(
                decision["training_plan"]["days"][key],
                weekly_result["plan_dates"][key],
            )
        )
    period = weekly_result["period"]
    result = {
        "schema_version": "weekly_reader_content_v2",
        "status": "ready",
        "title": f"TrainLab 周报 {period['activity_start_date']}～{period['activity_end_date']}",
        "activity_period": f"{period['activity_start_date']}~{period['activity_end_date']}",
        "sleep_wake_period": f"{period['sleep_wake_start_date']}~{period['sleep_wake_end_date']}",
        "plan_period": f"{period['plan_start_date']}~{period['plan_end_date']}",
        "sections": [
            {
                "section_code": "week_conclusion",
                "heading": "结论先行",
                "paragraphs": [decision["week_conclusion"]],
                "items": [],
            },
            {
                "section_code": "health_recovery",
                "heading": "全周健康与恢复",
                "paragraphs": [decision["health_review"]],
                "items": _historical_health_lines(evidence),
            },
            {
                "section_code": "all_activities",
                "heading": "全部实际运动",
                "paragraphs": [decision["all_activity_review"]],
                "items": [_activity_line_v2(item) for item in activities],
            },
            {
                "section_code": "technical_review",
                "heading": "重点课程技术复盘",
                "paragraphs": [],
                "items": technical_items or ["没有满足适用条件的技术指标。"],
            },
            {
                "section_code": "plan_comparison",
                "heading": "计划与实际简短对比",
                "paragraphs": [decision["plan_comparison"]],
                "items": [],
            },
            {
                "section_code": "combined_load",
                "heading": "跑步、攀岩和恢复联合判断",
                "paragraphs": [decision["climbing_and_combined_load"]],
                "items": [],
            },
            {
                "section_code": "fixed_plan",
                "heading": "唯一固定的七天下周计划",
                "paragraphs": [
                    f"进展选择：{decision['progression_decision']}。计划一经周报生成即固定，是否执行由用户依据体感自行决定。"
                ],
                "items": plan_items,
            },
        ],
        "charts": deepcopy(charts or []),
        "provider_calls": 0,
    }
    _validate_reader_content(result)
    return result


def _validate_reader_content(content: dict[str, Any]) -> None:
    schema_name = str(content.get("schema_version"))
    expected = (
        DAILY_SECTION_ORDER
        if schema_name == "daily_reader_content_v1"
        else WEEKLY_SECTION_ORDER
    )
    actual = tuple(
        item.get("section_code")
        for item in content.get("sections", [])
        if isinstance(item, dict)
    )
    if actual != expected:
        raise ValueError("reader_section_order_invalid")
    maximum = 2 if schema_name == "daily_reader_content_v1" else 3
    if len(content.get("charts", [])) > maximum:
        raise ValueError(
            "daily_chart_limit_exceeded"
            if maximum == 2
            else "weekly_chart_limit_exceeded"
        )
    errors = validate_payload(content, schema_name)
    if errors:
        raise ValueError(f"{schema_name}_invalid:" + ",".join(errors[:3]))


def render_reader_markdown(content: dict[str, Any]) -> str:
    _validate_reader_content(content)
    lines = [f"# {content['title']}", ""]
    if content["schema_version"] == "daily_reader_content_v1":
        lines.extend(
            [
                f"- 运动日期：{content['activity_date']}",
                f"- 睡眠醒来日：{content['sleep_wake_date']}",
                f"- 今日课程日期：{content['report_date']}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- 活动覆盖：{content['activity_period']}",
                f"- 睡眠醒来日覆盖：{content['sleep_wake_period']}",
                f"- 下周计划：{content['plan_period']}",
                "",
            ]
        )
    for section in content["sections"]:
        lines.extend([f"## {section['heading']}", ""])
        for paragraph in section["paragraphs"]:
            lines.extend([paragraph, ""])
        for item in section["items"]:
            lines.append(f"- {item}")
        if section["items"]:
            lines.append("")
    for chart in content["charts"]:
        lines.extend([f"### {chart['title']}", "", chart["alt_text"], ""])
    return "\n".join(lines).rstrip() + "\n"


def render_lowfi_html(content: dict[str, Any]) -> str:
    _validate_reader_content(content)
    viewport_markers = "\n".join(f"/* viewport:{width} */" for width in VIEWPORTS)
    metadata = (
        f"运动日期：{html.escape(content['activity_date'])}；"
        f"睡眠醒来日：{html.escape(content['sleep_wake_date'])}；"
        f"课程日期：{html.escape(content['report_date'])}"
        if content["schema_version"] == "daily_reader_content_v1"
        else f"活动覆盖：{html.escape(content['activity_period'])}；睡眠覆盖：{html.escape(content['sleep_wake_period'])}；计划：{html.escape(content['plan_period'])}"
    )
    sections: list[str] = []
    for section in content["sections"]:
        paragraphs = "".join(
            f"<p>{html.escape(item)}</p>" for item in section["paragraphs"]
        )
        items = (
            "<ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in section["items"])
            + "</ul>"
            if section["items"]
            else ""
        )
        sections.append(
            f'<section data-section="{html.escape(section["section_code"])}"><h2>{html.escape(section["heading"])}</h2>{paragraphs}{items}</section>'
        )
    charts = "".join(
        f'<figure data-chart="{html.escape(chart["chart_code"])}"><figcaption>{html.escape(chart["title"])}</figcaption><p>{html.escape(chart["alt_text"])}</p></figure>'
        for chart in content["charts"]
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{viewport_markers}\nbody{{max-width:672px;margin:0 auto;padding:16px;font-family:system-ui,sans-serif;line-height:1.6}}section{{border-top:1px solid #bbb;padding:12px 0}}h1,h2{{line-height:1.3}}@media(max-width:430px){{body{{padding:12px}}}}</style>"
        f"<title>{html.escape(content['title'])}</title></head><body><header><h1>{html.escape(content['title'])}</h1><p>{metadata}</p></header>"
        + "".join(sections)
        + charts
        + "</body></html>"
    )
