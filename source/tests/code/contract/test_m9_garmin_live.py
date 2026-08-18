from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts import canary_evidence
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.state import connect, init_database

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolated_canary_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canary_evidence, "PUBLIC_ROOT_PARENT", tmp_path.parent)


def _module(name: str):
    path = ROOT / f"skills/garmin-sync/scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(f"m9_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if name == "live_sync":
        setattr(
            module,
            "_production_assert_formal_source_evidence",
            getattr(module, "_assert_formal_source_evidence"),
        )
        setattr(
            module,
            "_assert_formal_source_evidence",
            lambda *_args, **_kwargs: None,
        )
    if name == "complete_live_daily":
        production_load = getattr(module, "_load")

        def test_load(relative: str, module_name: str):
            loaded = production_load(relative, module_name)
            if relative.endswith("garmin-sync/scripts/live_sync.py"):
                loaded._assert_formal_source_evidence = lambda *_args, **_kwargs: None
            return loaded

        setattr(module, "_load", test_load)
    return module


def _coach_module(name: str):
    path = ROOT / f"skills/training-coach/scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(f"m9_coach_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shared_module(name: str):
    path = ROOT / f"skills/_shared/scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(f"m9_shared_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _install_terminal_ai_attempt(
    source: Path, context: dict[str, Any], payload: dict[str, Any]
) -> tuple[Path, Path]:
    """Install the closed 2-failed, 3-failed, canary, 4-success chain."""
    runtime = _coach_module("codex_attempt_runtime")
    run_root = source.parent / "run/daily-20260817"
    run_root.mkdir(parents=True, mode=0o700)
    for directory in (source.parent / "run", run_root):
        directory.chmod(0o700)
    context_raw = (
        json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    )
    prompt_raw = b"synthetic frozen daily prompt\n"
    for path, raw in (
        (run_root / "context.json", context_raw),
        (run_root / "prompt.txt", prompt_raw),
    ):
        path.write_bytes(raw)
        path.chmod(0o600)

    prior = run_root / "ai-attempt-2"
    prior.mkdir(mode=0o700)
    events_raw = b'{"type":"error","message":"synthetic prior failure"}\n'
    stderr_raw = b"synthetic prior stderr\n"
    for name, raw in (("events.jsonl", events_raw), ("stderr.log", stderr_raw)):
        path = prior / name
        path.write_bytes(raw)
        path.chmod(0o600)
    wire_raw = runtime.SCHEMA_PATH.read_bytes()
    business_raw = runtime.BUSINESS_SCHEMA_PATH.read_bytes()
    prior_receipt = {
        "schema_version": "codex_ai_attempt_v1",
        "attempt": 2,
        "status": "failed",
        "error_code": "ai_codex_exit_nonzero",
        "error_category": "unknown_non_retryable",
        "exit_code": 1,
        "started_at_utc": "2026-08-17T00:00:00Z",
        "finished_at_utc": "2026-08-17T00:00:01Z",
        "elapsed_milliseconds": 1000,
        "timeout_seconds": 180,
        "max_log_bytes": 2097152,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "json_events": True,
            "output_schema": "daily_ai_result_v1",
        },
        "context_sha256": _sha_bytes(context_raw),
        "prompt_sha256": _sha_bytes(prompt_raw),
        "schema_sha256": _sha_bytes(business_raw),
        "events_captured_bytes": len(events_raw),
        "events_sha256": _sha_bytes(events_raw),
        "stderr_captured_bytes": len(stderr_raw),
        "stderr_sha256": _sha_bytes(stderr_raw),
        "result_bytes": None,
        "result_sha256": None,
        "provider_calls": 0,
        "external_actions": 0,
    }
    prior_raw = (
        json.dumps(prior_receipt, ensure_ascii=False, sort_keys=True, indent=2).encode()
        + b"\n"
    )
    (prior / "attempt-receipt.json").write_bytes(prior_raw)
    (prior / "attempt-receipt.json").chmod(0o600)

    attempt3_pending = run_root / runtime.ATTEMPT3_POLICY.pending_directory
    attempt3_pending.mkdir(mode=0o700)
    intent3 = runtime._intent(
        policy=runtime.ATTEMPT3_POLICY,
        timeout_seconds=180,
        max_log_bytes=2097152,
        prior_receipt_sha=_sha_bytes(prior_raw),
        context_sha=_sha_bytes(context_raw),
        prompt_sha=_sha_bytes(prompt_raw),
        wire_schema_sha=_sha_bytes(wire_raw),
        business_schema_sha=_sha_bytes(business_raw),
    )
    intent3_raw = runtime._json_bytes(intent3)
    runtime._atomic_owner_write(attempt3_pending / "attempt-intent.json", intent3_raw)
    attempt3_events = b'{"type":"error","message":"synthetic attempt 3 failure"}\n'
    attempt3_stderr = b"synthetic attempt 3 stderr\n"
    for name, raw in (
        ("events.jsonl", attempt3_events),
        ("stderr.log", attempt3_stderr),
    ):
        path = attempt3_pending / name
        path.write_bytes(raw)
        path.chmod(0o600)
    receipt3 = runtime._receipt(
        policy=runtime.ATTEMPT3_POLICY,
        intent_raw=intent3_raw,
        status="failed",
        error_code="ai_codex_error_event",
        error_category="schema_non_retryable",
        return_code=1,
        started_at="2026-08-17T00:00:02Z",
        elapsed_seconds=1,
        context_sha=_sha_bytes(context_raw),
        prompt_sha=_sha_bytes(prompt_raw),
        schema_sha=_sha_bytes(wire_raw),
        events_raw=attempt3_events,
        stderr_raw=attempt3_stderr,
        result_raw=None,
        timeout_seconds=180,
        max_log_bytes=2097152,
    )
    runtime._publish_terminal(
        attempt3_pending,
        run_root / runtime.ATTEMPT3_POLICY.attempt_directory,
        receipt3,
        None,
    )
    receipt3_raw = (run_root / "ai-attempt-3/attempt-receipt.json").read_bytes()

    wire_payload = {
        **payload,
        "error_code": payload.get("error_code"),
        "today_course": payload.get("today_course", {}),
    }
    result_raw = (
        json.dumps(wire_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )

    canary = (
        source.parents[1]
        / f"trainlab-m9-schema-canary-r07.{source.parent.name}"
        / "schema-canary-v2"
    )
    canary.mkdir(parents=True, mode=0o700)
    canary.parent.chmod(0o700)
    canary_prompt = b"public synthetic canary\n"
    canary_events = b'{"type":"turn.completed"}\n'
    canary_stderr = b"NO_STDERR\n"
    for name, raw in (
        ("prompt.txt", canary_prompt),
        ("events.jsonl", canary_events),
        ("stderr.log", canary_stderr),
        ("canary-result.json", result_raw),
    ):
        path = canary / name
        path.write_bytes(raw)
        path.chmod(0o600)
    wire_v2_raw = runtime.SCHEMA_V2_PATH.read_bytes()
    canary_receipt = {
        "schema_version": "codex_schema_canary_v1",
        "status": "succeeded",
        "error_code": None,
        "input_class": "public_synthetic",
        "codex_version": "codex-cli synthetic",
        "codex_executable_sha256": "f" * 64,
        "timeout_seconds": 180,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "json_events": True,
            "output_schema": "daily_ai_result_codex_v2",
        },
        "wire_schema_sha256": _sha_bytes(wire_v2_raw),
        "prompt_sha256": _sha_bytes(canary_prompt),
        "events_captured_bytes": len(canary_events),
        "events_sha256": _sha_bytes(canary_events),
        "stderr_captured_bytes": len(canary_stderr),
        "stderr_sha256": _sha_bytes(canary_stderr),
        "result_bytes": len(result_raw),
        "result_sha256": _sha_bytes(result_raw),
        "provider_calls": 0,
        "external_actions": 0,
    }
    canary_receipt_path = canary / "canary-receipt.json"
    canary_receipt_path.write_bytes(runtime._json_bytes(canary_receipt))
    canary_receipt_path.chmod(0o600)

    attempt4_pending = run_root / runtime.ATTEMPT4_POLICY.pending_directory
    attempt4_pending.mkdir(mode=0o700)
    intent4 = runtime._intent(
        policy=runtime.ATTEMPT4_POLICY,
        timeout_seconds=180,
        max_log_bytes=2097152,
        prior_receipt_sha=_sha_bytes(receipt3_raw),
        canary_receipt_sha=_sha_bytes(canary_receipt_path.read_bytes()),
        context_sha=_sha_bytes(context_raw),
        prompt_sha=_sha_bytes(prompt_raw),
        wire_schema_sha=_sha_bytes(wire_v2_raw),
        business_schema_sha=_sha_bytes(business_raw),
    )
    intent4_raw = runtime._json_bytes(intent4)
    runtime._atomic_owner_write(attempt4_pending / "attempt-intent.json", intent4_raw)
    current_events = b'{"type":"turn.completed"}\n'
    current_stderr = b"NO_STDERR\n"
    for name, raw in (
        ("events.jsonl", current_events),
        ("stderr.log", current_stderr),
    ):
        path = attempt4_pending / name
        path.write_bytes(raw)
        path.chmod(0o600)
    receipt4 = runtime._receipt(
        policy=runtime.ATTEMPT4_POLICY,
        intent_raw=intent4_raw,
        status="succeeded",
        error_code=None,
        error_category=None,
        return_code=0,
        started_at="2026-08-17T00:00:02Z",
        elapsed_seconds=1,
        context_sha=_sha_bytes(context_raw),
        prompt_sha=_sha_bytes(prompt_raw),
        schema_sha=_sha_bytes(wire_v2_raw),
        events_raw=current_events,
        stderr_raw=current_stderr,
        result_raw=result_raw,
        timeout_seconds=180,
        max_log_bytes=2097152,
    )
    runtime._publish_terminal(
        attempt4_pending,
        run_root / runtime.ATTEMPT4_POLICY.attempt_directory,
        receipt4,
        result_raw,
    )
    return run_root, canary_receipt_path


