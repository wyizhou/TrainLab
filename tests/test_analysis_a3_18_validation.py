from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from trainlab.analysis.result_validation import (
    AnalysisResultValidationError,
    AnalysisResultValidator,
    ResultValidationExpectation,
)

RUN_KEY = "analysis:1:weekly:2026-07-26:fixture"
REVIEW = {"start_local_date": "2026-07-19", "end_local_date": "2026-07-25"}
PLAN = {"start_local_date": "2026-07-26", "end_local_date": "2026-08-01"}
STOP = [
    "acute_pain",
    "chest_pain",
    "fainting_or_dizziness",
    "unusual_shortness_of_breath",
]


def rest() -> dict[str, object]:
    return {
        "activity_kind": "rest",
        "evidence": ["scheduled_recovery"],
        "uncertainty": "normal_training_uncertainty",
        "daily_activity_allowed": True,
        "recovery_signals": ["recovery_status_reassessed"],
        "seek_professional_help_if": ["concerning_symptom_appears"],
    }


def running(*, zone: int | None = None) -> dict[str, object]:
    return {
        "activity_kind": "running",
        "hansons_session_role": "speed" if zone else "easy",
        "course_type": "intervals" if zone else "easy",
        "warmup": "gentle_warmup",
        "main_set": "structured_intervals" if zone else "talk_test_easy",
        "cooldown": "gentle_cooldown",
        "planned_duration_minutes": 40,
        "total_volume": "interval_session_by_duration" if zone else "easy_by_duration",
        "target_zone": zone,
        "target_bpm_range": None,
        "prescribed_rpe": 8 if zone else 4,
        "talk_test": "short_phrases" if zone else "full_sentences",
        "work_intervals": (
            []
            if zone is None
            else [
                {
                    "work_seconds": 60,
                    "recovery_seconds": 60,
                    "repetitions": 4,
                    "target_zone": zone,
                }
            ]
        ),
        "stop_conditions": STOP,
        "rationale": "quality_session_appropriate" if zone else "recovery_appropriate",
    }


def base(day: str, *, red_flag: bool = False, zones: bool = False) -> dict[str, object]:
    zone_evidence: list[object] = []
    if zones:
        zone_evidence = [
            {
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
            }
        ]
    signals: list[object] = []
    if red_flag:
        signals = [
            {
                "signal_id": "injury",
                "kind": "acute_injury",
                "origin": "user_asserted",
                "source_revision_id": "injury-1",
                "current": True,
                "active": True,
                "effective_from_utc": "2026-07-01T00:00:00Z",
                "expires_at_utc": None,
            }
        ]
    return {
        "schema_version": "1",
        "subject_id": 1,
        "advice_local_date": day,
        "as_of_utc": f"{day}T00:00:00Z",
        "zone_evidence": zone_evidence,
        "safety_signals": signals,
        "quality_sessions": [],
        "substitution": None,
    }


def plan_item(
    index: int, prescription: dict[str, object] | None = None
) -> dict[str, object]:
    day = (
        date.fromisoformat(PLAN["start_local_date"]) + timedelta(days=index)
    ).isoformat()
    candidate = prescription or rest()
    return {
        "item_index": index,
        "local_date": day,
        "activity_kind": candidate["activity_kind"],
        "prescription": candidate,
        "rationale_text": "根据本周恢复安排。",
        "stop_conditions": [],
    }


def output(
    *,
    prior: dict[str, str] | None = None,
    prescriptions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    prior = prior or {"summary": "no_prior_artifact", "plan": "no_prior_artifact"}
    items = [
        plan_item(index, prescriptions[index] if prescriptions else None)
        for index in range(7)
    ]
    training_plan = {
        "period": PLAN,
        "timezone": "Asia/Hong_Kong",
        "objective": {"focus": "恢复"},
        "constraints": {"clock_time_forbidden": True},
        "prior_artifact_state": prior,
        "items": items,
    }
    return {
        "schema_version": "1",
        "run_key": RUN_KEY,
        "mode": "weekly",
        "subject_id": 1,
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "weekly_summary",
                "period": REVIEW,
                "structured_content": {
                    "prior_artifact_state": prior,
                    "summary": "本周恢复稳定。",
                },
                "user_visible_text": "本周健康、睡眠和训练数据已完成复盘，恢复总体稳定。",
            },
            {
                "artifact_kind": "weekly_training_plan",
                "period": PLAN,
                "structured_content": deepcopy(training_plan),
                "user_visible_text": "未来七天以恢复和循序渐进为主，按身体感受调整。",
            },
        ],
        "training_plan": training_plan,
        "source_usage": [
            {
                "ordinal": 0,
                "input_role": "health",
                "source_entity_id": "weekly:2026-07-19",
                "source_revision_id": "health-1",
            }
        ],
        "quality_disclosures": [],
        "safety": {
            "safety_state": "normal",
            "plan_items": [
                {
                    "item_index": item["item_index"],
                    "local_date": item["local_date"],
                    "safety_state": "normal",
                    "primary_item": item["prescription"],
                }
                for item in items
            ],
        },
        "warnings": [],
    }


