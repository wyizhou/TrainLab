"""Fixed running course and auditable load comparisons; no medical thresholds."""

from __future__ import annotations

from math import isclose
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_evidence,
    coaching_facts,
    model_job,
)


def validate_shape(output: Any) -> None:
    try:
        model_job.schema_validator(coaching_contract.schema("plan")).validate(output)
    except Exception:
        raise ValueError("coaching_plan_schema_invalid") from None


def load(output: dict[str, Any]) -> dict[str, Any]:
    workouts = [d["workout"] for d in output["days"] if d["workout"] is not None]
    hard = [w for w in workouts if w["hard_load"]]
    return {
        "distance_m": sum(w["dose"]["value"] for w in workouts)
        if all(w["dose"]["unit"] == "meters" for w in workouts)
        else None,
        "hard_count": len(hard),
        "peak_rpe": max(
            (s["rpe"] for w in workouts for g in w["steps"] for s in g["steps"]),
            default=0,
        ),
        "hard_seconds": sum(w["dose"]["value"] for w in hard)
        if all(w["dose"]["unit"] == "seconds" for w in hard)
        else None,
        "hard_meters": sum(w["dose"]["value"] for w in hard)
        if all(w["dose"]["unit"] == "meters" for w in hard)
        else None,
    }


def progression(output: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    current = load(output)
    histories = sorted(
        payload["running_history"], key=lambda h: h["period_end_utc"], reverse=True
    )
    baseline = None
    previous = None
    # Only the latest preceding week is a comparable course baseline. Older
    # plans or arbitrary R2 structures do not manufacture a recent workload.
    for h in histories[:1]:
        old = h["running"].get("plan", {})
        if (
            old.get("schema_version") == "fit_running_plan_v1"
            and h["period_end_utc"] == payload["period_start_utc"]
        ):
            validate_shape(old)
            if model_job.sha(h["running"]) != h["running_sha256"]:
                raise ValueError("coaching_history_binding_invalid")
            previous = load(old)
            baseline = {
                "period_end_utc": h["period_end_utc"],
                "running_sha256": h["running_sha256"],
                "method": "previous_fixed_plan_not_actual_completion",
            }
    dimensions = {}
    for key in current:
        before = previous[key] if previous is not None else None
        now = current[key]
        dimensions[key] = {
            "before": before,
            "after": now,
            "change": "unknown"
            if before is None or now is None
            else "increased"
            if now > before
            else "decreased"
            if now < before
            else "unchanged",
        }
    intensity = [
        dimensions[k]["change"]
        for k in ("hard_count", "peak_rpe", "hard_seconds", "hard_meters")
    ]
    intensity_change = (
        "increased"
        if "increased" in intensity
        else "unknown"
        if "unknown" in intensity
        else "no_observed_increase"
    )
    if (
        dimensions["distance_m"]["change"] == "increased"
        and intensity_change == "increased"
    ):
        raise ValueError("coaching_double_progression")
    return {
        "baseline": baseline,
        "dimensions": dimensions,
        "distance_change": dimensions["distance_m"]["change"],
        "intensity_change": intensity_change,
        "limitations": [
            "Explicit planned dose, hard-course count and subjective peak RPE are comparison dimensions, not a physiological intensity proof.",
            "Missing baseline or incompatible dose units remain unknown; absence of a measured increase does not prove overall intensity unchanged.",
        ],
    }


def sos_supported(output: dict[str, Any]) -> bool:
    # Any valid running/goal rationale can justify an initial SOS choice;
    # no prior SOS label or numeric readiness threshold is required.
    return output["rationale"]["status"] == "supported" and bool(
        output["rationale"]["evidence"]
    )


def project(output: Any, payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    validate_shape(output)
    if payload["stage"] != "plan":
        raise ValueError("coaching_plan_stage_invalid")
    dates = coaching_facts.dates(payload)
    coaching_evidence.validate_claim(
        output["rationale"], payload, root=root, running_only=True
    )
    hard_days = []
    for index, day in enumerate(output["days"]):
        w = day["workout"]
        if (day["kind"] == "rest") != (w is None):
            raise ValueError("coaching_rest_workout_invalid")
        if w is None:
            continue
        coaching_evidence.guard_text(w, future=True)
        steps = [(g["repeat"], s) for g in w["steps"] for s in g["steps"]]
        if any(s["unit"] != w["dose"]["unit"] for _, s in steps) or not isclose(
            sum(n * s["value"] for n, s in steps),
            w["dose"]["value"],
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("coaching_dose_mismatch")
        hard = w["kind"] in ("long", "tempo", "intervals") or any(
            s["effort"] == "hard" for _, s in steps
        )
        if w["hard_load"] != hard:
            raise ValueError("coaching_hard_load_mismatch")
        if hard:
            hard_days.append(index)
        if w["kind"] in ("tempo", "intervals") and not sos_supported(output):
            raise ValueError("coaching_sos_evidence_missing")
    if len(hard_days) > 3 or any(b - a < 3 for a, b in zip(hard_days, hard_days[1:])):
        raise ValueError("coaching_hard_load_spacing")
    coaching_evidence.guard_text(output["rationale"], future=False)
    coaching_evidence.guard_text(output["progression_limitations"], future=True)
    comparison = progression(output, payload)
    return {
        "days": [
            {"date": date, **model_job.clone(day)}
            for date, day in zip(dates, output["days"])
        ],
        "rationale": model_job.clone(output["rationale"]),
        "hard_load_count": len(hard_days),
        "progression": comparison,
        "progression_limitations": list(output["progression_limitations"]),
        "policy": model_job.clone(output["policy"]),
        "original_plan_sha256": model_job.sha(output),
    }