def _token_dir(root: Path) -> Path:
    tokens = root / "tokens"
    tokens.mkdir(mode=0o700, parents=True)
    token = tokens / "oauth.json"
    token.write_text("cached-token", encoding="utf-8")
    token.chmod(0o600)
    return tokens


def test_live_sync_cli_loads_from_repository_root_without_pythonpath() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/garmin-sync/scripts/live_sync.py"),
            "--help",
        ],
        cwd=ROOT.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--source-root" in result.stdout
    assert "--database" in result.stdout
    assert "--token-dir" in result.stdout


@pytest.mark.parametrize(
    ("relative_script", "required_flag"),
    [
        ("skills/training-coach/scripts/create_ai_prompt.py", "--context-json"),
        ("skills/garmin-sync/scripts/complete_live_daily.py", "--run-root"),
    ],
)
def test_daily_offline_clis_load_from_repository_root_without_pythonpath(
    relative_script: str, required_flag: str
) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / relative_script), "--help"],
        cwd=ROOT.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert required_flag in result.stdout


def _seal_source(source: Path) -> None:
    synthetic_fingerprint = {
        "schema_version": "formal_state_fingerprint_v1",
        "entries": [],
        "entry_count": 0,
        "raw_entry_count": 0,
        "sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    builder = _shared_module("build_m8_candidate")
    candidate_seed = builder._candidate_seed_manifest(source)
    builder._candidate_seed_manifest = lambda _path: candidate_seed
    builder._seal_candidate_scope(
        source.parent,
        source,
        ROOT,
        synthetic_fingerprint,
        synthetic_fingerprint,
    )


def _source(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    source = tmp_path / "source"
    for path in (
        source,
        source / "state",
        source / "state/raw",
        source / "state/raw/garmin",
        source / "state/raw/garmin/health",
        source / "state/raw/garmin/activities",
    ):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = source / "state/trainlab.db"
    init_database(database)
    goal = source / "goal.md"
    goal.write_text("# 我的训练目标\n\n- 合成测试目标。\n", encoding="utf-8")
    goal.chmod(0o600)
    _seal_source(source)
    return source, database


def _payloads() -> dict[str, bytes]:
    return {
        "get_rhr_day": json.dumps({"restingHeartRate": 52}).encode(),
        "get_hrv_data": json.dumps(
            {"hrvSummary": {"lastNightAvg": 56, "weeklyAvg": 54}}
        ).encode(),
        "get_heart_rates": json.dumps(
            {"heartRateValues": [[1, 50], [2, 60], [3, 55]]}
        ).encode(),
        "get_vo2max_trend": json.dumps({"records": []}).encode(),
        "get_weigh_ins": json.dumps({"dailyWeightSummaries": []}).encode(),
        "get_sleep_data": json.dumps(
            {
                "dailySleepDTO": {
                    "sleepStartTimestampGMT": "2026-08-16T16:00:00Z",
                    "sleepEndTimestampGMT": "2026-08-16T23:00:00Z",
                    "sleepTimeSeconds": 25200,
                }
            }
        ).encode(),
        "get_activities_by_date": json.dumps(
            {
                "count": 0,
                "page": 0,
                "page_size": 10,
                "has_more": False,
                "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
                "activities": [],
            }
        ).encode(),
    }


class FakeClient:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        tools: set[str] | None = None,
        token_to_change: Path | None = None,
        fail_tool: str | None = None,
        error_tool: str | None = None,
    ) -> None:
        module = _module("live_sync")
        self.payloads = payloads
        self.tools = tools or set(module.ALLOWED_TOOLS)
        self.token_to_change = token_to_change
        self.fail_tool = fail_tool
        self.error_tool = error_tool
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.entries = 0

    async def __aenter__(self):
        self.entries += 1
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self.token_to_change is not None:
            self.token_to_change.write_text("changed", encoding="utf-8")

    async def list_tools(self) -> set[str]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        module = _module("live_sync")
        self.calls.append((name, arguments))
        if self.fail_tool == name:
            raise RuntimeError("fake_provider_error")
        if self.error_tool == name:
            return module.ToolResponse(b"provider-declared-error", True)
        if name == "download_activity_file":
            output = Path(arguments["output_dir"])
            output.mkdir(mode=0o700, parents=True, exist_ok=True)
            fit = output / f"{arguments['activity_id']}.fit"
            fit.write_bytes(b"synthetic-fit")
            fit.chmod(0o600)
            payload = json.dumps(
                {
                    "activity_id": int(arguments["activity_id"]),
                    "format": "fit",
                    "file_path": str(fit.resolve()),
                    "size_bytes": fit.stat().st_size,
                }
            ).encode()
            return module.ToolResponse(payload, False)
        return module.ToolResponse(self.payloads[name], False)


class SlowClient(FakeClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]):
        await asyncio.sleep(0.05)
        return await super().call_tool(name, arguments)


class InitializationFailureClient(FakeClient):
    async def __aenter__(self):
        self.entries += 1
        raise RuntimeError("profile initialization failed")


class UnsafeFitClient(FakeClient):
    def __init__(self, payloads: dict[str, bytes], mode: str) -> None:
        super().__init__(payloads)
        self.mode = mode

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        if name != "download_activity_file":
            return await super().call_tool(name, arguments)
        self.calls.append((name, arguments))
        module = _module("live_sync")
        output = Path(arguments["output_dir"])
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        expected = output / f"{arguments['activity_id']}.fit"
        target = expected
        if self.mode == "wrong_path":
            target = output.parent / "outside.fit"
            target.write_bytes(b"fit")
        elif self.mode == "hardlink":
            origin = output / "origin.fit"
            origin.write_bytes(b"fit")
            os.link(origin, expected)
        else:
            expected.write_bytes(b"")
        target.chmod(0o600)
        return module.ToolResponse(
            json.dumps(
                {
                    "activity_id": int(arguments["activity_id"]),
                    "format": "fit",
                    "file_path": str(target.resolve()),
                    "size_bytes": target.stat().st_size,
                }
            ).encode(),
            False,
        )


def test_frozen_request_and_server_command_are_exact() -> None:
    live = _module("live_sync")
    client = _module("mcp_stdio")
    request = live.approved_request()
    assert not validate_payload(request, "garmin_live_request_v1")
    changed = json.loads(json.dumps(request))
    changed["run_date"] = "2026-08-18"
    with pytest.raises(ValueError, match="garmin_live_request_invalid"):
        live.validate_request(changed)
    command = client.server_command()
    assert "--offline" in command["args"]
    assert "3610be6feed93088d85b0f35aba9d7d07c2505a7" in " ".join(command["args"])
    assert command["args"][-2] == "python"
    assert command["args"][-1].endswith("mcp_server_guard.py")
    assert Path(command["args"][-1]).is_relative_to(ROOT)
    assert Path(command["args"][4]).is_relative_to(ROOT)
    assert command["environment"]["GARMIN_ENABLED_TOOLS"].split(",") == sorted(
        live.ALLOWED_TOOLS
    )
    forbidden = {
        "GARMIN_EMAIL",
        "GARMIN_EMAIL_FILE",
        "GARMIN_PASSWORD",
        "GARMIN_PASSWORD_FILE",
        "GARMINTOKENS_BASE64",
    }
    assert not forbidden.intersection(command["environment"])


