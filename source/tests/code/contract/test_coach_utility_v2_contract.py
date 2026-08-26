from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts.reader_safety import (
    validate_health_visible_text,
    validate_reader_visible_text,
)
from skills._shared.scripts.schema_validation import validate_payload

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COACH = _load(
    "trainlab_coach_utility_v2_contract",
    "skills/training-coach/scripts/coach_utility_v2.py",
)
RENDER = _load(
    "trainlab_coach_utility_v2_render_contract",
    "skills/training-report-publisher/scripts/render_coach_utility_v2.py",
)


def _step(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "name": phase,
        "instruction": f"完成{phase}",
        "end_condition": f"{phase}完成",
    }


def _course(day: str, session_type: str = "easy_run") -> dict[str, Any]:
    value = {
        "date": day,
        "activity_kind": "rest" if session_type == "rest" else "running",
        "session_type": session_type,
        "name": "恢复日" if session_type == "rest" else "轻松跑",
        "purpose": "恢复并维持训练连续性",
        "load_level": "low" if session_type != "sos_threshold" else "hard",
        "garmin_mapping_status": "unsupported_skip"
        if session_type == "rest"
        else "candidate",
        "duration_minutes": 40,
        "rpe_min": 1 if session_type == "rest" else 3,
        "rpe_max": 2 if session_type == "rest" else 4,
        "feel_guidance": "轻松、可以完整交谈",
        "steps": [_step("warmup"), _step("main"), _step("recovery"), _step("cooldown")],
        "start_gate": ["无持续疼痛"],
        "technique_notes": ["保持动作放松"],
        "downgrade_rule": "疲劳明显则休息",
        "stop_conditions": ["胸痛、眩晕或异常气短时停止"],
    }
    if session_type == "rest":
        value.pop("duration_minutes")
    return value


def _plan() -> dict[str, Any]:
    sessions = [
        "easy_run",
        "rest",
        "sos_threshold",
        "rest",
        "easy_run",
        "long_easy",
        "rest",
    ]
    items = [
        _course(f"2026-08-{24 + index:02d}", session)
        for index, session in enumerate(sessions)
    ]
    items[2]["name"] = "条件性节奏跑"
    items[2]["rpe_min"] = 6
    items[2]["rpe_max"] = 7
    items[2]["feel_guidance"] = "只能说短句但动作稳定"
    return {
        "schema_version": "training_plan_v2",
        "status": "succeeded",
        "progression_rule": "hold",
        "progression_dimension": "none",
        "sos_omission_reason": None,
        "items": items,
        "provider_calls": 0,
    }


def test_v2_schemas_accept_canonical_views() -> None:
    plan = _plan()
    assert validate_payload(plan, "training_plan_v2") == []
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=plan["items"][0],
        effective_course=plan["items"][0],
        adjustment="as_planned",
        yesterday_summary="昨日为恢复日，没有额外训练负荷。",
        review_health_summary="昨日非睡眠健康记录没有明确异常信号。",
        recovery_summary="睡眠与恢复指标支持按计划轻松跑。",
        decision_reasons=["维持原课，不增加距离或强度。"],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨夜睡眠", "昨日健康"],
        planned_course_context="verified_original",
    )
    weekly = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="睡眠总体稳定，后半周恢复余量下降。",
        activity_summary="跑步与攀岩负荷总体可控。",
        insights=[
            {
                "observation": "后半周睡眠缩短",
                "meaning": "恢复余量下降",
                "action": "SOS前检查恢复门",
            },
            {"observation": "跑量稳定", "meaning": "可以维持", "action": "不增加距离"},
            {
                "observation": "攀岩后疲劳",
                "meaning": "需错开硬课",
                "action": "相隔至少3天",
            },
        ],
        plan=plan,
        uncertainty=[],
    )
    assert validate_payload(daily, "daily_email_view_v2") == []
    assert validate_payload(weekly, "weekly_email_view_v2") == []
    daily["planned_course"]["raw_file_id"] = 12
    assert any(
        error.startswith("planned_course:additionalProperties")
        for error in validate_payload(daily, "daily_email_view_v2")
    )


def test_v2_renderer_exposes_all_actionable_sections_without_engineering_fields() -> (
    None
):
    plan = _plan()
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="caution",
        planned_course=plan["items"][2],
        effective_course=_course("2026-08-26", "easy_run"),
        adjustment="modified",
        yesterday_summary="昨日攀岩负荷偏高。",
        review_health_summary="昨日非睡眠健康记录没有明确异常信号。",
        recovery_summary="睡眠尚可，但疲劳较平时高。",
        decision_reasons=["取消质量刺激，保留轻松活动。"],
        adjustment_reason_codes=["insufficient_recovery"],
        evidence_labels=["昨日活动", "昨夜睡眠"],
        planned_course_context="verified_original",
    )
    rendered = RENDER.render_daily_v2(daily)
    for text in (
        "周计划原课",
        "今日调整",
        "热身",
        "主训练",
        "恢复",
        "放松",
        "开始前检查",
        "降级方案",
        "停止条件",
    ):
        assert text in rendered["html"]
    assert "schema_version" not in rendered["html"]
    assert "evidence_ref" not in rendered["html"]
    assert "心率区间" not in rendered["html"]


