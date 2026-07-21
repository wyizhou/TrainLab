from __future__ import annotations

import subprocess
from pathlib import Path

from trainlab.doctor import _rclone_drive_security
from trainlab.sync import remote_child, sync_once


def test_remote_child_handles_drive_root_and_subdirectory():
    assert remote_child("trainlab_drive:", "Health Metrics_v5.xlsx") == "trainlab_drive:Health Metrics_v5.xlsx"
    assert remote_child("trainlab_drive:TrainLab/", "/HealthFit") == "trainlab_drive:TrainLab/HealthFit"


def test_sync_uses_exact_sheet_export_and_healthfit_sources(settings, monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1] == "version":
            return subprocess.CompletedProcess(command, 0, stdout="rclone v1.74.4\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="ok")

    monkeypatch.setattr("trainlab.sync.subprocess.run", fake_run)
    state = sync_once(settings)

    assert commands[1][0:4] == [
        "rclone",
        "copyto",
        "trainlab_drive:Health Metrics_v5.xlsx",
        str(settings.path("health_workbook")),
    ]
    assert "--drive-export-formats" in commands[1]
    assert commands[2][0:4] == [
        "rclone",
        "copy",
        "trainlab_drive:HealthFit",
        str(settings.path("fit_directory")),
    ]
    assert "--checksum" in commands[2]
    assert "--update" in commands[2]
    assert all("--delete" not in command for command in commands)
    assert state["sources"] == {
        "google_sheet": "Health Metrics_v5.xlsx",
        "fit_directory": "HealthFit",
    }


def test_doctor_requires_private_custom_readonly_remote(settings, monkeypatch, tmp_path: Path):
    config_path = tmp_path / "rclone.conf"
    config_path.write_text("[trainlab_drive]\n", encoding="utf-8")
    config_path.chmod(0o600)

    def fake_run(command, **kwargs):
        if command[1:3] == ["config", "redacted"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="[trainlab_drive]\nscope = drive.readonly\nclient_id = XXX\ntoken = XXX\n",
                stderr="",
            )
        if command[1] == "lsf":
            return subprocess.CompletedProcess(command, 0, stdout="Health Metrics_v5.xlsx\nHealthFit/\n", stderr="")
        if command[1:3] == ["config", "file"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"Configuration file is stored at:\n{config_path}\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr("trainlab.doctor.subprocess.run", fake_run)
    ok, detail = _rclone_drive_security(settings, "trainlab_drive:")
    assert ok is True
    assert "shared_client_warning=absent" in detail


def test_doctor_rejects_shared_or_missing_client_id(settings, monkeypatch, tmp_path: Path):
    config_path = tmp_path / "rclone.conf"
    config_path.write_text("[trainlab_drive]\n", encoding="utf-8")
    config_path.chmod(0o600)

    def fake_run(command, **kwargs):
        if command[1:3] == ["config", "redacted"]:
            return subprocess.CompletedProcess(command, 0, stdout="scope = drive.readonly\ntoken = XXX\n", stderr="")
        if command[1] == "lsf":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Health Metrics_v5.xlsx\nHealthFit/\n",
                stderr="This remote uses rclone's shared Google Drive client_id",
            )
        if command[1:3] == ["config", "file"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"Configuration file is stored at:\n{config_path}\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr("trainlab.doctor.subprocess.run", fake_run)
    ok, detail = _rclone_drive_security(settings, "trainlab_drive:")
    assert ok is False
    assert "custom_client_id=missing" in detail
    assert "shared_client_warning=present" in detail