def test_zero_activity_sync_persists_distinct_mcp_captures_and_reuses(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    fake = FakeClient(_payloads())
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: fake)
    )
    assert result["status"] == "succeeded"
    assert result["mcp_tool_calls"] == 7
    assert result["provider_entries"] == 8
    assert result["inventory_complete"] is True
    assert result["inventory_count"] == 0
    assert result["external_actions"] == 0
    assert not validate_payload(result, "garmin_live_sync_receipt_v1")
    assert len(fake.calls) == 7
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT provider,relative_path FROM raw_files ORDER BY id"
        ).fetchall()
        action_count = connection.execute(
            "SELECT COUNT(*) FROM external_actions"
        ).fetchone()[0]
    finally:
        connection.close()
    assert len(rows) == 7
    assert all(row[0] == "garmin_mcp" for row in rows)
    assert all("mcp_capture" in row[1] for row in rows)
    assert action_count == 0

    context = _coach_module("build_context").build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result["receipt_output_id"],
    )
    assert context["status"] == "ready"
    assert context["activities"] == []
    assert context["live_sync"]["inventory_count"] == 0
    assert any(
        item["resource"] == "rhr"
        and item["metrics"].get("resting_heart_rate_bpm") == 52
        for item in context["health"]
    )

    second = FakeClient(_payloads())
    reused = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: second)
    )
    assert reused["status"] == "reused"
    assert reused["mcp_tool_calls"] == 0
    assert reused["provider_entries"] == 0
    assert reused["receipt_output_id"] == result["receipt_output_id"]
    assert not validate_payload(reused, "garmin_live_sync_receipt_v1")
    assert second.entries == 0


def test_candidate_scope_is_required_before_database_or_provider(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    (source.parent / "formal-state-fingerprint.json").unlink()
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path),
                lambda: fake,
            )
        )
    assert fake.entries == 0


def test_candidate_root_must_be_owner_only_before_provider(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    source.parent.chmod(0o755)
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path),
                lambda: fake,
            )
        )
    assert fake.entries == 0


def test_two_field_candidate_marker_is_rejected_before_provider(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    marker = source.parent / "formal-state-fingerprint.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": "m8_snapshot_receipt_v1",
                "formal_state_unchanged": True,
            }
        ),
        encoding="utf-8",
    )
    marker.chmod(0o600)
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path),
                lambda: fake,
            )
        )
    assert fake.entries == 0


def test_candidate_signed_from_arbitrary_source_is_rejected_before_provider(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    builder = _shared_module("build_m8_candidate")
    source = tmp_path / "arbitrary/source"
    database = source / "state/trainlab.db"
    init_database(database)
    goal = source / "goal.md"
    goal.write_text("# 合成目标\n", encoding="utf-8")
    goal.chmod(0o600)
    fingerprint = {
        "schema_version": "formal_state_fingerprint_v1",
        "entries": [],
        "entry_count": 0,
        "raw_entry_count": 0,
        "sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    builder._seal_candidate_scope(
        source.parent,
        source,
        source,
        fingerprint,
        fingerprint,
    )
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path),
                lambda: fake,
            )
        )
    assert fake.entries == 0


def test_candidate_builder_rejects_destination_inside_git_repository() -> None:
    builder = _shared_module("build_m8_candidate")
    forbidden = ROOT.parent / ".m9-forbidden-candidate"
    assert not forbidden.exists()
    with pytest.raises(ValueError, match="candidate_must_be_outside_repository"):
        builder._build_unlocked(ROOT, forbidden)
    assert not forbidden.exists()


def test_formal_source_evidence_is_recomputed_and_bound_to_seed(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    builder = _shared_module("build_m8_candidate")
    formal = tmp_path / "formal-source"
    database = formal / "state/trainlab.db"
    init_database(database)
    lock = formal / "state/trainlab.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    fingerprint = builder._formal_state_fingerprint(formal)
    seed = builder._candidate_seed_manifest(formal)
    production_check = getattr(live, "_production_assert_formal_source_evidence")
    production_check(formal, fingerprint, seed)

    forged_fingerprint = dict(fingerprint)
    forged_fingerprint["sha256"] = "0" * 64
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        production_check(formal, forged_fingerprint, seed)

    forged_seed = dict(seed)
    forged_seed["raw_count"] = int(seed["raw_count"]) + 1
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        production_check(formal, fingerprint, forged_seed)


def test_nonzero_candidate_wal_is_rejected_before_provider(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    connection = connect(database)
    try:
        live.begin_run(
            connection,
            run_key="candidate-open-wal:attempt-1",
            workflow_key="candidate:test",
            dedupe_key="candidate-open-wal",
            skill_name="garmin-sync",
            operation="index_existing_raw",
            trigger_kind="recovery",
            input_manifest={"case": "candidate-open-wal"},
        )
        wal = database.with_name(database.name + "-wal")
        assert wal.is_file() and wal.stat().st_size > 0
        fake = FakeClient(_payloads())
        with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
            asyncio.run(
                live.collect(
                    live.approved_request(),
                    source,
                    database,
                    _token_dir(tmp_path),
                    lambda: fake,
                )
            )
        assert fake.entries == 0
    finally:
        connection.close()


def test_raw_added_after_candidate_seal_requires_live_sync_provenance(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    connection = connect(database)
    seed = live.begin_run(
        connection,
        run_key="post-seal-injection:attempt-1",
        workflow_key="seed:post-seal-injection",
        dedupe_key=hashlib.sha256(b"post-seal-injection").hexdigest(),
        skill_name="garmin-sync",
        operation="index_existing_raw",
        trigger_kind="manual",
        input_manifest={"fixture": "post-seal-injection"},
        target_from_date="2026-08-16",
        target_through_date="2026-08-16",
    )
    injected = b'{"restingHeartRate":99}'
    relative = "garmin/health/20260816-rhr-post-seal.json"
    path = source / "state/raw" / relative
    path.write_bytes(injected)
    path.chmod(0o600)
    live._insert_raw(
        connection,
        run_id=seed,
        provider="garmin",
        data_class="health",
        resource="rhr",
        logical_key="garmin:rhr:post-seal",
        data_date="2026-08-16",
        relative_path=relative,
        file_format="json",
        byte_size=len(injected),
        digest=hashlib.sha256(injected).hexdigest(),
    )
    live.finish_run(connection, seed, status="succeeded")
    connection.close()
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path),
                lambda: fake,
            )
        )
    assert fake.entries == 0


def test_candidate_database_symlink_cannot_escape_candidate(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path / "candidate")
    outside = tmp_path / "outside.db"
    init_database(outside)
    outside_before = outside.read_bytes()
    database.unlink()
    database.symlink_to(outside)
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path / "candidate"),
                lambda: fake,
            )
        )
    assert fake.entries == 0
    assert outside.read_bytes() == outside_before


def test_candidate_raw_symlink_cannot_escape_candidate(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path / "candidate")
    health = source / "state/raw/garmin/health"
    outside = tmp_path / "outside-health"
    outside.mkdir(mode=0o700)
    health.rmdir()
    health.symlink_to(outside, target_is_directory=True)
    fake = FakeClient(_payloads())
    with pytest.raises(live.LiveSyncError, match="candidate_scope_required"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path / "candidate"),
                lambda: fake,
            )
        )
    assert fake.entries == 0
    assert list(outside.iterdir()) == []


