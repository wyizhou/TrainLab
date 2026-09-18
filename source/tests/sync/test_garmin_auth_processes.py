from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.sync.test_garmin_auth_cli import child_env, command, terminal
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth_store import GarminAuthStore
from trainlab.garmin_sync import _sync_process_lock


def test_cli_sync_and_maintenance_share_process_locks(tmp_path: Path) -> None:
    code, output = terminal(tmp_path, mfa=False)
    assert code == 0, output
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    with GarminAuthStore(tmp_path).locked():
        for action, args in (("maintain", ("--once",)), ("sync-once", ())):
            child = subprocess.run(command(tmp_path, action, *args), capture_output=True, text=True, env=child_env(), check=False, timeout=15)
            assert child.returncode == 1
            assert "RUN_BUSY" in child.stdout
    with _sync_process_lock(tmp_path):
        child = subprocess.run(command(tmp_path, "sync-once"), capture_output=True, text=True, env=child_env(), check=False, timeout=15)
        assert child.returncode == 1 and "RUN_BUSY" in child.stdout
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert not (tmp_path / "states/data.db").exists()
    status = subprocess.run(command(tmp_path, "status"), capture_output=True, text=True, env=child_env(), check=False, timeout=15)
    assert status.returncode == 0 and json.loads(status.stdout)["data"]["saved"]
