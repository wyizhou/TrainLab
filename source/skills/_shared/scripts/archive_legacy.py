#!/usr/bin/env python3
"""Owner-only legacy backup; no product imports, Provider calls or source writes."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PRIVATE_NAMES = {
    "goal.md",
    "email.json",
    "credentials.json",
    "gcp-oauth.keys.json",
    "gmail-api-auth-receipt.json",
    "gmail-api-token.json",
    "garmin_tokens.json",
    "token.json",
    ".env",
}


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


def private_dir(path: Path) -> None:
    if not path.parent.exists():
        private_dir(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError("archive_destination_invalid")
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError("archive_destination_invalid")


def write_bytes(path: Path, data: bytes) -> None:
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    write_bytes(path, data)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_file(source: Path, destination: Path) -> None:
    before = entry(source)
    if before["kind"] != "file":
        raise ValueError("archive_unsupported_entry")
    private_dir(destination.parent)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    if sha256(destination) != before["sha256"] or entry(source) != before:
        raise ValueError("archive_source_changed")


def source_paths(source: Path, names: list[str]) -> list[str]:
    if len(names) != len(set(names)) or not names:
        raise ValueError("archive_source_path_invalid")
    for name in names:
        path = Path(name)
        lower = name.lower()
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or str(path) != name
            or path.name in PRIVATE_NAMES
            or path.name.startswith(".env")
            or path.parts[0] in {"state", "logs", "config", "private", "secrets"}
            or "__pycache__" in path.parts
            or lower.endswith((".fit", ".db", ".sqlite", ".sqlite3", ".eml"))
        ):
            raise ValueError("archive_source_path_invalid")
        current = source
        for part in path.parts:
            current /= part
            entry(current)
        if not current.is_file():
            raise ValueError("archive_source_path_invalid")
    return sorted(names)


@contextmanager
def formal_lock(source: Path) -> Iterator[None]:
    lock = source / "state/trainlab.lock"
    try:
        info = entry(lock)
        if info["kind"] != "file" or info["mode"] != 0o600:
            raise ValueError("formal_state_lock_unavailable")
        descriptor = os.open(lock, os.O_RDONLY)
    except (OSError, ValueError) as exc:
        raise ValueError("formal_state_lock_unavailable") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("formal_state_lock_unavailable") from exc
        wal = source / "state/trainlab.db-wal"
        if wal.exists() and wal.stat().st_size:
            raise ValueError("formal_wal_nonempty")
        yield
    finally:
        os.close(descriptor)


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


def backup_database(source: Path, destination: Path) -> None:
    write_bytes(destination, b"")
    origin = immutable_database(source)
    target = sqlite3.connect(destination)
    try:
        origin.backup(target)
        target.commit()
    finally:
        origin.close()
        target.close()
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
    if database_check(source) != database_check(destination):
        raise ValueError("archive_database_mismatch")


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


def _copy_archive(source: Path, destination: Path) -> None:
    private_dir(destination)
    for path in sorted(source.rglob("*")):
        target = destination / path.relative_to(source)
        if path.is_dir():
            private_dir(target)
        else:
            copy_file(path, target)


def restore_archive(source: Path, destination: Path) -> None:
    verify_archive(source)
    if source.resolve() in destination.resolve().parents:
        raise ValueError("restore_destination_invalid")
    if destination.exists() or destination.is_symlink():
        raise ValueError("restore_target_exists")
    _copy_archive(source, destination)
    verify_archive(destination)


def create_archive(source: Path, parent: Path, names: list[str]) -> Path:
    source = source.absolute()
    if source.is_symlink() or source.resolve() != source:
        raise ValueError("archive_source_path_invalid")
    parent = parent.absolute()
    if source == parent or source in parent.parents or parent.resolve() != parent:
        raise ValueError("archive_destination_invalid")
    names = source_paths(source, names)
    with formal_lock(source):
        before = {
            "state": fingerprint(source / "state"),
            "source": {name: entry(source / name) for name in names},
        }
        original_db = source / "state/trainlab.db"
        digest = database_check(original_db)
        private_dir(parent)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        pending = parent / f".m12-legacy-{stamp}.pending"
        pending.mkdir(mode=0o700)
        # Only the fully verified directory is published; failures keep pending evidence.
        for name in names:
            copy_file(source / name, pending / "legacy-source" / name)
        for path in (source / "state", *sorted((source / "state").rglob("*"))):
            target = pending / "legacy-state" / path.relative_to(source / "state")
            if path.is_dir():
                private_dir(target)
            else:
                copy_file(path, target)
        backup_database(original_db, pending / "recovery/trainlab.db")
        after = {
            "state": fingerprint(source / "state"),
            "source": {name: entry(source / name) for name in names},
        }
        if before != after:
            raise ValueError("archive_source_changed")
        files, directories = inventory(pending)
        manifest = {
            "schema_version": "legacy_archive_v1",
            "files": files,
            "directories": directories,
            "source_before": before,
            "source_unchanged": True,
            "restore_drill": "pending",
            "database_digest": digest,
            "provider_calls": 0,
            "external_actions": 0,
        }
        write_json(pending / "manifest.json", manifest)
        _verify_contents(pending)
        drill = Path(tempfile.mkdtemp(prefix=".m12-restore-", dir=parent))
        _copy_archive(pending, drill)
        _verify_contents(drill)
        # The drill is a disposable copy, never the original state or retained archive.
        shutil.rmtree(drill)
        if (
            fingerprint(source / "state") != before["state"]
            or {name: entry(source / name) for name in names} != before["source"]
        ):
            raise ValueError("archive_source_changed")
        manifest["restore_drill"] = "passed"
        write_json(pending / "manifest.next", manifest)
        os.replace(pending / "manifest.next", pending / "manifest.json")
        _verify_contents(pending)
        for directory in sorted(
            (p for p in pending.rglob("*") if p.is_dir()), reverse=True
        ):
            sync_directory(directory)
        sync_directory(pending)
        final = parent / f"m12-legacy-{stamp}"
        pending.rename(final)
        sync_directory(parent)
        verify_archive(final)
        return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify", "restore"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            source = Path(__file__).resolve().parents[3]
            output = subprocess.check_output(
                ["git", "-C", str(source), "ls-files", "-z"]
            )
            names = [
                name.decode()
                for name in output.split(b"\0")
                if name and not name.startswith((b"state/", b"logs/", b"config/"))
            ]
            target = create_archive(source, source.parent / "data-backup", names)
            print(
                json.dumps(
                    {
                        "archive": str(target.relative_to(source.parent)),
                        **verify_archive(target),
                    }
                )
            )
        elif args.archive is None:
            parser.error("--archive is required")
        elif args.command == "verify":
            print(json.dumps(verify_archive(args.archive.resolve())))
        elif args.destination is None:
            parser.error("--destination is required")
        else:
            restore_archive(args.archive.resolve(), args.destination.absolute())
            print(json.dumps({"status": "restored", "provider_calls": 0}))
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        code = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc).startswith(("archive_", "formal_", "restore_"))
            else "archive_io_unavailable"
        )
        print(
            json.dumps({"status": "blocked", "error_code": code, "provider_calls": 0})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
