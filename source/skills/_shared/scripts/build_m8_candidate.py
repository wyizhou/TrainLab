#!/usr/bin/env python3
"""Build an isolated M8 candidate from the formal state without mutating it."""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_file,
    sha256_text,
)

FORMAL_DB_RELATIVE = Path("state/trainlab.db")
FORMAL_WAL_RELATIVE = Path("state/trainlab.db-wal")
FORMAL_SHM_RELATIVE = Path("state/trainlab.db-shm")
FORMAL_LOCK_RELATIVE = Path("state/trainlab.lock")
SQLITE_SHM_LOCK_OFFSET = 120
SQLITE_SHM_LOCK_BYTES = 8
MutationResult = TypeVar("MutationResult")
RENAME_SWAP = 0x00000002


def _assert_owner_only(path: Path, *, regular: bool = True) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("formal_state_lock_unavailable") from exc
    if regular and not stat.S_ISREG(metadata.st_mode):
        raise ValueError("formal_state_lock_unavailable")
    if (
        metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o600
        or metadata.st_nlink != 1
    ):
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


@contextmanager
def _locked_inactive_sqlite_state(source_root: Path) -> Iterator[None]:
    """Hold the SHM lock while proving no SQLite handle is active."""

    sqlite_inodes: set[tuple[int, int]] = set()
    sqlite_paths: list[Path] = []
    for relative in (FORMAL_DB_RELATIVE, FORMAL_WAL_RELATIVE, FORMAL_SHM_RELATIVE):
        path = source_root / relative
        try:
            sqlite_metadata = path.lstat()
        except FileNotFoundError:
            continue
        sqlite_paths.append(path)
        sqlite_inodes.add((int(sqlite_metadata.st_dev), int(sqlite_metadata.st_ino)))
    shm = source_root / FORMAL_SHM_RELATIVE
    descriptor: int | None = None
    acquired = False
    try:
        if shm.exists() or shm.is_symlink():
            try:
                metadata = shm.lstat()
            except OSError as exc:
                raise ValueError("formal_state_unavailable") from exc
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise ValueError("formal_state_unavailable")
            flags = os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(shm, flags)
            except OSError as exc:
                raise ValueError("formal_state_unavailable") from exc
            opened_shm = os.fstat(descriptor)
            if (opened_shm.st_dev, opened_shm.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise ValueError("formal_state_unavailable")
            try:
                fcntl.lockf(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                    SQLITE_SHM_LOCK_BYTES,
                    SQLITE_SHM_LOCK_OFFSET,
                    os.SEEK_SET,
                )
                acquired = True
            except OSError as exc:
                raise ValueError("formal_state_active") from exc

        descriptor_root = next(
            (
                Path(item)
                for item in ("/dev/fd", "/proc/self/fd")
                if Path(item).is_dir()
            ),
            None,
        )
        if descriptor_root is None:
            raise ValueError("formal_state_unavailable")
        for descriptor_path in descriptor_root.iterdir():
            if not descriptor_path.name.isdigit():
                continue
            descriptor_number = int(descriptor_path.name)
            if descriptor is not None and descriptor_number == descriptor:
                continue
            try:
                opened = os.fstat(descriptor_number)
            except OSError:
                continue
            if (int(opened.st_dev), int(opened.st_ino)) in sqlite_inodes:
                raise ValueError("formal_state_active")

        lsof = Path("/usr/sbin/lsof")
        if not lsof.is_file():
            discovered = shutil.which("lsof")
            if discovered is None:
                raise ValueError("formal_state_unavailable")
            lsof = Path(discovered)
        try:
            observed = subprocess.run(
                [str(lsof), "-F", "p", "--", *(str(path) for path in sqlite_paths)],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("formal_state_unavailable") from exc
        if observed.returncode not in (0, 1):
            raise ValueError("formal_state_unavailable")
        external_pids = {
            int(line[1:])
            for line in observed.stdout.splitlines()
            if line.startswith("p") and line[1:].isdigit()
        } - {os.getpid()}
        if external_pids:
            raise ValueError("formal_state_active")
        yield
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.lockf(
                    descriptor,
                    fcntl.LOCK_UN,
                    SQLITE_SHM_LOCK_BYTES,
                    SQLITE_SHM_LOCK_OFFSET,
                    os.SEEK_SET,
                )
            os.close(descriptor)


def _assert_formal_shm_inactive(source_root: Path) -> None:
    """Reject a live SQLite handle without deleting a stale SHM file."""

    with _locked_inactive_sqlite_state(source_root):
        pass


def _entry_fingerprint(path: Path, relative: Path) -> dict[str, object]:
    metadata = path.lstat()
    mode = metadata.st_mode
    if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise ValueError("formal_state_unsupported_entry")
    if metadata.st_uid != os.getuid():
        raise ValueError("formal_state_unsafe_entry")
    if stat.S_ISDIR(mode):
        if stat.S_IMODE(mode) != 0o700:
            raise ValueError("formal_state_unsafe_entry")
    else:
        # Finder metadata is not part of the registered evidence set and is
        # intentionally excluded from every Candidate.  It is still included
        # in the before/after fingerprint, while all evidence and SQLite files
        # remain owner-only and single-link.
        is_finder_metadata = relative.name == ".DS_Store" and str(relative).startswith(
            "raw/"
        )
        if metadata.st_nlink != 1 or (
            not is_finder_metadata and stat.S_IMODE(mode) != 0o600
        ):
            raise ValueError("formal_state_unsafe_entry")
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
    _assert_formal_shm_inactive(source_root)
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


def _assert_candidate_sidecars_quiescent(candidate_db: Path) -> None:
    """Require a zero WAL and inactive Candidate SHM without deleting either."""

    wal = candidate_db.with_name(candidate_db.name + "-wal")
    shm = candidate_db.with_name(candidate_db.name + "-shm")
    metadata_by_path: dict[Path, os.stat_result] = {}
    for sidecar in (wal, shm):
        if not sidecar.exists() and not sidecar.is_symlink():
            continue
        metadata = sidecar.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise ValueError("candidate_sidecar_unsafe")
        metadata_by_path[sidecar] = metadata
    if wal in metadata_by_path and metadata_by_path[wal].st_size != 0:
        raise ValueError("candidate_wal_nonempty")
    if candidate_db.parent.name != "state":
        if metadata_by_path:
            raise ValueError("candidate_sidecar_unsafe")
        return
    try:
        with _locked_inactive_sqlite_state(candidate_db.parent.parent):
            for sidecar, expected in metadata_by_path.items():
                current = sidecar.lstat()
                if (
                    (current.st_dev, current.st_ino)
                    != (expected.st_dev, expected.st_ino)
                    or current.st_uid != os.getuid()
                    or stat.S_IMODE(current.st_mode) != 0o600
                    or current.st_nlink != 1
                    or current.st_size != expected.st_size
                ):
                    raise ValueError("candidate_sidecar_unsafe")
    except ValueError as exc:
        if str(exc) == "candidate_sidecar_unsafe":
            raise
        raise ValueError("candidate_shm_active") from exc


def _candidate_file_fingerprint(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise ValueError("candidate_sidecar_unsafe")
    return {
        "dev": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
        "sha256": sha256_file(path),
    }


def _stable_candidate_file_fingerprint(path: Path) -> dict[str, object]:
    fingerprint = _candidate_file_fingerprint(path)
    fingerprint.pop("ctime_ns", None)
    return fingerprint


def _candidate_database_fingerprint(candidate_db: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in (
        candidate_db,
        candidate_db.with_name(candidate_db.name + "-wal"),
        candidate_db.with_name(candidate_db.name + "-shm"),
    ):
        if not path.exists() and not path.is_symlink():
            continue
        entries.append({"name": path.name, **_candidate_file_fingerprint(path)})
    return {
        "entries": entries,
        "sha256": sha256_text(canonical_json(entries)),
    }


def _candidate_sidecar_fingerprint(candidate_db: Path) -> dict[str, object]:
    raw_entries = _candidate_database_fingerprint(candidate_db)["entries"]
    if not isinstance(raw_entries, list):
        raise ValueError("candidate_sidecar_unsafe")
    entries = [
        item
        for item in raw_entries
        if isinstance(item, dict) and item.get("name") != candidate_db.name
    ]
    return {"entries": entries, "sha256": sha256_text(canonical_json(entries))}


def _atomic_swap(first: Path, second: Path) -> None:
    """Atomically exchange two files on Darwin; fail closed if unavailable."""

    renamex = getattr(ctypes.CDLL(None, use_errno=True), "renamex_np", None)
    if renamex is None:
        raise ValueError("candidate_atomic_swap_unavailable")
    renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex.restype = ctypes.c_int
    if renamex(os.fsencode(first), os.fsencode(second), RENAME_SWAP) != 0:
        raise ValueError("candidate_atomic_swap_failed")


def _mutate_candidate_database(
    candidate_db: Path,
    mutation: Callable[[sqlite3.Connection], MutationResult],
) -> MutationResult:
    """Apply a mutation to a private copy, then atomically publish it."""

    _assert_candidate_sidecars_quiescent(candidate_db)
    before = _candidate_database_fingerprint(candidate_db)
    before_main = _stable_candidate_file_fingerprint(candidate_db)
    before_sidecars = _candidate_sidecar_fingerprint(candidate_db)
    work_root = Path(
        tempfile.mkdtemp(prefix=".trainlab-db-work-", dir=candidate_db.parent)
    )
    os.chmod(work_root, 0o700)
    work_state = work_root / "state"
    work_state.mkdir(mode=0o700)
    work_database = work_state / "trainlab.db"
    replacement = work_root / "trainlab-replacement.db"
    preserve_work_root = False
    try:
        _online_backup(candidate_db, work_database)
        connection = connect(work_database)
        try:
            result = mutation(connection)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            connection.close()
        _assert_candidate_sidecars_quiescent(work_database)
        _online_backup(work_database, replacement)
        _assert_candidate_sidecars_quiescent(candidate_db)
        if _candidate_database_fingerprint(candidate_db) != before:
            raise ValueError("candidate_database_changed_during_mutation")
        _atomic_swap(candidate_db, replacement)
        try:
            if (
                _stable_candidate_file_fingerprint(replacement) != before_main
                or _candidate_sidecar_fingerprint(candidate_db) != before_sidecars
            ):
                raise ValueError("candidate_database_changed_during_mutation")
            _assert_candidate_sidecars_quiescent(candidate_db)
            for parent in (candidate_db.parent, replacement.parent):
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except Exception:
            try:
                _atomic_swap(candidate_db, replacement)
            except Exception as rollback_error:
                preserve_work_root = True
                raise ValueError("candidate_atomic_rollback_failed") from rollback_error
            raise
        return result
    finally:
        if not preserve_work_root:
            shutil.rmtree(work_root, ignore_errors=True)


def _checkpoint_candidate_database(candidate_db: Path) -> None:
    """Apply current schema, checkpoint Candidate WAL, and retain safe sidecars."""

    _mutate_candidate_database(candidate_db, lambda _connection: None)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)


def _candidate_seed_manifest(candidate_source: Path) -> dict[str, Any]:
    database = candidate_source / "state/trainlab.db"
    raw_root = candidate_source / "state/raw"
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,byte_size,sha256 FROM raw_files ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    entries: list[dict[str, Any]] = []
    for row in rows:
        relative = Path(str(row[1]))
        path = raw_root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != int(row[2])
            or sha256_file(path) != str(row[3])
        ):
            raise ValueError("candidate_seed_raw_invalid")
        entries.append(
            {
                "id": int(row[0]),
                "relative_path": relative.as_posix(),
                "byte_size": int(row[2]),
                "sha256": str(row[3]),
            }
        )
    return {
        "raw_max_id": max((int(item["id"]) for item in entries), default=0),
        "raw_count": len(entries),
        "raw_bytes": sum(int(item["byte_size"]) for item in entries),
        "raw_manifest_sha256": sha256_text(canonical_json(entries)),
    }


def _seal_candidate_scope(
    candidate_root: Path,
    candidate_source: Path,
    formal_source: Path,
    before: dict[str, object],
    after: dict[str, object],
) -> dict[str, Any]:
    """Bind a private filesystem marker to an immutable candidate DB receipt."""

    candidate_root = candidate_root.resolve()
    candidate_source = candidate_source.resolve()
    formal_source = formal_source.resolve()
    if before != after or before.get("schema_version") != "formal_state_fingerprint_v1":
        raise ValueError("formal_state_changed_during_snapshot")
    seed = _candidate_seed_manifest(candidate_source)
    formal_seed = _candidate_seed_manifest(formal_source)
    if seed != formal_seed:
        raise ValueError("candidate_seed_not_formal_state")
    builder_sha = sha256_file(Path(__file__).resolve())
    payload: dict[str, Any] = {
        "schema_version": "candidate_snapshot_receipt_v1",
        "candidate_source": str(candidate_source),
        "formal_source": str(formal_source),
        "formal_fingerprint_sha256": str(before.get("sha256", "")),
        "builder_sha256": builder_sha,
        **seed,
    }
    payload_sha = sha256_text(canonical_json(payload))
    database = candidate_source / "state/trainlab.db"

    def record_scope(connection: sqlite3.Connection) -> tuple[int, str]:
        run_id = begin_run(
            connection,
            run_key=f"candidate-snapshot:{payload_sha}:attempt-1",
            workflow_key="candidate:snapshot",
            dedupe_key=payload_sha,
            skill_name="garmin-sync",
            operation="index_existing_raw",
            trigger_kind="recovery",
            input_manifest=payload,
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="candidate:snapshot:scope",
            schema_name="candidate_snapshot_receipt_v1",
            schema_version="1",
            content_json=payload,
            content_text=canonical_json(payload),
        )
        finish_run(connection, run_id, status="succeeded")
        output_row = connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
        ).fetchone()
        if output_row is None:
            raise ValueError("candidate_scope_receipt_missing")
        return output_id, str(output_row[0])

    output_id, output_sha = _mutate_candidate_database(database, record_scope)
    marker = candidate_root / "formal-state-fingerprint.json"
    _write_private_json(
        marker,
        {
            "schema_version": "m8_snapshot_receipt_v1",
            "before": before,
            "after": after,
            "formal_state_unchanged": True,
            "candidate_scope": {
                "output_id": output_id,
                "output_sha256": output_sha,
            },
        },
    )
    return {"output_id": output_id, "output_sha256": output_sha, **payload}


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
    repository_root = source_root.parent
    if (repository_root / ".git").exists() and (
        candidate_root == repository_root
        or candidate_root.is_relative_to(repository_root)
    ):
        raise ValueError("candidate_must_be_outside_repository")
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
    _checkpoint_candidate_database(candidate_db)
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
        scope = _seal_candidate_scope(
            candidate_root.resolve(),
            Path(str(result["candidate_source"])),
            source_root,
            before,
            after,
        )
        result["formal_state_fingerprint_sha256"] = str(before["sha256"])
        result["formal_state_unchanged"] = True
        result["candidate_scope_output_id"] = int(scope["output_id"])
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
