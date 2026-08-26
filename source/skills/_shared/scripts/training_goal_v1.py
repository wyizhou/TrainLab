#!/usr/bin/env python3
"""Parse the owner-edited training goal into a bounded business contract."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from skills._shared.scripts.schema_validation import validate_payload

SCHEMA_VERSION = "training_goal_v1"
EXPECTED_HEADINGS = (
    "# 我的训练目标",
    "## 当前目标",
    "## 每周可训练安排",
    "## 训练偏好",
    "## 身体限制与恢复关注",
    "## 临时要求",
)
SECTION_FIELDS = (
    (
        "## 当前目标",
        (
            "比赛目标与日期",
            "当前训练重点",
            "周跑量、跑步频率和长跑距离的长期规则",
        ),
    ),
    (
        "## 每周可训练安排",
        ("周一", "周二", "周三", "周四", "周五", "周六", "周日"),
    ),
    (
        "## 训练偏好",
        (
            "训练强度偏好",
            "进阶方式",
            "硬负荷上限与最小间隔",
            "错过课程与距离/强度调整规则",
        ),
    ),
    (
        "## 身体限制与恢复关注",
        (
            "已知伤病、疼痛或其他限制",
            "需要特别关注的恢复信号",
            "出现红旗时的处理偏好",
        ),
    ),
    (
        "## 临时要求",
        ("当前长期目标之外的临时调整", "临时调整的有效周期"),
    ),
)
FIELD_BINDINGS = {
    "比赛目标与日期": ("current_goal", "competition_goal_and_date"),
    "当前训练重点": ("current_goal", "training_focus"),
    "周跑量、跑步频率和长跑距离的长期规则": (
        "current_goal",
        "long_term_load_rule",
    ),
    "周一": ("weekly_availability", "monday"),
    "周二": ("weekly_availability", "tuesday"),
    "周三": ("weekly_availability", "wednesday"),
    "周四": ("weekly_availability", "thursday"),
    "周五": ("weekly_availability", "friday"),
    "周六": ("weekly_availability", "saturday"),
    "周日": ("weekly_availability", "sunday"),
    "训练强度偏好": ("training_preferences", "intensity_preference"),
    "进阶方式": ("training_preferences", "progression_rule"),
    "硬负荷上限与最小间隔": ("training_preferences", "hard_load_rule"),
    "错过课程与距离/强度调整规则": (
        "training_preferences",
        "missed_session_rule",
    ),
    "已知伤病、疼痛或其他限制": ("constraints", "known_limitations"),
    "需要特别关注的恢复信号": ("constraints", "recovery_signals"),
    "出现红旗时的处理偏好": ("constraints", "red_flag_preference"),
    "当前长期目标之外的临时调整": (
        "temporary_adjustment",
        "adjustment",
    ),
    "临时调整的有效周期": ("temporary_adjustment", "valid_period"),
}
INTENSITY_PLAIN_PATTERN = re.compile(r"^[1-5]$")
INTENSITY_ANNOTATED_PATTERN = re.compile(r"^([1-5])/5[,;][ \t]*(\S(?:.*\S)?)$")


class TrainingGoalContractError(ValueError):
    """The private goal file does not match the frozen public template."""


def _expected_line_contract() -> tuple[tuple[str, str], ...]:
    expected: list[tuple[str, str]] = [("heading", EXPECTED_HEADINGS[0])]
    for heading, labels in SECTION_FIELDS:
        expected.append(("heading", heading))
        expected.extend(("field", label) for label in labels)
    return tuple(expected)


def _parse_intensity(value: str) -> int:
    if INTENSITY_PLAIN_PATTERN.fullmatch(value):
        return int(value)
    match = INTENSITY_ANNOTATED_PATTERN.fullmatch(value)
    if match is None or not 1 <= len(match.group(2)) <= 200:
        raise TrainingGoalContractError("training_goal_contract_intensity_invalid")
    return int(match.group(1))


def parse_training_goal_v1(text: str) -> dict[str, Any]:
    """Parse the frozen title, five sections and 19 ordered goal fields."""

    if not isinstance(text, str) or not text.strip():
        raise TrainingGoalContractError("training_goal_contract_empty")
    expected = _expected_line_contract()
    position = 0
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = unicodedata.normalize("NFKC", raw_line).strip()
        if not line:
            continue
        if position >= len(expected):
            raise TrainingGoalContractError("training_goal_contract_extra_text")
        expected_kind, expected_value = expected[position]
        if line.startswith("#"):
            if expected_kind != "heading" or line != expected_value:
                raise TrainingGoalContractError(
                    "training_goal_contract_heading_mismatch"
                )
            position += 1
            continue
        if not line.startswith("- "):
            raise TrainingGoalContractError("training_goal_contract_extra_text")
        field_text = line[2:]
        if ":" not in field_text:
            raise TrainingGoalContractError("training_goal_contract_field_invalid")
        label, value = (part.strip() for part in field_text.split(":", 1))
        if label not in FIELD_BINDINGS:
            raise TrainingGoalContractError("training_goal_contract_field_unknown")
        if expected_kind != "field" or label != expected_value:
            raise TrainingGoalContractError("training_goal_contract_field_order")
        if label in values:
            raise TrainingGoalContractError("training_goal_contract_field_duplicate")
        if not value:
            raise TrainingGoalContractError("training_goal_contract_value_empty")
        values[label] = value
        position += 1
    if position != len(expected):
        next_kind = expected[position][0]
        error = (
            "training_goal_contract_heading_mismatch"
            if next_kind == "heading"
            else "training_goal_contract_field_set_mismatch"
        )
        raise TrainingGoalContractError(error)
    if set(values) != set(FIELD_BINDINGS):
        raise TrainingGoalContractError("training_goal_contract_field_set_mismatch")
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_goal": {},
        "weekly_availability": {},
        "training_preferences": {},
        "constraints": {},
        "temporary_adjustment": {},
    }
    for label, (section, field) in FIELD_BINDINGS.items():
        parsed_value: str | int = values[label]
        if label == "训练强度偏好":
            parsed_value = _parse_intensity(values[label])
        result[section][field] = parsed_value
    errors = validate_payload(result, SCHEMA_VERSION)
    if errors:
        raise TrainingGoalContractError(
            "training_goal_contract_schema_invalid:" + ",".join(errors[:3])
        )
    return result
