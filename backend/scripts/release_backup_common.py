#!/usr/bin/env python3
"""Shared, dependency-free safety primitives for the v0.1.0 release backup tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

PRODUCT_VERSION = "v0.1.0"
MIGRATION_HEAD = "0003_activity_data_lifecycle"
MANIFEST_SCHEMA_VERSION = 1
DATABASE_FILE = "database.dump"
PRIVATE_FILES_FILE = "private-files.tar.gz"
MANIFEST_FILE = "manifest.json"
POSTGRES_IMAGE = "postgres:17-alpine"
ROOT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_SCRIPT = ROOT_DIR / "backend" / "scripts" / "compose.sh"
PROJECT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseBackupError(RuntimeError):
    """A context-free operational failure safe to show to an operator."""


@dataclass(frozen=True)
class Artifact:
    file: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ValidatedBackup:
    root: Path
    database: Path
    private_files: Path
    created_at: str


def validate_project_name(value: str) -> str:
    if not PROJECT_PATTERN.fullmatch(value):
        raise ReleaseBackupError("Compose project name must use lowercase letters, digits, _ or -")
    return value


def compose_command(project: str, *arguments: str) -> list[str]:
    return [str(COMPOSE_SCRIPT), "-p", validate_project_name(project), *arguments]


def run(
    command: Sequence[str],
    *,
    input_file: BinaryIO | None = None,
    output_file: BinaryIO | None = None,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            check=True,
            stdin=input_file,
            stdout=subprocess.PIPE if capture_output else output_file,
            stderr=subprocess.PIPE if capture_output else None,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseBackupError(
            "Release backup command failed; inspect Docker service logs"
        ) from exc


def run_text(command: Sequence[str]) -> str:
    result = run(command, capture_output=True)
    return result.stdout.decode("utf-8").strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> Artifact:
    return Artifact(file=path.name, size=path.stat().st_size, sha256=sha256_file(path))


def utc_timestamp() -> str:
    # Keep the operator scripts runnable with macOS' system Python 3.9.
    return (
        datetime.now(timezone.utc)  # noqa: UP017
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def write_manifest(directory: Path, created_at: str | None = None) -> Path:
    database = artifact(directory / DATABASE_FILE)
    private_files = artifact(directory / PRIVATE_FILES_FILE)
    payload = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "productVersion": PRODUCT_VERSION,
        "migrationHead": MIGRATION_HEAD,
        "createdAt": created_at or utc_timestamp(),
        "artifacts": {
            "database": database.__dict__,
            "privateFiles": private_files.__dict__,
        },
    }
    destination = directory / MANIFEST_FILE
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def create_private_directory(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise ReleaseBackupError(
            "Backup parent must exist and the destination must be a new directory"
        ) from exc
    os.chmod(path, 0o700)
    return path.resolve()


def compose_config(project: str) -> dict[str, Any]:
    output = run_text(compose_command(project, "config", "--format", "json"))
    try:
        document = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseBackupError("Docker Compose returned invalid configuration") from exc
    if not isinstance(document, dict):
        raise ReleaseBackupError("Docker Compose returned invalid configuration")
    return document


def private_volume_name(project: str) -> str:
    config = compose_config(project)
    try:
        name = config["volumes"]["trainlab-private-files"]["name"]
    except (KeyError, TypeError) as exc:
        raise ReleaseBackupError(
            "Private storage volume is missing from Compose configuration"
        ) from exc
    if not isinstance(name, str) or not name:
        raise ReleaseBackupError("Private storage volume is missing from Compose configuration")
    return name


def backend_is_running(project: str) -> bool:
    services = run_text(compose_command(project, "ps", "--status", "running", "--services"))
    return "backend" in services.splitlines()


def _regular_unlinked_file(path: Path) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError as exc:
        raise ReleaseBackupError("Backup is incomplete") from exc
    if not stat.S_ISREG(result.st_mode) or result.st_nlink != 1:
        raise ReleaseBackupError("Backup artifacts must be independent regular files")
    return result


def _validate_artifact(root: Path, value: object, expected_name: str) -> Path:
    if not isinstance(value, dict) or set(value) != {"file", "size", "sha256"}:
        raise ReleaseBackupError("Manifest artifact schema is invalid")
    filename = value["file"]
    size = value["size"]
    checksum = value["sha256"]
    if filename != expected_name:
        raise ReleaseBackupError("Manifest artifact path is not allowed")
    relative = PurePosixPath(filename)
    if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
        raise ReleaseBackupError("Manifest artifact path is not allowed")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ReleaseBackupError("Manifest artifact size is invalid")
    if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
        raise ReleaseBackupError("Manifest artifact checksum is invalid")
    path = root / filename
    file_stat = _regular_unlinked_file(path)
    if file_stat.st_size != size or sha256_file(path) != checksum:
        raise ReleaseBackupError("Backup artifact size or checksum does not match")
    return path


def validate_private_archive(path: Path) -> None:
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                relative = PurePosixPath(member.name)
                normalized_parts = tuple(part for part in relative.parts if part not in {"", "."})
                if relative.is_absolute() or ".." in normalized_parts:
                    raise ReleaseBackupError("Private archive contains an unsafe path")
                normalized = "/".join(normalized_parts)
                if normalized and normalized in seen:
                    raise ReleaseBackupError("Private archive contains duplicate paths")
                if normalized:
                    seen.add(normalized)
                if not (member.isdir() or member.isreg()):
                    raise ReleaseBackupError("Private archive contains links or special files")
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseBackupError("Private archive is invalid") from exc


def validate_backup(directory: Path) -> ValidatedBackup:
    try:
        root_stat = directory.lstat()
    except OSError as exc:
        raise ReleaseBackupError("Backup directory is unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise ReleaseBackupError("Backup directory must be a real directory")
    root = directory.resolve()
    manifest_path = root / MANIFEST_FILE
    _regular_unlinked_file(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBackupError("Manifest is invalid") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schemaVersion",
        "productVersion",
        "migrationHead",
        "createdAt",
        "artifacts",
    }:
        raise ReleaseBackupError("Manifest schema is invalid")
    if manifest["schemaVersion"] != MANIFEST_SCHEMA_VERSION:
        raise ReleaseBackupError("Manifest schema version is unsupported")
    if manifest["productVersion"] != PRODUCT_VERSION:
        raise ReleaseBackupError("Backup product version is unsupported")
    if manifest["migrationHead"] != MIGRATION_HEAD:
        raise ReleaseBackupError("Backup migration head is unsupported")
    created_at = manifest["createdAt"]
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise ReleaseBackupError("Manifest creation time is invalid")
    try:
        datetime.fromisoformat(created_at.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ReleaseBackupError("Manifest creation time is invalid") from exc
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"database", "privateFiles"}:
        raise ReleaseBackupError("Manifest artifact set is invalid")
    database = _validate_artifact(root, artifacts["database"], DATABASE_FILE)
    private_files = _validate_artifact(root, artifacts["privateFiles"], PRIVATE_FILES_FILE)
    validate_private_archive(private_files)
    return ValidatedBackup(
        root=root,
        database=database,
        private_files=private_files,
        created_at=created_at,
    )
