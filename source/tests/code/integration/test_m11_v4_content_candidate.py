from __future__ import annotations

import ast
import importlib.util
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skills._shared.state import canonical_json, init_database

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = _load(
    "trainlab_m11_v4_candidate_test",
    "skills/training-report-publisher/scripts/build_m11_v4_candidate.py",
)
RUNNER = _load(
    "trainlab_m11_v4_weekly_runner_test",
    "skills/training-coach/scripts/run_weekly_content_v4.py",
)


def _step(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "name": phase,
        "instruction": f"完成{phase}",
        "end_condition": f"{phase}完成",
    }


def _course(day: int, session: str) -> dict[str, Any]:
    rest = session == "rest"
    hard = session.startswith("sos_")
    return {
        "date": f"2026-08-{day:02d}",
        "activity_kind": "rest" if rest else "running",
        "session_type": session,
        "name": "休息" if rest else "训练课",
        "purpose": "恢复" if rest else "形成稳定训练刺激",
        "load_level": "hard" if hard else "low",
        "duration_minutes": 0 if rest else 45,
        "rpe_min": 1 if rest else (6 if hard else 3),
        "rpe_max": 2 if rest else (7 if hard else 4),
        "feel_guidance": "休息" if rest else "按RPE和动作体感执行",
        "steps": [_step("checklist")]
        if rest
        else [_step("warmup"), _step("main"), _step("recovery"), _step("cooldown")],
        "technique_notes": ["保持动作稳定"],
        "stop_conditions": ["胸痛、晕厥或尖锐疼痛时停止"],
    }


def _weekly_result() -> dict[str, Any]:
    sessions = [
        "easy_run",
        "rest",
        "sos_threshold",
        "rest",
        "easy_run",
        "long_easy",
        "rest",
    ]
    return {
        "schema_version": "weekly_ai_result_v3",
        "status": "succeeded",
        "period": "2026-08-11/2026-08-17",
        "week_conclusion": "本周活动与恢复证据完整，下一周保持当前负荷。",
        "health_review": "睡眠与恢复按七日证据总结。",
        "all_activity_review": "已覆盖证据中的全部活动。",
        "technical_findings": [],
        "plan_comparison": "计划比较仅作为次要背景。",
        "climbing_and_combined_load": "攀岩强度缺少明确证据时保持未知。",
        "progression_decision": "hold",
        "training_plan": {
            "schema_version": "training_plan_v3",
            "status": "succeeded",
            "progression_rule": "hold",
            "progression_dimension": "none",
            "sos_omission_reason": None,
            "sos_schedule_reason": "公开合成样例日期安排",
            "items": [
                _course(19 + index, session) for index, session in enumerate(sessions)
            ],
            "provider_calls": 0,
        },
        "uncertainty": ["公开合成样例不代表私人训练判断。"],
        "evidence_refs": ["daily-observation:public-synthetic"],
        "provider_calls": 0,
    }


def _owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(payload)
    path.chmod(0o600)


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


def _empty_weekly_evidence() -> dict[str, Any]:
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
                "facts": _missing_health_facts(),
                "health_analysis_ref": {
                    "output_id": day + 100,
                    "sha256": f"{day + 100:064x}",
                },
            }
            for day in range(11, 18)
        ],
        "all_activities": [],
        "weekly_totals": {
            "activity_count": 0,
            "activity_days": 0,
            "no_activity_days": 7,
            "duration_seconds": 0,
            "running_distance_km": 0,
            "by_activity_kind": {},
        },
        "key_run_refs": [],
        "plan_comparison": {
            "date_only_matches": 0,
            "unplanned_activities": 0,
            "comparison_is_secondary": True,
        },
        "raw_reads": 0,
        "provider_calls": 0,
    }


def _training_goal() -> dict[str, Any]:
    return {
        "schema_version": "training_goal_v1",
        "current_goal": {
            "competition_goal_and_date": "无",
            "training_focus": "跑步/攀岩联合训练",
            "long_term_load_rule": "由近期证据动态判断",
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
            "progression_rule": "保持稳定后再进阶",
            "hard_load_rule": "每周最多三次且间隔至少两个日历日",
            "missed_session_rule": "不补偿错过的质量课",
        },
        "constraints": {
            "known_limitations": "无",
            "recovery_signals": "关注睡眠与RHR/HRV趋势",
            "red_flag_preference": "红旗时停止自动外部执行",
        },
        "temporary_adjustment": {
            "adjustment": "无",
            "valid_period": "无",
        },
    }


def _goal_markdown() -> str:
    return """# 我的训练目标

## 当前目标

- 比赛目标与日期：无
- 当前训练重点：跑步/攀岩联合训练
- 周跑量、跑步频率和长跑距离的长期规则：由近期证据动态判断

## 每周可训练安排

- 周一：休息
- 周二：跑步
- 周三：跑步
- 周四：攀岩
- 周五：休息
- 周六：跑步
- 周日：攀岩

## 训练偏好

- 训练强度偏好：3/5，代表平衡推进
- 进阶方式：保持稳定后再进阶
- 硬负荷上限与最小间隔：每周最多三次且间隔至少两个日历日
- 错过课程与距离/强度调整规则：不补偿错过的质量课

## 身体限制与恢复关注

- 已知伤病、疼痛或其他限制：无
- 需要特别关注的恢复信号：关注睡眠与RHR/HRV趋势
- 出现红旗时的处理偏好：红旗时停止自动外部执行

## 临时要求

- 当前长期目标之外的临时调整：无
- 临时调整的有效周期：无
"""