def test_mcp_guard_disables_credentials_refresh_and_library_retry() -> None:
    guard = _module("mcp_server_guard")

    class AuthenticationError(RuntimeError):
        pass

    class Garmin:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.kwargs = kwargs

        def resume_login(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("unpatched")

        def get_training_status(self, *_args: object) -> dict[str, Any]:
            raise AssertionError("unpatched")

        def get_user_profile(self) -> dict[str, Any]:
            raise AssertionError("unpatched")

    class Client:
        def _refresh_session(self) -> None:
            raise AssertionError("unpatched")

        def _refresh_di_token(self) -> None:
            raise AssertionError("unpatched")

    garmin_module = type(
        "GarminModule",
        (),
        {"Garmin": Garmin, "GarminConnectAuthenticationError": AuthenticationError},
    )
    client_module = type("ClientModule", (), {"Client": Client})
    guard.install_guard(garmin_module, client_module)
    instance = Garmin(is_cn=True)
    assert instance.kwargs["retry_attempts"] == 0
    with pytest.raises(AuthenticationError, match="credential_login_disabled"):
        Garmin(email="forbidden", password="forbidden")
    with pytest.raises(AuthenticationError, match="cached_token_refresh_disabled"):
        Client()._refresh_session()
    with pytest.raises(AuthenticationError, match="cached_token_refresh_disabled"):
        Client()._refresh_di_token()
    with pytest.raises(AuthenticationError, match="interactive_auth_disabled"):
        instance.resume_login({}, "forbidden")
    assert instance.get_training_status("2026-08-16") == {}
    assert instance.get_user_profile() == {}


def test_mcp_guard_initialization_uses_one_profile_entry_without_settings() -> None:
    guard = _module("mcp_server_guard")

    class AuthenticationError(RuntimeError):
        pass

    class Garmin:
        client: Any
        display_name: str | None
        full_name: str
        unit_system: str | None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.username = "cached-user"
            self.garmin_connect_user_settings_url = "/settings"

        def _load_profile_and_settings(self) -> None:
            raise AssertionError("unpatched")

    class Client:
        def _refresh_session(self) -> None:
            raise AssertionError("unpatched")

        def _refresh_di_token(self) -> None:
            raise AssertionError("unpatched")

    garmin_module = type(
        "GarminModule",
        (),
        {"Garmin": Garmin, "GarminConnectAuthenticationError": AuthenticationError},
    )
    client_module = type("ClientModule", (), {"Client": Client})
    guard.install_guard(garmin_module, client_module)

    calls: list[str] = []

    class ProfileClient:
        def connectapi(self, path: str) -> dict[str, Any]:
            calls.append(path)
            if path != "/userprofile-service/socialProfile":
                raise AssertionError("settings or other initialization is forbidden")
            return {"displayName": "provider-user", "fullName": "Provider User"}

    instance = Garmin()
    instance.client = ProfileClient()
    instance._load_profile_and_settings()
    assert calls == ["/userprofile-service/socialProfile"]
    assert instance.display_name == "provider-user"
    assert instance.full_name == "Provider User"
    assert instance.unit_system is None

    failed_calls: list[str] = []

    class FailingClient:
        def connectapi(self, path: str) -> dict[str, Any]:
            failed_calls.append(path)
            raise RuntimeError("provider failure")

    failed = Garmin()
    failed.client = FailingClient()
    with pytest.raises(AuthenticationError, match="social profile"):
        failed._load_profile_and_settings()
    assert failed_calls == ["/userprofile-service/socialProfile"]


def test_real_mcp_hrv_field_names_are_preserved() -> None:
    metrics = _coach_module("parse_raw")._json_metrics(
        {"last_night_avg_hrv_ms": 56, "weekly_avg_hrv_ms": 54}, "hrv"
    )
    assert metrics["last_night_average"] == 56
    assert metrics["weekly_average"] == 54


def test_initialization_failure_conservatively_records_profile_entry(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    client = InitializationFailureClient(_payloads())
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: client,
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_mcp_session_failed"
    assert result["provider_entries"] == 1
    assert result["mcp_tool_calls"] == 0
    assert client.entries == 1


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("has_more", "activity_inventory_incomplete"),
        ("wrong_date", "activity_inventory_date_mismatch"),
        ("wrong_page", "activity_inventory_page_mismatch"),
        ("wrong_page_size", "activity_inventory_page_mismatch"),
        ("too_many", "activity_budget_exceeded"),
    ],
)
def test_inventory_scope_and_activity_budget_fail_closed(
    tmp_path: Path, mutation: str, error_code: str
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    payloads = _payloads()
    activities = [
        {
            "id": 1000 + index,
            "type": "running",
            "start_time": "2026-08-16T08:00:00",
        }
        for index in range(3 if mutation == "too_many" else 1)
    ]
    inventory = {
        "count": len(activities),
        "page": 1 if mutation == "wrong_page" else 0,
        "page_size": 200 if mutation == "wrong_page_size" else 10,
        "has_more": mutation == "has_more",
        "date_range": {
            "start": "2026-08-15" if mutation == "wrong_date" else "2026-08-16",
            "end": "2026-08-16",
        },
        "activities": activities,
    }
    payloads["get_activities_by_date"] = json.dumps(inventory).encode()
    fake = FakeClient(payloads)
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: fake)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == error_code
    assert not any(name == "download_activity_file" for name, _ in fake.calls)


def test_duplicate_activity_id_is_rejected_before_fit_download(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    payloads = _payloads()
    activity = {
        "id": 101,
        "type": "running",
        "start_time": "2026-08-16T08:00:00",
    }
    payloads["get_activities_by_date"] = json.dumps(
        {
            "count": 2,
            "page": 0,
            "page_size": 10,
            "has_more": False,
            "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
            "activities": [activity, dict(activity)],
        }
    ).encode()
    fake = FakeClient(payloads)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: fake,
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "activity_inventory_duplicate"
    assert not any(name == "download_activity_file" for name, _ in fake.calls)


def test_malicious_extra_tool_and_provider_error_do_not_retry(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    extra = FakeClient(_payloads(), tools=set(live.ALLOWED_TOOLS) | {"delete_workout"})
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: extra)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "mcp_tool_allowlist_mismatch"
    assert extra.calls == []

    source2, database2 = _source(tmp_path / "second")
    tokens2 = _token_dir(tmp_path / "second")
    failing = FakeClient(_payloads(), fail_tool="get_rhr_day")
    failed = asyncio.run(
        live.collect(
            live.approved_request(), source2, database2, tokens2, lambda: failing
        )
    )
    assert failed["status"] == "blocked"
    assert failed["error_code"] == "garmin_mcp_call_failed"
    assert [name for name, _ in failing.calls].count("get_rhr_day") == 1


def test_token_missing_or_changed_stops_safely(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    missing = tmp_path / "missing"
    fake = FakeClient(_payloads())
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, missing, lambda: fake)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "cached_token_unavailable"
    assert fake.entries == 0

    source2, database2 = _source(tmp_path / "changed")
    tokens = _token_dir(tmp_path / "changed")
    token_file = next(tokens.iterdir())
    changed = FakeClient(_payloads(), token_to_change=token_file)
    result2 = asyncio.run(
        live.collect(
            live.approved_request(), source2, database2, tokens, lambda: changed
        )
    )
    assert result2["status"] == "blocked"
    assert result2["error_code"] == "cached_token_changed"
    assert result2["token_unchanged"] is False
    serialized = json.dumps(result2)
    assert hashlib.sha256(b"cached-token").hexdigest() not in serialized
    assert hashlib.sha256(b"changed").hexdigest() not in serialized

    retry = FakeClient(_payloads())
    repeated = asyncio.run(
        live.collect(live.approved_request(), source2, database2, tokens, lambda: retry)
    )
    assert repeated["status"] == "blocked"
    assert repeated["error_code"] == "garmin_live_authorization_consumed"
    assert repeated["provider_entries"] == 0
    assert retry.entries == 0


def test_ephemeral_token_shadow_detects_any_write_without_touching_original(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    original = next(tokens.iterdir()).read_bytes()
    used_shadow: list[Path] = []

    def factory(shadow: Path, _download: Path) -> FakeClient:
        used_shadow.append(shadow)
        token = next(shadow.iterdir())
        token.chmod(0o600)
        return FakeClient(_payloads(), token_to_change=token)

    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, factory)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "cached_token_refresh_attempted"
    assert next(tokens.iterdir()).read_bytes() == original
    assert used_shadow and not used_shadow[0].exists()


def test_existing_same_capture_must_already_be_owner_only(tmp_path: Path) -> None:
    live = _module("live_sync")
    destination = tmp_path / "capture.json"
    destination.write_bytes(b"{}")
    destination.chmod(0o644)
    with pytest.raises(live.LiveSyncError, match="capture_path_conflict"):
        live._write_atomic(destination, b"{}")
    assert destination.stat().st_mode & 0o777 == 0o644


def test_mcp_error_response_records_actual_digest_and_size(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    fake = FakeClient(_payloads(), error_tool="get_rhr_day")
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: fake,
        )
    )
    assert result["status"] == "blocked"
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT content_json FROM skill_outputs "
            "WHERE schema_name='garmin_mcp_capture_v1' ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    capture = json.loads(str(row[0]))
    assert capture["response_bytes"] == len(b"provider-declared-error")
    assert (
        capture["response_sha256"]
        == hashlib.sha256(b"provider-declared-error").hexdigest()
    )