def expectation(
    *, prior: dict[str, str] | None = None, red_flag: bool = False, zones: bool = False
) -> ResultValidationExpectation:
    days = [
        (
            date.fromisoformat(PLAN["start_local_date"]) + timedelta(days=index)
        ).isoformat()
        for index in range(7)
    ]
    return ResultValidationExpectation(
        run_key=RUN_KEY,
        mode="weekly",
        subject_id=1,
        target_periods={"review": REVIEW, "plan": PLAN},
        input_manifest=[
            {
                "ordinal": 0,
                "input_role": "health",
                "source_entity_id": "weekly:2026-07-19",
                "source_revision_id": "health-1",
            }
        ],
        quality_gate={"state": "ready", "blockers": [], "warnings": []},
        safety_request_base={},
        weekly_safety_request_bases={
            day: base(day, red_flag=red_flag, zones=zones) for day in days
        },
        prior_artifact_state=prior
        or {"summary": "no_prior_artifact", "plan": "no_prior_artifact"},
    )


def validate(value: dict[str, object], exp: ResultValidationExpectation | None = None):
    return AnalysisResultValidator().validate(
        json.dumps(value, ensure_ascii=False).encode(), exp or expectation()
    )


def code(
    value: dict[str, object],
    expected_code: str,
    exp: ResultValidationExpectation | None = None,
) -> None:
    with pytest.raises(AnalysisResultValidationError) as caught:
        validate(value, exp)
    assert caught.value.code == expected_code


def test_weekly_first_run_has_exact_windows_plan_items_and_host_safety_normalization() -> (
    None
):
    accepted = validate(output()).result
    plan = accepted["training_plan"]
    assert plan["prior_artifact_state"] == {
        "summary": "no_prior_artifact",
        "plan": "no_prior_artifact",
    }
    assert [item["item_index"] for item in plan["items"]] == list(range(7))
    assert [item["local_date"] for item in plan["items"]] == [
        (
            date.fromisoformat(PLAN["start_local_date"]) + timedelta(days=index)
        ).isoformat()
        for index in range(7)
    ]
    weekly_artifact = next(
        item
        for item in accepted["artifacts"]
        if item["artifact_kind"] == "weekly_training_plan"
    )
    assert weekly_artifact["structured_content"] == plan
    assert (
        accepted["safety"]["plan_items"][0]["primary_item"]
        == plan["items"][0]["prescription"]
    )


def test_weekly_prior_artifact_state_is_host_canonicalized() -> None:
    value = output()
    wrong = {"summary": "available", "plan": "available"}
    value["artifacts"][0]["structured_content"]["prior_artifact_state"] = wrong
    value["training_plan"]["prior_artifact_state"] = wrong
    value["artifacts"][1]["structured_content"] = deepcopy(value["training_plan"])
    accepted = validate(value).result
    expected_state = {
        "summary": "no_prior_artifact",
        "plan": "no_prior_artifact",
    }
    assert accepted["training_plan"]["prior_artifact_state"] == expected_state
    assert (
        accepted["artifacts"][0]["structured_content"]["prior_artifact_state"]
        == expected_state
    )


def test_weekly_duplicate_activity_kind_is_host_canonicalized() -> None:
    value = output()
    value["training_plan"]["items"][0]["activity_kind"] = "running"
    value["artifacts"][1]["structured_content"] = deepcopy(value["training_plan"])
    accepted = validate(value).result
    assert accepted["training_plan"]["items"][0]["activity_kind"] == "rest"


