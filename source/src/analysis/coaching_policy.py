"""Small deterministic gates shared by the v2 coaching contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

HardLoadKind = Literal["running_sos", "hard_climbing", "other"]


def hard_load_decision(
    scheduled: list[tuple[date, HardLoadKind]],
    candidate_date: date,
    candidate_kind: HardLoadKind,
    *,
    max_hard_loads: int | None,
    min_gap_days: int | None,
) -> tuple[bool, str]:
    """Return whether a hard session can be added without stacking load."""

    if candidate_kind == "other":
        return True, "not_hard_load"
    prior = sorted(
        (day, kind)
        for day, kind in scheduled
        if day < candidate_date and kind != "other"
    )
    if max_hard_loads is not None and len(prior) >= max_hard_loads:
        return False, "hard_load_max_reached"
    if min_gap_days is not None and prior:
        gap = (candidate_date - prior[-1][0]).days
        if gap < min_gap_days:
            return False, "hard_load_recovery_gap"
    return True, "allowed"


def progression_decision(
    *,
    recovery_ready: bool,
    adherence_stable: bool,
    capacity_change: Literal["volume", "intensity", "none"] = "none",
) -> tuple[Literal["advance", "hold", "deload"], str]:
    if not recovery_ready:
        return "deload", "recovery_not_ready"
    if not adherence_stable:
        return "hold", "adherence_or_evidence_unstable"
    if capacity_change not in {"volume", "intensity", "none"}:
        return "hold", "invalid_progression_dimension"
    return (
        ("advance", capacity_change)
        if capacity_change != "none"
        else ("hold", "no_single_dimension_change")
    )
