from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from skills._shared.fit_weekly import history_archive


def fixture(root: Path) -> tuple[Path, list[str]]:
    source = root / "source"
    raw = source / "state/raw/activities"
    raw.mkdir(parents=True, mode=0o700)
    (raw / "synthetic.fit").write_bytes(b"public synthetic archive fixture")
    database = source / "state/trainlab.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO events VALUES(1, 'synthetic')")
    (source / "state/trainlab.lock").touch()
    (source / "state/trainlab.db-wal").touch()
    (source / "state/trainlab.db-shm").write_bytes(b"synthetic sidecar")
    (source / "core.py").write_text("ANSWER = 42\n")
    (source / "nested/code").mkdir(parents=True)
    (source / "nested/code/design-tokens.json").write_text('{"color":"blue"}')
    (source / "empty-marker").touch()
    for name in ("goal.md", "email.json", "gmail-api-token.json"):
        (source / name).write_text("private fixture must not be copied")
    for path in source.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    source.chmod(0o700)
    return source, ["core.py", "empty-marker", "nested/code/design-tokens.json"]


def pack(source: Path, parent: Path, names: list[str]) -> Path:
    target = parent / "synthetic-history"
    target.mkdir(parents=True, mode=0o700)
    for path in [source / name for name in names]:
        dest = target / "legacy-source" / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest.write_bytes(path.read_bytes())
    shutil.copytree(source / "state", target / "legacy-state")
    recovery = target / "recovery/trainlab.db"
    recovery.parent.mkdir(mode=0o700)
    recovery.write_bytes((source / "state/trainlab.db").read_bytes())
    for path in target.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    files, directories = history_archive.inventory(target)
    manifest = {
        "schema_version": "legacy_archive_v1",
        "files": files,
        "directories": directories,
        "source_before": {},
        "source_unchanged": True,
        "restore_drill": "passed",
        "database_digest": history_archive.database_check(recovery),
        "provider_calls": 0,
        "external_actions": 0,
    }
    (target / "manifest.json").write_text(json.dumps(manifest))
    (target / "manifest.json").chmod(0o600)
    return target
