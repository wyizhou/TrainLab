from __future__ import annotations

import hashlib
import importlib
import os
import sqlite3
import stat
import struct
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))


def module():
    return importlib.import_module("skills._shared.fit_weekly.storage")


def synthetic_fit() -> bytes:
    """A real CRC-valid, anonymous FIT with file_id and one session."""
    from fitdecode.utils import compute_crc

    data = bytes([0x40, 0, 0]) + struct.pack("<H", 0) + bytes([1, 0, 1, 0])
    data += bytes([0, 4])  # file_id.type = activity
    data += bytes([0x41, 0, 0]) + struct.pack("<H", 18)
    data += bytes([3, 253, 4, 0x86, 2, 4, 0x86, 5, 1, 0])
    data += bytes([1]) + struct.pack("<IIB", 1000003600, 1000000000, 1)
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(data), b".FIT")
    header += struct.pack("<H", compute_crc(header))
    return header + data + struct.pack("<H", compute_crc(header + data))


def fit_file(tmp_path: Path) -> Path:
    p = tmp_path / "source.fit"
    p.write_bytes(synthetic_fit())
    p.chmod(0o600)
    return p


def test_initialize_reopen_and_relative_relocation(tmp_path: Path) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    before = (root / "trainlab-fit.db").read_bytes()
    store.initialize(root)
    assert (root / "trainlab-fit.db").read_bytes() == before
    with store.open_store(root) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    moved = tmp_path / "moved"
    root.rename(moved)
    with store.open_store(moved) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    for p in [moved, *moved.rglob("*")]:
        assert p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)


def test_missing_store_is_not_silently_created(tmp_path: Path) -> None:
    store = module()
    root = tmp_path / "missing"
    with pytest.raises(ValueError, match="store_missing"):
        with store.open_store(root):
            pass
    assert not root.exists()


def test_initialization_rejects_existing_foreign_data(tmp_path: Path) -> None:
    store = module()
    root = tmp_path / "old-state"
    root.mkdir(mode=0o700)
    old = root / "trainlab.db"
    old.write_bytes(b"old private database")
    with pytest.raises(ValueError, match="store_destination_not_empty"):
        store.initialize(root)
    assert old.read_bytes() == b"old private database"
    assert not (root / "trainlab-fit.db").exists()


def test_fit_is_crc_checked_copied_and_reused_without_source_dependency(
    tmp_path: Path,
) -> None:
    store = module()
    original = fit_file(tmp_path)
    before = original.stat()
    root = tmp_path / "instance"
    store.initialize(root)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    with store.open_store(root) as db:
        first = store.import_fit(db, root, "101", original, digest)
        assert first == store.import_fit(db, root, "101", original, digest)
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM activity_fits").fetchone()[0] == 1
        assert first == f"fits/{digest}.fit"
    assert original.stat().st_ino == before.st_ino
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    original.unlink()
    with store.open_store(root) as db:
        assert store.verify_fit_closure(db, root) == 1
    assert (root / first).stat().st_nlink == 1


@pytest.mark.parametrize(
    "case", ["hash", "crc", "empty", "symlink", "hardlink", "mode"]
)
def test_bad_fit_never_enters_database(tmp_path: Path, case: str) -> None:
    store = module()
    p = fit_file(tmp_path)
    if case == "crc":
        p.write_bytes(p.read_bytes()[:-1] + b"\xff")
    if case == "empty":
        p.write_bytes(b"")
    if case == "mode":
        p.chmod(0o644)
    if case == "symlink":
        link = tmp_path / "link.fit"
        link.symlink_to(p)
        p = link
    if case == "hardlink":
        os.link(p, tmp_path / "hard.fit")
    digest = "0" * 64 if case == "hash" else hashlib.sha256(p.read_bytes()).hexdigest()
    root = tmp_path / "instance"
    store.initialize(root)
    with store.open_store(root) as db:
        with pytest.raises(ValueError):
            store.import_fit(db, root, "101", p, digest)
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0
        assert list((root / "fits").iterdir()) == []


def test_cross_activity_fit_reuse_is_rejected(tmp_path: Path) -> None:
    store = module()
    p = fit_file(tmp_path)
    root = tmp_path / "instance"
    store.initialize(root)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with store.open_store(root) as db:
        store.import_fit(db, root, "101", p, digest)
        with pytest.raises(ValueError, match="fit_activity_conflict"):
            store.import_fit(db, root, "202", p, digest)


