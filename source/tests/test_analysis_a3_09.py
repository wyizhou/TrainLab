from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.analysis.safety_rules import (
    TRAINING_SAFETY_POLICY_SHA256,
    TRAINING_SAFETY_POLICY_VERSION,
    SafetyRuleError,
    TrainingSafetyRuleEngine,
    evaluate_training_safety,
    stable_safety_hash,
)

AS_OF = "2026-07-24T00:00:00Z"
ADVICE_DATE = "2026-07-25"
STOP = [
    "acute_pain",
    "chest_pain",
    "fainting_or_dizziness",
    "unusual_shortness_of_breath",
]


def running(**overrides):
    item = {
        "activity_kind": "running",
        "hansons_session_role": "easy",
        "course_type": "easy",
        "warmup": "gentle_warmup",
        "main_set": "talk_test_easy",
        "cooldown": "gentle_cooldown",
        "planned_duration_minutes": 40,
        "total_volume": "easy_by_duration",
        "target_zone": None,
        "target_bpm_range": None,
        "prescribed_rpe": 4,
        "talk_test": "full_sentences",
        "work_intervals": [],
        "stop_conditions": STOP,
        "rationale": "recovery_appropriate",
    }
    item.update(overrides)
    if "hansons_session_role" not in overrides:
        item["hansons_session_role"] = {
            "easy": "easy",
            "long_easy": "long",
            "steady": "tempo",
            "intervals": "speed",
        }[item["course_type"]]
    return item


def test_hansons_role_must_match_the_controlled_running_course_type():
    with pytest.raises(SafetyRuleError, match="training_safety_hansons_role_invalid"):
        evaluate_training_safety(
            request(running(hansons_session_role="speed", course_type="easy"))
        )


def climbing(**overrides):
    item = {"activity_kind": "climbing", "rationale": "recovery_appropriate"}
    item.update(overrides)
    return item


def strength(**overrides):
    item = {
        "activity_kind": "strength",
        "rationale": "supports_running_and_climbing",
        "movements": [
            {"exercise_key": "bodyweight_squat", "movement_kind": "squat"},
            {"exercise_key": "supported_row", "movement_kind": "pull"},
            {"exercise_key": "suitcase_carry", "movement_kind": "carry"},
        ],
        "stop_conditions": ["acute_pain", "acute_discomfort"],
    }
    item.update(overrides)
    return item


def rest():
    return {
        "activity_kind": "rest",
        "evidence": ["scheduled_recovery"],
        "uncertainty": "normal_training_uncertainty",
        "daily_activity_allowed": True,
        "recovery_signals": ["energy_improves"],
        "seek_professional_help_if": ["concerning_symptom_appears"],
    }


def request(
    item=None,
    *,
    zones=(),
    signals=(),
    quality=(),
    substitution=None,
):
    return {
        "schema_version": "1",
        "subject_id": 1,
        "advice_local_date": ADVICE_DATE,
        "as_of_utc": AS_OF,
        "primary_items": [item or running()],
        "zone_evidence": list(zones),
        "safety_signals": list(signals),
        "quality_sessions": list(quality),
        "substitution": substitution,
    }


def boundaries(offset=0):
    return [
        {"zone": 1, "minimum_bpm": 100 + offset, "maximum_bpm": 119 + offset},
        {"zone": 2, "minimum_bpm": 120 + offset, "maximum_bpm": 139 + offset},
        {"zone": 3, "minimum_bpm": 140 + offset, "maximum_bpm": 159 + offset},
        {"zone": 4, "minimum_bpm": 160 + offset, "maximum_bpm": 179 + offset},
        {"zone": 5, "minimum_bpm": 180 + offset, "maximum_bpm": 200 + offset},
    ]


