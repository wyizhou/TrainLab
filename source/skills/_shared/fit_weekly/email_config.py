from __future__ import annotations

import os
import re
from pathlib import Path

from skills._shared.fit_weekly import gmail_message, run_config


def read(root: Path, value: str) -> str:
    try:
        path = run_config.private_path(root, value)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError("size")
        text = raw.decode("utf-8")
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("control")
        lines = [line.strip() for line in text.splitlines() if "@" in line]
        if len(lines) != 1 or text.count("@") != 1:
            raise ValueError("count")
        address = gmail_message.address(lines[0])
        if (
            re.fullmatch(
                r"[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}",
                address,
            )
            is None
        ):
            raise ValueError("address")
        return address
    except (ValueError, OSError, UnicodeError):
        raise ValueError("email_config_invalid") from None


def outside_repository(path: Path) -> None:
    path = run_config.instance_path(path)
    repository = run_config.SOURCE.parent
    boundary = repository if (repository / ".git").exists() else run_config.SOURCE
    if path.is_relative_to(boundary):
        raise ValueError("gmail_private_path_in_repository")
