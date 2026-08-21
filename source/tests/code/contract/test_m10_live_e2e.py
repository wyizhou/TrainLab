from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))

from skills._shared.scripts.schema_validation import validate_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    init_database,
)


def load_script(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def m10_preview_payload(
    actions: Any,
    *,
    emails: list[dict[str, Any]] | None = None,
    schedule: list[dict[str, Any]] | None = None,
    report_sources: list[dict[str, Any]] | None = None,
    training_plan_output_id: int = 3001,
    training_plan_output_sha256: str = "f" * 64,
) -> dict[str, Any]:
    recipient = "runner@example.com"
    email_rows = list(emails or [])
    while len(email_rows) < 8:
        index = len(email_rows) + 1
        request = {
            "to": [recipient],
            "subject": f"M10 synthetic {index}",
            "body": f"synthetic {index}",
            "htmlBody": f"<p>synthetic {index}</p>",
            "mimeType": "multipart/alternative",
        }
        email_rows.append(
            {
                "marker": f"synthetic-marker-{index}",
                "subject": request["subject"],
                "verification_query": f'subject:"{request["subject"]}"',
                "request_sha256": actions.sha256_text(actions.canonical_json(request)),
                "recipient": recipient,
                "recipient_sha256": actions.sha256_text(recipient),
            }
        )
    for index, row in enumerate(email_rows, 1):
        row.setdefault("recipient", recipient)
        row.setdefault("recipient_sha256", actions.sha256_text(recipient))
        row.setdefault("source_output_id", 1000 + index)
        row.setdefault("source_output_sha256", f"{index:064x}")
    if schedule is None:
        course = {
            "date": "2026-08-19",
            "name": "Synthetic-1K-E2E-20260818-GTS",
            "workout_data": {"workoutName": "Synthetic-1K-E2E-20260818-GTS"},
        }
        course["action_request_sha256"] = {
            phase: actions.sha256_text(actions.canonical_json(request))
            for phase, request in actions.garmin_action_requests(course).items()
        }
        schedule = [course]
    if report_sources is None:
        report_sources = [
            {
                "mode": "daily" if index < 7 else "weekly",
                "target": (f"2026-08-{12 + index:02d}" if index < 7 else "2026-08-18"),
                "source_output_id": 2001 + index,
                "source_output_sha256": f"{101 + index:064x}",
                "email_output_id": int(email_rows[index]["source_output_id"]),
                "email_output_sha256": str(email_rows[index]["source_output_sha256"]),
            }
            for index in range(8)
        ]
    payload = {
        "schema_version": "m10_external_preview_v1",
        "status": "awaiting_user_confirmation",
        "email_retention": "keep",
        "emails": email_rows,
        "report_sources": report_sources,
        "schedule": schedule,
        "training_plan_output_id": training_plan_output_id,
        "training_plan_output_sha256": training_plan_output_sha256,
        "gmail_send_budget": 8,
        "gmail_tool_call_budget": 26,
        "garmin_workout_budget": 4,
        "garmin_tool_call_budget": 20,
        "sites_calls": 0,
        "cron_calls": 0,
    }
    payload["preview_sha256"] = actions.sha256_text(actions.canonical_json(payload))
    return payload


def seed_valid_m10_preview(
    actions: Any,
    database: Path,
    *,
    prefix: str,
    plan_items: list[dict[str, Any]] | None = None,
    email_requests: list[dict[str, Any]] | None = None,
    invalid_daily_schema: bool = False,
    invalid_weekly_lineage: bool = False,
    invalid_training_plan: bool = False,
    failed_daily_run: bool = False,
) -> dict[str, Any]:
    recipient = "runner@example.com"
    requests = list(email_requests or [])
    while len(requests) < 8:
        index = len(requests) + 1
        requests.append(
            {
                "to": [recipient],
                "subject": f"M10 seeded {prefix} {index}",
                "body": f"seeded {index}",
                "htmlBody": f"<p>seeded {index}</p>",
                "mimeType": "multipart/alternative",
            }
        )
    items = list(plan_items or [])
    if not items:
        for index in range(7):
            running = index == 0
            item: dict[str, Any] = {
                "date": f"2026-08-{19 + index:02d}",
                "activity_kind": "running" if running else "rest",
                "name": "Synthetic 1K" if running else "休息",
                "purpose": "合成测试" if running else "恢复",
                "load_level": "low",
                "garmin_mapping_status": (
                    "candidate" if running else "unsupported_skip"
                ),
                "rpe": 2,
                "downgrade_rule": "疲劳则减量",
                "stop_conditions": ["疼痛时停止"],
            }
            if running:
                item["distance_km"] = 1.0
                item["steps"] = [{"name": "主课", "end_condition": "完成 1 km"}]
            items.append(item)
    training_plan = {
        "schema_version": "training_plan_v1",
        "status": "succeeded",
        "items": items,
        "progression_rule": "hold",
        "progression_dimension": "none",
        "provider_calls": 0,
    }
    schedule = actions.normalize_plan(training_plan)
    for row in schedule:
        row["action_request_sha256"] = {
            phase: actions.sha256_text(actions.canonical_json(request))
            for phase, request in actions.garmin_action_requests(row).items()
        }
    connection = connect(database)
    try:
        sources: list[tuple[int, str, str, str]] = []
        daily_lineage: list[dict[str, Any]] = []
        for index in range(7):
            target = f"2026-08-{12 + index:02d}"
            run_id = begin_run(
                connection,
                run_key=f"{prefix}:daily:{target}",
                workflow_key=f"daily:{target}",
                dedupe_key=f"{prefix}:daily:{target}",
                skill_name="training-coach",
                operation="daily_coach",
                trigger_kind="skill",
                input_manifest={"m10": True, "target": target},
            )
            daily_payload: dict[str, Any] = {
                "schema_version": "daily_ai_result_v1",
                "status": "succeeded",
                "report_date": target,
                "review_date": f"2026-08-{11 + index:02d}",
                "sleep_wake_date": target,
                "safety": "ready",
                "summary": f"daily {target}",
                "bounded_metrics": [],
                "stop_conditions": ["疼痛时停止"],
                "evidence_refs": [
                    {
                        "raw_file_id": index + 1,
                        "sha256": f"{index + 1:064x}",
                        "claim": "synthetic fixture",
                    }
                ],
                "provider_calls": 0,
            }
            if invalid_daily_schema and index == 0:
                daily_payload = {
                    "schema_version": "daily_ai_result_v1",
                    "report_date": target,
                }
            output_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="daily_summary",
                logical_key=f"{prefix}:daily-output:{target}",
                schema_name="daily_ai_result_v1",
                schema_version="1",
                title_text=f"M10 daily {target}",
                content_json=daily_payload,
                content_text=f"daily {target}",
                period_start_date=target,
                period_end_date=target,
            )
            output_sha = str(
                connection.execute(
                    "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
                ).fetchone()[0]
            )
            daily_lineage.append({"output_id": output_id, "output_sha256": output_sha})
            sources.append((output_id, output_sha, "daily", target))
            finish_run(
                connection,
                run_id,
                status="failed" if failed_daily_run and index == 0 else "succeeded",
            )
        weekly_run = begin_run(
            connection,
            run_key=f"{prefix}:weekly:2026-08-18",
            workflow_key="weekly:2026-08-18",
            dedupe_key=f"{prefix}:weekly:2026-08-18",
            skill_name="training-coach",
            operation="weekly_coach",
            trigger_kind="skill",
            input_manifest={"m10": True, "target": "2026-08-18"},
        )
        weekly_output_id = append_output(
            connection,
            skill_run_id=weekly_run,
            output_kind="weekly_summary",
            logical_key=f"{prefix}:weekly-output",
            schema_name="weekly_ai_result_v1",
            schema_version="1",
            title_text="M10 weekly",
            content_json={
                "schema_version": "weekly_ai_result_v1",
                "status": "succeeded",
                "period": "2026-08-12/2026-08-18",
                "daily_input_sha256": [item["output_sha256"] for item in daily_lineage],
                "summary": "weekly",
                "evidence_refs": [
                    {
                        "output_id": item["output_id"],
                        "sha256": item["output_sha256"],
                        "claim": "synthetic daily fixture",
                    }
                    for item in daily_lineage
                ],
                "goal_sha256": "a" * 64,
                "training_plan": training_plan,
                "provider_calls": 0,
            },
            content_text="weekly",
            lineage=[] if invalid_weekly_lineage else daily_lineage,
            period_start_date="2026-08-12",
            period_end_date="2026-08-18",
        )
        weekly_output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (weekly_output_id,),
            ).fetchone()[0]
        )
        sources.append((weekly_output_id, weekly_output_sha, "weekly", "2026-08-18"))
        plan_output_id = append_output(
            connection,
            skill_run_id=weekly_run,
            output_kind="training_plan",
            logical_key=f"{prefix}:training-plan",
            schema_name="training_plan_v1",
            schema_version="1",
            title_text="M10 plan",
            content_json=(
                {"schema_version": "training_plan_v1", "items": []}
                if invalid_training_plan
                else training_plan
            ),
            content_text="plan",
            lineage=daily_lineage,
            period_start_date="2026-08-12",
            period_end_date="2026-08-18",
        )
        plan_output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (plan_output_id,),
            ).fetchone()[0]
        )
        finish_run(connection, weekly_run, status="succeeded")
        emails: list[dict[str, Any]] = []
        report_sources: list[dict[str, Any]] = []
        for index, (source_id, source_sha, mode, target) in enumerate(sources):
            render_run = begin_run(
                connection,
                run_key=f"{prefix}:render:{index}",
                workflow_key=f"{mode}:{target}",
                dedupe_key=f"{prefix}:render:{index}",
                skill_name="training-report-publisher",
                operation="render_daily" if mode == "daily" else "render_weekly",
                trigger_kind="skill",
                input_manifest={"m10": True, "source_output_id": source_id},
            )
            request = requests[index]
            email_id = append_output(
                connection,
                skill_run_id=render_run,
                output_kind="email_render",
                logical_key=f"{prefix}:email:{index}",
                schema_name=f"{mode}_email_render",
                schema_version="1",
                title_text=str(request["subject"]),
                content_json={"source_output_id": source_id},
                content_text=str(request["body"]),
                content_html=str(request["htmlBody"]),
                lineage=[
                    {
                        "output_id": source_id,
                        "output_sha256": source_sha,
                        "source_output_id": source_id,
                        "source_output_sha256": source_sha,
                    }
                ],
                period_start_date=target if mode == "daily" else "2026-08-12",
                period_end_date=target,
            )
            email_sha = str(
                connection.execute(
                    "SELECT content_sha256 FROM skill_outputs WHERE id=?", (email_id,)
                ).fetchone()[0]
            )
            finish_run(connection, render_run, status="succeeded")
            marker = f"{prefix}-marker-{index + 1}"
            emails.append(
                {
                    "marker": marker,
                    "subject": request["subject"],
                    "verification_query": f'subject:"{request["subject"]}"',
                    "request_sha256": actions.sha256_text(
                        actions.canonical_json(request)
                    ),
                    "recipient": str(request["to"][0]),
                    "recipient_sha256": actions.sha256_text(str(request["to"][0])),
                    "source_output_id": email_id,
                    "source_output_sha256": email_sha,
                }
            )
            report_sources.append(
                {
                    "mode": mode,
                    "target": target,
                    "source_output_id": source_id,
                    "source_output_sha256": source_sha,
                    "email_output_id": email_id,
                    "email_output_sha256": email_sha,
                }
            )
        preview = m10_preview_payload(
            actions,
            emails=emails,
            schedule=schedule,
            report_sources=report_sources,
            training_plan_output_id=plan_output_id,
            training_plan_output_sha256=plan_output_sha,
        )
        preview_run = begin_run(
            connection,
            run_key=f"{prefix}:preview",
            workflow_key="m10:external-preview:2026-08-18",
            dedupe_key=f"{prefix}:preview",
            skill_name="training-report-publisher",
            operation="render_weekly",
            trigger_kind="manual",
            input_manifest={"m10": True, "preview": True},
        )
        preview_output_id = append_output(
            connection,
            skill_run_id=preview_run,
            output_kind="execution_summary",
            logical_key=f"{prefix}:preview-output",
            schema_name="m10_external_preview_v1",
            schema_version="1",
            title_text="M10 preview",
            content_json=preview,
            content_text="M10 preview",
            lineage=[
                {"output_id": plan_output_id, "output_sha256": plan_output_sha},
                *[
                    {
                        "output_id": int(item["source_output_id"]),
                        "output_sha256": str(item["source_output_sha256"]),
                    }
                    for item in emails
                ],
            ],
            period_start_date="2026-08-12",
            period_end_date="2026-08-25",
        )
        preview_output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (preview_output_id,),
            ).fetchone()[0]
        )
        finish_run(connection, preview_run, status="succeeded")
        return {
            "run_id": preview_run,
            "output_id": preview_output_id,
            "output_sha256": preview_output_sha,
            "preview": preview,
            "requests": requests,
        }
    finally:
        connection.close()


