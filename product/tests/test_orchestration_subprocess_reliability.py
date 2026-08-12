"""Boundary partitions for downstream process start and owned-group cleanup."""

from __future__ import annotations

import errno
import json
import signal
import subprocess

import pytest

import trainlab.orchestration.subprocess_runner as runner_module
from trainlab.orchestration import DownstreamCall, SubprocessRunner


def _call() -> DownstreamCall:
    return DownstreamCall("foundation", "status", "reliability-1", None)


def _receipt() -> bytes:
    return json.dumps(
        {
            "schema_version": "1",
            "invocation_id": "reliability-1",
            "mode": "status",
            "status": "ready",
            "foundation_schema_version": 1,
            "ready": True,
            "created_count": 0,
            "existing_count": 0,
            "verified_count": 1,
            "migration_start_version": None,
            "migration_end_version": None,
            "applied_migration_ids": [],
            "next_action": "none",
            "warnings": [],
            "errors": [],
            "started_at_utc": "2026-08-07T00:00:00Z",
            "completed_at_utc": "2026-08-07T00:00:01Z",
        }
    ).encode()


class _Process:
    pid = 42_001

    def __init__(
        self, *, output: bytes | None = None, failure: BaseException | None = None
    ) -> None:
        self.output = _receipt() if output is None else output
        self.failure = failure
        self.returncode = 0
        self.calls = 0

    def communicate(self, timeout: int) -> tuple[bytes, bytes]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.output, b"untrusted-child-stderr"


def _install_popen(monkeypatch: pytest.MonkeyPatch, action: object) -> list[int]:
    attempts: list[int] = []

    def popen(*_args: object, **_kwargs: object) -> _Process:
        attempts.append(1)
        if isinstance(action, BaseException):
            raise action
        return action  # type: ignore[return-value]

    monkeypatch.setattr(runner_module.subprocess, "Popen", popen)
    return attempts


@pytest.mark.parametrize(
    "failure", [errno.EAGAIN, errno.EMFILE], ids=["again", "fd-pressure"]
)
def test_transient_pre_start_failures_retry_with_count_and_time_bounds(
    monkeypatch: pytest.MonkeyPatch,
    failure: int,
) -> None:
    process = _Process()
    attempts = 0
    delays: list[float] = []

    def popen(*_args: object, **_kwargs: object) -> _Process:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError(failure, "sensitive-start-detail")
        return process

    monkeypatch.setattr(runner_module.subprocess, "Popen", popen)
    monkeypatch.setattr(runner_module.time, "sleep", delays.append)
    assert SubprocessRunner().run(_call()).kind == "accepted"
    assert attempts == 3
    assert delays == list(runner_module._PROCESS_START_RETRY_DELAYS_SECONDS)


@pytest.mark.parametrize(
    "failure",
    [errno.ENOENT, errno.EACCES, errno.EINVAL],
    ids=["missing", "permission", "non-transient"],
)
def test_nontransient_pre_start_failures_do_not_retry_or_expose_details(
    monkeypatch: pytest.MonkeyPatch,
    failure: int,
) -> None:
    attempts = _install_popen(monkeypatch, OSError(failure, "sensitive-start-detail"))
    result = SubprocessRunner().run(_call())
    assert (result.kind, result.error_code, result.exit_code) == (
        "untrusted",
        "process_start_failed",
        None,
    )
    assert len(attempts) == 1
    assert "sensitive-start-detail" not in repr(result)


def test_start_retry_deadline_prevents_a_further_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = _install_popen(
        monkeypatch, OSError(errno.EAGAIN, "sensitive-start-detail")
    )
    ticks = iter((100.0, 100.0, 101.1))
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: next(ticks))
    assert SubprocessRunner().run(_call()).error_code == "process_start_failed"
    assert len(attempts) == 1


def test_started_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(output=b"not-a-receipt")
    attempts = _install_popen(monkeypatch, process)
    result = SubprocessRunner().run(_call())
    assert (result.kind, result.error_code) == ("untrusted", "receipt_json_invalid")
    assert len(attempts) == 1


def test_timeout_reaps_owned_group_and_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process(failure=subprocess.TimeoutExpired("secret-command", 1))
    _install_popen(monkeypatch, process)
    signals: list[signal.Signals] = []
    monkeypatch.setattr(
        runner_module.os, "killpg", lambda _pid, sig: signals.append(sig)
    )
    monkeypatch.setattr(
        SubprocessRunner, "_process_group_exists", staticmethod(lambda _pid: False)
    )
    result = SubprocessRunner().run(_call())
    assert (result.kind, result.error_code) == (
        "timeout_unknown",
        "process_timeout_unknown",
    )
    assert signals[0] == signal.SIGTERM
    assert "secret-command" not in repr(result)


def test_cancellation_reaps_started_group_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process(failure=KeyboardInterrupt("secret-cancellation-detail"))
    _install_popen(monkeypatch, process)
    reaped: list[object] = []
    runner = SubprocessRunner()
    monkeypatch.setattr(
        runner, "_terminate_group", lambda item: reaped.append(item) or True
    )
    with pytest.raises(KeyboardInterrupt, match="secret-cancellation-detail"):
        runner.run(_call())
    assert reaped == [process]


def test_cleanup_no_child_created_does_not_signal_a_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_popen(monkeypatch, OSError(errno.ENOENT, "missing"))
    signals: list[int] = []
    monkeypatch.setattr(
        runner_module.os, "killpg", lambda _pid, _sig: signals.append(1)
    )
    assert SubprocessRunner().run(_call()).error_code == "process_start_failed"
    assert signals == []


def test_cleanup_already_exited_group_is_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    _install_popen(monkeypatch, process)
    monkeypatch.setattr(
        runner_module.os,
        "killpg",
        lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError()),
    )
    monkeypatch.setattr(
        SubprocessRunner, "_process_group_exists", staticmethod(lambda _pid: False)
    )
    assert SubprocessRunner()._terminate_group(process) is True


def test_cleanup_termination_timeout_is_controlled_without_child_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process(failure=subprocess.TimeoutExpired("secret-command", 1))
    _install_popen(monkeypatch, process)
    runner = SubprocessRunner()
    monkeypatch.setattr(runner, "_terminate_group", lambda _item: False)
    result = runner.run(_call())
    assert (result.kind, result.error_code, result.receipt) == (
        "untrusted",
        "process_group_unreaped",
        None,
    )
    assert "secret-command" not in repr(result)
