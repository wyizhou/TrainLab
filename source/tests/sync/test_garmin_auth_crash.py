from __future__ import annotations

import json
import multiprocessing
import os
import signal
import socket
from pathlib import Path
from typing import Any

import pytest

from tests.sync.auth_support import PASSWORD, OfflineGarmin
from tests.sync.test_garmin_auth import data
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_sdk import GarminSDK
from trainlab.garmin_auth_store import GarminAuthStore


def interrupted_commit(root: str, stage: str, connection: Any) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Crash test process network blocked")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.socket.connect_ex = denied  # type: ignore[method-assign]
    store = GarminAuthStore(Path(root))
    with store.locked():
        snapshot = store.snapshot()
        sdk = store.load(snapshot, GarminSDK)
        original_write = store._write_new
        original_fsync = store._fsync

        def pause() -> None:
            connection.send(True)
            connection.recv()

        def write(path: Path, raw: bytes) -> None:
            if stage == "half_pair" and path.name == "oauth2_token.json":
                pause()
            original_write(path, raw)

        def fsync(path: Path) -> None:
            if stage == "full_pair" and path.name.startswith("g-"):
                pause()
            original_fsync(path)

        store._write_new = write  # type: ignore[method-assign]
        store._fsync = fsync  # type: ignore[method-assign]
        store.commit(sdk, snapshot.revision, GarminSDK)


@pytest.mark.parametrize("stage", ["half_pair", "full_pair"])
def test_process_killed_during_commit_retains_complete_old_generation(tmp_path: Path, offline: OfflineGarmin, stage: str) -> None:
    service = GarminAuthService(tmp_path)
    data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    config = tmp_path / GARMIN_CONFIG_PATH
    before = config.read_bytes()
    active = tmp_path / json.loads(before)["tokenstore"]
    tokens = {path: path.read_bytes() for path in active.iterdir()}
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=interrupted_commit, args=(str(tmp_path), stage, child))
    process.start()
    try:
        assert parent.poll(10) and parent.recv()
        assert process.pid is not None
        os.kill(process.pid, signal.SIGKILL)
        process.join(10)
        assert config.read_bytes() == before
        assert all(path.read_bytes() == raw for path, raw in tokens.items())
        assert data(GarminAuthService(tmp_path).status())["saved"]
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)
        parent.close()
        child.close()
