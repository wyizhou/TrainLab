from __future__ import annotations

import os
from pathlib import Path


def write_private_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def write_private_text(path: Path, text: str) -> Path:
    return write_private_file(path, text.encode("utf-8"))


def make_dir(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


def chmod_tree(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            continue
        path.chmod(0o700 if path.is_dir() else 0o600)


def make_fifo(path: Path) -> Path:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.mkfifo(path, 0o600)
    return path
