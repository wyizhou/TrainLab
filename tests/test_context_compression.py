from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from trainlab.compression import ensure_summaries
from trainlab.context import build_runtime_input
from trainlab.db import connect


def test_bounded_context_and_recent_details(settings):
    connection = connect(settings.database_path)
    payload = build_runtime_input(
        settings,
        connection,
        slot="morning",
        as_of=datetime(2026, 4, 18, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")),
    )
    assert len(payload["activities"]["summaries"]) == 4
    assert {key: len(value) for key, value in payload["activities"]["details"].items()} == {
        "running": 1,
        "climbing": 2,
        "strength_training": 1,
    }
    assert all(len(value) <= 2 for value in payload["activities"]["details"].values())
    detailed_ids = {
        item["activity_id"] for values in payload["activities"]["details"].values() for item in values
    }
    assert detailed_ids == {item["activity_id"] for item in payload["activities"]["summaries"]}
    assert len(payload["history"]["weekly"]) <= 8
    assert len(payload["history"]["monthly"]) <= 12
    assert payload["profile"]["running"] == {"heart_rate_method": "heart_rate_reserve"}
    assert "personal" not in payload["profile"]
    decision_policy = payload["policy"]["training_decision"]
    assert decision_policy["user_selects_start_clock_time"] is True
    assert decision_policy["running_load"]["insufficient_history_fallback"]["main_set_minutes"] == 30
    assert decision_policy["recovery"]["independent_signals_required_to_downgrade_quality"] == 2
    assert decision_policy["climbing"]["output_prefix"] == "今日攀岩"
    heart_rate_policy = payload["policy"]["heart_rate_intensity"]
    assert heart_rate_policy["method"] == "heart_rate_reserve"
    assert heart_rate_policy["estimate"] is None
    assert heart_rate_policy["missing_behavior"] == "talk_test_easy_run_only"
    assert heart_rate_policy["heart_rate_affecting_medication_gate"] == {
        "configured_medications": [],
        "when_present": "disable_precise_hrr_targets_pending_qualified_guidance",
        "fallback": "rpe_and_talk_test",
    }
    assert heart_rate_policy["resting_heart_rate_source"] == {
        "strategy": "apple_health_daily_resting_heart_rate_only",
        "historical_source": "apple_health_resting_heart_rate",
        "rolling_window_calendar_days": 7,
        "rolling_window_statistic": "median",
        "minimum_valid_days": 5,
        "initial_baseline_activation": "immediate_when_minimum_valid_days_met",
        "initial_baseline_selection": "median_of_valid_completed_days_in_window",
        "recalculation_frequency": "daily",
        "include_current_local_day_in_baseline": False,
        "current_local_day_usage": "provisional_recovery_signal_only",
        "significant_increase_gate": {
            "relative_fraction": 0.05,
            "minimum_bpm": 3,
            "confirmation_consecutive_completed_days": 2,
            "first_day_status": "provisional_warning",
            "confirmed_status": "sustained_recovery_risk",
            "signal_alone_changes_training": False,
            "upward_baseline_candidate_after_consecutive_completed_days": 14,
            "candidate_stability_window_completed_days": 7,
            "candidate_stability_max_range_bpm": 3,
            "supported_baseline_selection": "median_of_stability_window_candidates",
            "adoption_health_gate": {
                "blocking_active_facts": [
                    "acute_illness",
                    "active_injury",
                    "red_flag_symptom",
                    "user_reported_not_recovered",
                ],
                "blocked_action": "keep_existing_baseline_and_preserve_candidate_history",
                "recheck_after_blocker_clears": True,
                "objective_recovery_signal_alone_permanently_blocks": False,
            },
            "unstable_candidate_action": "keep_existing_baseline_and_continue_rolling_observation",
            "baseline_before_candidate": "keep_existing_lower_baseline",
            "action": "flag_recovery_risk_and_defer_upward_baseline_update",
        },
        "decrease_policy": {
            "adoption": "immediate_for_more_conservative_prescription",
            "significant_decrease_relative_fraction": 0.05,
            "significant_decrease_minimum_bpm": 3,
            "significant_decrease_action": "flag_change_and_check_recovery_sleep_and_user_feedback",
            "infer_fitness_improvement_from_signal_alone": False,
        },
        "derived_from_sleep_minimum": False,
        "derived_from_background_samples": False,
        "missing_data_action": "disable_precise_hrr_targets",
    }
    assert heart_rate_policy["maximum_heart_rate_source"] == {
        "strategy": "historical_sustained_peak_then_age_fallback",
        "historical_source": "apple_health_workout_samples",
        "historical_peak_window_seconds": 10,
        "historical_peak_statistic": "median",
        "historical_peak_window_quality": {
            "minimum_valid_samples": 8,
            "maximum_missing_fraction": 0.2,
            "maximum_internal_gap_seconds": 2,
            "missing_data_action": "discard_window_without_imputation",
        },
        "cadence_lock_policy": {
            "cadence_proximity_role": "risk_signal",
            "cadence_proximity_alone_rejects_candidate": False,
            "cadence_proximity_tolerance": {
                "relative_fraction": 0.02,
                "minimum_bpm": 3,
            },
            "sustained_tracking_seconds": 30,
            "rejection_requires_joint_evidence": [
                "abrupt_convergence_to_cadence",
                "sustained_cadence_tracking",
                "workload_response_inconsistency",
            ],
        },
        "evaluation_frequency": "every_ingested_run",
        "ordinary_run_peak_role": "observation_only",
        "candidate_gate": "detected_near_maximal_running_segment",
        "candidate_minimum_segment_seconds": 180,
        "candidate_gate_logic": {
            "required": ["heart_rate_shape"],
            "at_least_one": ["relative_pace_or_power", "workout_structure"],
        },
        "heart_rate_shape_policy": {
            "accepted_patterns": ["continuous_plausible_rise", "high_stable_response"],
            "plateau_required": False,
            "plateau_role": "confidence_booster",
            "peak_allowed_position": "entire_segment",
            "final_window_seconds": 60,
            "final_window_peak_role": "confidence_booster",
        },
        "candidate_gate_signals": [
            "pace",
            "power",
            "heart_rate_rise",
            "segment_duration",
            "workout_context",
        ],
        "age_formula_percentage_gate": None,
        "minimum_supporting_runs": 2,
        "supporting_runs_require_distinct_local_dates": True,
        "supporting_candidate_tolerance_bpm": 5,
        "supported_baseline_selection": "lower_candidate",
        "supported_baseline_zone_unlock": {
            "immediately_eligible_zones": ["zone_3", "zone_4"],
            "zone_5_requires_prior_zone_4_adaptation": True,
            "zone_5_required_successful_zone_4_sessions": 2,
            "zone_5_zone_4_sessions_require_distinct_local_dates": True,
            "zone_5_minimum_hours_between_zone_4_sessions": 72,
            "zone_4_success_safety_gate": {
                "criterion": "no_reported_warning_symptoms_or_acute_injury",
                "primary_feedback_channel": "trainlab_email_reply",
                "no_reply_passes_gate": True,
                "no_reply_interpretation": "no_warning_symptoms_reported",
                "no_reply_is_medical_confirmation": False,
                "reported_warning_symptoms_invalidate_session": True,
            },
            "zone_4_success_completion_gate": {
                "minimum_planned_work_fraction_completed": 0.8,
                "applies_to": "planned_zone_4_work_duration_only",
                "exclude_warmup_recovery_and_cooldown": True,
                "below_threshold_interpretation": "insufficient_unlock_evidence_not_failed_training",
            },
            "zone_4_success_intensity_gate": {
                "minimum_time_weighted_fraction_in_zone_4": 0.5,
                "denominator": "valid_heart_rate_time_during_completed_zone_4_work",
                "minimum_valid_heart_rate_coverage_fraction": 0.8,
                "missing_heart_rate_imputation_allowed": False,
                "insufficient_coverage_interpretation": "indeterminate_not_success_or_failure",
                "heart_rate_smoothing": {
                    "statistic": "rolling_median",
                    "window_seconds": 10,
                    "minimum_samples_per_window": 8,
                    "maximum_gap_within_window_seconds": 2,
                },
                "maximum_contiguous_invalid_time_within_work_interval_seconds": 10,
                "contiguous_gap_scope": "invalidate_affected_work_interval_only",
                "invalid_work_interval_counts_as_uncompleted": True,
                "ignore_gaps_during": ["pause", "recovery", "cooldown"],
                "zone_5_counts_toward_zone_4_fraction": False,
                "maximum_time_weighted_fraction_in_zone_5": 0.1,
                "above_zone_5_limit_interpretation": "not_controlled_zone_4_unlock_evidence",
                "exclude_warmup_recovery_and_cooldown": True,
                "below_threshold_interpretation": "insufficient_intensity_evidence",
            },
            "zone_4_success_perceived_exertion_gate": {
                "scale": "cr10_0_to_10",
                "feedback_required": False,
                "no_rpe_reported_behavior": "use_objective_gates_without_penalty",
                "supportive_rpe_min": 7,
                "supportive_rpe_max": 8,
                "rpe_at_or_above_9_behavior": "not_controlled_zone_4_evidence",
                "rpe_at_or_below_6_behavior": "indeterminate_review_heart_rate_baselines",
                "text_equivalents_allowed": True,
                "role": "secondary_evidence_not_heart_rate_replacement",
            },
            "zone_4_success_observation_gate": {
                "candidate_status_immediately_after_session": True,
                "minimum_observation_hours": 48,
                "feedback_required": False,
                "no_reply_interpretation": "no_recovery_problem_reported",
                "reported_delayed_warning_or_acute_injury_invalidates_session": True,
                "late_linked_report_can_revoke_qualification": True,
            },
            "qualifying_zone_4_session": {
                "trainlab_prescription_link_required": True,
                "start_time_is_user_selected": True,
                "sport": "running",
                "work_interval_seconds": {"minimum": 180, "maximum": 300},
                "planned_zone_4_work_seconds": {"minimum": 720, "maximum": 960},
                "warmup_minimum_seconds": 600,
                "cooldown_minimum_seconds": 600,
                "recovery_target_zone": "zone_1",
                "activity_match_uses": [
                    "plan_date",
                    "sport",
                    "work_interval_count",
                    "work_interval_duration",
                ],
                "activity_match_ignores_start_clock_time": True,
            },
            "zone_5_continuous_prescription_allowed": False,
        },
        "lower_observations_can_reduce_baseline": False,
        "fallback_formula": "tanaka_208_minus_0_7_age",
        "fallback_confidence": "low",
        "fallback_allows_quality_sessions": False,
        "fallback_allowed_target_zones": ["zone_1", "zone_2"],
        "fallback_zone_presentation": "approximate_with_rpe_and_talk_test_required",
        "fallback_disallowed_target_zones": ["zone_3", "zone_4", "zone_5"],
        "fallback_candidate_bpm": 185,
    }
    connection.close()


def test_old_sensor_data_does_not_enter_window(settings):
    connection = connect(settings.database_path)
    payload = build_runtime_input(
        settings,
        connection,
        slot="evening",
        as_of=datetime(2026, 5, 1, 20, 0, tzinfo=ZoneInfo("Asia/Singapore")),
    )
    assert payload["activities"]["summaries"] == []
    assert all(value == [] for value in payload["activities"]["details"].values())
    connection.close()


def test_week_month_boundaries_dependencies_and_atomic_state(settings):
    connection = connect(settings.database_path)
    as_of = datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    first = ensure_summaries(settings, connection, as_of=as_of)
    second = ensure_summaries(settings, connection, as_of=as_of)
    assert second["generated"]["weekly"] == 0
    assert second["generated"]["monthly"] == 0
    weekly = connection.execute(
        "SELECT period_start_local, period_end_local FROM period_summaries WHERE period_type='weekly' LIMIT 1"
    ).fetchone()
    start = datetime.fromisoformat(weekly["period_start_local"]).date()
    end = datetime.fromisoformat(weekly["period_end_local"]).date()
    assert start.weekday() == 0 and end.weekday() == 6 and (end - start).days == 6
    monthly = connection.execute(
        "SELECT summary_json FROM period_summaries WHERE period_type='monthly' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    import json

    summary = json.loads(monthly["summary_json"])
    assert all(item["local_date"][:7] == summary["period_start_local"][:7] for item in summary["daily_rollups"])
    assert (settings.path("state_directory") / "compression_state.json").is_file()
    json.loads((settings.path("state_directory") / "compression_state.json").read_text(encoding="utf-8"))
    connection.close()


def test_new_daily_period_requires_no_code_change(settings):
    compression = copy.deepcopy(settings.compression)
    compression["periods"].insert(
        0,
        {"name": "daily", "kind": "day", "enabled": True, "timezone": "Asia/Singapore", "source": "raw_rollups"},
    )
    current = replace(settings, compression=compression)
    connection = connect(current.database_path)
    status = ensure_summaries(current, connection, as_of=datetime(2026, 4, 20, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")))
    assert status["generated"]["daily"] > 0
    connection.close()