def zone_evidence(
    kind="garmin_sport_zones",
    revision="garmin-zones",
    *,
    current=True,
    reliable="reliable",
    effective="2026-01-01T00:00:00Z",
    expires=None,
    offset=0,
):
    return {
        "evidence_id": f"e-{revision}",
        "source_kind": kind,
        "source_revision_id": revision,
        "current": current,
        "reliability": reliable,
        "effective_from_utc": effective,
        "expires_at_utc": expires,
        "sport": "running",
        "zones": boundaries(offset),
        "heart_rate_bpm": None,
        "measurement_method": "provider_profile"
        if kind == "garmin_sport_zones"
        else "user_verified",
    }


def baseline(
    kind, bpm, revision, *, method="provider_profile", reliable="reliable", current=True
):
    return {
        "evidence_id": f"e-{revision}",
        "source_kind": kind,
        "source_revision_id": revision,
        "current": current,
        "reliability": reliable,
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "expires_at_utc": None,
        "sport": None,
        "zones": None,
        "heart_rate_bpm": bpm,
        "measurement_method": method,
    }


def prohibited(kind, revision, bpm=None):
    method = {
        "time_in_zone": "activity_time_in_zone",
        "age_formula": "age_formula",
        "single_sample_max_hr": "single_sample",
    }[kind]
    return {
        "evidence_id": f"e-{revision}",
        "source_kind": kind,
        "source_revision_id": revision,
        "current": True,
        "reliability": "reliable",
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "expires_at_utc": None,
        "sport": None,
        "zones": None,
        "heart_rate_bpm": bpm,
        "measurement_method": method,
    }


def signal(kind, revision, *, origin="user_asserted", active=True, current=True):
    return {
        "signal_id": f"s-{revision}",
        "kind": kind,
        "origin": origin,
        "source_revision_id": revision,
        "current": current,
        "active": active,
        "effective_from_utc": "2026-07-23T00:00:00Z",
        "expires_at_utc": None,
    }


def quality(activity_id, local_date, start, end, revision):
    return {
        "activity_id": activity_id,
        "source_revision_id": revision,
        "current": True,
        "is_formal_training": True,
        "quality_session": True,
        "local_date": local_date,
        "start_time_utc": start,
        "end_time_utc": end,
    }


def substitution(
    *, planned_minutes=60, actual_minutes=30, planned_seconds=3600, actual_seconds=1800
):
    return {
        "source_revision_id": "sub-rev",
        "current": True,
        "declared": "substituted",
        "planned_activity_kind": "running",
        "actual_activity_kind": "running",
        "planned_duration_minutes": planned_minutes,
        "planned_duration_seconds": planned_seconds,
        "actual_duration_minutes": actual_minutes,
        "actual_duration_seconds": actual_seconds,
    }


def reason_codes(result):
    return {row["code"] for row in result["reasons"]}


