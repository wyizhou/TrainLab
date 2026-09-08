"""Deterministic stage projections from the one immutable weekly material set.

The v1/v2 weekly context remains an internal Host snapshot, never a planning
payload. In particular its all-sport digest and scope do not leak into plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_detail,
    model_job,
    stage_policy,
    storage,
    weekly_context,
)
from skills._shared.scripts.schema_validation import validate_payload


def project(
    materials: dict[str, Any], stage: str, plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    stage_policy.require(stage)
    week = materials["current_week"]
    body = {
        "schema_version": "fit_weekly_stage_input_v1",
        "stage": stage,
        "period_start_utc": week["period_start_utc"],
        "period_end_utc": week["period_end_utc"],
        "next_plan_dates": model_job.clone(week["next_plan_dates"]),
        "goal_snapshot": model_job.clone(materials["goal_snapshot"]),
        "provider_calls": 0,
        "external_actions": 0,
    }
    if stage == "plan":
        running = []
        for activity in week["activities"]:
            sessions = [s for s in activity["sessions"] if s["sport"] == "running"]
            if sessions:
                running.append(
                    {
                        **{
                            k: model_job.clone(activity[k])
                            for k in (
                                "activity_ref",
                                "fit_sha256",
                                "parser_version",
                                "start_utc",
                                "methods",
                            )
                        },
                        "sessions": model_job.clone(sessions),
                    }
                )
        body["running_activities"] = running
        body["running_history"] = [
            {
                "period_end_utc": h["period_end_utc"],
                "running_sha256": model_job.sha(h["report"]["running"]),
                "running": model_job.clone(h["report"]["running"]),
            }
            for h in materials["history_reports"]
            if h.get("schema_version") == "fit_weekly_history_v2"
        ]
    else:
        if plan is None:
            raise ValueError("weekly_plan_missing")
        body.update(
            current_week=model_job.clone(week),
            history_reports=model_job.clone(materials["history_reports"]),
            fixed_plan=model_job.clone(plan),
        )
    weekly_context.check_text(
        body, allow_sports_location=week["parser_version"] == "fit-summary-2"
    )
    if validate_payload(body, "fit_weekly_stage_input_v1"):
        raise ValueError("weekly_stage_input_invalid")
    return body


def verify_plan(
    root: Path,
    end: str,
    plan: dict[str, Any] | None,
    validate_plan: model_job.ResultValidator | None,
) -> None:
    if not callable(validate_plan):
        raise ValueError("weekly_plan_validator_missing")
    with storage.open_store(root) as db:
        key = stage_policy.job_key(end, "plan")
        intent, saved = (
            fit_detail.get(db, key + ":intent"),
            fit_detail.get(db, key + ":result"),
        )
        if intent is None or saved is None:
            raise ValueError("weekly_plan_missing")
        binding, request = intent
        if (
            binding != model_job.sha(request)
            or saved[0] != binding
            or request.get("stage") != "plan"
            or request["period_end_utc"] != end
        ):
            raise ValueError("weekly_plan_binding_invalid")
        capture = saved[1]
        path = model_job.capture_path(root, end, stage="plan")
        storage.private_entry(path.parent.parent, directory=True)
        storage.private_entry(path.parent, directory=True)
        storage.private_entry(path, nonempty=True)
        if path.read_bytes() != storage.canonical(capture).encode():
            raise ValueError("weekly_plan_binding_invalid")
        model_job.check_capture(
            capture,
            request,
            model_job.schema_validator(request["response_schema"]),
            validate_plan,
        )
        expected = {
            "period_end_utc": end,
            "request_sha256": binding,
            "capture_sha256": model_job.sha(capture),
            "result_sha256": model_job.sha(capture["output"]),
            "plan": capture["output"],
        }
        if capture["receipt"]["status"] != "succeeded" or storage.canonical(
            plan
        ) != storage.canonical(expected):
            raise ValueError("weekly_plan_binding_invalid")


def freeze(
    root: Path,
    end: str,
    stage: str,
    *,
    validate_history: model_job.ResultValidator,
    plan: dict[str, Any] | None = None,
    validate_plan: model_job.ResultValidator | None = None,
) -> dict[str, Any]:
    stage_policy.require(stage)
    if stage == "summary":
        verify_plan(root, end, plan, validate_plan)
    materials = weekly_context.freeze(root, end, validate_report=validate_history)
    body = project(materials, stage, plan)
    key = "weekly-stage-input:" + end + ":" + stage
    with storage.open_store(root) as db:
        fit_detail.put(db, key, model_job.sha(body), body)
    return body


def validator(
    root: Path,
    end: str,
    stage: str,
    *,
    validate_history: model_job.ResultValidator,
    plan: dict[str, Any] | None = None,
    validate_plan: model_job.ResultValidator | None = None,
) -> model_job.InputValidator:
    stage_policy.require(stage)

    def validate(body: dict[str, Any]) -> None:
        if stage == "summary":
            verify_plan(root, end, plan, validate_plan)
        materials = weekly_context.freeze(root, end, validate_report=validate_history)
        expected = project(materials, stage, plan)
        with storage.open_store(root) as db:
            saved = fit_detail.get(db, "weekly-stage-input:" + end + ":" + stage)
            if saved != (model_job.sha(expected), expected) or storage.canonical(
                body
            ) != storage.canonical(expected):
                raise ValueError("weekly_stage_input_invalid")

    return validate
