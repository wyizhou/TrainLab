from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

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


DECISION = _load(
    "trainlab_m11_v4_r18_contract_test",
    "skills/training-coach/scripts/weekly_decision_v4.py",
)
READER = _load(
    "trainlab_m11_v4_r18_reader_test",
    "skills/training-report-publisher/scripts/reader_content_v4.py",
)


def _step(label: str) -> dict[str, str]:
    return {
        "name": label,
        "instruction": f"完成{label}",
        "end_condition": f"{label}完成",
    }


def _running(session_type: str = "easy_run") -> dict[str, Any]:
    hard = session_type.startswith("sos_")
    return {
        "activity_kind": "running",
        "session_type": session_type,
        "name": "跑步课程",
        "purpose": "维持稳定训练",
        "load_level": "hard" if hard else "low",
        "duration_minutes": 45,
        "rpe_min": 6 if hard else 2,
        "rpe_max": 7 if hard else 4,
        "feel_guidance": "按RPE与动作体感执行",
        "steps": {
            "warmup": _step("热身"),
            "main": _step("主体"),
            "recovery": _step("恢复"),
            "cooldown": _step("放松"),
        },
        "technique_notes": ["保持动作稳定"],
        "stop_conditions": ["疼痛、胸痛、晕眩或异常呼吸时停止"],
    }


def _climbing() -> dict[str, Any]:
    value = _running()
    value.update(
        {
            "activity_kind": "climbing",
            "session_type": "climbing_technique",
            "name": "攀岩技术课",
        }
    )
    return value


def _rest() -> dict[str, Any]:
    return {
        "activity_kind": "rest",
        "session_type": "rest",
        "name": "休息",
        "purpose": "恢复",
        "load_level": "low",
        "duration_minutes": 0,
        "rpe_min": 1,
        "rpe_max": 1,
        "feel_guidance": "不安排结构化训练",
        "steps": {"checklist": _step("恢复检查")},
        "technique_notes": ["无需训练技术要求"],
        "stop_conditions": ["出现红旗症状时停止活动"],
    }


def _decision() -> dict[str, Any]:
    return {
        "schema_version": "weekly_model_decision_v1",
        "week_conclusion": "本周完整复盘后，下周保持训练连续性。",
        "health_review": "睡眠与恢复存在波动，继续观察趋势。",
        "all_activity_review": "已覆盖全部计划内外活动。",
        "technical_findings": [],
        "plan_comparison": "计划比较仅作次要背景。",
        "climbing_and_combined_load": "跑步、攀岩与恢复联合判断为保持。",
        "progression_decision": "hold",
        "training_plan": {
            "schema_version": "training_plan_decision_v1",
            "progression_rule": "hold",
            "progression_dimension": "none",
            "sos_omission_reason": None,
            "sos_schedule_reason": None,
            "days": {
                "day_1": _running("sos_threshold"),
                "day_2": _climbing(),
                "day_3": _running(),
                "day_4": _rest(),
                "day_5": _running(),
                "day_6": _running("long_easy"),
                "day_7": _rest(),
            },
        },
        "uncertainty": ["公开合成证据不代表私人判断。"],
        "evidence_refs": ["daily-observation:public-synthetic"],
    }


def _evidence() -> dict[str, Any]:
    missing: list[dict[str, Any]] = [
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
        for code in (
            "sleep:main_sleep",
            "rhr:resting_heart_rate",
            "hrv:hrv",
            "heart_rates:heart_rate",
            "max_metrics:vo2_max",
            "weigh_ins:weight",
        )
    ]
    missing[1] = {
        "metric_code": "rhr:resting_heart_rate",
        "status": "available",
        "value": {
            "resource": "rhr",
            "uncertainty": "named_fields",
            "metric": "resting_heart_rate",
            "resting_heart_rate_bpm": 48,
        },
        "unit": "bpm",
        "observed_date": "2026-08-11",
        "raw_refs": [{"raw_file_id": 501, "raw_sha256": "5" * 64}],
        "reason_code": None,
        "uncertainty": [],
    }
    return {
        "schema_version": "weekly_training_evidence_v2",
        "status": "ready",
        "period": {
            "activity_start_date": "2026-08-11",
            "activity_end_date": "2026-08-17",
            "sleep_wake_start_date": "2026-08-12",
            "sleep_wake_end_date": "2026-08-18",
        },
        "daily_observation_refs": [
            {
                "report_date": f"2026-08-{day + 1:02d}",
                "activity_date": f"2026-08-{day:02d}",
                "output_id": day,
                "sha256": f"{day:064x}",
            }
            for day in range(11, 18)
        ],
        "health_days": [
            {
                "health_date": f"2026-08-{day:02d}",
                "sleep_wake_date": f"2026-08-{day + 1:02d}",
                "facts": deepcopy(missing),
                "health_analysis_ref": {
                    "output_id": day + 100,
                    "sha256": f"{day + 100:064x}",
                },
            }
            for day in range(11, 18)
        ],
        "all_activities": [
            {
                "activity_inventory_id": 11,
                "raw_file_id": 1011,
                "raw_sha256": "b" * 64,
                "activity_date": "2026-08-11",
                "activity_kind": "running",
                "distance_km": 5.0,
                "duration_seconds": 2700,
                "average_heart_rate_bpm": 135,
                "maximum_heart_rate_bpm": 151,
                "coverage": {"summary": 1.0, "sequence": 1.0},
                "missing_fields": [],
                "uncertainty": [],
                "technical_metrics": [],
                "plan_relation": "unplanned",
            }
        ],
        "weekly_totals": {
            "activity_count": 1,
            "activity_days": 1,
            "no_activity_days": 6,
            "duration_seconds": 2700,
            "running_distance_km": 5.0,
            "by_activity_kind": {"running": 1},
        },
        "key_run_refs": [],
        "plan_comparison": {
            "date_only_matches": 0,
            "unplanned_activities": 1,
            "comparison_is_secondary": True,
        },
        "raw_reads": 0,
        "provider_calls": 0,
    }


