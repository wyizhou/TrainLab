from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .util import atomic_write_json, iso_utc, relative_to_root, sha256_file, write_heartbeat


def rclone_version(settings: Settings) -> str:
    executable = str(settings.values["sync"].get("executable", "rclone"))
    process = subprocess.run([executable, "version"], capture_output=True, text=True, timeout=20, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or f"{executable} version failed")
    match = re.search(r"rclone v([0-9]+(?:\.[0-9]+){2})", process.stdout)
    if not match:
        raise RuntimeError("Unable to parse rclone version")
    return match.group(1)


def verify_rclone(settings: Settings) -> str:
    actual = rclone_version(settings)
    required = str(settings.values["sync"].get("required_version", ""))
    if required and actual != required:
        raise RuntimeError(f"rclone {required} is required; found {actual}")
    return actual


def source_manifest(settings: Settings) -> list[dict[str, Any]]:
    source_root = settings.path("health_workbook").parent
    paths = []
    workbook = settings.path("health_workbook")
    if workbook.is_file():
        paths.append(workbook)
    fit_dir = settings.path("fit_directory")
    if fit_dir.is_dir():
        paths.extend(sorted(fit_dir.glob("*.fit")))
    return [
        {
            "path": relative_to_root(path, settings.root),
            "size_bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": sha256_file(path),
        }
        for path in paths
        if path.is_relative_to(source_root)
    ]


def remote_child(remote_root: str, child: str) -> str:
    root = remote_root.rstrip("/")
    separator = "" if root.endswith(":") else "/"
    return f"{root}{separator}{child.lstrip('/')}"


def _run_rclone(command: list[str], *, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or f"rclone exited with {process.returncode}")
    return process


def sync_once(settings: Settings) -> dict[str, Any]:
    version = verify_rclone(settings)
    sync_config = settings.values["sync"]
    remote = str(sync_config.get("remote_path", "")).strip()
    if not remote:
        raise RuntimeError("sync.remote_path is not configured")
    executable = str(sync_config.get("executable", "rclone"))
    google_sheet = sync_config["google_sheet"]
    fit = sync_config["fit"]
    workbook_command = [
        executable,
        "copyto",
        remote_child(remote, str(google_sheet["remote_file"])),
        str(settings.path("health_workbook")),
        "--drive-export-formats",
        str(google_sheet["export_format"]),
        "--log-level",
        "NOTICE",
    ]
    if sync_config.get("update", True):
        workbook_command.append("--update")
    workbook_process = _run_rclone(workbook_command)
    fit_command = [
        executable,
        "copy",
        remote_child(remote, str(fit["remote_directory"])),
        str(settings.path("fit_directory")),
        "--log-level",
        "NOTICE",
        "--create-empty-src-dirs",
    ]
    if sync_config.get("checksum", True):
        fit_command.append("--checksum")
    if sync_config.get("update", True):
        fit_command.append("--update")
    fit_process = _run_rclone(fit_command)
    manifest = source_manifest(settings)
    state = {
        "completed_at_utc": iso_utc(),
        "rclone_version": version,
        "remote": remote,
        "sources": {
            "google_sheet": str(google_sheet["remote_file"]),
            "fit_directory": str(fit["remote_directory"]),
        },
        "files": manifest,
        "stderr_tail": (workbook_process.stderr + "\n" + fit_process.stderr)[-2000:],
    }
    atomic_write_json(settings.path("state_directory") / "sync_manifest.json", state)
    return state


def drive_sync_daemon(settings: Settings) -> None:
    heartbeat = settings.path("state_directory") / "heartbeats" / "drive_sync.json"
    poll_seconds = int(settings.values["sync"].get("poll_seconds", 300))
    while True:
        try:
            state = sync_once(settings)
            write_heartbeat(heartbeat, status="ok", details={"files": len(state["files"])})
        except Exception as error:
            write_heartbeat(heartbeat, status="error", details={"error": f"{type(error).__name__}: {error}"})
        time.sleep(max(1, poll_seconds))