def test_static_policy_and_schemas_are_versioned_strict_and_self_validating():
    root = Path(__file__).parents[1] / "src/analysis"
    policy = json.loads((root / "training_safety_policy.json").read_text())
    schema = json.loads(
        (root / "schemas/training_safety_policy.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(policy)
    assert TRAINING_SAFETY_POLICY_VERSION == "1.0.1-a3-09"
    assert (
        TRAINING_SAFETY_POLICY_SHA256
        == "bf8b78e19514672e80b7f03ddcaa11f736523d992353082f83dc1b493755cce9"
    )
    for name in (
        "training_safety_request.schema.json",
        "training_safety_result.schema.json",
    ):
        loaded = json.loads((root / "schemas" / name).read_text())
        Draft202012Validator.check_schema(loaded)
        assert loaded["additionalProperties"] is False


def test_garmin_beats_user_and_hrr_with_exact_revision_lineage():
    evidence = (
        zone_evidence(),
        zone_evidence("user_zones", "user-zones", offset=-5),
        baseline("max_hr_baseline", 190, "max"),
        baseline("resting_hr_baseline", 50, "rest"),
    )
    result = evaluate_training_safety(request(running(target_zone=2), zones=evidence))
    item = result["primary_items"][0]
    assert result["zone_selection"]["source_kind"] == "garmin_sport_zones"
    assert item["target_bpm_range"] == {"minimum_bpm": 120, "maximum_bpm": 139}
    assert item["zone_source_revision_id"] == "garmin-zones"
    assert set(result["input_revision_ids"]) == {
        "garmin-zones",
        "user-zones",
        "max",
        "rest",
    }
    assert "exact_zone_source_garmin" in reason_codes(result)


def test_expired_and_future_garmin_fall_through_to_current_user_zones():
    evidence = (
        zone_evidence(expires="2026-07-01T00:00:00Z"),
        zone_evidence(
            "garmin_sport_zones", "future-garmin", effective="2026-08-01T00:00:00Z"
        ),
        zone_evidence("user_zones", "user-zones", offset=-5),
    )
    result = evaluate_training_safety(request(running(target_zone=2), zones=evidence))
    assert result["zone_selection"]["source_kind"] == "user_zones"
    assert {
        "zone_evidence_expired",
        "zone_evidence_future",
        "exact_zone_source_user",
    } <= reason_codes(result)


def test_same_priority_zone_conflict_fails_closed_to_rpe_fallback():
    evidence = (
        zone_evidence("user_zones", "user-one"),
        zone_evidence("user_zones", "user-two", offset=1),
    )
    result = evaluate_training_safety(
        request(
            running(course_type="intervals", target_zone=4, prescribed_rpe=8),
            zones=evidence,
        )
    )
    item = result["primary_items"][0]
    assert result["status"] == "modified_for_safety"
    assert result["zone_selection"]["source_kind"] == "rpe_talk_test"
    assert item["target_zone"] is None and item["target_bpm_range"] is None
    assert item["course_type"] == "easy" and item["prescribed_rpe"] == 4
    assert {"zone_source_conflict", "low_intensity_fallback"} <= reason_codes(result)


def test_hrr_requires_separate_current_reliable_non_prohibited_baselines():
    hrr = (
        baseline("max_hr_baseline", 190, "max"),
        baseline("resting_hr_baseline", 50, "rest"),
    )
    result = evaluate_training_safety(request(running(target_zone=2), zones=hrr))
    item = result["primary_items"][0]
    assert result["zone_selection"]["source_kind"] == "hrr"
    assert result["zone_selection"]["source_revision_ids"] == ["max", "rest"]
    assert item["target_bpm_range"] == {"minimum_bpm": 134, "maximum_bpm": 147}
    assert item["zone_source_revision_id"].startswith("hrr:")

    for broken in (
        (baseline("max_hr_baseline", 190, "max", current=False), hrr[1]),
        (baseline("max_hr_baseline", 190, "max", reliable="unreliable"), hrr[1]),
        (baseline("max_hr_baseline", 190, "max", method="single_sample"), hrr[1]),
        (hrr[0],),
    ):
        fallback = evaluate_training_safety(request(zones=broken))
        assert fallback["zone_selection"]["exact_bpm_allowed"] is False
        assert fallback["primary_items"][0]["target_bpm_range"] is None


def test_every_exact_zone_boundary_is_inclusive_contiguous_and_non_overlapping():
    hrr = (
        baseline("max_hr_baseline", 190, "max"),
        baseline("resting_hr_baseline", 50, "rest"),
    )
    hrr_zones = evaluate_training_safety(request(zones=hrr))["zone_selection"]["zones"]
    assert hrr_zones == [
        {"zone": 1, "minimum_bpm": 120, "maximum_bpm": 133},
        {"zone": 2, "minimum_bpm": 134, "maximum_bpm": 147},
        {"zone": 3, "minimum_bpm": 148, "maximum_bpm": 161},
        {"zone": 4, "minimum_bpm": 162, "maximum_bpm": 175},
        {"zone": 5, "minimum_bpm": 176, "maximum_bpm": 190},
    ]
    assert all(
        left["maximum_bpm"] + 1 == right["minimum_bpm"]
        for left, right in zip(hrr_zones, hrr_zones[1:])
    )

    for next_minimum in (119, 121):
        overlap_or_gap = zone_evidence()
        overlap_or_gap["zones"][1]["minimum_bpm"] = next_minimum
        with pytest.raises(SafetyRuleError, match="zone_boundaries_invalid"):
            evaluate_training_safety(request(zones=(overlap_or_gap,)))


def test_time_in_zone_single_sample_and_age_formula_never_unlock_exact_bpm():
    evidence = (
        prohibited("time_in_zone", "time-zone"),
        prohibited("single_sample_max_hr", "single-max", 199),
        prohibited("age_formula", "age", 180),
    )
    result = evaluate_training_safety(request(zones=evidence))
    assert result["zone_selection"]["source_kind"] == "rpe_talk_test"
    assert "prohibited_zone_evidence" in reason_codes(result)
    assert result["primary_items"][0]["target_bpm_range"] is None


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("hr_affecting_medication", "hr_medication_exact_bpm_blocked"),
        ("hr_baseline_unreliable", "hr_baseline_unreliable"),
    ],
)
def test_medication_or_unreliable_baseline_blocks_even_garmin_exact_bpm(kind, reason):
    result = evaluate_training_safety(
        request(
            running(target_zone=3, prescribed_rpe=6),
            zones=(zone_evidence(),),
            signals=(signal(kind, "blocker"),),
        )
    )
    assert result["zone_selection"]["exact_bpm_allowed"] is False
    assert result["primary_items"][0]["target_zone"] is None
    assert reason in reason_codes(result)
    reason_row = next(row for row in result["reasons"] if row["code"] == reason)
    assert reason_row["source_revision_ids"] == ["blocker"]


