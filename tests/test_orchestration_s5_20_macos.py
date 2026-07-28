from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "launchd"
TEMPLATE = DEPLOY / "com.trainlab.orchestrator-supervisor.plist.template"
INSTALL = DEPLOY / "install-local-supervisor.sh"
UNINSTALL = DEPLOY / "uninstall-local-supervisor.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "macos-local-supervisor.md"


def test_macos_launchagent_has_one_fixed_supervisor_argv_and_safe_lifecycle() -> None:
    document = plistlib.loads(TEMPLATE.read_bytes())
    assert document["Label"] == "com.trainlab.orchestrator-supervisor"
    assert document["ProgramArguments"] == [
        "@PYTHON_EXECUTABLE@", "-m", "trainlab", "supervisor", "run",
    ]
    assert document["WorkingDirectory"] == "@PROJECT_ROOT@"
    assert document["EnvironmentVariables"] == {
        "PYTHONUNBUFFERED": "1", "TZ": "Asia/Singapore", "PATH": "@RUNTIME_PATH@",
        "__PYVENV_LAUNCHER__": "@PROJECT_ROOT@/.venv/bin/python",
    }
    assert document["RunAtLoad"] is True
    assert document["KeepAlive"] == {"SuccessfulExit": False}
    assert document["ThrottleInterval"] == 15
    assert document["Umask"] == 63
    flattened = "\n".join(str(value) for value in document.values()).lower()
    for forbidden in ("garmin", "analysis", "mail run", "sh -c", "bash -c", "sudo", "codex", "npx"):
        assert forbidden not in flattened


def test_macos_deployment_scripts_are_shell_valid_and_only_manage_the_one_label() -> None:
    for script in (INSTALL, UNINSTALL):
        assert subprocess.run(["/bin/sh", "-n", str(script)], check=False).returncode == 0
        text = script.read_text(encoding="utf-8")
        assert "com.trainlab.orchestrator-supervisor" in text
        assert "launchctl" in text
        assert "sudo" not in text
        assert "trainlab supervisor run" not in text
    install = INSTALL.read_text(encoding="utf-8")
    assert "@RUNTIME_PATH@" in install
    assert "@PYTHON_EXECUTABLE@" in install
    assert "real_python" in install and "resolve(strict=True)" in install and "/Volumes/*" in install
    assert "touch \"$stdout_log\" \"$stderr_log\"" in install
    assert "chmod 600 \"$stdout_log\" \"$stderr_log\"" in install
    assert shutil.which("plutil") is not None


def test_macos_runbook_explains_the_single_service_and_non_destructive_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for required in ("唯一", "LaunchAgent", "-m trainlab supervisor run", "__PYVENV_LAUNCHER__", "外置卷", "--replace", "回滚", "不会删除日志、数据库、原始健康数据、FIT 文件或凭据"):
        assert required in text
