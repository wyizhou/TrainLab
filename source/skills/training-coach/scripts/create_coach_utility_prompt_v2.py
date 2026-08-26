#!/usr/bin/env python3
"""Create bounded Coaching Utility v2 prompts without invoking a model."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from coach_utility_v2 import validate_training_plan_v2

COMMON = """只使用 Host evidence JSON，不读取数据库、raw、文件系统、凭据或外部服务。provider_calls 必须为0。
TrainLab 不计算或处方心率区间、目标BPM、最大心率、乳酸阈值或Z1-Z5。已观测RHR、HRV、活动平均/最高心率只能作为历史事实。
跑步处方以RPE、可说话程度和动作感受为主。只有Host提供comparable_pace_reference_v1时，recovery/easy/long可附历史参考；SOS不得使用参考配速。
不要编造指标、伤病、比赛目标或证据。"""

_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


def validate_weekly_daily_input_refs(value: object) -> list[dict[str, Any]]:
    """Return normalized v2 daily refs or reject every malformed form consistently."""
    if not isinstance(value, list) or len(value) != 7:
        raise ValueError("weekly_daily_input_refs_invalid")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("weekly_daily_input_refs_invalid")
        output_id = item.get("output_id")
        sha256 = item.get("sha256")
        if (
            type(output_id) is not int
            or output_id <= 0
            or not isinstance(sha256, str)
            or _SHA256_PATTERN.fullmatch(sha256) is None
        ):
            raise ValueError("weekly_daily_input_refs_invalid")
        normalized.append({"output_id": output_id, "sha256": sha256})
    if len({item["output_id"] for item in normalized}) != 7:
        raise ValueError("weekly_daily_input_refs_invalid")
    return normalized


def daily_prompt(context: dict[str, Any], planned_course: dict[str, Any]) -> str:
    plan_errors = validate_training_plan_v2(
        {
            "schema_version": "training_plan_v2",
            "status": "succeeded",
            "progression_rule": "hold",
            "progression_dimension": "none",
            "sos_omission_reason": None,
            "items": [planned_course] * 7,
            "provider_calls": 0,
        }
    )
    ignored = {
        "course_dates_not_contiguous",
        "duplicate_course_date",
        "sos_count_must_equal_one",
        "hard_load_gap_less_than_three_days",
        "hard_load_count_exceeds_three",
    }
    if any(error not in ignored for error in plan_errors):
        raise ValueError("planned_course_invalid")
    planned_context = context.get("planned_course_context")
    if planned_context not in {"verified_original", "test_baseline"}:
        raise ValueError("planned_course_context_invalid")
    course_wording = (
        "保留周计划原课和今日有效课程"
        if planned_context == "verified_original"
        else "明确说明历史原计划不可验证，并把给定课程仅称为测试基准课；不得称为历史原课"
    )
    payload = {"context": context, "planned_course": planned_course}
    return (
        "你是TrainLab日报教练。输出daily_ai_result_v2严格JSON。\n"
        + COMMON
        + "\n必须分别解释昨日训练、昨日非睡眠健康事实、昨夜睡眠与恢复，并"
        + course_wording
        + "。"
        "今日只能按原计划、降级、休息或阻断，不得增加剂量、提升强度、移动或补做SOS。"
        "无论保持、降级、休息或阻断，effective_course都必须保留warmup、main、recovery、cooldown四个独立阶段。"
        "每个决定引用Host给出的证据。\nHost evidence JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def weekly_prompt(
    digest: dict[str, Any],
    goal_summary: dict[str, Any],
    daily_input_refs: list[dict[str, Any]],
) -> str:
    if (
        digest.get("schema_version") != "weekly_evidence_digest_v1"
        or digest.get("daily_count") != 7
    ):
        raise ValueError("weekly_digest_invalid")
    normalized_daily_input_refs = validate_weekly_daily_input_refs(daily_input_refs)
    payload = {
        "weekly_digest": digest,
        "daily_input_refs": normalized_daily_input_refs,
        "goal": goal_summary,
    }
    return (
        "你是TrainLab周报教练。输出weekly_ai_result_v2严格JSON。\n"
        + COMMON
        + "\n只能读取精确七份日报形成的weekly_digest和最多四份历史周总结，绝不回读raw。"
        "日报中的今日调整是建议，不是已完成训练；除非Host给出独立完成证据，不得写成已经执行或实际负荷已降低。"
        "每条洞察的evidence_refs只能引用顶层daily_input_refs中的七份v2日报output_id；"
        "禁止引用weekly_digest.daily_refs或日报内部的legacy/raw证据ID。"
        "输出健康总结、运动与负荷总结、3到5条观察→意义→行动洞察和连续七天详细课表。"
        "hold/advance恰好一节条件性SOS，默认星期三；deload、红旗或有证据的明显恢复不足可为0并说明。"
        "SOS和高负荷攀岩合计最多3次，日期差至少3天。每节课必须给出热身、主训练、恢复、放松、"
        "开始门、执行提示、降级和停止条件。\nHost evidence JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
