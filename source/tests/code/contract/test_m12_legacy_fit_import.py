from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def fixture(root: Path):
    return importlib.import_module("test_m12_legacy_archive").fixture(root)


def storage_module():
    return importlib.import_module("skills._shared.fit_weekly.storage")


def synthetic_fit() -> bytes:
    return importlib.import_module("test_m12_storage").synthetic_fit()


def importer():
    return importlib.import_module("skills._shared.fit_weekly.legacy_import")


def archive_fixture(tmp_path: Path, case: str = "valid") -> Path:
    archive = importlib.import_module("skills._shared.scripts.archive_legacy")
    source, names = fixture(tmp_path)
    unregistered = source / "state/raw/activities/unregistered.fit"
    unregistered.write_bytes(synthetic_fit())
    unregistered.chmod(0o600)
    raw = source / "state/raw/activities/synthetic.fit"
    raw.write_bytes(synthetic_fit())
    store = storage_module()
    sha = store.digest(raw.read_bytes())
    # Legacy raw_files.relative_path is relative to state/raw, not state.
    relative = "activities/synthetic.fit"
    if case == "path":
        relative = "../goal.md"
    if case == "hash":
        sha = "f" * 64
    if case == "crc":
        raw.write_bytes(raw.read_bytes()[:-1] + b"\xff")
        sha = store.digest(raw.read_bytes())
    if case == "missing":
        raw.unlink()
    with sqlite3.connect(source / "state/trainlab.db") as db:
        db.executescript("""
        CREATE TABLE activity_inventory(id INTEGER PRIMARY KEY,provider TEXT,provider_activity_id TEXT,activity_date TEXT);
        CREATE TABLE raw_files(id INTEGER PRIMARY KEY,provider TEXT,data_class TEXT,
         file_format TEXT,activity_inventory_id INTEGER,activity_binding_state TEXT,
         integrity_state TEXT,data_date TEXT,relative_path TEXT,sha256 TEXT,byte_size INTEGER);
        """)
        db.execute(
            "INSERT INTO activity_inventory VALUES(1,'garmin','101','2026-08-01')"
        )
        db.execute(
            "INSERT INTO raw_files VALUES(1,?,?,?,?,?,?,?,?,?,?)",
            (
                "garmin",
                "activity",
                "fit",
                None if case == "unbound" else 1,
                "bound",
                "missing" if case == "integrity" else "verified",
                "2026-08-02" if case == "date" else "2026-08-01",
                relative,
                sha,
                12 if case == "size" else len(synthetic_fit()),
            ),
        )
        # Healthy-looking old files and unregistered FIT are not import members.
        db.execute(
            "INSERT INTO raw_files VALUES(2,'garmin','health','json',NULL,'not_applicable','verified','2026-08-01','not-copied.json',?,20)",
            ("a" * 64,),
        )
        if case == "duplicate_identity":
            db.execute(
                "INSERT INTO activity_inventory VALUES(2,'garmin','202','2026-08-01')"
            )
            db.execute(
                "INSERT INTO raw_files SELECT 3,provider,data_class,file_format,2,activity_binding_state,integrity_state,data_date,relative_path,sha256,byte_size FROM raw_files WHERE id=1"
            )
        if case == "before_2022":
            db.execute("UPDATE raw_files SET data_date='2021-12-31' WHERE id=1")
            db.execute("UPDATE activity_inventory SET activity_date='2021-12-31'")
    return archive.create_archive(source, tmp_path / "backup", names)


