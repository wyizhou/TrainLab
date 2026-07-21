from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from trainlab.context import build_runtime_input
from trainlab.db import connect
from trainlab.zones import (
    assess_zone_4_session,
    calculate_hrr_zones,
    calculate_prescription_targets,
    classify_bpm,
    evaluate_zone_5_unlock,
)


SINGAPORE = ZoneInfo("Asia/Singapore")


def _policy(settings):
    connection = connect(settings.database_path)
    try:
        payload = build_runtime_input(
            settings,
            connection,
            slot="morning",
            as_of=datetime(2026, 4, 18, 9, 0, tzinfo=SINGAPORE),
        )
        return payload["policy"]["heart_rate_intensity"]
    finally:
        connection.close()


def test_hrr_zones_are_contiguous_and_rounded_up(settings):
    policy = _policy(settings)
    zones = calculate_hrr_zones(60, 190, policy["zones"])
    assert zones == {
        "zone_1": {"minimum_percent": 0.0, "minimum_bpm": 60, "maximum_bpm": 137},
        "zone_2": {"minimum_percent": 60.0, "minimum_bpm": 138, "maximum_bpm": 150},
        "zone_3": {"minimum_percent": 70.0, "minimum_bpm": 151, "maximum_bpm": 163},
        "zone_4": {"minimum_percent": 80.0, "minimum_bpm": 164, "maximum_bpm": 176},
        "zone_5": {"minimum_percent": 90.0, "minimum_bpm": 177, "maximum_bpm": 190},
    }
    assert classify_bpm(59, zones) == "below_zone_1"
    assert classify_bpm(138, zones) == "zone_2"
    assert classify_bpm(191, zones) == "above_zone_5"
    assert calculate_prescription_targets(60, 190, policy["zone_guidance"]) == {
        "zone_1": {"minimum_bpm": 125, "maximum_bpm": 137},
        "zone_2": {"minimum_bpm": 138, "maximum_bpm": 150},
        "zone_3": {"minimum_bpm": 151, "maximum_bpm": 163},
        "zone_4": {"minimum_bpm": 164, "maximum_bpm": 176},
        "zone_5": {"minimum_bpm": 177, "maximum_bpm": 190},
    }


def test_zone_4_session_is_pending_then_qualifies(settings):
    policy = _policy(settings)
    unlock = policy["maximum_heart_rate_source"]["supported_baseline_zone_unlock"]
    completed = datetime(2026, 7, 1, 8, 0, tzinfo=SINGAPORE)
    values = {
        "planned_work_seconds": 720,
        "completed_work_seconds": 600,
        "valid_heart_rate_seconds": 500,
        "zone_4_seconds": 300,
        "zone_5_seconds": 50,
        "rpe": 7,
    }
    pending = assess_zone_4_session(unlock, completed_at=completed, as_of=completed + timedelta(hours=24), **values)
    assert pending["status"] == "pending_observation"
    qualified = assess_zone_4_session(unlock, completed_at=completed, as_of=completed + timedelta(hours=48), **values)
    assert qualified["status"] == "qualified"
    assert qualified["qualified"] is True


def test_zone_4_gates_remain_conservative(settings):
    policy = _policy(settings)
    unlock = policy["maximum_heart_rate_source"]["supported_baseline_zone_unlock"]
    completed = datetime(2026, 7, 1, 8, 0, tzinfo=SINGAPORE)
    base = {
        "completed_at": completed,
        "as_of": completed + timedelta(hours=72),
        "planned_work_seconds": 720,
        "completed_work_seconds": 600,
        "valid_heart_rate_seconds": 500,
        "zone_4_seconds": 300,
        "zone_5_seconds": 50,
        "rpe": 7,
    }
    assert assess_zone_4_session(unlock, **{**base, "valid_heart_rate_seconds": 400})["status"] == "indeterminate"
    assert assess_zone_4_session(unlock, **{**base, "zone_5_seconds": 70})["status"] == "not_qualifying"
    assert assess_zone_4_session(unlock, **{**base, "rpe": 9})["status"] == "not_qualifying"
    assert assess_zone_4_session(unlock, **{**base, "rpe": 6})["status"] == "indeterminate"
    assert assess_zone_4_session(unlock, **{**base, "warning_symptom_reported": True})["status"] == "rejected"
    invalid = assess_zone_4_session(
        unlock,
        **{
            **base,
            "invalidated_work_seconds": 180,
            "longest_contiguous_invalid_seconds": 11,
        },
    )
    assert invalid["status"] == "not_qualifying"


def test_zone_5_unlock_spacing_blockers_and_expiry(settings):
    policy = _policy(settings)
    unlock = policy["maximum_heart_rate_source"]["supported_baseline_zone_unlock"]
    first_at = datetime(2026, 7, 1, 8, 0, tzinfo=SINGAPORE)
    second_at = first_at + timedelta(hours=96)
    session_values = {
        "planned_work_seconds": 720,
        "completed_work_seconds": 600,
        "valid_heart_rate_seconds": 500,
        "zone_4_seconds": 300,
        "zone_5_seconds": 50,
        "rpe": 7,
    }
    first = assess_zone_4_session(unlock, completed_at=first_at, as_of=second_at + timedelta(hours=48), **session_values)
    second = assess_zone_4_session(unlock, completed_at=second_at, as_of=second_at + timedelta(hours=48), **session_values)
    now = second_at + timedelta(hours=48)
    assert evaluate_zone_5_unlock(policy, [first, second], as_of=now)["status"] == "unlocked"
    assert evaluate_zone_5_unlock(policy, [first, second], as_of=now, active_blockers=["active_injury"])["status"] == "temporarily_locked"
    assert evaluate_zone_5_unlock(policy, [first, second], as_of=second_at + timedelta(days=22))["status"] == "expired_needs_one_zone_4_revalidation"
    assert evaluate_zone_5_unlock(policy, [first, second], as_of=second_at + timedelta(days=43))["status"] == "expired_full_reset"

    after_full_reset_at = second_at + timedelta(days=43)
    after_full_reset = assess_zone_4_session(
        unlock,
        completed_at=after_full_reset_at,
        as_of=after_full_reset_at + timedelta(hours=48),
        **session_values,
    )
    one_new = evaluate_zone_5_unlock(
        policy,
        [first, second, after_full_reset],
        as_of=after_full_reset_at + timedelta(hours=48),
    )
    assert one_new["status"] == "locked"
    assert one_new["qualifying_sessions"] == 1
