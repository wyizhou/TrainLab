#!/usr/bin/env python3
"""Validate and append a coach AI result; the model never receives a DB handle."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
)


def _load_course_validator() -> Any:
    path = Path(__file__).resolve().parent / "validate_course.py"
    spec = importlib.util.spec_from_file_location("trainlab_validate_course", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("course_validator_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _numbers(value: object) -> set[float]:
    result: set[float] = set()
    if isinstance(value, bool):
        return result
    if isinstance(value, (int, float)):
        result.add(float(value))
    elif isinstance(value, dict):
        for child in value.values():
            result.update(_numbers(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_numbers(child))
    return result


def _evidence_payloads(context: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Index host evidence objects by raw-file identity only."""
    result: dict[int, dict[str, Any]] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            raw_id = value.get("raw_file_id")
            if isinstance(raw_id, int) and not isinstance(raw_id, bool):
                result[raw_id] = value
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for key in ("health", "activities"):
        visit(context.get(key))
    return result


def _raw_sha_map(database: Path) -> dict[int, str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute("SELECT id,sha256 FROM raw_files").fetchall()
    finally:
        connection.close()
    return {int(row[0]): str(row[1]) for row in rows}


def _live_receipt_errors(context: dict[str, Any], database: Path) -> list[str]:
    live_sync = context.get("live_sync")
    if live_sync is None:
        return []
    if not isinstance(live_sync, dict) or not isinstance(
        live_sync.get("output_id"), int
    ):
        return ["garmin_live_sync_receipt_missing"]
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (int(live_sync["output_id"]),),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[2]) not in {
        "garmin_live_sync_receipt_v1",
        "garmin_rolling_week_receipt_v1",
    }:
        return ["garmin_live_sync_receipt_missing"]
    if str(row[3]) != "succeeded":
        return ["garmin_live_sync_receipt_incomplete"]
    try:
        receipt = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return ["garmin_live_sync_receipt_missing"]
    raw_ids = receipt.get("raw_file_ids")
    report_date = context.get("report_date")
    if str(row[2]) == "garmin_rolling_week_receipt_v1":
        windows = receipt.get("daily_windows")
        window = windows.get(report_date) if isinstance(windows, dict) else None
        if (
            receipt.get("workflow_key") != "m10:rolling-week:2026-08-11/2026-08-18"
            or not isinstance(window, dict)
            or window.get("report_date") != report_date
            or window.get("inventory_complete") is not True
        ):
            return ["garmin_live_sync_receipt_incomplete"]
        raw_ids = window.get("raw_file_ids")
    else:
        if (
            receipt.get("workflow_key") != "daily:2026-08-17"
            or receipt.get("inventory_complete") is not True
        ):
            return ["garmin_live_sync_receipt_incomplete"]
    if (
        receipt.get("status") != "succeeded"
        or live_sync.get("sha256") != str(row[1])
        or not isinstance(raw_ids, list)
        or any(
            isinstance(value, bool) or not isinstance(value, int) for value in raw_ids
        )
    ):
        return ["garmin_live_sync_receipt_incomplete"]
    context_ids = set(_evidence_payloads(context))
    if not context_ids.issubset(set(raw_ids)):
        return ["ai_evidence_outside_live_receipt"]
    return []


