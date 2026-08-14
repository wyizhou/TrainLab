"""Minimal, credential-free runtime environment helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def bounded_runtime_path(value: str | None = None) -> str:
    """Keep usable absolute PATH directories without forwarding other environment.

    The caller still supplies a fresh environment containing only this value and
    explicit locale settings.  This lets a supervised process find the Codex
    CLI and the Gmail MCP's ``npx`` command on macOS without binding either to
    a machine-specific executable path.
    """
    source = os.environ.get("PATH", "") if value is None else value
    if not isinstance(source, str):
        return ""
    accepted: list[str] = []
    seen: set[str] = set()
    for entry in source.split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        try:
            resolved = str(Path(entry).resolve(strict=True))
        except (OSError, RuntimeError):
            continue
        try:
            info = Path(resolved).stat()
        except OSError:
            continue
        if (
            resolved in seen
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, os.geteuid()}
            or bool(stat.S_IMODE(info.st_mode) & 0o002)
        ):
            continue
        seen.add(resolved)
        accepted.append(resolved)
    return os.pathsep.join(accepted)
