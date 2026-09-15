"""FIT activity time precision, separate from whole-second action authorization."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any


def utc_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value
    ):
        raise ValueError("fit_time_invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def millisecond_offset(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    decimal = Decimal(str(value))
    return (
        decimal.is_finite()
        and decimal >= 0
        and decimal * 1000 == (decimal * 1000).to_integral_value()
    )


def session_laps(
    session: dict[str, Any],
    laps: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    items = []
    for lap in laps:
        touches = [
            s for s in sessions if lap["start"] < s["end"] and lap["end"] > s["start"]
        ]
        owners = [
            s
            for s in touches
            if s["start"] <= lap["start"] < s["end"] and lap["end"] - s["end"] < 1
        ]
        if session not in touches:
            continue
        if len(touches) != 1 or len(owners) != 1 or owners[0] is not session:
            return [], True
        items.append({**lap, "precision_compatible": lap["end"] > session["end"]})
    ordered = sorted(items, key=lambda x: x["start"])
    for a, b in zip(ordered, ordered[1:]):
        if (
            a["start"] == b["start"]
            or a["end"] >= b["end"]
            or a["end"] - b["start"] >= 1
        ):
            return [], True
        if a["end"] > b["start"]:
            a["precision_compatible"] = b["precision_compatible"] = True
    if any(x["precision_compatible"] for x in ordered) and items != ordered:
        return [], True
    return ordered, False
