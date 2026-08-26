from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load() -> Any:
    path = SOURCE / "skills/training-coach/scripts/coach_utility_v2.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_coach_utility_v2_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COACH = _load()


def _step(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "name": phase,
        "instruction": f"完成{phase}",
        "end_condition": f"{phase}完成",
    }


def _course(
    day: str, kind: str = "running", session: str = "easy_run"
) -> dict[str, Any]:
    hard = session in {
        "sos_threshold",
        "sos_cruise_intervals",
        "sos_hills",
        "climbing_hard",
    }
    result: dict[str, Any] = {
        "date": day,
        "activity_kind": kind,
        "session_type": session,
        "name": "条件性节奏跑" if session.startswith("sos_") else "轻松跑",
        "purpose": "建立稳定训练刺激",
        "load_level": "hard" if hard else "low",
        "garmin_mapping_status": "candidate"
        if kind == "running"
        else "unsupported_skip",
        "rpe_min": 3 if not hard else 6,
        "rpe_max": 4 if not hard else 7,
        "feel_guidance": "能完整交谈" if not hard else "只能说短句但动作稳定",
        "steps": [_step("warmup"), _step("main"), _step("recovery"), _step("cooldown")],
        "start_gate": ["无持续疼痛且精神状态正常"],
        "technique_notes": ["动作放松，不追配速"],
        "downgrade_rule": "恢复不足则改为30分钟轻松跑",
        "stop_conditions": ["胸痛、眩晕、异常气短或疼痛加重时停止"],
    }
    if kind == "running":
        result["duration_minutes"] = 45
    elif kind == "climbing":
        result["duration_minutes"] = 60
    else:
        result["session_type"] = "rest"
        result["name"] = "恢复日"
        result["rpe_min"] = 1
        result["rpe_max"] = 2
        result.pop("duration_minutes", None)
    return result


def _plan(rule: str = "hold") -> dict[str, Any]:
    kinds = [
        ("running", "easy_run"),
        ("rest", "rest"),
        ("running", "sos_threshold"),
        ("rest", "rest"),
        ("climbing", "climbing_technique"),
        ("running", "long_easy"),
        ("rest", "rest"),
    ]
    return {
        "schema_version": "training_plan_v2",
        "status": "succeeded",
        "progression_rule": rule,
        "progression_dimension": "none",
        "sos_omission_reason": None,
        "items": [
            _course(f"2026-08-{24 + index:02d}", kind, session)
            for index, (kind, session) in enumerate(kinds)
        ],
        "provider_calls": 0,
    }


def test_hold_plan_requires_exactly_one_conditional_sos() -> None:
    assert COACH.validate_training_plan_v2(_plan()) == []
    none = _plan()
    none["items"][2] = _course("2026-08-26")
    assert "sos_count_must_equal_one" in COACH.validate_training_plan_v2(none)
    two = _plan()
    two["items"][6] = _course("2026-08-30", "running", "sos_hills")
    assert "sos_count_must_equal_one" in COACH.validate_training_plan_v2(two)


def test_deload_can_omit_sos_only_with_evidence_reason() -> None:
    value = _plan("deload")
    value["items"][2] = _course("2026-08-26")
    assert "sos_omission_reason_missing" in COACH.validate_training_plan_v2(value)
    value["sos_omission_reason"] = {
        "reason_code": "insufficient_recovery",
        "explanation": "连续恢复不足",
        "evidence_refs": [3, 4, 5],
    }
    assert COACH.validate_training_plan_v2(value) == []


def test_caution_string_cannot_justify_zero_sos() -> None:
    value = _plan("deload")
    value["items"][2] = _course("2026-08-26")
    value["sos_omission_reason"] = {
        "reason_code": "caution",
        "explanation": "仅有caution",
        "evidence_refs": [3],
    }
    assert "sos_omission_reason_invalid" in COACH.validate_training_plan_v2(value)


def test_hard_loads_need_three_day_date_difference() -> None:
    value = _plan()
    value["items"][4] = _course("2026-08-28", "climbing", "climbing_hard")
    assert value["items"][2]["date"] == "2026-08-26"
    assert "hard_load_gap_less_than_three_days" in COACH.validate_training_plan_v2(
        value
    )


