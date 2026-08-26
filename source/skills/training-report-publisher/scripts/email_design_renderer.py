#!/usr/bin/env python3
"""Shared active OpenDesign table/CID renderer for v3 daily and weekly email."""

from __future__ import annotations

import hashlib
import io
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.reader_safety import (
    require_course_visible_text,
    require_narrative_visible_text,
)
from skills._shared.scripts.schema_validation import require_valid_payload
from skills._shared.state import canonical_json

CHART_WIDTH = 1248
CHART_HEIGHT = 420
MAX_HTML_BYTES = 80 * 1024

_PRIVATE_PATTERN = re.compile(
    r"(?:\blatitude\b|\blongitude\b|\bgps\b|\bcoordinates?\b|\broute\b|"
    r"路线|经纬度|\btoken\b|\bcredentials?\b|\bpassword\b|\bpasswd\b|"
    r"\bapi[_-]?key\b|\bclient[_-]?secret\b|\bbearer\b|\boauth\b|"
    r"source/state|/private/|/Users/|/Volumes/|file://|https?://|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)
_ENGINEERING_PATTERN = re.compile(
    r"(?:schema_version|raw_file_id|raw_sha256|evidence_ref|sha256|provider_calls|"
    r"output_id|content_json|skill_run_id|error_code|lineage_json|logical_key|"
    r"dedupe_key|workflow_key|revision_no|inventory_id|activity_inventory_id)",
    re.IGNORECASE,
)
_CHART_TITLES = {
    "daily_activity_hr_zones": "历史活动 · 设备记录心率分区",
    "daily_sleep_stages": "昨夜睡眠阶段",
    "daily_activity_heart_rate": "历史活动 · 心率变化",
    "weekly_sleep": "七日睡眠时长",
    "weekly_rhr": "七日静息心率",
    "weekly_hrv": "七日昨夜 HRV",
    "weekly_running_distance": "七日跑量",
    "weekly_activity_duration": "七日活动时长",
    "weekly_activity_hr_zones": "本周设备记录心率分区",
}
_STACKED_LABELS = {
    "daily_activity_hr_zones": ("低于Z1", "Z1", "Z2", "Z3", "Z4", "Z5", "高于Z5"),
    "weekly_activity_hr_zones": ("低于Z1", "Z1", "Z2", "Z3", "Z4", "Z5", "高于Z5"),
    "daily_sleep_stages": ("深睡", "浅睡", "REM", "清醒"),
}
_PALETTE = ("#6A777D", "#26744B", "#087B8C", "#48548E", "#B85B18", "#A7372F", "#71355A")
_ROLE_CONTRACTS = {
    "daily_activity_hr_zones": ("stacked_duration", "seconds"),
    "daily_sleep_stages": ("stacked_duration", "seconds"),
    "weekly_activity_hr_zones": ("stacked_duration", "seconds"),
    "daily_activity_heart_rate": ("series", "bpm"),
    "weekly_sleep": ("series", "hours"),
    "weekly_rhr": ("series", "bpm"),
    "weekly_hrv": ("series", "ms"),
    "weekly_running_distance": ("series", "km"),
    "weekly_activity_duration": ("series", "minutes"),
}
_PHASE_LABELS = {
    "warmup": "热身",
    "main": "主训练",
    "recovery": "恢复",
    "cooldown": "放松",
    "checklist": "检查",
}
_SESSION_LABELS = {
    "recovery_run": "恢复跑",
    "easy_run": "轻松跑",
    "long_easy": "长距离轻松跑",
    "sos_threshold": "SOS 阈值跑",
    "sos_cruise_intervals": "SOS 巡航间歇",
    "sos_hills": "SOS 坡道训练",
    "climbing_technique": "攀岩技术课",
    "climbing_hard": "高负荷攀岩",
    "rest": "休息",
}
_DISPLAY_UNITS = {
    "hours": "小时",
    "minutes": "分钟",
    "seconds": "秒",
}
_AXIS_UNITS = {
    "hours": "h",
    "minutes": "min",
}
_ICON_CONTRACTS = {
    "email_brand_mark": (96, 96, "TrainLab"),
    "email_status_ready": (64, 64, "可以训练"),
    "email_status_caution": (64, 64, "需要谨慎"),
    "email_status_blocked": (64, 64, "报告已阻断"),
}
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")


@dataclass(frozen=True)
class InlineAsset:
    role: str
    cid: str
    filename: str
    media_type: str
    width_px: int
    height_px: int
    sha256: str
    alt: str
    data: bytes

    def manifest(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "cid": self.cid,
            "filename": self.filename,
            "media_type": self.media_type,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "byte_size": len(self.data),
            "sha256": self.sha256,
            "alt": self.alt,
        }


@dataclass(frozen=True)
class RenderedEmail:
    payload: dict[str, Any]
    assets: tuple[InlineAsset, ...]


def _format_number(value: object, digits: int = 1) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = round(float(value), digits)
    return str(int(number)) if number.is_integer() else f"{number:.{digits}f}"


def _format_duration(seconds: object) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "—"
    minutes = max(0, round(float(seconds) / 60))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}小时{remainder}分"
    return f"{hours}小时" if hours else f"{remainder}分钟"


def _format_pace(seconds: object) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "—"
    minutes, remainder = divmod(round(float(seconds)), 60)
    return f"{minutes}:{remainder:02d}/km"


def _display_unit(unit: object) -> str:
    return _DISPLAY_UNITS.get(str(unit), str(unit))


def _format_sleep_clock_range(start: object, end: object) -> str:
    if not isinstance(start, str) or not isinstance(end, str):
        return "时间待确认"
    try:
        parsed = []
        for value in (start, end):
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if instant.tzinfo is not None:
                instant = instant.astimezone(_HONG_KONG)
            parsed.append(instant)
    except ValueError:
        return "时间待确认"
    start_time, end_time = parsed
    day_span = (end_time.date() - start_time.date()).days
    if 0 <= day_span <= 1:
        return f"{start_time:%H:%M}–{end_time:%H:%M}"
    return f"{start_time:%Y-%m-%d %H:%M}–{end_time:%Y-%m-%d %H:%M}"