def test_v2_renderer_never_calls_a_test_baseline_the_historical_original() -> None:
    plan = _plan()
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=plan["items"][0],
        effective_course=plan["items"][0],
        adjustment="as_planned",
        yesterday_summary="昨日为恢复日。",
        review_health_summary="昨日健康记录没有明确异常信号。",
        recovery_summary="昨夜睡眠支持低负荷活动。",
        decision_reasons=["保持低负荷，不增加训练量。"],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨日健康", "昨夜睡眠"],
        planned_course_context="test_baseline",
    )
    rendered = RENDER.render_daily_v2(daily)
    assert "周计划原课</h2><p>未找到当时已经存在且可验证的周计划" in rendered["html"]
    assert "测试基准课（非历史原计划）" in rendered["html"]
    assert "周计划原课：无可验证记录" in rendered["text"]
    assert "昨日健康数据" in rendered["html"]
    assert "昨夜睡眠与恢复" in rendered["html"]


@pytest.mark.parametrize(
    "leak",
    [
        "raw_file_id=12",
        "output_id=9",
        "content_json={}",
        "skill_run_id=4",
        "error_code=blocked",
        "lineage_json=[]",
        "workflow_key=daily:2026-08-24",
        "source_output_id=9",
        "supersedes_raw_file_id=2",
        "delivery_skill_run_id=4",
    ],
)
def test_renderer_rejects_engineering_fields_even_inside_free_text(
    leak: str,
) -> None:
    plan = _plan()
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=plan["items"][0],
        effective_course=plan["items"][0],
        adjustment="as_planned",
        yesterday_summary="昨日恢复",
        review_health_summary="昨日非睡眠健康记录没有明确异常信号。",
        recovery_summary="恢复正常",
        decision_reasons=["按计划"],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨日活动"],
        planned_course_context="verified_original",
    )
    daily["yesterday_summary"] = leak
    with pytest.raises(ValueError, match="engineering_content_forbidden"):
        RENDER.render_daily_v2(daily)


@pytest.mark.parametrize(
    "prescription",
    [
        "建议 Zone 2",
        "目标心率 150 BPM",
        "按 maximum heart rate 的80%执行",
        "使用 Z3 完成主训练",
        "建议在Z2区完成",
        "把BPM控制稳定",
        "按80% HRmax执行",
        "本周采用Zone训练并据此控制强度。",
        "建议保持心率分区训练。",
        "建议按心率上下限控制强度。",
        "建议按心率范围控制强度。",
        "建议采用心率区带训练。",
        "建议依据心率最大控制强度。",
        "建议依据心率阈值控制强度。",
        "建议按Z-2完成主训练。",
        "目标写为BPM150。",
        "按HR-max的80%执行。",
        "使用target HR控制强度。",
        "本周安排乳酸阈值训练。",
    ],
)
def test_weekly_free_text_rejects_heart_rate_prescription(
    prescription: str,
) -> None:
    with pytest.raises(ValueError, match="heart_rate_prescription_forbidden"):
        COACH.build_weekly_view_v2(
            period="2026-08-12/2026-08-18",
            status="hold",
            health_summary=prescription,
            activity_summary="完成三次跑步和两次攀岩。",
            insights=[
                {"observation": "睡眠稳定", "meaning": "恢复可用", "action": "维持"},
                {
                    "observation": "跑量稳定",
                    "meaning": "无需加量",
                    "action": "保留一次SOS",
                },
                {"observation": "攀岩疲劳", "meaning": "需错开", "action": "间隔3天"},
            ],
            plan=_plan(),
            uncertainty=[],
        )


def test_daily_builder_rejects_engineering_free_text_before_render() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="engineering_content_forbidden"):
        COACH.build_daily_view_v2(
            report_date="2026-08-24",
            safety="ready",
            planned_course=plan["items"][0],
            effective_course=plan["items"][0],
            adjustment="as_planned",
            yesterday_summary="output_id=10",
            review_health_summary="昨日非睡眠健康记录没有明确异常信号。",
            recovery_summary="恢复正常",
            decision_reasons=["维持"],
            adjustment_reason_codes=["as_planned"],
            evidence_labels=["昨日活动"],
            planned_course_context="verified_original",
        )


