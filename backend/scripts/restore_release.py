#!/usr/bin/env python3
"""Validate and destructively restore a v0.1.0 stopped-writer release backup."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from release_backup_common import (
    MIGRATION_HEAD,
    POSTGRES_IMAGE,
    ReleaseBackupError,
    compose_command,
    private_volume_name,
    run,
    run_text,
    validate_backup,
    validate_project_name,
)


def confirmation_for(project: str) -> str:
    return f"RESTORE:{project}"


def restore_backup(source: Path, project: str, confirmation: str) -> None:
    project = validate_project_name(project)
    backup = validate_backup(source)
    expected_confirmation = confirmation_for(project)
    if confirmation != expected_confirmation:
        raise ReleaseBackupError(f"Explicit confirmation required: {expected_confirmation}")

    # Validate the custom PostgreSQL archive before stopping or writing any service.
    with backup.database.open("rb") as database_file:
        run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--network",
                "none",
                POSTGRES_IMAGE,
                "pg_restore",
                "--list",
            ],
            input_file=database_file,
            capture_output=True,
        )

    # From this point onward any failure intentionally leaves backend stopped.
    run(compose_command(project, "stop", "backend"))
    run(compose_command(project, "up", "-d", "--wait", "db"))
    volume = private_volume_name(project)
    run(
        [
            "docker",
            "volume",
            "create",
            "--label",
            f"com.docker.compose.project={project}",
            "--label",
            "com.docker.compose.volume=trainlab-private-files",
            volume,
        ],
        capture_output=True,
    )

    run(
        compose_command(
            project,
            "exec",
            "-T",
            "db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "trainlab",
            "-d",
            "postgres",
            "-c",
            "DROP DATABASE IF EXISTS trainlab WITH (FORCE)",
        )
    )
    run(compose_command(project, "exec", "-T", "db", "createdb", "-U", "trainlab", "trainlab"))
    with backup.database.open("rb") as database_file:
        run(
            compose_command(
                project,
                "exec",
                "-T",
                "db",
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "-U",
                "trainlab",
                "-d",
                "trainlab",
            ),
            input_file=database_file,
        )

    with backup.private_files.open("rb") as private_files:
        run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--network",
                "none",
                "-v",
                f"{volume}:/target",
                POSTGRES_IMAGE,
                "sh",
                "-eu",
                "-c",
                ("find /target -mindepth 1 -xdev -exec rm -rf {} +; tar -xzf - -C /target"),
            ],
            input_file=private_files,
        )
    run(
        compose_command(
            project,
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "alembic",
            "backend",
            "upgrade",
            "head",
        )
    )
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
        raise ReleaseBackupError("Restored database migration head is unexpected")
    run(
        compose_command(
            project,
            "exec",
            "-T",
            "db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "trainlab",
            "-d",
            "trainlab",
            "-c",
            "DELETE FROM sessions",
        )
    )
    run(compose_command(project, "up", "-d", "--wait", "backend"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path, help="validated backup directory")
    parser.add_argument(
        "--project",
        default=os.environ.get("COMPOSE_PROJECT_NAME", "trainlab"),
        help="Compose project name (default: COMPOSE_PROJECT_NAME or trainlab)",
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help="must exactly equal RESTORE:<project>",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        restore_backup(args.backup, args.project, args.confirm)
    except ReleaseBackupError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print("Restore complete; sessions were revoked and backend is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
