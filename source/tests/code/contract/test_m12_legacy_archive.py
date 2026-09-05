from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def module():
    spec = importlib.util.spec_from_file_location(
        "m12_archive", ROOT / "skills/_shared/scripts/archive_legacy.py"
    )
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


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


def test_archive_preserves_source_and_recovers_without_original(tmp_path: Path) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    before = archive.fingerprint(source)
    target = archive.create_archive(source, tmp_path / "data-backup", names)
    assert archive.fingerprint(source) == before
    result = archive.verify_archive(target)
    assert result["status"] == "verified"
    assert result["provider_calls"] == result["external_actions"] == 0
    assert (target / "legacy-state/raw/activities/synthetic.fit").read_bytes() == (
        source / "state/raw/activities/synthetic.fit"
    ).read_bytes()
    assert not any(
        (target / "legacy-source" / name).exists()
        for name in ("goal.md", "email.json", "gmail-api-token.json")
    )
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["source_unchanged"] is True
    assert manifest["restore_drill"] == "passed"
    assert str(source) not in (target / "manifest.json").read_text()
    for path in (target, *target.rglob("*")):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
        assert path.stat().st_uid == os.getuid()
        if path.is_file():
            assert path.stat().st_nlink == 1
    source.rename(tmp_path / "original-is-unavailable")
    restored = tmp_path / "restored"
    archive.restore_archive(target, restored)
    with sqlite3.connect(
        (restored / "recovery/trainlab.db").as_uri() + "?mode=ro&immutable=1",
        uri=True,
    ) as connection:
        assert connection.execute("SELECT value FROM events").fetchall() == [
            ("synthetic",)
        ]
    assert archive.verify_archive(restored)["status"] == "verified"
    with pytest.raises(ValueError, match="restore_target_exists"):
        archive.restore_archive(target, restored)


def test_restore_rejects_target_inside_retained_archive(tmp_path: Path) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    target = archive.create_archive(source, tmp_path / "data-backup", names)
    before = archive.fingerprint(target)
    with pytest.raises(ValueError, match="restore_destination_invalid"):
        archive.restore_archive(target, target / "child")
    assert archive.fingerprint(target) == before


def test_bad_database_is_rejected_before_archive_creation(tmp_path: Path) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    (source / "state/trainlab.db").write_bytes(b"not a SQLite database")
    before = archive.fingerprint(source)
    with pytest.raises(sqlite3.DatabaseError):
        archive.create_archive(source, tmp_path / "data-backup", names)
    assert archive.fingerprint(source) == before
    assert not (tmp_path / "data-backup").exists()


@pytest.mark.parametrize("problem", ["nonempty_wal", "missing_lock", "contended_lock"])
def test_archive_preflight_does_not_touch_source_or_create_candidate(
    tmp_path: Path, problem: str
) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    lock = source / "state/trainlab.lock"
    if problem == "nonempty_wal":
        (source / "state/trainlab.db-wal").write_bytes(b"uncheckpointed")
    elif problem == "missing_lock":
        lock.unlink()
    descriptor = os.open(lock, os.O_RDONLY) if problem == "contended_lock" else None
    if descriptor is not None:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        before = archive.fingerprint(source)
        with pytest.raises(
            ValueError, match="formal_wal_nonempty|formal_state_lock_unavailable"
        ):
            archive.create_archive(source, tmp_path / "data-backup", names)
        assert archive.fingerprint(source) == before
        assert not (tmp_path / "data-backup").exists()
    finally:
        if descriptor is not None:
            os.close(descriptor)


@pytest.mark.parametrize(
    "entry",
    ["../outside", "/etc/passwd", "email.json", "gmail-api-token.json", "goal.md"],
)
def test_source_whitelist_rejects_private_or_escaping_entries(
    tmp_path: Path, entry: str
) -> None:
    archive = module()
    source, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="archive_source_path_invalid"):
        archive.create_archive(source, tmp_path / "data-backup", [entry])
    assert not (tmp_path / "data-backup").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory_symlink"])
def test_archive_rejects_unsupported_entries(tmp_path: Path, kind: str) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    path = source / "state/raw/extra"
    original = source / "state/raw/activities/synthetic.fit"
    if kind == "symlink":
        path.symlink_to(original)
    elif kind == "hardlink":
        os.link(original, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(original.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="archive_unsupported_entry"):
        archive.create_archive(source, tmp_path / "data-backup", names)


def test_archive_rejects_destination_inside_source(tmp_path: Path) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    with pytest.raises(ValueError, match="archive_destination_invalid"):
        archive.create_archive(source, source / "backups", names)


@pytest.mark.parametrize("failure", ["copy", "source_drift"])
def test_failed_archive_is_never_published(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    original_copy = archive.copy_file
    count = 0

    def intercepted(src, dest):
        nonlocal count
        count += 1
        if count == 2:
            if failure == "copy":
                raise OSError("synthetic finite disk failure")
            (source / "state/raw/activities/synthetic.fit").write_bytes(b"drift")
        return original_copy(src, dest)

    monkeypatch.setattr(archive, "copy_file", intercepted)
    with pytest.raises((OSError, ValueError)):
        archive.create_archive(source, tmp_path / "data-backup", names)
    assert not list((tmp_path / "data-backup").glob("m12-legacy-*"))
    assert list((tmp_path / "data-backup").glob(".m12-legacy-*.pending"))


@pytest.mark.parametrize("mutation", ["bytes", "extra", "permissions", "manifest"])
def test_archive_verification_rejects_tampering(tmp_path: Path, mutation: str) -> None:
    archive = module()
    source, names = fixture(tmp_path)
    target = archive.create_archive(source, tmp_path / "data-backup", names)
    if mutation == "bytes":
        (target / "legacy-source/core.py").write_text("changed")
    elif mutation == "extra":
        (target / "undeclared").touch()
    elif mutation == "permissions":
        (target / "legacy-source/core.py").chmod(0o644)
    else:
        (target / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="archive_"):
        archive.verify_archive(target)
