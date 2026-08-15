from datetime import date

import pytest

from src.garmin.lifecycle import ActivityInventoryObservation, next_activity_state


def _observation(
    *,
    seen: set[str],
    complete: bool = True,
    absence_proven: bool = True,
    start: date | None = None,
    through: date = date(2026, 8, 9),
) -> ActivityInventoryObservation:
    return ActivityInventoryObservation(
        observation_id="observation-1",
        mode="repair",
        start_local_date=start,
        through_local_date=through,
        seen_ids=frozenset(seen),
        complete=complete,
        absence_proven=absence_proven,
        observed_at_utc="2026-08-10T00:00:00Z",
    )


def test_presence_reactivates_and_two_distinct_absences_delete() -> None:
    day = date(2026, 8, 8)
    first_absence = _observation(seen=set(), start=day, through=day)
    second_absence = ActivityInventoryObservation(
        observation_id="observation-2",
        mode="repair",
        start_local_date=day,
        through_local_date=day,
        seen_ids=frozenset(),
        complete=True,
        absence_proven=True,
        observed_at_utc="2026-08-11T00:00:00Z",
    )
    assert (
        next_activity_state("active", "42", day, first_absence) == "suspected_missing"
    )
    assert (
        next_activity_state("suspected_missing", "42", day, second_absence)
        == "provider_deleted"
    )
    assert (
        next_activity_state("provider_deleted", "42", day, _observation(seen={"42"}))
        == "active"
    )


@pytest.mark.parametrize(
    ("complete", "absence_proven"),
    [(False, False), (True, False), (False, True)],
)
def test_unproven_absence_never_advances_state(
    complete: bool, absence_proven: bool
) -> None:
    observation = _observation(
        seen=set(), complete=complete, absence_proven=absence_proven
    )
    assert (
        next_activity_state("active", "42", date(2026, 8, 8), observation) == "active"
    )


def test_out_of_window_absence_never_advances_state() -> None:
    observation = _observation(
        seen=set(), start=date(2026, 8, 9), through=date(2026, 8, 9)
    )
    assert (
        next_activity_state("active", "42", date(2026, 8, 8), observation) == "active"
    )


def test_old_seen_evidence_does_not_resurrect_provider_deleted_activity() -> None:
    observation = _observation(seen={"42"})
    assert (
        next_activity_state(
            "provider_deleted",
            "42",
            date(2026, 8, 8),
            observation,
            last_transition_at_utc="2026-08-11T00:00:00Z",
        )
        == "provider_deleted"
    )
