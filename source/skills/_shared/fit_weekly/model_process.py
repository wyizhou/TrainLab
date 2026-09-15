"""Bounded POSIX child supervision, not a model launcher or sandbox.

Only a trusted Host supplies argv/environment. Start once in a new process
session, multiplex all three pipes, then stop its process groups before returning.
Captured bytes stay in memory for the adapter's private evidence publication.
No threads, retry, shell interpolation, authentication or global configuration.
"""

from __future__ import annotations

import math
import os
import select
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import parent_watch
from skills._shared.fit_weekly.model_job import AdapterInterrupted


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    input_bytes: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    error_code: str | None
    process_stopped: bool = True


class ProcessInterrupted(AdapterInterrupted):
    """Expose bounded private diagnostics without presenting a terminal result."""

    def __init__(self, capture: ProcessResult):
        super().__init__("model_process_stop_unconfirmed")
        self.capture = capture


def session_groups(sid: int, timeout: float) -> set[int] | None:
    """Read only PID/group/owner/state; use getsid, not platform-specific ps SID.

    A failed or unparseable OS observation is unknown, never proof of stopping.
    Normal MCP tools create a separate process group inside the CLI session.
    Dead zombies cannot execute work; independently daemonized sessions are not
    supported. macOS ps's `sess` column does not reliably expose the POSIX SID.
    """
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,pgid=,uid=,stat="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.defpath, "LC_ALL": "C"},
            timeout=timeout,
            check=True,
        )
        groups = set()
        for line in result.stdout.decode("ascii").splitlines():
            pid, group, owner, state = line.split()
            pid_value, group_value, owner_value = int(pid), int(group), int(owner)
            if owner_value != os.geteuid() or state.startswith("Z"):
                continue
            try:
                if os.getsid(pid_value) == sid:
                    if group_value <= 1:
                        return None
                    groups.add(group_value)
            except ProcessLookupError:
                continue
        return groups
    except Exception:
        return None


