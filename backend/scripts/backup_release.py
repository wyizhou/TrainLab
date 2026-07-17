#!/usr/bin/env python3
"""Create a stopped-writer PostgreSQL + private FIT volume release backup."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from release_backup_common import (
    DATABASE_FILE,
    MIGRATION_HEAD,
    POSTGRES_IMAGE,
    PRIVATE_FILES_FILE,
    ReleaseBackupError,
    backend_is_running,
    compose_command,
    create_private_directory,
    private_volume_name,
    run,
    run_text,
    validate_project_name,
    write_manifest,
)


def create_backup(destination: Path, project: str) -> Path:
    project = validate_project_name(project)
    output = create_private_directory(destination)
    was_running = False
    complete = False
    try:
        was_running = backend_is_running(project)
        if was_running:
            run(compose_command(project, "stop", "backend"))

        version = run_text(
            compose_command(
                project,
                "exec",
                "-T",
                "db",
                "psql",
                "-At",
                "-U",
                "trainlab",
                "-d",
                "trainlab",
                "-c",
                "SELECT version_num FROM alembic_version",
            )
        )
        if version != MIGRATION_HEAD:
            raise ReleaseBackupError("Database migration head does not match this release")

        database_path = output / DATABASE_FILE
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(database_path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as database_file:
            run(
                compose_command(
                    project,
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "-U",
                    "trainlab",
                    "-d",
                    "trainlab",
                ),
                output_file=database_file,
            )
            database_file.flush()
            os.fsync(database_file.fileno())

        volume = private_volume_name(project)
        # A bind to a missing named volume would make Docker create an empty
        # source volume and produce a plausible but incomplete backup. Inspect
        # the source explicitly so backup is strictly read-only with respect
        # to volume existence.
        run(["docker", "volume", "inspect", volume], capture_output=True)
        private_files_path = output / PRIVATE_FILES_FILE
        descriptor = os.open(private_files_path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as private_files:
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    f"{volume}:/source:ro",
                    POSTGRES_IMAGE,
                    "tar",
                    "-czf",
                    "-",
                    "-C",
                    "/source",
                    ".",
                ],
                output_file=private_files,
            )
            private_files.flush()
            os.fsync(private_files.fileno())
        manifest = write_manifest(output)
        complete = True
        return manifest
    finally:
        if not complete:
            shutil.rmtree(output, ignore_errors=True)
        if was_running:
            try:
                run(compose_command(project, "up", "-d", "--wait", "backend"))
            except ReleaseBackupError:
                if complete:
                    raise
                print(
                    "Backend restart also failed; keep it stopped and inspect Compose logs",
                    file=sys.stderr,
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new backup directory; its parent directory must already exist",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("COMPOSE_PROJECT_NAME", "trainlab"),
        help="Compose project name (default: COMPOSE_PROJECT_NAME or trainlab)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = create_backup(args.output, args.project)
    except ReleaseBackupError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup complete: {manifest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