def test_interrupted_attempt_consumes_one_time_authorization(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    request = live.approved_request()
    request_sha = live.sha256_text(live.canonical_json(request))
    manifest = {"request_sha256": request_sha, "request": request}
    dedupe = live.sha256_text(live.canonical_json(manifest))
    connection = connect(database)
    live.begin_run(
        connection,
        run_key=f"{dedupe}:attempt-1",
        workflow_key=live.WORKFLOW_KEY,
        dedupe_key=dedupe,
        skill_name="garmin-sync",
        operation="daily_sync",
        trigger_kind="manual",
        input_manifest=manifest,
        target_from_date=live.HEALTH_DATE,
        target_through_date=live.SLEEP_DATE,
    )
    connection.close()
    fake = FakeClient(_payloads())
    result = asyncio.run(
        live.collect(request, source, database, _token_dir(tmp_path), lambda: fake)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_authorization_consumed"
    assert result["provider_entries"] == 0
    assert fake.entries == 0


def test_running_run_receipt_is_not_reused_as_success(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    request = live.approved_request()
    request_sha = live.sha256_text(live.canonical_json(request))
    manifest = {"request_sha256": request_sha, "request": request}
    dedupe = live.sha256_text(live.canonical_json(manifest))
    connection = connect(database)
    run_id = live.begin_run(
        connection,
        run_key=f"{dedupe}:attempt-1",
        workflow_key=live.WORKFLOW_KEY,
        dedupe_key=dedupe,
        skill_name="garmin-sync",
        operation="daily_sync",
        trigger_kind="manual",
        input_manifest=manifest,
        target_from_date=live.HEALTH_DATE,
        target_through_date=live.SLEEP_DATE,
    )
    incomplete = live._consumed_authorization(None, request_sha)
    incomplete.pop("error_code")
    incomplete["status"] = "succeeded"
    incomplete["inventory_complete"] = True
    live.append_output(
        connection,
        skill_run_id=run_id,
        output_kind="sync_summary",
        logical_key=live.SYNC_LOGICAL_KEY,
        schema_name="garmin_live_sync_receipt_v1",
        schema_version="1",
        content_json=incomplete,
        content_text=live.canonical_json(incomplete),
        period_start_date=live.HEALTH_DATE,
        period_end_date=live.SLEEP_DATE,
    )
    connection.close()
    fake = FakeClient(_payloads())
    result = asyncio.run(
        live.collect(request, source, database, _token_dir(tmp_path), lambda: fake)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_authorization_consumed"
    assert result["provider_entries"] == 0
    assert fake.entries == 0


def test_running_sync_receipt_is_rejected_by_context_commit_and_finalizer(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    sync = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(_payloads()),
        )
    )
    context_builder = _coach_module("build_context")
    valid_context = context_builder.build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=sync["receipt_output_id"],
    )
    connection = connect(database)
    try:
        original = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (sync["receipt_output_id"],),
        ).fetchone()
        assert original is not None
        run_id = live.begin_run(
            connection,
            run_key="running-receipt:attempt-1",
            workflow_key=live.WORKFLOW_KEY,
            dedupe_key="running-receipt",
            skill_name="garmin-sync",
            operation="daily_sync",
            trigger_kind="manual",
            input_manifest={"case": "running-receipt"},
            target_from_date=live.HEALTH_DATE,
            target_through_date=live.SLEEP_DATE,
        )
        forged_output_id = live.append_output(
            connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="garmin-live:2026-08-17:running-receipt",
            schema_name="garmin_live_sync_receipt_v1",
            schema_version="1",
            content_json=json.loads(str(original[0])),
            content_text=str(original[0]),
            period_start_date=live.HEALTH_DATE,
            period_end_date=live.SLEEP_DATE,
        )
        forged_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (forged_output_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()

    with pytest.raises(ValueError, match="garmin_live_sync_receipt_incomplete"):
        context_builder.build_daily_context(
            database,
            source,
            __import__("datetime").date(2026, 8, 17),
            live_sync_output_id=forged_output_id,
        )

    forged_context = json.loads(json.dumps(valid_context))
    forged_context["live_sync"] = {
        **forged_context["live_sync"],
        "output_id": forged_output_id,
        "sha256": forged_sha,
    }
    rhr = next(item for item in forged_context["health"] if item["resource"] == "rhr")
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "合成日报。",
        "bounded_metrics": [
            {
                "name": "resting heart rate",
                "value": 52,
                "unit": "bpm",
                "evidence_ref": rhr["raw_file_id"],
            }
        ],
        "stop_conditions": ["出现异常症状时停止。"],
        "evidence_refs": [
            {
                "raw_file_id": rhr["raw_file_id"],
                "sha256": rhr["sha256"],
                "claim": "静息心率证据。",
            }
        ],
        "recent_trend_sha256": forged_context["recent_trend"]["sha256"],
        "provider_calls": 0,
    }
    committed = _coach_module("commit_ai_result").commit(
        payload, forged_context, database, "daily"
    )
    assert committed["status"] == "blocked"
    assert committed["error_code"] == "garmin_live_sync_receipt_incomplete"
    finalizer = _module("complete_live_daily")
    run_root, canary_receipt = _install_terminal_ai_attempt(
        source, forged_context, payload
    )
    with pytest.raises(ValueError, match="garmin_live_sync_receipt_incomplete"):
        finalizer.complete(
            source,
            database,
            run_root,
            canary_receipt,
            tmp_path / "report-running",
        )
    assert not (tmp_path / "report-running").exists()


def test_timeout_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    real_timeout = asyncio.timeout
    monkeypatch.setattr(live.asyncio, "timeout", lambda _seconds: real_timeout(0.01))
    slow = SlowClient(_payloads())
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: slow)
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_wall_budget_exceeded"
    assert result["mcp_tool_calls"] == 1
    assert result["provider_entries"] == 2
    assert slow.calls == []