def _context() -> dict[str, Any]:
    evidence = _evidence()
    return {
        "schema_version": "m11_v4_weekly_model_context_v2",
        "activity_period": evidence["period"],
        "next_plan_dates": [f"2026-08-{day:02d}" for day in range(19, 26)],
        "training_goal": {
            "schema_version": "training_goal_v1",
            "current_goal": {
                "competition_goal_and_date": "无",
                "training_focus": "跑步/攀岩联合训练",
                "long_term_load_rule": "保持稳定",
            },
            "weekly_availability": {
                "monday": "休息",
                "tuesday": "跑步",
                "wednesday": "跑步",
                "thursday": "攀岩",
                "friday": "休息",
                "saturday": "跑步",
                "sunday": "攀岩",
            },
            "training_preferences": {
                "intensity_preference": 3,
                "progression_rule": "保持稳定",
                "hard_load_rule": "最多三次",
                "missed_session_rule": "不补课",
            },
            "constraints": {
                "known_limitations": "无",
                "recovery_signals": "关注恢复",
                "red_flag_preference": "阻断自动执行",
            },
            "temporary_adjustment": {"adjustment": "无", "valid_period": "无"},
        },
        "weekly_evidence": evidence,
        "allowed_technical_activity_refs": [],
        "provider_calls": 0,
        "external_actions": 0,
    }


def test_business_schema_projects_to_exact_wire_schema() -> None:
    schemas = SOURCE / "skills/_shared/schemas"
    business = json.loads(
        (schemas / "weekly_model_decision_v1.schema.json").read_text()
    )
    wire = json.loads(
        (schemas / "weekly_model_decision_v1_codex.schema.json").read_text()
    )
    assert DECISION.project_wire_schema(business) == wire
    DECISION.require_wire_schema_parity(business, wire)


@pytest.mark.parametrize("forbidden", ["period", "date", "status"])
def test_model_decision_rejects_host_owned_fields(forbidden: str) -> None:
    value = _decision()
    value[forbidden] = "2026-08-11"
    assert validate_payload(value, "weekly_model_decision_v1")


@pytest.mark.parametrize("phase", ["warmup", "main", "recovery", "cooldown"])
def test_non_rest_course_requires_each_named_phase(phase: str) -> None:
    value = _decision()
    del value["training_plan"]["days"]["day_1"]["steps"][phase]
    assert validate_payload(value, "weekly_model_decision_v1")


def test_rest_course_requires_only_checklist_and_variants_do_not_mix() -> None:
    value = _decision()
    value["training_plan"]["days"]["day_4"]["steps"] = {"warmup": _step("非法热身")}
    assert validate_payload(value, "weekly_model_decision_v1")
    value = _decision()
    value["training_plan"]["days"]["day_2"]["session_type"] = "easy_run"
    assert validate_payload(value, "weekly_model_decision_v1")


def test_host_injects_only_verified_period_and_dates() -> None:
    result = DECISION.assemble_weekly_ai_result_v4(_decision(), _context())
    assert result["period"] == {
        "activity_start_date": "2026-08-11",
        "activity_end_date": "2026-08-17",
        "sleep_wake_start_date": "2026-08-12",
        "sleep_wake_end_date": "2026-08-18",
        "plan_start_date": "2026-08-19",
        "plan_end_date": "2026-08-25",
    }
    assert result["plan_dates"] == {
        f"day_{index}": f"2026-08-{18 + index:02d}" for index in range(1, 8)
    }
    assert validate_payload(result, "weekly_ai_result_v4") == []


@pytest.mark.parametrize(
    "path,text",
    [
        (("health_review",), "历史静息心率 48 bpm。"),
        (("training_plan", "days", "day_1", "feel_guidance"), "保持 Z2。"),
        (("technical_findings",), "目标心率区间用于下周。"),
    ],
)
def test_model_decision_rejects_numeric_bpm_and_zone_prescriptions(
    path: tuple[str, ...], text: str
) -> None:
    value = _decision()
    if path == ("technical_findings",):
        value["technical_findings"] = [
            {
                "activity_refs": [11],
                "observation": "历史分区事实。",
                "interpretation": "仅作历史描述。",
                "planning_implication": text,
                "confidence": "low",
                "evidence_refs": ["synthetic"],
                "limitations": ["公开合成"],
            }
        ]
    else:
        target: dict[str, Any] = value
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = text
    errors = DECISION.validate_weekly_model_decision_v1(value, _evidence())
    assert "model_heart_rate_text_forbidden" in errors


def test_reader_displays_only_typed_historical_bpm_with_lineage() -> None:
    context = _context()
    result = DECISION.assemble_weekly_ai_result_v4(_decision(), context)
    reader = READER.build_weekly_reader_content_v2(result, context["weekly_evidence"])
    health = next(
        section
        for section in reader["sections"]
        if section["section_code"] == "health_recovery"
    )
    activities = next(
        section
        for section in reader["sections"]
        if section["section_code"] == "all_activities"
    )
    assert any("48 bpm" in item and "raw 501" in item for item in health["items"])
    assert any(
        "2026-08-11" in item
        and "平均心率 135 bpm" in item
        and "最高心率 151 bpm" in item
        and "raw 1011" in item
        for item in activities["items"]
    )
    assert validate_payload(reader, "weekly_reader_content_v2") == []
