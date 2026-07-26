from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trainlab.analysis.result_validation import (
    AnalysisResultValidationError,
    AnalysisResultValidator,
    ResultValidationExpectation,
)
from trainlab.analysis.safety_rules import evaluate_training_safety


RUN_KEY = "analysis:1:daily:2026-07-24:fixture"
SUMMARY = {"start_local_date": "2026-07-23", "end_local_date": "2026-07-23"}
ADVICE = {"start_local_date": "2026-07-24", "end_local_date": "2026-07-24"}
STOP = ["acute_pain", "chest_pain", "fainting_or_dizziness", "unusual_shortness_of_breath"]


def safety_request_base(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
            "schema_version": "1",
            "subject_id": 1,
            "advice_local_date": "2026-07-24",
            "as_of_utc": "2026-07-24T00:00:00Z",
            "zone_evidence": [],
            "safety_signals": [],
            "quality_sessions": [],
            "substitution": None,
    }
    value.update(changes)
    return value


def candidate(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "activity_kind": "running",
        "course_type": "easy",
        "warmup": "gentle_warmup",
        "main_set": "talk_test_easy",
        "cooldown": "gentle_cooldown",
        "planned_duration_minutes": 30,
        "total_volume": "easy_by_duration",
        "target_zone": None,
        "target_bpm_range": None,
        "prescribed_rpe": 4,
        "talk_test": "full_sentences",
        "work_intervals": [],
        "stop_conditions": STOP,
        "rationale": "recovery_appropriate",
    }
    value.update(changes)
    return value


def safety(item: dict[str, object] | None = None, **changes: object) -> dict[str, object]:
    return evaluate_training_safety(
        {**safety_request_base(**changes), "primary_items": [item or candidate()]}
    )


def expected() -> ResultValidationExpectation:
    return ResultValidationExpectation(
        run_key=RUN_KEY,
        mode="daily",
        subject_id=1,
        target_periods={"summary": SUMMARY, "advice": ADVICE},
        input_manifest=[
            {
                "ordinal": 0,
                "input_role": "health",
                "source_entity_id": "daily:2026-07-23",
                "source_revision_id": "health-revision-1",
            }
        ],
        quality_gate={"state": "ready", "blockers": [], "warnings": []},
        safety_request_base=safety_request_base(),
    )


def output(item: dict[str, object] | None = None) -> dict[str, object]:
    proposed = item or candidate()
    evidence = safety(proposed)
    primary = evidence["primary_items"][0]
    return {
        "schema_version": "1",
        "run_key": RUN_KEY,
        "mode": "daily",
        "subject_id": 1,
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "daily_summary",
                "period": SUMMARY,
                "structured_content": {"summary": "恢复情况稳定"},
                "user_visible_text": "昨日恢复情况稳定，已记录健康与运动数据。",
            },
            {
                "artifact_kind": "daily_training_advice",
                "period": ADVICE,
                "structured_content": {"primary_item": proposed},
                "user_visible_text": "今日建议轻松跑，保持能完整说话的轻松感觉；如有急性疼痛请停止。",
            },
        ],
        "training_plan": None,
        "source_usage": [
            {
                "ordinal": 0,
                "input_role": "health",
                "source_entity_id": "daily:2026-07-23",
                "source_revision_id": "health-revision-1",
            }
        ],
        "quality_disclosures": [],
        "safety": {"safety_state": evidence["safety_state"], "primary_item": primary},
        "warnings": [],
    }


def validate(value: dict[str, object], exp: ResultValidationExpectation | None = None):
    return AnalysisResultValidator().validate(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), exp or expected()
    )


def code(value: dict[str, object], expected_code: str) -> None:
    with pytest.raises(AnalysisResultValidationError) as caught:
        validate(value)
    assert caught.value.code == expected_code
    assert "昨日" not in str(caught.value)


def test_schema_is_strict_and_a_valid_daily_result_returns_only_typed_value() -> None:
    schema = json.loads((Path(__file__).parents[1] / "harness/schemas/analysis_result.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    accepted = validate(output())
    assert accepted.result["run_key"] == RUN_KEY
    assert set(accepted.result) == {"schema_version", "run_key", "mode", "subject_id", "status", "artifacts", "training_plan", "source_usage", "quality_disclosures", "safety", "warnings"}


def test_non_json_and_unknown_fields_are_rejected_without_echoing_output() -> None:
    with pytest.raises(AnalysisResultValidationError) as caught:
        AnalysisResultValidator().validate(b"not json", expected())
    assert caught.value.as_record() == {"code": "analysis_result_json_invalid", "path": "root"}
    changed = output()
    changed["send_email"] = True
    code(changed, "analysis_result_schema_invalid")


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda value: value.update(run_key="other"), "analysis_result_run_key_mismatch"),
        (lambda value: value.update(subject_id=2), "analysis_result_subject_mismatch"),
        (lambda value: value["artifacts"].pop(), "analysis_result_daily_cardinality_invalid"),
        (lambda value: value["artifacts"][0].update(period=ADVICE), "analysis_result_date_mismatch"),
        (lambda value: value["source_usage"][0].update(source_revision_id="invented"), "analysis_result_source_usage_invalid"),
    ],
)
def test_identity_cardinality_dates_and_manifest_bindings_fail_closed(mutate, expected_code: str) -> None:
    changed = deepcopy(output())
    mutate(changed)
    code(changed, expected_code)


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("系统已发送邮件。", "analysis_result_delivery_claim_forbidden"),
        ("这是医学诊断。", "analysis_result_medical_diagnosis_forbidden"),
        ("今天 RPE 10 全力冲刺。", "analysis_result_all_out_forbidden"),
        ("请查看 /Users/example/private。", "analysis_result_internal_path_forbidden"),
        ("跑 3 miles。", "analysis_result_imperial_unit_forbidden"),
        ("Today is easy.", "analysis_result_simplified_chinese_required"),
    ],
)
def test_unsafe_visible_text_is_rejected(text: str, expected_code: str) -> None:
    changed = output()
    changed["artifacts"][0]["user_visible_text"] = text
    code(changed, expected_code)