@pytest.mark.parametrize("mode", ["wrong_path", "hardlink", "empty"])
def test_unsafe_fit_output_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    payloads = _payloads()
    payloads["get_activities_by_date"] = json.dumps(
        {
            "count": 1,
            "page": 0,
            "page_size": 10,
            "has_more": False,
            "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
            "activities": [
                {"id": 101, "type": "running", "start_time": "2026-08-16T08:00:00"}
            ],
        }
    ).encode()
    monkeypatch.setattr(
        live, "inspect_fit", lambda _path: live.FitInspection(True, False)
    )
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            tokens,
            lambda: UnsafeFitClient(payloads, mode),
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "fit_capture_invalid"
    connection = connect(database, read_only=True, immutable=True)
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_files WHERE file_format='fit'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_two_activity_fit_weather_budget_and_atomic_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    tokens = _token_dir(tmp_path)
    payloads = _payloads()
    payloads["get_activities_by_date"] = json.dumps(
        {
            "count": 2,
            "page": 0,
            "page_size": 10,
            "has_more": False,
            "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
            "activities": [
                {"id": 101, "type": "running", "start_time": "2026-08-16T08:00:00"},
                {"id": 102, "type": "running", "start_time": "2026-08-16T18:00:00"},
            ],
        }
    ).encode()
    payloads["get_activity_weather"] = json.dumps({"temperature": 30}).encode()
    monkeypatch.setattr(
        live, "inspect_fit", lambda _path: live.FitInspection(True, True)
    )
    fake = FakeClient(payloads)
    result = asyncio.run(
        live.collect(live.approved_request(), source, database, tokens, lambda: fake)
    )
    assert result["status"] == "succeeded"
    assert result["mcp_tool_calls"] == 11
    assert result["provider_entries"] == 12
    assert result["fit_files"] == 2
    assert result["weather_calls"] == 2
    assert result["new_files"] == 11
    fits = sorted((source / "state/raw/garmin/activities").glob("*.fit"))
    assert len(fits) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in fits)
    connection = connect(database, read_only=True, immutable=True)
    try:
        bound = connection.execute(
            "SELECT COUNT(*) FROM raw_files WHERE file_format='fit' "
            "AND activity_binding_state='bound'"
        ).fetchone()[0]
        states = connection.execute(
            "SELECT collection_state,weather_state FROM activity_inventory ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    assert bound == 2
    assert [tuple(row) for row in states] == [
        ("complete", "complete"),
        ("complete", "complete"),
    ]


def test_existing_verified_fit_is_reused_and_included_in_sync_receipt(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    connection = connect(database)
    seed = live.begin_run(
        connection,
        run_key="seed-existing-fit:attempt-1",
        workflow_key="seed:existing-fit",
        dedupe_key=hashlib.sha256(b"seed-existing-fit").hexdigest(),
        skill_name="garmin-sync",
        operation="index_existing_raw",
        trigger_kind="manual",
        input_manifest={"fixture": "existing-fit"},
        target_from_date="2026-08-16",
        target_through_date="2026-08-16",
    )
    activity_hash = live._activity_hash("101")
    now = live.utc_now()
    cursor = connection.execute(
        """INSERT INTO activity_inventory
        (provider,provider_activity_id,activity_hash,activity_hash_version,activity_date,
         expected_formats_json,collection_state,weather_state,collection_policy_version,
         first_seen_at_utc,last_seen_at_utc,discovered_by_run_id,updated_at_utc)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "garmin",
            "101",
            activity_hash,
            "provider-nul-id-sha256-v1",
            "2026-08-16",
            json.dumps(["fit"]),
            "discovered",
            "not_requested",
            "synthetic-existing-v1",
            now,
            now,
            seed,
            now,
        ),
    )
    assert cursor.lastrowid is not None
    inventory_id = int(cursor.lastrowid)
    connection.commit()
    relative = f"garmin/activities/20260816-{activity_hash}.fit"
    fit_path = source / "state/raw" / relative
    fit_path.write_bytes(b"existing-fit-evidence")
    fit_path.chmod(0o600)
    raw_id = live._insert_raw(
        connection,
        run_id=seed,
        provider="garmin",
        data_class="activity",
        resource="activity_fit",
        logical_key=f"garmin:activity:{activity_hash}:fit",
        data_date="2026-08-16",
        relative_path=relative,
        file_format="fit",
        byte_size=fit_path.stat().st_size,
        digest=hashlib.sha256(fit_path.read_bytes()).hexdigest(),
        inventory_id=inventory_id,
    )
    live.finish_run(connection, seed, status="succeeded")
    connection.close()
    _seal_source(source)

    payloads = _payloads()
    payloads["get_activities_by_date"] = json.dumps(
        {
            "count": 1,
            "page": 0,
            "page_size": 10,
            "has_more": False,
            "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
            "activities": [
                {"id": 101, "type": "running", "start_time": "2026-08-16T08:00:00"}
            ],
        }
    ).encode()
    fake = FakeClient(payloads)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: fake,
        )
    )
    assert result["status"] == "succeeded"
    assert raw_id in result["raw_file_ids"]
    assert result["activity_inventory_ids"] == [inventory_id]
    assert not any(name == "download_activity_file" for name, _ in fake.calls)


def test_live_context_uses_only_receipt_bound_latest_fit_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    connection = connect(database)
    seed = live.begin_run(
        connection,
        run_key="seed-fit-revisions:attempt-1",
        workflow_key="seed:fit-revisions",
        dedupe_key=hashlib.sha256(b"seed-fit-revisions").hexdigest(),
        skill_name="garmin-sync",
        operation="index_existing_raw",
        trigger_kind="manual",
        input_manifest={"fixture": "fit-revisions"},
        target_from_date="2026-08-16",
        target_through_date="2026-08-16",
    )
    activity_hash = live._activity_hash("101")
    now = live.utc_now()
    cursor = connection.execute(
        """INSERT INTO activity_inventory
        (provider,provider_activity_id,activity_hash,activity_hash_version,activity_date,
         expected_formats_json,collection_state,weather_state,collection_policy_version,
         first_seen_at_utc,last_seen_at_utc,discovered_by_run_id,updated_at_utc)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "garmin",
            "101",
            activity_hash,
            "provider-nul-id-sha256-v1",
            "2026-08-16",
            json.dumps(["fit"]),
            "discovered",
            "not_requested",
            "synthetic-revisions-v1",
            now,
            now,
            seed,
            now,
        ),
    )
    assert cursor.lastrowid is not None
    inventory_id = int(cursor.lastrowid)
    connection.commit()

    raw_ids: list[int] = []
    paths: list[Path] = []
    for revision, payload in (("old", b"old-fit"), ("new", b"new-fit")):
        relative = f"garmin/activities/20260816-{activity_hash}-{revision}.fit"
        fit_path = source / "state/raw" / relative
        fit_path.write_bytes(payload)
        fit_path.chmod(0o600)
        raw_ids.append(
            live._insert_raw(
                connection,
                run_id=seed,
                provider="garmin",
                data_class="activity",
                resource="activity_fit",
                logical_key=f"garmin:activity:{activity_hash}:fit",
                data_date="2026-08-16",
                relative_path=relative,
                file_format="fit",
                byte_size=len(payload),
                digest=hashlib.sha256(payload).hexdigest(),
                inventory_id=inventory_id,
            )
        )
        paths.append(fit_path)
    live.finish_run(connection, seed, status="succeeded")
    connection.close()
    _seal_source(source)
    old_raw_id, new_raw_id = raw_ids

    payloads = _payloads()
    payloads["get_activities_by_date"] = json.dumps(
        {
            "count": 1,
            "page": 0,
            "page_size": 10,
            "has_more": False,
            "date_range": {"start": "2026-08-16", "end": "2026-08-16"},
            "activities": [
                {
                    "id": 101,
                    "type": "running",
                    "start_time": "2026-08-16T08:00:00",
                }
            ],
        }
    ).encode()
    sync = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(payloads),
        )
    )
    assert new_raw_id in sync["raw_file_ids"]
    assert old_raw_id not in sync["raw_file_ids"]

    activity_module = _coach_module("activity_evidence")
    selected = activity_module._load_activity(
        database, source, inventory_id, raw_file_id=new_raw_id
    )
    assert selected[0] == paths[1]
    assert selected[1] == new_raw_id
    with pytest.raises(ValueError, match="activity_raw_receipt_mismatch"):
        activity_module._load_activity(
            database, source, inventory_id, raw_file_id=new_raw_id + 1000
        )

    observed: list[int | None] = []

    class ReceiptBoundActivity:
        @staticmethod
        def build_activity_evidence(
            _database: Path,
            _source_root: Path,
            requested_inventory_id: int,
            *,
            raw_file_id: int | None = None,
            resolution_seconds: int = 30,
        ) -> dict[str, Any]:
            observed.append(raw_file_id)
            assert requested_inventory_id == inventory_id
            assert resolution_seconds == 30
            return {
                "schema_version": "activity_overview_v1",
                "status": "ready",
                "activity_inventory_id": inventory_id,
                "raw_file_id": new_raw_id,
                "raw_sha256": hashlib.sha256(b"new-fit").hexdigest(),
                "data_date": "2026-08-16",
                "format": "fit",
                "summary": {"duration_seconds": 1800, "distance_km": 5.0},
                "sequence_resolution_seconds": 30,
                "sequence": [],
                "gps_included": False,
                "provider_calls": 0,
            }

    context_module = _coach_module("build_context")
    monkeypatch.setattr(
        context_module, "_load_activity_module", lambda: ReceiptBoundActivity
    )
    context = context_module.build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=sync["receipt_output_id"],
    )
    assert context["status"] == "ready"
    assert observed == [new_raw_id]
    assert context["activities"][0]["raw_file_id"] == new_raw_id

    hardlink = paths[1].with_name("new-fit-hardlink.fit")
    os.link(paths[1], hardlink)
    try:
        with pytest.raises(ValueError, match="activity_raw_integrity_invalid"):
            activity_module._load_activity(
                database, source, inventory_id, raw_file_id=new_raw_id
            )
    finally:
        hardlink.unlink()


def test_context_rejects_capture_changed_after_sync(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(_payloads()),
        )
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT relative_path FROM raw_files WHERE resource_kind='rhr'"
        ).fetchone()
    finally:
        connection.close()
    capture = source / "state/raw" / str(row[0])
    capture.write_text(json.dumps({"restingHeartRate": 99}), encoding="utf-8")
    capture.chmod(0o600)
    reused_client = FakeClient(_payloads())
    reused = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path / "reuse"),
            lambda: reused_client,
        )
    )
    assert reused["status"] == "blocked"
    assert reused["error_code"] == "garmin_live_reuse_integrity_failed"
    assert reused["provider_entries"] == 0
    assert reused["mcp_tool_calls"] == 0
    assert reused_client.entries == 0
    with pytest.raises(ValueError, match="raw_evidence_integrity_invalid"):
        _coach_module("build_context").build_daily_context(
            database,
            source,
            __import__("datetime").date(2026, 8, 17),
            live_sync_output_id=result["receipt_output_id"],
        )