@pytest.mark.parametrize("kind", ["chest_pain", "fainting", "acute_injury"])
def test_explicit_red_flags_suspend_training_and_return_formal_rest(kind):
    result = evaluate_training_safety(
        request(
            running(target_zone=2),
            zones=(zone_evidence(),),
            signals=(signal(kind, "red"),),
        )
    )
    assert result["status"] == "modified_for_safety"
    assert result["safety_state"] == "suspended"
    assert result["professional_evaluation_recommended"] is True
    assert result["primary_items"][0]["activity_kind"] == "rest"
    assert result["primary_items"][0]["daily_activity_allowed"] is False
    assert {
        "red_flag_training_suspended",
        "professional_evaluation_recommended",
    } <= reason_codes(result)
    assert result["constraints"]["medical_diagnosis_forbidden"] is True
    assert (
        result["primary_items"][0]["uncertainty"] == "safety_rule_not_medical_diagnosis"
    )


def test_device_anomaly_only_warns_without_changing_or_diagnosing():
    result = evaluate_training_safety(
        request(
            climbing(),
            signals=(signal("device_anomaly", "device", origin="device_fact"),),
        )
    )
    assert result["status"] == "accepted"
    assert result["primary_items"] == [climbing()]
    assert result["safety_state"] == "warning"
    assert [row["code"] for row in result["warnings"]] == ["device_anomaly_warning"]
    assert result["professional_evaluation_recommended"] is False


def interval_running(zone=4, **overrides):
    item = running(
        course_type="intervals",
        main_set="structured_intervals",
        target_zone=zone,
        prescribed_rpe=8 if zone == 4 else 9,
        work_intervals=[
            {
                "work_seconds": 180 if zone == 4 else 60,
                "recovery_seconds": 180 if zone == 4 else 60,
                "repetitions": 4,
                "target_zone": zone,
            }
        ],
        planned_duration_minutes=50,
    )
    item.update(overrides)
    return item


