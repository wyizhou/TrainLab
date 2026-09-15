#!/usr/bin/env python3
"""Render deterministic TrainLab email v2 HTML, text, and CID PNG assets."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from html import escape
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from email_view import build_daily_view, build_weekly_view  # noqa: E402

MAX_HTML_BYTES = 80 * 1024
CHART_WIDTH = 1248
CHART_HEIGHT = 520
_PRIVATE_PATTERN = re.compile(
    r"(?:\blatitude\b|\blongitude\b|\bgps\b|\bcoordinates?\b|\broute\b|"
    r"路线|经纬度|\btoken\b|\bcredentials?\b|\bpassword\b|\bpasswd\b|"
    r"\bapi[_-]?key\b|\bclient[_-]?secret\b|\bbearer\b|\boauth\b|"
    r"source/state|/private/|/Users/|file://|https?://|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)
_VISIBLE_ENGINEERING_PATTERN = re.compile(
    r"(?:raw_file_id|sha256|bounded_metrics|evidence_ref|review_date|report_date|error_code|"
    r"\b[0-9a-f]{64}\b|\b\d{4,}\s*(?:秒|seconds?)\b)",
    re.IGNORECASE,
)


class EmailRenderError(ValueError):
    """Stable readable-email rendering failure."""


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


def _clean_text(value: object) -> str:
    return str(value) if value is not None else ""


def _chart_asset(chart: dict[str, Any]) -> InlineAsset:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency gate covers this
        raise EmailRenderError("email_chart_renderer_unavailable") from exc
    points = chart.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise EmailRenderError("email_chart_points_invalid")
    values = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise EmailRenderError("email_chart_points_invalid")
        y_value = point.get("y")
        if isinstance(y_value, bool) or not isinstance(y_value, (int, float)):
            raise EmailRenderError("email_chart_points_invalid")
        number = float(y_value)
        if not math.isfinite(number):
            raise EmailRenderError("email_chart_points_invalid")
        values.append((index, number))
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 88, 52, CHART_WIDTH - 48, CHART_HEIGHT - 68
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        y_value = round(top + (bottom - top) * fraction)
        draw.line((left, y_value, right, y_value), fill="#D7E4E6", width=2)
    minimum, maximum = (
        min(value for _index, value in values),
        max(value for _index, value in values),
    )
    padding = max(1.0, (maximum - minimum) * 0.1)
    low, high = minimum - padding, maximum + padding
    denominator = max(high - low, 1.0)
    coordinates = []
    for index, value in values:
        x_value = left + (right - left) * index / max(len(values) - 1, 1)
        y_value = bottom - (bottom - top) * (value - low) / denominator
        coordinates.append((round(x_value), round(y_value)))
    color = {
        "daily_activity_heart_rate": "#087B8C",
        "weekly_sleep": "#48548E",
        "weekly_rhr": "#B85B18",
        "weekly_hrv": "#26744B",
        "weekly_activity_duration": "#087B8C",
    }.get(str(chart.get("role")), "#087A78")
    draw.line(coordinates, fill=color, width=8, joint="curve")
    for x_value, y_value in coordinates:
        draw.ellipse(
            (x_value - 8, y_value - 8, x_value + 8, y_value + 8),
            fill="#FFFFFF",
            outline=color,
            width=5,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    data = buffer.getvalue()
    role = str(chart["role"])
    chart_sha = hashlib.sha256(canonical_json(chart).encode("utf-8")).hexdigest()
    cid = f"trainlab-{role}-{chart_sha[:24]}@trainlab.invalid"
    alt = _chart_text_summary(chart)
    return InlineAsset(
        role=role,
        cid=cid,
        filename=f"{role.replace('_', '-')}-{chart_sha[:12]}.png",
        media_type="image/png",
        width_px=CHART_WIDTH,
        height_px=CHART_HEIGHT,
        sha256=hashlib.sha256(data).hexdigest(),
        alt=alt,
        data=data,
    )


def _status_copy(status: str) -> tuple[str, str, str]:
    return {
        "ready": ("可以训练", "#E7F5ED", "#1B6F47"),
        "caution": ("需要谨慎", "#FFF2CF", "#8A5700"),
        "blocked": ("报告已阻断", "#FDE9E6", "#A7372F"),
    }.get(status, ("状态未知", "#EDF1F2", "#40535A"))


def _blocked_reason(error_code: object) -> str:
    return {
        "daily_sleep_evidence_missing": "主睡眠证据缺失",
        "daily_review_health_missing": "昨日健康证据缺失",
        "weekly_daily_inputs_missing": "七份日报证据不完整",
    }.get(str(error_code), "关键证据不完整")


def _weekly_decision_copy(view: dict[str, Any]) -> tuple[str, str, str]:
    if view.get("status") == "blocked":
        return "报告已阻断", "#FDE9E6", "#A7372F"
    decision = str(view.get("decision"))
    if decision == "advance":
        dimension = {
            "distance": "增加距离",
            "intensity": "增加强度",
            "none": "单项进阶",
        }.get(str(view.get("progression_dimension")), "单项进阶")
        return f"进阶 · {dimension}", "#E7F5ED", "#1B6F47"
    if decision == "deload":
        return "减量", "#FFF2CF", "#8A5700"
    return "维持", "#EDF1F2", "#40535A"


def _metric_table(metrics: dict[str, Any]) -> str:
    cells = []
    for key in ("sleep", "rhr", "hrv", "vo2_max", "weight"):
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        cells.append(
            '<td class="metric-cell" width="50%" valign="top">'
            f'<div class="eyebrow">{escape(_clean_text(item.get("label")))}</div>'
            f'<div class="metric-value">{escape(_clean_text(item.get("value")))}</div>'
            f'<div class="muted">{escape(_clean_text(item.get("detail")))}</div>'
            "</td>"
        )
    rows = []
    for index in range(0, len(cells), 2):
        right = cells[index + 1] if index + 1 < len(cells) else '<td width="50%"></td>'
        rows.append(f"<tr>{cells[index]}{right}</tr>")
    return (
        '<table role="presentation" width="100%" class="metric-grid">'
        + "".join(rows)
        + "</table>"
    )


def _activity_html(activities: list[dict[str, Any]]) -> str:
    if not activities:
        return '<div class="empty">昨日没有已验证活动。</div>'
    blocks = []
    for item in activities:
        values = [item.get("distance"), item.get("duration"), item.get("pace")]
        summary = " · ".join(escape(str(value)) for value in values if value)
        blocks.append(
            '<div class="activity-card">'
            f"<strong>{escape(_clean_text(item.get('label')))}</strong>"
            f'<div class="muted">{summary}</div></div>'
        )
    return "".join(blocks)


def _course_html(course: dict[str, Any] | None, notice: str) -> str:
    if course is None:
        return f'<div class="empty">{escape(notice)}</div>'
    details = []
    if course.get("duration_minutes") is not None:
        details.append(f"{course['duration_minutes']} 分钟")
    if course.get("distance_km") is not None:
        details.append(f"{course['distance_km']} km")
    if course.get("rpe") is not None:
        details.append(f"RPE {course['rpe']}/10")
    stop = "".join(
        f"<li>{escape(str(value))}</li>" for value in course.get("stop_conditions", [])
    )
    return (
        '<div class="course-card">'
        f'<div class="tag">{escape(_clean_text(course.get("activity_kind")))}</div>'
        f"<h3>{escape(_clean_text(course.get('name')))}</h3>"
        f"<p>{escape(_clean_text(course.get('purpose')))}</p>"
        f'<p class="muted">{" · ".join(escape(value) for value in details)}</p>'
        f"<p><strong>降级：</strong>{escape(_clean_text(course.get('downgrade_rule')))}</p>"
        f"<ul>{stop}</ul></div>"
    )


def _charts_html(charts: list[dict[str, Any]], assets: tuple[InlineAsset, ...]) -> str:
    by_role = {asset.role: asset for asset in assets}
    blocks = []
    for chart in charts:
        role = str(chart.get("role"))
        asset = by_role.get(role)
        if asset is None:
            continue
        blocks.append(
            '<div class="chart-card">'
            f"<h3>{escape(_clean_text(chart.get('title')))}</h3>"
            f'<img src="cid:{escape(asset.cid)}" width="624" alt="{escape(asset.alt)}" '
            'style="display:block;width:100%;max-width:624px;height:auto;border:0">'
            f'<div class="chart-fallback">{escape(_chart_text_summary(chart))}</div>'
            "</div>"
        )
    return "".join(blocks)


def _chart_text_summary(chart: dict[str, Any]) -> str:
    values = [
        float(point["y"])
        for point in chart.get("points", [])
        if isinstance(point, dict)
        and isinstance(point.get("y"), (int, float))
        and not isinstance(point.get("y"), bool)
    ]
    if not values:
        raise EmailRenderError("email_chart_points_invalid")
    raw_unit = _clean_text(chart.get("unit"))
    unit = {
        "hours": "小时",
        "minutes": "分钟",
        "km": "公里",
    }.get(raw_unit, raw_unit)
    formatted = [f"{round(value, 1):g}" for value in values]
    return (
        f"{chart.get('title', '数据图表')}，共 {len(values)} 个实测点；"
        f"最低 {min(float(value) for value in formatted):g}、"
        f"最高 {max(float(value) for value in formatted):g}、"
        f"起始 {formatted[0]}、结束 {formatted[-1]} {unit}"
    )


def _evidence_html(evidence: dict[str, Any]) -> str:
    claims = []
    for item in evidence.get("refs", []):
        if not isinstance(item, dict):
            continue
        claim = _clean_text(item.get("claim"))
        if claim and claim not in claims:
            claims.append(claim)
    rows = "".join(f"<li>{escape(claim)}</li>" for claim in claims)
    return (
        f"<p>已核验 {int(evidence.get('count', 0))} 个来源，完整 ID 与哈希保存在私有验证记录中。</p>"
        f"<ul>{rows}</ul>"
    )


def _weekly_plan(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">下周计划未生成。</div>'
    blocks = []
    for item in items:
        dose = []
        if item.get("distance_km") is not None:
            dose.append(f"{item['distance_km']} km")
        if item.get("duration_minutes") is not None:
            dose.append(f"{item['duration_minutes']} 分钟")
        dose.append(f"RPE {item.get('rpe')}/10")
        blocks.append(
            '<tr><td class="plan-date" valign="top">'
            f"{escape(_clean_text(item.get('date')))}</td>"
            '<td class="plan-body" valign="top">'
            f"<strong>{escape(_clean_text(item.get('name')))}</strong>"
            f"<div>{escape(_clean_text(item.get('purpose')))}</div>"
            f'<div class="muted">{" · ".join(escape(value) for value in dose)}</div>'
            f'<div class="muted">降级：{escape(_clean_text(item.get("downgrade_rule")))}</div>'
            "</td></tr>"
        )
    return (
        '<table role="presentation" width="100%" class="plan-table">'
        + "".join(blocks)
        + "</table>"
    )


def _styles() -> str:
    return """
