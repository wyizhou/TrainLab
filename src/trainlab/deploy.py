from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .doctor import run_doctor
from .util import atomic_write_json, iso_utc


MAC_FILES = (
    "com.trainlab.drive-sync.plist",
    "com.trainlab.ingest.plist",
    "com.trainlab.scheduler.plist",
    "com.trainlab.watchdog.plist",
)
LINUX_FILES = (
    "trainlab-drive-sync.service",
    "trainlab-ingest.service",
    "trainlab-scheduler.service",
    "trainlab-scheduler.timer",
    "trainlab-watchdog.service",
    "trainlab-watchdog.timer",
)


def _render(source: Path, target: Path, root: Path) -> None:
    content = source.read_text(encoding="utf-8").replace("@PROJECT_ROOT@", str(root))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def install_services(settings: Settings, *, system: str | None = None, enable: bool = False) -> dict[str, Any]:
    if enable:
        doctor = run_doctor(settings, production=True, verify_auth=True)
        if not doctor["ok"]:
            raise RuntimeError("Production doctor failed; services were not enabled")
        if (settings.root / "harness" / "development").exists():
            raise RuntimeError("Development Harness is still active; run finalize-production before enabling services")
    actual = (system or platform.system()).lower()
    installed: list[str] = []
    commands: list[list[str]] = []
    if actual in {"darwin", "macos"}:
        destination = Path.home() / "Library" / "LaunchAgents"
        for name in MAC_FILES:
            target = destination / name
            _render(settings.root / "deploy" / "launchd" / name, target, settings.root)
            installed.append(str(target))
            if enable:
                commands.append(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)])
    elif actual == "linux":
        destination = Path.home() / ".config" / "systemd" / "user"
        for name in LINUX_FILES:
            target = destination / name
            _render(settings.root / "deploy" / "systemd" / name, target, settings.root)
            installed.append(str(target))
        if enable:
            commands.extend(
                [
                    ["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", "--now", "trainlab-drive-sync.service", "trainlab-ingest.service"],
                    ["systemctl", "--user", "enable", "--now", "trainlab-scheduler.timer", "trainlab-watchdog.timer"],
                ]
            )
    else:
        raise RuntimeError(f"Unsupported platform: {actual}")
    for command in commands:
        process = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if process.returncode != 0 and "already bootstrapped" not in process.stderr.lower():
            raise RuntimeError(process.stderr.strip() or f"Failed: {' '.join(command)}")
    return {"platform": actual, "installed": installed, "enabled": enable}


def finalize_harness(settings: Settings) -> dict[str, Any]:
    doctor = run_doctor(settings, production=True, verify_auth=True)
    if not doctor["ok"]:
        raise RuntimeError("Production doctor failed; development Harness remains active")
    acceptance_path = settings.path("state_directory") / "production_acceptance.json"
    if not acceptance_path.is_file():
        raise RuntimeError("Missing state/production_acceptance.json")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    required = {"codex_real_gmail", "watchdog_failure_recovery"}
    missing = sorted(key for key in required if acceptance.get(key, {}).get("passed") is not True)
    if missing:
        raise RuntimeError(f"Production acceptance is incomplete: {', '.join(missing)}")
    source = settings.root / "harness" / "development" / "HARNESS.md"
    archive = settings.root / "archive" / "development-HARNESS.md"
    if source.exists():
        original = source.read_text(encoding="utf-8")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(
            "---\nstatus: expired\npurpose: development-only\nexpired_at_utc: " + iso_utc() + "\n---\n\n" + original,
            encoding="utf-8",
        )
        source.unlink()
        source.parent.rmdir()
    pointer = """# TrainLab production agent entry\n\nAlways load `harness/shared/HARNESS.md` and `harness/runtime/HARNESS.md`.\nNever load files under `archive/` or any development Harness.\nRun production analysis only through `trainlab run`.\n"""
    (settings.root / "AGENTS.md").write_text(pointer, encoding="utf-8")
    (settings.root / "CLAUDE.md").write_text(pointer, encoding="utf-8")
    return {"finalized": True, "archived": str(archive), "completed_at_utc": iso_utc()}