def test_import_is_registered_fit_only_and_independent_after_archive_removed(
    tmp_path: Path,
) -> None:
    archive = archive_fixture(tmp_path)
    migration = importer()
    root = tmp_path / "new-instance"
    result = migration.import_registered(archive, root)
    assert result["status"] == "complete"
    assert result["fit_count"] == 1
    assert result["provider_calls"] == result["external_actions"] == 0
    before = (root / "trainlab-fit.db").read_bytes()
    assert migration.import_registered(archive, root) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    archive.rename(tmp_path / "archive-offline")
    store = storage_module()
    with store.open_store(root) as db:
        assert store.verify_fit_closure(db, root) == 1
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        text = db.execute("SELECT content_json FROM documents").fetchone()[0]
        assert str(tmp_path) not in text
        assert json.loads(text) == result
    assert set(p.name for p in root.iterdir()) == {
        "fits",
        "writer.lock",
        "trainlab-fit.db",
    }


def test_legacy_raw_path_is_resolved_from_raw_root(tmp_path: Path) -> None:
    archive = archive_fixture(tmp_path)
    rows = importer().registered_fits(archive)
    assert rows[0]["source_member"] == "legacy-state/raw/activities/synthetic.fit"


@pytest.mark.parametrize(
    "case",
    [
        "path",
        "hash",
        "crc",
        "missing",
        "unbound",
        "integrity",
        "date",
        "size",
        "duplicate_identity",
    ],
)
def test_bad_registered_fit_fails_before_destination_creation(
    tmp_path: Path, case: str
) -> None:
    archive = archive_fixture(tmp_path, case)
    root = tmp_path / "new-instance"
    with pytest.raises(ValueError):
        importer().import_registered(archive, root)
    assert not root.exists()


def test_pre_2022_is_excluded_not_reported_as_complete_history(tmp_path: Path) -> None:
    archive = archive_fixture(tmp_path, "before_2022")
    result = importer().import_registered(archive, tmp_path / "new-instance")
    assert result["fit_count"] == 0
    assert result["history_coverage"] == "not_established"


def test_import_rejects_destination_inside_archive_and_preserves_source(
    tmp_path: Path,
) -> None:
    archive = archive_fixture(tmp_path)
    helper = importlib.import_module("skills._shared.scripts.archive_legacy")
    before = helper.fingerprint(archive)
    with pytest.raises(ValueError, match="legacy_import_destination_invalid"):
        importer().import_registered(archive, archive / "child")
    assert helper.fingerprint(archive) == before


def test_finite_interruption_replay_adopts_files_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = archive_fixture(tmp_path)
    migration = importer()
    root = tmp_path / "new-instance"
    put = migration.storage.put_document

    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(migration.storage, "put_document", fail)
    with pytest.raises(OSError):
        migration.import_registered(archive, root)
    with migration.storage.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0
    monkeypatch.setattr(migration.storage, "put_document", put)
    assert migration.import_registered(archive, root)["fit_count"] == 1
    with migration.storage.open_store(root) as db:
        assert migration.storage.verify_fit_closure(db, root) == 1


def test_archive_drift_during_copy_prevents_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = archive_fixture(tmp_path)
    migration = importer()
    copy = migration.storage.import_fit

    def drift(*args, **kwargs):
        result = copy(*args, **kwargs)
        (archive / "legacy-source/core.py").write_text("synthetic drift")
        return result

    monkeypatch.setattr(migration.storage, "import_fit", drift)
    root = tmp_path / "new-instance"
    with pytest.raises(ValueError):
        migration.import_registered(archive, root)
    with migration.storage.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0


def test_cli_relative_paths_and_redacted_failure(tmp_path: Path) -> None:
    archive = archive_fixture(tmp_path)
    source = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [
        sys.executable,
        "-m",
        "skills._shared.fit_weekly.legacy_import",
        "--archive",
        str(archive.relative_to(tmp_path)),
        "--destination",
        "new-instance",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0
    receipt = json.loads(result.stdout)
    assert receipt["fit_count"] == 1 and "members" not in receipt
    assert str(tmp_path) not in result.stdout + result.stderr
    command[-1] = str(archive.relative_to(tmp_path) / "child")
    bad = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert bad.returncode == 2
    assert json.loads(bad.stdout)["error_code"] == "legacy_import_destination_invalid"
    assert str(tmp_path) not in bad.stdout + bad.stderr
