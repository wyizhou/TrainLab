"""Deterministic activity lifecycle decisions from bounded inventory evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

ActivityState = Literal["active", "suspected_missing", "provider_deleted"]


@dataclass(frozen=True)
class ActivityInventoryObservation:
    """One validated inventory observation and its absence-proof boundary."""

    observation_id: str
    mode: str
    start_local_date: date | None
    through_local_date: date
    seen_ids: frozenset[str]
    complete: bool
    absence_proven: bool
    observed_at_utc: str = ""

    def covers(self, local_date: date) -> bool:
        if local_date > self.through_local_date:
            return False
        return self.start_local_date is None or local_date >= self.start_local_date

    def sees(self, provider_activity_id: str) -> bool:
        return provider_activity_id in self.seen_ids


def next_activity_state(
    current_state: str,
    provider_activity_id: str,
    local_date: date,
    observation: ActivityInventoryObservation,
    *,
    last_transition_at_utc: str | None = None,
) -> str:
    """Return the next state without treating unproven absence as deletion."""

    if observation.sees(provider_activity_id):
        if (
            current_state == "provider_deleted"
            and last_transition_at_utc
            and observation.observed_at_utc <= last_transition_at_utc
        ):
            return current_state
        return "active"
    if (
        not observation.complete
        or not observation.absence_proven
        or not observation.covers(local_date)
    ):
        return current_state
    if current_state == "active":
        return "suspected_missing"
    if current_state == "suspected_missing":
        return "provider_deleted"
    return current_state
