"""Read-only verification of an explicitly selected historical import archive.

Only import-history loads this module. It cannot create archives, scan a live
instance, checkpoint SQLite, restore files, or authorize a service operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if (
        not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
        or info.st_uid != os.getuid()
        or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
    ):
        raise ValueError("archive_unsupported_entry")
    result = {
        "kind": "directory" if path.is_dir() else "file",
        "device": info.st_dev,
        "inode": info.st_ino,
        "owner": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }
    if path.is_file():
        result["sha256"] = sha256(path)
    return result


def fingerprint(root: Path) -> dict[str, Any]:
    return {
        str(p.relative_to(root)): entry(p) for p in (root, *sorted(root.rglob("*")))
    }


def immutable_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def database_check(path: Path) -> str:
    connection = immutable_database(path)
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("archive_database_invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("archive_database_invalid")
        digest = hashlib.sha256()
        for line in connection.iterdump():
            digest.update(line.encode())
            digest.update(b"\n")
        return digest.hexdigest()
    finally:
        connection.close()


def inventory(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files, directories = [], []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        info = entry(path)
        expected = 0o700 if info["kind"] == "directory" else 0o600
        if info["mode"] != expected:
            raise ValueError("archive_permissions_invalid")
        if path.is_dir():
            directories.append(relative)
        elif relative != "manifest.json":
            files.append(
                {"path": relative, "size": info["size"], "sha256": info["sha256"]}
            )
    return files, directories


def _verify_contents(root: Path) -> dict[str, Any]:
    try:
        if entry(root)["mode"] != 0o700:
            raise ValueError("archive_permissions_invalid")
        if entry(root / "manifest.json")["mode"] != 0o600:
            raise ValueError("archive_permissions_invalid")
        manifest = json.loads((root / "manifest.json").read_text())
        required = {
            "schema_version",
            "files",
            "directories",
            "source_before",
            "source_unchanged",
            "restore_drill",
            "database_digest",
            "provider_calls",
            "external_actions",
        }
        if (
            set(manifest) != required
            or manifest["schema_version"] != "legacy_archive_v1"
            or manifest["source_unchanged"] is not True
            or manifest["provider_calls"] != 0
            or manifest["external_actions"] != 0
        ):
            raise ValueError("archive_manifest_invalid")
        files, directories = inventory(root)
        if files != manifest["files"] or directories != manifest["directories"]:
            raise ValueError("archive_content_mismatch")
        if database_check(root / "recovery/trainlab.db") != manifest["database_digest"]:
            raise ValueError("archive_database_mismatch")
        return manifest
    except (OSError, KeyError, TypeError, sqlite3.Error) as exc:
        raise ValueError("archive_invalid") from exc


def verify_archive(root: Path) -> dict[str, Any]:
    manifest = _verify_contents(root)
    if root.name.endswith(".pending") or manifest["restore_drill"] != "passed":
        raise ValueError("archive_incomplete")
    return {
        "status": "verified",
        "file_count": len(manifest["files"]),
        "provider_calls": 0,
        "external_actions": 0,
    }
