#!/usr/bin/env python3
"""Run the approved M10 seven-daily plus weekly AI/report preparation flow."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills._shared.scripts.schema_validation import validate_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_file,
    sha256_text,
    workflow_lock,
)

REPORT_START = date(2026, 8, 12)
REPORT_END = date(2026, 8, 18)
WEEK_END = date(2026, 8, 18)
MAX_AI_CALLS = 8
ROLLING_WORKFLOW_KEY = "m10:rolling-week:2026-08-11/2026-08-18"
AI_CALL_ROLE = "m10_rolling_ai_call_v1"


class RollingCoachError(RuntimeError):
    """A stable M10 AI/report preparation failure."""


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RollingCoachError(f"{name}_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _atomic_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise RollingCoachError("m10_artifact_empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
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


def _assert_candidate(source_root: Path, database: Path) -> tuple[Path, Path]:
    rolling = _load(
        "trainlab_m10_candidate_guard",
        Path(__file__).resolve().parents[2]
        / "garmin-sync/scripts/rolling_week_sync.py",
    )
    try:
        return rolling._assert_candidate_for_reuse(source_root, database)
    except Exception as exc:
        raise RollingCoachError("m10_candidate_scope_required") from exc


def _rolling_receipt(database: Path, output_id: int) -> tuple[dict[str, Any], str]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT so.id FROM skill_outputs so "
            "WHERE so.schema_name='garmin_rolling_week_receipt_v1'"
        ).fetchall()
        row = connection.execute(
            "SELECT so.content_json,so.content_sha256,so.schema_name,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (output_id,),
        ).fetchone()
    finally:
        connection.close()
    if (
        len(rows) != 1
        or int(rows[0][0]) != output_id
        or row is None
        or str(row[2]) != "garmin_rolling_week_receipt_v1"
    ):
        raise RollingCoachError("m10_rolling_receipt_missing")
    payload = json.loads(str(row[0]))
    if (
        str(row[3]) != "succeeded"
        or payload.get("status") != "succeeded"
        or payload.get("workflow_key") != ROLLING_WORKFLOW_KEY
        or len(payload.get("daily_windows", {})) != 7
    ):
        raise RollingCoachError("m10_rolling_receipt_incomplete")
    return payload, str(row[1])


def _matching_outputs(
    database: Path,
    mode: str,
    target: date,
    *,
    rolling_sync_output_id: int,
    required_daily_output_ids: list[int] | None = None,
) -> list[tuple[int, dict[str, Any], int]]:
    kind = "daily_summary" if mode == "daily" else "weekly_summary"
    schema = "daily_ai_result_v1" if mode == "daily" else "weekly_ai_result_v1"
    period = target.isoformat()
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT so.id,so.content_json,so.skill_run_id,sr.input_manifest_json "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.output_kind=? AND so.schema_name=? AND so.period_end_date=? "
            "AND sr.status='succeeded' AND sr.skill_name='training-coach' "
            "AND sr.operation=? ORDER BY so.revision_no DESC,so.id DESC",
            (
                kind,
                schema,
                period,
                "daily_coach" if mode == "daily" else "weekly_coach",
            ),
        ).fetchall()
    finally:
        connection.close()
    expected_ids = set(required_daily_output_ids or [])
    matches: list[tuple[int, dict[str, Any], int]] = []
    for row in rows:
        payload = json.loads(str(row[1]))
        manifest = json.loads(str(row[3]))
        context = manifest.get("context") if isinstance(manifest, dict) else None
        if not isinstance(context, dict) or validate_payload(payload, schema):
            continue
        if mode == "daily":
            live_sync = context.get("live_sync")
            if (
                payload.get("report_date") != period
                or not isinstance(live_sync, dict)
                or live_sync.get("output_id") != rolling_sync_output_id
            ):
                continue
        else:
            daily_reports = context.get("daily_reports")
            context_ids = {
                int(item["output_id"])
                for item in daily_reports or []
                if isinstance(item, dict)
                and isinstance(item.get("output_id"), int)
                and not isinstance(item.get("output_id"), bool)
            }
            if (
                payload.get("period")
                != f"{REPORT_START.isoformat()}/{REPORT_END.isoformat()}"
                or len(expected_ids) != 7
                or context_ids != expected_ids
            ):
                continue
        matches.append((int(row[0]), payload, int(row[2])))
    return matches


def _existing_output(
    database: Path,
    mode: str,
    target: date,
    *,
    rolling_sync_output_id: int,
    required_daily_output_ids: list[int] | None = None,
) -> tuple[int, dict[str, Any], int] | None:
    matches = _matching_outputs(
        database,
        mode,
        target,
        rolling_sync_output_id=rolling_sync_output_id,
        required_daily_output_ids=required_daily_output_ids,
    )
    return matches[0] if matches else None


def _claim_ai_call(
    database: Path,
    *,
    mode: str,
    target: date,
    rolling_sync_output_id: int,
    prompt_path: Path,
    schema_path: Path,
) -> int:
    target_key = f"{mode}:{target.isoformat()}"
    input_manifest = {
        "m10_role": AI_CALL_ROLE,
        "target": target_key,
        "rolling_sync_output_id": rolling_sync_output_id,
        "prompt_sha256": sha256_file(prompt_path),
        "schema_sha256": sha256_file(schema_path),
    }
    dedupe = sha256_text(canonical_json(input_manifest))
    with workflow_lock(database):
        connection = connect(database)
        try:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM skill_runs "
                    "WHERE json_extract(input_manifest_json,'$.m10_role')=? "
                    "AND json_extract(input_manifest_json,'$.rolling_sync_output_id')=?",
                    (AI_CALL_ROLE, rolling_sync_output_id),
                ).fetchone()[0]
            )
            existing = connection.execute(
                "SELECT id FROM skill_runs "
                "WHERE json_extract(input_manifest_json,'$.m10_role')=? "
                "AND json_extract(input_manifest_json,'$.rolling_sync_output_id')=? "
                "AND json_extract(input_manifest_json,'$.target')=?",
                (AI_CALL_ROLE, rolling_sync_output_id, target_key),
            ).fetchone()
            if existing is not None:
                raise RollingCoachError("m10_ai_attempt_already_recorded")
            if count >= MAX_AI_CALLS:
                raise RollingCoachError("m10_ai_budget_exceeded")
            return begin_run(
                connection,
                run_key=f"training-coach:m10-call:{target_key}:{dedupe}",
                workflow_key=f"m10:{target_key}",
                dedupe_key=dedupe,
                skill_name="training-coach",
                operation="daily_coach" if mode == "daily" else "weekly_coach",
                trigger_kind="manual",
                input_manifest=input_manifest,
                input_sha256=sha256_text(canonical_json(input_manifest)),
                target_from_date=target.isoformat(),
                target_through_date=target.isoformat(),
            )
        finally:
            connection.close()


def _finish_ai_call(
    database: Path, run_id: int, *, status: str, error_code: str | None = None
) -> None:
    connection = connect(database)
    try:
        finish_run(connection, run_id, status=status, error_code=error_code)
    finally:
        connection.close()


def _invoke_codex(
    *,
    executable: Path,
    source_root: Path,
    prompt_path: Path,
    schema_path: Path,
    result_path: Path,
    events_path: Path,
    stderr_path: Path,
) -> None:
    prompt = prompt_path.read_bytes()
    command = [
        str(executable),
        "exec",
        "-C",
        str(source_root),
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--output-schema",
        str(schema_path),
        "--json",
        "--output-last-message",
        str(result_path),
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=source_root,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RollingCoachError("m10_ai_timeout") from exc
    _atomic_write(events_path, completed.stdout or b'{"status":"no_events"}\n')
    _atomic_write(stderr_path, completed.stderr or b"m10 codex stderr empty\n")
    if completed.returncode != 0:
        raise RollingCoachError("m10_ai_failed")
    if not result_path.is_file() or result_path.is_symlink():
        raise RollingCoachError("m10_ai_result_missing")
    metadata = result_path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
    ):
        raise RollingCoachError("m10_ai_result_invalid")
    os.chmod(result_path, 0o600)


def _render_and_prepare(
    *,
    source_root: Path,
    database: Path,
    output_dir: Path,
    mode: str,
    payload: dict[str, Any],
    source_output_id: int,
) -> dict[str, Any]:
    renderer = _load(
        "trainlab_m10_renderer",
        Path(__file__).resolve().parents[2]
        / "training-report-publisher/scripts/render_report.py",
    )
    kind = "daily" if mode == "daily" else "weekly"
    period = payload["report_date"] if mode == "daily" else payload["period"]
    title = (
        f"TrainLab · M10验收 · 每日训练简报 · {period}"
        if mode == "daily"
        else f"TrainLab · M10验收 · 每周训练总结 · {period}"
    )
    report_payload = {"title": title, "period": period, "content": payload}
    template = (
        source_root / "templates/open-report" / f"{kind}_report.html"
    ).read_text(encoding="utf-8")
    html = renderer.render(
        template,
        title,
        period,
        renderer.body_html(report_payload["content"]),
        fixed=False,
        payload=report_payload,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    report_json = output_dir / "report.json"
    report_html = output_dir / "report.html"
    _atomic_write(
        report_json,
        (
            json.dumps(report_payload, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode(),
    )
    _atomic_write(report_html, html.encode())
    output_ids = renderer.persist_outputs(
        database,
        kind=kind,
        mode="open_report",
        title_text=title,
        payload=report_payload,
        html=html,
        include_email_render=True,
        source_output_id=source_output_id,
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        email = connection.execute(
            "SELECT content_sha256,title_text,content_text,content_html FROM skill_outputs "
            "WHERE id=? AND output_kind='email_render'",
            (int(output_ids["email_render"]),),
        ).fetchone()
        source = connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (source_output_id,)
        ).fetchone()
    finally:
        connection.close()
    if email is None or source is None:
        raise RollingCoachError("m10_report_lineage_missing")
    envelope = {
        "subject": str(email[1]),
        "text": str(email[2]),
        "html": str(email[3]),
        "report_output_id": int(output_ids["email_render"]),
        "report_output_sha256": str(email[0]),
        "source_output_id": source_output_id,
        "source_output_sha256": str(source[0]),
    }
    envelope_path = output_dir / "email-envelope.json"
    _atomic_write(
        envelope_path,
        (
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    )
    prepare = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[2]
                / "gmail-sender/scripts/prepare_message.py"
            ),
            str(envelope_path),
            "--database",
            str(database),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if prepare.returncode != 0:
        raise RollingCoachError("m10_email_prepare_failed")
    prepared = json.loads(prepare.stdout)
    if prepared.get("status") != "prepared" or prepared.get("provider_calls") != 0:
        raise RollingCoachError("m10_email_prepare_failed")
    return {
        "report_json": str(report_json),
        "report_html": str(report_html),
        "email_envelope": str(envelope_path),
        "subject": title,
        "output_ids": output_ids,
        "email_marker": prepared["marker"],
    }


def _run_one(
    *,
    mode: str,
    target: date,
    source_root: Path,
    database: Path,
    run_root: Path,
    executable: Path,
    rolling_sync_output_id: int,
    required_daily_output_ids: list[int] | None = None,
) -> tuple[dict[str, Any], bool]:
    target_dir = run_root / (
        f"daily-{target.isoformat()}" if mode == "daily" else "weekly"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, 0o700)
    existing = _existing_output(
        database,
        mode,
        target,
        rolling_sync_output_id=rolling_sync_output_id,
        required_daily_output_ids=required_daily_output_ids,
    )
    model_called = False
    if existing is None:
        prompt_module = _load(
            f"trainlab_m10_prompt_{mode}",
            Path(__file__).resolve().parent / "create_ai_prompt.py",
        )
        context_path = target_dir / "context.json"
        prompt_path = target_dir / "prompt.txt"
        context = prompt_module.create(
            mode=mode,
            target=target,
            database=database,
            source_root=source_root,
            context_path=context_path,
            prompt_path=prompt_path,
            rolling_sync_output_id=(
                rolling_sync_output_id if mode == "daily" else None
            ),
            required_daily_output_ids=required_daily_output_ids,
        )
        schema_name = (
            "daily_ai_result_codex_v2.schema.json"
            if mode == "daily"
            else "weekly_ai_codex_response_v1.schema.json"
        )
        schema_path = source_root / "skills/_shared/schemas" / schema_name
        result_path = target_dir / "ai-result.json"
        call_run_id = _claim_ai_call(
            database,
            mode=mode,
            target=target,
            rolling_sync_output_id=rolling_sync_output_id,
            prompt_path=prompt_path,
            schema_path=schema_path,
        )
        try:
            _invoke_codex(
                executable=executable,
                source_root=source_root,
                prompt_path=prompt_path,
                schema_path=schema_path,
                result_path=result_path,
                events_path=target_dir / "events.jsonl",
                stderr_path=target_dir / "stderr.log",
            )
        except Exception as exc:
            _finish_ai_call(
                database,
                call_run_id,
                status="failed",
                error_code=str(exc)[:200] or "m10_ai_failed",
            )
            raise
        _finish_ai_call(database, call_run_id, status="succeeded")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        wire_schema = (
            "daily_ai_result_codex_v2"
            if mode == "daily"
            else "weekly_ai_codex_response_v1"
        )
        if validate_payload(payload, wire_schema):
            raise RollingCoachError("m10_ai_wire_schema_invalid")
        commit_module = _load(
            f"trainlab_m10_commit_{mode}",
            Path(__file__).resolve().parent / "commit_ai_result.py",
        )
        committed = commit_module.commit(payload, context, database, mode)
        if committed.get("status") != "succeeded":
            raise RollingCoachError(
                str(committed.get("error_code", "m10_ai_commit_failed"))
            )
        source_output_id = int(committed["output_id"])
        canonical_output = _existing_output(
            database,
            mode,
            target,
            rolling_sync_output_id=rolling_sync_output_id,
            required_daily_output_ids=required_daily_output_ids,
        )
        if canonical_output is None or canonical_output[0] != source_output_id:
            raise RollingCoachError("m10_committed_output_missing")
        source_output_id, payload, _source_run_id = canonical_output
        model_called = True
    else:
        source_output_id, payload, _source_run_id = existing
    report = _render_and_prepare(
        source_root=source_root,
        database=database,
        output_dir=target_dir / "open-report",
        mode=mode,
        payload=payload,
        source_output_id=source_output_id,
    )
    report.update(
        {
            "mode": mode,
            "target": target.isoformat(),
            "source_output_id": source_output_id,
            "model_called": model_called,
        }
    )
    return report, model_called


def _assert_resume_ready(database: Path, rolling_sync_output_id: int) -> None:
    expected_targets = {
        *(
            f"daily:{(REPORT_START + timedelta(days=index)).isoformat()}"
            for index in range(7)
        ),
        f"weekly:{WEEK_END.isoformat()}",
    }
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT sr.status,sr.input_manifest_json,sr.skill_name,sr.operation,"
            "sr.workflow_key,sr.trigger_kind FROM skill_runs sr"
        ).fetchall()
    finally:
        connection.close()
    actual_targets: set[str] = set()
    ai_rows = 0
    for row in rows:
        raw_manifest = str(row[1])
        pairs = json.loads(raw_manifest, object_pairs_hook=lambda value: value)
        if not isinstance(pairs, list):
            continue
        role_pairs = [value for key, value in pairs if key == "m10_role"]
        if not role_pairs:
            continue
        if len(role_pairs) != 1 or role_pairs[0] != AI_CALL_ROLE:
            raise RollingCoachError("m10_resume_ai_history_invalid")
        ai_rows += 1
        manifest = json.loads(raw_manifest)
        target = manifest.get("target") if isinstance(manifest, dict) else None
        expected_operation = (
            "daily_coach"
            if isinstance(target, str) and target.startswith("daily:")
            else "weekly_coach"
        )
        manifest_keys = {
            "m10_role",
            "target",
            "rolling_sync_output_id",
            "prompt_sha256",
            "schema_sha256",
        }
        if (
            str(row[0]) != "succeeded"
            or not isinstance(target, str)
            or canonical_json(manifest) != raw_manifest
            or set(manifest) != manifest_keys
            or manifest.get("m10_role") != AI_CALL_ROLE
            or manifest.get("rolling_sync_output_id") != rolling_sync_output_id
            or not isinstance(manifest.get("prompt_sha256"), str)
            or len(str(manifest.get("prompt_sha256"))) != 64
            or not isinstance(manifest.get("schema_sha256"), str)
            or len(str(manifest.get("schema_sha256"))) != 64
            or str(row[2]) != "training-coach"
            or str(row[3]) != expected_operation
            or str(row[4]) != f"m10:{target}"
            or str(row[5]) != "manual"
        ):
            raise RollingCoachError("m10_resume_ai_history_invalid")
        actual_targets.add(target)
    if ai_rows != MAX_AI_CALLS or actual_targets != expected_targets:
        raise RollingCoachError("m10_resume_ai_history_invalid")

    daily_ids: list[int] = []
    for index in range(7):
        matches = _matching_outputs(
            database,
            "daily",
            REPORT_START + timedelta(days=index),
            rolling_sync_output_id=rolling_sync_output_id,
        )
        if len(matches) != 1:
            raise RollingCoachError("m10_resume_output_cardinality_invalid")
        daily_ids.append(int(matches[0][0]))
    weekly = _matching_outputs(
        database,
        "weekly",
        WEEK_END,
        rolling_sync_output_id=rolling_sync_output_id,
        required_daily_output_ids=daily_ids,
    )
    if len(weekly) != 1:
        raise RollingCoachError("m10_resume_output_cardinality_invalid")


def run(
    *,
    source_root: Path,
    database: Path,
    run_root: Path,
    executable: Path,
    rolling_sync_output_id: int,
    candidate_guard: Any | None = None,
    resume_existing: bool = False,
) -> dict[str, Any]:
    os.umask(0o077)
    source_root, database = (candidate_guard or _assert_candidate)(
        source_root, database
    )
    _rolling_receipt(database, rolling_sync_output_id)
    if resume_existing:
        if run_root.is_symlink() or not run_root.is_dir():
            raise RollingCoachError("m10_resume_root_invalid")
        metadata = run_root.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RollingCoachError("m10_resume_root_invalid")
        _assert_resume_ready(database, rolling_sync_output_id)
    else:
        if run_root.exists() or run_root.is_symlink():
            raise RollingCoachError("m10_run_root_exists")
        run_root.mkdir(parents=True, mode=0o700)
        os.chmod(run_root, 0o700)
    reports: list[dict[str, Any]] = []
    calls = 0
    for index in range(7):
        report, called = _run_one(
            mode="daily",
            target=REPORT_START + timedelta(days=index),
            source_root=source_root,
            database=database,
            run_root=run_root,
            executable=executable,
            rolling_sync_output_id=rolling_sync_output_id,
        )
        reports.append(report)
        calls += int(called)
    weekly, called = _run_one(
        mode="weekly",
        target=WEEK_END,
        source_root=source_root,
        database=database,
        run_root=run_root,
        executable=executable,
        rolling_sync_output_id=rolling_sync_output_id,
        required_daily_output_ids=[int(item["source_output_id"]) for item in reports],
    )
    reports.append(weekly)
    calls += int(called)
    if calls > MAX_AI_CALLS:
        raise RollingCoachError("m10_ai_budget_exceeded")

    connection = connect(database, read_only=True, immutable=True)
    try:
        weekly_run = connection.execute(
            "SELECT skill_run_id FROM skill_outputs WHERE id=?",
            (int(weekly["source_output_id"]),),
        ).fetchone()
        plan_row = (
            connection.execute(
                "SELECT id,content_json,lineage_json FROM skill_outputs "
                "WHERE output_kind='training_plan' AND schema_name='training_plan_v1' "
                "AND skill_run_id=? AND period_start_date=? AND period_end_date=?",
                (
                    int(weekly_run[0]),
                    REPORT_START.isoformat(),
                    WEEK_END.isoformat(),
                ),
            ).fetchone()
            if weekly_run is not None
            else None
        )
    finally:
        connection.close()
    if plan_row is None:
        raise RollingCoachError("m10_training_plan_missing")
    expected_daily_ids = {int(item["source_output_id"]) for item in reports[:7]}
    lineage = json.loads(str(plan_row[2]))
    if {
        int(item["output_id"])
        for item in lineage
        if isinstance(item, dict) and isinstance(item.get("output_id"), int)
    } != expected_daily_ids:
        raise RollingCoachError("m10_training_plan_lineage_mismatch")
    plan_path = run_root / "weekly" / "training-plan.json"
    _atomic_write(plan_path, (str(plan_row[1]) + "\n").encode())
    prepared = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[2]
                / "garmin-training-sender/scripts/prepare_gts.py"
            ),
            str(plan_path),
            "--database",
            str(database),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if prepared.returncode != 0:
        raise RollingCoachError("m10_gts_prepare_failed")
    gts = json.loads(prepared.stdout)
    if gts.get("status") != "prepared" or len(gts.get("actions", [])) > 4:
        raise RollingCoachError("m10_gts_prepare_failed")
    result = {
        "schema_version": "m10_rolling_week_prewrite_v1",
        "status": "prepared",
        "reports": reports,
        "subjects": [item["subject"] for item in reports],
        "training_plan_output_id": int(plan_row[0]),
        "gts": gts,
        "ai_calls": MAX_AI_CALLS,
        "ai_calls_this_run": calls,
        "gmail_calls": 0,
        "garmin_workout_calls": 0,
        "external_actions": 0,
    }
    _atomic_write(
        run_root / "prewrite-manifest.json",
        (
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--rolling-sync-output-id", type=int, required=True)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--codex", type=Path, default=Path(shutil.which("codex") or ""))
    args = parser.parse_args()
    if not args.resume_existing and not args.codex.is_file():
        raise SystemExit("codex_runtime_unavailable")
    try:
        result = run(
            source_root=args.source_root.resolve(),
            database=args.database.resolve(),
            run_root=args.run_root,
            executable=args.codex.resolve(),
            rolling_sync_output_id=args.rolling_sync_output_id,
            resume_existing=args.resume_existing,
        )
    except RollingCoachError as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