def _model_context() -> dict[str, Any]:
    evidence = _empty_weekly_evidence()
    return {
        "schema_version": "m11_v4_weekly_model_context_v2",
        "activity_period": evidence["period"],
        "next_plan_dates": [f"2026-08-{day:02d}" for day in range(19, 26)],
        "training_goal": _training_goal(),
        "weekly_evidence": evidence,
        "allowed_technical_activity_refs": [],
        "provider_calls": 0,
        "external_actions": 0,
    }


def _context_with_health_fact() -> dict[str, Any]:
    context = _model_context()
    context["weekly_evidence"]["health_days"][0]["facts"][1] = {
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
    return context


def _context_with_vo2_fact() -> dict[str, Any]:
    context = _model_context()
    context["weekly_evidence"]["health_days"][0]["facts"][4] = {
        "metric_code": "max_metrics:vo2_max",
        "status": "available",
        "value": {
            "resource": "max_metrics",
            "metric": "vo2_max",
            "vo2_max": 51.0,
            "unit": "ml/kg/min",
            "observed_date": "2026-08-10",
            "age_days": 1,
            "selection_kind": "latest_prior",
        },
        "unit": "ml/kg/min",
        "observed_date": "2026-08-10",
        "raw_refs": [{"raw_file_id": 551, "raw_sha256": "5" * 64}],
        "reason_code": None,
        "uncertainty": [],
    }
    return context


def _context_with_technical_metric() -> dict[str, Any]:
    context = _model_context()
    evidence = context["weekly_evidence"]
    activity_ref = {
        "activity_inventory_id": 11,
        "raw_file_id": 1011,
        "raw_sha256": "b" * 64,
    }
    metric_ref = f"activity:11:raw:1011:{'b' * 64}:metric:provider_hr_zone_duration_v1"
    evidence["all_activities"] = [
        {
            **activity_ref,
            "activity_date": "2026-08-11",
            "activity_kind": "running",
            "distance_km": 5.0,
            "duration_seconds": 2700,
            "average_heart_rate_bpm": 135,
            "maximum_heart_rate_bpm": 151,
            "coverage": {"summary": 1.0, "sequence": 1.0},
            "missing_fields": [],
            "uncertainty": [],
            "technical_metrics": [
                {
                    "metric_code": "provider_hr_zone_duration_v1",
                    "status": "available",
                    "value": {
                        "durations_seconds": [0, 300, 600, 900, 600, 300, 0],
                        "percentages": [0, 11.11, 22.22, 33.33, 22.22, 11.11, 0],
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
                    "confidence": "high",
                    "evidence_refs": [metric_ref],
                    "limitations": ["仅描述历史活动"],
                }
            ],
            "plan_relation": "unplanned",
        }
    ]
    evidence["weekly_totals"] = {
        "activity_count": 1,
        "activity_days": 1,
        "no_activity_days": 6,
        "duration_seconds": 2700,
        "running_distance_km": 5.0,
        "by_activity_kind": {"running": 1},
    }
    evidence["key_run_refs"] = [activity_ref]
    evidence["plan_comparison"]["unplanned_activities"] = 1
    context["allowed_technical_activity_refs"] = [activity_ref]
    return context


def _rewrite_frozen_context(root: Path, context_value: dict[str, Any]) -> None:
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    work = Path(manifest["ai_work_root"])
    context_path = work / "context.json"
    prompt_path = work / "prompt.txt"
    template = (SOURCE / "skills/_shared/prompts/weekly-content-v4-v2.txt").read_text(
        encoding="utf-8"
    )
    _owner_write(context_path, canonical_json(context_value).encode())
    _owner_write(
        prompt_path,
        (template + "\n" + canonical_json(context_value) + "\n").encode(),
    )
    manifest["context_sha256"] = RUNNER.file_sha256(context_path)
    manifest["prompt_sha256"] = RUNNER.file_sha256(prompt_path)
    manifest["prompt_template_sha256"] = RUNNER.file_sha256(
        SOURCE / "skills/_shared/prompts/weekly-content-v4-v2.txt"
    )
    manifest["repository_prompt_template_sha256"] = manifest["prompt_template_sha256"]
    _owner_write(manifest_path, canonical_json(manifest).encode())


def _candidate(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir(mode=0o700)
    work = tmp_path / "model-work"
    work.mkdir(mode=0o700)
    prompt = work / "prompt.txt"
    context = work / "context.json"
    schema = work / "weekly_ai_result_v3_codex.schema.json"
    context_value = _model_context()
    template_path = SOURCE / "skills/_shared/prompts/weekly-content-v4-v2.txt"
    template = template_path.read_text(encoding="utf-8")
    _owner_write(
        prompt,
        (template + "\n" + canonical_json(context_value) + "\n").encode(),
    )
    _owner_write(context, canonical_json(context_value).encode())
    _owner_write(
        schema,
        (
            SOURCE / "skills/_shared/schemas/weekly_ai_result_v3_codex.schema.json"
        ).read_bytes(),
    )
    manifest = {
        "schema_version": "m11_v4_content_candidate_v2",
        "status": "prepared",
        "prompt_sha256": RUNNER.file_sha256(prompt),
        "context_sha256": RUNNER.file_sha256(context),
        "wire_schema_sha256": RUNNER.file_sha256(schema),
        "repository_wire_schema_sha256": RUNNER.file_sha256(
            SOURCE / "skills/_shared/schemas/weekly_ai_result_v3_codex.schema.json"
        ),
        "context_contract_schema_sha256": RUNNER.file_sha256(
            SOURCE / "skills/_shared/schemas/m11_v4_weekly_model_context_v2.schema.json"
        ),
        "training_goal_contract_schema_sha256": RUNNER.file_sha256(
            SOURCE / "skills/_shared/schemas/training_goal_v1.schema.json"
        ),
        "weekly_evidence_contract_schema_sha256": RUNNER.file_sha256(
            SOURCE / "skills/_shared/schemas/weekly_training_evidence_v2.schema.json"
        ),
        "health_fact_contract_schema_sha256": RUNNER.file_sha256(
            SOURCE / "skills/_shared/schemas/health_fact_v2.schema.json"
        ),
        "prompt_template_sha256": RUNNER.file_sha256(template_path),
        "repository_prompt_template_sha256": RUNNER.file_sha256(template_path),
        "goal_template_sha256": RUNNER.file_sha256(SOURCE / "goal.module.md"),
        "repository_goal_template_sha256": RUNNER.file_sha256(
            SOURCE / "goal.module.md"
        ),
        "ai_work_root": str(work),
        "model_calls_authorized": 1,
        "model_calls_completed": 0,
        "provider_calls": 0,
        "external_actions": 0,
    }
    _owner_write(root / "candidate-manifest.json", canonical_json(manifest).encode())
    return root


def test_model_context_rejects_private_field_names() -> None:
    evidence = {
        "period": {},
        "key_run_refs": [],
        "all_activities": [{"gps": [1, 2]}],
    }
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(evidence, "公开合成目标")


@pytest.mark.parametrize(
    ("schema_name", "output_kind", "operation", "payload"),
    [
        (
            "daily_health_analysis_v3",
            "daily_summary",
            "daily_coach",
            {
                "schema_version": "daily_health_analysis_v3",
                "status": "succeeded",
                "report_date": "2026-08-12",
                "review_date": "2026-08-11",
                "sleep_wake_date": "2026-08-12",
                "safety": "ready",
                "health_summary": "公开合成健康总结。",
                "sleep_analysis": "公开合成睡眠总结。",
                "recovery_analysis": "公开合成恢复总结。",
                "health_alert": None,
                "uncertainty": [],
                "evidence_refs": [1],
                "provider_calls": 0,
            },
        ),
        ("weekly_ai_result_v3", "weekly_summary", "weekly_coach", _weekly_result()),
    ],
)
def test_v4_summary_append_satisfies_current_sqlite_text_contract(
    tmp_path: Path,
    schema_name: str,
    output_kind: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    database = init_database(tmp_path / "state/trainlab.db")
    output_id = BUILDER._append(
        database,
        skill_name="training-coach",
        operation=operation,
        schema_name=schema_name,
        logical_key=f"test:{schema_name}",
        payload=payload,
        output_kind=output_kind,
        period_start="2026-08-12",
        period_end="2026-08-12",
        lineage=[],
    )
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT content_json,content_text FROM skill_outputs WHERE id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row == (canonical_json(payload), canonical_json(payload))


def test_v4_builder_uses_only_current_sqlite_output_kinds() -> None:
    tree = ast.parse(
        (
            SOURCE
            / "skills/training-report-publisher/scripts/build_m11_v4_candidate.py"
        ).read_text(encoding="utf-8")
    )
    output_kinds = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_append"
        for keyword in node.keywords
        if keyword.arg == "output_kind"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    allowed = {
        "sync_summary",
        "bounded_evidence",
        "daily_summary",
        "weekly_fitness_review",
        "weekly_summary",
        "training_plan",
        "report_artifact",
        "email_render",
        "garmin_workout_contract",
        "execution_summary",
    }
    assert output_kinds <= allowed
    assert output_kinds == {
        "bounded_evidence",
        "daily_summary",
        "weekly_summary",
        "report_artifact",
    }


def test_candidate_builder_emits_exact_six_health_states() -> None:
    context = {
        "health": [
            {
                "raw_file_id": 41,
                "sha256": "a" * 64,
                "resource": "rhr",
                "data_date": "2026-08-11",
                "metrics": {
                    "resource": "rhr",
                    "uncertainty": "named_fields",
                    "metric": "resting_heart_rate",
                    "resting_heart_rate_bpm": 48,
                },
                "parser": "json_named_fields_v1",
            }
        ]
    }
    facts = BUILDER._health_facts_from_context(
        context, health_date="2026-08-11", sleep_wake_date="2026-08-12"
    )
    assert len(facts) == 6
    assert [fact["metric_code"] for fact in facts] == list(BUILDER.HEALTH_FACT_SPECS)
    assert facts[1]["status"] == "available"
    assert all(fact["status"] == "missing" for fact in facts[2:])
    assert facts[0]["status"] == "missing"


@pytest.mark.parametrize(
    ("observed_date", "expected_status", "expected_reason"),
    [
        ("2026-08-11", "available", None),
        ("2026-07-12", "available", None),
        ("not-a-date", "insufficient_data", "date_mismatch"),
    ],
)
def test_candidate_builder_normalizes_recent_vo2_health_state(
    observed_date: str, expected_status: str, expected_reason: str | None
) -> None:
    context = {
        "health": [
            {
                "raw_file_id": 51,
                "sha256": "b" * 64,
                "resource": "max_metrics",
                "data_date": observed_date,
                "metrics": {
                    "resource": "max_metrics",
                    "metric": "vo2_max",
                    "vo2_max": 51.0,
                    "unit": "ml/kg/min",
                    "observed_date": observed_date,
                    "age_days": 1,
                    "selection_kind": "latest_prior",
                },
                "parser": "recent_health_metrics_v1",
            }
        ]
    }
    facts = BUILDER._health_facts_from_context(
        context, health_date="2026-08-11", sleep_wake_date="2026-08-12"
    )
    vo2 = next(fact for fact in facts if fact["metric_code"] == "max_metrics:vo2_max")
    assert vo2["status"] == expected_status
    assert vo2["reason_code"] == expected_reason
    if expected_status == "available":
        assert vo2["value"]["age_days"] in {0, 30}


@pytest.mark.parametrize(
    "goal",
    ["联系 owner@example.com", "PASSWORD=private", "token: private"],
)
def test_model_context_rejects_private_goal_content(goal: str) -> None:
    evidence: dict[str, Any] = {
        "period": {},
        "key_run_refs": [],
        "all_activities": [],
    }
    structured_goal = _training_goal()
    structured_goal["current_goal"]["training_focus"] = goal
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(evidence, structured_goal)


def test_training_goal_parser_emits_strict_business_object() -> None:
    result = BUILDER._parse_training_goal_v1(_goal_markdown())
    assert result == _training_goal()
    assert "#" not in canonical_json(result)
    assert "我的训练目标" not in canonical_json(result)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "unknown", "extra_text", "intensity"],
)
def test_training_goal_parser_rejects_template_drift(mutation: str) -> None:
    text = _goal_markdown()
    if mutation == "missing":
        text = text.replace("- 周日：攀岩\n", "")
    elif mutation == "duplicate":
        text += "- 周日：休息\n"
    elif mutation == "unknown":
        text += "- 未知字段：内容\n"
    elif mutation == "extra_text":
        text += "这是一段未声明文字\n"
    else:
        text = text.replace("训练强度偏好：3", "训练强度偏好：6")
    with pytest.raises(BUILDER.CandidateV4Error, match="training_goal_contract"):
        BUILDER._parse_training_goal_v1(text)


@pytest.mark.parametrize(
    "value",
    [
        "联系 owner@example.com",
        "token: private",
        "使用 GPS 路线复盘",
        "/Users/private/goal.md",
        "请读取/Users/private/goal.md",
        "路径/etc/passwd",
        "read /opt/private/config",
        "/",
        "../goal.md",
        "skills/training-coach",
        "goal.md",
        r"C:\private\goal.md",
        r"\\server\private\goal.md",
    ],
)
def test_runner_revalidates_private_context_before_model_call(
    tmp_path: Path, value: str
) -> None:
    root = _candidate(tmp_path)
    context_value = _model_context()
    context_value["training_goal"]["current_goal"]["training_focus"] = value
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(
            context_value["weekly_evidence"], context_value["training_goal"]
        )
    _rewrite_frozen_context(root, context_value)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize(
    "goal",
    ["跑步/攀岩联合安排", "RHR/HRV 只作历史事实", "参考配速 6:00 min/km"],
)
def test_runner_allows_normal_unicode_slash_text(tmp_path: Path, goal: str) -> None:
    root = _candidate(tmp_path)
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = goal
    assert (
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
        == context
    )
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1


def test_vc008_allows_only_schema_bound_vo2_units_for_builder_and_runner(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_vo2_fact()
    assert (
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
        == context
    )
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_metric",
        "wrong_status",
        "top_level_only",
        "nested_only",
        "variant",
        "ordinary_text",
        "technical_limitation",
    ],
)
def test_vc008_rejects_vo2_unit_outside_exact_schema_binding_before_model(
    tmp_path: Path, mutation: str
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_vo2_fact()
    fact = context["weekly_evidence"]["health_days"][0]["facts"][4]
    if mutation == "wrong_metric":
        fact["metric_code"] = "weigh_ins:weight"
    elif mutation == "wrong_status":
        fact["status"] = "missing"
    elif mutation == "top_level_only":
        fact["value"]["unit"] = "ml_per_kg_per_min"
    elif mutation == "nested_only":
        fact["unit"] = "ml_per_kg_per_min"
    elif mutation == "variant":
        fact["unit"] = "ml/kg/min/evil"
        fact["value"]["unit"] = "ml/kg/min/evil"
    elif mutation == "ordinary_text":
        context = _model_context()
        context["training_goal"]["current_goal"]["training_focus"] = (
            "普通文本 ml/kg/min"
        )
    else:
        context = _context_with_technical_metric()
        context["weekly_evidence"]["all_activities"][0]["technical_metrics"][0][
            "limitations"
        ] = ["不得用整场均值或速度/心率替代"]

    with pytest.raises(
        BUILDER.CandidateV4Error,
        match="model_context_(?:private_field|invalid)",
    ):
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context_invalid"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


def test_vc008_host_decoupling_limitation_uses_no_slash() -> None:
    source = (SOURCE / "skills/training-coach/scripts/content_first_v4.py").read_text(
        encoding="utf-8"
    )
    assert "不得用整场均值或速度/心率替代" not in source
    assert "不得用整场均值、速度或心率替代" in source


@pytest.mark.parametrize(
    "value",
    [
        "activity_name: private route",
        "activity name=private route",
        "activity-name：private route",
        "activityName: private route",
        "活动名称：私人路线",
        "活动名=私人路线",
        "22.1234, 114.1234",
        "-22.123456; +114.12345678",
        "Bearer private-value",
        "Authorization: private-value",
        "README",
        "Dockerfile",
        "pyproject.toml",
        "私人目标.md",
        "email.json",
    ],
)
def test_vc006_runner_blocks_every_frozen_private_value_before_pending(
    tmp_path: Path, value: str
) -> None:
    root = _candidate(tmp_path)
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = value
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize("delimiter", [",", ";"])
@pytest.mark.parametrize(
    "ascii_whitespace",
    [
        pytest.param(" ", id="space"),
        pytest.param("\t", id="horizontal-tab"),
        pytest.param("\n", id="line-feed"),
        pytest.param("\v", id="vertical-tab"),
        pytest.param("\f", id="form-feed"),
        pytest.param("\r", id="carriage-return"),
        pytest.param("\r\n\v\f", id="mixed-ascii-whitespace"),
    ],
)
def test_vc006_runner_blocks_coordinate_pairs_with_every_ascii_whitespace(
    tmp_path: Path, delimiter: str, ascii_whitespace: str
) -> None:
    root = _candidate(tmp_path)
    context = _model_context()
    coordinate = f"坐标 22.1234{ascii_whitespace}{delimiter}{ascii_whitespace}114.1234"
    context["training_goal"]["current_goal"]["training_focus"] = coordinate
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
    _rewrite_frozen_context(root, context)
    assert any(
        error.endswith(":private_value")
        for error in RUNNER.MODEL_CONTEXT.validate_model_context_v2(context)
    )
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context_invalid"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize(
    "value",
    [
        "éfoo@example.com",
        "孤立 token 只是普通词",
        "foo.py",
    ],
)
def test_vc006_runner_allows_explicit_advisory_only_values(
    tmp_path: Path, value: str
) -> None:
    root = _candidate(tmp_path)
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = value
    assert (
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
        == context
    )
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1


VC007_ACTIVITY_LABELS = (
    "activity_name",
    "activity name",
    "activity-name",
    "activityName",
    "活动名称",
    "活动名",
)

VC007_UNICODE_SPACES = (
    "\u00a0",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200a",
    "\u202f",
    "\u205f",
    "\u3000",
)


@pytest.mark.parametrize("delimiter", [":", "：", "="])
@pytest.mark.parametrize("label", VC007_ACTIVITY_LABELS)
def test_vc007_activity_labels_use_local_nfkc_and_raw_delimiters(
    tmp_path: Path, label: str, delimiter: str
) -> None:
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = (
        f"说明 {label}{delimiter} 私人活动"
    )
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
    root = _candidate(tmp_path)
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context_invalid"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize(
    "value",
    [
        "Ⓐtoken:x",
        "ⒶBearer x",
        "ⒶAuthorization:x",
        "ⒶGPS",
        "ａｃｔｉｖｉｔｙ＿ｎａｍｅ:private",
        "ｍｉｎ/km",
        "README",
        "Dockerfile",
        "Makefile",
        "CMakeLists.txt",
        "pyproject.toml",
        "requirements.txt",
        ".env",
        "goal.md",
        "email.json",
        "private.json",
        "private.fit",
        "private.gpx",
        "private.tcx",
        "private.sqlite",
        "private.db",
        "private.toml",
        "private.yaml",
        "private.yml",
        "private.txt",
        "private.env",
        "private.ini",
        "private.cfg",
        "private.conf",
        "private.pem",
        "private.key",
    ],
)
def test_vc007_raw_ascii_private_fragments_block_builder_and_runner(
    tmp_path: Path, value: str
) -> None:
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = value
    with pytest.raises(BUILDER.CandidateV4Error, match="model_context_private_field"):
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
    root = _candidate(tmp_path)
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context_invalid"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize("delimiter", [",", ";"])
@pytest.mark.parametrize("unicode_space", VC007_UNICODE_SPACES)
def test_vc007_unicode_coordinate_spaces_are_advisory_only(
    tmp_path: Path, delimiter: str, unicode_space: str
) -> None:
    value = f"坐标 22.1234{unicode_space}{delimiter}{unicode_space}114.1234"
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = value
    assert (
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
        == context
    )
    root = _candidate(tmp_path)
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1