def test_zone4_structured_conservative_session_is_allowed_and_bounded():
    result = evaluate_training_safety(
        request(interval_running(), zones=(zone_evidence(),))
    )
    assert result["status"] == "modified_for_safety"
    assert result["primary_items"][0]["target_bpm_range"] == {
        "minimum_bpm": 160,
        "maximum_bpm": 179,
    }
    assert not reason_codes(result) & {
        "zone45_requires_intervals",
        "zone45_dose_exceeded",
        "zone45_recovery_insufficient",
    }


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (
            running(course_type="steady", target_zone=4, prescribed_rpe=8),
            "zone45_requires_intervals",
        ),
        (
            interval_running(
                work_intervals=[
                    {
                        "work_seconds": 600,
                        "recovery_seconds": 600,
                        "repetitions": 3,
                        "target_zone": 4,
                    }
                ]
            ),
            "zone45_dose_exceeded",
        ),
        (
            interval_running(
                planned_duration_minutes=30,
                work_intervals=[
                    {
                        "work_seconds": 180,
                        "recovery_seconds": 180,
                        "repetitions": 5,
                        "target_zone": 4,
                    }
                ],
            ),
            "zone45_dose_exceeded",
        ),
        (interval_running(prescribed_rpe=10), "rpe_too_high"),
    ],
)
def test_zone45_rejects_unstructured_excess_and_rpe10(item, code):
    result = evaluate_training_safety(request(item, zones=(zone_evidence(),)))
    assert result["status"] == "rejected" and result["primary_items"] == []
    assert code in reason_codes(result)


def test_zone5_single_interval_and_recovery_are_stricter():
    excessive = interval_running(
        5,
        work_intervals=[
            {
                "work_seconds": 180,
                "recovery_seconds": 180,
                "repetitions": 2,
                "target_zone": 5,
            }
        ],
    )
    result = evaluate_training_safety(request(excessive, zones=(zone_evidence(),)))
    assert result["status"] == "rejected"
    assert "zone45_dose_exceeded" in reason_codes(result)


def test_hidden_high_zone_interval_cannot_hide_behind_lower_or_null_target():
    for item in (
        running(
            course_type="intervals",
            target_zone=2,
            work_intervals=[
                {
                    "work_seconds": 60,
                    "recovery_seconds": 60,
                    "repetitions": 2,
                    "target_zone": 5,
                }
            ],
        ),
        running(
            course_type="intervals",
            target_zone=None,
            work_intervals=[
                {
                    "work_seconds": 60,
                    "recovery_seconds": 60,
                    "repetitions": 2,
                    "target_zone": 5,
                }
            ],
        ),
    ):
        result = evaluate_training_safety(request(item, zones=(zone_evidence(),)))
        assert result["status"] == "rejected"
        assert "interval_structure_invalid" in reason_codes(result)


@pytest.mark.parametrize(
    "item",
    [
        running(target_zone=None, course_type="steady", prescribed_rpe=9),
        running(target_zone=2, course_type="steady", prescribed_rpe=8),
        running(
            target_zone=3,
            course_type="intervals",
            prescribed_rpe=9,
            work_intervals=[
                {
                    "work_seconds": 60,
                    "recovery_seconds": 60,
                    "repetitions": 2,
                    "target_zone": 3,
                }
            ],
        ),
    ],
)
def test_quality_rpe_cannot_hide_behind_null_or_lower_zone(item):
    result = evaluate_training_safety(request(item, zones=(zone_evidence(),)))
    assert result["status"] == "rejected"
    assert "zone45_requires_intervals" in reason_codes(result)


def test_quality_rpe_without_exact_bpm_is_safely_downgraded():
    result = evaluate_training_safety(
        request(running(target_zone=None, course_type="steady", prescribed_rpe=9))
    )
    item = result["primary_items"][0]
    assert result["status"] == "modified_for_safety"
    assert item["course_type"] == "easy"
    assert item["target_zone"] is None and item["target_bpm_range"] is None
    assert item["prescribed_rpe"] == 4 and item["work_intervals"] == []


