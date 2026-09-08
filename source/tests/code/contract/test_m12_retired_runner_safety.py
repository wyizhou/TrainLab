"""RET-005: retired runner safety on the current, single-attempt M12 path.

All children are local Python programs and every instance is synthetic. Legacy
attempt numbers, retry categories and anonymous-file helpers are not restored.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skills._shared.fit_weekly import (
    codex_isolation,
    codex_output,
    fit_detail,
    model_job,
    model_process,
    process_capture,
    stage_policy,
    storage,
)

PROMPT = b"Public synthetic retired-runner safety request."
MODEL_TIMEOUT = 30.0


def _events(extra: dict[str, Any] | None = None) -> bytes:
    rows = [
        {"type": "thread.started", "thread_id": "public-safety-thread"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "public-answer",
                "type": "agent_message",
                "text": '{"ok":true}',
            },
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
        },
    ]
    if extra is not None:
        rows.insert(3, extra)
    return b"".join((json.dumps(row) + "\n").encode() for row in rows)


def _program(stdout: bytes, stderr: bytes = b"", exit_code: int = 0) -> str:
    return (
        "import sys; sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write({stdout!r}); sys.stdout.buffer.flush(); "
        f"sys.stderr.buffer.write({stderr!r}); sys.stderr.buffer.flush(); "
        f"sys.exit({exit_code})"
    )


def _environment() -> dict[str, str]:
    return {"PATH": os.defpath, "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}


class LocalProcessAdapter:
    """Use the real supervision/capture/parser, without a model or Provider."""

    def __init__(
        self,
        root: Path,
        end: str,
        program: str,
        *,
        stdout_limit: int = 16_384,
        stderr_limit: int = 4096,
    ) -> None:
        self.root, self.end, self.program = root, end, program
        self.stdout_limit, self.stderr_limit = stdout_limit, stderr_limit
        self.work = root / "public-process-capture"
        self.calls = self.launches = 0
        self.result: model_process.ProcessResult | None = None
        self.binding: dict[str, Any] = {}
        self.profile = {
            "kind": "fake",
            "name": "public-local-process",
            "configuration_sha256": model_job.sha(
                {"program": program, "stdout": stdout_limit, "stderr": stderr_limit}
            ),
        }

    def run(self, payload: Any, host: Any, schema: dict[str, Any]) -> Any:
        self.calls += 1
        with storage.open_store(self.root) as db:
            intent = fit_detail.get(
                db, stage_policy.job_key(self.end, host.stage) + ":intent"
            )
        assert intent is not None
        identity, request = intent
        assert request["stage"] == host.stage == "plan"
        assert request["payload"] == payload and host.root == self.root
        self.binding = process_capture.binding(
            PROMPT,
            identity,
            stdout_limit=self.stdout_limit,
            stderr_limit=self.stderr_limit,
        )

        def launch() -> model_process.ProcessResult:
            self.launches += 1
            assert json.loads((self.work / "intent.json").read_text())["binding"] == (
                self.binding
            )
            self.result = model_process.execute(
                [sys.executable, "-c", self.program],
                cwd=self.root,
                env=_environment(),
                prompt=PROMPT,
                timeout=MODEL_TIMEOUT,
                stop_timeout=5,
                stdout_limit=self.stdout_limit,
                stderr_limit=self.stderr_limit,
            )
            assert self.result.process_stopped
            return self.result

        captured = process_capture.run(self.work, self.binding, launch)
        return codex_output.parse_result(
            captured, schema, prompt_bytes=len(PROMPT)
        ).value


def _setup(tmp_path: Path, program: str, **options: Any) -> tuple[Any, ...]:
    fixture = importlib.import_module("test_m12_model_job")
    args = fixture.setup(tmp_path)
    return (*args[:5], LocalProcessAdapter(args[0], args[1], program, **options))


def _run(args: tuple[Any, ...]) -> dict[str, Any]:
    return importlib.import_module("test_m12_model_job").run(args)


def _snapshot(args: tuple[Any, ...]) -> dict[str, bytes]:
    adapter = args[-1]
    paths = [*adapter.work.iterdir(), model_job.capture_path(*args[:2], stage="plan")]
    return {str(p.relative_to(args[0])): p.read_bytes() for p in paths}


def _closed_once(args: tuple[Any, ...], first: dict[str, Any]) -> None:
    adapter = args[-1]
    raw = json.loads((adapter.work / "capture.json").read_text())
    assert process_capture.decode(raw, adapter.binding) == adapter.result
    assert adapter.work.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in adapter.work.iterdir())
    before = _snapshot(args)
    second = _run(args)
    assert second["receipt"] == first["receipt"]
    assert second["result"] == first["result"]
    assert second["invocation_adapter_calls"] == 0
    assert first["receipt"]["provider_calls"] == 0
    assert first["receipt"]["external_actions"] == 0
    assert adapter.calls == adapter.launches == 1
    assert _snapshot(args) == before


# Every M9 failure-category input remains explicit; M12 does not restore the
# obsolete transport/server retry labels or authorize another model attempt.
FAILURE_INPUTS = [
    pytest.param(
        {"type": "error", "message": "connection reset by peer"},
        b"",
        id="event-transport",
    ),
    pytest.param(
        {"type": "error", "message": "request failed with HTTP 503"},
        b"",
        id="event-http-503",
    ),
    pytest.param(
        {
            "type": "turn.failed",
            "error": {"message": "response did not match output schema"},
        },
        b"",
        id="turn-schema-message",
    ),
    pytest.param(
        {
            "type": "error",
            "error": {
                "code": "invalid_json_schema",
                "message": "Invalid schema: allOf is not permitted",
                "status": 400,
            },
        },
        b"",
        id="event-schema-nested",
    ),
    pytest.param(
        {
            "type": "turn.failed",
            "error": {
                "code": "invalid_json_schema",
                "status": 400,
                "details": {"keyword": "allOf"},
            },
        },
        b"",
        id="turn-schema-details",
    ),
    pytest.param(
        {"type": "error", "message": "401 authentication required"},
        b"",
        id="event-auth",
    ),
    pytest.param(
        {"type": "error", "message": "sandbox denied permission"},
        b"",
        id="event-sandbox",
    ),
    pytest.param(None, b"error: unexpected argument '--bad'", id="stderr-cli"),
    pytest.param(
        {"type": "error", "message": "something strange happened"},
        b"",
        id="event-unknown",
    ),
    pytest.param(None, b"Error: request failed with HTTP 503", id="stderr-http-503"),
    pytest.param(None, b"Error: connection reset by peer", id="stderr-transport"),
]


@pytest.mark.parametrize("event,stderr", FAILURE_INPUTS)
def test_legacy_failure_inputs_are_durable_single_attempts(tmp_path, event, stderr):
    stdout = _events(event)
    args = _setup(tmp_path, _program(stdout, stderr, 1))
    first = _run(args)
    assert first["status"] == "failed" and first["result"] is None
    assert first["receipt"]["error_code"] == "model_adapter_failed"
    assert args[-1].result.stdout == stdout
    assert args[-1].result.stderr == stderr
    assert args[-1].result.error_code == "process_exit_nonzero"
    _closed_once(args, first)


@pytest.mark.parametrize(
    "event,stderr", [case for case in FAILURE_INPUTS if case.values[0] is not None]
)
def test_error_event_cannot_be_hidden_by_valid_answer_and_zero_exit(
    tmp_path, event, stderr
):
    stdout = _events(event)
    args = _setup(tmp_path, _program(stdout, stderr))
    first = _run(args)
    assert args[-1].result.error_code is None
    assert args[-1].result.stdout == stdout
    assert first["status"] == "failed" and first["result"] is None
    _closed_once(args, first)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_log_overflow_never_publishes_valid_answer(tmp_path, stream):
    answer = _events()
    stdout = answer + (b"x" * 8192 if stream == "stdout" else b"")
    stderr = b"y" * 8192 if stream == "stderr" else b""
    args = _setup(
        tmp_path,
        _program(stdout, stderr),
        stdout_limit=len(answer) + 128,
        stderr_limit=256,
    )
    first = _run(args)
    captured = args[-1].result
    assert first["status"] == "failed" and first["result"] is None
    assert captured.error_code == "process_" + stream + "_limit"
    assert captured.stdout.startswith(answer)
    assert len(captured.stdout) <= len(answer) + 128
    assert len(captured.stderr) <= 256
    assert len(getattr(captured, stream)) == (
        len(answer) + 128 if stream == "stdout" else 256
    )
    _closed_once(args, first)


@pytest.mark.parametrize("status", ["succeeded", "failed"])
@pytest.mark.parametrize("stage", ["raw_capture", "outer_capture", "fsync"])
def test_slow_post_stop_persistence_is_synchronous_and_not_model_timeout(
    tmp_path, monkeypatch, status, stage
):
    args = _setup(tmp_path, _program(_events(), exit_code=int(status == "failed")))
    adapter = args[-1]
    outer = model_job.capture_path(*args[:2], stage="plan")
    raw_path = adapter.work / "capture.json"
    atomic, fsync = storage.atomic_file, storage.os.fsync
    delay = 0.1
    offset = 0.0
    delayed: list[bool] = []

    def model_clock() -> float:
        return time.monotonic() + offset

    def pause_after_stop() -> None:
        nonlocal offset
        assert adapter.result is not None and adapter.result.process_stopped
        assert not delayed
        delayed.append(False)
        time.sleep(delay)
        # Advance only this module's clock after real child termination. Process
        # launch and execution still have the full, uncompressed 30-second SLA.
        offset += MODEL_TIMEOUT + 1
        delayed[0] = True

    def slow_atomic(path: Path, data: bytes) -> None:
        target = raw_path if stage == "raw_capture" else outer
        if stage != "fsync" and path == target and not delayed:
            pause_after_stop()
        atomic(path, data)

    def slow_fsync(fd: int) -> None:
        if stage == "fsync" and adapter.result is not None and not delayed:
            pause_after_stop()
        fsync(fd)

    monkeypatch.setattr(
        model_process, "time", SimpleNamespace(monotonic=model_clock, sleep=time.sleep)
    )
    monkeypatch.setattr(storage, "atomic_file", slow_atomic)
    monkeypatch.setattr(storage.os, "fsync", slow_fsync)
    started = time.monotonic()
    first = _run(args)
    assert time.monotonic() - started >= delay
    assert delayed == [True] and offset > MODEL_TIMEOUT
    assert first["status"] == status
    assert adapter.result.error_code == (
        "process_exit_nonzero" if status == "failed" else None
    )
    before = _snapshot(args)
    time.sleep(delay * 2)
    assert _snapshot(args) == before
    _closed_once(args, first)


def _late_writer(ready: Path, release: Path, target: Path) -> str:
    return (
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(ready)!r}).write_text('started')\n"
        "deadline=time.monotonic()+30\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    if time.monotonic()>=deadline: raise RuntimeError('release missing')\n"
        "    time.sleep(0.01)\n"
        f"Path({str(target)!r}).write_text('late')\n"
        "os.write(1,b'LATE\\n')\n"
    )


def _wait_ready(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, "synthetic child did not start"
        time.sleep(0.01)
    assert path.read_text() == "started"


def test_late_writer_positive_control_writes_when_not_stopped(tmp_path):
    ready, release, target = (tmp_path / name for name in ("ready", "release", "late"))
    proc = subprocess.Popen(
        [sys.executable, "-c", _late_writer(ready, release, target)],
        cwd=tmp_path,
        env=_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_ready(ready)
        release.write_text("allowed")
        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0 and stderr == b""
        assert stdout == b"LATE\n" and target.read_text() == "late"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


@pytest.mark.parametrize("separate_group", [False, True])
def test_stopped_descendant_cannot_change_final_capture(tmp_path, separate_group):
    ready, release, target = (tmp_path / name for name in ("ready", "release", "late"))
    child = _late_writer(ready, release, target)
    program = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "sys.stdin.buffer.read()\n"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]"
        + (",process_group=0" if separate_group else "")
        + ")\n"
        "deadline=time.monotonic()+10\n"
        f"while not Path({str(ready)!r}).exists():\n"
        "    if time.monotonic()>=deadline: raise RuntimeError('child missing')\n"
        "    time.sleep(0.01)\n"
        f"sys.stdout.buffer.write({_events()!r}); sys.stdout.buffer.flush()\n"
    )
    args = _setup(tmp_path, program)
    first = _run(args)
    assert first["status"] == "succeeded"
    assert ready.read_text() == "started"
    assert args[-1].result.process_stopped
    assert args[-1].result.stdout == _events()
    before = _snapshot(args)
    # Only a stopped descendant is safe when its external condition later
    # becomes ready. This handshake avoids racing a short startup sleep.
    release.write_text("allowed only after terminal publication")
    time.sleep(0.2)
    assert not target.exists()
    assert _snapshot(args) == before
    _closed_once(args, first)


def test_real_unconfirmed_stop_remains_unknown_and_never_relaunches(
    tmp_path, monkeypatch
):
    args = _setup(tmp_path, _program(_events()))
    monkeypatch.setattr(model_process, "session_groups", lambda *_: None)
    with pytest.raises(process_capture.EvidenceUnavailable):
        _run(args)
    adapter = args[-1]
    assert not (adapter.work / "capture.json").exists()
    interrupted = json.loads((adapter.work / "interrupted.json").read_text())
    assert interrupted["process"]["process_stopped"] is False
    assert not model_job.capture_path(*args[:2], stage="plan").exists()
    result = _run(args)
    assert result["status"] == "unknown" and result["result"] is None
    assert result["invocation_adapter_calls"] == 0
    assert adapter.calls == adapter.launches == 1


@pytest.mark.parametrize("failure", ["missing_executable", "isolation"])
def test_launch_preparation_failure_has_no_model_intent_or_process(
    tmp_path, monkeypatch, failure
):
    fixture = importlib.import_module("test_m12_codex_adapter")
    args, runtime, proof, calls = fixture.setup(tmp_path, monkeypatch)
    before = (args[0] / "trainlab-fit.db").read_bytes()
    if failure == "missing_executable":
        runtime.executable.unlink()
    else:

        def unavailable(**_: Any) -> Any:
            raise ValueError("public isolation preflight failure")

        monkeypatch.setattr(codex_isolation, "prepare", unavailable)
    with pytest.raises(ValueError, match="codex_preparation_invalid"):
        fixture.prepare(args, runtime, proof)
    assert calls == []
    assert (args[0] / "trainlab-fit.db").read_bytes() == before
    with storage.open_store(args[0]) as db:
        assert not db.execute(
            "SELECT 1 FROM documents WHERE logical_key LIKE 'model-job:%'"
        ).fetchall()
    assert not model_job.capture_path(*args[:2], stage="plan").exists()