@pytest.mark.parametrize(
    "value",
    [
        "éfoo@example.com",
        "ᵃowner@example.com",
        "²foo@example.com",
        "ｆｏｏ＠ｅｘａｍｐｌｅ．ｃｏｍ",
        "２２．１２３４，１１４．１２３４",
        "ｔｏｋｅｎ：x",
        "ｐａｓｓｗｏｒｄ＝x",
        "Ｂｅａｒｅｒ x",
        "Ａｕｔｈｏｒｉｚａｔｉｏｎ：x",
        "ＧＰＳ",
        "ＲＥＡＤＭＥ",
        "ｇｏａｌ．ｍｄ",
        "folder／private",
        "folder＼private",
        "toKen:x",
        "authorızation:x",
        "GPſ",
        "activity_name﹕private",
        "activity_name＝private",
        "孤立 token 只是普通词",
        "foo.py",
    ],
)
def test_vc007_compatibility_and_matrix_external_values_are_advisory_only(
    tmp_path: Path, value: str
) -> None:
    context = _model_context()
    context["training_goal"]["current_goal"]["training_focus"] = value
    assert (
        BUILDER._bounded_model_context(
            context["weekly_evidence"], context["training_goal"]
        )
        == context
    )
    root = _candidate(tmp_path)
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1


