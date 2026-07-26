from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .db import connect, migrate
from .gmail_environment import inspect_gmail_environment, probe_gmail_environment
from .runner import codex_home
from .sync import verify_rclone


def _check(name: str, ok: bool, detail: str, *, required: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "required": required, "detail": detail}


def _rclone_drive_security(settings: Settings, remote: str) -> tuple[bool, str]:
    executable = str(settings.values["sync"].get("executable", "rclone"))
    remote_name = remote.split(":", 1)[0]
    required_scope = str(settings.values["sync"].get("required_scope", "drive.readonly"))
    require_custom = bool(settings.values["sync"].get("require_custom_client_id", True))
    redacted = subprocess.run(
        [executable, "config", "redacted", remote_name],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if redacted.returncode != 0:
        return False, redacted.stderr.strip() or f"Unable to inspect rclone remote {remote_name}"
    scope_ok = bool(re.search(rf"^scope\s*=\s*{re.escape(required_scope)}\s*$", redacted.stdout, re.MULTILINE))
    custom_client_ok = bool(re.search(r"^client_id\s*=\s*\S+\s*$", redacted.stdout, re.MULTILINE))

    listing = subprocess.run(
        [executable, "lsf", remote, "--max-depth", "1", "--format", "p"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    entries = {line.strip() for line in listing.stdout.splitlines() if line.strip()}
    sheet_name = str(settings.values["sync"]["google_sheet"]["remote_file"])
    fit_name = str(settings.values["sync"]["fit"]["remote_directory"]).rstrip("/") + "/"
    targets_ok = listing.returncode == 0 and sheet_name in entries and fit_name in entries
    shared_warning = "shared Google Drive client_id" in (redacted.stderr + listing.stderr)

    config_file = subprocess.run(
        [executable, "config", "file"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    config_lines = [line.strip() for line in config_file.stdout.splitlines() if line.strip()]
    config_path = Path(config_lines[-1]).expanduser() if config_file.returncode == 0 and config_lines else None
    mode_ok = bool(config_path and config_path.is_file() and config_path.stat().st_mode & 0o077 == 0)

    secure = bool(
        scope_ok
        and (custom_client_ok or not require_custom)
        and targets_ok
        and not shared_warning
        and mode_ok
    )
    details = [
        f"scope={required_scope}:{'ok' if scope_ok else 'missing'}",
        f"custom_client_id={'ok' if custom_client_ok else 'missing'}",
        f"targets={'ok' if targets_ok else 'missing'}",
        f"shared_client_warning={'present' if shared_warning else 'absent'}",
        f"config_permissions={'owner-only' if mode_ok else 'insecure-or-missing'}",
    ]
    if listing.returncode != 0:
        details.append(f"listing_error={listing.stderr.strip()[-500:]}")
    return secure, "; ".join(details)


def run_doctor(settings: Settings, *, production: bool = True, verify_auth: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        connection = connect(settings.database_path)
        migrate(connection)
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        connection.execute("PRAGMA integrity_check").fetchone()
        connection.close()
        checks.append(_check("database", True, f"schema {version}; SQLite opened with integrity check"))
    except Exception as error:
        checks.append(_check("database", False, f"{type(error).__name__}: {error}"))
    workbook = settings.path("health_workbook")
    fit_dir = settings.path("fit_directory")
    checks.append(_check("source_workbook", workbook.is_file(), str(workbook), required=production))
    checks.append(_check("source_fit_directory", fit_dir.is_dir(), str(fit_dir), required=production))
    runner_name = str(settings.values["runner"].get("primary", "codex"))
    executable = str(settings.values["runner"].get(f"{runner_name}_executable", runner_name))
    resolved = shutil.which(executable)
    checks.append(_check(f"runner_{runner_name}", bool(resolved), resolved or "not found", required=production))
    runtime_home = codex_home(settings)
    auth_file = runtime_home / "auth.json"
    skills_dir = runtime_home / "skills"
    custom_skills = sorted(item.name for item in skills_dir.iterdir() if item.name != ".system") if skills_dir.is_dir() else []
    try:
        plugin_check = subprocess.run(
            [executable, "plugin", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**os.environ, "CODEX_HOME": str(runtime_home)},
        )
        installed_plugins = plugin_check.returncode != 0 or "No marketplace plugins found" not in plugin_check.stdout
    except (OSError, subprocess.SubprocessError):
        installed_plugins = True
    home_ok = runtime_home.is_dir() and auth_file.is_file() and not custom_skills and not installed_plugins
    checks.append(
        _check(
            "codex_runtime_home",
            home_ok,
            f"{runtime_home}; auth={'present' if auth_file.is_file() else 'missing'}; custom_skills={custom_skills}; installed_plugins={installed_plugins}",
            required=production,
        )
    )
    remote = str(settings.values["sync"].get("remote_path", "")).strip()
    try:
        version = verify_rclone(settings)
        checks.append(_check("rclone_version", True, version, required=production))
    except Exception as error:
        checks.append(_check("rclone_version", False, str(error), required=production))
    checks.append(_check("rclone_remote", bool(remote), remote or "sync.remote_path is empty", required=production))
    if remote:
        try:
            secure, detail = _rclone_drive_security(settings, remote)
            checks.append(_check("rclone_drive_security", secure, detail, required=production))
        except Exception as error:
            checks.append(
                _check(
                    "rclone_drive_security",
                    False,
                    f"{type(error).__name__}: {error}",
                    required=production,
                )
            )
    strength_enabled = bool(settings.strength_policy.get("enabled"))
    if strength_enabled:
        catalog = {item["key"]: item for item in settings.exercise_catalog.get("exercises", [])}
        eligible = set(catalog)
        required_groups = settings.strength_policy.get("session_structure", {}).get("required_movement_groups", [])
        movement_coverage = all(
            any(catalog[key].get("movement") in alternatives for key in eligible)
            for alternatives in required_groups
        )
        complete = bool(settings.strength_policy.get("mode") == "movement_only" and movement_coverage)
        detail = (
            f"movement-only configured; {len(eligible)} catalog exercises available"
            if complete
            else "movement-only catalog does not cover every required movement group"
        )
        checks.append(_check("strength_profile", complete, detail))
    gmail_status = (
        probe_gmail_environment(executable=executable)
        if verify_auth
        else inspect_gmail_environment(executable=executable)
    )
    checks.append(
        _check(
            "gmail_environment_mcp",
            gmail_status.available
            and (gmail_status.authenticated is not False),
            f"{gmail_status.code}: {gmail_status.detail}",
            required=production,
        )
    )
    if production:
        checks.append(
            _check(
                "production_switch",
                bool(settings.values.get("production", {}).get("enabled")),
                f"production.enabled={bool(settings.values.get('production', {}).get('enabled'))}",
            )
        )
        checks.append(_check("mail_transport", settings.values["mail"].get("mode") == "mcp", f"mail.mode={settings.values['mail'].get('mode')}"))
    passed = all(item["ok"] for item in checks if item["required"])
    return {"ok": passed, "mode": "production" if production else "development", "checks": checks}
