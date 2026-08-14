from datetime import date

from src.analysis.coaching_policy import hard_load_decision, progression_decision


def test_running_sos_and_hard_climbing_share_recovery_gate():
    allowed, reason = hard_load_decision(
        [(date(2026, 8, 10), "hard_climbing")],
        date(2026, 8, 11),
        "running_sos",
        max_hard_loads=3,
        min_gap_days=2,
    )
    assert not allowed and reason == "hard_load_recovery_gap"


def test_progression_changes_one_dimension_or_holds():
    assert progression_decision(
        recovery_ready=True, adherence_stable=True, capacity_change="volume"
    ) == ("advance", "volume")
    assert progression_decision(recovery_ready=False, adherence_stable=True) == (
        "deload",
        "recovery_not_ready",
    )
