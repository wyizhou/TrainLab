#!/usr/bin/env python3
"""Dependency-free unit tests for release backup/restore safety and command ordering."""

from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_release
import drill_release_restore
import restore_release
from release_backup_common import (
    DATABASE_FILE,
    MANIFEST_FILE,
    MIGRATION_HEAD,
    PRIVATE_FILES_FILE,
    ReleaseBackupError,
    validate_backup,
    validate_project_name,
    write_manifest,
)


def tar_bytes(*, member_name: str = "user/activity.fit", member_type: bytes | None = None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        if member_type is None:
            payload = b"synthetic-fit"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        else:
            info.type = member_type
            archive.addfile(info)
    return output.getvalue()


def make_backup(root: Path, *, archive: bytes | None = None) -> Path:
    root.mkdir(mode=0o700)
    (root / DATABASE_FILE).write_bytes(b"synthetic-pg-dump")
    (root / PRIVATE_FILES_FILE).write_bytes(archive or tar_bytes())
    os.chmod(root / DATABASE_FILE, 0o600)
    os.chmod(root / PRIVATE_FILES_FILE, 0o600)
    write_manifest(root, "2026-07-17T00:00:00Z")
    return root


class ManifestSafetyTests(unittest.TestCase):
    def test_manifest_is_minimal_relative_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = make_backup(parent / "backup")
            validated = validate_backup(root)
            manifest = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))

            self.assertEqual(validated.database.name, DATABASE_FILE)
            self.assertEqual(validated.private_files.name, PRIVATE_FILES_FILE)
            self.assertEqual(manifest["productVersion"], "v0.1.0")
            self.assertEqual(manifest["migrationHead"], MIGRATION_HEAD)
            self.assertEqual(
                set(manifest),
                {"schemaVersion", "productVersion", "migrationHead", "createdAt", "artifacts"},
            )
            serialized = json.dumps(manifest)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("password", serialized.casefold())
            self.assertNotIn("cookie", serialized.casefold())
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            for filename in (DATABASE_FILE, PRIVATE_FILES_FILE, MANIFEST_FILE):
                self.assertEqual(stat.S_IMODE((root / filename).stat().st_mode), 0o600)

    def test_checksum_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup")
            (root / DATABASE_FILE).write_bytes(b"tampered")

            with self.assertRaisesRegex(ReleaseBackupError, "size or checksum"):
                validate_backup(root)

    def test_manifest_rejects_absolute_parent_and_extra_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup")
            manifest_path = root / MANIFEST_FILE
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for unsafe in ("/tmp/database.dump", "../database.dump", "nested/database.dump"):
                manifest["artifacts"]["database"]["file"] = unsafe
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ReleaseBackupError, "path"):
                    validate_backup(root)
            manifest["artifacts"]["database"]["file"] = DATABASE_FILE
            manifest["privatePath"] = "/private/health-data"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ReleaseBackupError, "schema"):
                validate_backup(root)

    def test_symlink_and_hardlink_artifacts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = make_backup(parent / "backup")
            database = root / DATABASE_FILE
            database.unlink()
            database.symlink_to(parent / "outside")
            with self.assertRaisesRegex(ReleaseBackupError, "regular files"):
                validate_backup(root)

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = make_backup(parent / "backup")
            os.link(root / DATABASE_FILE, parent / "second-link")
            with self.assertRaisesRegex(ReleaseBackupError, "regular files"):
                validate_backup(root)

    def test_archive_rejects_traversal_links_and_duplicate_paths(self) -> None:
        for archive in (
            tar_bytes(member_name="../escape.fit"),
            tar_bytes(member_name="link.fit", member_type=tarfile.SYMTYPE),
        ):
            with self.subTest(), tempfile.TemporaryDirectory() as temporary:
                root = make_backup(Path(temporary) / "backup", archive=archive)
                with self.assertRaises(ReleaseBackupError):
                    validate_backup(root)

        duplicate = io.BytesIO()
        with tarfile.open(fileobj=duplicate, mode="w:gz") as archive_file:
            for _ in range(2):
                info = tarfile.TarInfo("same.fit")
                info.size = 1
                archive_file.addfile(info, io.BytesIO(b"x"))
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup", archive=duplicate.getvalue())
            with self.assertRaisesRegex(ReleaseBackupError, "duplicate"):
                validate_backup(root)

    def test_project_name_rejects_shell_or_compose_option_injection(self) -> None:
        self.assertEqual(
            validate_project_name("trainlab_release_v010_u2"), "trainlab_release_v010_u2"
        )
        for unsafe in ("TrainLab", "--project-directory", "trainlab;rm", "../trainlab", ""):
            with self.subTest(unsafe=unsafe), self.assertRaises(ReleaseBackupError):
                validate_project_name(unsafe)


