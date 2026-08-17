#!/usr/bin/env python3
"""Run a bounded daily or weekly workflow against an isolated SQLite candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
    workflow_lock,
)


def _python() -> str:
    return sys.executable


def _script(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def _source_root(database: Path) -> Path:
    # Candidate databases normally live under candidate/state.  The caller may
    # provide an explicit source root for tests; otherwise use the product root.
    return (
        database.parent.parent if database.parent.name == "state" else database.parent
    )


def _bounded_output(
    database: Path,
    *,
    workflow_key: str,
    skill_name: str,
    operation: str,
    output_kind: str,
    logical_key: str,
    payload: dict[str, Any],
    period_start: str | None = None,
    period_end: str | None = None,
    lineage: list[dict[str, Any]] | None = None,
    status: str = "succeeded",
    error_code: str | None = None,
) -> tuple[int, int]:
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, str) and schema_version.endswith("_v1"):
        require_valid_payload(payload, schema_version)
    connection = connect(database)
    try:
        input_manifest = {
            "workflow_key": workflow_key,
            "logical_key": logical_key,
            "payload_sha256": sha256_text(canonical_json(payload)),
        }
        digest = sha256_text(canonical_json(input_manifest))
        run_id = begin_run(
            connection,
            run_key=f"{workflow_key}:{skill_name}:{operation}:{digest}:attempt-1",
            workflow_key=workflow_key,
            dedupe_key=digest,
            skill_name=skill_name,
            operation=operation,
            trigger_kind="skill",
            input_manifest=input_manifest,
            target_from_date=period_start,
            target_through_date=period_end,
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind=output_kind,
            logical_key=logical_key,
            schema_name=f"{output_kind}_v1",
            schema_version="1",
            title_text=output_kind,
            content_json=payload,
            content_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            lineage=lineage or [],
            period_start_date=period_start,
            period_end_date=period_end,
        )
        finish_run(connection, run_id, status=status, error_code=error_code)
        return run_id, output_id
    finally:
        connection.close()


def _parse_raw(
    source_root: Path, target_date: str, days: int, database: Path
) -> dict[str, Any]:
    command = [
        _python(),
        str(
            Path(__file__).resolve().parents[2] / "training-coach/scripts/parse_raw.py"
        ),
        "--source-root",
        str(source_root),
        "--date",
        target_date,
        "--days",
        str(days),
        "--database",
        str(database),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if not result.stdout.strip():
        return {"status": "blocked", "error_code": "bounded_evidence_script_failed"}
    return json.loads(result.stdout)


def _run_json_script(command: list[str]) -> dict[str, Any]:
    """Run a bounded internal helper and return only its JSON result."""
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if not result.stdout.strip():
        return {
            "status": "blocked",
            "error_code": "bounded_script_failed",
            "provider_calls": 0,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "blocked",
            "error_code": "bounded_script_invalid_output",
            "provider_calls": 0,
        }
    if not isinstance(payload, dict):
        return {
            "status": "blocked",
            "error_code": "bounded_script_invalid_output",
            "provider_calls": 0,
        }
    return payload


def _latest_output_id(
    database: Path, *, output_kind: str, logical_prefix: str | None = None
) -> int | None:
    connection = connect(database, read_only=True, immutable=True)
    try:
        if logical_prefix is None:
            row = connection.execute(
                "SELECT id FROM skill_outputs WHERE output_kind=? "
                "ORDER BY id DESC LIMIT 1",
                (output_kind,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT id FROM skill_outputs WHERE output_kind=? AND logical_key LIKE ? "
                "ORDER BY id DESC LIMIT 1",
                (output_kind, f"{logical_prefix}%"),
            ).fetchone()
        return int(row[0]) if row else None
    finally:
        connection.close()


def _render(
    database: Path, kind: str, payload: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_json = output_dir / "input.json"
    input_json.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    result = subprocess.run(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "training-report-publisher/scripts/render_report.py"
            ),
            "--input-json",
            str(input_json),
            "--kind",
            kind,
            "--mode",
            "open_report",
            "--output-dir",
            str(output_dir),
            "--database",
            str(database),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("report_render_failed")
    return json.loads(result.stdout)


def _prepare_email(database: Path, report_dir: Path, kind: str) -> int:
    html = (report_dir / "report.html").read_text(encoding="utf-8")
    connection = connect(database, read_only=True, immutable=True)
    try:
        report_row = connection.execute(
            "SELECT id,content_sha256,title_text,content_text,content_html,lineage_json "
            "FROM skill_outputs WHERE output_kind='email_render' "
            "AND content_html=? ORDER BY id DESC LIMIT 1",
            (html,),
        ).fetchone()
    finally:
        connection.close()
    if report_row is None:
        raise RuntimeError("email_report_output_missing")
    try:
        report_lineage = json.loads(str(report_row[5]))
    except json.JSONDecodeError as exc:
        raise RuntimeError("email_report_lineage_invalid") from exc
    source_item = next(
        (
            item
            for item in report_lineage
            if isinstance(item, dict) and item.get("source_output_id") is not None
        ),
        None,
    )
    envelope = report_dir / "email.json"
    envelope.write_text(
        json.dumps(
            {
                "subject": str(report_row[2] or f"TrainLab {kind}"),
                "text": str(report_row[3] or ""),
                "html": str(report_row[4] or html),
                "report_output_id": int(report_row[0]),
                "report_output_sha256": str(report_row[1]),
                "source_output_id": source_item.get("source_output_id")
                if isinstance(source_item, dict)
                else None,
                "source_output_sha256": source_item.get("source_output_sha256")
                if isinstance(source_item, dict)
                else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "gmail-sender/scripts/prepare_message.py"
            ),
            str(envelope),
            "--database",
            str(database),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("email_envelope_blocked")
    payload = json.loads(result.stdout)
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT id FROM skill_outputs WHERE output_kind='bounded_evidence' "
            "AND logical_key=? ORDER BY revision_no DESC LIMIT 1",
            (f"gmail-sender:message:{payload.get('marker')}",),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        raise RuntimeError("email_output_missing")
    if payload.get("provider_calls") != 0:
        raise RuntimeError("email_provider_call_detected")
    return int(row[0])


def _daily_payload(
    anchor: date, evidence: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    bounded_metrics = []
    resources: set[str] = set()
    recovery_flags: list[str] = []
    for item in evidence.get("evidence", []):
        if not isinstance(item, dict):
            continue
        details = item.get("evidence")
        metrics = details.get("metrics") if isinstance(details, dict) else None
        if isinstance(metrics, dict) and isinstance(metrics.get("resource"), str):
            resources.add(metrics["resource"])
            if metrics.get("resource") == "sleep":
                duration = metrics.get("duration_seconds")
                if isinstance(duration, (int, float)) and duration < 6 * 60 * 60:
                    recovery_flags.append("sleep_duration_short")
            if metrics.get("resource") == "rhr":
                aggregate = metrics.get("aggregate")
                average = (
                    aggregate.get("average") if isinstance(aggregate, dict) else None
                )
                if isinstance(average, (int, float)) and average >= 85:
                    recovery_flags.append("resting_heart_rate_elevated")
        metric: dict[str, Any] = {
            "sha256": item.get("sha256"),
            "data_date": item.get("data_date"),
            "format": item.get("format"),
            "metrics": metrics if isinstance(metrics, dict) else {},
        }
        if isinstance(item.get("raw_file_id"), int):
            metric["raw_file_id"] = item["raw_file_id"]
        bounded_metrics.append(metric)
    return {
        "schema_version": "daily_summary_v1",
        "status": "succeeded",
        "report_date": anchor.isoformat(),
        "review_date": (anchor - timedelta(days=1)).isoformat(),
        "sleep_wake_date": anchor.isoformat(),
        "evidence_file_count": evidence.get("file_count", 0),
        "bounded_metrics": bounded_metrics,
        "evidence_resources": sorted(resources),
        "history_daily_sha256": [sha256_text(canonical_json(item)) for item in history],
        "history_daily_dates": [
            str(item["report_date"])
            for item in history
            if isinstance(item.get("report_date"), str)
        ],
        "summary": (
            "检测到恢复红旗，今日应降级或休息。"
            if recovery_flags
            else "合成 candidate 的昨日健康、运动与昨夜睡眠摘要。"
        ),
        "safety": "caution" if recovery_flags else "ready",
        "stop_conditions": ["疼痛、胸痛、晕眩、异常呼吸或明显恢复不足时停止或降级。"],
        "provider_calls": 0,
    }


def _weekly_plan(start: date, daily: list[dict[str, Any]]) -> dict[str, Any]:
    running_distance = 0.0
    caution_days = 0
    for summary in daily:
        if summary.get("safety") == "caution":
            caution_days += 1
        for metric in summary.get("bounded_metrics", []):
            if not isinstance(metric, dict):
                continue
            details = metric.get("metrics")
            if isinstance(details, dict) and isinstance(
                details.get("distance_km"), (int, float)
            ):
                running_distance += float(details["distance_km"])
    if caution_days:
        easy_distance = 3.0
        long_distance = 5.0
        climbing_minutes = 60
    elif running_distance > 0:
        easy_distance = round(max(3.0, min(8.0, running_distance / 4.0)), 1)
        long_distance = round(
            max(easy_distance * 1.5, min(12.0, running_distance * 0.4)), 1
        )
        climbing_minutes = 90
    else:
        # No activity distance is still valid bounded evidence, but remain conservative.
        easy_distance = 4.0
        long_distance = 7.0
        climbing_minutes = 75
    items: list[dict[str, Any]] = []
    names = [
        ("running", "Easy-GTS", "easy", "moderate", "candidate", easy_distance),
        ("climbing", "攀岩-中等", "climbing", "moderate", "unsupported_skip", None),
        ("rest", "恢复日", "recovery", "low", "unsupported_skip", None),
        ("running", "Easy-GTS", "easy", "moderate", "candidate", easy_distance),
        ("rest", "恢复日", "recovery", "low", "unsupported_skip", None),
        ("climbing", "攀岩-中等", "climbing", "moderate", "unsupported_skip", None),
        (
            "running",
            "Long-Easy-GTS",
            "long_easy",
            "moderate",
            "candidate",
            long_distance,
        ),
    ]
    for offset, (kind, name, purpose, load, mapping, distance) in enumerate(names):
        item: dict[str, Any] = {
            "date": (start + timedelta(days=offset)).isoformat(),
            "activity_kind": kind,
            "name": name if kind != "climbing" else name,
            "purpose": purpose,
            "load_level": load,
            "garmin_mapping_status": mapping,
            "rpe": 3 if kind != "climbing" else 5,
            "downgrade_rule": "睡眠不足或主观沉重时缩短并降为轻松强度。",
            "stop_conditions": ["急性疼痛、胸痛、晕眩或异常呼吸立即停止。"],
        }
        if distance is not None:
            item["distance_km"] = distance
        if kind == "climbing":
            item["duration_minutes"] = climbing_minutes
        if kind == "running":
            item["steps"] = [{"name": "主课", "end_condition": f"完成 {distance} km"}]
        elif kind == "climbing":
            item["steps"] = [
                {"name": "攀岩课程", "end_condition": f"完成 {climbing_minutes} 分钟"}
            ]
        else:
            item["steps"] = [{"name": "恢复", "end_condition": "当天不安排训练"}]
        items.append(item)
    return {
        "schema_version": "training_plan_v1",
        "status": "succeeded",
        "items": items,
        "progression_rule": "hold",
        "progression_dimension": "none",
        "evidence_running_distance_km": round(running_distance, 3),
        "evidence_caution_days": caution_days,
        "evidence_daily_count": len(daily),
        "provider_calls": 0,
    }


def _run_daily_unlocked(
    database: Path, anchor: date, output_dir: Path
) -> dict[str, Any]:
    source_root = _source_root(database)
    index_result = _run_json_script(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2] / "garmin-sync/scripts/index_raw.py"
            ),
            "--source-root",
            str(source_root),
            "--database",
            str(database),
        ]
    )
    if index_result.get("status") == "blocked":
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": f"daily:{anchor.isoformat()}",
            "error_code": "garmin_raw_index_blocked",
            "provider_calls": 0,
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=f"daily:{anchor.isoformat()}",
            skill_name="garmin-sync",
            operation="index_existing_raw",
            output_kind="execution_summary",
            logical_key=f"workflow:daily:{anchor.isoformat()}",
            payload=receipt,
            status="blocked",
            error_code="garmin_raw_index_blocked",
        )
        return {**receipt, "output_ids": [receipt_id]}
    sync_plan = _run_json_script(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "garmin-sync/scripts/plan_window.py"
            ),
            "--run-date",
            anchor.isoformat(),
            "--database",
            str(database),
        ]
    )
    if sync_plan.get("status") != "planned" or sync_plan.get("external_calls") != 0:
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": f"daily:{anchor.isoformat()}",
            "error_code": "garmin_sync_plan_blocked",
            "provider_calls": 0,
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=f"daily:{anchor.isoformat()}",
            skill_name="garmin-sync",
            operation="daily_sync",
            output_kind="execution_summary",
            logical_key=f"workflow:daily:{anchor.isoformat()}",
            payload=receipt,
            status="blocked",
            error_code="garmin_sync_plan_blocked",
        )
        return {**receipt, "output_ids": [receipt_id]}
    review_evidence = _parse_raw(
        source_root, (anchor - timedelta(days=1)).isoformat(), 1, database
    )
    sleep_evidence = _parse_raw(source_root, anchor.isoformat(), 1, database)

    def _is_sleep_item(item: object) -> bool:
        if not isinstance(item, dict):
            return False
        details = item.get("evidence")
        metrics = details.get("metrics") if isinstance(details, dict) else None
        return "sleep" in str(item.get("relative_path", "")).lower() or (
            isinstance(metrics, dict) and metrics.get("resource") == "sleep"
        )

    review_items = [
        item for item in review_evidence.get("evidence", []) if not _is_sleep_item(item)
    ]
    sleep_items = [
        item for item in sleep_evidence.get("evidence", []) if _is_sleep_item(item)
    ]
    review_ready = review_evidence.get("status") == "ready" and bool(review_items)
    sleep_ready = (
        sleep_evidence.get("status") == "ready"
        and bool(sleep_items)
        and any(
            _is_sleep_item(item)
            and isinstance(item, dict)
            and isinstance(item.get("evidence"), dict)
            and isinstance(item["evidence"].get("metrics"), dict)
            and item["evidence"]["metrics"].get("completeness") == "complete"
            and isinstance(item["evidence"]["metrics"].get("sleep_start"), str)
            and isinstance(item["evidence"]["metrics"].get("sleep_end"), str)
            for item in sleep_items
        )
    )
    evidence: dict[str, Any] = {
        "status": "ready" if review_ready and sleep_ready else "blocked",
        "file_count": len(review_items) + len(sleep_items),
        "evidence": [*review_items, *sleep_items],
    }
    workflow_key = f"daily:{anchor.isoformat()}"
    history = _daily_history(
        database, anchor - timedelta(days=14), anchor - timedelta(days=1)
    )
    if not review_ready or not sleep_ready:
        if not review_ready and not sleep_ready:
            error_code = "daily_review_and_sleep_evidence_missing"
        elif not review_ready:
            error_code = "daily_review_evidence_missing"
        else:
            error_code = "daily_sleep_evidence_missing"
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "error_code": error_code,
            "provider_calls": 0,
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="training-coach",
            operation="daily_coach",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code=error_code,
        )
        return {**receipt, "output_ids": [receipt_id]}
    summary = _daily_payload(anchor, evidence, history)
    lineage = [
        {"input_sha256": item["sha256"]}
        for item in evidence.get("evidence", [])
        if isinstance(item, dict)
    ]
    _, summary_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="training-coach",
        operation="daily_coach",
        output_kind="daily_summary",
        logical_key=f"daily:{anchor.isoformat()}:summary",
        payload=summary,
        period_start=anchor.isoformat(),
        period_end=anchor.isoformat(),
        lineage=lineage,
    )
    report = {
        "title": f"TrainLab · {anchor.isoformat()} 日总结",
        "period": f"{(anchor - timedelta(days=1)).isoformat()}/{anchor.isoformat()}",
        "content": summary,
    }
    rendered = _render(database, "daily", report, output_dir)
    email_id = _prepare_email(database, output_dir, "daily")
    render_ids = (
        [
            int(value)
            for key, value in rendered["output_ids"].items()
            if key in {"report_artifact", "email_render"}
        ]
        if isinstance(rendered.get("output_ids"), dict)
        else list(rendered.get("output_ids") or [])
    )
    receipt = {
        "schema_version": "workflow_receipt_v1",
        "status": "succeeded",
        "outcome": "daily_complete",
        "workflow_key": workflow_key,
        "provider_calls": 0,
        "summary_output_id": summary_id,
        "sync_output_id": _latest_output_id(
            database,
            output_kind="sync_summary",
            logical_prefix=f"garmin-sync:window:{anchor.isoformat()}",
        ),
        "render_output_ids": render_ids,
        "email_output_id": email_id,
    }
    _, receipt_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="gmail-sender",
        operation="send_email",
        output_kind="execution_summary",
        logical_key=f"workflow:{workflow_key}",
        payload=receipt,
    )
    return {
        **receipt,
        "output_ids": [
            summary_id,
            email_id,
            receipt_id,
            *render_ids,
        ],
    }


def run_daily(database: Path, anchor: date, output_dir: Path) -> dict[str, Any]:
    with workflow_lock(database):
        return _run_daily_unlocked(database, anchor, output_dir)


def _workflow_receipt(database: Path, workflow_key: str) -> dict[str, Any] | None:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE output_kind='execution_summary' "
            "AND logical_key=? ORDER BY revision_no DESC LIMIT 1",
            (f"workflow:{workflow_key}",),
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
        if not isinstance(payload, dict) or payload.get("status") != "succeeded":
            return None
        require_valid_payload(payload, "workflow_receipt_v1")
    except (json.JSONDecodeError, ValueError):
        return None
    return payload


def _daily_history(
    database: Path, start: date, end: date, *, require_complete: bool = False
) -> list[dict[str, Any]]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = []
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            row = connection.execute(
                """SELECT content_json FROM skill_outputs
                   WHERE output_kind='daily_summary'
                     AND logical_key=? AND period_start_date=? AND period_end_date=?
                   ORDER BY revision_no DESC LIMIT 1""",
                (f"daily:{day}:summary", day, day),
            ).fetchone()
            if not row:
                if require_complete:
                    return []
                continue
            try:
                payload = json.loads(row[0])
            except json.JSONDecodeError:
                if require_complete:
                    return []
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    finally:
        connection.close()


def _run_weekly_unlocked(
    database: Path, ending: date, output_dir: Path
) -> dict[str, Any]:
    start = ending - timedelta(days=6)
    workflow_key = f"weekly:{ending.isoformat()}"
    if ending.weekday() != 6:
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "provider_calls": 0,
            "error_code": "weekly_requires_sunday",
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="weekly-fitness-summary",
            operation="weekly_coach",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code="weekly_requires_sunday",
        )
        return {**receipt, "output_ids": [receipt_id]}
    if any(
        _workflow_receipt(database, f"daily:{start + timedelta(days=offset):%Y-%m-%d}")
        is None
        for offset in range(7)
    ):
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "provider_calls": 0,
            "error_code": "daily_dependency_not_succeeded",
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="weekly-fitness-summary",
            operation="weekly_coach",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code="daily_dependency_not_succeeded",
        )
        return {**receipt, "output_ids": [receipt_id]}
    history_result = _run_json_script(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "weekly-fitness-summary/scripts/select_history.py"
            ),
            "--database",
            str(database),
            "--week-ending",
            ending.isoformat(),
        ]
    )
    if history_result.get("status") == "blocked":
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "error_code": "weekly_history_selection_failed",
            "provider_calls": 0,
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="weekly-fitness-summary",
            operation="weekly_coach",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code="weekly_history_selection_failed",
        )
        return {**receipt, "output_ids": [receipt_id]}
    daily = _daily_history(database, start, ending, require_complete=True)
    if len(daily) != 7:
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "error_code": "weekly_daily_history_incomplete",
            "provider_calls": 0,
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="weekly-fitness-summary",
            operation="weekly_coach",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code="weekly_daily_history_incomplete",
        )
        return {**receipt, "output_ids": [receipt_id]}
    daily_hashes = [sha256_text(canonical_json(day)) for day in daily]
    daily_valid = all(
        day.get("status") == "succeeded"
        and isinstance(day.get("bounded_metrics"), list)
        and bool(day.get("bounded_metrics"))
        and isinstance(day.get("evidence_resources"), list)
        and bool(day.get("evidence_resources"))
        for day in daily
    )
    if not daily_valid:
        receipt = {
            "schema_version": "workflow_receipt_v1",
            "status": "blocked",
            "outcome": "blocked",
            "workflow_key": workflow_key,
            "provider_calls": 0,
            "error_code": "weekly_evidence_inconsistent",
        }
        _, receipt_id = _bounded_output(
            database,
            workflow_key=workflow_key,
            skill_name="weekly-fitness-summary",
            operation="summarize_week",
            output_kind="execution_summary",
            logical_key=f"workflow:{workflow_key}",
            payload=receipt,
            status="blocked",
            error_code="weekly_evidence_inconsistent",
        )
        return {**receipt, "output_ids": [receipt_id]}
    activity_days = sum(
        any(
            isinstance(metric, dict) and metric.get("format") in {"fit", "gpx", "tcx"}
            for metric in day.get("bounded_metrics", [])
        )
        for day in daily
    )
    sleep_complete_days = sum(
        any(
            isinstance(metric, dict)
            and isinstance(metric.get("metrics"), dict)
            and metric["metrics"].get("resource") == "sleep"
            and metric["metrics"].get("completeness") == "complete"
            for metric in day.get("bounded_metrics", [])
        )
        for day in daily
    )
    review_payload = {
        "schema_version": "weekly_fitness_review_v1",
        "status": "succeeded",
        "period": f"{start.isoformat()}/{ending.isoformat()}",
        "daily_summary_count": 7,
        "evidence_consistency": "verified",
        "daily_input_sha256": daily_hashes,
        "activity_days": activity_days,
        "sleep_complete_days": sleep_complete_days,
        "provider_calls": 0,
    }
    _, review_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="weekly-fitness-summary",
        operation="summarize_week",
        output_kind="weekly_fitness_review",
        logical_key=f"weekly:{ending.isoformat()}:review",
        payload=review_payload,
        period_start=start.isoformat(),
        period_end=ending.isoformat(),
        lineage=[{"input_sha256": digest} for digest in daily_hashes],
    )
    plan = _weekly_plan(ending + timedelta(days=1), daily)
    plan_file = output_dir / "training_plan.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    validation = subprocess.run(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "training-coach/scripts/validate_course.py"
            ),
            str(plan_file),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if validation.returncode:
        raise RuntimeError("weekly_course_invalid")
    _, plan_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="training-coach",
        operation="validate_plan",
        output_kind="training_plan",
        logical_key=f"weekly:{ending.isoformat()}:plan",
        payload=plan,
        period_start=(ending + timedelta(days=1)).isoformat(),
        period_end=(ending + timedelta(days=7)).isoformat(),
        lineage=[{"input_sha256": sha256_text(canonical_json(day))} for day in daily],
    )
    weekly_summary = {
        "schema_version": "weekly_summary_v1",
        "status": "succeeded",
        "period": f"{start.isoformat()}/{ending.isoformat()}",
        "daily_count": len(daily),
        "daily_input_sha256": daily_hashes,
        "review_output_id": review_id,
        "evidence_consistency": "verified",
        "activity_days": activity_days,
        "sleep_complete_days": sleep_complete_days,
        "training_plan": plan,
        "progression_decision": "hold",
        "provider_calls": 0,
    }
    _, summary_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="training-coach",
        operation="weekly_coach",
        output_kind="weekly_summary",
        logical_key=f"weekly:{ending.isoformat()}:summary",
        payload=weekly_summary,
        period_start=start.isoformat(),
        period_end=ending.isoformat(),
        lineage=[{"input_sha256": sha256_text(canonical_json(day))} for day in daily],
    )
    gts = subprocess.run(
        [
            _python(),
            str(
                Path(__file__).resolve().parents[2]
                / "garmin-training-sender/scripts/prepare_gts.py"
            ),
            str(plan_file),
            "--database",
            str(database),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if gts.returncode:
        raise RuntimeError("weekly_gts_contract_blocked")
    gts_payload = json.loads(gts.stdout) if gts.stdout.strip() else {}
    report = {
        "title": f"TrainLab · {ending.isoformat()} 周总结",
        "period": f"{(ending + timedelta(days=1)).isoformat()}/{(ending + timedelta(days=7)).isoformat()}",
        "content": weekly_summary,
    }
    rendered = _render(database, "weekly", report, output_dir)
    email_id = _prepare_email(database, output_dir, "weekly")
    render_ids = (
        [
            int(value)
            for key, value in rendered["output_ids"].items()
            if key in {"report_artifact", "email_render"}
        ]
        if isinstance(rendered.get("output_ids"), dict)
        else list(rendered.get("output_ids") or [])
    )
    receipt = {
        "schema_version": "workflow_receipt_v1",
        "status": "succeeded",
        "outcome": "daily_weekly_complete",
        "workflow_key": workflow_key,
        "provider_calls": 0,
        "summary_output_id": summary_id,
        "review_output_id": review_id,
        "history_output_id": _latest_output_id(
            database,
            output_kind="bounded_evidence",
            logical_prefix=f"weekly-fitness-summary:history:{ending.isoformat()}",
        ),
        "plan_output_id": plan_id,
        "gts_output_id": _latest_output_id(
            database, output_kind="garmin_workout_contract"
        ),
        "render_output_ids": render_ids,
        "email_output_id": email_id,
        "gts_prepared": True,
        "gts_actions": len(gts_payload.get("actions", []))
        if isinstance(gts_payload, dict)
        else 0,
    }
    _, receipt_id = _bounded_output(
        database,
        workflow_key=workflow_key,
        skill_name="gmail-sender",
        operation="send_email",
        output_kind="execution_summary",
        logical_key=f"workflow:{workflow_key}",
        payload=receipt,
    )
    return {
        **receipt,
        "output_ids": [
            summary_id,
            plan_id,
            review_id,
            email_id,
            receipt_id,
            *render_ids,
        ],
    }


def run_weekly(database: Path, ending: date, output_dir: Path) -> dict[str, Any]:
    with workflow_lock(database):
        return _run_weekly_unlocked(database, ending, output_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument(
        "--date", required=True, help="Internal candidate-only test date"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = (
        run_daily(args.database, date.fromisoformat(args.date), args.output_dir)
        if args.mode == "daily"
        else run_weekly(args.database, date.fromisoformat(args.date), args.output_dir)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
