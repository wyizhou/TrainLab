from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy/systemd/trainlab-orchestrator-supervisor.service.template"
ENVIRONMENT = ROOT / "deploy/systemd/trainlab-orchestrator-supervisor.env.example"
RUNBOOK = ROOT / "docs/runbooks/orchestration-deployment.md"


def _unit_fields() -> dict[str, str]:
    section = ""
    fields: dict[str, str] = {}
    for line in UNIT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif section == "Service" and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


def test_s5_17_supervisor_is_the_only_fixed_service_command() -> None:
    unit_text = UNIT.read_text(encoding="utf-8")
    fields = _unit_fields()

    assert fields["Type"] == "notify"
    assert fields["NotifyAccess"] == "main"
    assert fields["ExecStart"] == "@PROJECT_ROOT@/.venv/bin/trainlab supervisor run"
    assert "ExecStartPre" not in fields
    assert "ExecStartPost" not in fields
    assert "ExecReload" not in fields
    assert "ExecStop" not in fields
    assert not (ROOT / "deploy/systemd/trainlab-orchestrator-supervisor.timer").exists()
    forbidden = ("scheduler", "watchdog", "garmin", "analysis", "mail run", "sh -c", "bash -c", "sudo")
    assert all(item not in fields["ExecStart"].lower() for item in forbidden)
    assert "OnCalendar=" not in unit_text


def test_s5_17_service_has_safe_shutdown_watchdog_restart_and_limits() -> None:
    fields = _unit_fields()

    expected = {
        "KillSignal": "SIGTERM",
        "KillMode": "control-group",
        "TimeoutStopSec": "90s",
        "Restart": "on-failure",
        "RestartSec": "15s",
        "WatchdogSec": "90s",
        "UMask": "0077",
        "NoNewPrivileges": "yes",
        "ProtectSystem": "strict",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
        "ReadWritePaths": "@DATA_ROOT@ @STATE_ROOT@ @LOG_ROOT@",
        "LimitNOFILE": "256",
        "TasksMax": "64",
        "MemoryMax": "1G",
        "CPUQuota": "100%",
    }
    for key, value in expected.items():
        assert fields.get(key) == value

    unit_text = UNIT.read_text(encoding="utf-8")
    assert "StartLimitIntervalSec=5min" in unit_text
    assert "StartLimitBurst=3" in unit_text


def test_s5_17_templates_and_runbook_do_not_admit_sensitive_or_arbitrary_configuration() -> None:
    material = "\n".join((UNIT.read_text(encoding="utf-8"), ENVIRONMENT.read_text(encoding="utf-8"))).lower()
    forbidden = ("token", "secret", "password", "oauth", "recipient", "email=", "model", "command=", "exec=", "codex")
    assert all(item not in material for item in forbidden)
    assert ENVIRONMENT.read_text(encoding="utf-8").splitlines()[-2:] == ["PYTHONUNBUFFERED=1", "TZ=Asia/Singapore"]

    runbook = RUNBOOK.read_text(encoding="utf-8")
    for required in ("唯一常驻", "SIGTERM", "WatchdogSec", "升级", "回滚", "不构成安装或生产切换授权"):
        assert required in runbook
    assert "不要创建或启用任何直接调用 Garmin、分析或邮件层的" in runbook
