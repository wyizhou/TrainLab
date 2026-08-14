import json

from jsonschema import Draft202012Validator

from src.analysis.result_validation import COURSE_VALIDATOR, _course_contract_for_item
from src.resources import resource_path


def _validate(payload: dict[str, object]) -> None:
    schema = json.loads(
        resource_path("harness/schemas/course_contract_v2.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_course_contract_schema_accepts_climbing_only_as_unsupported_garmin():
    payload = {
        "schema_version": "2",
        "local_date": "2026-08-13",
        "activity_kind": "climbing",
        "course_name": "技术攀岩恢复课",
        "purpose": "控制负荷并保留恢复余量",
        "dose": {"distance_m": None, "duration_seconds": 3600, "hard_session": False},
        "steps": [
            {
                "name": "热身与技术",
                "end_condition": "duration_seconds",
                "end_value": 3600,
            }
        ],
        "targets": {
            "pace_seconds_per_km": None,
            "heart_rate_bpm": None,
            "rpe": {"min": 2, "max": 4},
            "talk_test": "可完整对话",
        },
        "guardrails": ["不做极限尝试"],
        "load_level": "moderate",
        "recovery_cost": 24,
        "degradation_rule": "睡眠不足时改为休息",
        "stop_conditions": ["急性疼痛立即停止"],
        "garmin_mapping": "unsupported_skip",
    }
    _validate(payload)


def test_course_contract_schema_accepts_running_and_zero_dose_rest():
    common = {
        "schema_version": "2",
        "local_date": "2026-08-13",
        "course_name": "中性夹具课程",
        "purpose": "验证合同边界",
        "steps": [
            {"name": "整段", "end_condition": "duration_seconds", "end_value": 0}
        ],
        "targets": {
            "pace_seconds_per_km": None,
            "heart_rate_bpm": None,
            "rpe": None,
            "talk_test": None,
        },
        "guardrails": [],
        "load_level": "recovery",
        "recovery_cost": 0,
        "degradation_rule": "如有不适则停止。",
        "stop_conditions": ["acute_pain"],
    }
    _validate(
        {
            **common,
            "activity_kind": "running",
            "dose": {"distance_m": None, "duration_seconds": 1, "hard_session": False},
            "garmin_mapping": "requires_review",
        }
    )
    _validate(
        {
            **common,
            "activity_kind": "rest",
            "dose": {"distance_m": 0, "duration_seconds": 0, "hard_session": False},
            "garmin_mapping": "unsupported_skip",
        }
    )


def test_host_course_contract_preserves_dose_pace_and_phases():
    value = _course_contract_for_item(
        {
            "activity_kind": "running",
            "course_name": "中性节奏跑",
            "planned_duration_minutes": 50,
            "planned_distance_m": 5000,
            "pace_seconds_per_km": {"min": 300, "max": 330},
            "hansons_session_role": "easy",
            "prescribed_rpe": 4,
        },
        local_date="2026-08-13",
    )
    assert value is not None
    assert not list(COURSE_VALIDATOR.iter_errors(value))
    assert value["dose"]["distance_m"] == 5000.0
    assert value["targets"]["pace_seconds_per_km"] == {"min": 300, "max": 330}
    assert [step["name"] for step in value["steps"]] == ["热身", "主训练", "冷身"]