def test_m10_rolling_request_is_exact_and_bounded() -> None:
    rolling = load_script(
        "trainlab_test_m10_rolling_request",
        "skills/garmin-sync/scripts/rolling_week_sync.py",
    )
    request = rolling.approved_request()
    assert not validate_payload(request, "garmin_rolling_week_request_v1")
    assert len(request["base_calls"]) == 32
    assert (
        sum(call["tool"] == "get_activities_by_date" for call in request["base_calls"])
        == 7
    )
    assert request["budgets"] == {
        "mcp_tool_calls": 46,
        "provider_entries": 47,
        "inventory_ids_per_day": 10,
        "new_activities": 7,
        "fit_files": 7,
        "weather_calls": 7,
        "new_files": 46,
        "wall_seconds": 600,
    }
    changed = json.loads(json.dumps(request))
    changed["review_end_date"] = "2026-08-18"
    with pytest.raises(
        rolling.RollingSyncError, match="garmin_rolling_request_invalid"
    ):
        rolling.validate_request(changed)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"has_more": True}, "activity_inventory_incomplete"),
        ({"page": 1}, "activity_inventory_incomplete"),
        ({"page_size": 100}, "activity_inventory_incomplete"),
        (
            {"date_range": {"start": "2026-08-10", "end": "2026-08-11"}},
            "activity_inventory_incomplete",
        ),
    ],
)
def test_m10_inventory_fails_closed(change: dict[str, Any], code: str) -> None:
    rolling = load_script(
        f"trainlab_test_m10_inventory_{next(iter(change))}",
        "skills/garmin-sync/scripts/rolling_week_sync.py",
    )
    payload = {
        "activities": [],
        "count": 0,
        "page": 0,
        "page_size": 10,
        "has_more": False,
        "date_range": {"start": "2026-08-11", "end": "2026-08-11"},
    }
    payload.update(change)
    with pytest.raises(rolling.RollingSyncError, match=code):
        rolling.validate_inventory(payload, "2026-08-11")


def test_m10_inventory_rejects_duplicate_activity() -> None:
    rolling = load_script(
        "trainlab_test_m10_inventory_duplicate",
        "skills/garmin-sync/scripts/rolling_week_sync.py",
    )
    item = {"id": 10, "start_time": "2026-08-11T07:00:00"}
    payload = {
        "activities": [item, item],
        "count": 2,
        "page": 0,
        "page_size": 10,
        "has_more": False,
        "date_range": {"start": "2026-08-11", "end": "2026-08-11"},
    }
    with pytest.raises(rolling.RollingSyncError, match="activity_inventory_duplicate"):
        rolling.validate_inventory(payload, "2026-08-11")


class ZeroActivityClient:
    def __init__(self, rolling: Any) -> None:
        self.rolling = rolling
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "ZeroActivityClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_tools(self) -> set[str]:
        return set(self.rolling.ALLOWED_TOOLS)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "get_activities_by_date":
            day = arguments["start_date"]
            payload: Any = {
                "activities": [],
                "count": 0,
                "page": 0,
                "page_size": 10,
                "has_more": False,
                "date_range": {"start": day, "end": day},
            }
        else:
            payload = {"status": "synthetic"}
        return SimpleNamespace(
            payload=json.dumps(payload, sort_keys=True).encode(), is_error=False
        )


