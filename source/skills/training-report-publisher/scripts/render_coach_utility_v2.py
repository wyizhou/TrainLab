#!/usr/bin/env python3
"""Render Coaching Utility v2 views into deterministic, human-readable mail."""

from __future__ import annotations

import hashlib
import json
from html import escape
from html.parser import HTMLParser
from typing import Any

from skills._shared.scripts.reader_safety import (
    require_course_visible_text,
    require_health_visible_text,
    require_narrative_visible_text,
)

PHASE_LABELS = {
    "warmup": "热身",
    "main": "主训练",
    "recovery": "恢复",
    "cooldown": "放松",
    "checklist": "执行检查",
}
ADJUSTMENT_LABELS = {
    "as_planned": "按原计划执行",
    "modified": "今日降级调整",
    "rest": "今日改为恢复",
    "blocked": "今日停止训练",
    "unavailable": "今日课程不可用",
}
COURSE_KEYS = {
    "date",
    "activity_kind",
    "session_type",
    "name",
    "purpose",
    "load_level",
    "garmin_mapping_status",
    "duration_minutes",
    "distance_km",
    "rpe_min",
    "rpe_max",
    "feel_guidance",
    "reference_pace",
    "steps",
    "start_gate",
    "technique_notes",
    "downgrade_rule",
    "stop_conditions",
}
STEP_KEYS = {
    "phase",
    "name",
    "instruction",
    "end_condition",
    "repeats",
    "duration_minutes",
    "distance_km",
    "rpe_min",
    "rpe_max",
}

_BLOCK_TAGS = {"div", "h1", "h2", "h3", "li", "p", "section", "td", "tr"}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif tag in _BLOCK_TAGS and self.hidden_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0:
            self.parts.append(data)


def _html_visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _course(course: dict[str, Any], *, compact: bool = False) -> str:
    dose = []
    if course.get("distance_km") is not None:
        dose.append(f"{course['distance_km']} km")
    if course.get("duration_minutes") is not None:
        dose.append(f"{course['duration_minutes']} 分钟")
    dose.append(f"RPE {course['rpe_min']}–{course['rpe_max']}/10")
    reference = course.get("reference_pace")
    if isinstance(reference, dict):
        seconds = int(reference["seconds_per_km"])
        dose.append(f"历史参考 {seconds // 60}:{seconds % 60:02d}/km（不是目标配速）")
    steps = "".join(
        '<div class="step">'
        f"<strong>{escape(PHASE_LABELS.get(str(step.get('phase')), str(step.get('name'))))}</strong>"
        f" · {escape(str(step.get('instruction')))}"
        f'<div class="muted">结束：{escape(str(step.get("end_condition")))}</div></div>'
        for step in course.get("steps", [])
    )
    detail = (
        ""
        if compact
        else (
            '<div class="sub"><strong>开始前检查</strong>'
            + _list(course["start_gate"])
            + "</div>"
            '<div class="sub"><strong>执行提示</strong>'
            + _list(course["technique_notes"])
            + "</div>"
            f'<div class="sub"><strong>降级方案</strong><p>{escape(str(course["downgrade_rule"]))}</p></div>'
            '<div class="sub"><strong>停止条件</strong>'
            + _list(course["stop_conditions"])
            + "</div>"
        )
    )
    return (
        '<div class="course">'
        f'<div class="tag">{escape(str(course["session_type"]))}</div>'
        f"<h3>{escape(str(course['name']))}</h3>"
        f"<p>{escape(str(course['purpose']))}</p>"
        f'<p class="dose">{" · ".join(escape(item) for item in dose)}</p>'
        f'<p class="muted">体感：{escape(str(course["feel_guidance"]))}</p>'
        f'<div class="steps">{steps}</div>{detail}</div>'
    )


def _styles() -> str:
    return """
<style>
body{margin:0;background:#F3F8F7;color:#15343A;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.shell{max-width:700px;margin:auto;background:#fff}.head{padding:28px 24px;background:linear-gradient(135deg,#087A78,#35A98D);color:#fff}.head h1{font-size:26px;margin:4px 0}.pad{padding:22px}.section{border:1px solid #D7E7E4;border-radius:16px;padding:18px;margin-bottom:16px}.section h2{margin:0 0 10px;font-size:20px}.course{background:#F8FBFA;border:1px solid #D7E7E4;border-radius:13px;padding:15px;margin-top:10px}.course h3{margin:8px 0}.tag{display:inline-block;background:#DDF3ED;color:#096A62;border-radius:999px;padding:3px 9px;font-size:12px}.dose{font-weight:650}.muted{color:#587076;font-size:13px}.step{padding:9px 0;border-top:1px solid #E4EEEC}.sub{padding-top:8px}.insight{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0}.insight div{padding:10px;background:#F3F8F7;border-radius:10px}.day{margin-top:14px}.privacy{padding:0 22px 24px;color:#687D81;font-size:11px}@media(max-width:375px){.pad{padding:14px}.head{padding:22px 16px}.insight{display:block}.insight div{margin-bottom:6px}.section{padding:14px}}@media(prefers-color-scheme:dark){body{background:#10282E}.shell{background:#18363D;color:#F2F8F6}.section,.course{background:#21434A;border-color:#49656A}.muted,.privacy{color:#C8D8D6}.insight div{background:#294B52}}
</style>"""


