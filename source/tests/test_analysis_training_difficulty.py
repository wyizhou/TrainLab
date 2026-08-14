from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.config import AnalysisConfig
from src.analysis.training_difficulty import (
    race_goal_contract,
    training_control_contracts,
    training_difficulty_contract,
)


def config(
    tmp_path: Path,
    level: int = 2,
    source: str = "default",
    marathon: str | None = None,
    half_marathon: str | None = None,
    goal_source: str = "default",
) -> AnalysisConfig:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    return AnalysisConfig(
        "1",
        tmp_path,
        "Asia/Hong_Kong",
        tmp_path,
        schema,
        schema,
        1_000_000,
        30,
        30,
        7,
        60,
        60,
        tmp_path / "lock",
        tmp_path,
        level,
        source,
        marathon,
        goal_source,
        half_marathon,
        goal_source,
    )


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_contract_exposes_one_auditable_scale_and_all_decision_factors(
    tmp_path: Path, level: int
) -> None:
    contract = training_difficulty_contract(
        config(tmp_path, level, "project_global_config")
    )

    assert contract["key"] == "training_difficulty_contract_v1"
    assert contract["configured_level"] == level
    assert contract["configuration_source"] == "project_global_config"
    assert contract["configuration_key"] == ("project_global.training_difficulty_level")
    assert contract["assessment_factors"] == [
        "training_intensity",
        "total_training_volume",
        "relative_personal_capacity",
        "expected_recovery_cost",
    ]
    assert contract["interpretation"] == "overall_target_not_pace_multiplier"
    assert contract["safety_precedence"].startswith("recovery_")


def test_contract_rejects_invalid_direct_construction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="analysis_training_difficulty_invalid"):
        training_difficulty_contract(config(tmp_path, 6))


def test_every_training_control_is_explicit_and_pace_anchored(
    tmp_path: Path,
) -> None:
    value = config(
        tmp_path,
        3,
        "project_global_config",
        "03:30",
        "01:45",
        "project_global_config",
    )

    difficulty, goals, profile = training_control_contracts(value)

    assert difficulty["configured_level"] == 3
    assert goals == race_goal_contract(value)
    assert goals["configuration_keys"] == [
        "project_global.active_race_goal",
        "project_global.marathon_target_finish_time",
        "project_global.marathon_race_date",
        "project_global.half_marathon_target_finish_time",
        "project_global.half_marathon_race_date",
    ]
    assert goals["marathon"]["configured_finish_time"] == "03:30"
    assert goals["marathon"]["goal_pace_seconds_per_km"] == 299
    assert goals["half_marathon"]["configured_finish_time"] == "01:45"
    assert goals["half_marathon"]["goal_pace_seconds_per_km"] == 299
    assert goals["cross_inference"] == "forbidden"
    assert profile["key"] == "coaching_profile_contract_v1"
    assert profile["profile"]["status"] == "unconfigured"


def test_null_race_goals_remain_explicit_model_context(tmp_path: Path) -> None:
    goals = race_goal_contract(config(tmp_path))

    assert goals["marathon"] == {
        "distance": "marathon",
        "configured_finish_time": None,
        "configuration_source": "default",
        "configured": False,
        "total_seconds": None,
        "goal_pace_seconds_per_km": None,
    }
    assert goals["half_marathon"]["configured_finish_time"] is None
    assert goals["half_marathon"]["configured"] is False


@pytest.mark.parametrize("value", ["3:30", "03:60", "00:00", 210])
def test_race_goal_contract_rejects_invalid_direct_construction(
    tmp_path: Path, value: object
) -> None:
    configured = config(tmp_path)
    object.__setattr__(configured, "marathon_target_finish_time", value)
    with pytest.raises(ValueError, match="analysis_race_goal_invalid"):
        race_goal_contract(configured)
