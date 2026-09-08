"""Exact source references. Revalidation never creates a detail request or reads FIT."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_detail,
    model_job,
    stage_policy,
    storage,
    sync_calendar,
)


def running_view(payload: dict[str, Any]) -> dict[str, Any]:
    if payload["stage"] == "plan":
        return model_job.clone(payload)
    return {
        **{
            k: model_job.clone(payload[k])
            for k in (
                "period_start_utc",
                "period_end_utc",
                "next_plan_dates",
                "goal_snapshot",
            )
        },
        "stage": "plan",
        "running_activities": [
            {
                **{
                    k: model_job.clone(a[k])
                    for k in (
                        "activity_ref",
                        "fit_sha256",
                        "parser_version",
                        "start_utc",
                        "methods",
                    )
                },
                "sessions": [
                    model_job.clone(s) for s in a["sessions"] if s["sport"] == "running"
                ],
            }
            for a in payload["current_week"]["activities"]
            if any(s["sport"] == "running" for s in a["sessions"])
        ],
        "running_history": [
            {
                "period_end_utc": h["period_end_utc"],
                "running_sha256": model_job.sha(h["report"]["running"]),
                "running": model_job.clone(h["report"]["running"]),
            }
            for h in payload["history_reports"]
            if h.get("schema_version") == "fit_weekly_history_v2"
        ],
    }


def at(value: Any, path: list[Any]) -> Any:
    for key in path:
        if isinstance(value, dict) and type(key) is str and key in value:
            value = value[key]
        elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
            value = value[key]
        else:
            raise ValueError("coaching_evidence_path_invalid")
    if value is None or isinstance(value, dict):
        raise ValueError("coaching_evidence_unavailable")
    return value


def sessions(payload: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    activities = (
        payload["running_activities"]
        if payload["stage"] == "plan"
        else payload["current_week"]["activities"]
    )
    return [(a, s) for a in activities for s in a["sessions"]]


def resolve(ref: dict[str, Any], payload: dict[str, Any], *, root: Path) -> Any:
    source = ref["source"]
    if source in ("current", "detail"):
        matches = [
            (a, s)
            for a, s in sessions(payload)
            if a["activity_ref"] == ref["activity_ref"]
            and a["fit_sha256"] == ref["fit_sha256"]
            and s["session_ordinal"] == ref["session_ordinal"]
        ]
        if len(matches) != 1 or ref["period_end_utc"] is not None:
            raise ValueError("coaching_evidence_binding_invalid")
        activity, session = matches[0]
        if source == "current":
            if ref["request_sha256"] is not None:
                raise ValueError("coaching_evidence_binding_invalid")
            return at(session, ref["path"])
        request_sha = ref["request_sha256"]
        storage.require_sha(request_sha)
        key = fit_detail.period_key(payload["period_end_utc"])[0]
        with storage.open_store(root) as db:
            scope = fit_detail.get(db, key + ":scope")
            if scope is None:
                raise ValueError("coaching_evidence_binding_invalid")
            host = fit_detail.DetailHost(
                root, payload["period_end_utc"], scope[0], stage=payload["stage"]
            )
            bound_scope = host.scope(db)
            intent, result = (
                fit_detail.get(db, key + ":intent:" + request_sha),
                fit_detail.get(db, key + ":result:" + request_sha),
            )
            if intent is None or result is None or result[0] != request_sha:
                raise ValueError("coaching_detail_missing")
            req = fit_detail.request_value(intent[1]["request"])
            stage_policy.authorize(payload["stage"], activity, req)
            expected = {
                "schema_version": "fit_detail_intent_v1",
                "scope_sha256": scope[0],
                "request_sha256": request_sha,
                "request": req,
            }
            if (
                intent != (scope[0], expected)
                or model_job.sha({"scope_sha256": scope[0], "request": req})
                != request_sha
            ):
                raise ValueError("coaching_detail_binding_invalid")
            body = result[1]
            fit_detail.validate_result(body)
            members = [
                m
                for m in bound_scope["members"]
                if m["activity_ref"] == activity["activity_ref"]
                and m["fit_sha256"] == activity["fit_sha256"]
            ]
            if (
                len(members) != 1
                or body["status"] != "available"
                or body["scope_sha256"] != scope[0]
                or body["request_sha256"] != request_sha
                or body["fit_sha256"] != activity["fit_sha256"]
                or body["parser_version"] != activity["parser_version"]
                or any(body[k] != v for k, v in req.items())
                or req["activity_ref"] != activity["activity_ref"]
                or req["end_offset_seconds"] > members[0]["duration_seconds"]
            ):
                raise ValueError("coaching_detail_binding_invalid")
            path = ref["path"]
            if (
                len(path) < 3
                or path[0] != "blocks"
                or type(path[1]) is not int
                or not 0 <= path[1] < len(body["blocks"])
            ):
                raise ValueError("coaching_detail_path_invalid")
            block = body["blocks"][path[1]]
            if (
                block["session_ordinal"] != session["session_ordinal"]
                or not req["start_offset_seconds"]
                <= block["start_offset_seconds"]
                < block["end_offset_seconds"]
                <= req["end_offset_seconds"]
            ):
                raise ValueError("coaching_detail_session_invalid")
            if payload["stage"] == "plan" and session["sport"] != "running":
                raise ValueError("coaching_evidence_binding_invalid")
            origin = sync_calendar.utc_time(activity["start_utc"])
            session_start = (
                sync_calendar.utc_time(session["start_utc"]) - origin
            ).total_seconds()
            session_end = (
                sync_calendar.utc_time(session["end_utc"]) - origin
            ).total_seconds()
            if (
                not session_start
                <= block["start_offset_seconds"]
                < block["end_offset_seconds"]
                <= session_end
            ):
                raise ValueError("coaching_detail_session_invalid")
            return at(body, path)
    if any(
        ref[k] is not None
        for k in ("activity_ref", "fit_sha256", "session_ordinal", "request_sha256")
    ):
        raise ValueError("coaching_evidence_binding_invalid")
    if source == "goal":
        if ref["period_end_utc"] is not None:
            raise ValueError("coaching_evidence_binding_invalid")
        return at(payload["goal_snapshot"]["goal"], ref["path"])
    if source == "history":
        histories = (
            payload["running_history"]
            if payload["stage"] == "plan"
            else payload["history_reports"]
        )
        selected = [
            h
            for h in histories
            if h["period_end_utc"] == ref["period_end_utc"]
            and h["period_end_utc"] < payload["period_end_utc"]
        ]
        if len(selected) != 1:
            raise ValueError("coaching_history_missing")
        h = selected[0]
        field, sha_field = (
            ("running", "running_sha256")
            if payload["stage"] == "plan"
            else ("report", "report_sha256")
        )
        if model_job.sha(h[field]) != h[sha_field]:
            raise ValueError("coaching_history_binding_invalid")
        return at(h[field], ref["path"])
    raise ValueError("coaching_evidence_source_invalid")


def validate_claim(
    claim: dict[str, Any],
    payload: dict[str, Any],
    *,
    root: Path,
    running_only: bool = False,
) -> None:
    view = running_view(payload) if running_only else payload
    if (claim["status"] == "supported") != bool(claim["evidence"]):
        raise ValueError("coaching_claim_evidence_missing")
    for ref in claim["evidence"]:
        if storage.canonical(resolve(ref, view, root=root)) != storage.canonical(
            ref["value"]
        ):
            raise ValueError("coaching_evidence_value_mismatch")


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for child in value for s in strings(child)]
    if isinstance(value, dict):
        return [
            s for k, child in value.items() if k != "evidence" for s in strings(child)
        ]
    return []


def guard_text(value: Any, *, future: bool) -> None:
    """Bounded obvious-prescription guard, not a proof of arbitrary prose semantics."""
    for text in strings(value):
        for clause in re.split(
            r"[。；;，,\n]|但是|不过|然后|并且|同时|但|且|并|\bbut\b|\bhowever\b|\band\b",
            text,
            flags=re.I,
        ):
            # Explicit prohibitions and stop conditions are valid instructions.
            prohibition = re.search(
                r"(?i)(不(?:要|应|得|能|会)?|禁止|避免|do not|never|no)\s*(?:安排|进行|使用|设置|提供|做)?\s*(?:补课|补跑|每日.{0,6}(?:调课|改课)|替代计划|alternative plan|make.up (?:run|session))",
                clause,
            )
            if (
                re.search(
                    r"补课|补跑|每日.{0,6}(调课|改课)|替代计划|alternative plan|make.up (run|session)",
                    clause,
                )
                and not prohibition
            ):
                raise ValueError("coaching_dynamic_plan")
            denied_heart = re.search(
                r"(?i)(不(?:要|应|得|能|会)?|禁止|避免|do not|never).{0,8}(?:处方|推算|设定|设置|目标|划区|心率区|bpm|心率|threshold)",
                clause,
            )
            heart_target = re.search(
                r"(?i)(目标|保持|维持|控制|target|keep|maintain).{0,25}(\d+\s*bpm|心率.{0,8}\d|zone\s*[1-9]|[一二三四五1-5]区)|(?:心率|heart.?rate).{0,15}(?:目标|保持|维持|控制).{0,8}[一二三四五1-9]|(?:自行|推算|计算).{0,8}(?:心率区|阈值|threshold)",
                clause,
            )
            direct_future = future and re.search(
                r"(?i)\d+\s*bpm|zone\s*[1-9]|心率.{0,8}\d+", clause
            )
            if (heart_target or direct_future) and not denied_heart:
                raise ValueError("coaching_heart_prescription")
            if re.search(
                r"(?:没有|无|排除).{0,3}健康风险|health risk.free|medically safe",
                clause,
                re.I,
            ) and not re.search(r"不能|无法|不代表|不证明|not |cannot", clause, re.I):
                raise ValueError("coaching_health_clearance")