def test_simplified_training_plan_wording_passes_but_traditional_wording_fails() -> None:
    simplified = output()
    simplified["artifacts"][1]["user_visible_text"] = "今日训练方案为轻松跑，保持能完整说话的感觉。"
    assert validate(simplified).result["status"] == "accepted"

    traditional = output()
    traditional["artifacts"][1]["user_visible_text"] = "今日訓練計畫為輕鬆跑。"
    code(traditional, "analysis_result_simplified_chinese_required")


def test_fallback_hr_evidence_rejects_invented_bpm_and_changed_primary_item() -> None:
    invented = output()
    invented["artifacts"][1]["user_visible_text"] = "今日轻松跑，目标 150 bpm。"
    code(invented, "analysis_result_invented_bpm_forbidden")
    changed = output()
    changed["artifacts"][1]["structured_content"]["primary_item"]["prescribed_rpe"] = 10
    code(changed, "analysis_result_safety_candidate_rejected")


def test_source_backed_observed_bpm_is_allowed_only_in_completed_day_summary() -> None:
    value = output()
    value["artifacts"][0]["user_visible_text"] = (
        "昨日 Garmin 记录的静息心率为 52 bpm；该数值仅用于健康摘要。"
    )
    assert validate(value).result["status"] == "accepted"


def test_quality_disclosures_must_equal_actual_gate_warnings() -> None:
    value = output()
    exp = expected()
    object.__setattr__(
        exp,
        "quality_gate",
        {"state": "ready_with_warnings", "blockers": [], "warnings": [{"code": "quality_warning", "entity": "sleep", "summary": "safe"}]},
    )
    with pytest.raises(AnalysisResultValidationError, match="quality_disclosure_mismatch"):
        validate(value, exp)
    value["quality_disclosures"] = [{"code": "quality_warning", "entity": "sleep"}]
    assert validate(value, exp).result["mode"] == "daily"


def test_candidate_is_evaluated_by_a3_09_before_acceptance() -> None:
    assert validate(output(candidate())).result["status"] == "accepted"

    rpe_ten = output()
    primary = rpe_ten["artifacts"][1]["structured_content"]["primary_item"]
    primary["prescribed_rpe"] = 10
    code(rpe_ten, "analysis_result_safety_candidate_rejected")

    injured_base = safety_request_base(
        safety_signals=[
            {
                "signal_id": "acute-injury",
                "kind": "acute_injury",
                "origin": "user_asserted",
                "source_revision_id": "injury-revision",
                "current": True,
                "active": True,
                "effective_from_utc": "2026-07-23T00:00:00Z",
                "expires_at_utc": None,
            }
        ]
    )
    with pytest.raises(AnalysisResultValidationError) as caught:
        AnalysisResultValidator().validate(
            json.dumps(output(), ensure_ascii=False).encode(),
            ResultValidationExpectation(
                RUN_KEY, "daily", 1, {"summary": SUMMARY, "advice": ADVICE},
                expected().input_manifest, {"state": "ready", "blockers": [], "warnings": []}, injured_base,
            ),
        )
    assert caught.value.code == "analysis_result_safety_candidate_rejected"


def test_conservative_a3_09_normalization_is_owned_by_host_not_model() -> None:
    unsafe = candidate(course_type="intervals", target_zone=4, prescribed_rpe=8)
    value = output(unsafe)
    # The model fields are not authoritative. The host applies deterministic
    # fallback normalization to both persisted candidate locations.
    value["safety"] = {"safety_state": "normal", "primary_item": unsafe}
    accepted = validate(value).result
    normalized = accepted["safety"]["primary_item"]
    assert normalized["course_type"] == "easy"
    assert normalized["target_zone"] is None
    assert normalized["prescribed_rpe"] <= 4
    assert (
        accepted["artifacts"][1]["structured_content"]["primary_item"]
        == normalized
    )
