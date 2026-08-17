#!/usr/bin/env python3
"""Build an isolated M8 candidate from the formal state without mutating it."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import sqlite3
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state import canonical_json, connect, sha256_file  # noqa: E402

FORMAL_DB_RELATIVE = Path("state/trainlab.db")
FORMAL_WAL_RELATIVE = Path("state/trainlab.db-wal")
FORMAL_SHM_RELATIVE = Path("state/trainlab.db-shm")
FORMAL_LOCK_RELATIVE = Path("state/trainlab.lock")


def _assert_owner_only(path: Path, *, regular: bool = True) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("formal_state_lock_unavailable") from exc
    if regular and not stat.S_ISREG(metadata.st_mode):
        raise ValueError("formal_state_lock_unavailable")
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o777 != 0o600:
        raise ValueError("formal_state_lock_unavailable")
    return metadata


@contextmanager
def _formal_state_lock(source_root: Path) -> Iterator[None]:
    """Acquire the pre-existing formal lock without creating or changing it."""

    lock_path = source_root / FORMAL_LOCK_RELATIVE
    _assert_owner_only(lock_path)
    try:
        descriptor = os.open(lock_path, os.O_RDONLY)
    except OSError as exc:
        raise ValueError("formal_state_lock_unavailable") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("formal_state_lock_unavailable") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _formal_wal_path(source_root: Path) -> Path:
    return source_root / FORMAL_WAL_RELATIVE


def _assert_formal_wal_empty(source_root: Path) -> None:
    wal = _formal_wal_path(source_root)
    if wal.exists() and wal.stat().st_size != 0:
        raise ValueError("formal_wal_nonempty")


def _entry_fingerprint(path: Path, relative: Path) -> dict[str, object]:
    metadata = path.lstat()
    mode = metadata.st_mode
    if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise ValueError("formal_state_unsupported_entry")
    entry: dict[str, object] = {
        "path": relative.as_posix(),
        "type": "file" if stat.S_ISREG(mode) else "directory",
        "dev": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(mode & 0o777),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }
    if stat.S_ISREG(mode):
        entry["sha256"] = sha256_file(path)
    return entry


def _formal_state_fingerprint(source_root: Path) -> dict[str, object]:
    """Capture immutable metadata for the formal DB, lock and complete raw tree."""

    state_root = source_root / "state"
    required = (
        state_root / FORMAL_DB_RELATIVE.relative_to("state"),
        state_root / FORMAL_LOCK_RELATIVE.relative_to("state"),
    )
    for path in required:
        if not path.is_file() or path.is_symlink():
            raise ValueError("formal_state_unavailable")
    _assert_owner_only(required[0])
    _assert_owner_only(required[1])
    _assert_formal_wal_empty(source_root)
    raw_root = state_root / "raw"
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise ValueError("formal_raw_unavailable")
    entries: list[dict[str, object]] = []
    selected = [
        state_root / "trainlab.db",
        state_root / "trainlab.db-wal",
        state_root / "trainlab.db-shm",
        state_root / "trainlab.lock",
    ]
    for path in selected:
        if path.exists() or path.is_symlink():
            entries.append(_entry_fingerprint(path, path.relative_to(state_root)))
    for path in sorted(raw_root.rglob("*")):
        entries.append(_entry_fingerprint(path, path.relative_to(state_root)))
    entries.sort(key=lambda item: str(item["path"]))
    digest = hashlib.sha256(canonical_json(entries).encode("utf-8")).hexdigest()
    return {
        "schema_version": "formal_state_fingerprint_v1",
        "entries": entries,
        "entry_count": len(entries),
        "raw_entry_count": sum(
            1 for item in entries if str(item["path"]).startswith("raw/")
        ),
        "sha256": digest,
    }


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    descriptor = os.open(temporary, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _cleanup_candidate_sidecars(candidate_db: Path) -> None:
    """Remove only confirmed-empty candidate sidecars."""

    for sidecar in (
        candidate_db.with_name(candidate_db.name + "-wal"),
        candidate_db.with_name(candidate_db.name + "-shm"),
    ):
        if not sidecar.exists():
            continue
        if sidecar.stat().st_size != 0:
            raise ValueError("candidate_wal_nonempty")
        sidecar.unlink()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)


def _online_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    # Immutable mode is intentional here: the formal database is an input
    # snapshot only.  A plain ``mode=ro`` connection may still create or
    # refresh SQLite sidecars while inspecting a WAL-backed file.
    source_conn = sqlite3.connect(
        f"file:{source.resolve()}?mode=ro&immutable=1", uri=True
    )
    target_conn = sqlite3.connect(temporary)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        source_conn.close()
        target_conn.close()
    os.replace(temporary, destination)
    os.chmod(destination, 0o600)


def _build_unlocked(source_root: Path, candidate_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    candidate_root = candidate_root.resolve()
    if candidate_root == source_root or source_root in candidate_root.parents:
        raise ValueError("candidate_must_be_outside_source")
    if candidate_root.exists():
        if not candidate_root.is_dir() or any(candidate_root.iterdir()):
            raise ValueError("candidate_already_exists")
        os.chmod(candidate_root, 0o700)
    else:
        candidate_root.mkdir(mode=0o700, parents=True)
    candidate_source = candidate_root / "source"
    candidate_source.mkdir(mode=0o700)
    for name in ("AGENTS.md", "requirements.txt", "config.json", "goal.module.md"):
        _copy_file(source_root / name, candidate_source / name)
    goal = source_root / "goal.md"
    if not goal.is_file() or goal.stat().st_mode & 0o777 != 0o600:
        raise ValueError("goal_missing_or_permissions")
    _copy_file(goal, candidate_source / "goal.md")
    shutil.copytree(
        source_root / "skills",
        candidate_source / "skills",
        ignore=shutil.ignore_patterns("__pycache__", ".ruff_cache", ".mypy_cache"),
    )
    os.chmod(candidate_source / "skills", 0o700)
    for path in (candidate_source / "skills").rglob("*"):
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
    if (source_root / "templates").is_dir():
        shutil.copytree(source_root / "templates", candidate_source / "templates")
        os.chmod(candidate_source / "templates", 0o700)
        for path in (candidate_source / "templates").rglob("*"):
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
    state = candidate_source / "state"
    raw = state / "raw"
    raw.mkdir(mode=0o700, parents=True)
    formal_db = source_root / "state/trainlab.db"
    candidate_db = state / "trainlab.db"
    _online_backup(formal_db, candidate_db)
    connection = connect(formal_db, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT relative_path,byte_size,sha256 FROM raw_files ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        relative = Path(str(row[0]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("raw_path_invalid")
        source_file = source_root / "state/raw" / relative
        if not source_file.is_file() or source_file.is_symlink():
            raise ValueError("raw_source_missing")
        if source_file.stat().st_size != int(row[1]) or sha256_file(source_file) != str(
            row[2]
        ):
            raise ValueError("raw_source_hash_mismatch")
        _copy_file(source_file, raw / relative)
    for path in raw.rglob("*"):
        if path.is_dir():
            os.chmod(path, 0o700)
    os.chmod(state, 0o700)
    # Opening writable candidate state applies the current trigger set.  This
    # is intentionally never done against the formal database.
    candidate_connection = connect(candidate_db)
    candidate_connection.close()
    _cleanup_candidate_sidecars(candidate_db)
    return {
        "candidate_root": str(candidate_root),
        "candidate_source": str(candidate_source),
        "database": str(candidate_db),
        "raw_count": len(rows),
        "raw_bytes": sum(int(row[1]) for row in rows),
    }


def build(source_root: Path, candidate_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    with _formal_state_lock(source_root):
        before = _formal_state_fingerprint(source_root)
        result = _build_unlocked(source_root, candidate_root)
        after = _formal_state_fingerprint(source_root)
        if before != after:
            raise ValueError("formal_state_changed_during_snapshot")
        snapshot = candidate_root.resolve() / "formal-state-fingerprint.json"
        _write_private_json(
            snapshot,
            {
                "schema_version": "m8_snapshot_receipt_v1",
                "before": before,
                "after": after,
                "formal_state_unchanged": True,
            },
        )
        result["formal_state_fingerprint_sha256"] = str(before["sha256"])
        result["formal_state_unchanged"] = True
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source_root, args.candidate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
