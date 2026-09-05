from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load() -> Any:
    path = SOURCE / "skills/training-coach/scripts/content_first_v4.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_content_first_v4_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load()


def _step(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "name": phase,
        "instruction": f"完成{phase}",
        "end_condition": f"{phase}完成",
    }


def _course(day: str, session_type: str = "easy_run") -> dict[str, Any]:
    kind = "rest" if session_type == "rest" else "running"
    hard = session_type.startswith("sos_")
    return {
        "date": day,
        "activity_kind": kind,
        "session_type": session_type,
        "name": "休息" if kind == "rest" else "固定课程",
        "purpose": "恢复" if kind == "rest" else "完成计划刺激",
        "load_level": "hard" if hard else "low",
        "duration_minutes": 0 if kind == "rest" else 45,
        "rpe_min": 1 if kind == "rest" else (6 if hard else 3),
        "rpe_max": 2 if kind == "rest" else (7 if hard else 4),
        "feel_guidance": "休息" if kind == "rest" else "以计划体感执行",
        "steps": (
            [_step("checklist")]
            if kind == "rest"
            else [_step("warmup"), _step("main"), _step("recovery"), _step("cooldown")]
        ),
        "technique_notes": ["保持动作稳定"],
        "stop_conditions": ["胸痛、晕厥或尖锐疼痛时停止"],
    }


def _plan() -> dict[str, Any]:
    sessions = [
        "easy_run",
        "rest",
        "sos_threshold",
        "rest",
        "climbing_technique",
        "long_easy",
        "rest",
    ]
    result: dict[str, Any] = {
        "schema_version": "training_plan_v3",
        "status": "succeeded",
        "progression_rule": "hold",
        "progression_dimension": "none",
        "sos_omission_reason": None,
        "sos_schedule_reason": "合成样例日期安排",
        "items": [
            _course(f"2026-08-{19 + index:02d}", session)
            for index, session in enumerate(sessions)
        ],
        "provider_calls": 0,
    }
    result["items"][4]["activity_kind"] = "climbing"
    return result


def _activity(day: str, inventory_id: int, kind: str = "running") -> dict[str, Any]:
    return {
        "activity_inventory_id": inventory_id,
        "raw_file_id": 1000 + inventory_id,
        "raw_sha256": f"{inventory_id:064x}",
        "activity_date": day,
        "activity_kind": kind,
        "distance_km": 5.0 if kind == "running" else None,
        "duration_seconds": 2700,
        "coverage": {"summary": 1.0, "sequence": 1.0},
        "missing_fields": [],
        "uncertainty": [],
        "technical_metrics": [],
    }


HEALTH_METRIC_CODES = (
    "sleep:main_sleep",
    "rhr:resting_heart_rate",
    "hrv:hrv",
    "heart_rates:heart_rate",
    "max_metrics:vo2_max",
    "weigh_ins:weight",
)


def _missing_health_facts() -> list[dict[str, Any]]:
    return [
        {
            "metric_code": code,
            "status": "missing",
            "value": None,
            "unit": None,
            "observed_date": None,
            "raw_refs": [],
            "reason_code": "not_found",
            "uncertainty": [],
        }
        for code in HEALTH_METRIC_CODES
    ]


def _observation(day: int, activities: list[dict[str, Any]]) -> dict[str, Any]:
    report_day = day + 1
    return {
        "schema_version": "daily_completed_observation_v1",
        "status": "ready",
        "report_date": f"2026-08-{report_day:02d}",
        "activity_date": f"2026-08-{day:02d}",
        "health_date": f"2026-08-{day:02d}",
        "sleep_wake_date": f"2026-08-{report_day:02d}",
        "inventory": {
            "expected_count": len(activities),
            "observed_count": len(activities),
            "complete": True,
        },
        "health_inventory": {
            "expected_raw_file_ids": [],
            "observed_raw_file_ids": [],
            "complete": True,
        },
        "activities": activities,
        "health_facts": _missing_health_facts(),
        "health_analysis_ref": {
            "output_id": 2000 + day,
            "sha256": f"{2000 + day:064x}",
        },
        "provider_calls": 0,
    }


def test_training_plan_v3_is_fixed_and_rejects_dynamic_course_fields() -> None:
    value = _plan()
    assert V4.validate_training_plan_v3(value) == []
    for forbidden in ("start_gate", "downgrade_rule", "alternative_course"):
        changed = deepcopy(value)
        changed["items"][0][forbidden] = "不得进入 v3"
        assert f"item_0_{forbidden}_forbidden" in V4.validate_training_plan_v3(changed)


