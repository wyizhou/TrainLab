"""Full structured reports from successful local model jobs, never arbitrary files.

The caller supplies the business result validator for the saved schema version.
This ledger component does not certify coaching content or render a report.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import fit_detail, model_job, stage_policy, storage
from skills._shared.scripts.schema_validation import validate_payload


def completed_stages(
    db: sqlite3.Connection,
    root: Path,
    end: str,
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    captures = {}
    requests = {}
    for stage in ("plan", "summary"):
        key = stage_policy.job_key(end, stage)
        intent, saved = (
            fit_detail.get(db, key + ":intent"),
            fit_detail.get(db, key + ":result"),
        )
        if intent is None or saved is None:
            raise ValueError("weekly_history_invalid")
        binding, request = intent
        if (
            binding != model_job.sha(request)
            or saved[0] != binding
            or request.get("stage") != stage
            or request["period_end_utc"] != end
        ):
            raise ValueError("weekly_history_invalid")
        path = model_job.capture_path(root, end, stage=stage)
        storage.private_entry(path.parent.parent, directory=True)
        storage.private_entry(path.parent, directory=True)
        storage.private_entry(path, nonempty=True)
        raw = path.read_bytes()
        if raw != storage.canonical(saved[1]).encode():
            raise ValueError("weekly_history_invalid")
        fit_detail.DetailHost(root, end, request["scope_sha256"], stage=stage).scope(db)
        model_job.check_capture(
            saved[1],
            request,
            model_job.schema_validator(request["response_schema"]),
            validate_report,
        )
        if saved[1]["receipt"]["status"] != "succeeded":
            raise ValueError("weekly_history_invalid")
        captures[stage], requests[stage] = saved[1], request
    plan = captures["plan"]
    fixed = {
        "period_end_utc": end,
        "request_sha256": model_job.sha(requests["plan"]),
        "capture_sha256": model_job.sha(plan),
        "result_sha256": model_job.sha(plan["output"]),
        "plan": plan["output"],
    }
    if requests["summary"]["payload"].get("fixed_plan") != fixed:
        raise ValueError("weekly_history_invalid")
    expected = {
        "schema_version": "fit_weekly_stages_result_v1",
        "period_end_utc": end,
        "summary": captures["summary"]["output"],
        "running": {
            "analysis": captures["summary"]["output"]["running_analysis"],
            "plan": plan["output"],
        },
        "plan_binding": fixed,
        "summary_receipt": captures["summary"]["receipt"],
    }
    merged = fit_detail.get(db, "weekly-stages-result:" + end)
    if validate_payload(expected, "fit_weekly_stages_result_v1"):
        raise ValueError("weekly_history_invalid")
    if merged != (model_job.sha(expected), expected):
        raise ValueError("weekly_history_invalid")
    return {
        "schema_version": "fit_weekly_history_v2",
        "period_start_utc": fit_detail.period_key(end)[1]["start_utc"],
        "period_end_utc": end,
        "request_sha256": model_job.sha(requests["summary"]),
        "receipt_sha256": model_job.sha(captures["summary"]["receipt"]),
        "report_sha256": model_job.sha(expected),
        "report": model_job.clone(expected),
    }


def completed(
    db: sqlite3.Connection,
    root: Path,
    end: str,
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    try:
        _, slot = fit_detail.period_key(end)
        if not callable(validate_report):
            raise ValueError("validator")
        intent = fit_detail.get(db, "model-job:" + end + ":intent")
        saved = fit_detail.get(db, "model-job:" + end + ":result")
        if intent is None:
            return completed_stages(db, root, end, validate_report)
        if intent is None or saved is None:
            raise ValueError("unfinished")
        binding, request = intent
        if (
            model_job.sha(request) != binding
            or request["period_end_utc"] != end
            or request["schema_version"] != "fit_model_request_v1"
            or saved[0] != binding
        ):
            raise ValueError("binding")
        fit_detail.DetailHost(root, end, request["scope_sha256"]).scope(db)
        path = model_job.capture_path(root, end)
        storage.private_entry(path.parent.parent, directory=True)
        storage.private_entry(path.parent, directory=True)
        storage.private_entry(path, nonempty=True)
        raw = path.read_bytes()
        capture = json.loads(raw)
        if storage.canonical(capture).encode() != raw or saved[1] != capture:
            raise ValueError("capture")
        model_job.check_capture(
            capture,
            request,
            model_job.schema_validator(request["response_schema"]),
            validate_report,
        )
        receipt = capture["receipt"]
        if receipt["status"] != "succeeded" or not isinstance(capture["output"], dict):
            raise ValueError("unsuccessful")
        return {
            "schema_version": "fit_weekly_history_v1",
            "period_start_utc": slot["start_utc"],
            "period_end_utc": end,
            "request_sha256": binding,
            "receipt_sha256": model_job.sha(receipt),
            "report_sha256": receipt["output_sha256"],
            "report": model_job.clone(capture["output"]),
        }
    except Exception:
        raise ValueError("weekly_history_invalid") from None


def stored(db: sqlite3.Connection, end: str) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT input_sha256,content_json,content_sha256 FROM documents WHERE kind='weekly_report' AND logical_key=?",
        ("weekly-report:" + end,),
    ).fetchall()
    if not rows:
        return None
    try:
        if len(rows) != 1:
            raise ValueError("conflict")
        binding, text, sha = rows[0]
        body = json.loads(text)
        if (
            storage.canonical(body) != text
            or storage.digest(text.encode()) != sha
            or binding != body["request_sha256"]
            or end != body["period_end_utc"]
        ):
            raise ValueError("binding")
        return body
    except Exception:
        raise ValueError("weekly_history_invalid") from None


def read(
    db: sqlite3.Connection,
    root: Path,
    end: str,
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    body = stored(db, end)
    if body is None or body != completed(db, root, end, validate_report):
        raise ValueError("weekly_history_invalid")
    return body


def archive(
    root: Path,
    period_end: str,
    *,
    validate_report: model_job.ResultValidator,
) -> dict[str, Any]:
    """Promote a completed, revalidated job to immutable report history."""
    with storage.open_store(root) as db:
        body = completed(db, root, period_end, validate_report)
        old = stored(db, period_end)
        if old is not None and old != body:
            raise ValueError("weekly_history_invalid")
        storage.put_document(
            db,
            "weekly_report",
            "weekly-report:" + period_end,
            body["request_sha256"],
            body,
        )
        return body


def recent(
    db: sqlite3.Connection,
    root: Path,
    before: str,
    validate_report: model_job.ResultValidator,
) -> list[dict[str, Any]]:
    """Newest four actual preceding reports, not four manufactured weekly slots."""
    fit_detail.period_key(before)
    keys = db.execute(
        "SELECT DISTINCT logical_key FROM documents WHERE kind='weekly_report' ORDER BY logical_key DESC"
    ).fetchall()
    ends = []
    for row in keys:
        key = row[0]
        if not key.startswith("weekly-report:"):
            raise ValueError("weekly_history_invalid")
        end = key.removeprefix("weekly-report:")
        fit_detail.period_key(end)
        if end <= before:
            ends.append(end)
    return [
        read(db, root, end, validate_report) for end in sorted(ends, reverse=True)[:4]
    ]


def project(body: dict[str, Any]) -> dict[str, Any]:
    return {
        **(
            {"schema_version": body["schema_version"]}
            if body["schema_version"] == "fit_weekly_history_v2"
            else {}
        ),
        **{
            k: model_job.clone(body[k])
            for k in (
                "period_start_utc",
                "period_end_utc",
                "report_sha256",
                "report",
            )
        },
    }
