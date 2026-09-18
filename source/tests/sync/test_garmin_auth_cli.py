from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.sync.auth_support import CODE, PASSWORD, SECRET
from tests.sync.test_garmin_auth_maintenance import parse
from trainlab.contracts.paths import GARMIN_CONFIG_PATH


def child_env(*, mfa: bool = False, now: float | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"GARTH_HOME", "GARTH_TOKEN", "GARMINTOKENS", "GARTH_TELEMETRY"}}
    env["AUTH_TEST_MODE"] = "mfa" if mfa else "normal"
    if now is not None:
        env["AUTH_TEST_NOW"] = str(now)
    return env


def command(root: Path, action: str, *args: str) -> list[str]:
    return [sys.executable, "-m", "tests.sync.cli_harness", action, "--instance-root", str(root), *args]


def terminal(root: Path, *, mfa: bool, cancel: str | None = None, before_code: Callable[[], None] | None = None) -> tuple[int, str]:
    master, slave = pty.openpty()

    process = subprocess.Popen(command(root, "login", "--region", "com"), stdin=slave, stdout=slave, stderr=slave, env=child_env(mfa=mfa), start_new_session=True)
    os.close(slave)
    received = bytearray()

    def until(marker: str) -> None:
        deadline = time.monotonic() + 15
        while marker.encode() not in received:
            assert time.monotonic() < deadline, "CLI prompt timed out"
            if select.select([master], [], [], 0.1)[0]:
                chunk = os.read(master, 65536)
                assert chunk, "CLI stopped before prompt"
                received.extend(chunk)

    try:
        until("账号（不回显）：")
        os.write(master, b"synthetic@example.invalid\n")
        until("密码（不回显）：")
        os.write(master, (PASSWORD + "\n").encode())
        if mfa:
            until("验证码（不回显）：")
            if before_code is not None:
                before_code()
            if cancel == "eof":
                os.write(master, b"\x04")
            elif cancel == "sigint":
                os.kill(process.pid, signal.SIGINT)
            else:
                os.write(master, (CODE + "\n").encode())
        deadline = time.monotonic() + 15
        while process.poll() is None:
            assert time.monotonic() < deadline
            if select.select([master], [], [], 0.1)[0]:
                try:
                    received.extend(os.read(master, 65536))
                except OSError:
                    break
        process.wait(timeout=5)
        while select.select([master], [], [], 0.1)[0]:
            try:
                part = os.read(master, 65536)
            except OSError:
                break
            if not part:
                break
            received.extend(part)
        return process.returncode, received.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


@pytest.mark.parametrize("mfa", [False, True])
def test_real_cli_terminal_login_maintenance_and_restart(tmp_path: Path, mfa: bool) -> None:
    code, output = terminal(tmp_path, mfa=mfa)
    assert code == 0, output
    assert '"state": "authenticated"' in output
    assert all(secret not in output for secret in (SECRET, PASSWORD, CODE, "synthetic@example.invalid"))
    status = subprocess.run(command(tmp_path, "status"), capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    assert status.returncode == 0, status.stderr
    saved = json.loads(status.stdout)["data"]
    assert saved["saved"] and not saved["server_verified"]
    due = parse(saved["next_check_at_utc"]).timestamp()
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    maintain = subprocess.run(command(tmp_path, "maintain", "--once"), capture_output=True, text=True, env=child_env(now=due), timeout=15, check=False)
    assert maintain.returncode == 0, maintain.stdout + maintain.stderr
    assert json.loads(maintain.stdout)["data"]["state"] == "refreshed"
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() != before
    assert all(secret not in maintain.stdout + maintain.stderr for secret in (SECRET, PASSWORD, CODE))
    synced = subprocess.run(command(tmp_path, "sync-once"), capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    assert synced.returncode == 0, synced.stdout + synced.stderr
    payload = json.loads(synced.stdout)
    assert payload["ok"] and len(payload["downloaded"]) == 1
    assert (tmp_path / "states/data.db").is_file()
    assert all(secret not in synced.stdout + synced.stderr for secret in (SECRET, PASSWORD, CODE))


@pytest.mark.parametrize("cancel", ["eof", "sigint"])
def test_cli_cancellation_releases_flow_and_never_commits(tmp_path: Path, cancel: str) -> None:
    code, output = terminal(tmp_path, mfa=True, cancel=cancel)
    assert code == 130
    assert not (tmp_path / GARMIN_CONFIG_PATH).exists()
    assert all(secret not in output for secret in (SECRET, PASSWORD, CODE))
    status = subprocess.run(command(tmp_path, "status"), capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    assert json.loads(status.stdout)["data"]["state"] == "manual_required"


def test_cli_no_tty_rejects_without_input_and_unknown_options_never_echo(tmp_path: Path) -> None:
    result = subprocess.run(command(tmp_path, "login", "--region", "com"), input=PASSWORD, capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    assert result.returncode == 1
    assert "interactive_terminal_required" in result.stdout
    assert PASSWORD not in result.stdout + result.stderr
    result = subprocess.run(command(tmp_path, "login", "--region", "com", "--password", PASSWORD), capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    assert result.returncode == 2
    assert PASSWORD not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


def test_other_process_login_invalidates_waiting_mfa_without_blocking(tmp_path: Path) -> None:
    committed: list[bytes] = []

    def other_login() -> None:
        code, output = terminal(tmp_path, mfa=False)
        assert code == 0, output
        committed.append((tmp_path / GARMIN_CONFIG_PATH).read_bytes())

    code, output = terminal(tmp_path, mfa=True, before_code=other_login)
    assert code == 1 and "SOURCE_CONFLICT" in output
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == committed[0]
    assert all(secret not in output for secret in (SECRET, PASSWORD, CODE))


def test_actual_foreground_maintenance_can_be_interrupted(tmp_path: Path) -> None:
    code, output = terminal(tmp_path, mfa=False)
    assert code == 0, output
    status = subprocess.run(command(tmp_path, "status"), capture_output=True, text=True, env=child_env(), timeout=15, check=False)
    due = parse(json.loads(status.stdout)["data"]["next_check_at_utc"]).timestamp()
    process = subprocess.Popen(command(tmp_path, "maintain"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env(now=due), text=True)
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 10)[0]
        first = process.stdout.readline()
        assert json.loads(first)["data"]["state"] == "refreshed"
        assert process.poll() is None
        os.kill(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130
        assert "operation_cancelled" in stdout
        assert all(secret not in first + stdout + stderr for secret in (SECRET, PASSWORD, CODE))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