def test_course_requires_full_execution_detail() -> None:
    value = _plan()
    value["items"][0]["steps"] = [_step("main")]
    errors = COACH.validate_training_plan_v2(value)
    assert "item_0_required_phases_missing" in errors


@pytest.mark.parametrize(
    "forbidden",
    [
        "heart_rate_zone",
        "target_bpm",
        "max_heart_rate",
        "threshold_bpm",
        "Z2",
        "Zone 2",
        "150 BPM",
        "maximum heart rate at 80%",
        "目标心率150",
    ],
)
def test_prescription_rejects_heart_rate_zone_language(forbidden: str) -> None:
    value = _plan()
    value["items"][0]["technique_notes"].append(f"使用 {forbidden}")
    assert "heart_rate_prescription_forbidden" in COACH.validate_training_plan_v2(value)


def test_observed_heart_rate_is_allowed_as_historical_fact() -> None:
    facts = {"activity_average_heart_rate_bpm": 142, "activity_max_heart_rate_bpm": 168}
    assert COACH.validate_observed_health_facts(facts) == []


@pytest.mark.parametrize("weekly_first", [False, True])
def test_legacy_host_facts_keep_last_night_hrv_distinct_from_weekly_average(
    weekly_first: bool,
) -> None:
    last_night = {"name": "last_night_hrv_average", "value": 76, "unit": "ms"}
    weekly = {"name": "hrv_weekly_average", "value": 74, "unit": "ms"}
    metrics = [weekly, last_night] if weekly_first else [last_night, weekly]
    health, load, summary = COACH.derive_legacy_daily_host_facts(
        {
            "safety": "caution",
            "bounded_metrics": [
                {"name": "main_sleep_duration", "value": 7.93, "unit": "hours"},
                {"name": "resting_heart_rate", "value": 50, "unit": "bpm"},
                *metrics,
                {"name": "weight", "value": 69.9, "unit": "kg"},
            ],
        }
    )
    assert health == {
        "sleep_hours": 7.93,
        "legacy_safety": "caution",
        "resting_heart_rate_bpm": 50.0,
        "hrv_last_night_average_ms": 76.0,
        "weight_kg": 69.9,
    }
    assert load == {
        "running_distance_km": 0.0,
        "activity_count": 0,
        "hard_load_count": 0,
        "hard_load_classification": "unavailable",
    }
    assert "昨夜 HRV 76 ms" in summary
    assert "74" not in summary


@pytest.mark.parametrize(
    "metric_name",
    [
        "hrv_last_night_average",
        "last_night_hrv_average",
        "review_date_hrv_last_night_average",
        "review_date_last_night_hrv_average",
        "review_hrv_last_night_average",
        "review_last_night_hrv_average",
    ],
)
def test_legacy_host_facts_accept_real_last_night_hrv_field_variants(
    metric_name: str,
) -> None:
    health, _, summary = COACH.derive_legacy_daily_host_facts(
        {
            "safety": "ready",
            "bounded_metrics": [
                {"name": metric_name, "value": 71, "unit": "ms"},
            ],
        }
    )
    assert health["hrv_last_night_average_ms"] == 71.0
    assert "昨夜 HRV 71 ms" in summary


@pytest.mark.parametrize(
    "metric_name",
    [
        "other_hrv_last_night_average",
        "hrv_weekly_average_last_night_hrv_average",
    ],
)
def test_legacy_host_facts_reject_unapproved_last_night_hrv_prefixes(
    metric_name: str,
) -> None:
    health, _, summary = COACH.derive_legacy_daily_host_facts(
        {
            "safety": "ready",
            "bounded_metrics": [
                {"name": metric_name, "value": 888, "unit": "ms"},
            ],
        }
    )
    assert "hrv_last_night_average_ms" not in health
    assert "888" not in summary


