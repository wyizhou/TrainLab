from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .db import transaction
from .mail import gateway, record_delivery
from .util import atomic_write_json, iso_utc, parse_datetime, utc_now


def heartbeat_health(path: Path, max_age_seconds: int) -> tuple[bool, str]:
    if not path.is_file():
        return False, "heartbeat file is missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        updated = parse_datetime(value.get("updated_at_utc"))
        if not updated:
            return False, "heartbeat timestamp is invalid"
        age = (utc_now() - updated).total_seconds()
        if age > max_age_seconds:
            return False, f"heartbeat is {round(age)} seconds old"
        pid = int(value.get("pid", 0))
        if pid <= 0:
            return False, "heartbeat PID is invalid"
        try:
            os.kill(pid, 0)
        except OSError:
            return False, f"process {pid} is not running"
        if value.get("status") != "ok":
            return False, f"heartbeat status={value.get('status')}"
        return True, "healthy"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def heartbeat_path(settings: Settings, service: dict[str, Any]) -> Path:
    configured = Path(service["heartbeat"])
    if configured.parts and configured.parts[0] == "state":
        return settings.path("state_directory").joinpath(*configured.parts[1:])
    return configured if configured.is_absolute() else settings.root / configured


def restart_service(settings: Settings, service: dict[str, Any]) -> None:
    if platform.system() == "Darwin":
        target = f"gui/{os.getuid()}/{service['macos_label']}"
        command = ["launchctl", "kickstart", "-k", target]
    elif platform.system() == "Linux":
        command = ["systemctl", "--user", "restart", service["linux_unit"]]
    else:
        raise RuntimeError(f"Unsupported watchdog platform: {platform.system()}")
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or f"restart returned {process.returncode}")


def _alert(settings: Settings, connection, *, service_name: str, state: str, reason: str, event_id: str) -> None:
    mailer = gateway(settings, connection)
    state_slug = {"故障": "failure", "恢复": "recovery"}.get(state, state.lower())
    run_id = f"trainlab-watchdog-{service_name}-{event_id}-{state_slug}"
    subject = f"TrainLab 运维告警｜{service_name}｜{state}｜{run_id}"
    plain = f"服务：{service_name}\n状态：{state}\n详情：{reason}\nrun-id：{run_id}"
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:640px;margin:auto">'
        f'<h2 style="color:#b91c1c">TrainLab 运维{state}</h2>'
        f'<p style="line-height:1.6"><strong>服务：</strong>{service_name}<br><strong>详情：</strong>{reason}</p></div>'
    )
    receipt = mailer.send_self(run_id=run_id, subject=subject, plain_text=plain, html=html, label="TrainLab")
    close = getattr(mailer, "close", None)
    if close:
        close()
    with transaction(connection):
        record_delivery(connection, run_id=run_id, receipt=receipt, subject=subject, transport=settings.values["mail"].get("mode", "unknown"))


def watchdog_once(
    settings: Settings,
    connection,
    *,
    restart: Callable[[Settings, dict[str, Any]], None] = restart_service,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    state_path = settings.path("state_directory") / "watchdog_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"services": {}}
    results: dict[str, Any] = {}
    retry_count = int(settings.values["watchdog"].get("retry_count", 3))
    retry_delay = int(settings.values["watchdog"].get("retry_delay_seconds", 30))
    max_age = int(settings.values["watchdog"].get("heartbeat_max_age_seconds", 420))
    for name, service in settings.values["watchdog"]["services"].items():
        heartbeat = heartbeat_path(settings, service)
        healthy, reason = heartbeat_health(heartbeat, max_age)
        previous = state["services"].get(name, {"state": "unknown"})
        attempts = 0
        if not healthy:
            event_id = previous.get("event_id") if previous.get("state") == "failed" else utc_now().strftime("%Y%m%dT%H%M%SZ")
            for attempts in range(1, retry_count + 1):
                try:
                    restart(settings, service)
                except Exception as error:
                    reason = f"restart {attempts} failed: {error}"
                sleeper(retry_delay)
                healthy, check_reason = heartbeat_health(heartbeat, max_age)
                reason = check_reason if healthy else reason
                if healthy:
                    break
            if not healthy and previous.get("state") != "failed":
                _alert(settings, connection, service_name=name, state="故障", reason=reason, event_id=event_id)
            current_state = {"state": "healthy" if healthy else "failed", "event_id": event_id, "updated_at_utc": iso_utc(), "reason": reason}
        else:
            current_state = {"state": "healthy", "event_id": previous.get("event_id"), "updated_at_utc": iso_utc(), "reason": reason}
        if healthy and previous.get("state") == "failed":
            _alert(settings, connection, service_name=name, state="恢复", reason=reason, event_id=previous["event_id"])
            current_state["event_id"] = None
        state["services"][name] = current_state
        results[name] = {"healthy": healthy, "reason": reason, "restart_attempts": attempts}
    state["updated_at_utc"] = iso_utc()
    atomic_write_json(state_path, state)
    return results


def watchdog_daemon(settings: Settings, connection_factory) -> None:
    check_seconds = int(settings.values["watchdog"].get("check_seconds", 60))
    while True:
        connection = connection_factory()
        try:
            watchdog_once(settings, connection)
        finally:
            connection.close()
        time.sleep(max(1, check_seconds))
