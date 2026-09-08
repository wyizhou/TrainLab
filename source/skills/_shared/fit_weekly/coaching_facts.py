"""Host dates and all-sport statistics, derived only from the frozen stage input."""

from __future__ import annotations

from typing import Any

from skills._shared.fit_weekly import (
    coaching_evidence,
    model_job,
    sync_calendar,
    weekly_evidence,
)


def dates(payload: dict[str, Any]) -> list[str]:
    slot = sync_calendar.weekly_slot(payload["period_end_utc"])
    if (
        slot["end_utc"] != payload["period_end_utc"]
        or slot["start_utc"] != payload["period_start_utc"]
        or slot["plan_dates"] != payload["next_plan_dates"]
    ):
        raise ValueError("coaching_period_invalid")
    return list(slot["plan_dates"])


def total(values: list[Any]) -> dict[str, Any]:
    known = [v for v in values if v is not None]
    return {
        "value": sum(known) if known else None,
        "available_count": len(known),
        "missing_count": len(values) - len(known),
        "status": "complete"
        if known and len(known) == len(values)
        else "partial"
        if known
        else "unknown",
    }


def build(payload: dict[str, Any]) -> dict[str, Any]:
    inventory = []
    pairs = coaching_evidence.sessions(payload)
    names = {
        a["activity_ref"]: a.get("activity_name")
        for a in payload.get("current_week", {}).get("activity_sources", [])
    }
    for activity, session in pairs:
        inventory.append(
            {
                "activity_ref": activity["activity_ref"],
                "fit_sha256": activity["fit_sha256"],
                "session_ordinal": session["session_ordinal"],
                "sport": session["sport"],
                "start_utc": session["start_utc"],
                "end_utc": session["end_utc"],
                "activity_name": model_job.clone(names.get(activity["activity_ref"])),
                "distance_m": session["provider_summary"]["distance_m"],
                "timer_seconds": session["provider_summary"]["timer_seconds"],
                "elapsed_seconds": session["elapsed_seconds"],
                "valid_seconds": session["valid_seconds"],
                "sample_covered_seconds": session["sample_covered_seconds"],
                "gap_seconds": session["gap_seconds"],
                "historical_heart_rate": {
                    k: session["provider_summary"][k]
                    for k in ("avg_heart_rate_bpm", "max_heart_rate_bpm")
                },
                "recorded_session_hr_zones": model_job.clone(session["hr_zones"]),
                "methods": model_job.clone(activity["methods"]),
                "limitations": list(session["limitations"]),
            }
        )
    statistics = []
    for sport in sorted({s["sport"] for _, s in pairs}):
        rows = [row for row in inventory if row["sport"] == sport]
        statistics.append(
            {
                "sport": sport,
                "session_count": len(rows),
                "activity_count": len({row["activity_ref"] for row in rows}),
                "distance_m": total([row["distance_m"] for row in rows]),
                "timer_seconds": total([row["timer_seconds"] for row in rows]),
                "method": "sum_available_provider_session_values",
            }
        )
    return {
        "period_start_utc": payload["period_start_utc"],
        "period_end_utc": payload["period_end_utc"],
        "plan_dates": dates(payload),
        "inventory": inventory,
        "statistics": statistics,
        "activity_count": len({row["activity_ref"] for row in inventory}),
        "session_count": len(inventory),
        "unplaced_no_fit": [
            {
                **model_job.clone(row),
                "activity_name": model_job.clone(
                    row.get("activity_name", weekly_evidence.missing_name())
                ),
            }
            for row in payload.get("current_week", {}).get("unplaced_no_fit", [])
        ],
        "limitations": list(payload.get("current_week", {}).get("limitations", [])),
    }
