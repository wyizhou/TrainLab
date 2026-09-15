"""One ordered content tree consumed by both Markdown and PDF (no HTML report)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LABELS = {
    "running": "跑步",
    "rock_climbing": "攀岩",
    "cycling": "骑行",
    "swimming": "游泳",
    "walking": "步行",
    "strength_training": "力量训练",
    "complete": "完整",
    "partial": "部分已知",
    "unknown": "未知",
    "supported": "有来源支持",
    "missing": "缺失",
    "available": "可用",
    "insufficient_data": "资料不足",
    "unchanged": "不变",
    "increased": "增加",
    "decreased": "减少",
    "no_observed_increase": "未观察到增加",
    "easy": "轻松",
    "hard": "较高用力",
    "moderate": "适中",
    "long": "长距离",
    "tempo": "节奏",
    "intervals": "间歇",
    "warmup": "热身",
    "cooldown": "放松",
    "run": "跑步",
    "recovery": "恢复",
}
LABELS.update(
    {
        "source_observation": "来源记录观察",
        "timer_boundaries_unavailable": "无法获得计时启停边界",
        "laps_conflicting": "圈段记录存在冲突",
        "session_lap_end_start_plus_elapsed": "运动段与圈段的结束时间按开始时间加经过时长计算，不使用汇总消息时间或设备计时时长代替。",
        "lap_time_precision_compatible": "圈段存在严格小于一秒的端点精度差异；保留原范围并按所属运动段裁剪，不能据此证明圈段构成完整分区。",
        "timer_total_precision_difference": "设备计时时长与计时启停事件计算的有效时长存在不足一秒的精度差异；分别保留来源值。",
        "distance_reset_or_missing": "距离重置或缺失",
        "sample_gaps": "采样存在缺口",
        "inventory_is_as_of_snapshot": "运动清单截至冻结快照时点。",
        "registered_fit_end_time_membership": "已有 FIT 按活动结束时间归属周期。",
        "no_fit_end_time_unknown": "无 FIT 的记录缺少可信结束时间，周期归属未知。",
        "late_data_does_not_rewrite_frozen_week": "迟到资料不会改写已冻结的本周输入。",
        "provider_no_fit_end_unknown": "服务端无 FIT，结束时间和周期归属未知",
        "distance_m": "距离（米）",
        "timer_seconds": "设备计时时长（秒）",
        "hard_count": "硬负荷课数",
        "peak_rpe": "最高主观 RPE",
        "hard_seconds": "硬课时长（秒）",
        "hard_meters": "硬课距离（米）",
        "summary": "摘要",
        "provider_summary": "设备摘要",
        "cadence_spm": "步频（步/分）",
        "cadence_rpm": "设备节律（转/分）",
        "avg_cadence_rpm": "设备平均节律（转/分）",
        "power_w": "功率（瓦）",
        "avg_power_w": "平均功率（瓦）",
        "altitude_m": "海拔（米）",
        "temperature_c": "温度（摄氏度）",
        "speed_m_s": "速度（米/秒）",
        "step_length_mm": "步长（毫米）",
        "vertical_oscillation_mm": "垂直振幅（毫米）",
        "stance_time_ms": "触地时间（毫秒）",
        "vertical_ratio_percent": "垂直比（%）",
        "metrics": "采样指标",
        "statistics": "统计",
        "blocks": "细读分段",
        "segments": "分段",
        "mean": "平均值",
        "min": "最小值",
        "max": "最大值",
        "heart_rate_bpm": "历史心率（BPM）",
        "speed_mps": "速度（米/秒）",
        "power_watts": "功率（瓦）",
        "valid_seconds": "有效时长（秒）",
        "elapsed_seconds": "经过时长（秒）",
        "sample_covered_seconds": "采样覆盖时长（秒）",
        "gap_seconds": "缺口时长（秒）",
        "avg_heart_rate_bpm": "历史平均心率（BPM）",
        "max_heart_rate_bpm": "历史最高心率（BPM）",
        "current": "本期活动",
        "detail": "已有细读",
        "history": "历史报告",
        "goal": "目标快照",
        "Explicit planned dose, hard-course count and subjective peak RPE are comparison dimensions, not a physiological intensity proof.": "比较使用计划剂量、硬课次数与主观最高 RPE，不能据此证明生理强度。",
        "Missing baseline or incompatible dose units remain unknown; absence of a measured increase does not prove overall intensity unchanged.": "缺少基线或剂量单位不兼容时保持未知；未测得增加不证明整体强度不变。",
        "Exact structures, dates, dose, source references and explicit load comparisons validated; arbitrary prose accuracy, goal interpretation and coaching reasonableness are not proven by deterministic checks.": "已校验明确结构、日期、剂量、来源引用和负荷比较；确定性检查不能证明任意文字、目标解释或训练建议的合理性。",
    }
)


def label(value: str) -> str:
    return LABELS.get(value, value)


def number(value: Any, unit: str = "") -> str:
    if value is None:
        return "缺失 / 未知"
    return (f"{value:g}" if isinstance(value, (int, float)) else str(value)) + unit


def timestamp(value: str) -> str:
    """Display the same instant with an explicit readable UTC designation."""
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%d %H:%M:%S UTC")
    )


def source_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(source_value(v) for v in value)
    if isinstance(value, dict):
        return "；".join((label(k) + "：" + source_value(v)) for k, v in value.items())
    if isinstance(value, bool):
        return "是" if value else "否"
    return label(value) if isinstance(value, str) else number(value)


def source_text(ref: dict[str, Any]) -> str:
    parts = [label(ref["source"])]
    if ref["activity_ref"] is not None:
        parts.append(f"活动 {ref['activity_ref']} / 运动段 {ref['session_ordinal']}")
    if ref["period_end_utc"]:
        parts.append("周期结束 " + timestamp(ref["period_end_utc"]))
    path = " / ".join(
        f"第 {k + 1} 项" if isinstance(k, int) else label(k) for k in ref["path"]
    )
    parts.append("字段 " + path)
    parts.append("记录值 " + source_value(ref["value"]))
    if ref["fit_sha256"]:
        parts.append("FIT 摘要 " + ref["fit_sha256"][:12])
    if ref["request_sha256"]:
        parts.append("细读摘要 " + ref["request_sha256"][:12])
    return "；".join(parts)


def blocks(view: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def paragraph(text: str) -> None:
        result.append({"kind": "paragraph", "text": text})

    def heading(text: str, level: int = 2) -> None:
        result.append({"kind": "heading", "text": text, "level": level})

    def table(headers: list[str], rows: list[list[str]]) -> None:
        result.append({"kind": "table", "headers": headers, "rows": rows})

    def claim(item: dict[str, Any]) -> None:
        paragraph(f"[{label(item['status'])}] {item['text']}")
        paragraph("适用条件：" + item["conditions"])
        paragraph("方法：" + label(item["method"]))
        for ref in item["evidence"]:
            # Preserve exact source identity and reference value without
            # exposing raw FIT or inventing an activity/route attribution.
            paragraph("依据：" + source_text(ref))
        if not item["evidence"]:
            paragraph("依据：无可验证引用，保留不确定性。")
        for value in item["limitations"]:
            paragraph("局限：" + value)

    facts = view["facts"]
    heading("每周运动报告", 1)
    paragraph(
        f"统计周期：{timestamp(facts['period_start_utc'])} 至 {timestamp(facts['period_end_utc'])}（起点包含，终点不包含）"
    )
    paragraph(
        f"固定计划：{facts['plan_dates'][0]} 至 {facts['plan_dates'][-1]}（周一至周日）"
    )
    paragraph("本地修订：" + view["revision_id"])
    heading("一、核心结论")
    for item in view["core_conclusions"]:
        claim(item)
    claim(view["running_analysis"]["overview"])
    heading("二、全运动清单与统计")
    paragraph(
        f"已归属 FIT 活动：{facts['activity_count']}；运动段：{facts['session_count']}；无 FIT、归属待定：{len(facts['unplaced_no_fit'])}"
    )
    paragraph(
        "统计只汇总已知设备运动段字段；零值是已记录的零，缺失不会补零。无 FIT 记录不能用来证明本期无运动。"
    )
    if not facts["statistics"]:
        paragraph("没有可用运动统计；仅凭本表不能证明查询完整或没有活动。")
    else:

        def total(item: dict[str, Any], unit: str) -> str:
            return f"{number(item['value'], unit)}；{label(item['status'])}；已知 {item['available_count']} / 缺失 {item['missing_count']}"

        table(
            ["运动 / 活动数 / 段数", "距离", "有效计时时长"],
            [
                [
                    f"{label(s['sport'])} / {s['activity_count']} / {s['session_count']}",
                    total(s["distance_m"], " 米"),
                    total(s["timer_seconds"], " 秒"),
                ]
                for s in facts["statistics"]
            ],
        )
        known = [
            s for s in facts["statistics"] if s["timer_seconds"]["value"] is not None
        ]
        if known:
            result.append(
                {
                    "kind": "chart",
                    "title": "各运动已知设备计时时长（秒）",
                    "rows": [
                        [
                            label(s["sport"]),
                            s["timer_seconds"]["value"],
                            label(s["timer_seconds"]["status"]),
                        ]
                        for s in known
                    ],
                }
            )
            paragraph(
                "图表来源：本节清单的 设备运动段计时时长，按运动汇总已知值；部分已知不代表完整总时长。缺失项不绘制。"
            )
    for index, row in enumerate(facts["inventory"], 1):
        heading(
            f"活动 {index}：{label(row['sport'])} / {row['activity_ref']} / 运动段 {row['session_ordinal']}",
            3,
        )
        name = row["activity_name"]
        paragraph(
            "活动名称："
            + (name["value"] if name and name["value"] is not None else "缺失")
        )
        if name:
            paragraph(
                "名称状态："
                + label(name["status"])
                + (
                    "；来源：运动清单原记录（摘要 "
                    + name["source"]["capture_sha256"][:12]
                    + "）。"
                    if name["source"]
                    else "；无名称来源。"
                )
            )
        paragraph(f"时间：{timestamp(row['start_utc'])} 至 {timestamp(row['end_utc'])}")
        table(
            ["设备记录与覆盖", "值"],
            [
                [label_text, number(row[field], unit)]
                for label_text, field, unit in (
                    ("距离", "distance_m", " 米"),
                    ("设备计时时长", "timer_seconds", " 秒"),
                    ("经过时长", "elapsed_seconds", " 秒"),
                    ("有效时长", "valid_seconds", " 秒"),
                    ("采样覆盖", "sample_covered_seconds", " 秒"),
                    ("缺口", "gap_seconds", " 秒"),
                )
            ],
        )
        hr = row["historical_heart_rate"]
        paragraph(
            f"设备历史心率：平均 {number(hr['avg_heart_rate_bpm'], ' BPM')}；最高 {number(hr['max_heart_rate_bpm'], ' BPM')}。仅为已完成活动事实。"
        )
        zones = row["recorded_session_hr_zones"]
        if zones is None:
            paragraph("设备运动段心率分区时长：缺失。")
        else:
            table(
                ["设备分区序号", "已记录时长（秒）", "占比（%）"],
                [
                    [str(i + 1), number(d), number(zones["percentages"][i])]
                    for i, d in enumerate(zones["durations_seconds"])
                ],
            )
            paragraph(
                f"分区来源：设备原运动段心率分区时长，活动 {zones['activity_ref']}，FIT 摘要 {zones['fit_sha256'][:12]}，来源索引 {zones['reference_index']}。"
            )
            paragraph("占比从设备分区时长派生；不自行划区，也不用于未来课程处方。")
        paragraph("FIT 来源摘要：" + row["fit_sha256"][:12])
        paragraph(
            f"统计方法：连续指标按有效时长加权；距离基于有效距离采样间的线性变化；配速按覆盖时段计算。最大采样间隔 {number(row['methods']['max_sample_gap_seconds'], ' 秒')}。"
        )
        for value in row["limitations"]:
            paragraph("记录局限：" + label(value))
    for row in facts["unplaced_no_fit"]:
        paragraph(
            f"无 FIT、归属待定记录：活动 {row['activity_ref']}；清单日期 {row['inventory_date']}；{label(row['reason'])}。"
        )
        if row.get("activity_name"):
            paragraph(
                "活动名称："
                + (row["activity_name"]["value"] or "缺失")
                + "；"
                + label(row["activity_name"]["status"])
            )
    heading("三、重点跑技")
    if not view["running_analysis"]["technique"]:
        paragraph("本次没有足够依据给出重点跑技判断。")
    for item in view["running_analysis"]["technique"]:
        claim(item)
    heading("四、其他运动")
    if not view["other_sports"]:
        paragraph("本期冻结资料没有其他运动段可说明。")
    for item in view["other_sports"]:
        paragraph(f"活动 {item['activity_ref']} / 运动段 {item['session_ordinal']}")
        claim(item["explanation"])
    heading("五、计划对比")
    claim(view["running_analysis"]["plan_comparison"])
    comparison = view["plan"]["progression"]
    paragraph(
        "比较基线："
        + (
            "前一期固定计划，周期结束 "
            + timestamp(comparison["baseline"]["period_end_utc"])
            + "；计划不等于实际完成；来源摘要 "
            + comparison["baseline"]["running_sha256"][:12]
            if comparison["baseline"]
            else "无可比较的前一期固定计划，变化未知。"
        )
    )
    table(
        ["比较维度", "之前", "当前", "变化"],
        [
            [label(name), number(v["before"]), number(v["after"]), label(v["change"])]
            for name, v in comparison["dimensions"].items()
        ],
    )
    paragraph(
        f"距离变化：{label(comparison['distance_change'])}；强度比较：{label(comparison['intensity_change'])}。"
    )
    for value in comparison["limitations"] + view["plan"]["progression_limitations"]:
        paragraph("比较局限：" + label(value))
    heading("六、固定七日计划")
    paragraph(
        f"硬负荷课程：{view['plan']['hard_load_count']}；课程仅基于冻结跑步输入与目标。固定七日，不补课、不自动每日改课；休息日不创建课程。"
    )
    claim(view["plan"]["rationale"])
    for i, day in enumerate(view["plan"]["days"]):
        heading(
            day["date"]
            + " 周"
            + "一二三四五六日"[i]
            + (" / 休息" if day["kind"] == "rest" else " / 跑步"),
            3,
        )
        w = day["workout"]
        if w is None:
            paragraph("休息；不创建 Workout。")
            continue
        paragraph("课程类型：" + label(w["kind"]) + "；目的：" + w["purpose"])
        paragraph(
            "总剂量："
            + number(
                w["dose"]["value"], " 秒" if w["dose"]["unit"] == "seconds" else " 米"
            )
        )
        for group_index, group in enumerate(w["steps"], 1):
            heading(f"第 {group_index} 组：重复 {group['repeat']} 次", 4)
            for step_index, step in enumerate(group["steps"], 1):
                paragraph(
                    f"步骤 {step_index}：{label(step['phase'])}；{number(step['value'], ' 秒' if step['unit'] == 'seconds' else ' 米')}；用力 {label(step['effort'])}；RPE {step['rpe']}"
                )
                paragraph(step["instructions"])
        paragraph("技术备注：" + w["technical_notes"])
        for value in w["stop_conditions"]:
            paragraph("停止条件：" + value)
    heading("七、数据局限与安全")
    for value in facts["limitations"] + view["data_limitations"]:
        paragraph(label(value))
    paragraph(view["safety"]["note"])
    for value in view["validation_limits"]:
        paragraph("校验范围：" + label(value))
    paragraph(
        "本报告有独立修订记录，完整来源和内容摘要保存在本地。修订标识："
        + view["revision_id"]
        + "；内容摘要："
        + view["revision_sha256"][:12]
        + "。"
    )
    return result
