from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

_GATE = Lock()


@contextmanager
def write_gate(timeout: float = 5.0) -> Iterator[None]:
    if timeout < 0 or not _GATE.acquire(timeout=timeout):
        raise ValueError("RUN_BUSY")
    try:
        yield
    finally:
        _GATE.release()


@contextmanager
def read_view(path: Path, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
    with write_gate(timeout):
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout
        )
        try:
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("unsupported journal mode")
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            connection.execute("SELECT count(*) FROM activities").fetchone()
            yield connection
        finally:
            connection.rollback()
            connection.close()