def test_document_and_parse_identity_cannot_be_replaced(tmp_path: Path) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    p = fit_file(tmp_path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with store.open_store(root) as db:
        store.import_fit(db, root, "101", p, digest)
        key = store.put_parse(db, digest, "1", {"distance_m": 1000})
        assert store.put_parse(db, digest, "1", {"distance_m": 1000}) == key
        with pytest.raises(ValueError, match="immutable_result_conflict"):
            store.put_parse(db, digest, "1", {"distance_m": 2000})
        assert store.put_parse(db, digest, "2", {"distance_m": 2000}) != key
        result = store.put_document(
            db, "weekly_report", "week-1", digest, {"summary": "合成"}
        )
        assert result == store.put_document(
            db, "weekly_report", "week-1", digest, {"summary": "合成"}
        )
        with pytest.raises(ValueError, match="immutable_result_conflict"):
            store.put_document(
                db, "weekly_report", "week-1", digest, {"summary": "变化"}
            )
        for sql in (
            "DELETE FROM documents",
            "UPDATE documents SET content_json='{}'",
            "INSERT OR REPLACE INTO documents SELECT * FROM documents",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_open_store_rolls_back_and_writer_lock_is_exclusive(tmp_path: Path) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    with pytest.raises(RuntimeError):
        with store.open_store(root) as db:
            with pytest.raises(ValueError, match="store_busy"):
                with store.open_store(root):
                    pass
            store.put_document(db, "weekly_input", "week-1", "a" * 64, {"ok": True})
            raise RuntimeError("simulated finite crash")
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_orphan_file_after_rollback_can_be_reconciled_without_duplicate(
    tmp_path: Path,
) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    p = fit_file(tmp_path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError):
        with store.open_store(root) as db:
            store.import_fit(db, root, "101", p, digest)
            raise RuntimeError("crash before SQL commit")
    with store.open_store(root) as db:
        with pytest.raises(ValueError, match="fit_files_not_closed"):
            store.verify_fit_closure(db, root)
        store.import_fit(db, root, "101", p, digest)
        assert store.verify_fit_closure(db, root) == 1


@pytest.mark.parametrize(
    "case", ["schema", "database_mode", "lock_missing", "fit_changed", "extra_file"]
)
def test_corruption_or_permissions_fail_closed(tmp_path: Path, case: str) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    p = fit_file(tmp_path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with store.open_store(root) as db:
        relative = store.import_fit(db, root, "101", p, digest)
    if case == "schema":
        with sqlite3.connect(root / "trainlab-fit.db") as db:
            db.execute("DROP TABLE documents")
    elif case == "database_mode":
        (root / "trainlab-fit.db").chmod(0o644)
    elif case == "lock_missing":
        (root / "writer.lock").unlink()
    elif case == "fit_changed":
        (root / relative).write_bytes(b"changed")
    else:
        extra = root / "fits/extra.fit"
        extra.write_bytes(b"extra")
        extra.chmod(0o600)
    with pytest.raises(ValueError):
        with store.open_store(root) as db:
            store.verify_fit_closure(db, root)


def test_connection_cannot_write_files_into_another_instance(tmp_path: Path) -> None:
    store = module()
    first, second = tmp_path / "first", tmp_path / "second"
    store.initialize(first)
    store.initialize(second)
    p = fit_file(tmp_path)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    with store.open_store(first) as db:
        with pytest.raises(ValueError, match="store_instance_mismatch"):
            store.import_fit(db, second, "101", p, sha)
        assert not list((second / "fits").iterdir())
        assert not list((first / "fits").iterdir())


@pytest.mark.parametrize("operation", ["write", "rename", "fsync"])
def test_finite_file_failure_cannot_commit_an_index(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    p = fit_file(tmp_path)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()

    def fail(*args, **kwargs):
        raise OSError("synthetic finite IO failure")

    target = "fdopen" if operation == "write" else operation
    with monkeypatch.context() as patch:
        patch.setattr(store.os, target, fail)
        with pytest.raises(OSError):
            with store.open_store(root) as db:
                store.import_fit(db, root, "101", p, sha)
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0
    assert not (root / f"fits/{sha}.fit").exists()


def test_parse_foreign_key_canonical_replay_and_no_legacy_imports(
    tmp_path: Path,
) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    with store.open_store(root) as db:
        with pytest.raises(sqlite3.IntegrityError):
            store.put_parse(db, "a" * 64, "1", {"sample": 1})
        first = store.put_document(
            db, "weekly_input", "week-1", "a" * 64, {"b": 2, "a": 1}
        )
        second = store.put_document(
            db, "weekly_input", "week-1", "a" * 64, {"a": 1, "b": 2}
        )
        assert first == second
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        with pytest.raises(ValueError):
            store.put_document(
                db, "weekly_input", "week-2", "a" * 64, {"bad": float("nan")}
            )
    import ast

    tree = ast.parse(Path(store.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert all(not name or not name.startswith("skills.") for name in imports)


@pytest.mark.parametrize("replay_failure", [None, "file", "directory"])
def test_renamed_orphan_replay_completes_durability_before_sql_commit(
    tmp_path: Path, monkeypatch, replay_failure: str | None
) -> None:
    store = module()
    root = tmp_path / "instance"
    store.initialize(root)
    source = fit_file(tmp_path)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()

    def directory_failure(*args):
        raise OSError("finite directory fsync failure after rename")

    with monkeypatch.context() as patch:
        patch.setattr(store, "sync_dir", directory_failure)
        with pytest.raises(OSError):
            with store.open_store(root) as db:
                store.import_fit(db, root, "101", source, sha)
    assert (root / f"fits/{sha}.fit").exists()
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0
    events = []
    original_fsync = store.os.fsync

    def observed_fsync(fd):
        kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        events.append(kind)
        if kind == replay_failure:
            raise OSError("finite replay persistence failure")
        return original_fsync(fd)

    def replay():
        with store.open_store(root) as db:
            db.set_trace_callback(
                lambda sql: events.append("commit") if sql == "COMMIT" else None
            )
            store.import_fit(db, root, "101", source, sha)

    with monkeypatch.context() as patch:
        patch.setattr(store.os, "fsync", observed_fsync)
        if replay_failure:
            with pytest.raises(OSError):
                replay()
        else:
            replay()
    if replay_failure:
        assert "commit" not in events
        with store.open_store(root) as db:
            assert db.execute("SELECT COUNT(*) FROM fits").fetchone()[0] == 0
            store.import_fit(db, root, "101", source, sha)
    else:
        assert events == ["file", "directory", "commit"]
    with store.open_store(root) as db:
        assert store.verify_fit_closure(db, root) == 1
