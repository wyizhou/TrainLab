from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable
sys.path.insert(0, str(ROOT))
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    require_lastrowid,
)


def run_script(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(path), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_goal_module_and_private_mode(tmp_path: Path) -> None:
    module = ROOT / "goal.module.md"
    goal = tmp_path / "goal.md"
    goal.write_text(
        module.read_text(encoding="utf-8")
        .replace("【请填写】", "测试值")
        .replace("【无则填写“无”】", "无"),
        encoding="utf-8",
    )
    goal.chmod(0o600)
    result = run_script(
        ROOT / "skills/_shared/scripts/validate_goal.py",
        "--goal",
        str(goal),
        "--module",
        str(module),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_window_does_not_read_history() -> None:
    result = run_script(
        ROOT / "skills/garmin-sync/scripts/plan_window.py", "--run-date", "2026-08-15"
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["history_readback_days"] == 0
    assert payload["activity_summary"] is False
    assert payload["main_sleep_wake_date"] == "2026-08-15"


def test_state_schema_is_exact(tmp_path: Path) -> None:
    db = tmp_path / "trainlab.db"
    created = run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(db)
    )
    assert created.returncode == 0, created.stdout + created.stderr
    verified = run_script(
        ROOT / "skills/_shared/scripts/verify_state.py", "--database", str(db)
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    payload = json.loads(verified.stdout)
    assert payload["schema_exact"] is True
    content_fingerprint = payload["formal_state_content_fingerprint"]
    assert (
        content_fingerprint["schema_version"] == "formal_state_content_fingerprint_v1"
    )
    assert content_fingerprint["entry_count"] == 1
    assert content_fingerprint["raw_file_count"] == 0
    assert len(content_fingerprint["sha256"]) == 64
    connection = connect(db)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    for table in (
        "skill_runs",
        "activity_inventory",
        "raw_files",
        "skill_outputs",
        "approvals",
        "external_actions",
    ):
        assert all(
            row[6] == "RESTRICT"
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        )
    connection.close()


def test_course_rejects_missing_dose(tmp_path: Path) -> None:
    course = tmp_path / "course.json"
    course.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "date": "2026-08-17",
                        "activity_kind": "running",
                        "name": "Easy-GTS",
                        "purpose": "easy",
                        "garmin_mapping_status": "candidate",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = run_script(
        ROOT / "skills/training-coach/scripts/validate_course.py", str(course)
    )
    assert result.returncode != 0
    assert "dose_missing" in result.stdout


def test_gts_prepare_is_network_free(tmp_path: Path) -> None:
    course = tmp_path / "course.json"
    items = []
    for offset in range(7):
        kind = "running" if offset in {0, 2, 4, 6} else "rest"
        item = {
            "date": f"2026-08-{17 + offset:02d}",
            "activity_kind": kind,
            "name": "Easy-6KM-GTS" if kind == "running" else "恢复日",
            "purpose": "easy" if kind == "running" else "recovery",
            "load_level": "moderate" if kind == "running" else "low",
            "garmin_mapping_status": "candidate"
            if kind == "running"
            else "unsupported_skip",
            "rpe": 3 if kind == "running" else 1,
            "downgrade_rule": "睡眠差时休息。",
            "stop_conditions": ["疼痛或异常呼吸立即停止。"],
            "steps": [{"name": "主课", "end_condition": "完成目标"}],
        }
        if kind == "running":
            item["distance_km"] = 6
        items.append(item)
    course.write_text(
        json.dumps(
            {
                "schema_version": "training_plan_v1",
                "status": "succeeded",
                "items": items,
                "progression_rule": "hold",
                "progression_dimension": "none",
                "provider_calls": 0,
            }
        ),
        encoding="utf-8",
    )
    result = run_script(
        ROOT / "skills/garmin-training-sender/scripts/prepare_gts.py", str(course)
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["provider_calls"] == 0


def test_state_rejects_duplicate_active_runs_and_mismatched_actions(
    tmp_path: Path,
) -> None:
    db = tmp_path / "trainlab.db"
    run_script(ROOT / "skills/_shared/scripts/init_state.py", "--database", str(db))
    connection = connect(db)
    manifest_sha = hashlib.sha256(b"{}").hexdigest()
    connection.execute(
        """INSERT INTO skill_runs
        (run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,attempt_no,
         input_manifest_json,input_sha256,status,created_at_utc,finished_at_utc)
            VALUES ('r1','w','d','garmin-sync','daily_sync','manual',1,'{}',
                    ?, 'succeeded',
                    '2026-01-01T00:00:00Z','2026-01-01T00:00:01Z')""",
        (manifest_sha,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO skill_runs
            (run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,attempt_no,
             input_manifest_json,input_sha256,status,created_at_utc)
            VALUES ('r2','w','d','garmin-sync','daily_sync','manual',2,'{}',
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                    'running','2026-01-01T00:00:01Z')"""
        )
    connection.commit()
    connection.close()


def test_online_backup_creates_verified_pair(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    prefix = hashlib.sha256(database.read_bytes()).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = tmp_path / f"backups/trainlab-{stamp}-test-backup-{prefix}.db"
    result = run_script(
        ROOT / "skills/_shared/scripts/backup_state.py",
        str(destination),
        "--database",
        str(database),
        "--backup-type",
        "pre_change",
        "--operation-id",
        "test-backup",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    destination = Path(result.stdout.splitlines()[0])
    manifest = destination.with_suffix(".manifest.json")
    assert destination.stat().st_mode & 0o777 == 0o600
    assert manifest.stat().st_mode & 0o777 == 0o600
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["backup_type"] == "pre_change"
    assert payload["integrity_check"] == "ok"
    assert "highest_ids" in payload
    assert "raw_index" in payload
    assert "skill_versions" in payload


def test_mail_prepare_rejects_script_html(tmp_path: Path) -> None:
    message = tmp_path / "message.json"
    message.write_text(
        json.dumps({"subject": "x", "text": "x", "html": "<script>x</script>"}),
        encoding="utf-8",
    )
    result = run_script(
        ROOT / "skills/gmail-sender/scripts/prepare_message.py", str(message)
    )
    assert result.returncode != 0
    assert "email_render_invalid" in result.stdout


def test_report_html_is_stable_for_nested_mapping_order() -> None:
    path = ROOT / "skills/training-report-publisher/scripts/render_report.py"
    spec = importlib.util.spec_from_file_location("trainlab_render_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.body_html({"metrics": {"b": 2, "a": [{"d": 4, "c": 3}]}})
    second = module.body_html({"metrics": {"a": [{"c": 3, "d": 4}], "b": 2}})
    assert first == second


def test_render_report_persists_report_and_email_outputs(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    payload = tmp_path / "report.json"
    payload.write_text(
        json.dumps(
            {
                "title": "Test",
                "period": "2026-08-10/2026-08-16",
                "content": {"课程": "课程占位"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    connection = connect(database)
    try:
        source_run = begin_run(
            connection,
            run_key="render-source",
            workflow_key="weekly:2026-08-09",
            dedupe_key="render-source",
            skill_name="training-coach",
            operation="weekly_coach",
            trigger_kind="skill",
            input_manifest={"test": "render-source"},
        )
        source_payload = {
            "title": "Test",
            "period": "2026-08-10/2026-08-16",
            "content": {"课程": "课程占位"},
        }
        append_output(
            connection,
            skill_run_id=source_run,
            output_kind="weekly_summary",
            logical_key="render-source-output",
            schema_name="weekly_ai_result_v1",
            schema_version="1",
            content_json=source_payload,
            content_text="source",
        )
        finish_run(connection, source_run, status="succeeded")
    finally:
        connection.close()
    output_dir = tmp_path / "render"
    result = run_script(
        ROOT / "skills/training-report-publisher/scripts/render_report.py",
        "--input-json",
        str(payload),
        "--kind",
        "weekly",
        "--output-dir",
        str(output_dir),
        "--database",
        str(database),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    connection = sqlite3.connect(database)
    kinds = {
        row[0]
        for row in connection.execute(
            "SELECT output_kind FROM skill_outputs ORDER BY id"
        )
    }
    assert {"report_artifact", "email_render"}.issubset(kinds)
    connection.close()
    fixed_dir = tmp_path / "fixed-render"
    fixed = run_script(
        ROOT / "skills/training-report-publisher/scripts/render_report.py",
        "--input-json",
        str(payload),
        "--kind",
        "weekly",
        "--mode",
        "fixed_email",
        "--output-dir",
        str(fixed_dir),
        "--database",
        str(database),
    )
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    html = (fixed_dir / "report.html").read_text(encoding="utf-8")
    assert "3 / 5" not in html
    assert "2026-07-27 20:00" not in html
    assert "{{" not in html
    assert "Easy" not in html
    assert "Long" not in html
    assert "RPE 4" not in html
    assert "质量课程" not in html

    replay_dir = tmp_path / "replay-render"
    replay = run_script(
        ROOT / "skills/training-report-publisher/scripts/render_report.py",
        "--input-json",
        str(payload),
        "--kind",
        "weekly",
        "--output-dir",
        str(replay_dir),
        "--database",
        str(database),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    first_ids = json.loads(result.stdout)["output_ids"]
    replay_ids = json.loads(replay.stdout)["output_ids"]
    assert replay_ids == first_ids
    assert replay_ids["source_output_id"] > 0
    assert len(replay_ids["source_output_sha256"]) == 64
    assert "休息与轻度恢复" not in html
    verified = run_script(
        ROOT / "skills/_shared/scripts/verify_state.py", "--database", str(database)
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_restore_state_verifies_backup_pair(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    prefix = hashlib.sha256(database.read_bytes()).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = tmp_path / f"backups/trainlab-{stamp}-test-restore-{prefix}.db"
    result = run_script(
        ROOT / "skills/_shared/scripts/backup_state.py",
        str(destination),
        "--database",
        str(database),
        "--backup-type",
        "manual",
        "--operation-id",
        "test-restore",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    destination = Path(result.stdout.splitlines()[0])
    verified = run_script(
        ROOT / "skills/_shared/scripts/restore_state.py",
        "--backup",
        str(destination),
        "--raw-root",
        str(tmp_path / "raw"),
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert json.loads(verified.stdout)["restore_applied"] is False


def test_append_only_outputs_and_raw_bindings(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    connection = connect(database)
    manifest: dict[str, object] = {}
    manifest_sha = hashlib.sha256(b"{}").hexdigest()
    cursor = connection.execute(
        """INSERT INTO skill_runs
        (run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,attempt_no,
         input_manifest_json,input_sha256,status,created_at_utc)
        VALUES ('append-run','w','append-d','training-coach','daily_coach','manual',1,
                ?,?,'running','2026-01-01T00:00:00Z')""",
        (json.dumps(manifest), manifest_sha),
    )
    run_id = require_lastrowid(cursor)
    content = {"ok": True}
    output_payload: dict[str, object] = {
        "title": "T",
        "json": content,
        "text": "ok",
        "html": None,
        "lineage": [],
    }
    output_sha = hashlib.sha256(
        json.dumps(
            output_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    connection.execute(
        """INSERT INTO skill_outputs
        (skill_run_id,output_kind,logical_key,revision_no,schema_name,schema_version,
         title_text,content_json,content_text,lineage_json,content_sha256,created_at_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            "daily_summary",
            "append-output",
            1,
            "daily",
            "1",
            "T",
            json.dumps(content, separators=(",", ":")),
            "ok",
            "[]",
            output_sha,
            "2026-01-01T00:00:00Z",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM skill_outputs WHERE logical_key='append-output'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE skill_outputs SET content_text='changed' WHERE logical_key='append-output'"
        )
    connection.close()


def test_approval_scope_and_authority_are_exact(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    connection = connect(database)
    manifest_sha = hashlib.sha256(b"{}").hexdigest()
    run_cursor = connection.execute(
        """INSERT INTO skill_runs
        (run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,attempt_no,
         input_manifest_json,input_sha256,status,created_at_utc)
        VALUES ('scope-run','w','scope-d','training-coach','weekly_coach','manual',1,
                '{}',?,'running','2026-01-01T00:00:00Z')""",
        (manifest_sha,),
    )
    run_id = require_lastrowid(run_cursor)
    content = {"plan": "easy"}
    output_payload: dict[str, object] = {
        "title": "Plan",
        "json": content,
        "text": "Plan",
        "html": None,
        "lineage": [],
    }
    output_sha = hashlib.sha256(
        json.dumps(
            output_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    output_cursor = connection.execute(
        """INSERT INTO skill_outputs
        (skill_run_id,output_kind,logical_key,revision_no,schema_name,schema_version,
         title_text,content_json,content_text,lineage_json,content_sha256,created_at_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            "garmin_workout_contract",
            "scope-output",
            1,
            "plan",
            "1",
            "Plan",
            json.dumps(content, separators=(",", ":")),
            "Plan",
            "[]",
            output_sha,
            "2026-01-01T00:00:00Z",
        ),
    )
    output_id = require_lastrowid(output_cursor)
    scope = {
        "provider": "garmin",
        "action_kind": "garmin_workout_create",
        "entity_kind": "workout",
        "target_key": "2026-08-17",
        "scope_kind": "garmin",
        "budget": {"max_actions": 1},
    }
    scope_json = json.dumps(
        scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    scope_sha = hashlib.sha256(scope_json.encode()).hexdigest()
    connection.execute(
        """INSERT INTO approvals
        (approval_key, candidate_output_id,candidate_output_sha256,authority_kind,decision,
         scope_kind,scope_json,scope_sha256,source_ref,reason_code,decided_at_utc,valid_from_utc,
         valid_until_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "scope-approval",
            output_id,
            output_sha,
            "user_explicit",
            "approved",
            "garmin",
            scope_json,
            scope_sha,
            "test",
            "test",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "2099-01-01T00:00:00Z",
        ),
    )
    approval_id = int(connection.execute("SELECT id FROM approvals").fetchone()[0])
    request = {"workout": "Plan"}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
    request_sha = hashlib.sha256(request_json.encode()).hexdigest()
    connection.execute(
        """INSERT INTO external_actions
        (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
         source_output_sha256,approval_id,target_key,request_json,request_sha256,status,attempt_count,
         prepared_at_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "scope-action",
            run_id,
            "garmin",
            "workout",
            "garmin_workout_create",
            output_id,
            output_sha,
            approval_id,
            "2026-08-17",
            request_json,
            request_sha,
            "prepared",
            0,
            "2026-08-15T00:00:00Z",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE external_actions SET provider='gmail' WHERE idempotency_key='scope-action'"
        )
    connection.close()


def test_external_action_state_machine_and_lineage_guards(tmp_path: Path) -> None:
    database = tmp_path / "trainlab.db"
    run_script(
        ROOT / "skills/_shared/scripts/init_state.py", "--database", str(database)
    )
    connection = connect(database)
    run_id = begin_run(
        connection,
        run_key="state-machine-run",
        workflow_key="test",
        dedupe_key="state-machine-dedupe",
        skill_name="garmin-training-sender",
        operation="apply_weekly_plan",
        trigger_kind="manual",
        input_manifest={},
    )
    output_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="garmin_workout_contract",
        logical_key="state-machine-output",
        schema_name="test",
        schema_version="1",
        content_json={"workout": "Easy-GTS"},
        content_text="Easy-GTS",
        lineage=[],
    )
    output_sha = str(
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
        ).fetchone()[0]
    )

    def insert_approval(
        key: str, scope: Mapping[str, object], decision: str = "approved"
    ) -> int:
        scope_json = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        cursor = connection.execute(
            """INSERT INTO approvals
            (approval_key,candidate_output_id,candidate_output_sha256,authority_kind,decision,
             scope_kind,scope_json,scope_sha256,source_ref,reason_code,decided_at_utc,
             valid_from_utc,valid_until_utc,supersedes_approval_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                key,
                output_id,
                output_sha,
                "user_explicit",
                decision,
                str(scope["scope_kind"]),
                scope_json,
                hashlib.sha256(scope_json.encode()).hexdigest(),
                "test",
                "test",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2099-01-01T00:00:00Z",
            ),
        )
        return require_lastrowid(cursor)

    valid_scope = {
        "provider": "garmin",
        "action_kind": "garmin_workout_create",
        "entity_kind": "workout",
        "target_key": "2026-08-17",
        "scope_kind": "garmin",
        "budget": {"max_actions": 1},
    }
    approval_id = insert_approval("state-machine-approval", valid_scope)
    request_json = json.dumps(
        {"workout": "Easy-GTS"}, sort_keys=True, separators=(",", ":")
    )
    action_cursor = connection.execute(
        """INSERT INTO external_actions
        (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
         source_output_sha256,approval_id,target_key,request_json,request_sha256,status,
            attempt_count,prepared_at_utc,provider_object_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "state-machine-action",
            run_id,
            "garmin",
            "workout",
            "garmin_workout_create",
            output_id,
            output_sha,
            approval_id,
            "2026-08-17",
            request_json,
            hashlib.sha256(request_json.encode()).hexdigest(),
            "prepared",
            0,
            "2026-08-15T00:00:00Z",
            "Easy-GTS",
        ),
    )
    action_id = require_lastrowid(action_cursor)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM external_actions WHERE id=?", (action_id,))
    connection.execute(
        "UPDATE external_actions SET status='in_progress', started_at_utc=? WHERE id=?",
        ("2026-08-15T00:01:00Z", action_id),
    )
    connection.execute(
        """UPDATE external_actions
           SET status='succeeded', finished_at_utc=?, result_external_id=?, provider_marker=?
           WHERE id=?""",
        ("2026-08-15T00:02:00Z", "garmin-123", "validated", action_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE external_actions SET idempotency_key='changed-key' WHERE id=?",
            (action_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE external_actions SET provider_object_name='Changed-GTS' WHERE id=?",
            (action_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE external_actions SET status='prepared' WHERE id=?", (action_id,)
        )

    delete_scope = {
        "provider": "garmin",
        "action_kind": "garmin_workout_delete",
        "entity_kind": "workout",
        "target_key": "2026-08-17",
        "scope_kind": "garmin",
        "budget": {"max_actions": 1},
    }
    delete_approval = insert_approval("delete-approval", delete_scope)
    unschedule_scope = {
        "provider": "garmin",
        "action_kind": "garmin_calendar_unschedule",
        "entity_kind": "calendar_entry",
        "target_key": "2026-08-17",
        "scope_kind": "garmin",
        "budget": {"max_actions": 1},
    }
    unschedule_approval = insert_approval("unschedule-approval", unschedule_scope)
    unschedule_request = json.dumps(
        {"calendar_entry": "calendar-123"}, sort_keys=True, separators=(",", ":")
    )
    unschedule_cursor = connection.execute(
        """INSERT INTO external_actions
        (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
         source_output_sha256,approval_id,related_action_id,target_key,target_external_id,
         request_json,request_sha256,status,attempt_count,prepared_at_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "unschedule-action",
            run_id,
            "garmin",
            "calendar_entry",
            "garmin_calendar_unschedule",
            output_id,
            output_sha,
            unschedule_approval,
            action_id,
            "2026-08-17",
            "calendar-123",
            unschedule_request,
            hashlib.sha256(unschedule_request.encode()).hexdigest(),
            "prepared",
            0,
            "2026-08-15T00:02:30Z",
        ),
    )
    unschedule_id = require_lastrowid(unschedule_cursor)
    connection.execute(
        "UPDATE external_actions SET status='in_progress', started_at_utc=? WHERE id=?",
        ("2026-08-15T00:02:40Z", unschedule_id),
    )
    connection.execute(
        "UPDATE external_actions SET status='succeeded', finished_at_utc=? WHERE id=?",
        ("2026-08-15T00:02:50Z", unschedule_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO external_actions
            (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
             source_output_sha256,approval_id,target_key,target_external_id,provider_object_name,
             request_json,request_sha256,status,attempt_count,prepared_at_utc)
            VALUES ('unowned-delete',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                "garmin",
                "workout",
                "garmin_workout_delete",
                output_id,
                output_sha,
                delete_approval,
                "2026-08-17",
                "missing-id",
                "NotOwned-GTS",
                request_json,
                hashlib.sha256(request_json.encode()).hexdigest(),
                "prepared",
                0,
                "2026-08-15T00:03:00Z",
            ),
        )
    connection.execute(
        """INSERT INTO external_actions
        (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
         source_output_sha256,approval_id,target_key,target_external_id,provider_object_name,
         request_json,request_sha256,status,attempt_count,prepared_at_utc)
        VALUES ('owned-delete',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            "garmin",
            "workout",
            "garmin_workout_delete",
            output_id,
            output_sha,
            delete_approval,
            "2026-08-17",
            "garmin-123",
            "Easy-GTS",
            request_json,
            hashlib.sha256(request_json.encode()).hexdigest(),
            "prepared",
            0,
            "2026-08-15T00:03:00Z",
        ),
    )

    invalid_scope = {
        "provider": "gmail",
        "action_kind": "garmin_workout_delete",
        "entity_kind": "site_snapshot",
        "target_key": "wrong-provider",
        "scope_kind": "gmail",
        "budget": {"max_actions": 1},
    }
    invalid_approval = insert_approval("invalid-semantics-approval", invalid_scope)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO external_actions
            (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
             source_output_sha256,approval_id,target_key,request_json,request_sha256,status,
             attempt_count,prepared_at_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "invalid-semantics-action",
                run_id,
                "gmail",
                "site_snapshot",
                "garmin_workout_delete",
                output_id,
                output_sha,
                invalid_approval,
                "wrong-provider",
                request_json,
                hashlib.sha256(request_json.encode()).hexdigest(),
                "prepared",
                0,
                "2026-08-15T00:00:00Z",
            ),
        )

    empty_budget = dict(valid_scope)
    empty_budget["budget"] = {}
    with pytest.raises(sqlite3.IntegrityError):
        insert_approval("empty-budget-approval", empty_budget)
    with pytest.raises(sqlite3.IntegrityError):
        insert_approval("unlinked-revocation", valid_scope, decision="revoked")
    with pytest.raises(sqlite3.IntegrityError):
        append_output(
            connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="empty-lineage-object",
            schema_name="test",
            schema_version="1",
            content_json={"ok": True},
            content_text="ok",
            lineage=[{}],
        )
    connection.close()
