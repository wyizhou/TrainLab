"""Stage identity and running-session permissions; never a second budget."""

from __future__ import annotations

from typing import Any

from skills._shared.fit_weekly import fit_time


def require(stage: str | None, *, legacy: bool = False) -> str | None:
    if stage in ("plan", "summary") or stage is None and legacy:
        return stage
    raise ValueError("model_stage_required")


def job_key(end: str, stage: str | None = None) -> str:
    require(stage, legacy=True)
    return "model-job:" + end + (":" + stage if stage else "")


def legacy_goal(payload: dict[str, Any]) -> bool:
    snapshot = payload.get("goal_snapshot")
    if not isinstance(snapshot, dict):
        return False
    goal = snapshot.get("goal")
    return isinstance(goal, dict) and goal.get("schema_version") == "training_goal_v1"


def authorize(
    stage: str | None, activity: dict[str, Any], request: dict[str, Any]
) -> None:
    require(stage, legacy=True)
    if stage != "plan":
        return
    origin = fit_time.utc_time(activity["start_utc"])
    start, end = request["start_offset_seconds"], request["end_offset_seconds"]
    permitted = []
    for session in activity["sessions"]:
        a = (fit_time.utc_time(session["start_utc"]) - origin).total_seconds()
        b = (fit_time.utc_time(session["end_utc"]) - origin).total_seconds()
        if a < end and start < b:
            if session["sport"] != "running":
                raise ValueError("detail_stage_forbidden")
            permitted.append((a, b))
    cursor = start
    for a, b in sorted(permitted):
        if a > cursor:
            break
        cursor = max(cursor, b)
    if cursor < end:
        raise ValueError("detail_stage_forbidden")
