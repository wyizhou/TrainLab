#!/usr/bin/env python3
"""Commit one validated M9 AI daily result without any external action."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date
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


def _load(relative: str, name: str) -> Any:
    source = Path(__file__).resolve().parents[3]
    path = source / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name}_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    parent = Path(os.path.abspath(path.parent))
    metadata = parent.lstat()
    if (
        parent.resolve(strict=True) != parent
        or not parent.is_dir()
        or parent.is_symlink()
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o700
    ):
        raise ValueError("report_output_scope_invalid")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _sha_for_output(connection: Any, output_id: int) -> str:
    row = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
    ).fetchone()
    if row is None:
        raise ValueError("workflow_output_missing")
    return str(row[0])


def _prepare_output_dir(source_root: Path, output_dir: Path) -> Path:
    candidate_root = Path(os.path.abspath(source_root)).parent
    destination = Path(os.path.abspath(output_dir))
    if not destination.is_relative_to(candidate_root) or destination == candidate_root:
        raise ValueError("report_output_scope_invalid")
    current = candidate_root
    try:
        candidate_metadata = current.lstat()
    except OSError as exc:
        raise ValueError("report_output_scope_invalid") from exc
    if (
        current.resolve(strict=True) != current
        or not current.is_dir()
        or current.is_symlink()
        or candidate_metadata.st_uid != os.getuid()
        or candidate_metadata.st_mode & 0o777 != 0o700
    ):
        raise ValueError("report_output_scope_invalid")
    for part in destination.relative_to(candidate_root).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            metadata = current.lstat()
            if (
                current.resolve(strict=True) != current
                or not current.is_dir()
                or current.is_symlink()
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o777 != 0o700
            ):
                raise ValueError("report_output_scope_invalid")
        else:
            current.mkdir(mode=0o700)
    return destination


def _require_succeeded_sync_receipt(database: Path, output_id: int) -> None:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT so.schema_name,sr.status FROM skill_outputs so "
            "JOIN skill_runs sr ON sr.id=so.skill_run_id WHERE so.id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[0]) != "garmin_live_sync_receipt_v1":
        raise ValueError("garmin_live_sync_receipt_missing")
    if str(row[1]) != "succeeded":
        raise ValueError("garmin_live_sync_receipt_incomplete")


def complete(
    source_root: Path,
    database: Path,
    run_root: Path,
    canary_receipt: Path,
    output_dir: Path,
) -> dict[str, Any]:
    live = _load("skills/garmin-sync/scripts/live_sync.py", "trainlab_m9_live")
    try:
        live._assert_candidate_scope(source_root, database)
    except live.LiveSyncError as exc:
        raise ValueError(str(exc)) from exc
    candidate_root = Path(os.path.abspath(source_root)).parent
    expected_run_root = candidate_root / "run/daily-20260817"
    if Path(os.path.abspath(run_root)) != expected_run_root:
        raise ValueError("ai_run_root_invalid")
    runtime = _load(
        "skills/training-coach/scripts/codex_attempt_runtime.py",
        "trainlab_m9_codex_attempt",
    )
    try:
        _attempt_receipt, ai_payload, context = runtime.load_succeeded_result(
            run_root=run_root,
            canary_receipt_path=canary_receipt,
        )
    except runtime.RunnerBlocked as exc:
        raise ValueError(str(exc)) from exc
    if context.get("status") != "ready":
        raise ValueError("daily_context_not_ready")
    live_sync = context.get("live_sync")
    if not isinstance(live_sync, dict):
        raise ValueError("garmin_live_sync_receipt_missing")
    sync_output_id = live_sync.get("output_id")
    if not isinstance(sync_output_id, int):
        raise ValueError("garmin_live_sync_receipt_missing")
    _require_succeeded_sync_receipt(database, sync_output_id)
    context_builder = _load(
        "skills/training-coach/scripts/build_context.py", "trainlab_m9_context"
    )
    canonical_context = context_builder.build_daily_context(
        database,
        source_root,
        date(2026, 8, 17),
        live_sync_output_id=sync_output_id,
    )
    if canonical_json(canonical_context) != canonical_json(context):
        raise ValueError("daily_context_receipt_mismatch")
    output_dir = _prepare_output_dir(source_root, output_dir)

    coach = _load(
        "skills/training-coach/scripts/commit_ai_result.py", "trainlab_m9_commit"
    )
    committed = coach.commit(ai_payload, context, database, "daily")
    if committed.get("status") != "succeeded":
        return committed
    summary_output_id = int(committed["output_id"])

    publisher = _load(
        "skills/training-report-publisher/scripts/render_report.py",
        "trainlab_m9_report",
    )
    report_payload: dict[str, object] = {
        "title": "TrainLab · 每日训练简报",
        "period": str(ai_payload["report_date"]),
        "content": ai_payload,
    }
    template = (
        Path(__file__).resolve().parents[3] / "templates/open-report/daily_report.html"
    ).read_text(encoding="utf-8")
    html = publisher.render(
        template,
        str(report_payload["title"]),
        str(report_payload["period"]),
        publisher.body_html(ai_payload),
        fixed=False,
        payload=report_payload,
    )
    _write(
        output_dir / "report.json",
        json.dumps(report_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    _write(output_dir / "report.html", html)
    report_outputs = publisher.persist_outputs(
        database,
        kind="daily",
        mode="open_report",
        title_text=str(report_payload["title"]),
        payload=report_payload,
        html=html,
        include_email_render=False,
    )
    report_output_id = int(report_outputs["report_artifact"])

    receipt = {
        "schema_version": "workflow_receipt_v1",
        "status": "succeeded",
        "outcome": "daily_complete",
        "workflow_key": "daily:2026-08-17",
        "provider_calls": 0,
        "summary_output_id": summary_output_id,
        "sync_output_id": sync_output_id,
        "render_output_ids": [report_output_id],
        "warnings": [],
    }
    require_valid_payload(receipt, "workflow_receipt_v1")
    manifest = {
        "receipt": receipt,
        "summary_sha256": sha256_text(canonical_json(ai_payload)),
    }
    digest = sha256_text(canonical_json(manifest))
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"garmin-live:daily:2026-08-17:receipt:{digest}:attempt-1",
            workflow_key="daily:2026-08-17",
            dedupe_key=digest,
            skill_name="training-report-publisher",
            operation="render_daily",
            trigger_kind="skill",
            input_manifest=manifest,
            target_from_date="2026-08-17",
            target_through_date="2026-08-17",
        )
        receipt_output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="execution_summary",
            logical_key="workflow:daily:2026-08-17",
            schema_name="workflow_receipt_v1",
            schema_version="1",
            content_json=receipt,
            content_text=canonical_json(receipt),
            lineage=[
                {
                    "output_id": output_id,
                    "output_sha256": _sha_for_output(connection, output_id),
                }
                for output_id in (
                    sync_output_id,
                    summary_output_id,
                    report_output_id,
                )
            ],
            period_start_date="2026-08-17",
            period_end_date="2026-08-17",
        )
        current = connection.execute(
            "SELECT status FROM skill_runs WHERE id=?", (run_id,)
        ).fetchone()
        if current is not None and str(current[0]) == "running":
            finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    return {
        "status": "succeeded",
        "workflow_key": "daily:2026-08-17",
        "sync_output_id": sync_output_id,
        "summary_output_id": summary_output_id,
        "report_output_id": report_output_id,
        "receipt_output_id": receipt_output_id,
        "provider_calls": 0,
        "external_actions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--canary-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = complete(
        args.source_root,
        args.database,
        args.run_root,
        args.canary_receipt,
        args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