def test_weekly_plan_artifact_uses_the_canonical_top_level_plan() -> None:
    value = output()
    value["artifacts"][1]["structured_content"] = {}
    accepted = validate(value).result
    assert accepted["artifacts"][1]["structured_content"] == accepted["training_plan"]


def test_weekly_user_visible_text_cannot_narrate_raw_device_fields() -> None:
    value = output()
    value["artifacts"][0]["user_visible_text"] = "本周 Body Battery 有多次变化。"
    code(value, "analysis_result_raw_device_narration_forbidden")


@pytest.mark.parametrize("shape", ["weekly", "plan_revision"])
def test_regeneration_validates_complete_weekly_and_plan_revision_shapes(
    shape: str,
) -> None:
    run_key = "analysis:1:regenerate:42:fixture"
    value = output()
    value["run_key"] = run_key
    value["mode"] = "regenerate"
    if shape == "plan_revision":
        value["artifacts"] = [value["artifacts"][1]]
    value["source_usage"] = [
        {
            "ordinal": 0,
            "input_role": "regeneration.source_artifact",
            "source_entity_id": "42",
            "source_revision_id": "3",
        }
    ]
    source_manifest = [
        {
            "ordinal": 0,
            "input_role": "regeneration.source_artifact",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "42",
            "source_revision_id": "3",
        }
    ]
    exp = replace(
        expectation(),
        run_key=run_key,
        mode="regenerate",
        input_manifest=source_manifest,
        regeneration_source_shape=shape,
        regeneration_source_artifact_id="42",
    )
    accepted = validate(value, exp).result
    assert accepted["mode"] == "regenerate"
    assert len(accepted["training_plan"]["items"]) == 7


@pytest.mark.parametrize(
    "mutate,expected_code",
    [
        (
            lambda value: value["training_plan"]["items"].pop(),
            "analysis_result_schema_invalid",
        ),
        (
            lambda value: value["training_plan"]["items"][0].update(stop_conditions={}),
            "analysis_result_schema_invalid",
        ),
        (
            lambda value: value["training_plan"]["items"][0].update(
                activity_kind="climbing", prescription={"activity_kind": "climbing"}
            ),
            "analysis_result_schema_invalid",
        ),
        (
            lambda value: value["training_plan"]["items"][0].update(
                activity_kind="strength", prescription={"activity_kind": "strength"}
            ),
            "analysis_result_schema_invalid",
        ),
        (
            lambda value: value["training_plan"]["items"].__setitem__(
                1, {**value["training_plan"]["items"][1], "item_index": 0}
            ),
            "analysis_result_weekly_item_sequence_invalid",
        ),
    ],
)
def test_weekly_shape_and_prior_state_fail_closed(mutate, expected_code: str) -> None:
    value = output()
    mutate(value)
    code(value, expected_code)


def test_available_prior_state_is_required_in_both_artifacts() -> None:
    prior = {"summary": "available", "plan": "available"}
    value = output(prior=prior)
    exp = expectation(prior=prior)
    code(
        value,
        "analysis_result_weekly_prior_source_invalid",
        exp,
    )
    prior_inputs = [
        *exp.input_manifest,
        {
            "ordinal": 1,
            "input_role": "artifact.prior_model_output",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "previous-summary",
            "source_revision_id": "previous-summary-r1",
            "source_window": {
                "start_local_date": "2026-07-12",
                "end_local_date": "2026-07-18",
            },
        },
        {
            "ordinal": 2,
            "input_role": "plan.current_revision",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "previous-plan",
            "source_revision_id": "previous-plan-r1",
            "source_window": {
                "start_local_date": "2026-07-19",
                "end_local_date": "2026-07-25",
            },
        },
    ]
    object.__setattr__(exp, "input_manifest", prior_inputs)
    value["source_usage"].extend(
        [
            {
                "ordinal": row["ordinal"],
                "input_role": row["input_role"],
                "source_entity_id": row["source_entity_id"],
                "source_revision_id": row["source_revision_id"],
            }
            for row in prior_inputs[1:]
        ]
    )
    assert validate(value, exp).result["mode"] == "weekly"