def test_m10_zero_activity_collection_is_reused_without_provider(
    tmp_path: Path,
) -> None:
    rolling = load_script(
        "trainlab_test_m10_zero_activity",
        "skills/garmin-sync/scripts/rolling_week_sync.py",
    )
    source = tmp_path / "source"
    for directory in (
        source,
        source / "state",
        source / "state/raw",
        source / "state/raw/garmin",
        source / "state/raw/garmin/health",
        source / "state/raw/garmin/activities",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    database = init_database(source / "state/trainlab.db")
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    token = tokens / "oauth.json"
    token.write_text("{}", encoding="utf-8")
    token.chmod(0o600)
    client = ZeroActivityClient(rolling)

    def guard(root: Path, db: Path) -> tuple[Path, Path]:
        return root.resolve(), db.resolve()

    result = asyncio.run(
        rolling.collect(
            rolling.approved_request(),
            source,
            database,
            tokens,
            lambda _shadow, _staging: client,
            candidate_guard=guard,
        )
    )
    assert result["status"] == "succeeded"
    assert result["provider_entries"] == 33
    assert result["mcp_tool_calls"] == 32
    assert result["inventory_by_date"] == {
        f"2026-08-{day:02d}": 0 for day in range(11, 18)
    }
    assert len(result["daily_windows"]) == 7
    assert not validate_payload(
        {key: value for key, value in result.items() if key != "receipt_output_id"},
        "garmin_rolling_week_receipt_v1",
    )
    assert len(client.calls) == 32

    reused_client = ZeroActivityClient(rolling)
    reused = asyncio.run(
        rolling.collect(
            rolling.approved_request(),
            source,
            database,
            tokens,
            lambda _shadow, _staging: reused_client,
            candidate_guard=guard,
        )
    )
    assert reused["status"] == "succeeded"
    assert reused["provider_entries"] == 0
    assert reused["mcp_tool_calls"] == 0
    assert reused_client.calls == []
    connection = connect(database, read_only=True, immutable=True)
    try:
        assert (
            connection.execute("SELECT COUNT(*) FROM external_actions").fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_m10_unsealed_candidate_is_rejected_before_provider(tmp_path: Path) -> None:
    rolling = load_script(
        "trainlab_test_m10_unsealed_candidate",
        "skills/garmin-sync/scripts/rolling_week_sync.py",
    )
    source = tmp_path / "source"
    for directory in (source, source / "state"):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    database = init_database(source / "state/trainlab.db")
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    called = False

    def client_factory(*_args: object) -> Any:
        nonlocal called
        called = True
        raise AssertionError("provider must not be reached")

    with pytest.raises(rolling.RollingSyncError, match="candidate_scope_required"):
        asyncio.run(
            rolling.collect(
                rolling.approved_request(),
                source,
                database,
                tokens,
                client_factory,
            )
        )
    assert called is False


def test_m10_model_command_isolated_and_no_retry(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("return json", encoding="utf-8")
    prompt.chmod(0o600)
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    schema.chmod(0o600)
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/bin/sh\n"
        "last=''\n"
        'while [ "$#" -gt 0 ]; do\n'
        "  if [ \"$1\" = '--output-last-message' ]; then shift; last=$1; fi\n"
        "  shift\n"
        "done\n"
        "cat >/dev/null\n"
        'printf \'{"status":"ok"}\\n\'\n'
        'printf \'{"provider_calls":0}\' >"$last"\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)
    result_path = tmp_path / "result.json"
    runner._invoke_codex(
        executable=executable,
        source_root=source,
        prompt_path=prompt,
        schema_path=schema,
        result_path=result_path,
        events_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.log",
    )
    assert json.loads(result_path.read_text(encoding="utf-8")) == {"provider_calls": 0}
    assert result_path.stat().st_mode & 0o777 == 0o600


def test_m10_runner_rejects_unsealed_database_before_writing(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_candidate_guard",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    source = tmp_path / "source"
    state = source / "state"
    state.mkdir(parents=True)
    source.chmod(0o700)
    state.chmod(0o700)
    database = init_database(state / "trainlab.db")
    run_root = tmp_path / "run"
    with pytest.raises(runner.RollingCoachError, match="m10_candidate_scope_required"):
        runner.run(
            source_root=source,
            database=database,
            run_root=run_root,
            executable=tmp_path / "codex",
            rolling_sync_output_id=1,
        )
    assert not run_root.exists()


def test_m10_ai_budget_is_persistent_across_run_roots(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_budget",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    prompt.write_text("same prompt", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")
    prompt.chmod(0o600)
    schema.chmod(0o600)
    for offset in range(8):
        run_id = runner._claim_ai_call(
            database,
            mode="daily" if offset < 7 else "weekly",
            target=date(2026, 8, 12 + offset),
            rolling_sync_output_id=55,
            prompt_path=prompt,
            schema_path=schema,
        )
        runner._finish_ai_call(database, run_id, status="succeeded")
    with pytest.raises(runner.RollingCoachError, match="m10_ai_budget_exceeded"):
        runner._claim_ai_call(
            database,
            mode="daily",
            target=date(2026, 8, 20),
            rolling_sync_output_id=55,
            prompt_path=prompt,
            schema_path=schema,
        )
    with pytest.raises(
        runner.RollingCoachError, match="m10_ai_attempt_already_recorded"
    ):
        runner._claim_ai_call(
            database,
            mode="daily",
            target=date(2026, 8, 12),
            rolling_sync_output_id=55,
            prompt_path=prompt,
            schema_path=schema,
        )


def test_m10_resume_requires_exact_eight_succeeded_ai_calls(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_resume_history",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    prompt.write_text("frozen prompt", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")
    prompt.chmod(0o600)
    schema.chmod(0o600)
    for index in range(7):
        run_id = runner._claim_ai_call(
            database,
            mode="daily",
            target=date(2026, 8, 12 + index),
            rolling_sync_output_id=55,
            prompt_path=prompt,
            schema_path=schema,
        )
        runner._finish_ai_call(database, run_id, status="succeeded")
    with pytest.raises(runner.RollingCoachError, match="m10_resume_ai_history_invalid"):
        runner._assert_resume_ready(database, 55)

    run_id = runner._claim_ai_call(
        database,
        mode="weekly",
        target=date(2026, 8, 18),
        rolling_sync_output_id=55,
        prompt_path=prompt,
        schema_path=schema,
    )
    runner._finish_ai_call(database, run_id, status="succeeded")
    daily_ids = iter(range(101, 108))

    def matching_outputs(
        _database: Path,
        mode: str,
        _target: date,
        **_kwargs: object,
    ) -> list[tuple[int, dict[str, Any], int]]:
        output_id = next(daily_ids) if mode == "daily" else 108
        return [(output_id, {"status": "succeeded"}, output_id + 1000)]

    runner._matching_outputs = matching_outputs
    runner._assert_resume_ready(database, 55)

    runner._matching_outputs = lambda *_args, **_kwargs: [
        (101, {"status": "succeeded"}, 1101),
        (201, {"status": "succeeded"}, 1201),
    ]
    with pytest.raises(
        runner.RollingCoachError, match="m10_resume_output_cardinality_invalid"
    ):
        runner._assert_resume_ready(database, 55)

    connection = connect(database)
    try:
        extra_run = begin_run(
            connection,
            run_key="m10-extra-ai-other-receipt",
            workflow_key="m10:daily:2026-08-12",
            dedupe_key="m10-extra-ai-other-receipt",
            skill_name="training-coach",
            operation="daily_coach",
            trigger_kind="manual",
            input_manifest={
                "m10_role": runner.AI_CALL_ROLE,
                "target": "daily:2026-08-12",
                "rolling_sync_output_id": 99,
                "prompt_sha256": "a" * 64,
                "schema_sha256": "b" * 64,
            },
        )
        finish_run(connection, extra_run, status="succeeded")
    finally:
        connection.close()
    with pytest.raises(runner.RollingCoachError, match="m10_resume_ai_history_invalid"):
        runner._assert_resume_ready(database, 55)


def test_m10_resume_rejects_self_declared_non_coach_runs(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_resume_identity",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    targets = [f"daily:2026-08-{day:02d}" for day in range(12, 19)] + [
        "weekly:2026-08-18"
    ]
    connection = connect(database)
    try:
        for index, target in enumerate(targets):
            run_id = begin_run(
                connection,
                run_key=f"m10-fake-ai-{index}",
                workflow_key=f"m10:{target}",
                dedupe_key=f"m10-fake-ai-{index}",
                skill_name="garmin-sync",
                operation="manual_backfill",
                trigger_kind="manual",
                input_manifest={
                    "m10_role": runner.AI_CALL_ROLE,
                    "target": target,
                    "rolling_sync_output_id": 55,
                    "prompt_sha256": "a" * 64,
                    "schema_sha256": "b" * 64,
                },
            )
            finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    with pytest.raises(runner.RollingCoachError, match="m10_resume_ai_history_invalid"):
        runner._assert_resume_ready(database, 55)


def test_m10_resume_rejects_duplicate_json_role_keys(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_resume_duplicate_json",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    targets = [f"daily:2026-08-{day:02d}" for day in range(12, 19)] + [
        "weekly:2026-08-18"
    ]
    connection = connect(database)
    try:
        for index, target in enumerate(targets):
            operation = "daily_coach" if target.startswith("daily:") else "weekly_coach"
            manifest = (
                '{"m10_role":"m10_rolling_ai_call_v1",'
                f'"target":"{target}",'
                '"rolling_sync_output_id":55,'
                f'"prompt_sha256":"{"a" * 64}",'
                f'"schema_sha256":"{"b" * 64}",'
                '"m10_role":"forged"}'
            )
            connection.execute(
                "INSERT INTO skill_runs "
                "(run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,"
                "attempt_no,input_manifest_json,input_sha256,status,created_at_utc,"
                "started_at_utc,finished_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"m10-duplicate-json-{index}",
                    f"m10:{target}",
                    f"m10-duplicate-json-{index}",
                    "training-coach",
                    operation,
                    "manual",
                    1,
                    manifest,
                    runner.sha256_text(runner.canonical_json(json.loads(manifest))),
                    "succeeded",
                    "2026-08-19T00:00:00Z",
                    "2026-08-19T00:00:00Z",
                    "2026-08-19T00:00:00Z",
                ),
            )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(runner.RollingCoachError, match="m10_resume_ai_history_invalid"):
        runner._assert_resume_ready(database, 55)


def test_m10_rolling_receipt_must_be_unique(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_unique_rolling_receipt",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    connection = connect(database)
    receipt_ids: list[int] = []
    try:
        for index in range(2):
            run_id = begin_run(
                connection,
                run_key=f"m10-rolling-receipt-{index}",
                workflow_key=runner.ROLLING_WORKFLOW_KEY,
                dedupe_key=f"m10-rolling-receipt-{index}",
                skill_name="garmin-sync",
                operation="manual_backfill",
                trigger_kind="manual",
                input_manifest={"m10": True, "index": index},
            )
            receipt_ids.append(
                append_output(
                    connection,
                    skill_run_id=run_id,
                    output_kind="sync_summary",
                    logical_key=f"m10:rolling-receipt:{index}",
                    schema_name="garmin_rolling_week_receipt_v1",
                    schema_version="1",
                    title_text="rolling receipt",
                    content_json={
                        "status": "succeeded",
                        "workflow_key": runner.ROLLING_WORKFLOW_KEY,
                        "daily_windows": {str(index): {}},
                    },
                    content_text="rolling receipt",
                )
            )
            finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    with pytest.raises(runner.RollingCoachError, match="m10_rolling_receipt_missing"):
        runner._rolling_receipt(database, receipt_ids[0])


def test_m10_reused_output_never_invokes_codex(tmp_path: Path) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_no_ninth_call",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-12",
    }
    runner._existing_output = lambda *_args, **_kwargs: (71, payload, 33)
    runner._invoke_codex = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("Codex must not be called while resuming")
    )
    runner._render_and_prepare = lambda **_kwargs: {
        "subject": "M10 resumed daily",
        "output_ids": {},
    }
    report, called = runner._run_one(
        mode="daily",
        target=date(2026, 8, 12),
        source_root=tmp_path,
        database=tmp_path / "trainlab.db",
        run_root=tmp_path / "run",
        executable=tmp_path / "codex",
        rolling_sync_output_id=42,
    )
    assert called is False
    assert report["source_output_id"] == 71


def test_m10_report_binds_explicit_normalized_source_output(tmp_path: Path) -> None:
    renderer = load_script(
        "trainlab_test_m10_renderer_explicit_source",
        "skills/training-report-publisher/scripts/render_report.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    connection = connect(database)
    try:
        source_run = begin_run(
            connection,
            run_key="m10-normalized-weekly",
            workflow_key="weekly:2026-08-18",
            dedupe_key="m10-normalized-weekly",
            skill_name="training-coach",
            operation="weekly_coach",
            trigger_kind="manual",
            input_manifest={"m10": True},
        )
        source_id = append_output(
            connection,
            skill_run_id=source_run,
            output_kind="weekly_summary",
            logical_key="m10:normalized-weekly",
            schema_name="weekly_ai_result_v1",
            schema_version="1",
            title_text="normalized weekly",
            content_json={"normalized": True},
            content_text="normalized weekly",
            period_start_date="2026-08-12",
            period_end_date="2026-08-18",
        )
        finish_run(connection, source_run, status="succeeded")
    finally:
        connection.close()
    title = "TrainLab · M10验收 · 每周训练总结 · 2026-08-12/2026-08-18"
    payload = {
        "title": title,
        "period": "2026-08-12/2026-08-18",
        "content": {"normalized": True},
    }
    template = (SOURCE / "templates/open-report/weekly_report.html").read_text(
        encoding="utf-8"
    )
    html = renderer.render(
        template,
        title,
        payload["period"],
        renderer.body_html(payload["content"]),
        fixed=False,
        payload=payload,
    )
    result = renderer.persist_outputs(
        database,
        kind="weekly",
        mode="open_report",
        title_text=title,
        payload=payload,
        html=html,
        source_output_id=source_id,
    )
    assert result["source_output_id"] == source_id

    mismatched = {
        "period": "2026-08-12/2026-08-18",
        "content": {"normalized": True, "wire_only_null": None},
    }
    mismatched_html = renderer.render(
        template,
        title,
        mismatched["period"],
        renderer.body_html(mismatched["content"]),
        fixed=False,
        payload=mismatched,
    )
    with pytest.raises(ValueError, match="report_source_content_mismatch"):
        renderer.persist_outputs(
            database,
            kind="weekly",
            mode="open_report",
            title_text=title,
            payload=mismatched,
            html=mismatched_html,
            source_output_id=source_id,
        )
    with pytest.raises(ValueError, match="report_html_mismatch"):
        renderer.persist_outputs(
            database,
            kind="weekly",
            mode="open_report",
            title_text=title,
            payload=payload,
            html="<html><body>different</body></html>",
            source_output_id=source_id,
        )
    forged_envelope = {
        **payload,
        "period": "2026-08-11/2026-08-18",
        "forged": True,
    }
    forged_html = renderer.render(
        template,
        title,
        forged_envelope["period"],
        renderer.body_html(forged_envelope["content"]),
        fixed=False,
        payload=forged_envelope,
    )
    with pytest.raises(ValueError, match="report_source_envelope_mismatch"):
        renderer.persist_outputs(
            database,
            kind="weekly",
            mode="open_report",
            title_text=title,
            payload=forged_envelope,
            html=forged_html,
            source_output_id=source_id,
        )
    wrong_title_payload = {**payload, "title": "forged title"}
    wrong_title_html = renderer.render(
        template,
        "forged title",
        wrong_title_payload["period"],
        renderer.body_html(wrong_title_payload["content"]),
        fixed=False,
        payload=wrong_title_payload,
    )
    with pytest.raises(ValueError, match="report_source_envelope_mismatch"):
        renderer.persist_outputs(
            database,
            kind="weekly",
            mode="open_report",
            title_text="forged title",
            payload=wrong_title_payload,
            html=wrong_title_html,
            source_output_id=source_id,
        )


def test_m10_output_reuse_rejects_nonterminal_unbound_summary(
    tmp_path: Path,
) -> None:
    runner = load_script(
        "trainlab_test_m10_runner_reuse",
        "skills/training-coach/scripts/run_rolling_week.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key="m10-unrelated-running",
            workflow_key="daily:2026-08-12",
            dedupe_key="m10-unrelated-running",
            skill_name="training-coach",
            operation="daily_coach",
            trigger_kind="manual",
            input_manifest={"context": {"live_sync": {"output_id": 999}}},
        )
        append_output(
            connection,
            skill_run_id=run_id,
            output_kind="daily_summary",
            logical_key="m10:unrelated",
            schema_name="daily_ai_result_v1",
            schema_version="1",
            title_text="unrelated",
            content_json={},
            content_text="unrelated",
            period_start_date="2026-08-12",
            period_end_date="2026-08-12",
        )
    finally:
        connection.close()
    assert (
        runner._existing_output(
            database,
            "daily",
            date(2026, 8, 12),
            rolling_sync_output_id=55,
        )
        is None
    )


def test_m10_daily_commit_accepts_exact_rolling_receipt(tmp_path: Path) -> None:
    commit = load_script(
        "trainlab_test_m10_commit_rolling",
        "skills/training-coach/scripts/commit_ai_result.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key="m10-rolling-receipt-run",
            workflow_key="m10:rolling-week:2026-08-11/2026-08-18",
            dedupe_key="m10-rolling-receipt-run",
            skill_name="garmin-sync",
            operation="manual_backfill",
            trigger_kind="manual",
            input_manifest={"m10": True},
        )
        receipt_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="m10:test:rolling-receipt",
            schema_name="garmin_rolling_week_receipt_v1",
            schema_version="1",
            title_text="rolling",
            content_json={
                "status": "succeeded",
                "workflow_key": "m10:rolling-week:2026-08-11/2026-08-18",
                "daily_windows": {
                    "2026-08-12": {
                        "report_date": "2026-08-12",
                        "inventory_complete": True,
                        "raw_file_ids": [],
                    }
                },
            },
        )
        receipt_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (receipt_id,)
            ).fetchone()[0]
        )
        finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    context = {
        "report_date": "2026-08-12",
        "health": [],
        "activities": [],
        "live_sync": {"output_id": receipt_id, "sha256": receipt_sha},
    }
    assert commit._live_receipt_errors(context, database) == []


