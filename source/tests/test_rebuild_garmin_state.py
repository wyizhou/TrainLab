from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from src.foundation import FoundationConfig, FoundationRequest, FoundationTool
from tools.rebuild_garmin_state import rebuild


def _config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "runtime",
        root / "runtime" / "foundation-ready.json",
        root / "runtime" / "locks" / "foundation.lock",
    )


def _init_store(root: Path) -> None:
    result = FoundationTool(_config(root)).execute(
        FoundationRequest("init", "rebuild-fixture", "2026-08-13T00:00:00Z")
    )
    assert result.status == "initialized"


def _insert_raw(root: Path, relative_path: str, payload: bytes) -> None:
    destination = root / relative_path
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.write_bytes(payload)
    os.chmod(destination, 0o600)
    digest = hashlib.sha256(payload).hexdigest()
    connection = sqlite3.connect(root / "data.db")
    connection.execute(
        "INSERT INTO raw_objects"
        "(sha256,relative_path,media_type,size_bytes,provider,resource_kind,original_name,fetched_at_utc)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (
            digest,
            relative_path,
            "application/json",
            len(payload),
            "garmin",
            "health",
            Path(relative_path).name,
            "2026-08-13T00:00:00Z",
        ),
    )
    connection.commit()
    connection.close()


def test_rebuild_includes_backup_only_raw_and_registers_unresolved_legacy_fit(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy"
    backup = legacy / "backups" / "one"
    _init_store(legacy)
    _init_store(backup)
    _insert_raw(legacy, "raw/active.json", b"active")
    _insert_raw(backup, "raw/backup-only.json", b"backup-only")
    legacy_fit = legacy / "legacy" / "unknown.fit"
    legacy_fit.parent.mkdir(mode=0o700)
    legacy_fit.write_bytes(b"not-a-fit-but-safe-test-marker")
    os.chmod(legacy_fit, 0o600)

    output = tmp_path / "candidate"
    result = rebuild(legacy, output)
    assert result["counts"]["raw_objects"] == 2
    assert result["counts"]["backup_only_raw_objects"] == 1
    assert result["legacy_fit_candidates"] == 1
    assert result["unresolved_legacy_fit"] == 1
    assert sum(1 for path in (output / "raw").rglob("*") if path.is_file()) == 2
    assert all(
        path.stat().st_mode & 0o777 == 0o600
        for path in (output / "raw").rglob("*")
        if path.is_file()
    )
    assert all(
        path.stat().st_mode & 0o777 == 0o700
        for path in (output / "raw").rglob("*")
        if path.is_dir()
    )
    manifest = json.loads((output / "runtime" / "rebuild-manifest.json").read_text())
    assert manifest["source_kind"] == "garmin_offline_rebuild"
