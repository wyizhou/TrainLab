from __future__ import annotations

import os
import signal
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest

import trainlab.local_supervisor as launcher_module
from trainlab.local_supervisor import (
    LocalSupervisorLauncher,
    LocalSupervisorLauncherError,
)


class FakeProcess:
    def __init__(self, pid: int, exit_code: int) -> None:
        self.pid = pid
        self._exit_code = exit_code
        self._waited = False

    def wait(self) -> int:
        self._waited = True
        return self._exit_code

    def poll(self) -> int | None:
        return self._exit_code if self._waited else None


class FakeFactory:
    def __init__(self, exit_codes: list[int]) -> None:
        self._exit_codes = iter(exit_codes)
        self.calls: list[tuple[tuple[str, ...], Path, Mapping[str, str]]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> FakeProcess:
        self.calls.append((argv, cwd, env))
        return FakeProcess(10_000 + len(self.calls), next(self._exit_codes))


def _root(tmp_path: Path) -> Path:
    (tmp_path / "harness").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    lock_parent = tmp_path / "state/runtime/locks"
    lock_parent.mkdir(parents=True)
    lock_parent.chmod(0o700)
    executable = tmp_path / ".venv/bin/trainlab"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    return tmp_path


def test_launcher_restarts_serially_with_bounded_backoff(tmp_path: Path) -> None:
    root = _root(tmp_path)
    factory = FakeFactory([1, 1, 0])
    delays: list[float] = []
    events: list[dict[str, object]] = []
    launcher = LocalSupervisorLauncher(
        root,
        process_factory=factory,
        retry_wait=lambda delay: delays.append(delay) is None and False,
        emit=events.append,
    )

    assert launcher.run() == 0
    assert len(factory.calls) == 3
    assert delays == [15.0, 30.0]
    assert [event["event"] for event in events] == [
        "restart_scheduled",
        "restart_scheduled",
    ]
    for argv, cwd, environment in factory.calls:
        assert argv == (str(root / ".venv/bin/trainlab"), "supervisor", "run")
        assert cwd == root
        assert environment["TZ"] == "Asia/Hong_Kong"
        assert environment["PYTHONUNBUFFERED"] == "1"
    lock = root / "state/runtime/locks/local-supervisor.lock"
    assert lock.read_text(encoding="ascii").strip() == str(os.getpid())
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_launcher_stops_after_three_abnormal_restart_attempts(
    tmp_path: Path,
) -> None:
    factory = FakeFactory([1, 1, 1, 1])
    delays: list[float] = []
    events: list[dict[str, object]] = []
    launcher = LocalSupervisorLauncher(
        _root(tmp_path),
        process_factory=factory,
        retry_wait=lambda delay: delays.append(delay) is None and False,
        emit=events.append,
    )

    assert launcher.run() == 1
    assert len(factory.calls) == 4
    assert delays == [15.0, 30.0, 60.0]
    assert events[-1] == {
        "component": "local_supervisor_launcher",
        "event": "restart_exhausted",
        "exit_code": 1,
        "restart_count": 3,
    }


@pytest.mark.parametrize("mode", (0o720, 0o702))
def test_launcher_rejects_group_or_world_writable_lock_parent(
    tmp_path: Path, mode: int
) -> None:
    root = _root(tmp_path)
    (root / "state/runtime/locks").chmod(mode)
    factory = FakeFactory([0])

    with pytest.raises(
        LocalSupervisorLauncherError,
        match="local_supervisor_lock_parent_invalid",
    ):
        LocalSupervisorLauncher(root, process_factory=factory).run()

    assert not factory.calls


def test_launcher_rejects_second_launcher_lock(tmp_path: Path) -> None:
    root = _root(tmp_path)
    factory = FakeFactory([0])

    with launcher_module._exclusive_launcher_lock(root):
        with pytest.raises(
            LocalSupervisorLauncherError,
            match="local_supervisor_already_running",
        ):
            LocalSupervisorLauncher(root, process_factory=factory).run()

    assert not factory.calls


def test_launcher_redacts_lock_io_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = FakeFactory([0])

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("private filesystem detail")

    monkeypatch.setattr(launcher_module.os, "fsync", fail_fsync)
    with pytest.raises(
        LocalSupervisorLauncherError,
        match="local_supervisor_lock_invalid",
    ) as failure:
        LocalSupervisorLauncher(_root(tmp_path), process_factory=factory).run()

    assert "private filesystem detail" not in str(failure.value)
    assert not factory.calls


def test_stop_signal_terminates_child_group_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    signals: list[tuple[int, signal.Signals]] = []
    launcher: LocalSupervisorLauncher

    class StopProcess(FakeProcess):
        def wait(self) -> int:
            launcher.request_stop()
            self._waited = True
            return -signal.SIGTERM

    def factory(
        _argv: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> StopProcess:
        del cwd, env
        calls.append(1)
        return StopProcess(12_345, 0)

    monkeypatch.setattr(
        launcher_module.os,
        "killpg",
        lambda pid, signum: signals.append((pid, signum)),
    )
    launcher = LocalSupervisorLauncher(_root(tmp_path), process_factory=factory)

    assert launcher.run() == 0
    assert calls == [1]
    assert signals == [(12_345, signal.SIGTERM)]