def _chart_alt(chart: dict[str, Any]) -> str:
    if chart["chart_type"] == "stacked_duration":
        parts = [
            f"{item['label']} {_format_number(item['percentage'], 2)}% · {_format_duration(item['duration_seconds'])}"
            for item in chart["segments"]
        ]
        return f"{chart['title']}：" + "；".join(parts)
    points = chart["points"]
    if len(points) <= 14:
        summary = "；".join(
            f"{_point_label(chart, item['x'])} {_format_number(item['y'])} {_display_unit(chart['unit'])}"
            for item in points
        )
    else:
        values = [float(item["y"]) for item in points]
        summary = (
            f"{len(points)}个实测点；"
            f"起点 {_point_label(chart, points[0]['x'])} {_format_number(points[0]['y'])} {_display_unit(chart['unit'])}；"
            f"终点 {_point_label(chart, points[-1]['x'])} {_format_number(points[-1]['y'])} {_display_unit(chart['unit'])}；"
            f"最低 {_format_number(min(values))} {_display_unit(chart['unit'])}；"
            f"最高 {_format_number(max(values))} {_display_unit(chart['unit'])}"
        )
    return f"{chart['title']}：{summary}"


def _point_label(chart: dict[str, Any], value: object) -> str:
    if chart["role"] == "daily_activity_heart_rate" and isinstance(value, int):
        minutes, seconds = divmod(value, 60)
        return f"{minutes}:{seconds:02d}"
    return str(value)


def _validate_chart(chart: dict[str, Any]) -> None:
    role = str(chart.get("role"))
    if chart.get("title") != _CHART_TITLES.get(role):
        raise ValueError("email_chart_title_invalid")
    if (chart.get("chart_type"), chart.get("unit")) != _ROLE_CONTRACTS.get(role):
        raise ValueError("email_chart_role_contract_invalid")
    if chart.get("chart_type") == "stacked_duration":
        labels = tuple(str(item.get("label")) for item in chart.get("segments", []))
        if labels != _STACKED_LABELS.get(role):
            raise ValueError("email_chart_segments_invalid")
        if chart.get("percentage_source") != "derived_from_provider_duration":
            raise ValueError("email_chart_percentage_source_invalid")
        durations = [float(item["duration_seconds"]) for item in chart["segments"]]
        if any(not math.isfinite(value) or value < 0 for value in durations):
            raise ValueError("email_chart_duration_invalid")
        total = sum(durations)
        if total <= 0:
            raise ValueError("email_chart_duration_invalid")
        for item, duration in zip(chart["segments"], durations):
            expected = round(duration / total * 100, 2)
            actual = float(item["percentage"])
            if not math.isfinite(actual) or abs(actual - expected) > 0.001:
                raise ValueError("email_chart_percentage_mismatch")
    else:
        points = chart.get("points", [])
        if (
            len(points) < 2
            or len(points) > 2880
            or len({canonical_json(item["x"]) for item in points}) != len(points)
            or any(not math.isfinite(float(item["y"])) for item in points)
        ):
            raise ValueError("email_chart_points_invalid")