def test_missing_optional_metrics_do_not_block_but_all_health_or_sleep_does(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    context_module = _coach_module("build_context")
    payloads = _payloads()
    payloads["get_vo2max_trend"] = b"No VO2 Max data found for 2026-08-16."
    payloads["get_weigh_ins"] = b"No weight data found for 2026-08-16."
    source, database = _source(tmp_path / "optional")
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path / "optional"),
            lambda: FakeClient(payloads),
        )
    )
    context = context_module.build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result["receipt_output_id"],
    )
    assert context["status"] == "ready"

    missing_health = _payloads()
    for tool in (
        "get_rhr_day",
        "get_hrv_data",
        "get_heart_rates",
        "get_vo2max_trend",
        "get_weigh_ins",
    ):
        missing_health[tool] = f"No data found for {tool}.".encode()
    source2, database2 = _source(tmp_path / "all-missing")
    result2 = asyncio.run(
        live.collect(
            live.approved_request(),
            source2,
            database2,
            _token_dir(tmp_path / "all-missing"),
            lambda: FakeClient(missing_health),
        )
    )
    context2 = context_module.build_daily_context(
        database2,
        source2,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result2["receipt_output_id"],
    )
    assert context2["status"] == "blocked"
    assert "daily_review_health_missing" in context2["errors"]

    empty_health = _payloads()
    for tool in (
        "get_rhr_day",
        "get_hrv_data",
        "get_heart_rates",
        "get_vo2max_trend",
        "get_weigh_ins",
    ):
        empty_health[tool] = b"{}"
    source_empty, database_empty = _source(tmp_path / "all-empty")
    result_empty = asyncio.run(
        live.collect(
            live.approved_request(),
            source_empty,
            database_empty,
            _token_dir(tmp_path / "all-empty"),
            lambda: FakeClient(empty_health),
        )
    )
    context_empty = context_module.build_daily_context(
        database_empty,
        source_empty,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result_empty["receipt_output_id"],
    )
    assert context_empty["status"] == "blocked"
    assert "daily_review_health_missing" in context_empty["errors"]

    missing_sleep = _payloads()
    missing_sleep["get_sleep_data"] = b"No sleep data found for 2026-08-17."
    source3, database3 = _source(tmp_path / "sleep-missing")
    result3 = asyncio.run(
        live.collect(
            live.approved_request(),
            source3,
            database3,
            _token_dir(tmp_path / "sleep-missing"),
            lambda: FakeClient(missing_sleep),
        )
    )
    context3 = context_module.build_daily_context(
        database3,
        source3,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result3["receipt_output_id"],
    )
    assert context3["status"] == "blocked"
    assert "daily_sleep_evidence_missing" in context3["errors"]


@pytest.mark.parametrize(
    ("sleep_payload", "expected_error"),
    [
        (
            {
                "dailySleepDTO": {
                    "isNap": True,
                    "sleepStartTimestampGMT": "2026-08-16T18:00:00Z",
                    "sleepEndTimestampGMT": "2026-08-16T19:00:00Z",
                    "sleepTimeSeconds": 3600,
                }
            },
            "daily_sleep_evidence_missing",
        ),
        (
            {
                "dailySleepDTO": [
                    {
                        "sleepStartTimestampGMT": "2026-08-16T15:00:00Z",
                        "sleepEndTimestampGMT": "2026-08-16T22:00:00Z",
                        "sleepTimeSeconds": 25200,
                    },
                    {
                        "sleepStartTimestampGMT": "2026-08-16T16:00:00Z",
                        "sleepEndTimestampGMT": "2026-08-16T23:00:00Z",
                        "sleepTimeSeconds": 25200,
                    },
                ]
            },
            "daily_sleep_evidence_ambiguous",
        ),
    ],
)
def test_nap_or_multiple_main_sleep_candidates_block_before_ai(
    tmp_path: Path,
    sleep_payload: dict[str, Any],
    expected_error: str,
) -> None:
    live = _module("live_sync")
    context_module = _coach_module("build_context")
    payloads = _payloads()
    payloads["get_sleep_data"] = json.dumps(sleep_payload).encode()
    source, database = _source(tmp_path)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(payloads),
        )
    )
    context = context_module.build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=result["receipt_output_id"],
    )
    assert context["status"] == "blocked"
    assert expected_error in context["errors"]


def test_blocked_live_context_never_writes_ai_prompt_and_cli_is_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    payloads = _payloads()
    for tool in (
        "get_rhr_day",
        "get_hrv_data",
        "get_heart_rates",
        "get_vo2max_trend",
        "get_weigh_ins",
    ):
        payloads[tool] = b"{}"
    source, database = _source(tmp_path)
    sync = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(payloads),
        )
    )
    prompt_module = _coach_module("create_ai_prompt")
    context_path = tmp_path / "blocked-context.json"
    prompt_path = tmp_path / "blocked-prompt.txt"
    with pytest.raises(
        prompt_module.PromptBlocked, match="daily_review_health_missing"
    ):
        prompt_module.create(
            "daily",
            __import__("datetime").date(2026, 8, 17),
            database,
            source,
            context_path,
            prompt_path,
            sync["receipt_output_id"],
        )
    assert json.loads(context_path.read_text(encoding="utf-8"))["status"] == "blocked"
    assert context_path.stat().st_mode & 0o777 == 0o600
    assert not prompt_path.exists()

    monkeypatch.setattr(
        "sys.argv",
        [
            "create_ai_prompt.py",
            "--mode",
            "daily",
            "--date",
            "2026-08-17",
            "--database",
            str(database),
            "--source-root",
            str(source),
            "--context-json",
            str(context_path),
            "--prompt",
            str(prompt_path),
            "--live-sync-output-id",
            str(sync["receipt_output_id"]),
        ],
    )
    assert prompt_module.main() == 2
    assert not prompt_path.exists()

    prompt_path.write_text("stale prompt", encoding="utf-8")
    prompt_path.chmod(0o600)
    assert prompt_module.main() == 2
    assert prompt_path.read_text(encoding="utf-8") == "stale prompt"


def test_total_wall_budget_starts_before_candidate_and_token_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path / "candidate-timeout")
    fake = FakeClient(_payloads())
    preflight_clock = iter((0.0, 90.0))
    monkeypatch.setattr(live, "monotonic", lambda: next(preflight_clock))
    with pytest.raises(live.LiveSyncError, match="garmin_live_wall_budget_exceeded"):
        asyncio.run(
            live.collect(
                live.approved_request(),
                source,
                database,
                _token_dir(tmp_path / "candidate-timeout"),
                lambda: fake,
            )
        )
    assert fake.entries == 0

    live2 = _module("live_sync")
    source2, database2 = _source(tmp_path / "token-timeout")
    fake2 = FakeClient(_payloads())
    token_clock = iter((0.0, 1.0, 90.0))
    monkeypatch.setattr(live2, "monotonic", lambda: next(token_clock, 90.0))
    result = asyncio.run(
        live2.collect(
            live2.approved_request(),
            source2,
            database2,
            _token_dir(tmp_path / "token-timeout"),
            lambda: fake2,
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_wall_budget_exceeded"
    assert result["provider_entries"] == 0
    assert fake2.entries == 0


def test_total_wall_budget_includes_cleanup_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path / "cleanup-timeout")
    fake = FakeClient(_payloads())
    clock = [0.0]
    original_remove = live._remove_token_shadow

    def delayed_remove(path: Path) -> None:
        original_remove(path)
        clock[0] = live.WALL_SECONDS

    monkeypatch.setattr(live, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live, "_remove_token_shadow", delayed_remove)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path / "cleanup-timeout"),
            lambda: fake,
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_wall_budget_exceeded"
    receipt = connect(database, read_only=True)
    try:
        row = receipt.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (result["receipt_output_id"],),
        ).fetchone()
        assert row is not None
        assert json.loads(str(row[0]))["status"] == "blocked"
    finally:
        receipt.close()


