from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts.schema_validation import validate_payload

ROOT = Path(__file__).resolve().parents[3]


def _runner():
    path = ROOT / "skills/training-coach/scripts/codex_attempt_runtime.py"
    spec = importlib.util.spec_from_file_location("m9_codex_attempt_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.run_codex_daily

    def run_codex_daily(**kwargs):
        kwargs.setdefault("environment_check", lambda: "0" * 64)
        return original(**kwargs)

    setattr(module, "run_codex_daily", run_codex_daily)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _daily_payload() -> dict[str, Any]:
    return {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "error_code": None,
        "report_date": "2026-08-17",
        "review_date": "2026-08-16",
        "sleep_wake_date": "2026-08-17",
        "safety": "ready",
        "summary": "合成日报。",
        "bounded_metrics": [
            {"name": "rhr", "value": 52, "unit": "bpm", "evidence_ref": 1}
        ],
        "stop_conditions": ["出现危险信号时停止。"],
        "evidence_refs": [
            {"raw_file_id": 1, "sha256": "a" * 64, "claim": "合成证据。"}
        ],
        "recent_trend_sha256": "b" * 64,
        "today_course": {},
        "provider_calls": 0,
    }


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidate = tmp_path / "candidate"
    run_root = candidate / "run/daily-20260817"
    run_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for directory in (candidate, candidate / "run", run_root):
        directory.chmod(0o700)
    context = run_root / "context.json"
    prompt = run_root / "prompt.txt"
    if not context.exists():
        context.write_text(
            json.dumps(
                {
                    "schema_version": "daily_ai_context_v1",
                    "status": "ready",
                    "report_date": "2026-08-17",
                    "review_date": "2026-08-16",
                    "sleep_wake_date": "2026-08-17",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not prompt.exists():
        prompt.write_text("frozen synthetic prompt\n", encoding="utf-8")
    context.chmod(0o600)
    prompt.chmod(0o600)
    prior = run_root / "ai-attempt-2"
    prior.mkdir(mode=0o700, exist_ok=True)
    prior.chmod(0o700)
    prior_receipt = prior / "attempt-receipt.json"
    if not prior_receipt.exists():
        events = prior / "events.jsonl"
        stderr = prior / "stderr.log"
        events.write_bytes(b'{"type":"error","message":"synthetic"}\n')
        stderr.write_bytes(b"synthetic stderr\n")
        events.chmod(0o600)
        stderr.chmod(0o600)
        payload = {
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
            "context_sha256": _sha(context),
            "prompt_sha256": _sha(prompt),
            "schema_sha256": _sha(
                ROOT / "skills/_shared/schemas/daily_ai_result_v1.schema.json"
            ),
            "events_captured_bytes": events.stat().st_size,
            "events_sha256": _sha(events),
            "stderr_captured_bytes": stderr.stat().st_size,
            "stderr_sha256": _sha(stderr),
            "result_bytes": None,
            "result_sha256": None,
            "provider_calls": 0,
            "external_actions": 0,
        }
        assert validate_payload(payload, "codex_ai_attempt_v1") == []
        prior_receipt.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        prior_receipt.chmod(0o600)
    return run_root, context, prompt


def _fake_codex(
    tmp_path: Path,
    *,
    events: list[dict[str, Any]] | None = None,
    stderr: str = "",
    result: object | str | None = None,
    returncode: int = 0,
    sleep_seconds: float = 0.0,
    extra_stdout: str = "",
    expected_prompt: str | None = None,
    expected_schema_sha256: str | None = None,
    schema_must_be_read_only: bool = False,
    read_stdin: bool = True,
) -> Path:
    path = tmp_path / f"fake-codex-{len(list(tmp_path.glob('fake-codex-*')))}.py"
    result_text = (
        result
        if isinstance(result, str)
        else json.dumps(result, ensure_ascii=False, sort_keys=True)
        if result is not None
        else None
    )
    script = f"""#!{sys.executable}
import json
import hashlib
import sys
import time
import os
from pathlib import Path

args = sys.argv[1:]
assert "--ephemeral" in args
assert "--ignore-user-config" in args
assert args[args.index("--sandbox") + 1] == "read-only"
assert "--json" in args
assert "--output-schema" in args
assert args[-1] == "-"
prompt = sys.stdin.read() if {read_stdin!r} else ""
assert {expected_prompt!r} is None or prompt == {expected_prompt!r}
schema_path = Path(args[args.index("--output-schema") + 1])
schema_sha256 = hashlib.sha256(schema_path.read_bytes()).hexdigest()
assert {expected_schema_sha256!r} is None or schema_sha256 == {expected_schema_sha256!r}
if {schema_must_be_read_only!r}:
    try:
        writable = os.open(schema_path, os.O_WRONLY)
    except OSError:
        pass
    else:
        os.close(writable)
        raise AssertionError("schema descriptor is writable")
time.sleep({sleep_seconds!r})
for event in {events or []!r}:
    print(json.dumps(event, ensure_ascii=False), flush=True)
if {extra_stdout!r}:
    print({extra_stdout!r}, flush=True)
if {stderr!r}:
    print({stderr!r}, file=sys.stderr, flush=True)
result = {result_text!r}
if result is not None:
    output = Path(args[args.index("--output-last-message") + 1])
    output.write_text(result + "\\n", encoding="utf-8")
raise SystemExit({returncode})
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return path


def _run(
    tmp_path: Path,
    fake: Path,
    *,
    timeout_seconds: float = 180.0,
    max_log_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    return module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        environment_check=lambda: "0" * 64,
        timeout_seconds=timeout_seconds,
        max_log_bytes=max_log_bytes,
    )


def test_success_is_owner_only_atomic_and_schema_valid(tmp_path: Path) -> None:
    fake = _fake_codex(
        tmp_path,
        events=[{"type": "turn.completed", "usage": {"output_tokens": 20}}],
        result=_daily_payload(),
    )
    result = _run(tmp_path, fake)
    attempt = tmp_path / "candidate/run/daily-20260817/ai-attempt-3"
    assert result["status"] == "succeeded"
    assert result["error_category"] is None
    assert sorted(path.name for path in attempt.iterdir()) == [
        "ai-result.json",
        "attempt-intent.json",
        "attempt-receipt.json",
        "events.jsonl",
        "stderr.log",
    ]
    assert attempt.stat().st_mode & 0o777 == 0o700
    for path in attempt.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_size > 0
        assert path.stat().st_nlink == 1
    receipt = json.loads((attempt / "attempt-receipt.json").read_text())
    assert receipt["attempt"] == 3
    assert receipt["command_contract"]["output_schema"] == ("daily_ai_result_codex_v1")
    assert validate_payload(receipt, "codex_ai_attempt_v1") == []
    assert receipt["events_captured_bytes"] == (attempt / "events.jsonl").stat().st_size
    assert receipt["events_sha256"] == _sha(attempt / "events.jsonl")
    assert receipt["stderr_captured_bytes"] == (attempt / "stderr.log").stat().st_size
    assert receipt["stderr_sha256"] == _sha(attempt / "stderr.log")
    assert json.loads((attempt / "ai-result.json").read_text()) == _daily_payload()
    assert (attempt / "stderr.log").read_text() == "NO_STDERR\n"


@pytest.mark.parametrize(
    ("event", "stderr", "expected"),
    [
        (
            {"type": "error", "message": "connection reset by peer"},
            "",
            "transport_retryable",
        ),
        (
            {"type": "error", "message": "request failed with HTTP 503"},
            "",
            "server_5xx_retryable",
        ),
        (
            {
                "type": "turn.failed",
                "error": {"message": "response did not match output schema"},
            },
            "",
            "schema_non_retryable",
        ),
        (
            {
                "type": "error",
                "error": {
                    "code": "invalid_json_schema",
                    "message": "Invalid schema: allOf is not permitted",
                    "status": 400,
                },
            },
            "",
            "schema_non_retryable",
        ),
        (
            {
                "type": "turn.failed",
                "error": {
                    "code": "invalid_json_schema",
                    "status": 400,
                    "details": {"keyword": "allOf"},
                },
            },
            "",
            "schema_non_retryable",
        ),
        (
            {"type": "error", "message": "401 authentication required"},
            "",
            "auth_non_retryable",
        ),
        (
            {"type": "error", "message": "sandbox denied permission"},
            "",
            "sandbox_non_retryable",
        ),
        (None, "error: unexpected argument '--bad'", "cli_non_retryable"),
        (
            {"type": "error", "message": "something strange happened"},
            "",
            "unknown_non_retryable",
        ),
        (None, "Error: request failed with HTTP 503", "server_5xx_retryable"),
        (None, "Error: connection reset by peer", "transport_retryable"),
    ],
)
def test_failure_categories_are_persisted(
    tmp_path: Path,
    event: dict[str, Any] | None,
    stderr: str,
    expected: str,
) -> None:
    fake = _fake_codex(
        tmp_path,
        events=[event] if event else [],
        stderr=stderr,
        returncode=1,
    )
    result = _run(tmp_path, fake)
    attempt = tmp_path / "candidate/run/daily-20260817/ai-attempt-3"
    assert result["status"] == "failed"
    assert result["error_category"] == expected
    assert not (attempt / "ai-result.json").exists()
    receipt = json.loads((attempt / "attempt-receipt.json").read_text())
    assert receipt["error_category"] == expected
    assert validate_payload(receipt, "codex_ai_attempt_v1") == []


def test_model_text_containing_500_is_not_server_error(tmp_path: Path) -> None:
    fake = _fake_codex(
        tmp_path,
        events=[
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "HTTP 500 is text"},
            }
        ],
        returncode=1,
    )
    result = _run(tmp_path, fake)
    assert result["error_category"] == "unknown_non_retryable"


def test_timeout_is_transport_failure_and_cannot_be_retried(tmp_path: Path) -> None:
    fake = _fake_codex(tmp_path, sleep_seconds=0.5, returncode=1)
    result = _run(tmp_path, fake, timeout_seconds=0.05)
    assert result["status"] == "failed"
    assert result["error_code"] == "ai_codex_timeout"
    assert result["error_category"] == "transport_retryable"
    replay = _run(tmp_path, fake)
    assert replay == result


def test_stdin_backpressure_is_inside_the_hard_timeout(tmp_path: Path) -> None:
    run_root, _context, prompt = _inputs(tmp_path)
    prompt.write_bytes(b"x" * (2 * 1024 * 1024))
    prompt.chmod(0o600)
    receipt_path = run_root / "ai-attempt-2/attempt-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["prompt_sha256"] = _sha(prompt)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    fake = _fake_codex(
        tmp_path,
        read_stdin=False,
        sleep_seconds=0.3,
        result=_daily_payload(),
    )

    started = time.monotonic()
    result = _run(tmp_path, fake, timeout_seconds=0.05)
    elapsed = time.monotonic() - started

    assert result["status"] == "failed"
    assert result["error_code"] == "ai_codex_timeout"
    assert result["error_category"] == "transport_retryable"
    assert elapsed < 0.5


def test_child_exit_before_full_prompt_is_a_failure(tmp_path: Path) -> None:
    run_root, _context, prompt = _inputs(tmp_path)
    prompt.write_bytes(b"x" * (2 * 1024 * 1024))
    prompt.chmod(0o600)
    receipt_path = run_root / "ai-attempt-2/attempt-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["prompt_sha256"] = _sha(prompt)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    fake = _fake_codex(
        tmp_path,
        read_stdin=False,
        result=_daily_payload(),
    )

    result = _run(tmp_path, fake)

    assert result["status"] == "failed"
    assert result["error_code"] == "ai_prompt_incomplete"
    assert not (run_root / "ai-attempt-3/ai-result.json").exists()


def test_result_and_evidence_finalization_are_synchronous_after_model_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_publish = module._publish_terminal

    def immediate_process(command: list[str], *_args: object, **_kwargs: object):
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(_daily_payload(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
        return (0, False, False, False, True, 0.01, True)

    def delayed_publish(*args: object, **kwargs: object):
        time.sleep(0.6)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(module, "_publish_terminal", delayed_publish)
    monkeypatch.setattr(module, "_run_process", immediate_process)
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=0.5,
    )

    assert result["status"] == "succeeded", result
    assert (run_root / "ai-attempt-3/ai-result.json").is_file()
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_process_launch_is_inside_the_hard_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"

    def delayed_launch(*_args: object, **_kwargs: object):
        time.sleep(0.2)
        raise OSError("synthetic delayed launch")

    monkeypatch.setattr(module.subprocess, "Popen", delayed_launch)
    started = time.monotonic()
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=0.05,
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "ai_codex_timeout"
    assert time.monotonic() - started >= 0.2


def test_kill_permission_error_still_produces_a_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, sleep_seconds=0.3, returncode=1)
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"

    def deny_group_kill(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(module.os, "killpg", deny_group_kill)
    with pytest.raises(module.RunnerBlocked, match="ai_process_stop_unconfirmed"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
            timeout_seconds=0.05,
        )

    assert (run_root / "ai-attempt-3.pending").is_dir()
    assert not (run_root / "ai-attempt-3").exists()


def test_group_and_process_kill_failures_do_not_escape_without_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, sleep_seconds=0.3, returncode=1)
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"

    def deny_kill(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(module.os, "killpg", deny_kill)
    monkeypatch.setattr(module.subprocess.Popen, "kill", deny_kill)
    with pytest.raises(module.RunnerBlocked, match="ai_process_stop_unconfirmed"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
            timeout_seconds=0.05,
        )

    assert (run_root / "ai-attempt-3.pending").is_dir()
    assert not (run_root / "ai-attempt-3").exists()


def test_local_write_crossing_model_deadline_can_persist_verified_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_write = module._atomic_owner_write
    calls = 0

    def immediate_process(command: list[str], *_args: object, **_kwargs: object):
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(_daily_payload(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
        return (0, False, False, False, True, 0.01, True)

    def delayed_write(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            time.sleep(0.6)
        original_write(*args, **kwargs)

    monkeypatch.setattr(module, "_atomic_owner_write", delayed_write)
    monkeypatch.setattr(module, "_run_process", immediate_process)
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=0.5,
    )

    persisted = json.loads(
        (run_root / "ai-attempt-3/attempt-receipt.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "succeeded"
    assert persisted["status"] == "succeeded"
    assert (run_root / "ai-attempt-3/ai-result.json").is_file()


def test_success_receipt_post_replace_failure_cannot_leave_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_write = module._atomic_owner_write
    calls = 0

    def fail_after_success_replace(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_write(*args, **kwargs)
            return
        if calls == 2:
            original_write(*args, **kwargs)
            raise OSError("synthetic post-replace failure")
        raise OSError("synthetic failure receipt failure")

    monkeypatch.setattr(module, "_atomic_owner_write", fail_after_success_replace)
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_incomplete"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )

    assert not (run_root / "ai-attempt-3").exists()
    assert (run_root / "ai-attempt-3.pending").is_dir()


def test_termination_confirmation_is_synchronous_after_model_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, sleep_seconds=0.5, returncode=1)
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"

    def delayed_wait(*_args: object, **_kwargs: object) -> int:
        time.sleep(0.4)
        raise subprocess.TimeoutExpired("synthetic", 0.01)

    monkeypatch.setattr(module.subprocess.Popen, "wait", delayed_wait)
    started = time.monotonic()
    with pytest.raises(module.RunnerBlocked, match="ai_process_stop_unconfirmed"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
            timeout_seconds=0.2,
        )
    elapsed = time.monotonic() - started

    assert elapsed >= 0.4
    assert (run_root / "ai-attempt-3.pending").is_dir()
    assert not (run_root / "ai-attempt-3").exists()


def test_failure_receipt_delay_is_synchronous_and_has_no_late_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, returncode=1)
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_write = module._atomic_owner_write

    def delayed_write(*args: object, **kwargs: object) -> None:
        time.sleep(0.2)
        original_write(*args, **kwargs)

    monkeypatch.setattr(module, "_atomic_owner_write", delayed_write)
    started = time.monotonic()
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert result["status"] == "failed"
    assert elapsed >= 0.4
    assert not (run_root / "ai-attempt-3/ai-result.json").exists()
    time.sleep(0.25)
    receipt_path = run_root / "ai-attempt-3/attempt-receipt.json"
    if receipt_path.exists():
        assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] != (
            "succeeded"
        )


def test_slow_local_success_publish_is_synchronous_and_final_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_replace = module.os.replace

    def immediate_process(command: list[str], *_args: object, **_kwargs: object):
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(_daily_payload(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
        return (0, False, False, False, True, 0.0, True)

    def delayed_success_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path.name == "attempt-receipt.json":
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            if payload.get("status") == "succeeded":
                time.sleep(0.2)
        original_replace(source, destination)

    monkeypatch.setattr(module, "_run_process", immediate_process)
    monkeypatch.setattr(module.os, "replace", delayed_success_replace)
    started = time.monotonic()
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=0.1,
    )
    elapsed = time.monotonic() - started

    assert result["status"] == "succeeded"
    assert elapsed >= 0.2
    attempt = run_root / "ai-attempt-3"
    receipt = json.loads((attempt / "attempt-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "succeeded"
    assert (attempt / "ai-result.json").is_file()
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_failed_attempt_2_is_preserved_and_does_not_block_attempt_3(
    tmp_path: Path,
) -> None:
    run_root, _context, _prompt = _inputs(tmp_path)
    prior = run_root / "ai-attempt-2"
    evidence = prior / "attempt-receipt.json"
    frozen_evidence = evidence.read_bytes()

    fake = _fake_codex(tmp_path, result=_daily_payload())
    result = _run(tmp_path, fake)

    assert result["status"] == "succeeded"
    assert evidence.read_bytes() == frozen_evidence
    assert (run_root / "ai-attempt-3/ai-result.json").is_file()
    assert not (run_root / "ai-attempt-4").exists()


@pytest.mark.parametrize("evidence_name", ["events.jsonl", "stderr.log"])
def test_attempt_3_requires_closed_attempt_2_capture_evidence(
    tmp_path: Path, evidence_name: str
) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    evidence = run_root / "ai-attempt-2" / evidence_name
    evidence.write_bytes(evidence.read_bytes() + b"tampered")
    evidence.chmod(0o600)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    fake = _fake_codex(tmp_path, result=_daily_payload())

    with pytest.raises(module.RunnerBlocked, match="prior_attempt_evidence_invalid"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )

    assert not (run_root / "ai-attempt-3").exists()


def test_intent_write_failure_never_starts_or_publishes_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_write = module._atomic_owner_write
    calls = 0

    def fail_first_write(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic fallback receipt failure")
        original_write(*args, **kwargs)

    monkeypatch.setattr(module, "_atomic_owner_write", fail_first_write)
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_incomplete"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )
    assert not (run_root / "ai-attempt-3").exists()
    assert (run_root / "ai-attempt-3.pending").is_dir()


def test_unapproved_attempt_directory_blocks_attempt_3(tmp_path: Path) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    unapproved = run_root / "ai-attempt-4"
    unapproved.mkdir(mode=0o700)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    fake = _fake_codex(tmp_path, result=_daily_payload())

    with pytest.raises(module.RunnerBlocked, match="ai_attempt_history_invalid"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )

    assert not (run_root / "ai-attempt-3").exists()


def test_attempt_3_rejects_prompt_or_context_not_bound_to_attempt_2(
    tmp_path: Path,
) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    context.write_text(
        json.dumps(
            {
                "schema_version": "daily_ai_context_v1",
                "status": "ready",
                "report_date": "2026-08-17",
                "review_date": "2026-08-16",
                "sleep_wake_date": "2026-08-17",
                "altered": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt.write_text("altered prompt\n", encoding="utf-8")
    context.chmod(0o600)
    prompt.chmod(0o600)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    fake = _fake_codex(tmp_path, result=_daily_payload())

    with pytest.raises(module.RunnerBlocked, match="prior_attempt_input_mismatch"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )

    assert not (run_root / "ai-attempt-3").exists()


def test_schema_failure_does_not_publish_ai_result(tmp_path: Path) -> None:
    fake = _fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result={"schema_version": "daily_ai_result_v1"},
    )
    result = _run(tmp_path, fake)
    attempt = tmp_path / "candidate/run/daily-20260817/ai-attempt-3"
    assert result["status"] == "failed"
    assert result["error_category"] == "schema_non_retryable"
    assert result["error_code"] == "ai_result_schema_invalid"
    assert not (attempt / "ai-result.json").exists()


def test_business_valid_but_wire_invalid_result_is_rejected(tmp_path: Path) -> None:
    payload = _daily_payload()
    payload.pop("error_code")
    assert validate_payload(payload, "daily_ai_result_v1") == []
    assert validate_payload(payload, "daily_ai_result_codex_v1") != []
    fake = _fake_codex(tmp_path, result=payload)

    result = _run(tmp_path, fake)

    attempt = tmp_path / "candidate/run/daily-20260817/ai-attempt-3"
    assert result["status"] == "failed"
    assert result["error_code"] == "ai_result_schema_invalid"
    assert not (attempt / "ai-result.json").exists()


@pytest.mark.parametrize(
    ("field", "expected_error"),
    [
        ("context", "frozen_context_sha256_mismatch"),
        ("prompt", "frozen_prompt_sha256_mismatch"),
        ("schema", "frozen_schema_sha256_mismatch"),
    ],
)
def test_hash_mismatch_stops_before_process_and_attempt_creation(
    tmp_path: Path, field: str, expected_error: str
) -> None:
    fake = _fake_codex(tmp_path, result=_daily_payload())
    module = _runner()
    run_root, _context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    expected = {
        "context": _sha(_context),
        "prompt": _sha(prompt),
        "schema": _sha(schema),
    }
    expected[field] = "0" * 64
    with pytest.raises(module.RunnerBlocked, match=expected_error):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=expected["context"],
            expected_prompt_sha256=expected["prompt"],
            expected_schema_sha256=expected["schema"],
            codex_executable=fake,
        )
    assert not (run_root / "ai-attempt-3").exists()


def test_missing_codex_stops_before_attempt_creation(tmp_path: Path) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    with pytest.raises(module.RunnerBlocked, match="codex_cli_unavailable"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=tmp_path / "missing-codex",
        )
    assert not (run_root / "ai-attempt-3").exists()


def test_launch_failure_is_persisted_as_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _fake_codex(tmp_path, result=_daily_payload())
    module = _runner()

    def fail_launch(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(module.subprocess, "Popen", fail_launch)
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
    )
    attempt = run_root / "ai-attempt-3"
    assert result["status"] == "failed"
    assert result["error_code"] == "ai_codex_launch_failed"
    assert result["error_category"] == "cli_non_retryable"
    assert sorted(path.name for path in attempt.iterdir()) == [
        "attempt-intent.json",
        "attempt-receipt.json",
        "events.jsonl",
        "stderr.log",
    ]
    assert all(path.stat().st_size > 0 for path in attempt.iterdir())


def test_frozen_bytes_are_used_even_if_source_paths_change_after_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    tracked_schema = (
        ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    )
    schema = tmp_path / "daily.schema.json"
    schema.write_bytes(tracked_schema.read_bytes())
    schema.chmod(0o600)
    monkeypatch.setattr(module, "SCHEMA_PATH", schema)
    original_prompt = prompt.read_text(encoding="utf-8")
    original_schema_sha = _sha(schema)
    original_loader = module._load_frozen_inputs

    def load_then_replace(*args: object, **kwargs: object):
        frozen = original_loader(*args, **kwargs)
        context.write_text('{"status":"altered"}\n', encoding="utf-8")
        prompt.write_text("ALTERED AFTER SHA CHECK\n", encoding="utf-8")
        schema.write_text("{}\n", encoding="utf-8")
        context.chmod(0o600)
        prompt.chmod(0o600)
        schema.chmod(0o600)
        return frozen

    monkeypatch.setattr(module, "_load_frozen_inputs", load_then_replace)
    fake = _fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result=_daily_payload(),
        expected_prompt=original_prompt,
        expected_schema_sha256=original_schema_sha,
        schema_must_be_read_only=True,
    )
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(frozen_context := run_root / "context.json"),
        expected_prompt_sha256=hashlib.sha256(original_prompt.encode()).hexdigest(),
        expected_schema_sha256=original_schema_sha,
        codex_executable=fake,
    )
    assert result["status"] == "succeeded"
    assert result["context_sha256"] != _sha(frozen_context)
    assert result["prompt_sha256"] != _sha(prompt)
    assert result["schema_sha256"] != _sha(schema)


def test_log_budget_is_bounded_and_result_is_not_published(tmp_path: Path) -> None:
    fake = _fake_codex(
        tmp_path,
        extra_stdout="x" * 512,
        result=_daily_payload(),
    )
    result = _run(tmp_path, fake, max_log_bytes=128)
    attempt = tmp_path / "candidate/run/daily-20260817/ai-attempt-3"
    assert result["status"] == "failed"
    assert result["error_code"] == "ai_log_budget_exceeded"
    assert result["error_category"] == "cli_non_retryable"
    assert (attempt / "events.jsonl").stat().st_size <= 128
    assert not (attempt / "ai-result.json").exists()


def test_cli_has_no_date_mode_or_request_id(tmp_path: Path) -> None:
    runner = ROOT / "skills/training-coach/scripts/run_codex_daily.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert "--run-root" in completed.stdout
    assert "--expected-context-sha256" in completed.stdout
    assert "--canary-receipt" in completed.stdout
    assert "--token-dir" in completed.stdout
    assert "--date" not in completed.stdout
    assert "--mode" not in completed.stdout
    assert "request-id" not in completed.stdout


def test_intent_is_durable_before_codex_process_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original = module.subprocess.Popen
    observed = False

    def inspect_then_launch(*args: object, **kwargs: object):
        nonlocal observed
        pending = run_root / "ai-attempt-3.pending"
        intent = pending / "attempt-intent.json"
        assert pending.is_dir()
        assert intent.is_file() and intent.stat().st_size > 0
        assert (
            validate_payload(
                json.loads(intent.read_text()), "codex_ai_attempt_intent_v1"
            )
            == []
        )
        assert not (run_root / "ai-attempt-3").exists()
        observed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", inspect_then_launch)
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
    )
    assert observed is True
    assert result["status"] == "succeeded"


def test_existing_pending_blocks_without_starting_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    (run_root / "ai-attempt-3.pending").mkdir(mode=0o700)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Codex must not start")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_incomplete"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )


def test_run_root_lock_contention_stops_before_pending(tmp_path: Path) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    descriptor = os.open(run_root, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(module.RunnerBlocked, match="ai_attempt_lock_unavailable"):
            module.run_codex_daily(
                run_root=run_root,
                expected_context_sha256=_sha(context),
                expected_prompt_sha256=_sha(prompt),
                expected_schema_sha256=_sha(schema),
                codex_executable=fake,
            )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_unconfirmed_process_stop_leaves_pending_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    monkeypatch.setattr(
        module,
        "_run_process",
        lambda *_args, **_kwargs: (124, True, False, False, True, 0.1, False),
    )
    with pytest.raises(module.RunnerBlocked, match="ai_process_stop_unconfirmed"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )
    assert (run_root / "ai-attempt-3.pending/attempt-intent.json").is_file()
    assert not (run_root / "ai-attempt-3").exists()


def test_terminal_publish_failure_leaves_pending_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_rename = module.os.rename

    def fail_final_rename(source: str | Path, destination: str | Path) -> None:
        if Path(destination).name == "ai-attempt-3":
            raise OSError("synthetic terminal rename failure")
        original_rename(source, destination)

    monkeypatch.setattr(module.os, "rename", fail_final_rename)
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_incomplete"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )
    assert (run_root / "ai-attempt-3.pending").is_dir()
    assert not (run_root / "ai-attempt-3").exists()


def test_valid_success_replay_does_not_start_codex_or_change_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    first = _run(tmp_path, fake)
    before = {
        path.name: path.read_bytes() for path in (run_root / "ai-attempt-3").iterdir()
    }

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Codex must not start on replay")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    replay = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
    )
    after = {
        path.name: path.read_bytes() for path in (run_root / "ai-attempt-3").iterdir()
    }
    assert replay == first
    assert after == before


def test_invalid_terminal_extra_file_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    _run(tmp_path, fake)
    run_root, context, prompt = _inputs(tmp_path)
    extra = run_root / "ai-attempt-3/extra.txt"
    extra.write_text("unexpected\n", encoding="utf-8")
    extra.chmod(0o600)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no restart")),
    )
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_terminal_invalid"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )


def test_runner_source_has_no_async_write_or_finalization_reserve() -> None:
    source = (
        ROOT / "skills/training-coach/scripts/codex_attempt_runtime.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "threading",
        "_bounded_atomic_owner_write",
        "rollback_payload",
        "finalization_reserve",
    ):
        assert forbidden not in source


def test_late_process_group_child_is_stopped_before_final_publish(
    tmp_path: Path,
) -> None:
    module = _runner()
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    fake = tmp_path / "fake-codex-descendant.py"
    payload = json.dumps(_daily_payload(), ensure_ascii=False, sort_keys=True)
    fake.write_text(
        f"""#!{sys.executable}
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
sys.stdin.read()
subprocess.Popen([
    sys.executable,
    "-c",
    "import os,time; time.sleep(0.4); os.write(1,b'LATE\\n')",
])
Path(args[args.index("--output-last-message") + 1]).write_text({payload!r} + "\\n")
print('{{"type":"turn.completed"}}', flush=True)
""",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
    )
    final = run_root / "ai-attempt-3"
    before = (final / "events.jsonl").read_bytes()
    assert result["status"] == "succeeded"
    assert b"LATE\n" not in before
    time.sleep(0.6)
    after = (final / "events.jsonl").read_bytes()
    assert after == before
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_process_group_must_be_observed_gone_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()

    class ExitedProcess:
        pid = 9001

        @staticmethod
        def poll() -> int:
            return 0

    monkeypatch.setattr(module, "_process_group_exists", lambda _pid: True)
    monkeypatch.setattr(module.os, "killpg", lambda *_args: None)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    assert module._terminate_and_confirm(ExitedProcess()) is False


def test_post_model_fsync_is_not_counted_as_model_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    original_popen = module.subprocess.Popen
    original_fsync = module.os.fsync
    process_started = False
    delayed_calls = 0

    def observe_popen(*args: object, **kwargs: object):
        nonlocal process_started
        process_started = True
        return original_popen(*args, **kwargs)

    def delayed_post_model_fsync(descriptor: int) -> None:
        nonlocal delayed_calls
        if process_started and delayed_calls < 2:
            delayed_calls += 1
            time.sleep(1.1)
        original_fsync(descriptor)

    monkeypatch.setattr(module.subprocess, "Popen", observe_popen)
    monkeypatch.setattr(module.os, "fsync", delayed_post_model_fsync)
    started = time.monotonic()
    result = module.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(schema),
        codex_executable=fake,
        timeout_seconds=2.0,
    )
    assert time.monotonic() - started > 2.0
    assert result["status"] == "succeeded"


def test_business_schema_must_match_attempt_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    wire = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    changed = tmp_path / "changed-business-schema.json"
    changed.write_bytes(
        (ROOT / "skills/_shared/schemas/daily_ai_result_v1.schema.json").read_bytes()
        + b"\n"
    )
    changed.chmod(0o600)
    monkeypatch.setattr(module, "BUSINESS_SCHEMA_PATH", changed)
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Codex must not start")
        ),
    )
    with pytest.raises(module.RunnerBlocked, match="prior_attempt_input_mismatch"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(wire),
            codex_executable=fake,
        )
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_environment_drift_stops_before_pending_and_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    fingerprints = iter(("0" * 64, "1" * 64))
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Codex must not start")
        ),
    )
    with pytest.raises(module.RunnerBlocked, match="ai_environment_changed"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
            environment_check=lambda: next(fingerprints),
        )
    assert not (run_root / "ai-attempt-3.pending").exists()


def test_production_environment_failure_stops_before_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    token_dir = tmp_path / "tokens"
    token_dir.mkdir(mode=0o700)
    monkeypatch.setattr(
        module,
        "_production_environment_check",
        lambda *_args: (_ for _ in ()).throw(
            module.RunnerBlocked("ai_environment_preflight_failed")
        ),
    )
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Codex must not start")
        ),
    )
    with pytest.raises(module.RunnerBlocked, match="ai_environment_preflight_failed"):
        module._run_codex_daily_impl(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
            token_dir=token_dir,
        )


def test_final_receipt_must_identify_attempt_3(tmp_path: Path) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    _run(tmp_path, fake)
    receipt_path = run_root / "ai-attempt-3/attempt-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["attempt"] = 2
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    receipt_path.chmod(0o600)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_terminal_invalid"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )


@pytest.mark.parametrize(
    "failing_helper",
    ["_anonymous_read_only_file", "_ensure_capture", "_publish_terminal"],
)
def test_finite_post_intent_io_failures_are_stable_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_helper: str
) -> None:
    module = _runner()
    fake = _fake_codex(tmp_path, result=_daily_payload())
    run_root, context, prompt = _inputs(tmp_path)
    schema = ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
    monkeypatch.setattr(
        module,
        failing_helper,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("finite I/O fault")),
    )
    with pytest.raises(module.RunnerBlocked, match="ai_attempt_incomplete"):
        module.run_codex_daily(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(schema),
            codex_executable=fake,
        )
    assert (run_root / "ai-attempt-3.pending").is_dir()
    assert not (run_root / "ai-attempt-3").exists()
