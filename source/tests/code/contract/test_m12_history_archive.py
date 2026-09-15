from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import history_archive

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
fixture = importlib.import_module("m12_history_factory")


def archive_at(tmp_path):
    source, names = fixture.fixture(tmp_path)
    return source, fixture.pack(source, tmp_path / "history", names)


def test_readonly_verification_and_immutable_database_survive_relocation(tmp_path):
    source, archive = archive_at(tmp_path)
    before = history_archive.fingerprint(archive)
    original = history_archive.fingerprint(source)
    assert history_archive.verify_archive(archive)["status"] == "verified"
    db = history_archive.immutable_database(archive / "recovery/trainlab.db")
    try:
        assert db.execute("SELECT value FROM events").fetchall() == [("synthetic",)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO events VALUES(2, 'forbidden')")
    finally:
        db.close()
    assert history_archive.fingerprint(archive) == before
    assert history_archive.fingerprint(source) == original
    source.rename(tmp_path / "source-unavailable")
    moved = tmp_path / "moved"
    archive.rename(moved)
    assert history_archive.verify_archive(moved)["status"] == "verified"
    assert not (moved / "recovery/trainlab.db-wal").exists()
    assert not (moved / "recovery/trainlab.db-shm").exists()


@pytest.mark.parametrize("mutation", ["bytes", "extra", "permissions", "manifest"])
def test_archive_verification_rejects_tampering_without_writes(tmp_path, mutation):
    _, archive = archive_at(tmp_path)
    if mutation == "bytes":
        (archive / "legacy-source/core.py").write_text("changed")
    elif mutation == "extra":
        (archive / "undeclared").touch()
    elif mutation == "permissions":
        (archive / "legacy-source/core.py").chmod(0o644)
    else:
        (archive / "manifest.json").write_text("{}")
    before = history_archive.fingerprint(archive)
    with pytest.raises(ValueError, match="archive_"):
        history_archive.verify_archive(archive)
    assert history_archive.fingerprint(archive) == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory_symlink"])
def test_archive_verification_rejects_unsupported_entries(tmp_path, kind):
    _, archive = archive_at(tmp_path)
    path = archive / "extra"
    original = archive / "legacy-source/core.py"
    if kind == "symlink":
        path.symlink_to(original)
    elif kind == "hardlink":
        os.link(original, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(original.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="archive_unsupported_entry"):
        history_archive.verify_archive(archive)
    assert path.lstat()


@pytest.mark.parametrize("kind", ["pending_name", "pending_drill", "database", "sha"])
def test_incomplete_or_invalid_archive_never_becomes_import_authority(tmp_path, kind):
    _, archive = archive_at(tmp_path)
    path = archive / "manifest.json"
    value = json.loads(path.read_text())
    if kind == "pending_name":
        destination = archive.with_suffix(".pending")
        archive.rename(destination)
        archive = destination
    elif kind == "pending_drill":
        value["restore_drill"] = "pending"
        path.write_text(json.dumps(value))
    elif kind == "database":
        (archive / "recovery/trainlab.db").write_bytes(b"invalid database")
    else:
        value["database_digest"] = "a" * 64
        path.write_text(json.dumps(value))
    before = history_archive.fingerprint(archive)
    with pytest.raises(ValueError, match="archive_"):
        history_archive.verify_archive(archive)
    assert history_archive.fingerprint(archive) == before


def test_retained_history_verifier_has_no_live_state_or_archive_executor():
    assert not any(
        hasattr(history_archive, name)
        for name in ("create_archive", "restore_archive", "formal_lock", "main")
    )
    assert "shutil" not in history_archive.__dict__
