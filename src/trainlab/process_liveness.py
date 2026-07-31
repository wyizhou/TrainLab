"""Portable process liveness checks with Linux zombie awareness."""

from __future__ import annotations

import os
from pathlib import Path

_PROC_ROOT = Path("/proc")


def _parse_linux_stat(raw: str) -> tuple[str, int] | None:
    closing = raw.rfind(")")
    if closing < 0:
        return None
    fields = raw[closing + 1 :].split()
    if len(fields) < 3 or len(fields[0]) != 1:
        return None
    try:
        return fields[0], int(fields[2])
    except ValueError:
        return None


def _linux_proc_available() -> bool:
    return (_PROC_ROOT / "self/stat").is_file()


def process_is_running(pid: int) -> bool:
    """Return false for an absent process or a Linux zombie."""
    if type(pid) is not int or isinstance(pid, bool) or pid <= 0:
        return False
    if _linux_proc_available():
        try:
            parsed = _parse_linux_stat(
                (_PROC_ROOT / str(pid) / "stat").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return False
        except OSError:
            parsed = None
        if parsed is not None:
            return parsed[0] != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def process_group_has_live_members(pgid: int) -> bool:
    """Return true only while a process group has an executable member.

    On Linux, an orphan zombie can remain visible indefinitely when container
    PID 1 does not reap children. Such an entry cannot execute or perform a
    side effect, so it is not a live member. Platforms without a trustworthy
    ``/proc`` view retain the conservative ``killpg(..., 0)`` behavior.
    """
    if type(pgid) is not int or isinstance(pgid, bool) or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    if not _linux_proc_available():
        return True

    scan_complete = True
    try:
        entries = tuple(_PROC_ROOT.iterdir())
    except OSError:
        return True
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            parsed = _parse_linux_stat((entry / "stat").read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except OSError:
            scan_complete = False
            continue
        if parsed is None:
            scan_complete = False
            continue
        state, process_group = parsed
        if process_group == pgid and state != "Z":
            return True
    return not scan_complete
