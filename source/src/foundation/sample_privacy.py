"""Synthetic-sample privacy and owner-only filesystem helpers."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path


def write_owner_file(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.chmod(path, 0o600)


def secure_tree(root: Path) -> None:
    for path in sorted(
        root.rglob("*"), key=lambda value: len(value.parts), reverse=True
    ):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(root, 0o700)


def scan_privacy(root: Path, tables: dict[str, str]) -> list[str]:
    patterns = (
        ("email_address", r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"),
        (
            "credential",
            r"(?:access|refresh)[_-]?token|api[_-]?key|password|client[_-]?secret|begin private key",
        ),
        ("authorization_url", r"https?://accounts\.google|authorization\s*[:=]"),
        (
            "raw_html",
            r"<!doctype\s+html|</?(?:html|head|body|script|style|div|span|p|table|form|iframe)\b",
        ),
        (
            "full_payload",
            r"full[_ -]?(?:provider|model)?[_ -]?payload|raw[_ -]?model[_ -]?response",
        ),
        (
            "hidden_reasoning",
            r"chain[_ -]?of[_ -]?thought|hidden[_ -]?reasoning|<thinking>",
        ),
    )
    values: list[tuple[str, str]] = []
    conn = sqlite3.connect(root / "data.db")
    try:
        for table in tables:
            columns = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
                if row[2].upper() in {"TEXT", "BLOB"}
            ]
            if columns:
                selected = ",".join(f'"{column}"' for column in columns)
                for row_index, row in enumerate(
                    conn.execute(f'SELECT {selected} FROM "{table}"')
                ):
                    for column, value in zip(columns, row):
                        if value is not None:
                            values.append(
                                (
                                    f"database:{table}:{row_index}:{column}",
                                    value.decode("utf-8", "replace")
                                    if isinstance(value, bytes)
                                    else str(value),
                                )
                            )
    finally:
        conn.close()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "data.db":
            values.append(
                (
                    f"file:{path.relative_to(root)}",
                    path.read_bytes().decode("utf-8", "replace"),
                )
            )
    return sorted(
        f"{code}:{location}"
        for location, value in values
        for code, pattern in patterns
        if re.search(pattern, value.lower())
    )