def test_reader_safety_allows_labelled_observed_bpm_facts_only() -> None:
    assert (
        validate_health_visible_text(
            "昨日非睡眠健康记录：静息心率 47 bpm；活动平均心率 142 bpm。"
        )
        == []
    )
    assert validate_reader_visible_text("昨日健康记录：静息心率 47 bpm。") == [
        "heart_rate_prescription_forbidden"
    ]
    for prescription in (
        "目标静息心率 50 bpm",
        "建议把静息心率控制在 50 bpm",
        "把 BPM 控制稳定",
        "训练目标 150 bpm",
        "活动平均心率 142 bpm",
        "把静息心率控制稳定",
        "目标静息心率",
        "建议提高活动平均心率",
        "target: heart rate",
    ):
        assert validate_reader_visible_text(prescription) == [
            "heart_rate_prescription_forbidden"
        ]


def test_reader_safety_allows_weekly_observed_bpm_range_only() -> None:
    assert (
        validate_health_visible_text(
            "本周健康记录：静息心率 47至50 bpm、昨夜HRV 68至81 ms，不能据此增加负荷。"
        )
        == []
    )
    for prescription in (
        "本周目标静息心率 47至50 bpm。",
        "建议把静息心率控制在 47至50 bpm。",
    ):
        assert validate_health_visible_text(prescription) == [
            "heart_rate_prescription_forbidden"
        ]


def test_health_bpm_exception_rejects_distant_prescription_in_same_sentence() -> None:
    for text in (
        "本周健康记录：静息心率47至50 bpm，作为今天训练必须达到的目标。",
        "本周健康记录：静息心率47至50 bpm，今天训练达到这个数值即可。",
        "本周健康记录：静息心率47至50 bpm，这是今天训练应达到的数值。",
        "本周健康记录：静息心率47至50 bpm，训练时保持这个数值。",
        "本周健康记录：静息心率47至50 bpm；训练必须达到这个数值。",
        "本周健康记录：静息心率47至50 bpm;训练必须达到这个数值。",
    ):
        assert validate_health_visible_text(text) == [
            "heart_rate_prescription_forbidden"
        ]
        with pytest.raises(ValueError, match="heart_rate_prescription_forbidden"):
            COACH.build_weekly_view_v2(
                period="2026-08-12/2026-08-18",
                status="hold",
                health_summary=text,
                activity_summary="完成三次跑步。",
                insights=[
                    {
                        "observation": "睡眠稳定",
                        "meaning": "恢复可用",
                        "action": "维持",
                    },
                    {
                        "observation": "跑量稳定",
                        "meaning": "无需加量",
                        "action": "保留SOS",
                    },
                    {
                        "observation": "攀岩疲劳",
                        "meaning": "需错开",
                        "action": "间隔3天",
                    },
                ],
                plan=_plan(),
                uncertainty=[],
            )


def test_health_bpm_exception_accepts_common_observed_range_separators() -> None:
    for separator in ("至", "-", "~", "～", "–", "—"):
        for label in (
            "静息心率",
            "活动平均心率",
            "活动最高心率",
            "活动最大心率",
        ):
            text = f"本周健康记录：{label}47{separator}50 bpm。"
            assert validate_health_visible_text(text) == []
            assert validate_reader_visible_text(text) == [
                "heart_rate_prescription_forbidden"
            ]


def test_health_field_and_metric_label_are_the_observation_context() -> None:
    for text in (
        "活动最大心率170–176 bpm。历史训练使用RPE。",
        "活动平均心率142 bpm；本周训练使用RPE。",
    ):
        assert validate_health_visible_text(text) == []
        assert validate_reader_visible_text(text) == [
            "heart_rate_prescription_forbidden"
        ]


def test_observed_bpm_facts_are_allowed_in_narrative_but_never_course() -> None:
    observed = "本周历史记录：静息心率47至50 bpm。"
    course = _plan()["items"][0]
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=course,
        effective_course=course,
        adjustment="as_planned",
        yesterday_summary=observed,
        review_health_summary="昨日健康记录完整。",
        recovery_summary="昨夜睡眠稳定。",
        decision_reasons=[observed],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨日活动"],
        planned_course_context="verified_original",
    )
    assert observed in RENDER.render_daily_v2(daily)["text"]

    activity_observed = "本周活动平均心率142 bpm。"
    insight_observed = "本周活动最高心率176 bpm。"
    weekly = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="本周历史记录：静息心率47至50 bpm。",
        activity_summary=activity_observed,
        insights=[
            {
                "observation": insight_observed,
                "meaning": "恢复可用",
                "action": "维持",
            },
            {"observation": "跑量稳定", "meaning": "无需加量", "action": "保留SOS"},
            {"observation": "攀岩疲劳", "meaning": "需错开", "action": "间隔3天"},
        ],
        plan=_plan(),
        uncertainty=[],
    )
    weekly_text = RENDER.render_weekly_v2(weekly)["text"]
    assert activity_observed in weekly_text
    assert insight_observed in weekly_text