def _payload(
    subject: str,
    html: str,
    text: str,
    source: object,
    *,
    health_summary: str,
) -> dict[str, Any]:
    require_health_visible_text(health_summary)
    escaped_health = escape(health_summary)
    if html.count(escaped_health) != 1 or text.count(health_summary) != 1:
        raise ValueError("health_summary_render_binding_invalid")
    reader_only_html = html.replace(escaped_health, "[health-observation]", 1)
    reader_only_text = text.replace(health_summary, "[health-observation]", 1)
    require_narrative_visible_text(
        {
            "subject": subject,
            "html": _html_visible_text(reader_only_html),
            "text": reader_only_text,
        }
    )
    return {
        "subject": subject,
        "html": html,
        "text": text,
        "source_sha256": hashlib.sha256(_canonical(source).encode()).hexdigest(),
        "provider_calls": 0,
    }


def _reject_engineering_content(view: object) -> None:
    if not isinstance(view, dict):
        raise ValueError("view_invalid")
    courses: list[dict[str, Any]] = []
    for key in ("planned_course", "effective_course"):
        course = view.get(key)
        if isinstance(course, dict):
            courses.append(course)
    plan = view.get("training_plan")
    if isinstance(plan, dict):
        courses.extend(item for item in plan.get("items", []) if isinstance(item, dict))
    for course in courses:
        require_course_visible_text(course)
        if set(course) - COURSE_KEYS:
            raise ValueError("engineering_content_forbidden")
        for step in course.get("steps", []):
            if not isinstance(step, dict) or set(step) - STEP_KEYS:
                raise ValueError("engineering_content_forbidden")
    schema_version = view.get("schema_version")
    health_key = (
        "review_health_summary"
        if schema_version == "daily_email_view_v2"
        else "health_summary"
        if schema_version == "weekly_email_view_v2"
        else None
    )
    reader_only_view = dict(view)
    if health_key is not None:
        health_summary = reader_only_view.pop(health_key, None)
        if not isinstance(health_summary, str):
            raise ValueError("health_summary_missing")
        require_health_visible_text(health_summary)
    require_narrative_visible_text(reader_only_view)


def render_daily_v2(view: dict[str, Any]) -> dict[str, Any]:
    _reject_engineering_content(view)
    subject = f"TrainLab · 每日训练简报 · {view['report_date']}"
    reasons = _list([str(item) for item in view["decision_reasons"]])
    evidence = "、".join(escape(str(item)) for item in view["evidence_labels"])
    verified_original = view["planned_course_context"] == "verified_original"
    planned_html = (
        f'<div class="section"><h2>周计划原课</h2>{_course(view["planned_course"])}</div>'
        if verified_original
        else '<div class="section"><h2>周计划原课</h2><p>未找到当时已经存在且可验证的周计划。</p></div>'
        f'<div class="section"><h2>测试基准课（非历史原计划）</h2>{_course(view["planned_course"])}</div>'
    )
    planned_text = (
        f"周计划原课：{view['planned_course']['name']}"
        if verified_original
        else "周计划原课：无可验证记录\n"
        f"测试基准课（非历史原计划）：{view['planned_course']['name']}"
    )
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(subject)}</title>{_styles()}</head><body>"
        f'<div class="shell"><div class="head"><div>TRAINLAB DAILY</div><h1>{escape(subject)}</h1></div><div class="pad">'
        f'<div class="section"><h2>昨日训练怎么理解</h2><p>{escape(view["yesterday_summary"])}</p></div>'
        f'<div class="section"><h2>昨日健康数据</h2><p>{escape(view["review_health_summary"])}</p></div>'
        f'<div class="section"><h2>昨夜睡眠与恢复</h2><p>{escape(view["recovery_summary"])}</p></div>'
        f"{planned_html}"
        f'<div class="section"><h2>今日调整 · {escape(ADJUSTMENT_LABELS[view["adjustment"]])}</h2>{reasons}{_course(view["effective_course"])}</div>'
        f'<div class="section"><h2>证据说明</h2><p>{evidence}</p></div>'
        '</div><div class="privacy">仅用于个人训练复盘，不替代医疗诊断。</div></div></body></html>'
    )
    lines = [
        subject,
        "",
        f"昨日训练：{view['yesterday_summary']}",
        f"昨日健康数据：{view['review_health_summary']}",
        f"昨夜睡眠与恢复：{view['recovery_summary']}",
        "",
        planned_text,
        f"今日调整：{ADJUSTMENT_LABELS[view['adjustment']]} — {view['effective_course']['name']}",
        *[f"- {item}" for item in view["decision_reasons"]],
        (
            "剂量："
            + " · ".join(
                item
                for item in (
                    f"{view['effective_course'].get('duration_minutes')} 分钟"
                    if view["effective_course"].get("duration_minutes") is not None
                    else "",
                    f"{view['effective_course'].get('distance_km')} km"
                    if view["effective_course"].get("distance_km") is not None
                    else "",
                    f"RPE {view['effective_course']['rpe_min']}–{view['effective_course']['rpe_max']}/10",
                )
                if item
            )
        ),
        f"体感：{view['effective_course']['feel_guidance']}",
        "开始前检查：" + "；".join(view["effective_course"]["start_gate"]),
        "执行提示：" + "；".join(view["effective_course"]["technique_notes"]),
        "",
        "执行步骤：",
        *[
            f"- {PHASE_LABELS.get(step['phase'], step['name'])}：{step['instruction']}（{step['end_condition']}）"
            for step in view["effective_course"]["steps"]
        ],
        f"降级方案：{view['effective_course']['downgrade_rule']}",
        *[f"停止条件：{item}" for item in view["effective_course"]["stop_conditions"]],
    ]
    return _payload(
        subject,
        html,
        "\n".join(lines) + "\n",
        view,
        health_summary=str(view["review_health_summary"]),
    )


