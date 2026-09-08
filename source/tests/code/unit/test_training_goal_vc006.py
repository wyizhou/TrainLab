from __future__ import annotations

import pytest

from skills._shared.fit_weekly.storage import canonical as canonical_json
from skills._shared.scripts.training_goal_v1 import (
    TrainingGoalContractError,
    parse_training_goal_v1,
)


def _goal(intensity: str = "3/5，平衡推进") -> str:
    return f"""# 我的训练目标

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
- 训练强度偏好：{intensity}
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1", 1),
        ("5", 5),
        ("3/5,平衡推进", 3),
        ("3/5； 平衡推进", 3),
        ("3/5，" + "稳" * 200, 3),
    ],
)
def test_vc006_accepts_only_frozen_intensity_forms(source: str, expected: int) -> None:
    result = parse_training_goal_v1(_goal(source))
    assert result["training_preferences"]["intensity_preference"] == expected
    serialized = canonical_json(result)
    assert "平衡推进" not in serialized
    assert "稳" * 20 not in serialized


@pytest.mark.parametrize(
    "source",
    [
        "0",
        "6",
        "3.5",
        "3x",
        "3/5",
        "3/5,",
        "3/5,   ",
        "3/5," + "稳" * 201,
    ],
)
def test_vc006_rejects_non_contract_intensity_forms(source: str) -> None:
    with pytest.raises(
        TrainingGoalContractError, match="training_goal_contract_intensity_invalid"
    ):
        parse_training_goal_v1(_goal(source))


def test_vc006_rejects_field_moved_to_another_section() -> None:
    text = _goal().replace("- 周一：休息\n", "")
    text = text.replace(
        "- 周跑量、跑步频率和长跑距离的长期规则：由近期证据动态判断\n",
        "- 周跑量、跑步频率和长跑距离的长期规则：由近期证据动态判断\n- 周一：休息\n",
    )
    with pytest.raises(
        TrainingGoalContractError, match="training_goal_contract_field_order"
    ):
        parse_training_goal_v1(text)


def test_vc006_rejects_field_reordering_inside_section() -> None:
    text = _goal().replace(
        "- 周一：休息\n- 周二：跑步\n",
        "- 周二：跑步\n- 周一：休息\n",
    )
    with pytest.raises(
        TrainingGoalContractError, match="training_goal_contract_field_order"
    ):
        parse_training_goal_v1(text)


def test_vc006_rejects_heading_with_the_right_fields_in_the_wrong_order() -> None:
    text = _goal()
    text = text.replace("## 当前目标", "## TEMP", 1)
    text = text.replace("## 每周可训练安排", "## 当前目标", 1)
    text = text.replace("## TEMP", "## 每周可训练安排", 1)
    with pytest.raises(
        TrainingGoalContractError, match="training_goal_contract_heading_mismatch"
    ):
        parse_training_goal_v1(text)
