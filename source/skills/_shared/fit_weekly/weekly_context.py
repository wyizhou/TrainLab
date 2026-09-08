"""Freeze one self-contained weekly input: all FIT facts, goal and full reports.

Only Host code reads the instance. The model receives this projection, never
the goal file, SQLite, sync captures or a pathname. Replays use the original
snapshot even after the user edits the goal or another report is archived.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema

from skills._shared.fit_weekly import (
    fit_detail,
    fit_parse,
    input_privacy,
    model_job,
    storage,
    weekly_evidence,
    weekly_history,
)
from skills._shared.scripts.training_goal_v1 import parse_training_goal_v1

GOAL_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas/training_goal_v1.schema.json"
)


def context_suffix(parser_version: str) -> str:
    return {"fit-summary-1": "v1", "fit-summary-2": "v2"}[
        fit_parse.require_parser_version(parser_version)
    ]


def check_text(value: Any, *, allow_sports_location: bool = False) -> None:
    input_privacy.check(value, allow_sports_location=allow_sports_location)


def goal(
    root: Path, *, allow_sports_location: bool = False
) -> tuple[str, dict[str, Any]]:
    try:
        p = root / "goal.md"
        storage.private_entry(p, nonempty=True)
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        check_text(text, allow_sports_location=allow_sports_location)
        parsed = parse_training_goal_v1(text)
        check_text(parsed, allow_sports_location=allow_sports_location)
        return storage.digest(raw), {"sha256": model_job.sha(parsed), "goal": parsed}
    except Exception:
        raise ValueError("weekly_goal_invalid") from None


def evidence(db: sqlite3.Connection, end: str) -> tuple[str, dict[str, Any]]:
    item = fit_detail.get(db, "weekly-evidence:" + end)
    if item is None or item[0] != model_job.sha(item[1]):
        raise ValueError("weekly_evidence_missing")
    weekly_evidence.validate(item[1])
    if item[1]["period_end_utc"] != end:
        raise ValueError("weekly_evidence_invalid")
    return item


def project_evidence(body: dict[str, Any]) -> dict[str, Any]:
    weekly_evidence.validate(body)
    return {
        **{
            k: model_job.clone(body[k])
            for k in (
                "parser_version",
                "period_start_utc",
                "period_end_utc",
                "next_plan_dates",
                "activities",
                "activity_sources",
                "unplaced_no_fit",
                "counts",
                "limitations",
                "provider_calls",
                "external_actions",
            )
        },
        "schema_version": "fit_weekly_model_evidence_"
        + context_suffix(body["parser_version"]),
        "inventory_as_of_utc": body["sources"]["inventory_as_of_utc"],
    }


def checked(
    db: sqlite3.Connection,
    root: Path,
    end: str,
    saved: tuple[str, dict[str, Any]],
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    try:
        binding, record = saved
        original_sha, original = evidence(db, end)
        suffix = context_suffix(original["parser_version"])
        if (
            set(record)
            != {"schema_version", "evidence_sha256", "goal_source_sha256", "context"}
            or record["schema_version"] != "fit_weekly_context_record_" + suffix
        ):
            raise ValueError("shape")
        storage.require_sha(record["goal_source_sha256"])
        body = record["context"]
        if (
            binding != model_job.sha(body)
            or set(body)
            != {
                "schema_version",
                "current_week",
                "goal_snapshot",
                "history_reports",
                "scope_sha256",
                "provider_calls",
                "external_actions",
            }
            or body["schema_version"] != "fit_weekly_context_" + suffix
        ):
            raise ValueError("shape")
        if record["evidence_sha256"] != original_sha or body[
            "current_week"
        ] != project_evidence(original):
            raise ValueError("evidence")
        weekly_evidence.verify_name_sources(db, root, original)
        for activity in original["activities"]:
            if (
                fit_parse.parse_registered(
                    db,
                    root,
                    activity["activity_ref"],
                    activity["fit_sha256"],
                    parser_version=original["parser_version"],
                )
                != activity
            ):
                raise ValueError("source")
        if (
            type(body["provider_calls"]) is not int
            or body["provider_calls"] != 0
            or type(body["external_actions"]) is not int
            or body["external_actions"] != 0
        ):
            raise ValueError("calls")
        snapshot = body["goal_snapshot"]
        if set(snapshot) != {"sha256", "goal"} or snapshot["sha256"] != model_job.sha(
            snapshot["goal"]
        ):
            raise ValueError("goal")
        jsonschema.Draft202012Validator(json.loads(GOAL_SCHEMA.read_text())).validate(
            snapshot["goal"]
        )
        scope = fit_detail.DetailHost(root, end, body["scope_sha256"]).scope(db)
        if scope["parser_version"] != original["parser_version"]:
            raise ValueError("scope")
        expected = sorted(
            [
                {k: a[k] for k in ("activity_ref", "fit_sha256", "parse_sha256")}
                for a in original["activity_sources"]
            ],
            key=lambda a: a["activity_ref"],
        )
        if [
            {k: m[k] for k in ("activity_ref", "fit_sha256", "parse_sha256")}
            for m in scope["members"]
        ] != expected:
            raise ValueError("scope")
        history = body["history_reports"]
        if not isinstance(history, list) or len(history) > 4:
            raise ValueError("history")
        ends = [h["period_end_utc"] for h in history]
        if ends != sorted(set(ends), reverse=True) or any(
            e > original["period_start_utc"] for e in ends
        ):
            raise ValueError("history")
        for h in history:
            if h != weekly_history.project(
                weekly_history.read(db, root, h["period_end_utc"], validate_report)
            ):
                raise ValueError("history")
        check_text(body, allow_sports_location=suffix == "v2")
        return model_job.clone(body)
    except Exception:
        raise ValueError("weekly_context_invalid") from None


def freeze(
    root: Path,
    period_end: str,
    *,
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    fit_detail.period_key(period_end)
    if not callable(validate_report):
        raise ValueError("weekly_context_validator_missing")
    key = "weekly-context:" + period_end
    with storage.open_store(root) as db:
        previous = fit_detail.get(db, key)
        if previous is not None:
            return checked(db, root, period_end, previous, validate_report)
        evidence_sha, current = evidence(db, period_end)
        suffix = context_suffix(current["parser_version"])
        source_sha, snapshot = goal(root, allow_sports_location=suffix == "v2")
        history = weekly_history.recent(
            db, root, current["period_start_utc"], validate_report
        )
        check_text(project_evidence(current), allow_sports_location=suffix == "v2")
        check_text(
            [weekly_history.project(h) for h in history],
            allow_sports_location=suffix == "v2",
        )
    scope = fit_detail.freeze_scope(
        root,
        period_end,
        [
            {k: a[k] for k in ("activity_ref", "fit_sha256")}
            for a in current["activities"]
        ],
        parser_version=current["parser_version"],
    )
    body = {
        "schema_version": "fit_weekly_context_" + suffix,
        "current_week": project_evidence(current),
        "goal_snapshot": snapshot,
        "history_reports": [weekly_history.project(h) for h in history],
        "scope_sha256": scope["scope_sha256"],
        "provider_calls": 0,
        "external_actions": 0,
    }
    record = {
        "schema_version": "fit_weekly_context_record_" + suffix,
        "evidence_sha256": evidence_sha,
        "goal_source_sha256": source_sha,
        "context": body,
    }
    with storage.open_store(root) as db:
        # Another completed freeze wins; never overwrite its original goal/history.
        previous = fit_detail.get(db, key)
        if previous is not None:
            return checked(db, root, period_end, previous, validate_report)
        checked(db, root, period_end, (model_job.sha(body), record), validate_report)
        fit_detail.put(db, key, model_job.sha(body), record)
        return model_job.clone(body)


def validator(
    root: Path,
    period_end: str,
    *,
    validate_report: model_job.ResultValidator,
) -> model_job.InputValidator:
    """The same freeze validator runs before model intent, with no new snapshot."""
    if not callable(validate_report):
        raise ValueError("weekly_context_validator_missing")
    fit_detail.period_key(period_end)

    def validate(body: dict[str, Any]) -> None:
        with storage.open_store(root) as db:
            saved = fit_detail.get(db, "weekly-context:" + period_end)
            if saved is None or storage.canonical(
                checked(db, root, period_end, saved, validate_report)
            ) != storage.canonical(model_job.clone(body)):
                raise ValueError("weekly_context_invalid")

    return validate