def test_quality_frequency_and_minimum_recovery_fail_closed():
    recent = quality(
        "q1",
        "2026-07-23",
        "2026-07-23T10:00:00Z",
        "2026-07-23T11:00:00Z",
        "q1-rev",
    )
    recovery = evaluate_training_safety(
        request(interval_running(), zones=(zone_evidence(),), quality=(recent,))
    )
    assert recovery["status"] == "rejected"
    assert "zone45_recovery_insufficient" in reason_codes(recovery)

    earlier = quality(
        "q2",
        "2026-07-20",
        "2026-07-20T10:00:00Z",
        "2026-07-20T11:00:00Z",
        "q2-rev",
    )
    another = quality(
        "q3",
        "2026-07-18",
        "2026-07-18T10:00:00Z",
        "2026-07-18T11:00:00Z",
        "q3-rev",
    )
    frequency = evaluate_training_safety(
        request(
            interval_running(), zones=(zone_evidence(),), quality=(earlier, another)
        )
    )
    assert frequency["status"] == "rejected"
    assert "zone45_frequency_exceeded" in reason_codes(frequency)
    future = quality(
        "future",
        "2026-07-24",
        "2026-07-24T10:00:00Z",
        "2026-07-24T11:00:00Z",
        "future-rev",
    )
    with pytest.raises(SafetyRuleError, match="future_quality_session"):
        evaluate_training_safety(
            request(interval_running(), zones=(zone_evidence(),), quality=(future,))
        )


def test_running_fields_source_revision_stop_conditions_and_bpm_mismatch():
    result = evaluate_training_safety(
        request(running(target_zone=2), zones=(zone_evidence(),))
    )
    item = result["primary_items"][0]
    required = {
        "course_type",
        "warmup",
        "main_set",
        "cooldown",
        "planned_duration_minutes",
        "total_volume",
        "zone_source_kind",
        "zone_source_revision_id",
        "zone_source_revision_ids",
        "target_zone",
        "target_bpm_range",
        "prescribed_rpe",
        "talk_test",
        "work_intervals",
        "stop_conditions",
    }
    assert required <= set(item)
    incomplete = evaluate_training_safety(
        request(running(stop_conditions=["acute_pain"]), zones=(zone_evidence(),))
    )
    assert incomplete["status"] == "rejected"
    assert "stop_conditions_incomplete" in reason_codes(incomplete)
    mismatch = evaluate_training_safety(
        request(
            running(
                target_zone=2,
                target_bpm_range={"minimum_bpm": 150, "maximum_bpm": 160},
            ),
            zones=(zone_evidence(),),
        )
    )
    assert mismatch["status"] == "rejected"
    assert "target_bpm_mismatch" in reason_codes(mismatch)


def test_climbing_is_conservative_and_recovery_signal_changes_to_rest():
    accepted = evaluate_training_safety(request(climbing()))
    assert accepted["primary_items"] == [climbing()]
    blocked = evaluate_training_safety(
        request(
            climbing(), signals=(signal("forearm_recovery_insufficient", "forearm"),)
        )
    )
    assert blocked["status"] == "modified_for_safety"
    assert blocked["primary_items"][0]["activity_kind"] == "rest"
    assert "climbing_recovery_insufficient" in reason_codes(blocked)
    with pytest.raises(SafetyRuleError, match="request_schema_invalid"):
        evaluate_training_safety(request(climbing(grade="V5")))
    with pytest.raises(SafetyRuleError):
        evaluate_training_safety(request(climbing(rationale="Try V5 for 10 routes")))