def test_available_prior_sources_must_both_be_used() -> None:
    prior = {"summary": "available", "plan": "available"}
    value = output(prior=prior)
    exp = expectation(prior=prior)
    prior_inputs = [
        *exp.input_manifest,
        {
            "ordinal": 1,
            "input_role": "artifact.prior_model_output",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "previous-summary",
            "source_revision_id": "previous-summary-r1",
            "source_window": {
                "start_local_date": "2026-07-12",
                "end_local_date": "2026-07-18",
            },
        },
        {
            "ordinal": 2,
            "input_role": "plan.current_revision",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "previous-plan",
            "source_revision_id": "previous-plan-r1",
            "source_window": {
                "start_local_date": "2026-07-19",
                "end_local_date": "2026-07-25",
            },
        },
    ]
    object.__setattr__(exp, "input_manifest", prior_inputs)
    value["source_usage"].append(
        {
            "ordinal": 1,
            "input_role": "artifact.prior_model_output",
            "source_entity_id": "previous-summary",
            "source_revision_id": "previous-summary-r1",
        }
    )
    code(
        value,
        "analysis_result_weekly_prior_source_usage_required",
        exp,
    )


def _exact_prior_manifest() -> list[dict[str, object]]:
    return [
        {
            "ordinal": 1,
            "input_role": "artifact.prior_model_output",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "69",
            "source_revision_id": "69-r1",
            "source_window": {
                "start_local_date": "2026-07-12",
                "end_local_date": "2026-07-18",
            },
        },
        {
            "ordinal": 2,
            "input_role": "plan.current_revision",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": "70",
            "source_revision_id": "70-r1",
            "source_window": {
                "start_local_date": "2026-07-19",
                "end_local_date": "2026-07-25",
            },
        },
    ]


def _available_prior_value_and_expectation():
    prior = {"summary": "available", "plan": "available"}
    value = output(prior=prior)
    exp = expectation(prior=prior)
    rows = _exact_prior_manifest()
    object.__setattr__(exp, "input_manifest", [*exp.input_manifest, *rows])
    value["source_usage"].extend(
        {
            "ordinal": row["ordinal"],
            "input_role": row["input_role"],
            "source_entity_id": row["source_entity_id"],
            "source_revision_id": row["source_revision_id"],
        }
        for row in rows
    )
    return value, exp


def test_weekly_prior_lineage_requires_exact_unique_summary_and_plan_sources() -> None:
    value, exp = _available_prior_value_and_expectation()
    assert validate(value, exp).result["mode"] == "weekly"

    missing_summary, missing_summary_exp = _available_prior_value_and_expectation()
    object.__setattr__(
        missing_summary_exp,
        "input_manifest",
        [row for row in missing_summary_exp.input_manifest if row["ordinal"] != 1],
    )
    missing_summary["source_usage"] = [
        row for row in missing_summary["source_usage"] if row["ordinal"] != 1
    ]
    code(
        missing_summary,
        "analysis_result_weekly_prior_source_invalid",
        missing_summary_exp,
    )

    missing_plan, missing_plan_exp = _available_prior_value_and_expectation()
    object.__setattr__(
        missing_plan_exp,
        "input_manifest",
        [row for row in missing_plan_exp.input_manifest if row["ordinal"] != 2],
    )
    missing_plan["source_usage"] = [
        row for row in missing_plan["source_usage"] if row["ordinal"] != 2
    ]
    code(missing_plan, "analysis_result_weekly_prior_source_invalid", missing_plan_exp)

    duplicate_summary, duplicate_summary_exp = _available_prior_value_and_expectation()
    object.__setattr__(
        duplicate_summary_exp,
        "input_manifest",
        [
            *duplicate_summary_exp.input_manifest,
            {**_exact_prior_manifest()[0], "ordinal": 3, "source_entity_id": "71"},
        ],
    )
    code(
        duplicate_summary,
        "analysis_result_weekly_prior_source_invalid",
        duplicate_summary_exp,
    )

    duplicate_plan, duplicate_plan_exp = _available_prior_value_and_expectation()
    object.__setattr__(
        duplicate_plan_exp,
        "input_manifest",
        [
            *duplicate_plan_exp.input_manifest,
            {**_exact_prior_manifest()[1], "ordinal": 3, "source_entity_id": "71"},
        ],
    )
    code(
        duplicate_plan,
        "analysis_result_weekly_prior_source_invalid",
        duplicate_plan_exp,
    )


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda value, exp: value["source_usage"].pop(1),
            "analysis_result_weekly_prior_source_usage_required",
        ),
        (
            lambda value, exp: value["source_usage"].pop(),
            "analysis_result_weekly_prior_source_usage_required",
        ),
        (
            lambda value, exp: exp.input_manifest[1].update(
                input_role="plan.current_revision"
            ),
            "analysis_result_weekly_prior_source_invalid",
        ),
        (
            lambda value, exp: exp.input_manifest[1].update(
                source_window={
                    "start_local_date": "2026-07-11",
                    "end_local_date": "2026-07-18",
                }
            ),
            "analysis_result_weekly_prior_source_invalid",
        ),
        (
            lambda value, exp: exp.input_manifest[1].update(
                source_entity_type="training_plan"
            ),
            "analysis_result_weekly_prior_source_invalid",
        ),
        (
            lambda value, exp: value["source_usage"].append(
                dict(value["source_usage"][1])
            ),
            "analysis_result_source_usage_invalid",
        ),
    ],
)
def test_weekly_prior_source_usage_rejects_invalid_lineage(
    mutate, expected_code: str
) -> None:
    value, exp = _available_prior_value_and_expectation()
    mutate(value, exp)
    code(value, expected_code, exp)