def test_reference_pace_is_host_only_and_never_sos() -> None:
    value = _plan()
    value["items"][0]["reference_pace"] = {
        "schema_version": "comparable_pace_reference_v1",
        "seconds_per_km": 365,
        "observed_date": "2026-08-10",
        "activity_output_id": 91,
        "activity_sha256": "a" * 64,
        "label": "历史参考，不是目标配速",
    }
    assert COACH.validate_training_plan_v2(value) == []
    value["items"][2]["reference_pace"] = deepcopy(value["items"][0]["reference_pace"])
    assert "sos_reference_pace_forbidden" in COACH.validate_training_plan_v2(value)


def test_daily_adjustment_cannot_increase_or_move_planned_course() -> None:
    planned = _course("2026-08-26", "running", "sos_threshold")
    effective = deepcopy(planned)
    assert COACH.validate_daily_adjustment(planned, effective, "as_planned") == []
    effective["date"] = "2026-08-27"
    assert "daily_course_date_changed" in COACH.validate_daily_adjustment(
        planned, effective, "modified"
    )
    effective = deepcopy(planned)
    effective["duration_minutes"] = 60
    assert "daily_course_dose_increased" in COACH.validate_daily_adjustment(
        planned, effective, "modified"
    )


def test_daily_adjustment_requires_all_four_course_phases() -> None:
    planned = _course("2026-08-26", "running", "sos_threshold")
    effective = _course("2026-08-26", "running", "easy_run")
    effective["steps"] = [
        _step("warmup"),
        _step("warmup"),
        _step("main"),
        _step("cooldown"),
    ]
    assert (
        "daily_effective_course_required_phases_missing"
        in COACH.validate_daily_adjustment(planned, effective, "modified")
    )


def test_caution_alone_cannot_cancel_the_only_sos() -> None:
    planned = _course("2026-08-26", "running", "sos_threshold")
    effective = _course("2026-08-26", "running", "easy_run")
    errors = COACH.validate_daily_adjustment(
        planned,
        effective,
        "modified",
        safety="caution",
        adjustment_reason_codes=["caution"],
    )
    assert "sos_downgrade_evidence_missing" in errors
    assert (
        COACH.validate_daily_adjustment(
            planned,
            effective,
            "modified",
            safety="caution",
            adjustment_reason_codes=["insufficient_recovery"],
        )
        == []
    )


def test_daily_rollup_strips_paths_gps_and_point_series() -> None:
    context = {
        "status": "ready",
        "report_date": "2026-08-26",
        "review_date": "2026-08-25",
        "sleep_wake_date": "2026-08-26",
        "health": [
            {
                "resource": "rhr",
                "data_date": "2026-08-25",
                "metrics": {"resting_heart_rate_bpm": 48},
                "raw_file_id": 1,
                "sha256": "a" * 64,
                "relative_path": "private",
            }
        ],
        "activities": [
            {
                "activity_inventory_id": 9,
                "data_date": "2026-08-25",
                "summary": {"distance_km": 8.0},
                "observed_heart_rate": {"average_bpm": 142},
                "raw_file_id": 2,
                "raw_sha256": "b" * 64,
                "sequence": [{"gps": [1, 2]}],
            }
        ],
        "recent_trend": {"days_available": 7},
        "recent_health_metrics": {},
    }
    rollup = COACH.build_daily_evidence_rollup_v1(
        context,
        _course("2026-08-26"),
        plan_output_id=8,
        plan_sha256="c" * 64,
        planned_course_context="test_baseline",
    )
    serialized = str(rollup)
    assert "relative_path" not in serialized
    assert "sequence" not in serialized
    assert "gps" not in serialized.lower()
    assert rollup["activities"][0]["observed_heart_rate"]["average_bpm"] == 142
    assert rollup["planned_course_context"] == "test_baseline"


def test_daily_view_keeps_original_and_effective_course() -> None:
    planned = _course("2026-08-26", "running", "sos_threshold")
    effective = _course("2026-08-26", "running", "easy_run")
    view = COACH.build_daily_view_v2(
        report_date="2026-08-26",
        safety="caution",
        planned_course=planned,
        effective_course=effective,
        adjustment="modified",
        yesterday_summary="昨日攀岩量偏高。",
        recovery_summary="睡眠尚可，但主观疲劳上升。",
        decision_reasons=["保留训练习惯，取消质量刺激。"],
        adjustment_reason_codes=["insufficient_recovery"],
        evidence_labels=["昨日活动", "昨夜睡眠"],
        planned_course_context="test_baseline",
        review_health_summary="昨日静息心率与HRV记录完整，无明确异常信号。",
    )
    assert view["planned_course"]["session_type"] == "sos_threshold"
    assert view["effective_course"]["session_type"] == "easy_run"
    assert view["adjustment"] == "modified"
    assert view["planned_course_context"] == "test_baseline"
    assert "HRV" in view["review_health_summary"]


