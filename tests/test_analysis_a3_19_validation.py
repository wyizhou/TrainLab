from __future__ import annotations

from copy import deepcopy
import json

import pytest

from trainlab.analysis.result_validation import (
    AnalysisResultValidationError,
    AnalysisResultValidator,
    ResultValidationExpectation,
)


RUN_KEY = "analysis:subject:revise_plan:41:91:revision-one"
PERIOD = {"start_local_date": "2026-07-20", "end_local_date": "2026-07-26"}
STOP = ["acute_pain", "chest_pain", "fainting_or_dizziness", "unusual_shortness_of_breath"]


def item(index: int, day: str) -> dict[str, object]:
    return {
        "item_index": index, "local_date": day, "activity_kind": "rest",
        "prescription": {
            "activity_kind": "rest", "evidence": ["scheduled_recovery"],
            "uncertainty": "normal_training_uncertainty",
            "daily_activity_allowed": True,
            "recovery_signals": ["recovery_status_reassessed"],
            "seek_professional_help_if": ["concerning_symptom_appears"],
        },
        "rationale_text": "保留恢复空间。", "stop_conditions": STOP,
    }


def running(zone: int = 4) -> dict[str, object]:
    return {
        "activity_kind": "running", "hansons_session_role": "speed", "course_type": "intervals",
        "warmup": "gentle_warmup", "main_set": "structured_intervals",
        "cooldown": "gentle_cooldown", "planned_duration_minutes": 30,
        "total_volume": "interval_session_by_duration", "target_zone": zone,
        "target_bpm_range": None, "prescribed_rpe": 8,
        "talk_test": "short_phrases",
        "work_intervals": [{
            "work_seconds": 60, "recovery_seconds": 60,
            "repetitions": 4, "target_zone": zone,
        }],
        "stop_conditions": STOP, "rationale": "quality_session_appropriate",
    }


DAYS = [f"2026-07-{day:02d}" for day in range(20, 27)]


def expectation() -> ResultValidationExpectation:
    manifest = [
        {"ordinal": 0, "input_role": "plan.current_revision", "source_entity_type": "analysis_artifact", "source_entity_id": "81", "source_revision_id": "1"},
        {"ordinal": 1, "input_role": "reason.accepted", "source_entity_type": "conversation_event", "source_entity_id": "91", "source_revision_id": "91"},
    ]
    bases = {
        day: {"schema_version": "1", "subject_id": 1, "advice_local_date": day, "as_of_utc": "2026-07-22T00:00:00Z", "zone_evidence": [], "safety_signals": [], "quality_sessions": [], "substitution": None}
        for day in DAYS[2:]
    }
    return ResultValidationExpectation(
        run_key=RUN_KEY, mode="revise_plan", subject_id=1,
        target_periods={"plan": PERIOD}, input_manifest=manifest,
        quality_gate={"state": "ready", "blockers": [], "warnings": []},
        safety_request_base={}, weekly_safety_request_bases=bases,
        original_plan={"plan_id": "41", "artifact_id": "81", "period": PERIOD},
        original_plan_items=[item(index, day) for index, day in enumerate(DAYS)],
        reason_event={"reason_event_id": "91", "effective_local_date": "2026-07-22"},
    )


def output() -> dict[str, object]:
    plan = {
        "period": PERIOD, "timezone": "Asia/Singapore", "objective": {}, "constraints": {},
        "original_plan_id": "41", "original_artifact_id": "81", "reason_event_id": "91",
        "effective_local_date": "2026-07-22", "items": [item(index, day) for index, day in enumerate(DAYS[2:])],
    }
    return {
        "schema_version": "1", "run_key": RUN_KEY, "mode": "revise_plan", "subject_id": 1, "status": "accepted",
        "artifacts": [{"artifact_kind": "weekly_training_plan", "period": PERIOD, "structured_content": plan, "user_visible_text": "计划已按已确认的限制调整，保留恢复空间。"}],
        "training_plan": plan,
        "source_usage": [
            {"ordinal": 0, "input_role": "plan.current_revision", "source_entity_id": "81", "source_revision_id": "1"},
            {"ordinal": 1, "input_role": "reason.accepted", "source_entity_id": "91", "source_revision_id": "91"},
        ],
        "quality_disclosures": [], "safety": {"safety_state": "normal", "plan_items": []}, "warnings": [],
    }


def validate(value: dict[str, object], exp: ResultValidationExpectation | None = None):
    return AnalysisResultValidator().validate(json.dumps(value, ensure_ascii=False).encode(), exp or expectation())


def rejects(
    value: dict[str, object], code: str,
    exp: ResultValidationExpectation | None = None,
) -> None:
    with pytest.raises(AnalysisResultValidationError) as caught:
        validate(value, exp)
    assert caught.value.code == code