def test_strength_is_movement_only_full_body_and_has_pain_stops():
    accepted = evaluate_training_safety(request(strength()))
    item = accepted["primary_items"][0]
    assert item["activity_kind"] == "strength"
    assert not {"sets", "reps", "weight", "rest_seconds", "set_rpe", "e1rm"} & set(item)
    blocked = evaluate_training_safety(
        request(strength(), signals=(signal("recent_long_run", "long-run"),))
    )
    assert blocked["primary_items"][0]["activity_kind"] == "rest"
    assert "strength_recovery_insufficient" in reason_codes(blocked)
    for mutation in (strength(sets=3), strength(movements=strength()["movements"][:2])):
        with pytest.raises(SafetyRuleError):
            evaluate_training_safety(request(mutation))
    with pytest.raises(SafetyRuleError):
        evaluate_training_safety(
            request(strength(rationale="Perform 3x10 with 50 kg and RPE 8"))
        )
    missing_stop = evaluate_training_safety(
        request(strength(stop_conditions=["acute_pain"]))
    )
    assert missing_stop["status"] == "rejected"
    assert "stop_conditions_incomplete" in reason_codes(missing_stop)


def test_rest_is_formal_primary_result():
    result = evaluate_training_safety(request(rest()))
    assert result["status"] == "accepted"
    assert result["primary_items"] == [rest()]
    assert "rest_selected" in reason_codes(result)


def test_exactly_one_primary_unknown_fields_and_free_text_fail_closed():
    engine = TrainingSafetyRuleEngine()
    for items in ([], [running(), climbing()]):
        payload = request()
        payload["primary_items"] = items
        with pytest.raises(SafetyRuleError, match="request_schema_invalid"):
            engine.evaluate(payload)
    unknown = request()
    unknown["unexpected"] = True
    with pytest.raises(SafetyRuleError, match="request_schema_invalid"):
        engine.evaluate(unknown)
    with pytest.raises(SafetyRuleError):
        engine.evaluate(request(running(rationale="start at 07:00")))
    with pytest.raises(SafetyRuleError):
        engine.evaluate(request(running(rationale="start at 7 pm")))


@pytest.mark.parametrize(
    "item",
    [
        running(rationale="Start at noon"),
        running(rationale="You have myocarditis"),
        running(main_set="maximal_effort_repeats"),
        rest() | {"evidence": ["Take ibuprofen 400mg as treatment"]},
        strength(
            rationale="Perform three sets of ten repetitions with fifty kilograms"
        ),
        climbing(rationale="Try ten routes"),
        climbing(rationale="Do three hangs on a small edge"),
        climbing(rationale="Aim for V-five"),
    ],
)
def test_all_advice_content_is_controlled_tokens_not_free_text(item):
    with pytest.raises(SafetyRuleError):
        evaluate_training_safety(request(item, zones=(zone_evidence(),)))


def test_substitution_same_sport_different_dose_is_not_false_conflict():
    result = evaluate_training_safety(request(substitution=substitution()))
    assert result["substitution_assessment"] == {
        "status": "consistent_with_substitution",
        "planned_activity_kind": "running",
        "actual_activity_kind": "running",
        "duration_ratio": 0.5,
        "source_revision_id": "sub-rev",
    }
    exact = evaluate_training_safety(
        request(substitution=substitution(actual_minutes=60, actual_seconds=3600))
    )
    assert (
        exact["substitution_assessment"]["status"]
        == "conflicts_with_exact_activity_evidence"
    )
    with pytest.raises(SafetyRuleError, match="duration_units_ambiguous"):
        evaluate_training_safety(
            request(substitution=substitution(actual_minutes=30, actual_seconds=1700))
        )
    with pytest.raises(SafetyRuleError, match="duration_units_ambiguous"):
        evaluate_training_safety(request(running(planned_duration_seconds=2300)))