def render_weekly_v2(view: dict[str, Any]) -> dict[str, Any]:
    _reject_engineering_content(view)
    start, end = str(view["period"]).split("/")
    subject = f"TrainLab · 每周总结 · {start}~{end}"
    insights = "".join(
        '<div class="insight">'
        f"<div><strong>观察</strong><br>{escape(item['observation'])}</div>"
        f"<div><strong>意义</strong><br>{escape(item['meaning'])}</div>"
        f"<div><strong>行动</strong><br>{escape(item['action'])}</div></div>"
        for item in view["insights"]
    )
    days = "".join(
        f'<div class="day"><strong>{escape(item["date"])}</strong>{_course(item)}</div>'
        for item in view["training_plan"]["items"]
    )
    uncertainty = (
        _list(view["uncertainty"])
        if view["uncertainty"]
        else "<p>本周无额外数据缺口。</p>"
    )
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(subject)}</title>{_styles()}</head><body>"
        f'<div class="shell"><div class="head"><div>TRAINLAB WEEKLY</div><h1>{escape(subject)}</h1></div><div class="pad">'
        f'<div class="section"><h2>健康总结</h2><p>{escape(view["health_summary"])}</p></div>'
        f'<div class="section"><h2>运动与负荷总结</h2><p>{escape(view["activity_summary"])}</p></div>'
        f'<div class="section"><h2>观察 → 意义 → 行动</h2>{insights}</div>'
        f'<div class="section"><h2>七日训练计划</h2>{days}</div>'
        f'<div class="section"><h2>数据限制</h2>{uncertainty}</div>'
        '</div><div class="privacy">课程强度仅使用 RPE 与体感描述；设备训练目标由 Garmin 负责。</div></div></body></html>'
    )
    lines = [
        subject,
        "",
        f"健康总结：{view['health_summary']}",
        f"运动与负荷总结：{view['activity_summary']}",
        "",
        "观察 → 意义 → 行动",
    ]
    lines.extend(
        f"- {item['observation']} → {item['meaning']} → {item['action']}"
        for item in view["insights"]
    )
    lines.append("\n七日训练计划")
    for item in view["training_plan"]["items"]:
        lines.append(
            f"- {item['date']} {item['name']}：{item['purpose']}，RPE {item['rpe_min']}–{item['rpe_max']}"
        )
        dose = []
        if item.get("duration_minutes") is not None:
            dose.append(f"{item['duration_minutes']} 分钟")
        if item.get("distance_km") is not None:
            dose.append(f"{item['distance_km']} km")
        if dose:
            lines.append("  - 剂量：" + " · ".join(dose))
        lines.append(f"  - 体感：{item['feel_guidance']}")
        lines.append("  - 开始前检查：" + "；".join(item["start_gate"]))
        lines.append("  - 执行提示：" + "；".join(item["technique_notes"]))
        lines.extend(
            f"  - {PHASE_LABELS.get(step['phase'], step['name'])}：{step['instruction']}"
            for step in item["steps"]
        )
        lines.append(f"  - 降级：{item['downgrade_rule']}")
        lines.append("  - 停止条件：" + "；".join(item["stop_conditions"]))
    return _payload(
        subject,
        html,
        "\n".join(lines) + "\n",
        view,
        health_summary=str(view["health_summary"]),
    )