def test_training_plan_v3_keeps_sos_and_hard_load_spacing() -> None:
    value = _plan()
    value["items"][5]["session_type"] = "climbing_hard"
    value["items"][5]["activity_kind"] = "climbing"
    value["items"][5]["load_level"] = "hard"
    assert "hard_load_gap_less_than_three_days" not in V4.validate_training_plan_v3(
        value
    )
    value["items"][3] = deepcopy(value["items"][5])
    value["items"][3]["date"] = "2026-08-22"
    assert "hard_load_gap_less_than_three_days" in V4.validate_training_plan_v3(value)


def test_weekly_evidence_contains_every_planned_and_unplanned_activity() -> None:
    observations = []
    for day in range(11, 18):
        activities = [_activity(f"2026-08-{day:02d}", day)]
        if day == 14:
            activities.append(_activity("2026-08-14", 114, "climbing"))
        observations.append(_observation(day, activities))
    evidence = V4.build_weekly_training_evidence_v2(
        observations,
        planned_activity_dates={"2026-08-11", "2026-08-13", "2026-08-16"},
    )
    assert evidence["period"] == {
        "activity_start_date": "2026-08-11",
        "activity_end_date": "2026-08-17",
        "sleep_wake_start_date": "2026-08-12",
        "sleep_wake_end_date": "2026-08-18",
    }
    assert len(evidence["all_activities"]) == 8
    assert any(
        item["plan_relation"] == "unplanned" for item in evidence["all_activities"]
    )
    assert evidence["raw_reads"] == 0
    assert evidence["provider_calls"] == 0


def test_weekly_evidence_rejects_incomplete_or_non_contiguous_observations() -> None:
    observations = [_observation(day, []) for day in range(11, 18)]
    observations[3]["inventory"]["complete"] = False
    with pytest.raises(ValueError, match="daily_observation_incomplete"):
        V4.build_weekly_training_evidence_v2(observations)
    observations = [_observation(day, []) for day in range(11, 18)]
    observations[-1]["activity_date"] = "2026-08-19"
    with pytest.raises(ValueError, match="daily_observation_dates_not_contiguous"):
        V4.build_weekly_training_evidence_v2(observations)