def test_revision_accepts_only_remaining_suffix_and_normalizes_safety() -> None:
    accepted = validate(output()).result
    assert accepted["training_plan"]["items"][0]["local_date"] == "2026-07-22"
    assert len(accepted["safety"]["plan_items"]) == 5


@pytest.mark.parametrize("mutate,code", [
    (lambda value: value["training_plan"].update(effective_local_date="2026-07-19"), "analysis_result_revision_lineage_mismatch"),
    (lambda value: value["training_plan"]["items"].pop(), "analysis_result_revision_item_cardinality_invalid"),
    (lambda value: value["training_plan"]["items"].__setitem__(0, item(0, "2026-07-21")), "analysis_result_revision_item_sequence_invalid"),
    (lambda value: value["training_plan"]["items"][0].update(activity_kind="climbing", prescription={"activity_kind": "climbing"}), "analysis_result_schema_invalid"),
    (lambda value: value["training_plan"]["items"][0].update(activity_kind="strength", prescription={"activity_kind": "strength"}), "analysis_result_schema_invalid"),
    (lambda value: value["training_plan"].update(original_plan_id="other"), "analysis_result_revision_lineage_mismatch"),
])
def test_revision_dates_items_and_lineage_fail_closed(mutate, code: str) -> None:
    value = deepcopy(output()); mutate(value)
    # Keep the artifact deliberately synchronized: this isolates semantic checks.
    value["artifacts"][0]["structured_content"] = value["training_plan"]
    rejects(value, code)


def test_revision_rejects_historical_item_injection_and_missing_required_source_usage() -> None:
    value = deepcopy(output())
    value["training_plan"]["items"].insert(0, item(0, "2026-07-21"))
    value["artifacts"][0]["structured_content"] = value["training_plan"]
    rejects(value, "analysis_result_revision_item_cardinality_invalid")
    value = output(); value["source_usage"].pop()
    rejects(value, "analysis_result_revision_source_usage_required")


def test_revision_enforces_red_flag_bpm_and_clock_time_rules() -> None:
    exp = expectation()
    exp.weekly_safety_request_bases["2026-07-22"] = {**exp.weekly_safety_request_bases["2026-07-22"], "safety_signals": [{"signal_id": "injury", "kind": "acute_injury", "origin": "user_asserted", "source_revision_id": "injury", "current": True, "active": True, "effective_from_utc": "2026-07-20T00:00:00Z", "expires_at_utc": None}]}
    unsafe = output()
    unsafe["training_plan"]["items"][0].update(
        activity_kind="running",
        prescription={
            "activity_kind": "running", "hansons_session_role": "easy", "course_type": "easy",
            "warmup": "gentle_warmup", "main_set": "talk_test_easy",
            "cooldown": "gentle_cooldown", "planned_duration_minutes": 30,
            "total_volume": "easy_by_duration", "target_zone": None,
            "target_bpm_range": None, "prescribed_rpe": 4,
            "talk_test": "full_sentences", "work_intervals": [],
            "stop_conditions": STOP, "rationale": "recovery_appropriate",
        },
    )
    unsafe["artifacts"][0]["structured_content"] = unsafe["training_plan"]
    protected = validate(unsafe, exp).result
    assert protected["safety"]["safety_state"] == "suspended"
    assert protected["training_plan"]["items"][0]["activity_kind"] == "rest"
    value = output(); value["artifacts"][0]["user_visible_text"] = "建议在 08:00 训练。"
    rejects(value, "analysis_result_training_clock_time_forbidden")
    value = output(); value["training_plan"]["items"][0]["rationale_text"] = "目标 150 bpm。"; value["artifacts"][0]["structured_content"] = value["training_plan"]
    rejects(value, "analysis_result_invented_bpm_forbidden")


def test_revision_checks_high_intensity_across_preserved_prefix_boundary() -> None:
    exp = expectation()
    exp.original_plan_items[1]["activity_kind"] = "running"
    exp.original_plan_items[1]["prescription"] = running()
    zones = [{
        "evidence_id": "running-zones",
        "source_kind": "garmin_sport_zones",
        "source_revision_id": "zones-1",
        "current": True,
        "reliability": "reliable",
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "expires_at_utc": None,
        "sport": "running",
        "heart_rate_bpm": None,
        "measurement_method": "provider_profile",
        "zones": [
            {
                "zone": index,
                "minimum_bpm": 100 + (index - 1) * 10,
                "maximum_bpm": 109 + (index - 1) * 10,
            }
            for index in range(1, 6)
        ],
    }]
    exp.weekly_safety_request_bases["2026-07-22"] = {
        **exp.weekly_safety_request_bases["2026-07-22"],
        "zone_evidence": zones,
    }
    value = output()
    value["training_plan"]["items"][0].update(
        activity_kind="running", prescription=running()
    )
    value["artifacts"][0]["structured_content"] = value["training_plan"]
    rejects(
        value,
        "analysis_result_weekly_high_intensity_frequency_exceeded",
        exp,
    )