def test_daily_effective_course_rejects_observed_bpm_fact_as_instruction() -> None:
    plan = _plan()
    effective = dict(plan["items"][0])
    effective["feel_guidance"] = "昨日活动平均心率 142 bpm"
    with pytest.raises(ValueError, match="heart_rate_prescription_forbidden"):
        COACH.build_daily_view_v2(
            report_date="2026-08-24",
            safety="ready",
            planned_course=plan["items"][0],
            effective_course=effective,
            adjustment="modified",
            yesterday_summary="昨日恢复。",
            review_health_summary="昨日健康记录完整。",
            recovery_summary="昨夜睡眠稳定。",
            decision_reasons=["保持低负荷。"],
            adjustment_reason_codes=["insufficient_recovery"],
            evidence_labels=["昨日活动"],
            planned_course_context="verified_original",
        )


def test_final_renderer_rechecks_course_heart_rate_for_daily_and_weekly() -> None:
    plan = _plan()
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=plan["items"][0],
        effective_course=plan["items"][0],
        adjustment="as_planned",
        yesterday_summary="昨日恢复。",
        review_health_summary="昨日健康记录：静息心率 47 bpm。",
        recovery_summary="昨夜睡眠稳定。",
        decision_reasons=["保持低负荷。"],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨日活动"],
        planned_course_context="verified_original",
    )
    daily["effective_course"]["feel_guidance"] = "昨日活动平均心率 142 bpm"
    with pytest.raises(ValueError, match="heart_rate_prescription_forbidden"):
        RENDER.render_daily_v2(daily)

    weekly = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="本周历史记录：静息心率 47 bpm。",
        activity_summary="完成三次跑步。",
        insights=[
            {"observation": "睡眠稳定", "meaning": "恢复可用", "action": "维持"},
            {"observation": "跑量稳定", "meaning": "无需加量", "action": "保留SOS"},
            {"observation": "攀岩疲劳", "meaning": "需错开", "action": "间隔3天"},
        ],
        plan=_plan(),
        uncertainty=[],
    )
    weekly["training_plan"]["items"][0]["feel_guidance"] = "历史活动最高心率 176 bpm"
    with pytest.raises(ValueError, match="heart_rate_prescription_forbidden"):
        RENDER.render_weekly_v2(weekly)


def test_plain_text_contains_full_course_contract() -> None:
    plan = _plan()
    daily = COACH.build_daily_view_v2(
        report_date="2026-08-24",
        safety="ready",
        planned_course=plan["items"][0],
        effective_course=plan["items"][0],
        adjustment="as_planned",
        yesterday_summary="昨日恢复",
        review_health_summary="昨日非睡眠健康记录没有明确异常信号。",
        recovery_summary="恢复正常",
        decision_reasons=["维持"],
        adjustment_reason_codes=["as_planned"],
        evidence_labels=["昨日活动"],
        planned_course_context="verified_original",
    )
    text = RENDER.render_daily_v2(daily)["text"]
    for expected in (
        "RPE",
        "分钟",
        "体感",
        "开始前检查",
        "执行提示",
        "降级方案",
        "停止条件",
    ):
        assert expected in text


def test_weekly_renderer_exposes_health_load_insights_and_sos() -> None:
    weekly = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="本周睡眠总体稳定。",
        activity_summary="完成三次跑步和两次攀岩。",
        insights=[
            {
                "observation": "睡眠稳定",
                "meaning": "基础恢复可用",
                "action": "维持训练",
            },
            {
                "observation": "跑量稳定",
                "meaning": "无需加量",
                "action": "只保留一次SOS",
            },
            {
                "observation": "攀岩疲劳",
                "meaning": "硬课要错开",
                "action": "间隔至少3天",
            },
        ],
        plan=_plan(),
        uncertainty=[],
    )
    rendered = RENDER.render_weekly_v2(weekly)
    for text in (
        "健康总结",
        "运动与负荷总结",
        "观察 → 意义 → 行动",
        "七日训练计划",
        "条件性节奏跑",
    ):
        assert text in rendered["html"]
    assert "schema_version" not in rendered["text"]
    assert "target_bpm" not in rendered["text"]
    assert "课程强度仅使用 RPE 与体感描述" in rendered["html"]
    assert (
        validate_reader_visible_text(
            {"html": rendered["html"], "text": rendered["text"]}
        )
        == []
    )