def _chart_asset(chart: dict[str, Any]) -> InlineAsset:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise ValueError("email_chart_renderer_unavailable") from exc
    _validate_chart(chart)
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 72, 54, CHART_WIDTH - 48, CHART_HEIGHT - 64
    if chart["chart_type"] == "stacked_duration":
        x_position = float(left)
        width = right - left
        for index, segment in enumerate(chart["segments"]):
            segment_width = width * float(segment["percentage"]) / 100
            next_x = (
                float(right)
                if index == len(chart["segments"]) - 1
                else x_position + segment_width
            )
            draw.rounded_rectangle(
                (round(x_position), top + 80, round(next_x), bottom - 80),
                radius=16,
                fill=_PALETTE[index % len(_PALETTE)],
            )
            x_position = next_x
        legend_y = bottom - 35
        for index, segment in enumerate(chart["segments"]):
            legend_x = left + index * max(1, (right - left) // len(chart["segments"]))
            draw.text(
                (legend_x, legend_y),
                f"{index + 1}:{_format_number(segment['percentage'])}%",
                fill=_PALETTE[index % len(_PALETTE)],
            )
    else:
        points = chart["points"]
        values = [float(item["y"]) for item in points]
        if len(values) < 2 or any(not math.isfinite(value) for value in values):
            raise ValueError("email_chart_points_invalid")
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = round(top + (bottom - top) * fraction)
            draw.line((left, y, right, y), fill="#D7E4E6", width=2)
        low, high = min(values), max(values)
        padding = max(1.0, (high - low) * 0.1)
        denominator = max(high - low + 2 * padding, 1.0)
        coordinates = []
        for index, value in enumerate(values):
            x_coordinate = left + (right - left) * index / (len(values) - 1)
            y_coordinate = (
                bottom - (bottom - top) * (value - low + padding) / denominator
            )
            coordinates.append((round(x_coordinate), round(y_coordinate)))
        color = {
            "daily_activity_heart_rate": "#087B8C",
            "weekly_sleep": "#48548E",
            "weekly_rhr": "#B85B18",
            "weekly_hrv": "#26744B",
            "weekly_running_distance": "#087B8C",
            "weekly_activity_duration": "#71355A",
        }.get(str(chart["role"]), "#087A78")
        draw.line(coordinates, fill=color, width=8, joint="curve")
        for x, y in coordinates:
            draw.ellipse(
                (x - 8, y - 8, x + 8, y + 8), fill="#FFFFFF", outline=color, width=5
            )
        label_indexes = sorted({0, len(points) // 2, len(points) - 1})
        for index in label_indexes:
            x, _y = coordinates[index]
            label = _point_label(chart, points[index]["x"])
            draw.text((max(left, x - 28), bottom + 12), label[-10:], fill="#40535A")
        draw.text(
            (left, top - 24),
            _AXIS_UNITS.get(str(chart["unit"]), str(chart["unit"])),
            fill="#40535A",
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    data = buffer.getvalue()
    chart_sha = hashlib.sha256(canonical_json(chart).encode()).hexdigest()
    role = str(chart["role"])
    return InlineAsset(
        role=role,
        cid=f"trainlab-{role}-{chart_sha[:24]}@trainlab.invalid",
        filename=f"{role.replace('_', '-')}-{chart_sha[:12]}.png",
        media_type="image/png",
        width_px=CHART_WIDTH,
        height_px=CHART_HEIGHT,
        sha256=hashlib.sha256(data).hexdigest(),
        alt=_chart_alt(chart),
        data=data,
    )


def _icon_asset(role: str) -> InlineAsset:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise ValueError("email_icon_renderer_unavailable") from exc
    contract = _ICON_CONTRACTS.get(role)
    if contract is None:
        raise ValueError("email_icon_role_invalid")
    width, height, alt = contract
    scale = 4
    image = Image.new("RGBA", (width * scale, height * scale), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    def points(values: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
        return [(x * scale, y * scale) for x, y in values]

    if role == "email_brand_mark":
        draw.rounded_rectangle(
            (0, 0, 96 * scale - 1, 96 * scale - 1),
            radius=22 * scale,
            fill="#087A78",
        )
        draw.polygon(
            points(
                (
                    (22, 27),
                    (53, 27),
                    (53, 38),
                    (43, 38),
                    (43, 71),
                    (32, 71),
                    (32, 38),
                    (22, 38),
                )
            ),
            fill="#FFFFFF",
        )
        draw.polygon(
            points(((56, 27), (67, 27), (67, 60), (82, 60), (82, 71), (56, 71))),
            fill="#FFFFFF",
        )
    elif role == "email_status_ready":
        draw.ellipse((3 * scale, 3 * scale, 61 * scale, 61 * scale), fill="#1B6F47")
        draw.line(
            points(((19, 32), (27, 40), (45, 21))),
            fill="#FFFFFF",
            width=6 * scale,
            joint="curve",
        )
    elif role == "email_status_caution":
        draw.polygon(points(((32, 5), (61, 56), (3, 56))), fill="#E6B94A")
        draw.line(
            points(((32, 21), (32, 38))),
            fill="#5D3A00",
            width=6 * scale,
        )
        draw.ellipse(
            (28.5 * scale, 43.5 * scale, 35.5 * scale, 50.5 * scale),
            fill="#5D3A00",
        )
    else:
        draw.polygon(
            points(
                (
                    (20, 4),
                    (44, 4),
                    (60, 20),
                    (60, 44),
                    (44, 60),
                    (20, 60),
                    (4, 44),
                    (4, 20),
                )
            ),
            fill="#A7372F",
        )
        draw.line(
            points(((18, 32), (46, 32))),
            fill="#FFFFFF",
            width=7 * scale,
        )
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    return InlineAsset(
        role=role,
        cid=f"trainlab-{role}-{digest[:24]}@trainlab.invalid",
        filename=f"{role.replace('_', '-')}-{digest[:12]}.png",
        media_type="image/png",
        width_px=width,
        height_px=height,
        sha256=digest,
        alt=alt,
        data=data,
    )


def _require_asset(assets: tuple[InlineAsset, ...], role: str) -> InlineAsset:
    matches = [asset for asset in assets if asset.role == role]
    if len(matches) != 1:
        raise ValueError("email_inline_asset_missing")
    return matches[0]


def _component(name: str, body: str, *, css_class: str = "section") -> str:
    styles = {
        "section": "width:100%;margin:0 0 20px;border:1px solid #D7E4E6;border-radius:16px;background:#FFFFFF;",
        "hero-wrap": "width:100%;margin:0 0 20px;background:#FFFFFF;",
        "header": "width:100%;background:#FFFFFF;color:#17323B;border-bottom:1px solid #D7E4E6;",
        "privacy": "width:100%;color:#556970;font-size:11px;",
        "card sleep-card": "width:100%;background:#E9EBF7;color:#414A82;border-radius:16px;",
        "card recovery-card": "width:100%;background:#E7F5ED;color:#1B6F47;border-radius:16px;",
    }
    cell_styles = {
        "section": "padding:22px;",
        "hero-wrap": "padding:0;",
        "header": "padding:28px 24px 22px;",
        "privacy": "padding:4px 32px 28px;",
        "card sleep-card": "padding:20px;",
        "card recovery-card": "padding:20px;",
    }
    cell_classes = {
        "section": "section-cell",
        "hero-wrap": "hero-cell",
        "header": "header-cell",
        "privacy": "privacy-cell",
        "card sleep-card": "card-cell",
        "card recovery-card": "card-cell",
    }
    body = (
        body.replace(
            "<h1>",
            '<h1 class="header-title" style="margin:3px 0 0;font-size:28px;line-height:1.2;letter-spacing:-.015em;color:#17323B;font-weight:600;">',
        )
        .replace(
            "<h2>", '<h2 style="margin:0 0 12px;font-size:22px;line-height:1.35;">'
        )
        .replace(
            "<h3>", '<h3 style="margin:18px 0 8px;font-size:18px;line-height:1.4;">'
        )
        .replace(
            '<div class="eyebrow">',
            '<div class="eyebrow" style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">',
        )
        .replace(
            '<div class="metric-row">',
            '<div class="metric-row" style="margin-bottom:8px;">',
        )
        .replace(
            '<div class="empty">',
            '<div class="empty" style="padding:16px;border-radius:12px;background:#EDF1F2;color:#40535A;">',
        )
    )
    return (
        f'<table role="presentation" width="100%" class="{css_class}" '
        f'data-component="{name}" style="{styles[css_class]}"><tr>'
        f'<td class="{cell_classes[css_class]}" style="{cell_styles[css_class]}">{body}</td></tr></table>'
    )


def _hero_inline(css_class: str) -> str:
    return {
        "hero-ready": "background:#E7F5ED;color:#1B6F47;border:1px solid #A9D7BD;",
        "hero-caution": "background:#FFF2CF;color:#8A5700;border:1px solid #E6C66D;",
        "hero-blocked": "background:#FDE9E6;color:#A7372F;border:1px solid #E6AAA4;",
        "hero-neutral": "background:#EDF1F2;color:#40535A;border:1px solid #CAD8DB;",
    }[css_class]


def _list(items: list[str]) -> str:
    return (
        '<ul style="margin:8px 0 0;padding-left:20px;">'
        + "".join(
            f'<li style="margin:5px 0;">{escape(str(item))}</li>' for item in items
        )
        + "</ul>"
    )


def _course_html(course: dict[str, Any], *, detailed: bool) -> str:
    dose = []
    if course.get("duration_minutes") is not None:
        dose.append(f"{_format_number(course['duration_minutes'])} 分钟")
    if course.get("distance_km") is not None:
        dose.append(f"{_format_number(course['distance_km'])} km")
    dose.append(
        f"RPE {_format_number(course['rpe_min'])}–{_format_number(course['rpe_max'])}/10"
    )
    session_label = _SESSION_LABELS.get(
        str(course["session_type"]), str(course["session_type"])
    )
    head = (
        '<div class="course-head" style="margin:0;">'
        '<span class="tag" style="display:inline-block;padding:3px 10px;border-radius:999px;'
        'background:#DDF2F4;color:#086B79;font-size:12px;font-weight:700;">'
        f"{escape(session_label)}</span>"
        f'<h3 style="font-size:18px;line-height:1.35;margin:8px 0;">{escape(str(course["name"]))}</h3>'
        f'<p style="margin:6px 0;">{escape(str(course["purpose"]))}</p>'
        f'<p class="muted" style="margin:6px 0;font-size:13px;color:#556970;">{" · ".join(dose)}</p>'
        f'<p style="margin:6px 0;"><strong>体感：</strong>{escape(str(course["feel_guidance"]))}</p></div>'
    )
    if not detailed:
        return head
    steps = "".join(
        '<tr><td class="step-phase" valign="top" style="width:82px;padding:11px 8px;'
        'border-bottom:1px solid #E4ECEE;color:#087A78;font-weight:700;">'
        f"{escape(_PHASE_LABELS.get(str(step['phase']), str(step['name'])))}</td>"
        '<td class="step-body" valign="top" style="padding:11px 8px;border-bottom:1px solid #E4ECEE;">'
        f"<strong>{escape(str(step['name']))}</strong><br>{escape(str(step['instruction']))}"
        f'<div class="muted" style="font-size:13px;color:#556970;margin-top:4px;">结束条件：{escape(str(step["end_condition"]))}</div></td></tr>'
        for step in course["steps"]
    )
    return (
        head
        + f'<table role="presentation" width="100%" class="steps" style="width:100%;margin-top:12px;border-collapse:collapse;">{steps}</table>'
        + f'<h4 style="margin:14px 0 6px;">开始前检查</h4>{_list(course["start_gate"])}'
        + f'<h4 style="margin:14px 0 6px;">执行提示</h4>{_list(course["technique_notes"])}'
        + f'<p class="downgrade" style="padding:12px;background:#FFF2CF;border-radius:10px;"><strong>降级方案：</strong>{escape(str(course["downgrade_rule"]))}</p>'
        + f'<h4 class="danger" style="margin:14px 0 6px;color:#A7372F;">停止条件</h4>{_list(course["stop_conditions"])}'
    )


def _activity_kpi(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">昨日没有已验证活动。</div>'
    blocks = []
    for item in items:
        metrics = [
            (
                "距离",
                f"{_format_number(item.get('distance_km'))} km"
                if item.get("distance_km") is not None
                else "—",
            ),
            ("时长", _format_duration(item["duration_seconds"])),
            ("平均配速", _format_pace(item.get("pace_seconds_per_km"))),
            (
                "心率",
                f"{_format_number(item.get('heart_rate_average_bpm'))} / {_format_number(item.get('heart_rate_maximum_bpm'))} bpm"
                if item.get("heart_rate_average_bpm") is not None
                else "—",
            ),
        ]
        rows = []
        for offset in range(0, len(metrics), 4):
            cells = "".join(
                '<td class="kpi-cell" width="25%" valign="top" '
                'style="padding:14px 10px;border:1px solid #D7E4E6;">'
                f'<div class="eyebrow" style="font-size:12px;font-weight:700;">{escape(label)}</div>'
                f'<div class="kpi-value" style="font-size:21px;font-weight:700;margin:5px 0;">{escape(value)}</div></td>'
                for label, value in metrics[offset : offset + 4]
            )
            rows.append(f"<tr>{cells}</tr>")
        blocks.append(
            f'<h3 style="margin:0 0 10px;">{escape(str(item["label"]))}</h3>'
            '<table role="presentation" width="100%" class="kpi-table" '
            f'style="width:100%;table-layout:fixed;">{"".join(rows)}</table>'
        )
    return "".join(blocks)


def _metric_html(item: dict[str, Any] | None, missing: str = "暂无数据") -> str:
    if not isinstance(item, dict):
        return f'<div class="metric-value" style="font-size:21px;font-weight:700;margin:5px 0;">{missing}</div>'
    return (
        f'<div class="metric-value" style="font-size:21px;font-weight:700;margin:5px 0;">{escape(_format_number(item["value"]))} {escape(str(item["unit"]))}</div>'
        f'<div class="muted" style="font-size:13px;color:#556970;">更新于 {escape(str(item["observed_date"]))}</div>'
    )


def _charts_html(charts: list[dict[str, Any]], assets: tuple[InlineAsset, ...]) -> str:
    chart_assets = [asset for asset in assets if asset.role in _ROLE_CONTRACTS]
    if len(chart_assets) != len(charts):
        raise ValueError("email_chart_asset_count_invalid")
    blocks = []
    for chart, asset in zip(charts, chart_assets):
        blocks.append(
            '<table role="presentation" width="100%" class="chart-card" '
            'style="width:100%;margin-top:14px;border:1px solid #D7E4E6;border-radius:14px;"><tr><td style="padding:16px;">'
            f'<h3 style="margin:0 0 10px;font-size:18px;">{escape(str(chart["title"]))}</h3>'
            f'<img src="cid:{escape(asset.cid)}" width="624" alt="{escape(asset.alt)}" '
            'style="display:block;width:100%;max-width:624px;height:auto;border:0">'
            + _chart_fallback_html(chart)
            + "</td></tr></table>"
        )
    return "".join(blocks)


def _chart_fallback_html(chart: dict[str, Any]) -> str:
    if chart["chart_type"] == "stacked_duration":
        rows = "".join(
            "<tr>"
            f'<td style="padding:5px;border-bottom:1px solid #E4ECEE;">{escape(str(item["label"]))}</td>'
            f'<td style="padding:5px;border-bottom:1px solid #E4ECEE;">{escape(_format_duration(item["duration_seconds"]))}</td>'
            f'<td style="padding:5px;border-bottom:1px solid #E4ECEE;">{escape(_format_number(item["percentage"], 2))}%</td>'
            "</tr>"
            for item in chart["segments"]
        )
        headings = "<th>类别</th><th>时长</th><th>占比</th>"
    else:
        summary = escape(_chart_alt(chart))
        return (
            '<div class="chart-fallback" style="font-size:12px;color:#556970;margin-top:8px;">'
            "图片不可用时："
            f'<p style="margin:6px 0;line-height:1.6;overflow-wrap:anywhere;">{summary}</p></div>'
        )
    return (
        '<div class="chart-fallback" style="font-size:12px;color:#556970;margin-top:8px;">'
        "图片不可用时，以下表格保留全部输入值："
        '<table role="presentation" width="100%" style="margin-top:6px;border-collapse:collapse;">'
        f"<tr>{headings}</tr>{rows}</table></div>"
    )


def _header_html(title: str, eyebrow: str, asset: InlineAsset) -> str:
    return (
        '<table role="presentation" width="100%" style="width:100%;border-collapse:collapse;"><tr>'
        '<td width="52" valign="middle" style="width:52px;">'
        f'<img src="cid:{escape(asset.cid)}" width="48" height="48" alt="TrainLab" '
        'data-asset-role="email_brand_mark" style="display:block;width:48px;height:48px;border:0;border-radius:12px;">'
        '</td><td valign="middle" style="padding-left:12px;">'
        f'<div class="eyebrow" style="color:#556970;">{escape(eyebrow)}</div>'
        f"<h1>{escape(title)}</h1></td></tr></table>"
    )


def _daily_status_hero(
    label: str,
    copy: str,
    css_class: str,
    status_asset: InlineAsset,
    error_detail: str,
) -> str:
    return (
        f'<table role="presentation" width="100%" class="hero {css_class}" '
        f'style="width:100%;border-radius:16px;{_hero_inline(css_class)}"><tr>'
        '<td width="56" valign="top" style="width:56px;padding:22px 0 22px 22px;">'
        f'<img src="cid:{escape(status_asset.cid)}" width="40" height="40" alt="{escape(label)}" '
        f'data-asset-role="{escape(status_asset.role)}" style="display:block;width:40px;height:40px;border:0;">'
        '</td><td valign="top" style="padding:20px 22px 20px 14px;">'
        f'<div style="font-size:13px;line-height:1.4;letter-spacing:.02em;font-weight:600;">今日状态 · {escape(label)}</div>'
        f'<div style="margin-top:5px;font-size:20px;line-height:1.45;color:#17323B;font-weight:600;">{escape(copy)}</div>'
        f"{error_detail}</td></tr></table>"
    )


def _daily_html(view: dict[str, Any], assets: tuple[InlineAsset, ...]) -> str:
    status_copy = {
        "ready": ("可以训练", "可按开始门执行今天的课程。", "hero-ready"),
        "caution": (
            "需要谨慎",
            "优先执行降级后的课程，并持续观察恢复。",
            "hero-caution",
        ),
        "blocked": ("报告已阻断", "关键证据补齐前不执行课程。", "hero-blocked"),
    }[str(view["safety"])]
    brand_asset = _require_asset(assets, "email_brand_mark")
    status_asset = _require_asset(assets, f"email_status_{view['safety']}")
    planned_note = (
        "已验证的历史原课"
        if view["planned_course_context"] == "verified_original"
        else "隔离测试基准课，不冒充历史原课"
    )
    blocked = view["status"] == "blocked"
    planned = _course_html(view["planned_course"], detailed=False)
    effective = _course_html(view["effective_course"], detailed=False)
    sleep = view.get("sleep_card")
    sleep_html = (
        f'<div class="metric-value" style="font-size:21px;font-weight:700;margin:5px 0;">{_format_duration(sleep["duration_seconds"])}</div>'
        f'<div class="muted" style="font-size:13px;color:#556970;">{escape(_format_sleep_clock_range(sleep["start"], sleep["end"]))} · 数据完整</div>'
        if isinstance(sleep, dict)
        else '<div class="metric-value" style="font-size:21px;font-weight:700;margin:5px 0;">暂无主睡眠数据</div>'
    )
    health = view["health_cards"]
    trend = view["recent_trend"]
    chart_section = (
        _component(
            "StaticCharts",
            "<h2>真实数据图表</h2>" + _charts_html(view["charts"], assets),
        )
        if view["charts"]
        else ""
    )
    course_sections = ""
    if not blocked:
        course_sections = _component(
            "CourseComparison",
            "<h2>周计划原课与今日调整</h2>"
            f'<p class="muted">{escape(planned_note)}</p><table role="presentation" width="100%"><tr>'
            f'<td class="course-column" width="50%" valign="top" style="padding:14px;border:1px solid #D7E4E6;"><div class="eyebrow">原课</div>{planned}</td>'
            f'<td class="course-column" width="50%" valign="top" style="padding:14px;border:1px solid #D7E4E6;"><div class="eyebrow">调整后</div>{effective}</td></tr></table>'
            "<h3>调整原因</h3>" + _list(view["decision_reasons"]),
        ) + _component(
            "CourseDetails",
            "<h2>今天怎么练</h2>"
            + _course_html(view["effective_course"], detailed=True),
        )
    error_detail = (
        f"<p><strong>错误代码：</strong>{escape(str(view.get('error_code') or '未提供'))}</p>"
        if blocked
        else ""
    )
    limit_section = (
        _component(
            "DataLimits",
            "<h2>数据限制</h2>" + _list(view["data_limits"]),
        )
        if view["data_limits"]
        else ""
    )
    sleep_component = _component(
        "SleepCard", "<h2>睡眠</h2>" + sleep_html, css_class="card sleep-card"
    )
    recovery_component = _component(
        "RecoveryCard",
        '<h2>恢复</h2><div class="metric-row"><div>RHR</div>'
        + _metric_html(health["rhr"])
        + '</div><div class="metric-row"><div>HRV</div>'
        + _metric_html(health["hrv"])
        + "</div>",
        css_class="card recovery-card",
    )
    health_cards = (
        '<table role="presentation" width="100%" class="two-column"><tr>'
        f'<td width="50%" valign="top">{sleep_component}</td>'
        f'<td width="50%" valign="top">{recovery_component}</td>'
        "</tr></table>"
    )
    body = "".join(
        [
            _component(
                "Header",
                _header_html(str(view["title"]), "TRAINLAB DAILY", brand_asset),
                css_class="header",
            ),
            '<div class="pad" style="padding:28px 32px;">',
            _component(
                "SafetyHero",
                _daily_status_hero(
                    status_copy[0],
                    status_copy[1],
                    status_copy[2],
                    status_asset,
                    error_detail,
                ),
                css_class="hero-wrap",
            ),
            _component(
                "TrainingInterpretation",
                f"<h2>昨日训练怎么理解</h2><p>{escape(str(view['yesterday_summary']))}</p>",
            ),
            _component(
                "HealthInterpretation",
                f"<h2>昨日健康数据</h2><p>{escape(str(view['review_health_summary']))}</p>",
            ),
            _component(
                "RecoveryInterpretation",
                f"<h2>昨夜睡眠与恢复</h2><p>{escape(str(view['recovery_summary']))}</p>",
            ),
            course_sections,
            _component(
                "ActivityKPI",
                "<h2>昨日训练</h2>" + _activity_kpi(view["activity_kpis"]),
            ),
            health_cards,
            _component(
                "HealthSnapshot",
                '<h2>健康快照</h2><table role="presentation" width="100%"><tr>'
                f'<td class="metric-cell" width="50%" style="padding:16px;border:1px solid #D7E4E6;"><strong>VO₂ Max</strong>{_metric_html(health["vo2_max"])}</td>'
                f'<td class="metric-cell" width="50%" style="padding:16px;border:1px solid #D7E4E6;"><strong>体重</strong>{_metric_html(health["weight"])}</td></tr></table>',
            ),
            chart_section,
            limit_section,
            _component(
                "TrendSummary",
                "<h2>近14天压缩趋势</h2>"
                f"<p>可用 {_format_number(trend.get('days_available'), 0)} 天 · 平均睡眠 {_format_number(trend.get('sleep_average_hours'))} 小时 · 跑量 {_format_number(trend.get('running_distance_km'))} km</p>",
            ),
            _component(
                "Evidence",
                "<h2>证据与限制</h2>"
                + _list(
                    view["evidence_labels"] + view["uncertainty"] + view["data_limits"]
                ),
            ),
            "</div>",
            _component(
                "Privacy",
                "仅用于个人训练复盘，不替代医疗诊断。图表不展示个人定位或原始逐点文件。",
                css_class="privacy",
            ),
        ]
    )
    return _document(view["title"], body)


def _weekly_plan(plan: dict[str, Any]) -> str:
    cards = []
    for course in plan["items"]:
        cards.append(
            '<table role="presentation" width="100%" class="plan-card" '
            'style="width:100%;margin:0 0 12px;border:1px solid #D7E4E6;border-radius:16px;">'
            '<tr><td class="plan-date" style="padding:12px 16px;background:#EDF1F2;font-weight:700;">'
            f'{escape(str(course["date"]))}</td></tr><tr><td class="plan-body" style="padding:16px;">'
            + _course_html(course, detailed=True)
            + "</td></tr></table>"
        )
    return "".join(cards)


def _weekly_html(view: dict[str, Any], assets: tuple[InlineAsset, ...]) -> str:
    blocked = view["status"] == "blocked"
    brand_asset = _require_asset(assets, "email_brand_mark")
    decision = {
        "advance": ("小幅进阶", "一次只增加一个负荷维度", "hero-ready"),
        "hold": ("维持负荷", "先提高恢复稳定性，再讨论加量", "hero-neutral"),
        "deload": ("主动减量", "优先恢复，取消不必要的质量刺激", "hero-caution"),
    }[str(view["progression_rule"])]
    if blocked:
        decision = (
            "报告已阻断",
            f"错误代码：{view.get('error_code') or '未提供'}。不展示推进决策或可执行计划。",
            "hero-blocked",
        )
    kpi = view["weekly_kpis"]
    metrics = (
        ("日报", "7份"),
        ("谨慎日", f"{kpi['caution_days']}天"),
        ("跑量", f"{_format_number(kpi['running_distance_km'])} km"),
        ("活动", f"{kpi['activity_count']}次"),
        ("平均睡眠", f"{_format_number(kpi['average_sleep_hours'])}小时"),
    )
    kpi_rows = []
    for offset in range(0, len(metrics), 4):
        cells = "".join(
            '<td class="kpi-cell" width="25%" style="padding:14px 10px;border:1px solid #D7E4E6;">'
            f'<div class="eyebrow" style="font-size:12px;font-weight:700;">{label}</div>'
            f'<div class="kpi-value" style="font-size:21px;font-weight:700;margin:5px 0;">{value}</div></td>'
            for label, value in metrics[offset : offset + 4]
        )
        kpi_rows.append(f"<tr>{cells}</tr>")
    insights = "".join(
        '<table role="presentation" width="100%" class="insight" style="margin:10px 0;table-layout:fixed;"><tr>'
        f'<td style="padding:13px;border:1px solid #D7E4E6;"><strong>观察</strong><br>{escape(str(item["observation"]))}</td>'
        f'<td style="padding:13px;border:1px solid #D7E4E6;"><strong>意义</strong><br>{escape(str(item["meaning"]))}</td>'
        f'<td style="padding:13px;border:1px solid #D7E4E6;"><strong>行动</strong><br>{escape(str(item["action"]))}</td></tr></table>'
        for item in view["insights"]
    )
    normal_sections = ""
    if not blocked:
        normal_sections = "".join(
            [
                _component(
                    "WeekComparison",
                    "<h2>周对比</h2>"
                    f"<p>{escape(str(view['week_comparison']['summary']))}</p>",
                ),
                _component(
                    "StaticCharts",
                    "<h2>七日趋势</h2>" + _charts_html(view["charts"], assets),
                )
                if view["charts"]
                else "",
                _component("InsightCards", "<h2>观察 → 意义 → 行动</h2>" + insights),
                _component(
                    "PlanTimeline",
                    "<h2>下周七日详细计划</h2>" + _weekly_plan(view["training_plan"]),
                ),
            ]
        )
    body = "".join(
        [
            _component(
                "Header",
                _header_html(str(view["title"]), "TRAINLAB WEEKLY", brand_asset),
                css_class="header",
            ),
            '<div class="pad" style="padding:28px 32px;">',
            _component(
                "WeeklyDecisionHero",
                f'<div class="hero {decision[2]}" style="padding:22px;border-radius:16px;{_hero_inline(decision[2])}"><div class="eyebrow">NEXT WEEK</div><h2>{decision[0]}</h2><p>{decision[1]}</p></div><h3>健康总结</h3><p>{escape(str(view["health_summary"]))}</p><h3>运动与负荷总结</h3><p>{escape(str(view["activity_summary"]))}</p>',
                css_class="hero-wrap",
            ),
            _component(
                "WeeklyKPI",
                '<h2>本周关键数据</h2><table role="presentation" width="100%" class="kpi-table" style="width:100%;table-layout:fixed;">'
                + "".join(kpi_rows)
                + "</table>",
            ),
            normal_sections,
            _component(
                "DataLimits",
                "<h2>数据限制</h2>"
                + (
                    _list(view["uncertainty"] + view["data_limits"])
                    if view["uncertainty"] or view["data_limits"]
                    else "<p>本周没有额外数据限制。</p>"
                ),
            ),
            _component(
                "Evidence",
                "<h2>证据说明</h2><p>本周图表只聚合精确七份日报展示证据，不重新读取原始文件。</p>",
            ),
            "</div>",
            _component(
                "Privacy",
                "课程强度只使用 RPE、体感和历史参考配速；设备训练目标由 Garmin 负责。",
                css_class="privacy",
            ),
        ]
    )
    return _document(view["title"], body)


def _styles() -> str:
    return """<style>
@media only screen and (max-width:375px){.shell{width:100%!important}.header-cell,.pad{padding-left:18px!important;padding-right:18px!important}.header-title{font-size:23px!important}.section-cell,.hero-cell{padding:16px!important}.course-column,.two-column>tbody>tr>td{display:block!important;width:100%!important;box-sizing:border-box}.kpi-table td{display:inline-block!important;width:50%!important;box-sizing:border-box}.insight td{display:block!important;width:100%!important;box-sizing:border-box}.card{margin:5px 0!important}.privacy-cell{padding-left:18px!important;padding-right:18px!important}}
@media (prefers-color-scheme:dark){body{background:#12252B!important}.shell,.section,.hero-wrap{background:#17323B!important;color:#F4F8F8!important}.section,.hero-wrap,.chart-card,.course-column,.metric-cell,.kpi-cell,.insight td{border-color:#456069!important}.muted,.chart-fallback,.privacy{color:#D7E4E6!important}}
</style>"""


def _document(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(str(title))}</title>{_styles()}</head>"
        '<body style="margin:0;background:#F4F8F8;color:#17323B;font-family:-apple-system,'
        "BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;line-height:1.55;\">"
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(str(title))} · 训练与恢复重点</div>'
        '<table role="presentation" width="100%" style="width:100%;border-collapse:collapse;background:#F4F8F8;"><tr><td align="center" style="padding:24px 12px 40px;">'
        f'<table role="presentation" class="shell" width="100%" style="width:100%;max-width:672px;border-collapse:separate;border-spacing:0;background:#FFFFFF;border:1px solid #D7E4E6;border-radius:20px;overflow:hidden;"><tr><td style="padding:0;">{body}</td></tr></table>'
        "</td></tr></table></body></html>"
    )


def _plain_text(view: dict[str, Any], assets: tuple[InlineAsset, ...]) -> str:
    lines = [str(view["title"]), ""]
    if view["kind"] == "daily":
        lines.extend(
            [
                f"昨日训练：{view['yesterday_summary']}",
                f"昨日健康：{view['review_health_summary']}",
                f"昨夜恢复：{view['recovery_summary']}",
            ]
        )
        if view["status"] != "blocked":
            lines.extend(
                [
                    "",
                    f"周计划原课：{view['planned_course']['name']}",
                    f"今日调整：{view['effective_course']['name']}",
                    "",
                    "今天怎么练",
                ]
            )
            course = view["effective_course"]
            lines.extend(
                f"- {_PHASE_LABELS.get(str(step['phase']), str(step['name']))}：{step['instruction']}（{step['end_condition']}）"
                for step in course["steps"]
            )
            lines.extend(
                [
                    "开始前检查：" + "；".join(course["start_gate"]),
                    "执行提示：" + "；".join(course["technique_notes"]),
                    "降级方案：" + str(course["downgrade_rule"]),
                    "停止条件：" + "；".join(course["stop_conditions"]),
                ]
            )
        lines.extend(("", "昨日训练数据"))
        if view["activity_kpis"]:
            for item in view["activity_kpis"]:
                lines.append(
                    f"- {item['label']}：{_format_number(item.get('distance_km'))} km · {_format_duration(item['duration_seconds'])}"
                )
        else:
            lines.append("- 昨日没有已验证活动")
    else:
        lines.extend(
            [
                f"健康总结：{view['health_summary']}",
                f"运动与负荷总结：{view['activity_summary']}",
            ]
        )
        if view["status"] != "blocked":
            lines.extend(("", "观察 → 意义 → 行动"))
            lines.extend(
                f"- {item['observation']} → {item['meaning']} → {item['action']}"
                for item in view["insights"]
            )
            lines.extend(("", "七日详细计划"))
            for course in view["training_plan"]["items"]:
                lines.append(
                    f"- {course['date']} {course['name']}：{course['purpose']}"
                )
                lines.extend(
                    f"  - {_PHASE_LABELS.get(str(step['phase']), str(step['name']))}：{step['instruction']}"
                    for step in course["steps"]
                )
                lines.append("  - 开始前检查：" + "；".join(course["start_gate"]))
                lines.append("  - 执行提示：" + "；".join(course["technique_notes"]))
                lines.append("  - 降级方案：" + str(course["downgrade_rule"]))
                lines.append("  - 停止条件：" + "；".join(course["stop_conditions"]))
    if view.get("data_limits"):
        lines.extend(("", "数据限制", *[f"- {item}" for item in view["data_limits"]]))
    chart_assets = [asset for asset in assets if asset.role in _ROLE_CONTRACTS]
    if chart_assets:
        lines.extend(
            ("", "图表文字说明", *[f"- {asset.alt}" for asset in chart_assets])
        )
    lines.extend(("", "仅用于个人训练复盘，不替代医疗诊断。"))
    return "\n".join(lines).strip() + "\n"


def _validate_visible_contract(view: dict[str, Any]) -> None:
    if view["kind"] == "daily":
        require_narrative_visible_text(
            {
                "yesterday": view["yesterday_summary"],
                "health": view["review_health_summary"],
                "recovery": view["recovery_summary"],
                "reasons": view["decision_reasons"],
                "uncertainty": view["uncertainty"],
            }
        )
        if view["status"] != "blocked":
            require_course_visible_text(view["planned_course"])
            require_course_visible_text(view["effective_course"])
    else:
        require_narrative_visible_text(
            {
                "health": view["health_summary"],
                "activity": view["activity_summary"],
                "insights": view["insights"],
                "uncertainty": view["uncertainty"],
            }
        )
        if view["status"] != "blocked":
            for course in view["training_plan"]["items"]:
                require_course_visible_text(course)


def render_email_v3(view: dict[str, Any]) -> RenderedEmail:
    kind = str(view.get("kind"))
    if kind not in {"daily", "weekly"}:
        raise ValueError("email_view_kind_invalid")
    require_valid_payload(view, f"{kind}_email_view_v3")
    if _PRIVATE_PATTERN.search(canonical_json(view)):
        raise ValueError("email_private_content_forbidden")
    _validate_visible_contract(view)
    assets = (
        _icon_asset("email_brand_mark"),
        *((_icon_asset(f"email_status_{view['safety']}"),) if kind == "daily" else ()),
        *tuple(_chart_asset(chart) for chart in view["charts"]),
    )
    html = _daily_html(view, assets) if kind == "daily" else _weekly_html(view, assets)
    text = _plain_text(view, assets)
    visible = (
        re.sub(r"cid:[A-Za-z0-9._-]+@trainlab\.invalid", "cid:[inline-image]", html)
        + "\n"
        + text
    )
    if _PRIVATE_PATTERN.search(visible) or _ENGINEERING_PATTERN.search(visible):
        raise ValueError("email_visible_content_forbidden")
    if len(html.encode()) > MAX_HTML_BYTES:
        raise ValueError("email_html_too_large")
    headings = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    if headings != [escape(str(view["title"]))]:
        raise ValueError("email_subject_heading_mismatch")
    manifest = {
        "schema_version": "email_inline_asset_manifest_v1",
        "assets": [asset.manifest() for asset in assets],
    }
    require_valid_payload(manifest, "email_inline_asset_manifest_v1")
    payload = {
        "schema_version": f"{kind}_email_render_v3",
        "kind": kind,
        "subject": view["title"],
        "text": text,
        "html": html,
        "view_sha256": hashlib.sha256(canonical_json(view).encode()).hexdigest(),
        "asset_manifest": manifest,
        "provider_calls": 0,
    }
    require_valid_payload(payload, f"{kind}_email_render_v3")
    return RenderedEmail(payload=payload, assets=assets)
