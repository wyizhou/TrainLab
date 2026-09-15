"""Explicit immutable local revisions. Original AI captures remain authoritative sources.

No model/Provider execution, implicit latest selection, or weekly-history promotion.
A saved revision alone is not publishable: its byte-bound artifacts must also exist.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching,
    coaching_plan,
    coaching_summary,
    fit_detail,
    model_job,
    storage,
)
from skills._shared.scripts.schema_validation import validate_payload


def key(end: str, revision_id: str) -> str:
    fit_detail.period_key(end)
    if not isinstance(revision_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", revision_id
    ):
        raise ValueError("report_revision_id_invalid")
    return f"report-revision:{end}:{revision_id}"


def publication_key(end: str) -> str:
    fit_detail.period_key(end)
    return "report-publication:" + end


def selection_key(end: str) -> str:
    return publication_key(end) + ":selection"


def require_unsealed(db: sqlite3.Connection, end: str) -> None:
    if (
        fit_detail.get(db, publication_key(end)) is not None
        or fit_detail.get(db, selection_key(end)) is not None
    ):
        raise ValueError("report_period_sealed")


def original(root: Path, end: str) -> dict[str, Any]:
    report = coaching.report(root, end)
    requests, results = {}, {}
    with storage.open_store(root) as db:
        for stage in ("plan", "summary"):
            intent = fit_detail.get(db, f"model-job:{end}:{stage}:intent")
            result = fit_detail.get(db, f"model-job:{end}:{stage}:result")
            if intent is None or result is None:
                raise ValueError("report_source_missing")
            requests[stage] = intent[1]
            results[stage] = result[1]
    return {
        "report": report,
        "requests": requests,
        "plan_content": results["plan"]["output"],
        "summary_content": results["summary"]["output"],
        "source": {
            "report_sha256": report["source_report_sha256"],
            "host_report_sha256": model_job.sha(report),
            "raw_plan_sha256": report["raw_plan_sha256"],
            "raw_summary_sha256": report["raw_summary_sha256"],
            "plan_request_sha256": model_job.sha(requests["plan"]),
            "summary_request_sha256": model_job.sha(requests["summary"]),
        },
    }


def make(
    end: str,
    revision_id: str,
    source: dict[str, Any],
    plan: dict[str, Any],
    summary: dict[str, Any],
    *,
    parent: dict[str, Any] | None = None,
    target: str = "original",
) -> dict[str, Any]:
    return {
        "schema_version": "fit_report_revision_v1",
        "period_end_utc": end,
        "revision_id": revision_id,
        "base_revision_id": parent["revision_id"] if parent else None,
        "base_revision_sha256": model_job.sha(parent) if parent else None,
        "edit_target": target,
        "source": model_job.clone(source),
        "plan_content": model_job.clone(plan),
        "summary_content": model_job.clone(summary),
        "effective_plan_sha256": model_job.sha(plan),
        "effective_summary_sha256": model_job.sha(summary),
    }


def validate(
    body: dict[str, Any], source: dict[str, Any], root: Path, end: str
) -> None:
    if validate_payload(body, "fit_report_revision_v1"):
        raise ValueError("report_revision_schema_invalid")
    if (
        body["source"] != source["source"]
        or body["period_end_utc"] != end
        or body["effective_plan_sha256"] != model_job.sha(body["plan_content"])
        or body["effective_summary_sha256"] != model_job.sha(body["summary_content"])
    ):
        raise ValueError("report_revision_source_invalid")
    # The plan always uses the ORIGINAL running-only request. Summary checks
    # use original all-sport facts, never write summary request.fixed_plan.
    coaching_plan.project(
        body["plan_content"], source["requests"]["plan"]["payload"], root=root
    )
    coaching_summary.validate(
        body["summary_content"], source["requests"]["summary"]["payload"], root=root
    )


def create(root: Path, end: str) -> dict[str, Any]:
    source = original(root, end)
    body = make(
        end, "ai", source["source"], source["plan_content"], source["summary_content"]
    )
    validate(body, source, root, end)
    with storage.open_store(root) as db:
        fit_detail.put(db, key(end, "ai"), model_job.sha(body), body)
    return body


def _read(
    root: Path, end: str, revision_id: str, expected_sha: str, source: dict[str, Any]
) -> dict[str, Any]:
    storage.require_sha(expected_sha)
    chain = []
    seen = set()
    current_id, current_sha = revision_id, expected_sha
    with storage.open_store(root) as db:
        while True:
            if current_id in seen:
                raise ValueError("report_revision_cycle")
            seen.add(current_id)
            saved = fit_detail.get(db, key(end, current_id))
            if (
                saved is None
                or saved[0] != current_sha
                or model_job.sha(saved[1]) != current_sha
            ):
                raise ValueError("report_revision_missing_or_sha_invalid")
            body = saved[1]
            if (
                validate_payload(body, "fit_report_revision_v1")
                or body["revision_id"] != current_id
            ):
                raise ValueError("report_revision_schema_invalid")
            chain.append(body)
            if body["base_revision_id"] is None:
                break
            current_id, current_sha = (
                body["base_revision_id"],
                body["base_revision_sha256"],
            )
    parent = None
    for body in reversed(chain):
        validate(body, source, root, end)
        if parent is None:
            if body != make(
                end,
                "ai",
                source["source"],
                source["plan_content"],
                source["summary_content"],
            ):
                raise ValueError("report_revision_origin_invalid")
        else:
            target = body["edit_target"]
            unchanged = "summary_content" if target == "plan" else "plan_content"
            if (
                target not in ("plan", "summary")
                or body[unchanged] != parent[unchanged]
            ):
                raise ValueError("report_revision_edit_boundary_invalid")
        parent = body
    return model_job.clone(chain[0])


def read(root: Path, end: str, revision_id: str, expected_sha: str) -> dict[str, Any]:
    key(end, revision_id)
    return _read(root, end, revision_id, expected_sha, original(root, end))


def edit(
    root: Path,
    end: str,
    *,
    base_revision_id: str,
    base_revision_sha256: str,
    revision_id: str,
    target: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    key(end, revision_id)
    if target not in ("summary", "plan") or revision_id in ("ai", base_revision_id):
        raise ValueError("report_edit_target_invalid")
    source = original(root, end)
    parent = _read(root, end, base_revision_id, base_revision_sha256, source)
    body = make(
        end,
        revision_id,
        source["source"],
        content if target == "plan" else parent["plan_content"],
        content if target == "summary" else parent["summary_content"],
        parent=parent,
        target=target,
    )
    validate(body, source, root, end)
    with storage.open_store(root) as db:
        require_unsealed(db, end)
        fit_detail.put(db, key(end, revision_id), model_job.sha(body), body)
    # Durable revision precedes rendering. Failure leaves no valid artifact
    # manifest; replay resumes locally and never re-runs either model stage.
    from skills._shared.fit_weekly import report_artifacts

    report_artifacts.render(root, end, revision_id, model_job.sha(body))
    return body


def view(root: Path, end: str, revision_id: str, expected_sha: str) -> dict[str, Any]:
    source = original(root, end)
    body = _read(root, end, revision_id, expected_sha, source)
    plan = coaching_plan.project(
        body["plan_content"], source["requests"]["plan"]["payload"], root=root
    )
    # This is a LOCAL effective view, not a fit_coaching_report_v1 capture.
    # Never rename an edited content SHA to original/raw AI SHA.
    del plan["original_plan_sha256"]
    return {
        "revision_id": revision_id,
        "revision_sha256": expected_sha,
        "source": model_job.clone(body["source"]),
        "effective_plan_sha256": body["effective_plan_sha256"],
        "effective_summary_sha256": body["effective_summary_sha256"],
        "facts": model_job.clone(source["report"]["facts"]),
        **{
            k: model_job.clone(v)
            for k, v in body["summary_content"].items()
            if k != "schema_version"
        },
        "plan": plan,
        "validation_limits": list(source["report"]["validation_limits"]),
    }
