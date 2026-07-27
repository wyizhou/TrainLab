"""Shared deterministic contract for the project-wide training difficulty."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .config import AnalysisConfig


_LEVELS: Mapping[int, Mapping[str, Any]] = {
    1: {"label": "simple", "relative_scale": 1.0, "examples": ["recovery"]},
    2: {
        "label": "easy",
        "relative_scale": 1.5,
        "examples": ["easy", "base_low"],
    },
    3: {
        "label": "moderate",
        "relative_scale": 2.0,
        "examples": ["garmin_coach_typical", "base", "ordinary_long"],
    },
    4: {
        "label": "moderately_hard",
        "relative_scale": 3.0,
        "examples": ["tempo", "threshold", "race_build"],
    },
    5: {
        "label": "hard",
        "relative_scale": 4.0,
        "examples": ["vo2_max_intervals", "sprints"],
    },
}
_FINISH_TIME = re.compile(r"^(?P<hours>\d{2}):(?P<minutes>[0-5]\d)$")


def training_difficulty_contract(config: AnalysisConfig) -> dict[str, Any]:
    """Return one route-independent, auditable model-input contract."""

    level = config.training_difficulty_level
    if isinstance(level, bool) or not isinstance(level, int) or level not in _LEVELS:
        raise ValueError("analysis_training_difficulty_invalid")
    source = config.training_difficulty_source
    if source not in {"default", "project_global_config"}:
        raise ValueError("analysis_training_difficulty_source_invalid")
    return {
        "key": "training_difficulty_contract_v1",
        "algorithm_version": "training-difficulty-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "configured_level": level,
        "configured_level_definition": dict(_LEVELS[level]),
        "valid_range": {"minimum": 1, "maximum": 5},
        "default_level": 2,
        "configuration_source": source,
        "configuration_key": "project_global.training_difficulty_level",
        "assessment_factors": [
            "training_intensity",
            "total_training_volume",
            "relative_personal_capacity",
            "expected_recovery_cost",
        ],
        "interpretation": "overall_target_not_pace_multiplier",
        "session_variation": "allowed_for_recovery_and_periodization",
        "safety_precedence": "recovery_and_hard_safety_rules_override_target",
    }


def _race_goal(
    value: str | None,
    source: str,
    *,
    distance_key: str,
    distance_km: float,
) -> dict[str, Any]:
    if source not in {"default", "project_global_config"}:
        raise ValueError("analysis_race_goal_source_invalid")
    total_seconds: int | None = None
    pace_seconds_per_km: int | None = None
    if value is not None:
        match = _FINISH_TIME.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise ValueError("analysis_race_goal_invalid")
        total_seconds = (
            int(match.group("hours")) * 60 + int(match.group("minutes"))
        ) * 60
        if total_seconds <= 0:
            raise ValueError("analysis_race_goal_invalid")
        pace_seconds_per_km = round(total_seconds / distance_km)
    return {
        "distance": distance_key,
        "configured_finish_time": value,
        "configuration_source": source,
        "configured": value is not None,
        "total_seconds": total_seconds,
        "goal_pace_seconds_per_km": pace_seconds_per_km,
    }


def race_goal_contract(config: AnalysisConfig) -> dict[str, Any]:
    """Expose both race goals on every analysis route, including explicit nulls."""

    return {
        "key": "race_goal_contract_v1",
        "algorithm_version": "race-goal-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "configuration_keys": [
            "project_global.marathon_target_finish_time",
            "project_global.half_marathon_target_finish_time",
        ],
        "marathon": _race_goal(
            config.marathon_target_finish_time,
            config.marathon_target_finish_time_source,
            distance_key="marathon",
            distance_km=42.195,
        ),
        "half_marathon": _race_goal(
            config.half_marathon_target_finish_time,
            config.half_marathon_target_finish_time_source,
            distance_key="half_marathon",
            distance_km=21.0975,
        ),
        "cross_inference": "forbidden",
        "cycle_assumption": "goal_does_not_imply_active_race_cycle",
        "usage": "pace_anchor_only_when_route_and_evidence_support_it",
        "safety_precedence": "recovery_and_hard_safety_rules_override_goal",
    }


def training_control_contracts(config: AnalysisConfig) -> tuple[dict[str, Any], ...]:
    """Return every user-controlled analysis variable for every model route."""

    return training_difficulty_contract(config), race_goal_contract(config)