def test_total_wall_budget_downgrades_success_during_receipt_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path / "receipt-timeout")
    fake = FakeClient(_payloads())
    clock = [0.0]
    original_append = live.append_output

    def delayed_append(*args: Any, **kwargs: Any) -> int:
        output_id = original_append(*args, **kwargs)
        if kwargs.get("output_kind") == "sync_summary":
            clock[0] = live.WALL_SECONDS
        return output_id

    monkeypatch.setattr(live, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live, "append_output", delayed_append)
    result = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path / "receipt-timeout"),
            lambda: fake,
        )
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "garmin_live_wall_budget_exceeded"
    connection = connect(database, read_only=True)
    try:
        run = connection.execute(
            "SELECT status FROM skill_runs WHERE workflow_key=? AND operation='daily_sync'",
            (live.WORKFLOW_KEY,),
        ).fetchone()
        receipt = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (result["receipt_output_id"],),
        ).fetchone()
        assert run is not None and str(run[0]) == "blocked"
        assert receipt is not None
        assert json.loads(str(receipt[0]))["status"] == "blocked"
    finally:
        connection.close()


def test_live_daily_commit_report_receipt_is_idempotent_without_email_or_gts(
    tmp_path: Path,
) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    sync = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(_payloads()),
        )
    )
    context = _coach_module("build_context").build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=sync["receipt_output_id"],
    )
    rhr = next(item for item in context["health"] if item["resource"] == "rhr")
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "昨日未发现活动；恢复证据可用，按计划保守执行。",
        "bounded_metrics": [
            {
                "name": "resting heart rate",
                "value": 52,
                "unit": "bpm",
                "evidence_ref": rhr["raw_file_id"],
            }
        ],
        "stop_conditions": ["出现疼痛、胸痛、晕眩、异常呼吸或明显恢复不足时停止。"],
        "evidence_refs": [
            {
                "raw_file_id": rhr["raw_file_id"],
                "sha256": rhr["sha256"],
                "claim": "昨日静息心率证据。",
            }
        ],
        "recent_trend_sha256": context["recent_trend"]["sha256"],
        "provider_calls": 0,
    }
    finalizer = _module("complete_live_daily")
    run_root, canary_receipt = _install_terminal_ai_attempt(source, context, payload)
    first = finalizer.complete(
        source, database, run_root, canary_receipt, tmp_path / "report-a"
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        before = {
            kind: connection.execute(
                "SELECT COUNT(*) FROM skill_outputs WHERE output_kind=?", (kind,)
            ).fetchone()[0]
            for kind in (
                "daily_summary",
                "report_artifact",
                "email_render",
                "garmin_workout_contract",
                "execution_summary",
            )
        }
        actions = connection.execute(
            "SELECT COUNT(*) FROM external_actions"
        ).fetchone()[0]
    finally:
        connection.close()
    second = finalizer.complete(
        source, database, run_root, canary_receipt, tmp_path / "report-b"
    )
    connection = connect(database, read_only=True, immutable=True)
    try:
        after = {
            kind: connection.execute(
                "SELECT COUNT(*) FROM skill_outputs WHERE output_kind=?", (kind,)
            ).fetchone()[0]
            for kind in before
        }
    finally:
        connection.close()
    assert first == second
    assert before == after
    assert before["email_render"] == 0
    assert before["garmin_workout_contract"] == 0
    assert actions == 0
    assert (tmp_path / "report-a/report.json").read_bytes() == (
        tmp_path / "report-b/report.json"
    ).read_bytes()
    assert (tmp_path / "report-a/report.html").read_bytes() == (
        tmp_path / "report-b/report.html"
    ).read_bytes()


def test_live_daily_rejects_context_raw_outside_sync_receipt(tmp_path: Path) -> None:
    live = _module("live_sync")
    source, database = _source(tmp_path)
    sync = asyncio.run(
        live.collect(
            live.approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(_payloads()),
        )
    )
    context_module = _coach_module("build_context")
    context = context_module.build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=sync["receipt_output_id"],
    )

    connection = connect(database)
    seed = live.begin_run(
        connection,
        run_key="seed-outside-receipt:attempt-1",
        workflow_key="seed:outside-receipt",
        dedupe_key=hashlib.sha256(b"seed-outside-receipt").hexdigest(),
        skill_name="garmin-sync",
        operation="index_existing_raw",
        trigger_kind="manual",
        input_manifest={"fixture": "outside-receipt"},
        target_from_date="2026-08-16",
        target_through_date="2026-08-16",
    )
    old_payload = json.dumps({"restingHeartRate": 61}).encode()
    relative = "garmin/health/20260816-rhr-outside-receipt.json"
    old_path = source / "state/raw" / relative
    old_path.write_bytes(old_payload)
    old_path.chmod(0o600)
    old_raw_id = live._insert_raw(
        connection,
        run_id=seed,
        provider="garmin",
        data_class="health",
        resource="rhr",
        logical_key="garmin:rhr:outside-receipt",
        data_date="2026-08-16",
        relative_path=relative,
        file_format="json",
        byte_size=len(old_payload),
        digest=hashlib.sha256(old_payload).hexdigest(),
    )
    live.finish_run(connection, seed, status="succeeded")
    connection.close()
    _seal_source(source)

    injected = json.loads(json.dumps(context))
    injected["health"].append(
        {
            "raw_file_id": old_raw_id,
            "sha256": hashlib.sha256(old_payload).hexdigest(),
            "resource": "rhr",
            "data_date": "2026-08-16",
            "metrics": {"resource": "rhr", "resting_heart_rate_bpm": 61},
            "parser": "garmin_health_v1",
        }
    )
    ai_payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "仅用于合成越界证据测试。",
        "bounded_metrics": [
            {
                "name": "resting heart rate",
                "value": 61,
                "unit": "bpm",
                "evidence_ref": old_raw_id,
            }
        ],
        "stop_conditions": ["出现危险信号时停止。"],
        "evidence_refs": [
            {
                "raw_file_id": old_raw_id,
                "sha256": hashlib.sha256(old_payload).hexdigest(),
                "claim": "合成旧记录。",
            }
        ],
        "recent_trend_sha256": injected["recent_trend"]["sha256"],
        "provider_calls": 0,
    }
    committed = _coach_module("commit_ai_result").commit(
        ai_payload, injected, database, "daily"
    )
    assert committed["status"] == "blocked"
    assert committed["error_code"] == "ai_evidence_outside_live_receipt"

    report_dir = source.parent / "forged-report"
    run_root, canary_receipt = _install_terminal_ai_attempt(
        source, injected, ai_payload
    )
    with pytest.raises(ValueError, match="daily_context_receipt_mismatch"):
        _module("complete_live_daily").complete(
            source, database, run_root, canary_receipt, report_dir
        )
    assert not report_dir.exists()


def test_live_daily_finalizer_requires_candidate_marker(tmp_path: Path) -> None:
    finalizer = _module("complete_live_daily")
    source, database = _source(tmp_path)
    (source.parent / "formal-state-fingerprint.json").unlink()
    with pytest.raises(ValueError, match="candidate_scope_required"):
        finalizer.complete(
            source,
            database,
            source.parent / "run/daily-20260817",
            tmp_path / "missing-canary-receipt.json",
            tmp_path / "out",
        )


def test_live_daily_finalizer_rejects_output_symlink(tmp_path: Path) -> None:
    finalizer = _module("complete_live_daily")
    source, database = _source(tmp_path)
    sync = asyncio.run(
        _module("live_sync").collect(
            _module("live_sync").approved_request(),
            source,
            database,
            _token_dir(tmp_path),
            lambda: FakeClient(_payloads()),
        )
    )
    context = _coach_module("build_context").build_daily_context(
        database,
        source,
        __import__("datetime").date(2026, 8, 17),
        live_sync_output_id=sync["receipt_output_id"],
    )
    rhr = next(item for item in context["health"] if item["resource"] == "rhr")
    payload = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "合成输出边界测试。",
        "bounded_metrics": [
            {
                "name": "resting heart rate",
                "value": 52,
                "unit": "bpm",
                "evidence_ref": rhr["raw_file_id"],
            }
        ],
        "stop_conditions": ["出现危险信号时停止。"],
        "evidence_refs": [
            {
                "raw_file_id": rhr["raw_file_id"],
                "sha256": rhr["sha256"],
                "claim": "合成静息心率。",
            }
        ],
        "recent_trend_sha256": context["recent_trend"]["sha256"],
        "provider_calls": 0,
    }
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    output = tmp_path / "report-link"
    output.symlink_to(outside, target_is_directory=True)
    run_root, canary_receipt = _install_terminal_ai_attempt(source, context, payload)
    with pytest.raises(ValueError, match="report_output_scope_invalid"):
        finalizer.complete(source, database, run_root, canary_receipt, output)
    assert list(outside.iterdir()) == []