def test_m10_schedule_normalization_is_owned_and_bounded() -> None:
    actions = load_script(
        "trainlab_test_m10_external_normalize",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    items = []
    for index in range(7):
        running = index in {0, 2, 4, 6}
        items.append(
            {
                "date": f"2026-08-{19 + index:02d}",
                "activity_kind": "running" if running else "rest",
                "name": f"Easy-{index + 3}KM-GTS" if running else "休息",
                "purpose": "Easy有氧" if running else "恢复",
                "garmin_mapping_status": "candidate" if running else "unsupported_skip",
                "distance_km": float(index + 3) if running else None,
                "duration_minutes": None,
                "pace_min_seconds_per_km": 390 if running else None,
                "pace_max_seconds_per_km": 435 if running else None,
                "heart_rate_min_bpm": None,
                "heart_rate_max_bpm": None,
                "steps": [{"name": "主课", "end_condition": f"完成 {index + 3} km"}],
                "downgrade_rule": "疲劳则减量",
                "stop_conditions": ["疼痛时停止"],
            }
        )
    schedule = actions.normalize_plan({"items": items})
    assert len(schedule) == 4
    assert all(row["name"].endswith("-E2E-20260818-GTS") for row in schedule)
    assert len({row["name"] for row in schedule}) == 4
    assert all(row["workout_data"]["workoutName"] == row["name"] for row in schedule)
    assert all(row["pace_upper"] == "7:15/km" for row in schedule)
    assert all(row["pace_lower"] == "6:30/km" for row in schedule)
    batch = actions.garmin_batch_requests({"schedule": schedule})
    assert len(batch["upload"]["workouts_data"]) == 4
    assert batch["inspect_calendar"] == {
        "start_date": "2026-08-19",
        "end_date": "2026-08-25",
    }


def test_m10_schedule_skips_compound_workout_instead_of_flattening_it() -> None:
    actions = load_script(
        "trainlab_test_m10_external_compound",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    items = []
    for index in range(7):
        running = index in {0, 2}
        compound = index == 2
        items.append(
            {
                "date": f"2026-08-{19 + index:02d}",
                "activity_kind": "running" if running else "rest",
                "name": "4x5min interval"
                if compound
                else ("Easy 5K" if running else "休息"),
                "purpose": "质量课" if compound else "Easy有氧",
                "garmin_mapping_status": "candidate" if running else "unsupported_skip",
                "distance_km": 5.0 if running else None,
                "duration_minutes": None,
                "pace_min_seconds_per_km": 390 if running else None,
                "pace_max_seconds_per_km": 435 if running else None,
                "heart_rate_min_bpm": None,
                "heart_rate_max_bpm": None,
                "steps": (
                    [
                        {"name": "热身", "end_condition": "10 分钟"},
                        {"name": "重复", "end_condition": "4 x 5 分钟"},
                    ]
                    if compound
                    else [{"name": "主课", "end_condition": "完成 5 km"}]
                ),
                "downgrade_rule": "疲劳则减量",
                "stop_conditions": ["疼痛时停止"],
            }
        )
    schedule = actions.normalize_plan({"items": items})
    assert [row["date"] for row in schedule] == ["2026-08-19"]
    assert schedule[0]["workout_data"]["workoutName"] == schedule[0]["name"]


def test_m10_schedule_rejects_compound_meaning_hidden_in_one_step() -> None:
    actions = load_script(
        "trainlab_test_m10_external_single_compound",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    items = []
    for index in range(7):
        running = index in {0, 2}
        items.append(
            {
                "date": f"2026-08-{19 + index:02d}",
                "activity_kind": "running" if running else "rest",
                "name": "Easy 5K" if index == 0 else ("质量跑" if running else "休息"),
                "purpose": "Easy有氧" if index == 0 else "恢复",
                "garmin_mapping_status": "candidate" if running else "unsupported_skip",
                "distance_km": 5.0 if index == 0 else None,
                "duration_minutes": 30.0 if index == 2 else None,
                "pace_min_seconds_per_km": 390 if running else None,
                "pace_max_seconds_per_km": 435 if running else None,
                "heart_rate_min_bpm": None,
                "heart_rate_max_bpm": None,
                "steps": [
                    {
                        "name": "主课",
                        "end_condition": (
                            "完成 5 km"
                            if index == 0
                            else "3组，每组5分钟，组间慢跑2分钟"
                        ),
                    }
                ],
                "downgrade_rule": "疲劳则减量",
                "stop_conditions": ["疼痛时停止"],
            }
        )
    schedule = actions.normalize_plan({"items": items})
    assert [row["date"] for row in schedule] == ["2026-08-19"]


def test_m10_gmail_requests_are_exact_self_delivery(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_gmail_requests",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    config = tmp_path / "email.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "trainlab_email_recipient_v1",
                "email": "runner@example.com",
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    emails = []
    for index in range(8):
        envelope = tmp_path / f"email-{index}.json"
        envelope.write_text(
            json.dumps(
                {
                    "subject": f"TrainLab {index}",
                    "text": f"text {index}",
                    "html": f"<p>text {index}</p>",
                }
            ),
            encoding="utf-8",
        )
        envelope.chmod(0o600)
        request = {
            "to": ["runner@example.com"],
            "subject": f"TrainLab {index}",
            "body": f"text {index}",
            "htmlBody": f"<p>text {index}</p>",
            "mimeType": "multipart/alternative",
        }
        emails.append(
            {
                "subject": f"TrainLab {index}",
                "envelope_path": str(envelope),
                "envelope_sha256": actions.sha256_file(envelope),
                "request_sha256": actions.sha256_text(actions.canonical_json(request)),
                "recipient": "runner@example.com",
                "recipient_sha256": actions.sha256_text("runner@example.com"),
            }
        )
    requests = actions.gmail_send_requests({"emails": emails}, config)
    assert len(requests) == 8
    assert all(request["to"] == ["runner@example.com"] for request in requests)
    assert all(request["mimeType"] == "multipart/alternative" for request in requests)
    assert all("attachments" not in request for request in requests)
    config.write_text(
        json.dumps(
            {
                "schema_version": "trainlab_email_recipient_v1",
                "email": "different@example.com",
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    with pytest.raises(actions.ExternalActionError, match="m10_email_envelope_invalid"):
        actions.gmail_send_requests({"emails": emails}, config)
    config.write_text(
        json.dumps(
            {
                "schema_version": "trainlab_email_recipient_v1",
                "email": "runner@example.com",
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    first = Path(emails[0]["envelope_path"])
    mutated = json.loads(first.read_text(encoding="utf-8"))
    mutated["text"] = "changed after preview"
    first.write_text(json.dumps(mutated), encoding="utf-8")
    first.chmod(0o600)
    with pytest.raises(actions.ExternalActionError, match="m10_email_envelope_invalid"):
        actions.gmail_send_requests({"emails": emails}, config)


def test_m10_private_email_config_is_owner_only_and_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions = load_script(
        "trainlab_test_m10_private_email_config",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    config = tmp_path / "email.json"
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    config.write_text(
        json.dumps(
            {
                "schema_version": "trainlab_email_recipient_v1",
                "email": "runner@example.com",
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    assert actions.load_email_recipient(config) == (
        "runner@example.com",
        actions.sha256_text("runner@example.com"),
    )
    config.chmod(0o644)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    config.chmod(0o600)
    config.write_text(
        json.dumps(
            {
                "schema_version": "trainlab_email_recipient_v1",
                "email": "",
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    target = tmp_path / "target.json"
    target.write_text(
        '{"schema_version":"trainlab_email_recipient_v1","email":"runner@example.com"}',
        encoding="utf-8",
    )
    target.chmod(0o600)
    config.unlink()
    config.symlink_to(target)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    monkeypatch.setattr(actions, "_assert_candidate_database", lambda path: Path(path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "m10_external_actions.py",
            "preview",
            "--database",
            str(tmp_path / "trainlab.db"),
            "--run-root",
            str(tmp_path),
            "--email-config",
            str(config),
        ],
    )
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.main()
    config.unlink()
    hardlink_source = tmp_path / "email-hardlink-source.json"
    hardlink_source.write_text(
        '{"schema_version":"trainlab_email_recipient_v1","email":"runner@example.com"}',
        encoding="utf-8",
    )
    hardlink_source.chmod(0o600)
    hardlink = tmp_path / "email-hardlink.json"
    hardlink.hardlink_to(hardlink_source)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(hardlink)
    hardlink.unlink()
    hardlink_source.unlink()
    config.write_text(
        '{"schema_version":"trainlab_email_recipient_v1","email":"not-an-address"}',
        encoding="utf-8",
    )
    config.chmod(0o600)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    config.write_bytes(b"{" + b"x" * 1_024 + b"}")
    config.chmod(0o600)
    with pytest.raises(actions.ExternalActionError, match="m10_email_config_invalid"):
        actions.load_email_recipient(config)
    config.write_text(
        '{"schema_version":"trainlab_email_recipient_v1","email":"runner@example.com"}',
        encoding="utf-8",
    )
    config.chmod(0o600)
    with monkeypatch.context() as owner_patch:
        owner_patch.setattr(actions.os, "getuid", lambda: config.stat().st_uid + 1)
        with pytest.raises(
            actions.ExternalActionError, match="m10_email_config_invalid"
        ):
            actions.load_email_recipient(config)


def test_m10_email_module_is_safe_tracked_template() -> None:
    template = json.loads((SOURCE / "email.module.json").read_text(encoding="utf-8"))
    assert template == {
        "schema_version": "trainlab_email_recipient_v1",
        "email": "",
    }
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "email.json"],
            cwd=SOURCE,
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "email.module.json"],
            cwd=SOURCE,
            check=False,
        ).returncode
        == 1
    )


def test_m10_preview_cli_emits_redacted_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    actions = load_script(
        "trainlab_test_m10_private_email_cli",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    private_address = "runner@example.com"
    preview = {
        "schema_version": "m10_external_preview_v1",
        "status": "awaiting_user_confirmation",
        "preview_sha256": "a" * 64,
        "preview_output_id": 123,
        "preview_output_sha256": "b" * 64,
        "emails": [{"recipient": private_address} for _ in range(8)],
        "schedule": [{"name": "test"}],
    }
    monkeypatch.setattr(actions, "build_preview", lambda *_args: preview)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "m10_external_actions.py",
            "preview",
            "--database",
            str(tmp_path / "trainlab.db"),
            "--run-root",
            str(tmp_path),
            "--email-config",
            str(tmp_path / "email.json"),
        ],
    )
    assert actions.main() == 0
    stdout = capsys.readouterr().out
    assert private_address not in stdout
    assert json.loads(stdout) == {
        "email_count": 8,
        "preview_output_id": 123,
        "preview_output_sha256": "b" * 64,
        "preview_sha256": "a" * 64,
        "schedule_count": 1,
        "schema_version": "m10_external_preview_cli_receipt_v1",
        "status": "awaiting_user_confirmation",
    }


def test_m10_external_actions_reject_unsealed_database(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_external_candidate_guard",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    database = init_database(tmp_path / "trainlab.db")
    with pytest.raises(
        actions.ExternalActionError, match="m10_candidate_scope_required"
    ):
        actions._assert_candidate_database(database)


def test_m10_garmin_lookup_parser_accepts_exact_created_workout() -> None:
    actions = load_script(
        "m10_actions_lookup_success",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    name = "恢复Easy跑-E2E-20260818-GTS"
    payload = json.dumps(
        {
            "id": 37278107,
            "name": name,
            "sport": "running",
            "estimated_distance_meters": 4000.0,
        },
        ensure_ascii=True,
    )

    assert actions.parse_garmin_workout_lookup(
        payload,
        expected_workout_id="37278107",
        expected_name=name,
    ) == {
        "exists": True,
        "not_found": False,
        "workout_id": "37278107",
        "name": name,
    }


def test_m10_garmin_lookup_parser_accepts_exact_not_found() -> None:
    actions = load_script(
        "m10_actions_lookup_absent",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    payload = (
        "Error retrieving workout: Garmin Connect is unreachable. "
        "(Details: API call client error (404): API Error 404 - "
        "{'message': None, 'error': 'NotFoundException'})"
    )

    assert actions.parse_garmin_workout_lookup(
        payload,
        expected_workout_id="37278107",
        expected_name="恢复Easy跑-E2E-20260818-GTS",
    ) == {
        "exists": False,
        "not_found": True,
        "workout_id": "37278107",
        "name": "恢复Easy跑-E2E-20260818-GTS",
    }


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (
            json.dumps({"id": 99, "name": "恢复Easy跑-E2E-20260818-GTS"}),
            "m10_garmin_lookup_identity_mismatch",
        ),
        (
            json.dumps({"id": 37278107, "name": "Unrelated-GTS"}),
            "m10_garmin_lookup_identity_mismatch",
        ),
        (
            "Error retrieving workout: server 500; previous detail "
            "404 NotFoundException",
            "m10_garmin_lookup_result_invalid",
        ),
        (
            json.dumps({"id": True, "name": "恢复Easy跑-E2E-20260818-GTS"}),
            "m10_garmin_lookup_result_invalid",
        ),
        ("Error retrieving workout: timeout", "m10_garmin_lookup_result_invalid"),
        ("{}", "m10_garmin_lookup_result_invalid"),
    ],
)
def test_m10_garmin_lookup_parser_fails_closed(payload: str, error_code: str) -> None:
    actions = load_script(
        f"m10_actions_lookup_invalid_{abs(hash(payload))}",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    with pytest.raises(actions.ExternalActionError, match=error_code):
        actions.parse_garmin_workout_lookup(
            payload,
            expected_workout_id="37278107",
            expected_name="恢复Easy跑-E2E-20260818-GTS",
        )


def test_m10_garmin_lookup_cli_rejects_conflicting_status_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions = load_script(
        "m10_actions_lookup_cli_conflicting_status",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "m10_external_actions.py",
            "parse-garmin-workout-lookup",
            "--expected-workout-id",
            "37278107",
            "--expected-name",
            "恢复Easy跑-E2E-20260818-GTS",
        ],
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "Error retrieving workout: server 500; previous detail "
            "404 NotFoundException"
        ),
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_garmin_lookup_result_invalid"
    ):
        actions.main()


def test_m10_preview_validation_requires_exact_batch(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_preview_validation",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    valid = m10_preview_payload(actions)
    recipient_unbound = json.loads(actions.canonical_json(valid))
    del recipient_unbound["emails"][0]["recipient_sha256"]
    recipient_unbound["preview_sha256"] = actions.sha256_text(
        actions.canonical_json(
            {
                key: value
                for key, value in recipient_unbound.items()
                if key != "preview_sha256"
            }
        )
    )
    fabricated = dict(valid)
    fabricated["emails"] = fabricated["emails"][:2]
    fabricated["preview_sha256"] = actions.sha256_text(
        actions.canonical_json(
            {key: value for key, value in fabricated.items() if key != "preview_sha256"}
        )
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        assert (
            connection.execute(
                "SELECT trainlab_valid_m10_preview(?)",
                (actions.canonical_json(valid),),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT trainlab_valid_m10_preview(?)",
                (actions.canonical_json(fabricated),),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT trainlab_valid_m10_preview(?)",
                (actions.canonical_json(recipient_unbound),),
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key="m10-fabricated-preview",
            workflow_key="m10:external-preview:2026-08-18",
            dedupe_key="m10-fabricated-preview",
            skill_name="training-report-publisher",
            operation="render_weekly",
            trigger_kind="manual",
            input_manifest={"m10": True},
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="execution_summary",
            logical_key="m10:fabricated-preview",
            schema_name="m10_external_preview_v1",
            schema_version="1",
            title_text="fabricated",
            content_json=valid,
            content_text="fabricated",
        )
        output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
            ).fetchone()[0]
        )
        finish_run(connection, run_id, status="succeeded")
    finally:
        connection.close()
    first = valid["emails"][0]
    spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{first['marker']}"
    )
    with pytest.raises(sqlite3.IntegrityError, match="m10_preview_sources_invalid"):
        actions.authorize_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            source_ref=f"m10-preview:{valid['preview_sha256']}",
            preview_sha256=str(valid["preview_sha256"]),
        )


def test_m10_mcp_write_claim_requires_preview_approval_and_action(
    tmp_path: Path,
) -> None:
    database = init_database(tmp_path / "trainlab.db")
    manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "gmail",
        "tool_name": "send_email",
        "request_sha256": "1" * 64,
        "preview_output_id": 1,
        "preview_output_sha256": "2" * 64,
        "preview_sha256": "3" * 64,
        "external_action_ids": [],
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-fabricated-mcp-call",
                workflow_key="m10:external:gmail:2026-08-18",
                dedupe_key="m10-fabricated-mcp-call",
                skill_name="gmail-sender",
                operation="send_email",
                trigger_kind="manual",
                input_manifest=manifest,
            )
    finally:
        connection.close()


def test_m10_external_action_ledger_requires_exact_approval(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_external_ledger",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    request = {
        "to": ["runner@example.com"],
        "subject": "TrainLab test",
        "body": "bounded text",
        "htmlBody": "<p>bounded text</p>",
        "mimeType": "multipart/alternative",
    }
    second_request = {
        "to": ["runner@example.com"],
        "subject": "TrainLab second",
        "body": "second text",
        "htmlBody": "<p>second text</p>",
        "mimeType": "multipart/alternative",
    }
    seeded = seed_valid_m10_preview(
        actions,
        database,
        prefix="m10-email-source",
        email_requests=[request, second_request],
    )
    preview_sha = str(seeded["preview"]["preview_sha256"])
    run_id = int(seeded["run_id"])
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])
    first_marker = str(seeded["preview"]["emails"][0]["marker"])
    second_marker = str(seeded["preview"]["emails"][1]["marker"])
    spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{first_marker}"
    )
    approval_id = actions.authorize_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    request_json = actions.canonical_json(request)
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_terminal_evidence_invalid"
        ):
            connection.execute(
                """INSERT INTO external_actions
                (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
                 source_output_id,source_output_sha256,approval_id,target_key,request_json,
                 request_sha256,status,attempt_count,prepared_at_utc,finished_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "b" * 64,
                    run_id,
                    "gmail",
                    "email",
                    "gmail_send",
                    output_id,
                    output_sha,
                    approval_id,
                    f"m10:email:{first_marker}",
                    request_json,
                    actions.sha256_text(request_json),
                    "succeeded",
                    0,
                    actions.utc_now(),
                    actions.utc_now(),
                ),
            )
    finally:
        connection.close()
    action_id = actions.prepare_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=approval_id,
        request=request,
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_mcp_action_binding_invalid"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="send_email",
            request=request,
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
        )
    with pytest.raises(
        actions.ExternalActionError, match="m10_mcp_action_binding_invalid"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="send_email",
            request={**request, "subject": "not approved"},
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
        )
    call_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="send_email",
        request=request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_missing"
        ):
            connection.execute(
                "UPDATE skill_runs SET status='succeeded' WHERE id=?", (call_id,)
            )
    finally:
        connection.rollback()
        connection.close()
    actions.finish_mcp_tool_call(
        database,
        call_id,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "send_email",
            "request_sha256": actions.sha256_text(actions.canonical_json(request)),
            "external_action_ids": [action_id],
            "message_id": "message-1",
            "matched_message_ids": [],
            "match_count": 0,
        },
    )
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_duplicate"
        ):
            actions.append_output(
                connection,
                skill_run_id=call_id,
                output_kind="execution_summary",
                logical_key=f"m10:mcp-result:{call_id}:late",
                schema_name="m10_mcp_call_result_v1",
                schema_version="999",
                title_text="M10 gmail send_email late result",
                content_json={
                    "schema_version": "m10_mcp_call_result_v1",
                    "provider": "gmail",
                    "tool_name": "send_email",
                    "request_sha256": actions.sha256_text(
                        actions.canonical_json(request)
                    ),
                    "external_action_ids": [action_id],
                    "message_id": "message-1",
                    "matched_message_ids": [],
                    "match_count": 0,
                    "unexpected": True,
                },
                content_text="late duplicate",
                lineage=[{"output_id": output_id, "output_sha256": output_sha}],
            )
    finally:
        connection.rollback()
        connection.close()
    with pytest.raises(actions.ExternalActionError, match="m10_action_not_in_preview"):
        actions.prepare_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            approval_id=approval_id,
            request={**request, "to": ["other@example.invalid"]},
        )
    actions.transition_action(database, action_id, status="in_progress")
    verification_query = str(seeded["preview"]["emails"][0]["verification_query"])
    search_request = {"query": verification_query, "maxResults": 10}
    search_call, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=search_request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_missing"
        ):
            connection.execute(
                "UPDATE skill_runs SET status='succeeded' WHERE id=?", (search_call,)
            )
    finally:
        connection.rollback()
        connection.close()
    actions.finish_mcp_tool_call(
        database,
        search_call,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "search_emails",
            "request_sha256": actions.sha256_text(
                actions.canonical_json(search_request)
            ),
            "external_action_ids": [action_id],
            "message_id": None,
            "matched_message_ids": ["message-1"],
            "match_count": 1,
        },
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_gmail_success_evidence_missing"
    ):
        actions.transition_action(
            database,
            action_id,
            status="succeeded",
            result_external_id="message-2",
            provider_marker=first_marker,
            response_summary={
                "verified": True,
                "match_count": 1,
                "verification_query": verification_query,
                "send_message_id": "message-2",
                "matched_message_id": "message-2",
            },
        )
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_terminal_evidence_invalid"
        ):
            connection.execute(
                "UPDATE external_actions SET status='succeeded',"
                "result_external_id='message-2',provider_marker=?,"
                "response_summary_json=? WHERE id=?",
                (
                    first_marker,
                    actions.canonical_json(
                        {
                            "verified": True,
                            "match_count": 1,
                            "verification_query": verification_query,
                            "send_message_id": "message-2",
                            "matched_message_id": "message-2",
                        }
                    ),
                    action_id,
                ),
            )
    finally:
        connection.rollback()
        connection.close()
    actions.transition_action(
        database,
        action_id,
        status="succeeded",
        result_external_id="message-1",
        provider_marker=first_marker,
        response_summary={
            "verified": True,
            "match_count": 1,
            "verification_query": verification_query,
            "send_message_id": "message-1",
            "matched_message_id": "message-1",
        },
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status,attempt_count,result_external_id FROM external_actions WHERE id=?",
            (action_id,),
        ).fetchone()
        approval_count = connection.execute(
            "SELECT COUNT(*) FROM approvals"
        ).fetchone()[0]
    finally:
        connection.close()
    assert tuple(row) == ("succeeded", 1, "message-1")
    assert approval_count == 1

    second_spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{second_marker}"
    )
    second_approval = actions.authorize_action(
        database,
        spec=second_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    second_action = actions.prepare_action(
        database,
        spec=second_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=second_approval,
        request=second_request,
    )
    actions.transition_action(database, second_action, status="in_progress")
    actions.transition_action(database, second_action, status="failed_safe")
    with pytest.raises(
        (actions.ExternalActionError, sqlite3.IntegrityError),
        match="m10_external_retry_forbidden",
    ):
        actions.transition_action(database, second_action, status="in_progress")


def test_unknown_gmail_send_allows_only_exact_read_reconciliation(
    tmp_path: Path,
) -> None:
    actions = load_script(
        "trainlab_test_m10_unknown_gmail_reconciliation",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    request = {
        "to": ["runner@example.com"],
        "subject": "TrainLab reconciliation fixture",
        "body": "bounded text",
        "htmlBody": "<p>bounded text</p>",
        "mimeType": "multipart/alternative",
    }
    seeded = seed_valid_m10_preview(
        actions,
        database,
        prefix="m10-unknown-gmail",
        email_requests=[request],
    )
    preview = seeded["preview"]
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])
    preview_sha = str(preview["preview_sha256"])
    marker = str(preview["emails"][0]["marker"])
    spec = actions.action_spec("gmail", "gmail_send", "email", f"m10:email:{marker}")
    approval_id = actions.authorize_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    action_id = actions.prepare_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=approval_id,
        request=request,
    )
    send_run_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="send_email",
        request=request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    actions.finish_mcp_tool_call(
        database,
        send_run_id,
        status="failed",
        error_code="gmail_send_unconfirmed",
    )
    actions.transition_action(database, action_id, status="in_progress")
    actions.transition_action(
        database,
        action_id,
        status="unknown",
        error_code="gmail_send_unconfirmed",
        error_summary="provider result could not be confirmed",
    )
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="m10_old_gmail_reconciliation_missing",
        ):
            connection.execute(
                "UPDATE external_actions SET status='failed_safe',"
                "finished_at_utc=?,last_reconciled_at_utc=?,"
                "response_summary_json=?,error_code='gmail_manual_not_sent',"
                "error_summary='manual_mailbox_reconciliation' WHERE id=?",
                (
                    actions.utc_now(),
                    actions.utc_now(),
                    actions.canonical_json(
                        {
                            "reconciliation_output_id": 999999,
                            "reconciliation_output_sha256": "a" * 64,
                            "conclusion": "not_sent",
                        }
                    ),
                    action_id,
                ),
            )
    finally:
        connection.rollback()
        connection.close()

    with pytest.raises(
        actions.ExternalActionError, match="m10_mcp_action_binding_invalid"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="send_email",
            request=request,
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
        )

    exact_query = str(preview["emails"][0]["verification_query"])
    exact_search = {
        "query": exact_query,
        "maxResults": 10,
    }
    search_run_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=exact_search,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert search_run_id > 0
    assert reused is False

    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request={**exact_search, "query": exact_query + " changed"},
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
        )
    altered_limit = {**exact_search, "maxResults": 9}
    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request=altered_limit,
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
        )
    invalid_manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "gmail",
        "tool_name": "search_emails",
        "request_json": altered_limit,
        "request_sha256": actions.sha256_text(actions.canonical_json(altered_limit)),
        "preview_output_id": output_id,
        "preview_output_sha256": output_sha,
        "preview_sha256": preview_sha,
        "external_action_ids": [action_id],
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-unknown-gmail-altered-limit",
                workflow_key="m10:external:gmail:2026-08-18",
                dedupe_key="m10-unknown-gmail-altered-limit",
                skill_name="gmail-sender",
                operation="mcp_tool_call",
                trigger_kind="manual",
                input_manifest=invalid_manifest,
            )
    finally:
        connection.rollback()
        connection.close()
    actions.finish_mcp_tool_call(
        database,
        search_run_id,
        status="failed",
        error_code="gmail_search_result_unpersisted",
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_external_retry_forbidden"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request=exact_search,
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
        )
    base_manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "gmail",
        "tool_name": "search_emails",
        "request_json": exact_search,
        "request_sha256": actions.sha256_text(actions.canonical_json(exact_search)),
        "preview_output_id": output_id,
        "preview_output_sha256": output_sha,
        "preview_sha256": preview_sha,
        "external_action_ids": [action_id],
    }
    forged_reconciliation = {
        **base_manifest,
        "reconciliation_mode": "user_approved_result_unpersisted",
        "prior_run_id": search_run_id + 1,
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-unknown-gmail-forged-reconciliation",
                workflow_key="m10:external:gmail:2026-08-18",
                dedupe_key=actions.sha256_text(actions.canonical_json(base_manifest)),
                skill_name="gmail-sender",
                operation="mcp_tool_call",
                trigger_kind="manual",
                input_manifest=forged_reconciliation,
            )
    finally:
        connection.rollback()
        connection.close()
    retry_run_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=exact_search,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
        reconcile_failed_run_id=search_run_id,
    )
    assert retry_run_id != search_run_id
    assert reused is False
    with pytest.raises(
        actions.ExternalActionError, match="m10_external_retry_forbidden"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request=exact_search,
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[action_id],
            reconcile_failed_run_id=search_run_id,
        )
    actions.finish_mcp_tool_call(
        database,
        retry_run_id,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "search_emails",
            "request_sha256": actions.sha256_text(actions.canonical_json(exact_search)),
            "external_action_ids": [action_id],
            "message_id": None,
            "matched_message_ids": ["message-1"],
            "match_count": 1,
        },
    )
    replay_run_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=exact_search,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
        reconcile_failed_run_id=search_run_id,
    )
    assert (replay_run_id, reused) == (retry_run_id, True)


def test_m10_garmin_lifecycle_requires_both_absence_verifications(
    tmp_path: Path,
) -> None:
    actions = load_script(
        "trainlab_test_m10_garmin_lifecycle",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    name = "Easy-5K-E2E-20260818-GTS"
    plan_items: list[dict[str, Any]] = []
    for index in range(7):
        running = index < 4
        distance = 5.0 if index == 0 else float(index + 1)
        item: dict[str, Any] = {
            "date": f"2026-08-{19 + index:02d}",
            "activity_kind": "running" if running else "rest",
            "name": (
                "Easy-5K"
                if index == 0
                else (f"Easy-{index + 1}K" if running else "休息")
            ),
            "purpose": "Easy有氧" if running else "恢复",
            "load_level": "low",
            "garmin_mapping_status": ("candidate" if running else "unsupported_skip"),
            "rpe": 2,
            "downgrade_rule": "疲劳则减量",
            "stop_conditions": ["疼痛时停止"],
        }
        if running:
            item["distance_km"] = distance
            item["steps"] = [{"name": "主课", "end_condition": f"完成 {distance:g} km"}]
        plan_items.append(item)
    seeded = seed_valid_m10_preview(
        actions,
        database,
        prefix="m10-garmin-source",
        plan_items=plan_items,
    )
    preview_schedule = list(seeded["preview"]["schedule"])
    run_id = int(seeded["run_id"])
    preview_sha = str(seeded["preview"]["preview_sha256"])
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])

    invalid_spec = actions.action_spec(
        "garmin",
        "garmin_calendar_schedule",
        "calendar_entry",
        f"m10:schedule:{name}",
    )
    invalid_approval = actions.authorize_action(
        database,
        spec=invalid_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    invalid_request = actions.canonical_json(
        actions.garmin_action_requests(preview_schedule[0])["schedule"]
    )
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_garmin_schedule_order_invalid"
        ):
            connection.execute(
                """INSERT INTO external_actions
                (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
                 source_output_id,source_output_sha256,approval_id,related_action_id,
                 target_key,target_external_id,provider_object_name,request_json,
                 request_sha256,status,attempt_count,prepared_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "c" * 64,
                    run_id,
                    "garmin",
                    "calendar_entry",
                    "garmin_calendar_schedule",
                    output_id,
                    output_sha,
                    invalid_approval,
                    None,
                    f"m10:schedule:{name}",
                    "workout-0",
                    name,
                    invalid_request,
                    actions.hashlib.sha256(invalid_request.encode()).hexdigest(),
                    "prepared",
                    0,
                    actions.utc_now(),
                ),
            )
    finally:
        connection.close()

    create_spec = actions.action_spec(
        "garmin", "garmin_workout_create", "workout", f"m10:create:{name}"
    )
    create_approval = actions.authorize_action(
        database,
        spec=create_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )

    def direct_insert(
        *,
        key: str,
        action_kind: str,
        request: dict[str, Any],
        approval_id: int,
        status: str = "prepared",
        result_external_id: str | None = None,
        response_summary: dict[str, Any] | None = None,
        object_name: str = name,
        target_key: str | None = None,
        source_id: int = output_id,
        source_sha256: str = output_sha,
        source_run_id: int = run_id,
    ) -> None:
        request_json = actions.canonical_json(request)
        direct_connection = connect(database)
        try:
            direct_connection.execute(
                """INSERT INTO external_actions
                (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
                 source_output_id,source_output_sha256,approval_id,related_action_id,
                 target_key,target_external_id,result_external_id,provider_object_name,
                 request_json,request_sha256,response_summary_json,status,attempt_count,
                 prepared_at_utc,finished_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key * 64,
                    source_run_id,
                    "garmin",
                    "workout",
                    action_kind,
                    source_id,
                    source_sha256,
                    approval_id,
                    None,
                    target_key or f"m10:create:{object_name}",
                    None,
                    result_external_id,
                    object_name,
                    request_json,
                    actions.hashlib.sha256(request_json.encode()).hexdigest(),
                    (
                        actions.canonical_json(response_summary)
                        if response_summary is not None
                        else None
                    ),
                    status,
                    0,
                    actions.utc_now(),
                    actions.utc_now()
                    if status
                    in {"succeeded", "already_done", "failed_safe", "cancelled"}
                    else None,
                ),
            )
        finally:
            direct_connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="m10_garmin_phase_required"):
        direct_insert(
            key="d",
            action_kind="garmin_workout_create",
            request={"name": name},
            approval_id=create_approval,
        )
    with pytest.raises(
        sqlite3.IntegrityError, match="m10_garmin_terminal_evidence_invalid"
    ):
        direct_insert(
            key="e",
            action_kind="garmin_workout_create",
            request=actions.garmin_action_requests(preview_schedule[0])["create"],
            approval_id=create_approval,
            status="succeeded",
            result_external_id="workout-unproven",
        )
    with pytest.raises(
        sqlite3.IntegrityError, match="m10_external_preview_member_invalid"
    ):
        direct_insert(
            key="7",
            action_kind="garmin_workout_create",
            request=actions.garmin_action_requests(preview_schedule[0])["create"],
            approval_id=create_approval,
            object_name="Existing-Style-GTS",
            target_key=create_spec["target_key"],
        )
    with pytest.raises(sqlite3.IntegrityError):
        direct_insert(
            key="f",
            action_kind="garmin_workout_adopt",
            request=actions.garmin_action_requests(preview_schedule[0])["create"],
            approval_id=create_approval,
        )

    def prepare_phase(
        phase: str,
        action_kind: str,
        entity_kind: str,
        *,
        related: int | None = None,
        target_id: str | None = None,
    ) -> int:
        spec = actions.action_spec(
            "garmin", action_kind, entity_kind, f"m10:{phase}:{name}"
        )
        approval = actions.authorize_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            source_ref=f"m10-preview:{preview_sha}",
            preview_sha256=preview_sha,
        )
        return actions.prepare_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            approval_id=approval,
            request=actions.garmin_action_requests(preview_schedule[0])[phase],
            related_action_id=related,
            target_external_id=target_id,
            provider_object_name=name,
        )

    def succeed(
        action_id: int,
        *,
        result_id: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        actions.transition_action(database, action_id, status="in_progress")
        actions.transition_action(
            database,
            action_id,
            status="succeeded",
            result_external_id=result_id,
            response_summary=summary,
        )

    owner = prepare_phase("create", "garmin_workout_create", "workout")
    succeed(
        owner,
        result_id="workout-1",
        summary={"created_new": True, "preexisting": False},
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_garmin_lifecycle_order_invalid"
    ):
        prepare_phase(
            "delete",
            "garmin_workout_delete",
            "workout",
            related=owner,
            target_id="workout-1",
        )

    created_verify = prepare_phase(
        "verify_created",
        "garmin_workout_verify",
        "workout",
        related=owner,
        target_id="workout-1",
    )
    succeed(created_verify, summary={"exists": True})
    schedule = prepare_phase(
        "schedule",
        "garmin_calendar_schedule",
        "calendar_entry",
        related=owner,
        target_id="workout-1",
    )
    succeed(schedule, result_id="calendar-1")
    scheduled_verify = prepare_phase(
        "verify_scheduled",
        "garmin_workout_verify",
        "workout",
        related=schedule,
        target_id="calendar-1",
    )
    succeed(scheduled_verify, summary={"exists": True})
    unschedule = prepare_phase(
        "unschedule",
        "garmin_calendar_unschedule",
        "calendar_entry",
        related=owner,
        target_id="calendar-1",
    )
    succeed(unschedule)
    with pytest.raises(
        actions.ExternalActionError, match="m10_garmin_lifecycle_order_invalid"
    ):
        prepare_phase(
            "delete",
            "garmin_workout_delete",
            "workout",
            related=owner,
            target_id="workout-1",
        )
    absent_after_unschedule = prepare_phase(
        "verify_absent_after_unschedule",
        "garmin_workout_verify",
        "workout",
        related=unschedule,
        target_id="calendar-1",
    )
    succeed(absent_after_unschedule, summary={"absent": True})
    deletion = prepare_phase(
        "delete",
        "garmin_workout_delete",
        "workout",
        related=owner,
        target_id="workout-1",
    )
    with pytest.raises(
        actions.ExternalActionError, match="m10_mcp_action_binding_invalid"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="garmin",
            tool_name="delete_workouts",
            request={"workout_ids": ["preexisting-workout-123"]},
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[deletion],
        )
    delete_call, reused = actions.claim_mcp_tool_call(
        database,
        provider="garmin",
        tool_name="delete_workouts",
        request={"workout_ids": ["workout-1"]},
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[deletion],
    )
    assert reused is False
    actions.finish_mcp_tool_call(database, delete_call, status="succeeded")
    succeed(deletion)
    with pytest.raises(actions.ExternalActionError):
        actions.assert_garmin_cleanup_complete(database, [owner])
    absent_after_delete = prepare_phase(
        "verify_absent_after_delete",
        "garmin_workout_verify",
        "workout",
        related=deletion,
        target_id="workout-1",
    )
    succeed(absent_after_delete, summary={"absent": True})
    actions.assert_garmin_cleanup_complete(database, [owner])

    for index in range(2, 5):
        extra_name = f"Easy-{index}K-E2E-20260818-GTS"
        extra_row = next(row for row in preview_schedule if row["name"] == extra_name)
        spec = actions.action_spec(
            "garmin",
            "garmin_workout_create",
            "workout",
            f"m10:create:{extra_name}",
        )
        approval = actions.authorize_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            source_ref=f"m10-preview:{preview_sha}",
            preview_sha256=preview_sha,
        )
        actions.prepare_action(
            database,
            spec=spec,
            source_output_id=output_id,
            source_output_sha256=output_sha,
            approval_id=approval,
            request=actions.garmin_action_requests(extra_row)["create"],
            provider_object_name=extra_name,
        )
    fifth_name = "Easy-5K-B-E2E-20260818-GTS"
    fifth_plan_items: list[dict[str, Any]] = []
    for index in range(7):
        running = index == 6
        item = {
            "date": f"2026-08-{19 + index:02d}",
            "activity_kind": "running" if running else "rest",
            "name": "Easy-5K-B" if running else "休息",
            "purpose": "Easy有氧" if running else "恢复",
            "load_level": "low",
            "garmin_mapping_status": ("candidate" if running else "unsupported_skip"),
            "rpe": 2,
            "downgrade_rule": "疲劳则减量",
            "stop_conditions": ["疼痛时停止"],
        }
        if running:
            item["distance_km"] = 5.0
            item["steps"] = [{"name": "主课", "end_condition": "完成 5 km"}]
        fifth_plan_items.append(item)
    fifth_seeded = seed_valid_m10_preview(
        actions,
        database,
        prefix="m10-fifth-garmin-source",
        plan_items=fifth_plan_items,
    )
    fifth_row = dict(fifth_seeded["preview"]["schedule"][0])
    fifth_run_id = int(fifth_seeded["run_id"])
    fifth_preview_sha = str(fifth_seeded["preview"]["preview_sha256"])
    fifth_output_id = int(fifth_seeded["output_id"])
    fifth_output_sha = str(fifth_seeded["output_sha256"])
    fifth_spec = actions.action_spec(
        "garmin",
        "garmin_workout_create",
        "workout",
        f"m10:create:{fifth_name}",
    )
    fifth_approval = actions.authorize_action(
        database,
        spec=fifth_spec,
        source_output_id=fifth_output_id,
        source_output_sha256=fifth_output_sha,
        source_ref=f"m10-preview:{fifth_preview_sha}",
        preview_sha256=fifth_preview_sha,
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="m10_garmin_create_budget_exceeded"
    ):
        direct_insert(
            key="9",
            action_kind="garmin_workout_create",
            request=actions.garmin_action_requests(fifth_row)["create"],
            approval_id=fifth_approval,
            object_name=fifth_name,
            source_id=fifth_output_id,
            source_sha256=fifth_output_sha,
            source_run_id=fifth_run_id,
        )
    with pytest.raises(actions.ExternalActionError, match="m10_workout_budget_invalid"):
        actions.prepare_action(
            database,
            spec=fifth_spec,
            source_output_id=fifth_output_id,
            source_output_sha256=fifth_output_sha,
            approval_id=fifth_approval,
            request=actions.garmin_action_requests(fifth_row)["create"],
            provider_object_name=fifth_name,
        )
    with pytest.raises(
        actions.ExternalActionError, match="m10_garmin_cleanup_scope_mismatch"
    ):
        actions.assert_garmin_cleanup_complete(database, [owner])


@pytest.mark.parametrize(
    "invalid_option",
    [
        "invalid_daily_schema",
        "invalid_weekly_lineage",
        "invalid_training_plan",
        "failed_daily_run",
    ],
)
def test_m10_approval_requires_verified_report_and_plan_sources(
    tmp_path: Path, invalid_option: str
) -> None:
    actions = load_script(
        f"trainlab_test_m10_invalid_source_{invalid_option}",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / f"{invalid_option}.db")
    invalid = {
        "invalid_daily_schema": invalid_option == "invalid_daily_schema",
        "invalid_weekly_lineage": invalid_option == "invalid_weekly_lineage",
        "invalid_training_plan": invalid_option == "invalid_training_plan",
        "failed_daily_run": invalid_option == "failed_daily_run",
    }
    seeded = seed_valid_m10_preview(
        actions,
        database,
        prefix=f"m10-{invalid_option}",
        invalid_daily_schema=invalid["invalid_daily_schema"],
        invalid_weekly_lineage=invalid["invalid_weekly_lineage"],
        invalid_training_plan=invalid["invalid_training_plan"],
        failed_daily_run=invalid["failed_daily_run"],
    )
    preview_sha = str(seeded["preview"]["preview_sha256"])
    marker = str(seeded["preview"]["emails"][0]["marker"])
    with pytest.raises(sqlite3.IntegrityError, match="m10_preview_sources_invalid"):
        actions.authorize_action(
            database,
            spec=actions.action_spec(
                "gmail", "gmail_send", "email", f"m10:email:{marker}"
            ),
            source_output_id=int(seeded["output_id"]),
            source_output_sha256=str(seeded["output_sha256"]),
            source_ref=f"m10-preview:{preview_sha}",
            preview_sha256=preview_sha,
        )


def test_m10_garmin_mcp_run_binds_exact_prepared_request(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_mcp_exact_garmin",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    seeded = seed_valid_m10_preview(actions, database, prefix="m10-mcp-exact")
    preview = seeded["preview"]
    row = dict(preview["schedule"][0])
    preview_sha = str(preview["preview_sha256"])
    spec = actions.action_spec(
        "garmin",
        "garmin_workout_create",
        "workout",
        f"m10:create:{row['name']}",
    )
    approval = actions.authorize_action(
        database,
        spec=spec,
        source_output_id=int(seeded["output_id"]),
        source_output_sha256=str(seeded["output_sha256"]),
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    action_id = actions.prepare_action(
        database,
        spec=spec,
        source_output_id=int(seeded["output_id"]),
        source_output_sha256=str(seeded["output_sha256"]),
        approval_id=approval,
        request=actions.garmin_action_requests(row)["create"],
        provider_object_name=str(row["name"]),
    )
    malicious_request = {"workout_data": {"workoutName": "Not approved"}}
    manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "garmin",
        "tool_name": "upload_workout",
        "request_json": malicious_request,
        "request_sha256": actions.sha256_text(
            actions.canonical_json(malicious_request)
        ),
        "preview_output_id": int(seeded["output_id"]),
        "preview_output_sha256": str(seeded["output_sha256"]),
        "preview_sha256": preview_sha,
        "external_action_ids": [action_id],
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-malicious-garmin-run",
                workflow_key="m10:external:garmin:2026-08-18",
                dedupe_key="e" * 64,
                skill_name="garmin-training-sender",
                operation="apply_weekly_plan",
                trigger_kind="manual",
                input_manifest=manifest,
            )
    finally:
        connection.close()


def test_m10_mcp_contract_rejects_alternate_workflow_extra_fields_and_unbounded_reads(
    tmp_path: Path,
) -> None:
    actions = load_script(
        "trainlab_test_m10_mcp_closed_contract",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    seeded = seed_valid_m10_preview(actions, database, prefix="m10-mcp-closed")
    preview = seeded["preview"]
    preview_id = int(seeded["output_id"])
    preview_output_sha = str(seeded["output_sha256"])
    preview_sha = str(preview["preview_sha256"])

    course = dict(preview["schedule"][0])
    create_request = actions.garmin_action_requests(course)["create"]
    create_spec = actions.action_spec(
        "garmin",
        "garmin_workout_create",
        "workout",
        f"m10:create:{course['name']}",
    )
    create_approval = actions.authorize_action(
        database,
        spec=create_spec,
        source_output_id=preview_id,
        source_output_sha256=preview_output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    create_action = actions.prepare_action(
        database,
        spec=create_spec,
        source_output_id=preview_id,
        source_output_sha256=preview_output_sha,
        approval_id=create_approval,
        request=create_request,
        provider_object_name=str(course["name"]),
    )

    def insert_manifest(
        *, workflow_key: str, request: dict[str, Any], run_suffix: str
    ) -> None:
        manifest = {
            "m10_role": "m10_external_mcp_call_v1",
            "provider": "garmin",
            "tool_name": "upload_workout",
            "request_json": request,
            "request_sha256": actions.sha256_text(actions.canonical_json(request)),
            "preview_output_id": preview_id,
            "preview_output_sha256": preview_output_sha,
            "preview_sha256": preview_sha,
            "external_action_ids": [create_action],
        }
        connection = connect(database)
        try:
            begin_run(
                connection,
                run_key=f"m10-closed-{run_suffix}",
                workflow_key=workflow_key,
                dedupe_key=f"m10-closed-{run_suffix}",
                skill_name="garmin-training-sender",
                operation="apply_weekly_plan",
                trigger_kind="manual",
                input_manifest=manifest,
            )
        finally:
            connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"):
        insert_manifest(
            workflow_key="m10:mcp-bypass:garmin",
            request=create_request,
            run_suffix="wrong-workflow",
        )
    with pytest.raises(sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"):
        insert_manifest(
            workflow_key="m10:external:garmin:2026-08-18",
            request={**create_request, "unapproved": True},
            run_suffix="extra-field",
        )

    unbounded_read = {"unapproved": True}
    unbounded_manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "garmin",
        "tool_name": "get_workouts",
        "request_json": unbounded_read,
        "request_sha256": actions.sha256_text(actions.canonical_json(unbounded_read)),
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_output_sha,
        "preview_sha256": preview_sha,
        "external_action_ids": [],
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-closed-unbounded-read",
                workflow_key="m10:external:garmin:2026-08-18",
                dedupe_key="m10-closed-unbounded-read",
                skill_name="garmin-training-sender",
                operation="apply_weekly_plan",
                trigger_kind="manual",
                input_manifest=unbounded_manifest,
            )
    finally:
        connection.close()

    omitted_identity = {
        "provider": "gmail",
        "tool_name": "send_email",
        "request_json": dict(seeded["requests"][0]),
    }
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_mcp_run_contract_invalid"
        ):
            begin_run(
                connection,
                run_key="m10-closed-omitted-identity",
                workflow_key="daily:2026-08-18",
                dedupe_key="m10-closed-omitted-identity",
                skill_name="gmail-sender",
                operation="mcp_tool_call",
                trigger_kind="manual",
                input_manifest=omitted_identity,
            )
    finally:
        connection.close()

    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="garmin",
            tool_name="get_workouts",
            request={"unapproved": True},
            preview_output_id=preview_id,
            preview_output_sha256=preview_output_sha,
        )
    call_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="garmin",
        tool_name="get_workouts",
        request={},
        preview_output_id=preview_id,
        preview_output_sha256=preview_output_sha,
    )
    assert reused is False
    actions.finish_mcp_tool_call(database, call_id, status="succeeded")

    marker = str(preview["emails"][0]["marker"])
    email_spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{marker}"
    )
    email_approval = actions.authorize_action(
        database,
        spec=email_spec,
        source_output_id=preview_id,
        source_output_sha256=preview_output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    email_action = actions.prepare_action(
        database,
        spec=email_spec,
        source_output_id=preview_id,
        source_output_sha256=preview_output_sha,
        approval_id=email_approval,
        request=dict(seeded["requests"][0]),
    )
    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request={"query": "not-the-approved-marker", "maxResults": 10},
            preview_output_id=preview_id,
            preview_output_sha256=preview_output_sha,
            external_action_ids=[email_action],
        )
    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request={"query": marker, "maxResults": 10},
            preview_output_id=preview_id,
            preview_output_sha256=preview_output_sha,
            external_action_ids=[email_action],
        )
    subject_query = str(seeded["preview"]["emails"][0]["verification_query"])
    subject_call, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request={"query": subject_query, "maxResults": 10},
        preview_output_id=preview_id,
        preview_output_sha256=preview_output_sha,
        external_action_ids=[email_action],
    )
    assert reused is False
    with pytest.raises(actions.ExternalActionError, match="m10_mcp_result_invalid"):
        actions.finish_mcp_tool_call(database, subject_call, status="succeeded")
    actions.finish_mcp_tool_call(
        database,
        subject_call,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "search_emails",
            "request_sha256": actions.sha256_text(
                actions.canonical_json({"query": subject_query, "maxResults": 10})
            ),
            "external_action_ids": [email_action],
            "message_id": None,
            "matched_message_ids": ["message-1"],
            "match_count": 1,
        },
    )
    with pytest.raises(actions.ExternalActionError, match="m10_mcp_read_scope_invalid"):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request={"query": 'subject:"not approved"', "maxResults": 10},
            preview_output_id=preview_id,
            preview_output_sha256=preview_output_sha,
            external_action_ids=[email_action],
        )


@pytest.mark.parametrize(
    "sql_matched_ids",
    [[], ["message-1", "message-2"]],
    ids=["zero-match", "multiple-matches"],
)
def test_m10_gmail_sql_rejects_non_unique_search_evidence(
    tmp_path: Path, sql_matched_ids: list[str]
) -> None:
    actions = load_script(
        "trainlab_test_m10_gmail_multi_match",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    seeded = seed_valid_m10_preview(
        actions, database, prefix="m10-gmail-multi-match-source"
    )
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])
    preview_sha = str(seeded["preview"]["preview_sha256"])
    marker = str(seeded["preview"]["emails"][0]["marker"])
    request = dict(seeded["requests"][0])
    spec = actions.action_spec("gmail", "gmail_send", "email", f"m10:email:{marker}")
    approval_id = actions.authorize_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    action_id = actions.prepare_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=approval_id,
        request=request,
    )
    send_call, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="send_email",
        request=request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    actions.finish_mcp_tool_call(
        database,
        send_call,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "send_email",
            "request_sha256": actions.sha256_text(actions.canonical_json(request)),
            "external_action_ids": [action_id],
            "message_id": "message-1",
            "matched_message_ids": [],
            "match_count": 0,
        },
    )
    actions.transition_action(database, action_id, status="in_progress")
    verification_query = str(seeded["preview"]["emails"][0]["verification_query"])
    search_request = {"query": verification_query, "maxResults": 10}
    search_call, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=search_request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    invalid_result = {
        "schema_version": "m10_mcp_call_result_v1",
        "provider": "gmail",
        "tool_name": "search_emails",
        "request_sha256": actions.sha256_text(actions.canonical_json(search_request)),
        "external_action_ids": [action_id],
        "message_id": None,
        "matched_message_ids": sql_matched_ids,
        "match_count": len(sql_matched_ids),
    }
    for matched_ids in ([], ["message-1", "message-2"]):
        api_result = {
            **invalid_result,
            "matched_message_ids": matched_ids,
            "match_count": len(matched_ids),
        }
        with pytest.raises(actions.ExternalActionError, match="m10_mcp_result_invalid"):
            actions.finish_mcp_tool_call(
                database,
                search_call,
                status="succeeded",
                result_summary=api_result,
            )
    connection = connect(database)
    try:
        actions.append_output(
            connection,
            skill_run_id=search_call,
            output_kind="execution_summary",
            logical_key=f"m10:mcp-result:{search_call}",
            schema_name="m10_mcp_call_result_v1",
            schema_version="1",
            title_text="M10 gmail search_emails result",
            content_json=invalid_result,
            content_text=actions.canonical_json(invalid_result),
            lineage=[{"output_id": output_id, "output_sha256": output_sha}],
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_missing"
        ):
            actions.finish_run(connection, search_call, status="succeeded")
    finally:
        connection.rollback()
        connection.close()


def test_m10_gmail_sql_rejects_schema_invalid_single_result(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_gmail_schema_invalid_result",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    seeded = seed_valid_m10_preview(
        actions, database, prefix="m10-gmail-invalid-result-source"
    )
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])
    preview_sha = str(seeded["preview"]["preview_sha256"])
    marker = str(seeded["preview"]["emails"][0]["marker"])
    request = dict(seeded["requests"][0])
    spec = actions.action_spec("gmail", "gmail_send", "email", f"m10:email:{marker}")
    approval_id = actions.authorize_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    action_id = actions.prepare_action(
        database,
        spec=spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=approval_id,
        request=request,
    )
    call_id, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="send_email",
        request=request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[action_id],
    )
    assert reused is False
    invalid_result = {
        "schema_version": "m10_mcp_call_result_v1",
        "provider": "gmail",
        "tool_name": "send_email",
        "request_sha256": actions.sha256_text(actions.canonical_json(request)),
        "external_action_ids": [action_id],
        "message_id": "message-1",
        "matched_message_ids": [],
        "match_count": 0,
        "unexpected": True,
    }
    connection = connect(database)
    try:
        actions.append_output(
            connection,
            skill_run_id=call_id,
            output_kind="execution_summary",
            logical_key=f"m10:mcp-result:{call_id}",
            schema_name="m10_mcp_call_result_v1",
            schema_version="999",
            title_text="M10 gmail send_email result",
            content_json=invalid_result,
            content_text=actions.canonical_json(invalid_result),
            lineage=[{"output_id": output_id, "output_sha256": output_sha}],
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_missing"
        ):
            actions.finish_run(connection, call_id, status="succeeded")
    finally:
        connection.rollback()
        connection.close()


def test_m10_mcp_tool_call_budgets_are_persistent(tmp_path: Path) -> None:
    actions = load_script(
        "trainlab_test_m10_mcp_call_budget",
        "skills/_shared/scripts/m10_external_actions.py",
    )
    actions._assert_candidate_database = lambda path: Path(path)
    database = init_database(tmp_path / "trainlab.db")
    seeded = seed_valid_m10_preview(actions, database, prefix="m10-mcp-preview-source")
    output_id = int(seeded["output_id"])
    output_sha = str(seeded["output_sha256"])
    preview_sha = str(seeded["preview"]["preview_sha256"])
    marker = str(seeded["preview"]["emails"][0]["marker"])
    email_spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{marker}"
    )
    email_approval = actions.authorize_action(
        database,
        spec=email_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    email_action = actions.prepare_action(
        database,
        spec=email_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=email_approval,
        request=dict(seeded["requests"][0]),
    )

    gmail_request = {
        "query": str(seeded["preview"]["emails"][0]["verification_query"]),
        "maxResults": 10,
    }
    first_run, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=gmail_request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[email_action],
    )
    assert reused is False
    actions.finish_mcp_tool_call(
        database,
        first_run,
        status="succeeded",
        result_summary={
            "schema_version": "m10_mcp_call_result_v1",
            "provider": "gmail",
            "tool_name": "search_emails",
            "request_sha256": actions.sha256_text(
                actions.canonical_json(gmail_request)
            ),
            "external_action_ids": [email_action],
            "message_id": None,
            "matched_message_ids": ["message-1"],
            "match_count": 1,
        },
    )
    connection = connect(database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="m10_gmail_mcp_result_missing"
        ):
            connection.execute(
                "INSERT INTO skill_runs "
                "(run_key,workflow_key,dedupe_key,skill_name,operation,trigger_kind,"
                "attempt_no,input_manifest_json,input_sha256,status,created_at_utc) "
                "SELECT run_key || ':direct-success',workflow_key,"
                "dedupe_key || ':direct-success',skill_name,operation,trigger_kind,"
                "attempt_no,input_manifest_json,input_sha256,'succeeded',created_at_utc "
                "FROM skill_runs WHERE id=?",
                (first_run,),
            )
    finally:
        connection.rollback()
        connection.close()
    reused_run, reused = actions.claim_mcp_tool_call(
        database,
        provider="gmail",
        tool_name="search_emails",
        request=gmail_request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
        external_action_ids=[email_action],
    )
    assert (reused_run, reused) == (first_run, True)
    gmail_manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "gmail",
        "tool_name": "search_emails",
        "request_json": gmail_request,
        "request_sha256": actions.sha256_text(actions.canonical_json(gmail_request)),
        "preview_output_id": output_id,
        "preview_output_sha256": output_sha,
        "preview_sha256": preview_sha,
        "external_action_ids": [email_action],
    }
    connection = connect(database)
    try:
        for index in range(1, actions.GMAIL_MCP_CALL_BUDGET):
            begin_run(
                connection,
                run_key=f"m10-gmail-budget-{index}",
                workflow_key="m10:external:gmail:2026-08-18",
                dedupe_key=f"m10-gmail-budget-{index}",
                skill_name="gmail-sender",
                operation="mcp_tool_call",
                trigger_kind="manual",
                input_manifest=gmail_manifest,
            )
    finally:
        connection.close()
    second_marker = str(seeded["preview"]["emails"][1]["marker"])
    second_spec = actions.action_spec(
        "gmail", "gmail_send", "email", f"m10:email:{second_marker}"
    )
    second_approval = actions.authorize_action(
        database,
        spec=second_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        source_ref=f"m10-preview:{preview_sha}",
        preview_sha256=preview_sha,
    )
    second_action = actions.prepare_action(
        database,
        spec=second_spec,
        source_output_id=output_id,
        source_output_sha256=output_sha,
        approval_id=second_approval,
        request=dict(seeded["requests"][1]),
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="m10_mcp_tool_call_budget_exceeded"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="gmail",
            tool_name="search_emails",
            request={
                "query": str(seeded["preview"]["emails"][1]["verification_query"]),
                "maxResults": 10,
            },
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
            external_action_ids=[second_action],
        )

    garmin_request: dict[str, Any] = {}
    garmin_run, reused = actions.claim_mcp_tool_call(
        database,
        provider="garmin",
        tool_name="get_workouts",
        request=garmin_request,
        preview_output_id=output_id,
        preview_output_sha256=output_sha,
    )
    assert reused is False
    actions.finish_mcp_tool_call(database, garmin_run, status="succeeded")
    garmin_manifest = {
        "m10_role": "m10_external_mcp_call_v1",
        "provider": "garmin",
        "tool_name": "get_workouts",
        "request_json": garmin_request,
        "request_sha256": actions.sha256_text(actions.canonical_json(garmin_request)),
        "preview_output_id": output_id,
        "preview_output_sha256": output_sha,
        "preview_sha256": preview_sha,
        "external_action_ids": [],
    }
    connection = connect(database)
    try:
        for index in range(1, actions.GARMIN_MCP_CALL_BUDGET):
            begin_run(
                connection,
                run_key=f"m10-garmin-budget-{index}",
                workflow_key="m10:external:garmin:2026-08-18",
                dedupe_key=f"m10-garmin-budget-{index}",
                skill_name="garmin-training-sender",
                operation="mcp_tool_call",
                trigger_kind="manual",
                input_manifest=garmin_manifest,
            )
    finally:
        connection.close()
    with pytest.raises(
        sqlite3.IntegrityError, match="m10_mcp_tool_call_budget_exceeded"
    ):
        actions.claim_mcp_tool_call(
            database,
            provider="garmin",
            tool_name="get_scheduled_workouts",
            request={"start_date": "2026-08-19", "end_date": "2026-08-25"},
            preview_output_id=output_id,
            preview_output_sha256=output_sha,
        )
