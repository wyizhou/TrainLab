"""Bounded restart launcher for short-lived local Supervisor observation.

This is not a business scheduler and never invokes a lower-layer tool.  It
serially owns one fixed ``trainlab supervisor run`` child, reaps that child,
and performs a bounded restart after abnormal exits.  Long-running Linux and
macOS deployments remain the responsibility of systemd and launchd.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import stat
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from trainlab.util import project_root

_RESTART_DELAYS_SECONDS = (15.0, 30.0, 60.0)
_LOCK_RELATIVE_PATH = Path("state/foundation/state/locks/local-supervisor.lock")


class LocalSupervisorLauncherError(RuntimeError):
    """A data-free local launcher failure."""


class ManagedProcess(Protocol):
    pid: int

    def wait(self) -> int: ...

    def poll(self) -> int | None: ...


class ProcessFactory(Protocol):
    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> ManagedProcess: ...


def _spawn_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> ManagedProcess:
    return subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def _emit(event: dict[str, object]) -> None:
    print(json.dumps(event, sort_keys=True, separators=(",", ":")), flush=True)


@contextmanager
def _exclusive_launcher_lock(root: Path) -> Iterator[None]:
    path = root / _LOCK_RELATIVE_PATH
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise LocalSupervisorLauncherError(
            "local_supervisor_lock_parent_invalid"
        ) from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise LocalSupervisorLauncherError("local_supervisor_lock_parent_invalid")

    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LocalSupervisorLauncherError("local_supervisor_lock_invalid") from exc
    try:
        try:
            evidence = os.fstat(descriptor)
            if (
                not stat.S_ISREG(evidence.st_mode)
                or evidence.st_uid != os.geteuid()
                or evidence.st_nlink != 1
            ):
                raise LocalSupervisorLauncherError("local_supervisor_lock_invalid")
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LocalSupervisorLauncherError(
                    "local_supervisor_already_running"
                ) from exc
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
        except LocalSupervisorLauncherError:
            raise
        except OSError as exc:
            raise LocalSupervisorLauncherError("local_supervisor_lock_invalid") from exc
        yield
    finally:
        os.close(descriptor)


class LocalSupervisorLauncher:
    """Run one Supervisor child with bounded abnormal-exit retries."""

    def __init__(
        self,
        root: Path,
        *,
        process_factory: ProcessFactory = _spawn_process,
        retry_wait: Callable[[float], bool] | None = None,
        emit: Callable[[dict[str, object]], None] = _emit,
    ) -> None:
        self._root = project_root(root)
        self._process_factory = process_factory
        self._retry_wait = retry_wait
        self._emit = emit
        self._stop = threading.Event()
        self._child: ManagedProcess | None = None

    def request_stop(self) -> None:
        self._stop.set()
        child = self._child
        if child is None or child.poll() is not None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def run(self) -> int:
        executable = self._root / ".venv/bin/trainlab"
        try:
            executable_evidence = executable.lstat()
        except OSError as exc:
            raise LocalSupervisorLauncherError(
                "local_supervisor_executable_invalid"
            ) from exc
        if (
            not stat.S_ISREG(executable_evidence.st_mode)
            or executable_evidence.st_uid != os.geteuid()
            or executable_evidence.st_mode & 0o111 == 0
            or executable_evidence.st_mode & 0o022 != 0
        ):
            raise LocalSupervisorLauncherError("local_supervisor_executable_invalid")
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["TZ"] = "Asia/Hong_Kong"
        argv = (str(executable), "supervisor", "run")

        with _exclusive_launcher_lock(self._root):
            for attempt in range(len(_RESTART_DELAYS_SECONDS) + 1):
                if self._stop.is_set():
                    return 0
                try:
                    child = self._process_factory(argv, cwd=self._root, env=environment)
                    self._child = child
                    exit_code = child.wait()
                except OSError:
                    exit_code = 127
                finally:
                    self._child = None

                if self._stop.is_set() or exit_code == 0:
                    return 0
                if attempt == len(_RESTART_DELAYS_SECONDS):
                    self._emit(
                        {
                            "component": "local_supervisor_launcher",
                            "event": "restart_exhausted",
                            "exit_code": exit_code,
                            "restart_count": attempt,
                        }
                    )
                    return exit_code if exit_code != 0 else 1

                delay = _RESTART_DELAYS_SECONDS[attempt]
                self._emit(
                    {
                        "component": "local_supervisor_launcher",
                        "event": "restart_scheduled",
                        "exit_code": exit_code,
                        "restart_count": attempt + 1,
                        "delay_seconds": int(delay),
                    }
                )
                interrupted = (
                    self._retry_wait(delay)
                    if self._retry_wait is not None
                    else self._stop.wait(delay)
                )
                if interrupted or self._stop.is_set():
                    return 0
        return 0


def main() -> int:
    launcher = LocalSupervisorLauncher(project_root())
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _number, _frame: launcher.request_stop())
    try:
        return launcher.run()
    except LocalSupervisorLauncherError as exc:
        print(
            json.dumps(
                {
                    "component": "local_supervisor_launcher",
                    "event": "rejected",
                    "error_code": exc.args[0],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