def _drop_null_optional_plan_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize strict model nulls before validating the domain plan contract."""
    if not isinstance(payload.get("training_plan"), dict):
        return payload
    normalized = dict(payload)
    plan = dict(payload["training_plan"])
    plan = {key: value for key, value in plan.items() if value is not None}
    items = plan.get("items")
    if isinstance(items, list):
        plan["items"] = [
            {key: value for key, value in item.items() if value is not None}
            if isinstance(item, dict)
            else item
            for item in items
        ]
    normalized["training_plan"] = plan
    return normalized


def _record_blocked_run(
    payload: dict[str, Any],
    context: dict[str, Any],
    database: Path,
    mode: str,
    errors: list[str],
) -> int:
    """Persist deterministic validation failures as a terminal Skill run.

    A rejected model result is still an observed execution.  Keeping that
    execution in the state database makes a blocked slot resumable and avoids
    treating a preflight JSON file as if it were a durable receipt.
    """
    period_value = (
        payload.get("report_date")
        or payload.get("period")
        or context.get("report_date")
        or context.get("period")
    )
    period = str(period_value or "unknown")
    workflow_key = (
        f"daily:{period}" if mode == "daily" else f"weekly:{period.split('/')[-1]}"
    )
    manifest = {
        "mode": mode,
        "context": context,
        "validation_errors": sorted(set(errors)),
    }
    digest = sha256_text(canonical_json(manifest))
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"training-coach:ai:{workflow_key}:{digest}:attempt-1",
            workflow_key=workflow_key,
            dedupe_key=digest,
            skill_name="training-coach",
            operation="daily_coach" if mode == "daily" else "weekly_coach",
            trigger_kind="skill",
            input_manifest=manifest,
            input_sha256=sha256_text(canonical_json(manifest)),
            target_from_date=(
                period.split("/", 1)[0]
                if "/" in period
                else period
                if len(period) == 10
                else None
            ),
            target_through_date=(
                period.split("/", 1)[-1]
                if "/" in period
                else period
                if len(period) == 10
                else None
            ),
        )
        finish_run(connection, run_id, status="blocked", error_code=errors[0])
        return run_id
    finally:
        connection.close()


def _schema_errors(payload: dict[str, Any], schema_name: str) -> list[str]:
    try:
        require_valid_payload(payload, schema_name)
    except ValueError:
        return [f"{schema_name}_invalid"]
    return []


def _normalize_daily_evidence_refs(
    payload: dict[str, Any], evidence_refs: list[dict[str, Any]]
) -> list[str]:
    """Normalize legacy positional refs to stable raw-file IDs.

    Early real-model responses used both an evidence-array position and a raw
    ID.  The persisted contract is now always the raw ID; direct IDs win when
    a number could be interpreted both ways.
    """
    raw_ids = {
        int(ref["raw_file_id"])
        for ref in evidence_refs
        if isinstance(ref, dict) and isinstance(ref.get("raw_file_id"), int)
    }
    errors: list[str] = []
    metrics = payload.get("bounded_metrics", [])
    if not isinstance(metrics, list):
        return errors
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        reference = metric.get("evidence_ref")
        if isinstance(reference, bool) or not isinstance(reference, int):
            errors.append("ai_evidence_ref_invalid")
            continue
        if reference in raw_ids:
            resolved = reference
        elif 1 <= reference <= len(evidence_refs):
            candidate = evidence_refs[reference - 1].get("raw_file_id")
            if not isinstance(candidate, int):
                errors.append("ai_evidence_ref_invalid")
                continue
            resolved = candidate
        else:
            errors.append("ai_evidence_ref_invalid")
            continue
        metric["evidence_ref"] = resolved
    return errors


def _validate_daily(
    payload: dict[str, Any], context: dict[str, Any], database: Path
) -> list[str]:
    errors: list[str] = _schema_errors(payload, "daily_ai_result_v1")
    if errors:
        return errors
    errors.extend(_live_receipt_errors(context, database))
    for field in ("report_date", "review_date", "sleep_wake_date"):
        if payload.get(field) != context.get(field):
            errors.append("daily_date_mismatch")
    trend = context.get("recent_trend")
    expected_trend_sha = trend.get("sha256") if isinstance(trend, dict) else None
    if payload.get("recent_trend_sha256") != expected_trend_sha:
        errors.append("daily_recent_trend_sha_mismatch")
    raw_sha = _raw_sha_map(database)
    evidence_refs = payload["evidence_refs"]
    if not isinstance(evidence_refs, list):
        return ["daily_ai_result_v1_invalid"]
    errors.extend(_normalize_daily_evidence_refs(payload, evidence_refs))
    refs = {
        int(ref["raw_file_id"]): ref
        for ref in evidence_refs
        if isinstance(ref, dict) and isinstance(ref.get("raw_file_id"), int)
    }
    for raw_id, ref in refs.items():
        if raw_sha.get(raw_id) != ref["sha256"]:
            errors.append("ai_evidence_sha_mismatch")
    referenced_ids = set(refs)
    context_ids = {
        int(item["raw_file_id"])
        for item in context.get("health", [])
        if isinstance(item, dict) and isinstance(item.get("raw_file_id"), int)
    }
    for activity in context.get("activities", []):
        if isinstance(activity, dict) and isinstance(activity.get("raw_file_id"), int):
            context_ids.add(int(activity["raw_file_id"]))
    if not referenced_ids.issubset(context_ids):
        errors.append("ai_evidence_outside_context")
    evidence_payloads = _evidence_payloads(context)
    for metric in payload.get("bounded_metrics", []):
        value = metric.get("value") if isinstance(metric, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            unit = (
                str(metric.get("unit", "")).lower() if isinstance(metric, dict) else ""
            )
            evidence_ref = (
                metric.get("evidence_ref") if isinstance(metric, dict) else None
            )
            allowed = (
                _numbers(evidence_payloads.get(evidence_ref, {}))
                if isinstance(evidence_ref, int) and not isinstance(evidence_ref, bool)
                else set()
            )
            allowed_minutes = {round(number / 60, 3) for number in allowed}
            allowed_hours = {round(number / 3600, 3) for number in allowed}
            candidates = allowed
            if unit in {"min", "minute", "minutes"}:
                candidates = allowed | allowed_minutes
            elif unit in {"h", "hr", "hour", "hours"}:
                candidates = allowed | allowed_hours
            if not any(
                abs(float(value) - candidate) <= 0.01 for candidate in candidates
            ):
                errors.append("ai_metric_not_in_evidence")
        if (
            isinstance(metric, dict)
            and metric.get("evidence_ref") not in referenced_ids
        ):
            errors.append("ai_evidence_ref_invalid")
    required_safety = "ready"
    for item in context.get("health", []):
        metrics = item.get("metrics") if isinstance(item, dict) else None
        if not isinstance(metrics, dict):
            continue
        if (
            metrics.get("resource") == "sleep"
            and isinstance(metrics.get("duration_seconds"), (int, float))
            and metrics["duration_seconds"] < 6 * 60 * 60
        ):
            required_safety = "caution"
        if (
            metrics.get("resource") == "rhr"
            and isinstance(metrics.get("resting_heart_rate_bpm"), (int, float))
            and metrics["resting_heart_rate_bpm"] >= 85
        ):
            required_safety = "caution"
    if required_safety == "caution" and payload.get("safety") == "ready":
        errors.append("ai_safety_downgrade")
    if context.get("status") != "ready" and payload.get("status") == "succeeded":
        errors.append("ai_context_not_ready")
    return sorted(set(errors))


def _validate_weekly(
    payload: dict[str, Any], context: dict[str, Any], database: Path
) -> list[str]:
    errors: list[str] = _schema_errors(payload, "weekly_ai_result_v1")
    if errors:
        return errors
    if payload.get("period") != context.get("period"):
        errors.append("weekly_period_mismatch")
    goal = context.get("goal")
    expected_goal_sha = goal.get("sha256") if isinstance(goal, dict) else None
    if payload.get("goal_sha256") != expected_goal_sha:
        errors.append("weekly_goal_sha_mismatch")
    expected = [
        report.get("sha256")
        for report in context.get("daily_reports", [])
        if isinstance(report, dict)
    ]
    if payload.get("daily_input_sha256") != expected:
        errors.append("weekly_daily_inputs_mismatch")
    expected_refs = {
        int(report["output_id"]): str(report["sha256"])
        for report in context.get("daily_reports", [])
        if isinstance(report, dict)
        and isinstance(report.get("output_id"), int)
        and isinstance(report.get("sha256"), str)
    }
    for ref in payload.get("evidence_refs", []):
        if not isinstance(ref, dict):
            errors.append("weekly_evidence_ref_invalid")
            continue
        output_id = ref.get("output_id")
        if not isinstance(output_id, int) or expected_refs.get(output_id) != ref.get(
            "sha256"
        ):
            errors.append("weekly_evidence_ref_invalid")
    try:
        require_valid_payload(payload["training_plan"], "training_plan_v1")
    except ValueError:
        errors.append("training_plan_invalid")
        return sorted(set(errors))
    validator = _load_course_validator()
    return sorted(set(errors + validator.validate(payload["training_plan"])))


def commit(
    payload: dict[str, Any], context: dict[str, Any], database: Path, mode: str
) -> dict[str, Any]:
    # A missing or ambiguous evidence window is a deterministic host decision,
    # not an AI validation error.  Persist it even when no model payload exists
    # so the slot remains auditable and cannot be mistaken for a successful run.
    if context.get("status") != "ready":
        context_errors = context.get("errors")
        if mode == "weekly" and not context_errors:
            context_errors = [
                f"weekly_daily_missing:{day}"
                for day in context.get("missing_dates", [])
                if isinstance(day, str)
            ]
        errors = [
            error
            for error in (context_errors or [])
            if isinstance(error, str) and error
        ] or [f"{mode}_context_not_ready"]
        run_id = _record_blocked_run(payload, context, database, mode, errors)
        return {
            "status": "blocked",
            "error_code": errors[0],
            "errors": sorted(set(errors)),
            "run_id": run_id,
            "provider_calls": 0,
        }
    if mode == "weekly":
        payload = _drop_null_optional_plan_fields(payload)
    errors = (
        _validate_daily(payload, context, database)
        if mode == "daily"
        else _validate_weekly(payload, context, database)
    )
    if errors:
        run_id = _record_blocked_run(payload, context, database, mode, errors)
        return {
            "status": "blocked",
            "error_code": errors[0],
            "errors": errors,
            "run_id": run_id,
            "provider_calls": 0,
        }
    period = payload["report_date"] if mode == "daily" else payload["period"]
    workflow_key = (
        f"daily:{period}" if mode == "daily" else f"weekly:{period.split('/')[-1]}"
    )
    context_sha = sha256_text(canonical_json(context))
    input_manifest = {"mode": mode, "context": context}
    input_sha = sha256_text(canonical_json(input_manifest))
    dedupe_key = sha256_text(
        canonical_json({"mode": mode, "context_sha256": context_sha})
    )
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"training-coach:ai:{workflow_key}:{dedupe_key}:attempt-1",
            workflow_key=workflow_key,
            dedupe_key=dedupe_key,
            skill_name="training-coach",
            operation="daily_coach" if mode == "daily" else "weekly_coach",
            trigger_kind="skill",
            input_manifest=input_manifest,
            input_sha256=input_sha,
            target_from_date=period.split("/", 1)[0] if "/" in period else period,
            target_through_date=period.split("/", 1)[-1] if "/" in period else period,
        )
        run_status = connection.execute(
            "SELECT status FROM skill_runs WHERE id=?", (run_id,)
        ).fetchone()[0]
        if run_status == "succeeded":
            existing = connection.execute(
                "SELECT id FROM skill_outputs WHERE skill_run_id=? AND output_kind=? "
                "ORDER BY id LIMIT 1",
                (run_id, "daily_summary" if mode == "daily" else "weekly_summary"),
            ).fetchone()
            if existing is None:
                raise ValueError("ai_success_without_output")
            return {
                "status": "succeeded",
                "workflow_key": workflow_key,
                "run_id": run_id,
                "output_id": int(existing[0]),
                "reused": True,
                "provider_calls": 0,
            }
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="daily_summary" if mode == "daily" else "weekly_summary",
            logical_key=f"training-coach:ai:{workflow_key}",
            schema_name=f"{mode}_ai_result_v1",
            schema_version="1",
            title_text=f"TrainLab {mode} AI result",
            content_json=payload,
            content_text=payload.get("summary"),
            lineage=(
                [
                    {
                        "raw_file_id": ref["raw_file_id"],
                        "raw_sha256": ref["sha256"],
                    }
                    for ref in payload.get("evidence_refs", [])
                ]
                if mode == "daily"
                else [
                    {
                        "output_id": ref["output_id"],
                        "output_sha256": ref["sha256"],
                    }
                    for ref in payload.get("evidence_refs", [])
                ]
            ),
            period_start_date=period.split("/", 1)[0] if "/" in period else period,
            period_end_date=period.split("/", 1)[-1] if "/" in period else period,
        )
        if mode == "weekly":
            append_output(
                connection,
                skill_run_id=run_id,
                output_kind="training_plan",
                logical_key=f"training-coach:ai:{workflow_key}:plan",
                schema_name="training_plan_v1",
                schema_version="1",
                title_text="TrainLab AI training plan",
                content_json=payload["training_plan"],
                content_text=json.dumps(
                    payload["training_plan"], ensure_ascii=False, sort_keys=True
                ),
                lineage=[
                    {
                        "output_id": ref["output_id"],
                        "output_sha256": ref["sha256"],
                    }
                    for ref in payload.get("evidence_refs", [])
                ],
                period_start_date=period.split("/", 1)[0],
                period_end_date=period.split("/", 1)[-1],
            )
        finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    return {
        "status": "succeeded",
        "workflow_key": workflow_key,
        "run_id": run_id,
        "output_id": output_id,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.result_json.read_text(encoding="utf-8"))
    context = json.loads(args.context_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(context, dict):
        raise SystemExit("ai input must be objects")
    try:
        result = commit(payload, context, args.database, args.mode)
    except ValueError as exc:
        result = {"status": "blocked", "error_code": str(exc), "provider_calls": 0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
