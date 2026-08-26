from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


PROMPT = _load(
    "trainlab_coach_utility_v2_prompt_test",
    "skills/training-coach/scripts/create_coach_utility_prompt_v2.py",
)


def _course() -> dict[str, Any]:
    return {
        "date": "2026-08-26",
        "activity_kind": "running",
        "session_type": "sos_threshold",
        "name": "条件性节奏跑",
        "purpose": "在恢复允许时保留一次质量刺激",
        "load_level": "hard",
        "garmin_mapping_status": "candidate",
        "duration_minutes": 45,
        "rpe_min": 6,
        "rpe_max": 7,
        "feel_guidance": "只能说短句但动作稳定",
        "steps": [
            {
                "phase": phase,
                "name": phase,
                "instruction": phase,
                "end_condition": f"{phase}完成",
            }
            for phase in ("warmup", "main", "recovery", "cooldown")
        ],
        "start_gate": ["无持续疼痛且恢复状态允许"],
        "technique_notes": ["动作稳定，不追配速"],
        "downgrade_rule": "恢复不足改为30分钟轻松跑",
        "stop_conditions": ["胸痛、眩晕或异常气短时停止"],
    }


def test_daily_prompt_freezes_original_course_and_downgrade_only() -> None:
    prompt = PROMPT.daily_prompt(
        {
            "schema_version": "daily_evidence_rollup_v1",
            "planned_course_context": "verified_original",
        },
        _course(),
    )
    assert "周计划原课" in prompt
    assert "不得增加剂量、提升强度、移动或补做SOS" in prompt
    assert (
        "无论保持、降级、休息或阻断，effective_course都必须保留warmup、main、recovery、cooldown四个独立阶段"
        in prompt
    )
    assert "不计算或处方心率区间" in prompt
    assert "provider_calls 必须为0" in prompt


def test_daily_prompt_discloses_test_baseline_and_separates_health_from_sleep() -> None:
    prompt = PROMPT.daily_prompt(
        {
            "schema_version": "daily_evidence_rollup_v1",
            "planned_course_context": "test_baseline",
        },
        _course(),
    )
    assert "测试基准课" in prompt
    assert "不得称为历史原课" in prompt
    assert "昨日非睡眠健康事实" in prompt
    assert "昨夜睡眠与恢复" in prompt


def test_daily_prompt_rejects_missing_planned_course_identity() -> None:
    with pytest.raises(ValueError, match="planned_course_context_invalid"):
        PROMPT.daily_prompt({"schema_version": "daily_evidence_rollup_v1"}, _course())


def test_weekly_prompt_forbids_raw_and_requires_sos_and_detail() -> None:
    digest = {
        "schema_version": "weekly_evidence_digest_v1",
        "daily_count": 7,
        "daily_refs": [],
        "provider_calls": 0,
    }
    refs = [
        {"output_id": 85 + index, "sha256": f"{index + 1:x}" * 64} for index in range(7)
    ]
    prompt = PROMPT.weekly_prompt(
        digest,
        {"sha256": "a" * 64, "summary": "跑攀并行"},
        refs,
    )
    assert "绝不回读raw" in prompt
    assert "恰好一节条件性SOS" in prompt
    assert "日期差至少3天" in prompt
    assert "热身、主训练、恢复、放松" in prompt
    assert "建议，不是已完成训练" in prompt
    assert "只能引用顶层daily_input_refs" in prompt
    assert "禁止引用weekly_digest.daily_refs" in prompt
    assert '"output_id": 85' in prompt


def test_weekly_prompt_rejects_missing_v2_daily_input_refs() -> None:
    digest = {
        "schema_version": "weekly_evidence_digest_v1",
        "daily_count": 7,
        "daily_refs": [],
        "provider_calls": 0,
    }
    with pytest.raises(ValueError, match="weekly_daily_input_refs_invalid"):
        PROMPT.weekly_prompt(digest, {"summary": "跑攀并行"}, [])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda refs: refs.__setitem__(0, "not-a-mapping"),
        lambda refs: refs[0].__setitem__("output_id", True),
        lambda refs: refs[0].__setitem__("output_id", []),
        lambda refs: refs[0].__setitem__("sha256", "g" * 64),
        lambda refs: refs[1].__setitem__("output_id", refs[0]["output_id"]),
    ],
    ids=["non-mapping", "bool-id", "unhashable-id", "nonhex-sha", "duplicate-id"],
)
def test_weekly_prompt_rejects_malformed_v2_daily_input_refs(mutate: Any) -> None:
    digest = {
        "schema_version": "weekly_evidence_digest_v1",
        "daily_count": 7,
        "daily_refs": [],
        "provider_calls": 0,
    }
    refs: list[Any] = [
        {"output_id": 85 + index, "sha256": f"{index + 1:x}" * 64} for index in range(7)
    ]
    mutate(refs)
    with pytest.raises(ValueError, match="weekly_daily_input_refs_invalid"):
        PROMPT.weekly_prompt(digest, {"summary": "跑攀并行"}, refs)
