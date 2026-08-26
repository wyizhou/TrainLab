from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from skills._shared.state_fingerprint import formal_state_content_fingerprint


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _state_tree(tmp_path: Path, name: str = "source") -> tuple[Path, Path]:
    state = tmp_path / name / "state"
    raw = state / "raw/garmin/health"
    raw.mkdir(parents=True, mode=0o700)
    evidence = raw / "20260812-rhr.json"
    evidence.write_bytes(b"{}")
    os.chmod(evidence, 0o600)
    for directory in (state, state / "raw", state / "raw/garmin", raw):
        os.chmod(directory, 0o700)

    database = state / "trainlab.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE raw_files (relative_path TEXT, byte_size INTEGER, sha256 TEXT)"
    )
    connection.execute(
        "INSERT INTO raw_files VALUES (?,?,?)",
        ("garmin/health/20260812-rhr.json", 2, _sha256(b"{}")),
    )
    connection.commit()
    connection.close()
    os.chmod(database, 0o600)
    return database, state / "raw"


def test_content_fingerprint_is_stable_across_inode_and_mtime_changes(
    tmp_path: Path,
) -> None:
    database, raw_root = _state_tree(tmp_path)
    before = formal_state_content_fingerprint(database, raw_root)

    copied = tmp_path / "copied"
    shutil.copytree(database.parent.parent, copied)
    copied_database = copied / "state/trainlab.db"
    copied_raw = copied / "state/raw"
    os.utime(copied_database, ns=(1_000_000_000, 1_000_000_000))
    os.utime(
        copied_raw / "garmin/health/20260812-rhr.json",
        ns=(2_000_000_000, 2_000_000_000),
    )

    after = formal_state_content_fingerprint(copied_database, copied_raw)

    assert before == after
    assert before["schema_version"] == "formal_state_content_fingerprint_v1"
    assert before["entry_count"] == 2
    assert before["raw_file_count"] == 1


def test_content_fingerprint_changes_with_registered_bytes(tmp_path: Path) -> None:
    database, raw_root = _state_tree(tmp_path)
    before = formal_state_content_fingerprint(database, raw_root)
    evidence = raw_root / "garmin/health/20260812-rhr.json"
    evidence.write_bytes(b'{"changed":true}')
    os.chmod(evidence, 0o600)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE raw_files SET byte_size=?, sha256=?",
        (evidence.stat().st_size, _sha256(evidence.read_bytes())),
    )
    connection.commit()
    connection.close()
    os.chmod(database, 0o600)

    after = formal_state_content_fingerprint(database, raw_root)

    assert before["sha256"] != after["sha256"]


def test_content_fingerprint_rejects_finder_metadata(tmp_path: Path) -> None:
    database, raw_root = _state_tree(tmp_path)
    finder = raw_root / ".DS_Store"
    finder.write_bytes(b"finder")
    os.chmod(finder, 0o600)

    with pytest.raises(ValueError, match="formal_state_finder_metadata_forbidden"):
        formal_state_content_fingerprint(database, raw_root)