class BackupCommandTests(unittest.TestCase):
    def test_backup_streams_both_artifacts_to_host_owned_0600_files(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
            command_list = list(command)
            commands.append(command_list)
            output = kwargs.get("output_file")
            if output is not None and "pg_dump" in command_list:
                output.write(b"synthetic-pg-dump")
            elif output is not None and command_list[:2] == ["docker", "run"]:
                output.write(tar_bytes())
            return None

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "backup"
            with (
                patch.object(backup_release, "backend_is_running", return_value=False),
                patch.object(backup_release, "run_text", return_value=MIGRATION_HEAD),
                patch.object(backup_release, "private_volume_name", return_value="private-volume"),
                patch.object(backup_release, "run", side_effect=fake_run),
            ):
                manifest = backup_release.create_backup(destination, "trainlab_release_v010_u2")

            self.assertEqual(manifest, destination.resolve() / MANIFEST_FILE)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            for filename in (DATABASE_FILE, PRIVATE_FILES_FILE, MANIFEST_FILE):
                self.assertEqual(stat.S_IMODE((destination / filename).stat().st_mode), 0o600)
            tar_command = next(command for command in commands if command[:2] == ["docker", "run"])
            inspect_index = commands.index(["docker", "volume", "inspect", "private-volume"])
            tar_index = commands.index(tar_command)
            self.assertLess(inspect_index, tar_index)
            self.assertIn("-czf", tar_command)
            self.assertIn("-", tar_command)
            self.assertFalse(any(str(destination) in argument for argument in tar_command))

    def test_missing_private_volume_fails_without_creating_backup(self) -> None:
        commands: list[list[str]] = []

        def fail_missing_volume(command, **_kwargs):  # type: ignore[no-untyped-def]
            command_list = list(command)
            commands.append(command_list)
            if command_list[:3] == ["docker", "volume", "inspect"]:
                raise ReleaseBackupError("synthetic missing volume")
            return None

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "backup"
            with (
                patch.object(backup_release, "backend_is_running", return_value=False),
                patch.object(backup_release, "run_text", return_value=MIGRATION_HEAD),
                patch.object(backup_release, "private_volume_name", return_value="missing-volume"),
                patch.object(backup_release, "run", side_effect=fail_missing_volume),
                self.assertRaises(ReleaseBackupError),
            ):
                backup_release.create_backup(destination, "trainlab_release_v010_u2")

            self.assertIn(["docker", "volume", "inspect", "missing-volume"], commands)
            self.assertFalse(any(command[:2] == ["docker", "run"] for command in commands))
            self.assertFalse(destination.exists())

    def test_failed_backup_removes_new_partial_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "partial"
            with (
                patch.object(backup_release, "backend_is_running", return_value=False),
                patch.object(backup_release, "run_text", return_value=MIGRATION_HEAD),
                patch.object(backup_release, "run", side_effect=ReleaseBackupError("synthetic")),
                self.assertRaises(ReleaseBackupError),
            ):
                backup_release.create_backup(destination, "trainlab_release_v010_u2")
            self.assertFalse(destination.exists())


class RestoreCommandTests(unittest.TestCase):
    def test_wrong_confirmation_runs_no_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup")
            with (
                patch.object(restore_release, "run") as run_command,
                self.assertRaisesRegex(ReleaseBackupError, "Explicit confirmation"),
            ):
                restore_release.restore_backup(root, "trainlab_release_v010_u2", "wrong")
            run_command.assert_not_called()

    def test_database_preflight_failure_happens_before_compose_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup")
            commands: list[list[str]] = []

            def fail_preflight(command, **_kwargs):  # type: ignore[no-untyped-def]
                commands.append(list(command))
                raise ReleaseBackupError("invalid PostgreSQL archive")

            with (
                patch.object(restore_release, "run", side_effect=fail_preflight),
                self.assertRaises(ReleaseBackupError),
            ):
                restore_release.restore_backup(
                    root,
                    "trainlab_release_v010_u2",
                    "RESTORE:trainlab_release_v010_u2",
                )
            self.assertEqual(commands[0][:2], ["docker", "run"])
            self.assertFalse(any("stop" in command for command in commands))

    def test_restore_revokes_sessions_before_starting_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = make_backup(Path(temporary) / "backup")
            commands: list[list[str]] = []

            def record(command, **_kwargs):  # type: ignore[no-untyped-def]
                commands.append(list(command))
                return None

            with (
                patch.object(restore_release, "run", side_effect=record),
                patch.object(restore_release, "run_text", return_value=MIGRATION_HEAD),
                patch.object(restore_release, "private_volume_name", return_value="private-volume"),
            ):
                restore_release.restore_backup(
                    root,
                    "trainlab_release_v010_u2",
                    "RESTORE:trainlab_release_v010_u2",
                )

            rendered = [" ".join(command) for command in commands]
            stop_index = next(i for i, command in enumerate(rendered) if " stop backend" in command)
            drop_index = next(i for i, command in enumerate(rendered) if "DROP DATABASE" in command)
            sessions_index = next(
                i for i, command in enumerate(rendered) if "DELETE FROM sessions" in command
            )
            start_index = next(
                i for i, command in enumerate(rendered) if " up -d --wait backend" in command
            )
            self.assertLess(stop_index, drop_index)
            self.assertLess(drop_index, sessions_index)
            self.assertLess(sessions_index, start_index)
            self.assertEqual(start_index, len(rendered) - 1)


class DrillIsolationTests(unittest.TestCase):
    def test_drill_refuses_default_or_unrelated_compose_projects(self) -> None:
        for unsafe in ("trainlab", "production", "trainlab_release_v010_u3"):
            with self.subTest(unsafe=unsafe), self.assertRaises(drill_release_restore.DrillError):
                drill_release_restore.require_isolated_project(unsafe)

        self.assertEqual(
            drill_release_restore.require_isolated_project("trainlab_release_v010_u2_ci"),
            "trainlab_release_v010_u2_ci",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