def test_daily_observation_rejects_health_inventory_self_claim() -> None:
    facts = _missing_health_facts()
    facts[1] = {
        "metric_code": "rhr:resting_heart_rate",
        "status": "available",
        "value": {
            "resource": "rhr",
            "uncertainty": "named_fields",
            "metric": "resting_heart_rate",
            "resting_heart_rate_bpm": 50,
        },
        "unit": "bpm",
        "observed_date": "2026-08-11",
        "raw_refs": [{"raw_file_id": 10, "raw_sha256": "a" * 64}],
        "reason_code": None,
        "uncertainty": [],
    }
    with pytest.raises(ValueError, match="daily_health_inventory_incomplete"):
        V4.build_daily_completed_observation(
            report_date="2026-08-12",
            activity_date="2026-08-11",
            health_date="2026-08-11",
            sleep_wake_date="2026-08-12",
            activities=[],
            expected_activity_count=0,
            health_facts=facts,
            expected_health_raw_file_ids=[10, 11],
            health_analysis_ref={"output_id": 1, "sha256": "b" * 64},
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_daily_observation_requires_exact_six_health_states(mutation: str) -> None:
    facts = _missing_health_facts()
    if mutation == "missing":
        facts.pop()
    elif mutation == "duplicate":
        facts[-1]["metric_code"] = facts[0]["metric_code"]
    else:
        facts[-1]["metric_code"] = "invented:health_metric"
    with pytest.raises(ValueError, match="daily_health_contract_invalid"):
        V4.build_daily_completed_observation(
            report_date="2026-08-12",
            activity_date="2026-08-11",
            health_date="2026-08-11",
            sleep_wake_date="2026-08-12",
            activities=[],
            expected_activity_count=0,
            health_facts=facts,
            expected_health_raw_file_ids=[],
            health_analysis_ref={"output_id": 1, "sha256": "b" * 64},
        )


def test_weekly_evidence_contains_exactly_42_health_states() -> None:
    evidence = V4.build_weekly_training_evidence_v2(
        [_observation(day, []) for day in range(11, 18)]
    )
    assert len(evidence["health_days"]) == 7
    assert sum(len(day["facts"]) for day in evidence["health_days"]) == 42
    assert all(
        {fact["metric_code"] for fact in day["facts"]} == set(HEALTH_METRIC_CODES)
        for day in evidence["health_days"]
    )


def test_decoupling_requires_explicit_eligible_steady_segment_and_power() -> None:
    activity = _activity("2026-08-11", 11)
    activity["sequence_resolution_seconds"] = 30
    activity["sequence"] = [
        {
            "offset_seconds": offset,
            "metrics": {"heart_rate_bpm": 130 + offset / 3600, "power_watts": 200},
        }
        for offset in range(0, 3000, 30)
    ]
    unavailable = V4.build_activity_technical_evidence(activity)
    metric = next(
        item
        for item in unavailable["metrics"]
        if item["metric_code"] == "aerobic_decoupling_power_hr_v1"
    )
    assert metric["status"] == "not_applicable"
    assert metric["method"]["exclusions"]

    activity["steady_segment"] = {
        "start_offset_seconds": 600,
        "end_offset_seconds": 3000,
        "excluded_intervals": [],
        "eligibility_source": "fit_session_and_lap_structure",
    }
    available = V4.build_activity_technical_evidence(activity)
    metric = next(
        item
        for item in available["metrics"]
        if item["metric_code"] == "aerobic_decoupling_power_hr_v1"
    )
    assert metric["status"] == "available"
    assert metric["confidence"] in {"moderate", "high"}
    assert metric["coverage"] >= 0.8


def test_technical_metrics_actually_exclude_first_ten_minutes() -> None:
    activity = _activity("2026-08-11", 11)
    activity["sequence_resolution_seconds"] = 30
    activity["sequence"] = [
        {
            "offset_seconds": offset,
            "metrics": {
                "heart_rate_bpm": 180 if offset < 600 else 130,
                "power_watts": 100 if offset < 600 else 200,
                "cadence_spm": 190 if offset < 600 else 170,
            },
        }
        for offset in range(0, 3000, 30)
    ]
    activity["steady_segment"] = {
        "start_offset_seconds": 0,
        "end_offset_seconds": 3000,
        "excluded_intervals": [],
        "eligibility_source": "fit_session_and_lap_structure",
    }
    result = V4.build_activity_technical_evidence(activity)
    for code in (
        "aerobic_decoupling_power_hr_v1",
        "running_dynamics_front_back_v1",
    ):
        metric = next(item for item in result["metrics"] if item["metric_code"] == code)
        assert metric["status"] == "available"
        assert metric["method"]["segment"].startswith("600-")
        assert "已实际排除活动前10分钟" in metric["method"]["exclusions"]


def test_weekly_ai_technical_findings_bind_to_available_key_run_metric() -> None:
    activity = _activity("2026-08-11", 11)
    metric_ref = f"activity:11:raw:1011:{11:064x}:metric:provider_hr_zone_duration_v1"
    activity["technical_metrics"] = [
        {
            "metric_code": "provider_hr_zone_duration_v1",
            "status": "available",
            "value": {
                "durations_seconds": [0, 1, 2, 3, 4, 5, 6],
                "percentages": [0, 4.76, 9.52, 14.29, 19.05, 23.81, 28.57],
                "definition_sha256": "d" * 64,
                "percentage_source": "derived_from_provider_duration",
            },
            "unit": "seconds_and_percent",
            "method": {
                "method_code": "provider_session_duration_passthrough",
                "method_version": "1.0",
                "segment": "whole provider session",
                "exclusions": [],
            },
            "coverage": 1.0,
            "confidence": "moderate",
            "evidence_refs": [metric_ref],
            "limitations": ["仅描述历史活动"],
        }
    ]
    observations = [
        _observation(day, [activity] if day == 11 else []) for day in range(11, 18)
    ]
    evidence = V4.build_weekly_training_evidence_v2(observations)
    result: dict[str, Any] = {
        "schema_version": "weekly_ai_result_v3",
        "status": "succeeded",
        "period": "2026-08-11/2026-08-17",
        "week_conclusion": "结论",
        "health_review": "健康总结",
        "all_activity_review": "活动总结",
        "technical_findings": [
            {
                "activity_refs": [11],
                "observation": "设备记录了历史分区时长。",
                "interpretation": "仅作历史事实。",
                "planning_implication": "不用于心率处方。",
                "confidence": "moderate",
                "evidence_refs": [metric_ref],
                "limitations": ["不重算分区"],
            }
        ],
        "plan_comparison": "次要背景",
        "climbing_and_combined_load": "无攀岩证据。",
        "progression_decision": "hold",
        "training_plan": _plan(),
        "uncertainty": [],
        "evidence_refs": ["daily-observation:synthetic"],
        "provider_calls": 0,
    }
    assert V4.validate_weekly_ai_result_v3(result, evidence) == []
    forged = deepcopy(result)
    forged["technical_findings"][0]["evidence_refs"] = ["forged"]
    assert (
        "technical_finding_0_metric_not_available"
        in V4.validate_weekly_ai_result_v3(forged, evidence)
    )
    unauthorized = deepcopy(result)
    unauthorized["technical_findings"][0]["activity_refs"] = [999]
    assert (
        "technical_finding_0_activity_not_allowed"
        in V4.validate_weekly_ai_result_v3(unauthorized, evidence)
    )


def test_weekly_ai_technical_findings_require_evidence_for_each_activity() -> None:
    activities: list[dict[str, Any]] = []
    metric_refs: dict[int, str] = {}
    for activity_id in (11, 12):
        activity = _activity(f"2026-08-{activity_id:02d}", activity_id)
        metric_ref = (
            f"activity:{activity_id}:raw:{1000 + activity_id}:"
            f"{activity_id:064x}:metric:provider_hr_zone_duration_v1"
        )
        metric_refs[activity_id] = metric_ref
        activity["technical_metrics"] = [
            {
                "metric_code": "provider_hr_zone_duration_v1",
                "status": "available",
                "value": {
                    "durations_seconds": [0, 1, 2, 3, 4, 5, 6],
                    "percentages": [
                        0,
                        4.76,
                        9.52,
                        14.29,
                        19.05,
                        23.81,
                        28.57,
                    ],
                    "definition_sha256": "d" * 64,
                    "percentage_source": "derived_from_provider_duration",
                },
                "unit": "seconds_and_percent",
                "method": {
                    "method_code": "provider_session_duration_passthrough",
                    "method_version": "1.0",
                    "segment": "whole provider session",
                    "exclusions": [],
                },
                "coverage": 1.0,
                "confidence": "moderate",
                "evidence_refs": [metric_ref],
                "limitations": ["仅描述历史活动"],
            }
        ]
        activities.append(activity)
    observations = [
        _observation(
            day,
            [
                item
                for item in activities
                if item["activity_date"] == f"2026-08-{day:02d}"
            ],
        )
        for day in range(11, 18)
    ]
    evidence = V4.build_weekly_training_evidence_v2(observations)
    result: dict[str, Any] = {
        "schema_version": "weekly_ai_result_v3",
        "status": "succeeded",
        "period": "2026-08-11/2026-08-17",
        "week_conclusion": "结论",
        "health_review": "健康总结",
        "all_activity_review": "活动总结",
        "technical_findings": [
            {
                "activity_refs": [11, 12],
                "observation": "两项活动均有设备记录的历史分区时长。",
                "interpretation": "仅作历史事实。",
                "planning_implication": "不用于心率处方。",
                "confidence": "moderate",
                "evidence_refs": [metric_refs[11], metric_refs[12]],
                "limitations": ["不重算分区"],
            }
        ],
        "plan_comparison": "次要背景",
        "climbing_and_combined_load": "无攀岩证据。",
        "progression_decision": "hold",
        "training_plan": _plan(),
        "uncertainty": [],
        "evidence_refs": ["daily-observation:synthetic"],
        "provider_calls": 0,
    }
    assert V4.validate_weekly_ai_result_v3(result, evidence) == []

    missing_second = deepcopy(result)
    missing_second["technical_findings"][0]["evidence_refs"] = [metric_refs[11]]
    assert (
        "technical_finding_0_activity_12_evidence_missing"
        in V4.validate_weekly_ai_result_v3(missing_second, evidence)
    )

    duplicate_activity = deepcopy(result)
    duplicate_activity["technical_findings"][0]["activity_refs"] = [11, 11]
    assert (
        "technical_finding_0_activity_refs_duplicate"
        in V4.validate_weekly_ai_result_v3(duplicate_activity, evidence)
    )

    unavailable_evidence = deepcopy(evidence)
    activity_12 = next(
        item
        for item in unavailable_evidence["all_activities"]
        if item["activity_inventory_id"] == 12
    )
    activity_12["technical_metrics"][0]["status"] = "insufficient_data"
    assert (
        "technical_finding_0_activity_12_evidence_missing"
        in V4.validate_weekly_ai_result_v3(result, unavailable_evidence)
    )

    excessive_confidence = deepcopy(result)
    excessive_confidence["technical_findings"][0]["confidence"] = "high"
    assert (
        "technical_finding_0_confidence_exceeds_host"
        in V4.validate_weekly_ai_result_v3(excessive_confidence, evidence)
    )

    shared_reference_evidence = deepcopy(evidence)
    shared_reference = metric_refs[11]
    activity_12 = next(
        item
        for item in shared_reference_evidence["all_activities"]
        if item["activity_inventory_id"] == 12
    )
    activity_12["technical_metrics"][0]["evidence_refs"] = [shared_reference]
    shared_reference_result = deepcopy(result)
    shared_reference_result["technical_findings"][0]["evidence_refs"] = [
        shared_reference
    ]
    errors = V4.validate_weekly_ai_result_v3(
        shared_reference_result, shared_reference_evidence
    )
    assert "technical_evidence_identity_invalid" in errors
    assert "technical_finding_0_activity_12_evidence_missing" in errors


@pytest.mark.parametrize(
    "bad_reference",
    [
        f"activity:99:raw:1011:{11:064x}:metric:provider_hr_zone_duration_v1",
        f"activity:11:raw:9999:{11:064x}:metric:provider_hr_zone_duration_v1",
        f"activity:11:raw:1011:{12:064x}:metric:provider_hr_zone_duration_v1",
        f"activity:11:raw:1011:{11:064x}:metric:invented_metric_v1",
    ],
)
def test_weekly_ai_rejects_metric_reference_identity_mismatch(
    bad_reference: str,
) -> None:
    activity = _activity("2026-08-11", 11)
    activity["technical_metrics"] = [
        {
            "metric_code": "provider_hr_zone_duration_v1",
            "status": "available",
            "value": {
                "durations_seconds": [0, 1, 2, 3, 4, 5, 6],
                "percentages": [0, 4.76, 9.52, 14.29, 19.05, 23.81, 28.57],
                "definition_sha256": "d" * 64,
                "percentage_source": "derived_from_provider_duration",
            },
            "unit": "seconds_and_percent",
            "method": {
                "method_code": "provider_session_duration_passthrough",
                "method_version": "1.0",
                "segment": "whole provider session",
                "exclusions": [],
            },
            "coverage": 1.0,
            "confidence": "moderate",
            "evidence_refs": [bad_reference],
            "limitations": ["仅描述历史活动"],
        }
    ]
    evidence = V4.build_weekly_training_evidence_v2(
        [_observation(day, [activity] if day == 11 else []) for day in range(11, 18)]
    )
    result = _weekly_result_for_reference(bad_reference)
    errors = V4.validate_weekly_ai_result_v3(result, evidence)
    assert "technical_evidence_identity_invalid" in errors


def _weekly_result_for_reference(reference: str) -> dict[str, Any]:
    return {
        "schema_version": "weekly_ai_result_v3",
        "status": "succeeded",
        "period": "2026-08-11/2026-08-17",
        "week_conclusion": "结论",
        "health_review": "健康总结",
        "all_activity_review": "活动总结",
        "technical_findings": [
            {
                "activity_refs": [11],
                "observation": "历史事实。",
                "interpretation": "仅作历史事实。",
                "planning_implication": "不用于处方。",
                "confidence": "moderate",
                "evidence_refs": [reference],
                "limitations": ["不重算分区"],
            }
        ],
        "plan_comparison": "次要背景",
        "climbing_and_combined_load": "无攀岩证据。",
        "progression_decision": "hold",
        "training_plan": _plan(),
        "uncertainty": [],
        "evidence_refs": ["daily-observation:synthetic"],
        "provider_calls": 0,
    }


def test_provider_zones_are_carried_but_never_recomputed_from_samples() -> None:
    activity = _activity("2026-08-11", 11)
    activity["sequence"] = [
        {"offset_seconds": 0, "metrics": {"heart_rate_bpm": 120}},
        {"offset_seconds": 30, "metrics": {"heart_rate_bpm": 180}},
    ]
    result = V4.build_activity_technical_evidence(activity)
    assert all(
        item["metric_code"] != "provider_hr_zone_duration_v1"
        for item in result["metrics"]
    )
    activity["observed_heart_rate_zones"] = {
        "source": "fit_session_time_in_hr_zone",
        "reference_mesg": "session",
        "reference_index": 0,
        "durations_seconds": [0, 60, 120, 180, 60, 0, 0],
        "definition_sha256": "a" * 64,
    }
    result = V4.build_activity_technical_evidence(activity)
    metric = next(
        item
        for item in result["metrics"]
        if item["metric_code"] == "provider_hr_zone_duration_v1"
    )
    assert metric["status"] == "available"
    assert metric["method"]["method_code"] == "provider_session_duration_passthrough"


def test_climbing_without_provider_intensity_or_user_rpe_stays_unknown() -> None:
    activity = _activity("2026-08-14", 14, "climbing")
    result = V4.build_activity_technical_evidence(activity)
    assert result["climbing_intensity"] == "intensity_unknown"
