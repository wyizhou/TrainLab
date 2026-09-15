from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def identity(pid: int) -> bytes | None:
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart=,stat="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LC_ALL": "C"},
            timeout=2,
            check=False,
        )
        fields = result.stdout.strip().rsplit(None, 1)
        if result.returncode != 0 or len(fields) != 2 or fields[1].startswith(b"Z"):
            return None
        return fields[0]
    except Exception:
        return None


def groups_in(sid: int) -> set[int]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,uid=,stat="],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "LC_ALL": "C"},
        timeout=2,
        check=True,
    )
    groups = set()
    for line in result.stdout.decode("ascii").splitlines():
        pid, group, owner, state = line.split()
        if int(owner) != os.geteuid() or state.startswith("Z"):
            continue
        try:
            if os.getsid(int(pid)) == sid:
                groups.add(int(group))
        except ProcessLookupError:
            pass
    return groups


def kill_group(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def stop_session(sid: int) -> None:
    own = os.getpgrp()
    kill_group(sid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            groups = groups_in(sid) - {own}
            if not groups:
                break
            for group in groups:
                kill_group(group)
        except Exception:
            pass
        time.sleep(0.05)
    os.killpg(own, signal.SIGKILL)


def command(argv: list[str], *, error_fd: int = -1) -> list[str]:
    from pathlib import Path

    return [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        str(os.getpid()),
        str(error_fd),
        *argv,
    ]


def main() -> None:
    parent = int(sys.argv[1])
    error_fd = int(sys.argv[2])
    if error_fd >= 0:
        os.set_inheritable(error_fd, False)
    argv = sys.argv[3:]
    if not argv or parent <= 1 or os.getppid() != parent:
        raise SystemExit(125)
    original = identity(parent)
    if original is None:
        raise SystemExit(125)
    if os.getsid(0) != os.getpid():
        os.setsid()
    sid = os.getpid()
    ready_read, ready_write = os.pipe()
    watcher = os.fork()
    if watcher == 0:
        os.close(ready_read)
        if error_fd >= 0:
            os.close(error_fd)
        os.setpgid(0, 0)
        for number in (0, 1, 2):
            os.close(number)
        os.write(ready_write, b"1")
        os.close(ready_write)
        while identity(parent) == original and identity(sid) is not None:
            time.sleep(0.1)
        stop_session(sid)
        os._exit(125)
    os.close(ready_write)
    if os.read(ready_read, 1) != b"1" or identity(parent) != original:
        os.kill(watcher, signal.SIGKILL)
        raise SystemExit(125)
    os.close(ready_read)
    os.execvpe(argv[0], argv, os.environ)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        try:
            error_fd = int(sys.argv[2])
            if error_fd >= 0:
                os.write(error_fd, b"launch_failed")
        finally:
            os._exit(125)
