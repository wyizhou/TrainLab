"""All-sport summary with a separate strictly running-source analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_evidence,
    coaching_facts,
    model_job,
)


def validate(output: Any, payload: dict[str, Any], *, root: Path) -> None:
    try:
        model_job.schema_validator(coaching_contract.schema("summary")).validate(output)
    except Exception:
        raise ValueError("coaching_summary_schema_invalid") from None
    if payload["stage"] != "summary":
        raise ValueError("coaching_summary_stage_invalid")
    coaching_facts.dates(payload)
    for claim in output["core_conclusions"]:
        coaching_evidence.validate_claim(claim, payload, root=root)
    running = output["running_analysis"]
    for claim in [
        running["overview"],
        running["plan_comparison"],
        *running["technique"],
    ]:
        coaching_evidence.validate_claim(claim, payload, root=root, running_only=True)
    expected = {
        (a["activity_ref"], s["session_ordinal"])
        for a, s in coaching_evidence.sessions(payload)
        if s["sport"] != "running"
    }
    actual = [(x["activity_ref"], x["session_ordinal"]) for x in output["other_sports"]]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("coaching_other_sports_incomplete")
    for item in output["other_sports"]:
        coaching_evidence.validate_claim(item["explanation"], payload, root=root)
        for ref in item["explanation"]["evidence"]:
            if ref["source"] in ("current", "detail") and (
                ref["activity_ref"],
                ref["session_ordinal"],
            ) != (item["activity_ref"], item["session_ordinal"]):
                raise ValueError("coaching_other_sport_evidence_mismatch")
    coaching_evidence.guard_text(output, future=False)