def signal_stop(group: int) -> None:
    """Signal delivery is not a liveness verdict; callers must still observe.

    macOS can return EPERM for an already zombie-only group. Live members or
    an unreadable session will still prevent the caller's terminal result.
    """
    try:
        os.killpg(group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def stop(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    """Bounded synchronous reap and observation, including leftover children."""
    deadline = time.monotonic() + timeout
    try:
        signal_stop(proc.pid)
        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        while (remaining := deadline - time.monotonic()) > 0:
            groups = session_groups(proc.pid, remaining)
            if groups == set():
                return True
            if groups is None:
                return False
            for group in groups:
                signal_stop(group)
            time.sleep(min(0.02, remaining))
    except Exception:
        return False
    return False


def options(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    prompt: bytes,
    timeout: float,
    stop_timeout: float,
    stdout_limit: int,
    stderr_limit: int,
) -> None:
    try:
        if (
            os.name != "posix"
            or not isinstance(argv, list)
            or not argv
            or not argv[0]
            or any(not isinstance(a, str) or "\x00" in a for a in argv)
            or not Path(argv[0]).is_absolute()
            or not isinstance(cwd, Path)
            or not cwd.is_absolute()
            or not cwd.is_dir()
            or not isinstance(env, dict)
            or any(
                not isinstance(k, str)
                or not k
                or "=" in k
                or "\x00" in k
                or not isinstance(v, str)
                or "\x00" in v
                for k, v in env.items()
            )
            or type(prompt) is not bytes
            or not 0 < len(prompt) <= 16_777_216
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in (timeout, stop_timeout)
            )
            or any(
                type(v) is not int or not 0 < v <= 67_108_864
                for v in (stdout_limit, stderr_limit)
            )
        ):
            raise ValueError("invalid")
    except Exception:
        raise ValueError("process_options_invalid") from None


def execute(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    prompt: bytes,
    timeout: float = 600,
    stop_timeout: float = 5,
    stdout_limit: int = 67_108_864,
    stderr_limit: int = 1_048_576,
) -> ProcessResult:
    """No ordinary return until the new child session is confirmed non-running.

    `timeout` covers launch/input/model execution; `stop_timeout` is the extra
    termination/observation allowance. Post-stop local persistence belongs to
    the adapter and is not performed asynchronously or hidden in this budget.
    This function alone provides neither Codex capability nor read isolation.
    """
    options(argv, cwd, env, prompt, timeout, stop_timeout, stdout_limit, stderr_limit)
    deadline = time.monotonic() + timeout
    launch_read, launch_write = os.pipe()
    try:
        proc = subprocess.Popen(
            parent_watch.command(argv, error_fd=launch_write),
            cwd=cwd,
            env=env.copy(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
            pass_fds=(launch_write,),
            umask=0o077,
            bufsize=0,
        )
    except Exception:
        os.close(launch_read)
        os.close(launch_write)
        return ProcessResult(None, 0, b"", b"", "process_start_failed")
    os.close(launch_write)
    sent = 0
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    error: str | None = None
    interrupted: BaseException | None = None
    group_signalled = False
    selector = None
    streams: list[Any] = [proc.stdin, proc.stdout, proc.stderr]
    try:
        launch_ready, _, _ = select.select(
            [launch_read], [], [], max(0, deadline - time.monotonic())
        )
        if not launch_ready:
            error = "process_timeout"
        elif os.read(launch_read, 32):
            error = "process_start_failed"
        selector = selectors.DefaultSelector()
        for stream, name in zip(streams, ("stdin", "stdout", "stderr"), strict=True):
            os.set_blocking(stream.fileno(), False)
            selector.register(
                stream,
                selectors.EVENT_WRITE if name == "stdin" else selectors.EVENT_READ,
                name,
            )
        while error is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = "process_timeout"
                break
            exited = proc.poll() is not None
            if exited and not group_signalled:
                # A descendant may still hold the pipes open after the leader
                # exits. Stop it now, then drain buffered bytes to EOF.
                groups = session_groups(proc.pid, min(remaining, stop_timeout))
                if groups is None:
                    raise OSError("session_observation_unavailable")
                for group in groups:
                    signal_stop(group)
                group_signalled = True
            if exited and sent != len(prompt):
                error = "process_input_incomplete"
                break
            if exited and not selector.get_map():
                break
            for key, _ in selector.select(min(remaining, 0.05)):
                ready: Any = key.fileobj
                name = key.data
                if name == "stdin":
                    try:
                        sent += os.write(key.fd, prompt[sent : sent + 65_536])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        error = "process_input_incomplete"
                        break
                    if sent == len(prompt):
                        selector.unregister(ready)
                        ready.close()
                else:
                    try:
                        data = os.read(
                            key.fd, min(65_536, limits[name] - len(buffers[name]) + 1)
                        )
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(ready)
                        ready.close()
                    else:
                        available = limits[name] - len(buffers[name])
                        buffers[name].extend(data[:available])
                        if len(data) > available:
                            error = "process_" + name + "_limit"
                            break
    except Exception:
        error = "process_io_failed"
    except BaseException as exc:
        interrupted = exc
    finally:
        # No daemon writer/reaper; adapter cannot publish while children remain.
        confirmed = stop(proc, stop_timeout)
        os.close(launch_read)
        for resource in [selector, *streams]:
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                error = error or "process_io_failed"
    if not confirmed:
        raise ProcessInterrupted(
            ProcessResult(
                proc.returncode,
                sent,
                bytes(buffers["stdout"]),
                bytes(buffers["stderr"]),
                "process_stop_unconfirmed",
                False,
            )
        )
    if interrupted is not None:
        raise interrupted
    if error is None and proc.returncode != 0:
        error = "process_exit_nonzero"
    return ProcessResult(
        None if error == "process_start_failed" else proc.returncode,
        sent,
        bytes(buffers["stdout"]),
        bytes(buffers["stderr"]),
        error,
    )
