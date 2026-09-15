from __future__ import annotations

import fcntl
import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from skills._shared.fit_weekly import publication_ledger, run_config, run_state, storage


class Stopped(SystemExit):
    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(128 + signum)


_requested: int | None = None


def check_stop() -> None:
    if _requested is not None:
        raise Stopped(_requested)


def stop(signum: int, frame: FrameType | None) -> None:
    global _requested
    _requested = signum
    raise Stopped(signum)


@contextmanager
def run(root: Path, command: str, *, initialize: bool = False) -> Iterator[dict]:
    global _requested
    _requested = None
    root = run_config.instance_path(root)
    if initialize and not root.exists():
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        storage.sync_dir(root.parent)
    storage.private_entry(root, directory=True)
    if command not in run_state.COMMANDS:
        raise ValueError("run_command_invalid")
    if not initialize and run_state.database_status(root)["database"] != "readable":
        raise ValueError("run_instance_unreadable")
    path = root / "lifecycle.lock"
    if not path.exists() and not path.is_symlink() and (root / "runtime/runs").exists():
        raise ValueError("run_lock_missing")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        storage.private_entry(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    previous = {}
    start = None
    try:
        os.fsync(fd)
        storage.sync_dir(root)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("lifecycle_busy") from None
        if initialize:
            storage.initialize(root, lifecycle_locked=True)
        if run_state.database_status(root)["database"] != "readable":
            raise ValueError("run_instance_unreadable")
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        start = run_state.begin(root, command, publication_ledger.utc_now())
        try:
            yield start
            check_stop()
        except Stopped as exc:
            run_state.finish(
                root, start, "stopped", publication_ledger.utc_now(), exc.signum
            )
            raise
        except BaseException:
            if _requested is not None:
                run_state.finish(
                    root, start, "stopped", publication_ledger.utc_now(), _requested
                )
                raise Stopped(_requested) from None
            run_state.finish(root, start, "failed", publication_ledger.utc_now())
            raise
        else:
            run_state.finish(root, start, "completed", publication_ledger.utc_now())
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        os.close(fd)
        _requested = None
