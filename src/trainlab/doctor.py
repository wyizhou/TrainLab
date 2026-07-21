from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import Settings, load_yaml
from .db import connect, migrate
from .mail import MappedGmailMCP
from .runner import codex_home
from .sync import verify_rclone


def _check(name: str, ok: bool, detail: str, *, required: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "required": required, "detail": detail}


def _mask_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "configured-self"
    return f"{local[:2]}***@{domain}"


def _gmail_config_errors(root: Path, config: dict[str, Any]) -> list[str]:
    schema = json.loads((root / "harness" / "schemas" / "gmail_mcp.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=lambda item: list(item.path))
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


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
    gmail_path = settings.root / settings.values["mail"]["gmail_config"]
    if not gmail_path.is_file():
        checks.append(_check("gmail_mapping", False, f"missing {gmail_path}", required=production))
    else:
        gmail_config = load_yaml(gmail_path)
        gmail_errors = _gmail_config_errors(settings.root, gmail_config)
        configured = bool(gmail_config.get("configured"))
        authenticated_self = str(gmail_config.get("authenticated_self", "")).strip()
        mapping_ok = bool(configured and not gmail_errors and authenticated_self)
        mapping_detail = (
            "configured TrainLab Gmail MCP mapping"
            if mapping_ok
            else "; ".join(gmail_errors[:3]) or "configured=false or authenticated_self is empty"
        )
        checks.append(_check("gmail_mapping", mapping_ok, mapping_detail, required=production))
        if mapping_ok and verify_auth:
            client = None
            try:
                client = MappedGmailMCP(settings)
                account = client.get_self()
                client.search_run_id("trainlab-doctor-nonexistent")
                expected_tools = {
                    str(item["tool"])
                    for item in gmail_config["capabilities"].values()
                }
                missing_tools = sorted(expected_tools - client.available_tools())
                account_ok = account.lower() == authenticated_self.lower()
                checks.append(
                    _check(
                        "gmail_auth",
                        bool(account_ok and not missing_tools),
                        f"authenticated self: {_mask_email(account)}; missing_tools={missing_tools}",
                    )
                )
            except Exception as error:
                checks.append(_check("gmail_auth", False, f"{type(error).__name__}: {error}"))
            finally:
                if client:
                    client.close()
        server_name = gmail_config.get("server_name")
        if mapping_ok and server_name:
            for runner, command in ((runner_name, [executable, "mcp", "list"]),):
                try:
                    process = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=20,
                        check=False,
                        env={**os.environ, "CODEX_HOME": str(runtime_home)},
                    )
                    found = process.returncode == 0 and str(server_name) in process.stdout
                    detail = f"server {server_name}" if found else (process.stderr.strip() or f"server {server_name} not registered")
                except (OSError, subprocess.SubprocessError) as error:
                    found = False
                    detail = f"{type(error).__name__}: {error}"
                checks.append(_check(f"{runner}_gmail_mcp", found, detail, required=production))
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