def test_weekly_digest_requires_exactly_seven_v2_dailies_and_never_raw() -> None:
    dailies = [
        {
            "schema_version": "daily_ai_result_v2",
            "report_date": f"2026-08-{12 + index:02d}",
            "status": "succeeded",
            "safety": "ready",
            "daily_load": {
                "running_distance_km": 5.0,
                "activity_count": 1,
                "hard_load_count": 0,
            },
            "health_observations": {"sleep_hours": 7.0, "rhr_bpm": 48, "hrv_ms": 60},
            "evidence_refs": [{"output_id": index + 1, "sha256": f"{index + 1:064x}"}],
        }
        for index in range(7)
    ]
    digest = COACH.build_weekly_digest_v1(dailies, [])
    assert digest["daily_count"] == 7
    assert digest["activity_summary"]["running_distance_km"] == 35.0
    assert "raw" not in str(digest).lower()
    with pytest.raises(ValueError, match="weekly_requires_exactly_seven_v2_dailies"):
        COACH.build_weekly_digest_v1(dailies[:6], [])


def test_weekly_view_has_health_load_insights_and_seven_courses() -> None:
    view = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="睡眠总体稳定，后半周恢复略有下降。",
        activity_summary="完成3次跑步和2次攀岩，硬负荷2次。",
        insights=[
            {
                "observation": "后半周睡眠缩短",
                "meaning": "恢复余量下降",
                "action": "SOS前保留恢复门",
            },
            {
                "observation": "跑量稳定",
                "meaning": "基础负荷可维持",
                "action": "本周不加距离",
            },
            {
                "observation": "攀岩后疲劳上升",
                "meaning": "跑攀需错开",
                "action": "硬攀与SOS相隔3天",
            },
        ],
        plan=_plan(),
        uncertainty=["缺少一日体重记录"],
    )
    assert len(view["insights"]) == 3
    assert len(view["training_plan"]["items"]) == 7
    assert view["training_plan"]["items"][2]["session_type"] == "sos_threshold"


def test_weekly_view_rejects_advice_misrepresented_as_completed_training() -> None:
    with pytest.raises(ValueError, match="unverified_adjustment_execution_claim"):
        COACH.build_weekly_view_v2(
            period="2026-08-12/2026-08-18",
            status="hold",
            health_summary="恢复总体稳定。",
            activity_summary="实际负荷低于原计划。",
            insights=[
                {
                    "observation": "今日调整已经执行",
                    "meaning": "负荷下降",
                    "action": "继续观察",
                },
                {"observation": "活动记录完整", "meaning": "可复盘", "action": "维持"},
                {"observation": "睡眠稳定", "meaning": "可恢复", "action": "早睡"},
            ],
            plan=_plan(),
            uncertainty=[],
        )

    assert COACH.validate_weekly_advisory_language(
        {"summary": "本周已执行降级，训练负荷比原计划减少。"}
    ) == ["unverified_adjustment_execution_claim"]


def test_weekly_view_allows_observed_activity_completion_facts() -> None:
    view = COACH.build_weekly_view_v2(
        period="2026-08-12/2026-08-18",
        status="hold",
        health_summary="恢复总体稳定。",
        activity_summary="本周记录并完成5次活动。",
        insights=[
            {"observation": "完成3次跑步", "meaning": "跑量稳定", "action": "维持"},
            {"observation": "完成2次攀岩", "meaning": "负荷可见", "action": "错开硬课"},
            {"observation": "睡眠稳定", "meaning": "可恢复", "action": "继续观察"},
        ],
        plan=_plan(),
        uncertainty=[],
    )
    assert view["activity_summary"] == "本周记录并完成5次活动。"
