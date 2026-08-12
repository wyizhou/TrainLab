"""Configuration-file security helpers for the Foundation layer."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def read_owner_only_bytes(path: Path, *, limit: int = 1024 * 1024) -> bytes:
    """Read a regular, owner-only file while rejecting symlink replacement."""
    parent = path.parent
    info = parent.lstat()
    if not (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o022 == 0):
        raise ValueError("unsafe_foundation_configuration")
    before = path.lstat()
    if not (stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode)
            and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) & 0o022 == 0):
        raise ValueError("unsafe_foundation_configuration")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("unsafe_foundation_configuration")
        chunks: list[bytes] = []
        total = 0
        while block := os.read(descriptor, 65536):
            total += len(block)
            if total > limit:
                raise ValueError("invalid_foundation_configuration")
            chunks.append(block)
        after = path.lstat()
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("unsafe_foundation_configuration")
        return b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