<style>
body{margin:0!important;padding:0!important;background:#F4F8F8;color:#17323B;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
table{border-collapse:collapse}.shell{width:100%;max-width:672px;background:#fff}.pad{padding:24px}.header{background:#087A78;color:#fff;padding:28px 24px}.header h1{margin:6px 0 0;font-size:28px;line-height:1.22}.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}.section{margin:0 0 18px;padding:20px;border:1px solid #D7E4E6;border-radius:16px}.section h2{margin:0 0 12px;font-size:20px}.section h3{margin:0 0 8px;font-size:17px}.hero{padding:20px;border-radius:16px}.hero strong{font-size:22px}.metric-cell{padding:14px;border:1px solid #D7E4E6}.metric-value{font-size:23px;font-weight:650;margin:4px 0}.muted{color:#556970;font-size:13px}.empty{padding:16px;background:#EDF1F2;color:#40535A;border-radius:12px}.activity-card,.course-card,.chart-card{padding:16px;border:1px solid #D7E4E6;border-radius:12px;margin-top:10px}.tag{display:inline-block;padding:3px 9px;border-radius:999px;background:#E4F2F2;color:#087A78;font-size:12px}.plan-date{width:112px;padding:14px 10px;border-bottom:1px solid #D7E4E6;font-weight:600}.plan-body{padding:14px 10px;border-bottom:1px solid #D7E4E6}.chart-fallback{font-size:12px;color:#556970;margin-top:8px}.mono{font-family:SFMono-Regular,Consolas,Menlo,monospace;word-break:break-all}.evidence{font-size:11px;color:#556970}.privacy{padding:0 24px 24px;color:#556970;font-size:11px}
@media only screen and (max-width:375px){.pad{padding:16px!important}.header{padding:22px 16px!important}.header h1{font-size:24px!important}.section{padding:16px!important}.metric-grid,.metric-grid tbody,.metric-grid tr{display:block!important;width:100%!important}.metric-cell{display:block!important;width:100%!important;box-sizing:border-box!important}.plan-date,.plan-body{display:block!important;width:100%!important;box-sizing:border-box!important}.plan-date{padding-bottom:4px!important;border-bottom:0!important}}
@media (prefers-color-scheme:dark){body{background:#12252B!important}.shell{background:#17323B!important;color:#F4F8F8!important}.section,.activity-card,.course-card,.chart-card{background:#203E46!important;border-color:#456069!important}.muted,.evidence,.privacy,.chart-fallback{color:#D7E4E6!important}}
</style>"""


def _daily_html(view: dict[str, Any], assets: tuple[InlineAsset, ...]) -> str:
    label, background, foreground = _status_copy(str(view["status"]))
    stop = "".join(
        f"<li>{escape(str(value))}</li>" for value in view.get("stop_conditions", [])
    )
    reason = (
        f"<div><strong>阻断原因：</strong>{escape(_blocked_reason(view.get('error_code')))}</div>"
        if view.get("error_code")
        else ""
    )
    title = escape(str(view["title"]))
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{_styles()}</head><body><table role="presentation" width="100%"><tr><td align="center"><table role="presentation" class="shell" width="672"><tr><td class="header"><div class="eyebrow">TRAINLAB DAILY</div><h1>{title}</h1></td></tr><tr><td class="pad"><div class="hero" style="background:{background};color:{foreground}"><strong>{escape(label)}</strong>{reason}<p>{escape(str(view["summary"]))}</p></div><div class="section"><h2>恢复概览</h2>{_metric_table(view["metrics"])}</div><div class="section"><h2>今日课程</h2>{_course_html(view.get("today_course"), str(view.get("course_notice") or ""))}</div><div class="section"><h2>昨日活动</h2>{_activity_html(view["activities"])}</div>{_charts_html(view["charts"], assets)}<div class="section"><h2>停止条件</h2><ul>{stop}</ul></div><div class="section evidence"><h2>证据与来源</h2>{_evidence_html(view["evidence"])}</div></td></tr><tr><td class="privacy">仅用于个人训练复盘，不替代医疗诊断。缺失数据不会被猜测或补造。</td></tr></table></td></tr></table></body></html>"""


def _weekly_html(view: dict[str, Any], assets: tuple[InlineAsset, ...]) -> str:
    decision_label, background, foreground = _weekly_decision_copy(view)
    reason = (
        f"<div><strong>阻断原因：</strong>{escape(_blocked_reason(view.get('error_code')))}</div>"
        if view.get("error_code")
        else ""
    )
    stats = view["stats"]
    title = escape(str(view["title"]))
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{_styles()}</head><body><table role="presentation" width="100%"><tr><td align="center"><table role="presentation" class="shell" width="672"><tr><td class="header"><div class="eyebrow">TRAINLAB WEEKLY</div><h1>{title}</h1></td></tr><tr><td class="pad"><div class="hero" style="background:{background};color:{foreground}"><strong>{escape(decision_label)}</strong>{reason}<p>{escape(str(view["summary"]))}</p></div><div class="section"><h2>本周概览</h2><table role="presentation" width="100%"><tr><td class="metric-cell">日报<br><span class="metric-value">{stats["daily_count"]}</span></td><td class="metric-cell">谨慎日<br><span class="metric-value">{stats["caution_days"]}</span></td><td class="metric-cell">跑量<br><span class="metric-value">{stats["running_distance_km"]} km</span></td></tr></table></div>{_charts_html(view["charts"], assets)}<div class="section"><h2>下周计划</h2>{_weekly_plan(view["plan_items"])}</div><div class="section evidence"><h2>证据与来源</h2>{_evidence_html(view["evidence"])}</div></td></tr><tr><td class="privacy">计划会随恢复状态调整；疼痛、胸闷、眩晕或异常气短时停止训练。</td></tr></table></td></tr></table></body></html>"""


def _plain_text(view: dict[str, Any]) -> str:
    lines = [str(view["title"]), "", str(view["summary"]), ""]
    if view["kind"] == "daily":
        lines.append("恢复概览")
        for key in ("sleep", "rhr", "hrv", "vo2_max", "weight"):
            item = view["metrics"][key]
            detail = (
                str(item.get("detail") or "") if key in {"vo2_max", "weight"} else ""
            )
            suffix = f"｜{detail}" if detail else ""
            lines.append(f"- {item['label']}：{item['value']}{suffix}")
        lines.extend(("", "今日课程"))
        course = view.get("today_course")
        lines.append(
            f"- {course['name']}：{course['purpose']}"
            if isinstance(course, dict)
            else f"- {view['course_notice']}"
        )
        lines.extend(("", "昨日活动"))
        if view["activities"]:
            for item in view["activities"]:
                values = [item.get("distance"), item.get("duration"), item.get("pace")]
                lines.append(
                    f"- {item['label']}："
                    + " · ".join(str(value) for value in values if value)
                )
        else:
            lines.append("- 昨日没有已验证活动")
    else:
        lines.extend(("下周计划",))
        for item in view["plan_items"]:
            lines.append(f"- {item['date']} {item['name']}：{item['purpose']}")
    lines.extend(("", "仅用于个人训练复盘，不替代医疗诊断。"))
    return "\n".join(lines).strip() + "\n"


def render_email(view: dict[str, Any]) -> RenderedEmail:
    """Render a validated view to deterministic content and inline assets."""

    kind = view.get("kind")
    if kind not in {"daily", "weekly"}:
        raise EmailRenderError("email_view_kind_invalid")
    require_valid_payload(view, f"{kind}_email_view_v1")
    if _PRIVATE_PATTERN.search(canonical_json(view)):
        raise EmailRenderError("email_private_content_forbidden")
    assets = tuple(_chart_asset(chart) for chart in view.get("charts", []))
    html = _daily_html(view, assets) if kind == "daily" else _weekly_html(view, assets)
    text = _plain_text(view)
    visible = "\n".join((html, text, *(asset.alt for asset in assets)))
    if _VISIBLE_ENGINEERING_PATTERN.search(visible):
        raise EmailRenderError("email_engineering_content_forbidden")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise EmailRenderError("email_html_too_large")
    subject = str(view["title"])
    headings = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    if headings != [escape(subject)]:
        raise EmailRenderError("email_subject_heading_mismatch")
    manifest = {
        "schema_version": "email_inline_asset_manifest_v1",
        "assets": [asset.manifest() for asset in assets],
    }
    require_valid_payload(manifest, "email_inline_asset_manifest_v1")
    view_sha = hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()
    payload = {
        "schema_version": f"{kind}_email_render_v2",
        "kind": kind,
        "subject": subject,
        "text": text,
        "html": html,
        "view_sha256": view_sha,
        "asset_manifest": manifest,
        "provider_calls": 0,
    }
    require_valid_payload(payload, f"{kind}_email_render_v2")
    return RenderedEmail(payload=payload, assets=assets)


def _atomic_owner_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise EmailRenderError("email_preview_artifact_empty")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            current = path.read_bytes()
            if current != payload:
                raise EmailRenderError("email_preview_replay_mismatch")
            temporary.unlink()
            return
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _ensure_private_parent(path: Path) -> None:
    parent = Path(os.path.abspath(path.parent))
    if not parent.exists():
        parent.mkdir(mode=0o700)
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not parent.is_dir()
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise EmailRenderError("email_preview_parent_invalid")


def _source_payload(
    database: Path, source_output_id: int
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.output_kind,so.schema_name,so.content_json,so.content_sha256,"
            "sr.input_manifest_json,sr.status FROM skill_outputs so "
            "JOIN skill_runs sr ON sr.id=so.skill_run_id WHERE so.id=?",
            (source_output_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[5]) != "succeeded":
        raise EmailRenderError("email_preview_source_missing")
    pair = (str(row[0]), str(row[1]))
    if pair == ("daily_summary", "daily_ai_result_v1"):
        kind = "daily"
    elif pair == ("weekly_summary", "weekly_ai_result_v1"):
        kind = "weekly"
    else:
        raise EmailRenderError("email_preview_source_invalid")
    try:
        payload = json.loads(str(row[2]))
        manifest = json.loads(str(row[4]))
    except json.JSONDecodeError as exc:
        raise EmailRenderError("email_preview_source_invalid") from exc
    context = manifest.get("context") if isinstance(manifest, dict) else None
    if not isinstance(payload, dict) or not isinstance(context, dict):
        raise EmailRenderError("email_preview_context_missing")
    return kind, payload, context, str(row[3])


def _unique_plan_for_date(database: Path, report_date: str) -> dict[str, Any] | None:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT so.content_json FROM skill_outputs so JOIN skill_runs sr "
            "ON sr.id=so.skill_run_id WHERE so.output_kind='weekly_summary' "
            "AND so.schema_name='weekly_ai_result_v1' AND sr.status='succeeded'"
        ).fetchall()
    finally:
        connection.close()
    candidates = []
    for row in rows:
        try:
            value = json.loads(str(row[0]))
        except json.JSONDecodeError:
            continue
        plan = value.get("training_plan") if isinstance(value, dict) else None
        if not isinstance(plan, dict):
            continue
        try:
            require_valid_payload(plan, "training_plan_v1")
        except ValueError:
            continue
        if (
            sum(
                1
                for item in plan.get("items", [])
                if isinstance(item, dict) and item.get("date") == report_date
            )
            == 1
        ):
            candidates.append(plan)
    unique = {canonical_json(item): item for item in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _recent_health_payload(
    database: Path, output_id: int, report_date: str
) -> tuple[dict[str, Any], str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.period_start_date,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=? AND so.output_kind='bounded_evidence' "
            "AND so.schema_name='recent_health_metrics_v1'",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[2]) != report_date or str(row[3]) != "succeeded":
        raise EmailRenderError("email_recent_health_snapshot_invalid")
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise EmailRenderError("email_recent_health_snapshot_invalid") from exc
    try:
        require_valid_payload(payload, "recent_health_metrics_v1")
    except ValueError as exc:
        raise EmailRenderError("email_recent_health_snapshot_invalid") from exc
    if payload.get("report_date") != report_date:
        raise EmailRenderError("email_recent_health_snapshot_invalid")
    return payload, str(row[1])


def build_from_database(
    database: Path,
    source_output_id: int,
    *,
    recent_health_output_id: int | None = None,
) -> tuple[dict[str, Any], RenderedEmail, str]:
    kind, payload, context, source_sha = _source_payload(database, source_output_id)
    if recent_health_output_id is not None:
        if kind != "daily":
            raise EmailRenderError("email_recent_health_snapshot_daily_only")
        snapshot, _snapshot_sha = _recent_health_payload(
            database, recent_health_output_id, str(payload["report_date"])
        )
        context = copy.deepcopy(context)
        context["recent_health_metrics"] = snapshot
    view = (
        build_daily_view(
            payload,
            context,
            _unique_plan_for_date(database, str(payload["report_date"])),
        )
        if kind == "daily"
        else build_weekly_view(payload, context)
    )
    return view, render_email(view), source_sha


def _persist(
    database: Path,
    *,
    source_output_id: int,
    source_sha: str,
    view: dict[str, Any],
    rendered: RenderedEmail,
    recent_health_output_id: int | None = None,
) -> dict[str, int]:
    kind = str(view["kind"])
    period = str(view["period"])
    input_manifest = {
        "schema_version": "m11_email_preview_input_v1",
        "source_output_id": source_output_id,
        "source_output_sha256": source_sha,
        "view_sha256": rendered.payload["view_sha256"],
        "asset_manifest": rendered.payload["asset_manifest"],
    }
    snapshot_sha: str | None = None
    if recent_health_output_id is not None:
        _snapshot, snapshot_sha = _recent_health_payload(
            database, recent_health_output_id, period.split("/", 1)[0]
        )
        input_manifest["recent_health_output_id"] = recent_health_output_id
        input_manifest["recent_health_output_sha256"] = snapshot_sha
    digest = sha256_text(canonical_json(input_manifest))
    run_key = (
        f"training-report-publisher:m11:{kind}:{source_output_id}:{digest}:attempt-1"
    )
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=run_key,
            workflow_key=f"m11:preview:{kind}:{period}",
            dedupe_key=digest,
            skill_name="training-report-publisher",
            operation="render_daily" if kind == "daily" else "render_weekly",
            trigger_kind="manual",
            input_manifest=input_manifest,
            input_sha256=digest,
            target_from_date=period.split("/", 1)[0],
            target_through_date=period.split("/", 1)[-1],
        )
        existing = connection.execute(
            "SELECT id,output_kind FROM skill_outputs WHERE skill_run_id=? "
            "AND logical_key LIKE ? ORDER BY id",
            (run_id, f"training-report-publisher:m11:{kind}:{source_output_id}:%"),
        ).fetchall()
        if len(existing) == 2:
            return {str(row[1]): int(row[0]) for row in existing}
        if existing:
            raise EmailRenderError("email_preview_partial_commit")
        lineage = [
            {"output_id": source_output_id, "output_sha256": source_sha},
            {"input_sha256": digest},
        ]
        if recent_health_output_id is not None and snapshot_sha is not None:
            lineage.insert(
                1,
                {
                    "output_id": recent_health_output_id,
                    "output_sha256": snapshot_sha,
                },
            )
        report_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="report_artifact",
            logical_key=f"training-report-publisher:m11:{kind}:{source_output_id}:report",
            schema_name=f"{kind}_email_view_v1",
            schema_version="1",
            title_text=str(view["title"]),
            content_json=view,
            content_text=str(rendered.payload["text"]),
            content_html=str(rendered.payload["html"]),
            lineage=lineage,
            period_start_date=period.split("/", 1)[0],
            period_end_date=period.split("/", 1)[-1],
        )
        report_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (report_id,)
            ).fetchone()[0]
        )
        email_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="email_render",
            logical_key=f"training-report-publisher:m11:{kind}:{source_output_id}:email",
            schema_name=f"{kind}_email_render_v2",
            schema_version="2",
            title_text=str(rendered.payload["subject"]),
            content_json=rendered.payload,
            content_text=str(rendered.payload["text"]),
            content_html=str(rendered.payload["html"]),
            lineage=[
                *lineage,
                {"output_id": report_id, "output_sha256": report_sha},
            ],
            period_start_date=period.split("/", 1)[0],
            period_end_date=period.split("/", 1)[-1],
        )
        finish_run(connection, run_id, status="succeeded")
        return {"report_artifact": report_id, "email_render": email_id}
    except Exception:
        if "run_id" in locals():
            try:
                finish_run(
                    connection,
                    run_id,
                    status="failed",
                    error_code="email_preview_commit_failed",
                )
            except ValueError:
                pass
        raise
    finally:
        connection.close()


def write_preview(
    database: Path,
    source_output_id: int,
    output_dir: Path,
    *,
    recent_health_output_id: int | None = None,
) -> dict[str, Any]:
    _ensure_private_parent(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    view, rendered, source_sha = build_from_database(
        database,
        source_output_id,
        recent_health_output_id=recent_health_output_id,
    )
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(assets_dir, 0o700)
    files = {
        "view.json": (canonical_json(view) + "\n").encode("utf-8"),
        "render.json": (canonical_json(rendered.payload) + "\n").encode("utf-8"),
        "report.html": str(rendered.payload["html"]).encode("utf-8"),
        "report.txt": str(rendered.payload["text"]).encode("utf-8"),
    }
    browser_html = str(rendered.payload["html"])
    for asset in rendered.assets:
        browser_html = browser_html.replace(
            f"cid:{asset.cid}", f"assets/{asset.filename}"
        )
    files["browser-preview.html"] = browser_html.encode("utf-8")
    for name, payload in files.items():
        _atomic_owner_write(output_dir / name, payload)
    for asset in rendered.assets:
        _atomic_owner_write(assets_dir / asset.filename, asset.data)
    output_ids = _persist(
        database,
        source_output_id=source_output_id,
        source_sha=source_sha,
        view=view,
        rendered=rendered,
        recent_health_output_id=recent_health_output_id,
    )
    artifact_paths = [
        *(output_dir / name for name in files),
        *(assets_dir / asset.filename for asset in rendered.assets),
    ]
    artifacts = [
        {
            "path": path.relative_to(output_dir).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "byte_size": path.stat().st_size,
            "mode": "0600",
        }
        for path in sorted(artifact_paths)
    ]
    receipt = {
        "schema_version": "m11_email_preview_receipt_v1",
        "status": "succeeded",
        "source_output_id": source_output_id,
        "source_output_sha256": source_sha,
        "kind": view["kind"],
        "view_sha256": rendered.payload["view_sha256"],
        "asset_manifest": rendered.payload["asset_manifest"],
        "output_ids": output_ids,
        "files": sorted(
            [*files, *(f"assets/{asset.filename}" for asset in rendered.assets)]
        ),
        "artifacts": artifacts,
        "provider_calls": 0,
        "external_actions": 0,
    }
    _atomic_owner_write(
        output_dir / "preview-receipt.json",
        (canonical_json(receipt) + "\n").encode("utf-8"),
    )
    verify_preview(output_dir)
    return receipt


def verify_preview(output_dir: Path) -> dict[str, Any]:
    metadata = output_dir.lstat()
    if (
        output_dir.is_symlink()
        or not output_dir.is_dir()
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise EmailRenderError("email_preview_root_invalid")
    receipt_path = output_dir / "preview-receipt.json"
    receipt_info = receipt_path.lstat()
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or receipt_info.st_uid != os.getuid()
        or receipt_info.st_nlink != 1
        or stat.S_IMODE(receipt_info.st_mode) != 0o600
        or receipt_info.st_size <= 0
    ):
        raise EmailRenderError("email_preview_receipt_invalid")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected = {
        str(item["path"]): item
        for item in receipt.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    actual = {
        path.relative_to(output_dir).as_posix(): path
        for path in output_dir.rglob("*")
        if path.is_file() and path != receipt_path
    }
    if set(actual) != set(expected):
        raise EmailRenderError("email_preview_manifest_mismatch")
    allowed_directories = {output_dir, output_dir / "assets"}
    for directory in (path for path in output_dir.rglob("*") if path.is_dir()):
        info = directory.lstat()
        if (
            directory not in allowed_directories
            or directory.is_symlink()
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise EmailRenderError("email_preview_artifact_invalid")
    for name, path in actual.items():
        info = path.lstat()
        item = expected[name]
        if (
            path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size <= 0
            or item.get("mode") != "0600"
            or item.get("byte_size") != info.st_size
            or item.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise EmailRenderError("email_preview_artifact_invalid")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-output-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--recent-health-output-id", type=int)
    args = parser.parse_args()
    receipt = write_preview(
        args.database,
        args.source_output_id,
        args.output_dir,
        recent_health_output_id=args.recent_health_output_id,
    )
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