def test_vc006_authoritative_templates_have_frozen_hashes() -> None:
    contracts = RUNNER.MODEL_CONTEXT.require_authoritative_contracts()
    assert contracts["prompt_template_sha256"] == (
        "15828d08b13876b183cc6091e960da9395d89ad788ba08c1c331c4b49ce4dab5"
    )
    assert contracts["goal_template_sha256"] == (
        "362c6dba4a7b0f3668da8a2d8c37e6325efe5498845b77f3f1002b8eb56be136"
    )


@pytest.mark.parametrize(
    "manifest_key",
    ["repository_prompt_template_sha256", "repository_goal_template_sha256"],
)
def test_vc006_runner_requires_independent_template_manifest_binding(
    tmp_path: Path, manifest_key: str
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop(manifest_key)
    _owner_write(manifest_path, canonical_json(manifest).encode())
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    with pytest.raises(ValueError, match="weekly_model_.*template.*drift"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


def test_vc006_runner_rejects_prompt_and_manifest_synchronized_drift(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    work = Path(manifest["ai_work_root"])
    context = json.loads((work / "context.json").read_text())
    drifted_template = b"drifted public template\n"
    _owner_write(
        work / "prompt.txt",
        drifted_template + b"\n" + canonical_json(context).encode() + b"\n",
    )
    drift_sha = RUNNER.file_sha256(work / "prompt.txt")
    manifest["prompt_sha256"] = drift_sha
    manifest["prompt_template_sha256"] = "0" * 64
    manifest["repository_prompt_template_sha256"] = "0" * 64
    _owner_write(manifest_path, canonical_json(manifest).encode())
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_prompt_template_drift"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_vc006_pending_intent_io_failure_never_starts_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = _candidate(tmp_path)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    if failure == "fsync":
        monkeypatch.setattr(
            RUNNER.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync"))
        )
    else:
        original_replace = RUNNER.os.replace

        def fail_intent_replace(source: str | Path, target: str | Path) -> None:
            if Path(target).name == "attempt-intent.json":
                raise OSError("replace")
            original_replace(source, target)

        monkeypatch.setattr(RUNNER.os, "replace", fail_intent_replace)

    with pytest.raises(OSError):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending/attempt-intent.json").exists()
    assert not (root / "weekly-ai-attempt").exists()


@pytest.mark.parametrize(
    "case",
    [
        "available_null",
        "missing_non_null",
        "missing_with_raw",
        "insufficient_without_raw",
        "outside_lookback_rhr",
        "duplicate_metric",
        "missing_metric",
    ],
)
def test_runner_rejects_invalid_health_state_matrix_before_model_call(
    tmp_path: Path, case: str
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_health_fact()
    facts = context["weekly_evidence"]["health_days"][0]["facts"]
    rhr = facts[1]
    if case == "available_null":
        rhr["value"] = None
    elif case == "missing_non_null":
        rhr["status"] = "missing"
        rhr["reason_code"] = "not_found"
    elif case == "missing_with_raw":
        rhr.update(
            {
                "status": "missing",
                "value": None,
                "unit": None,
                "observed_date": None,
                "reason_code": "not_found",
            }
        )
    elif case == "insufficient_without_raw":
        rhr.update(
            {
                "status": "insufficient_data",
                "value": None,
                "unit": None,
                "observed_date": None,
                "raw_refs": [],
                "reason_code": "incomplete",
            }
        )
    elif case == "outside_lookback_rhr":
        rhr.update(
            {
                "status": "missing",
                "value": None,
                "unit": None,
                "observed_date": None,
                "raw_refs": [],
                "reason_code": "outside_lookback",
            }
        )
    elif case == "duplicate_metric":
        facts[-1]["metric_code"] = facts[0]["metric_code"]
    else:
        facts.pop()
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


@pytest.mark.parametrize(
    ("case", "value"),
    [
        ("unknown", 1),
        ("activity_name", "private route"),
        ("email", "owner@example.com"),
        ("token", "private"),
        ("path", "/etc/passwd"),
    ],
)
def test_runner_rejects_open_health_value_fields_before_model_call(
    tmp_path: Path, case: str, value: object
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_health_fact()
    context["weekly_evidence"]["health_days"][0]["facts"][1]["value"][
        "surprise_field" if case == "unknown" else case
    ] = value
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


@pytest.mark.parametrize(
    "case",
    [
        "unknown_value_field",
        "unknown_metric",
        "available_null",
        "unavailable_non_null",
    ],
)
def test_runner_rejects_open_or_mismatched_technical_values_before_model_call(
    tmp_path: Path, case: str
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_technical_metric()
    metric = context["weekly_evidence"]["all_activities"][0]["technical_metrics"][0]
    if case == "unknown_value_field":
        metric["value"]["surprise_field"] = 1
    elif case == "unknown_metric":
        metric["metric_code"] = "invented_metric_v1"
    elif case == "available_null":
        metric["value"] = None
    else:
        metric["status"] = "insufficient_data"
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


def test_runner_rejects_cross_activity_metric_reference_alias_before_model_call(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    context = _context_with_technical_metric()
    evidence = context["weekly_evidence"]
    first = evidence["all_activities"][0]
    second = json.loads(json.dumps(first))
    second.update(
        {
            "activity_inventory_id": 12,
            "raw_file_id": 1012,
            "raw_sha256": "c" * 64,
            "activity_date": "2026-08-12",
        }
    )
    evidence["all_activities"].append(second)
    second_ref = {
        "activity_inventory_id": 12,
        "raw_file_id": 1012,
        "raw_sha256": "c" * 64,
    }
    evidence["key_run_refs"].append(second_ref)
    context["allowed_technical_activity_refs"].append(second_ref)
    evidence["weekly_totals"].update(
        {
            "activity_count": 2,
            "activity_days": 2,
            "no_activity_days": 5,
            "duration_seconds": 5400,
            "running_distance_km": 10.0,
            "by_activity_kind": {"running": 2},
        }
    )
    evidence["plan_comparison"]["unplanned_activities"] = 2
    _rewrite_frozen_context(root, context)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_context"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


@pytest.mark.parametrize(
    "drift",
    ["const", "required", "type", "additional_properties"],
)
def test_runner_rejects_candidate_wire_schema_and_manifest_drift(
    tmp_path: Path, drift: str
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    schema_path = (
        Path(manifest["ai_work_root"]) / "weekly_ai_result_v3_codex.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    if drift == "const":
        schema["properties"]["status"]["const"] = "blocked"
    elif drift == "required":
        schema["required"].remove("provider_calls")
    elif drift == "type":
        schema["properties"]["provider_calls"]["type"] = "string"
    else:
        schema["additionalProperties"] = True
    _owner_write(schema_path, canonical_json(schema).encode())
    manifest["wire_schema_sha256"] = RUNNER.file_sha256(schema_path)
    manifest["repository_wire_schema_sha256"] = RUNNER.file_sha256(
        SOURCE / "skills/_shared/schemas/weekly_ai_result_v3_codex.schema.json"
    )
    _owner_write(manifest_path, canonical_json(manifest).encode())
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_wire_schema_source_drift"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


@pytest.mark.parametrize(
    "manifest_key",
    [
        "context_contract_schema_sha256",
        "training_goal_contract_schema_sha256",
        "weekly_evidence_contract_schema_sha256",
        "health_fact_contract_schema_sha256",
    ],
)
def test_runner_rejects_authoritative_contract_manifest_drift(
    tmp_path: Path, manifest_key: str
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[manifest_key] = "0" * 64
    _owner_write(manifest_path, canonical_json(manifest).encode())
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_wire_schema_source_drift"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


def test_runner_rejects_prompt_context_mismatch_before_model_call(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    prompt_path = Path(manifest["ai_work_root"]) / "prompt.txt"
    _owner_write(prompt_path, b"public but not the canonical context prompt")
    manifest["prompt_sha256"] = RUNNER.file_sha256(prompt_path)
    _owner_write(manifest_path, canonical_json(manifest).encode())
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_model_prompt_context_mismatch"):
        RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt.pending").exists()


def test_activity_inventory_is_independent_of_report_artifacts(tmp_path: Path) -> None:
    database = tmp_path / "inventory.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE activity_inventory(id INTEGER,activity_date TEXT,collection_state TEXT);"
        "CREATE TABLE raw_files(id INTEGER,activity_inventory_id INTEGER,integrity_state TEXT,file_format TEXT);"
        "INSERT INTO activity_inventory VALUES(7,'2026-08-11','complete');"
        "INSERT INTO activity_inventory VALUES(8,'2026-08-11','complete');"
        "INSERT INTO raw_files VALUES(70,7,'verified','fit');"
        "INSERT INTO raw_files VALUES(80,8,'verified','fit');"
    )
    connection.commit()
    connection.close()
    assert BUILDER._independent_activity_inventory(database, "2026-08-11") == [7, 8]


def test_incomplete_activity_inventory_blocks_before_report_use(tmp_path: Path) -> None:
    database = tmp_path / "inventory.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE activity_inventory(id INTEGER,activity_date TEXT,collection_state TEXT);"
        "CREATE TABLE raw_files(id INTEGER,activity_inventory_id INTEGER,integrity_state TEXT,file_format TEXT);"
        "INSERT INTO activity_inventory VALUES(7,'2026-08-11','incomplete');"
    )
    connection.commit()
    connection.close()
    with pytest.raises(BUILDER.CandidateV4Error, match="activity_inventory_incomplete"):
        BUILDER._independent_activity_inventory(database, "2026-08-11")


def test_health_inventory_closes_exact_resources_and_selected_recent_values(
    tmp_path: Path,
) -> None:
    database = tmp_path / "health.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE raw_files(id INTEGER,data_class TEXT,integrity_state TEXT,data_date TEXT,resource_kind TEXT)"
    )
    connection.executemany(
        "INSERT INTO raw_files VALUES(?,?,?,?,?)",
        [
            (1, "health", "verified", "2026-08-11", "rhr"),
            (2, "health", "verified", "2026-08-11", "heart_rates"),
            (3, "health", "verified", "2026-08-12", "sleep"),
            (4, "health", "verified", "2026-08-10", "max_metrics"),
        ],
    )
    connection.commit()
    connection.close()
    facts = [
        {
            "metric_code": "max_metrics:vo2_max",
            "raw_refs": [{"raw_file_id": 4, "raw_sha256": "4" * 64}],
        }
    ]
    assert BUILDER._independent_health_raw_ids(
        database,
        health_date="2026-08-11",
        sleep_wake_date="2026-08-12",
        selected_facts=facts,
    ) == [1, 2, 3, 4]


def test_weekly_runner_rejects_model_work_inside_raw_candidate(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    unsafe = root / "ai-workdir"
    unsafe.mkdir(mode=0o700)
    manifest["ai_work_root"] = str(unsafe)
    _owner_write(manifest_path, canonical_json(manifest).encode())
    with pytest.raises(ValueError, match="work_directory_not_isolated"):
        RUNNER.run_weekly_content(root, executable="codex")


def test_weekly_runner_rejects_undeclared_model_work_file(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    manifest = json.loads((root / "candidate-manifest.json").read_text())
    _owner_write(Path(manifest["ai_work_root"]) / "raw.fit", b"forbidden")
    with pytest.raises(ValueError, match="work_directory_manifest_invalid"):
        RUNNER.run_weekly_content(root, executable="codex")


def test_weekly_runner_persists_intent_before_the_only_model_call(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        intent = root / "weekly-ai-attempt.pending/attempt-intent.json"
        assert intent.is_file()
        assert stat.S_IMODE(intent.stat().st_mode) == 0o600
        return SimpleNamespace(
            returncode=0, stdout=canonical_json(_weekly_result()).encode(), stderr=b""
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert calls == 1
    assert (root / "weekly-ai-attempt/ai-result.json").is_file()
    assert not (root / "weekly-ai-attempt.pending").exists()
    replay = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert replay["status"] == "succeeded"
    assert replay["reused"] is True
    assert calls == 1


def test_vc009_weekly_runner_binds_isolated_non_git_command_contract(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    manifest = json.loads((root / "candidate-manifest.json").read_text())
    work_root = Path(manifest["ai_work_root"])
    captured_command: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured_command.extend(command)
        assert kwargs["cwd"] == work_root
        assert root.resolve() not in work_root.resolve().parents
        assert work_root.resolve() not in root.resolve().parents
        intent = json.loads(
            (root / "weekly-ai-attempt.pending/attempt-intent.json").read_text()
        )
        assert intent["command_contract"] == {
            "ephemeral": True,
            "ignore_user_config": True,
            "output_schema": "weekly_ai_result_v3_codex",
            "sandbox": "read-only",
            "skip_git_repo_check": True,
        }
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_weekly_result()).encode(),
            stderr=b"",
        )

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "succeeded"
    assert captured_command.count("--skip-git-repo-check") == 1
    assert "--ephemeral" in captured_command
    assert "--ignore-user-config" in captured_command
    assert captured_command[captured_command.index("--sandbox") + 1] == "read-only"
    assert captured_command[captured_command.index("-C") + 1] == str(work_root)
    assert captured_command[-1] == "-"


def test_weekly_runner_failure_is_terminal_and_never_retries(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"transport failed")

    result = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert result["status"] == "blocked"
    assert result["error_code"] == "weekly_model_cli_failed"
    assert calls == 1
    replay = RUNNER.run_weekly_content(root, executable="codex", run_process=fake_run)
    assert replay["status"] == "blocked"
    assert replay["reused"] is True
    assert calls == 1


def test_candidate_private_files_remain_owner_only(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for path in root.rglob("*"):
        metadata = path.lstat()
        assert metadata.st_uid == os.getuid()
        assert not path.is_symlink()
        if path.is_file():
            assert stat.S_IMODE(metadata.st_mode) == 0o600
