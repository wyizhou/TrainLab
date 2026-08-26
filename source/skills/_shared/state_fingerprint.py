"""Portable content fingerprints for the private raw-first state."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_raw_file(raw_root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not relative:
        raise ValueError("formal_state_content_raw_path_invalid")
    path = raw_root.joinpath(*candidate.parts)
    resolved_root = raw_root.resolve()
    if resolved_root not in path.resolve(strict=False).parents:
        raise ValueError("formal_state_content_raw_path_invalid")
    current = raw_root
    if current.is_symlink():
        raise ValueError("formal_state_content_raw_symlink")
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("formal_state_content_raw_symlink")
    return path


def formal_state_content_fingerprint(
    database: Path, raw_root: Path | None = None
) -> dict[str, object]:
    """Hash DB and registered raw bytes without host-local filesystem identity."""

    database = database.resolve()
    metadata = database.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise ValueError("formal_state_content_database_unsafe")
    raw_root = (raw_root or database.parent / "raw").resolve()
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise ValueError("formal_state_content_raw_unavailable")

    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute(
            "SELECT relative_path,byte_size,sha256 FROM raw_files "
            "ORDER BY relative_path"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError("formal_state_content_registry_unavailable") from exc
    finally:
        connection.close()

    entries: list[dict[str, object]] = [
        {
            "path": "trainlab.db",
            "size": int(metadata.st_size),
            "sha256": _sha256_file(database),
        }
    ]
    registered: set[str] = set()
    for row in rows:
        relative = str(row[0])
        path = _safe_raw_file(raw_root, relative)
        if not path.is_file():
            raise ValueError("formal_state_content_raw_file_missing")
        actual_size = int(path.stat().st_size)
        actual_sha256 = _sha256_file(path)
        if actual_size != int(row[1]) or actual_sha256 != str(row[2]):
            raise ValueError("formal_state_content_raw_hash_or_size_mismatch")
        registered.add(relative)
        entries.append(
            {
                "path": f"raw/{Path(relative).as_posix()}",
                "size": actual_size,
                "sha256": actual_sha256,
            }
        )

    for path in raw_root.rglob("*"):
        if path.name == ".gitkeep":
            continue
        if path.is_symlink():
            raise ValueError("formal_state_content_raw_symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(raw_root).as_posix()
        if relative in registered:
            continue
        if path.name == ".DS_Store":
            raise ValueError("formal_state_finder_metadata_forbidden")
        raise ValueError("formal_state_content_raw_unregistered_file")

    entries.sort(key=lambda item: str(item["path"]))
    encoded = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": "formal_state_content_fingerprint_v1",
        "entry_count": len(entries),
        "raw_file_count": len(entries) - 1,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