def test_weekly_plan_prose_cannot_invent_bpm_without_evidence() -> None:
    value = output()
    value["artifacts"][1]["user_visible_text"] = "未来七天跑步目标心率为 165 BPM。"
    code(value, "analysis_result_invented_bpm_forbidden")


@pytest.mark.parametrize(
    "apply_clock",
    [
        lambda value: value["artifacts"][1].update(
            user_visible_text="未来七天每天早上 7:00 开始训练。"
        ),
        lambda value: value["training_plan"]["items"][0].update(
            rationale_text="上午 8 点跑步更方便。"
        ),
    ],
)
def test_weekly_plan_cannot_choose_a_training_clock_time(apply_clock) -> None:
    value = output()
    apply_clock(value)
    if "rationale_text" in value["training_plan"]["items"][0]:
        value["artifacts"][1]["structured_content"] = deepcopy(value["training_plan"])
    code(value, "analysis_result_training_clock_time_forbidden")


def test_three_high_intensity_days_are_rejected_after_daily_safety_checks() -> None:
    prescriptions = [
        running(zone=4) if index in {0, 2, 4} else rest() for index in range(7)
    ]
    code(
        output(prescriptions=prescriptions),
        "analysis_result_weekly_high_intensity_frequency_exceeded",
        expectation(zones=True),
    )


def test_high_intensity_running_days_need_at_least_48_hours_between_dates() -> None:
    prescriptions = [
        running(zone=4) if index in {0, 1} else rest() for index in range(7)
    ]
    code(
        output(prescriptions=prescriptions),
        "analysis_result_weekly_high_intensity_recovery_insufficient",
        expectation(zones=True),
    )


def test_hansons_sos_roles_cannot_be_scheduled_on_consecutive_days() -> None:
    tempo = running()
    tempo.update(
        hansons_session_role="tempo",
        course_type="steady",
        target_zone=3,
        prescribed_rpe=6,
    )
    prescriptions = [
        deepcopy(tempo) if index in {0, 1} else rest() for index in range(7)
    ]
    code(
        output(prescriptions=prescriptions),
        "analysis_result_hansons_sos_recovery_insufficient",
        expectation(zones=True),
    )


def test_red_flag_requires_the_entire_week_to_be_safety_suspended() -> None:
    value = output(
        prescriptions=[rest(), running(), rest(), rest(), rest(), rest(), rest()]
    )
    # A base only carrying a red flag on day zero cannot safely leave later
    # days active; the validator requires a fully suspended weekly outcome.
    exp = expectation()
    first = PLAN["start_local_date"]
    bases = dict(exp.weekly_safety_request_bases or {})
    bases[first] = base(first, red_flag=True)
    object.__setattr__(exp, "weekly_safety_request_bases", bases)
    code(value, "analysis_result_weekly_red_flag_plan_not_suspended", exp)