def test_deterministic_pure_evaluation_does_not_mutate_log_or_read_runtime(
    monkeypatch, capsys
):
    engine = TrainingSafetyRuleEngine()
    payload = request(
        running(target_zone=2),
        zones=(zone_evidence(),),
        signals=(signal("device_anomaly", "device", origin="device_fact"),),
        substitution=substitution(),
    )
    original = deepcopy(payload)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda *_: (_ for _ in ()).throw(AssertionError("runtime io")),
    )
    first = engine.evaluate(payload)
    second = engine.evaluate(payload)
    assert first == second
    assert stable_safety_hash(first) == stable_safety_hash(second)
    assert engine.serialize_result(first) == engine.serialize_result(second)
    assert payload == original
    assert capsys.readouterr().out == "" and capsys.readouterr().err == ""


def test_evidence_permutations_have_identical_stable_result():
    evidence = (
        zone_evidence(),
        zone_evidence("user_zones", "user-zones", offset=-5),
        prohibited("time_in_zone", "time-zone"),
    )
    signals = (
        signal("device_anomaly", "device-a", origin="device_fact"),
        signal("device_anomaly", "device-b", origin="device_fact"),
    )
    first = evaluate_training_safety(
        request(running(target_zone=2), zones=evidence, signals=signals)
    )
    second = evaluate_training_safety(
        request(
            running(target_zone=2),
            zones=tuple(reversed(evidence)),
            signals=tuple(reversed(signals)),
        )
    )
    assert first == second


def test_result_validator_rejects_unknown_fields_and_lineage_reordering():
    engine = TrainingSafetyRuleEngine()
    result = engine.evaluate(request(zones=(zone_evidence(),)))
    malformed = deepcopy(result)
    malformed["unknown"] = True
    with pytest.raises(SafetyRuleError, match="result_schema_invalid"):
        engine.validate_result(malformed)
    malformed = deepcopy(result)
    malformed["input_revision_ids"] = list(reversed(malformed["input_revision_ids"]))
    if len(malformed["input_revision_ids"]) < 2:
        malformed["input_revision_ids"] = ["z", "a"]
    with pytest.raises(SafetyRuleError, match="lineage_invalid"):
        engine.validate_result(malformed)
    malformed = deepcopy(result)
    malformed["policy_sha256"] = "0" * 64
    with pytest.raises(SafetyRuleError, match="policy_invalid"):
        engine.validate_result(malformed)
    malformed = deepcopy(result)
    malformed["zone_selection"]["exact_bpm_allowed"] = False
    with pytest.raises(SafetyRuleError, match="zone_invalid"):
        engine.validate_result(malformed)


@pytest.mark.parametrize(
    ("item", "field", "value"),
    [
        (running(), "rationale", "start_at_noon"),
        (running(), "rationale", "you_have_myocarditis"),
        (running(), "main_set", "maximal_effort_repeats"),
        (climbing(), "rationale", "try_ten_routes"),
        (
            strength(),
            "rationale",
            "perform_three_sets_of_ten_with_fifty_kilograms",
        ),
    ],
)
def test_result_validator_rejects_token_shaped_free_text_bypasses(item, field, value):
    engine = TrainingSafetyRuleEngine()
    result = engine.evaluate(request(item, zones=(zone_evidence(),)))
    result["primary_items"][0][field] = value
    with pytest.raises(SafetyRuleError, match="controlled_token_invalid"):
        engine.validate_result(result)

    rest_result = engine.evaluate(request(rest()))
    rest_result["primary_items"][0]["evidence"] = ["take_ibuprofen_400mg_as_treatment"]
    with pytest.raises(SafetyRuleError, match="controlled_token_invalid"):
        engine.validate_result(rest_result)


def test_result_validator_rejects_quality_rpe_without_zone45_intervals():
    engine = TrainingSafetyRuleEngine()
    result = engine.evaluate(request(running(), zones=(zone_evidence(),)))
    item = result["primary_items"][0]
    item["course_type"] = "steady"
    item["hansons_session_role"] = "tempo"
    item["prescribed_rpe"] = 9
    with pytest.raises(SafetyRuleError, match="result_running_rule_invalid"):
        engine.validate_result(result)
