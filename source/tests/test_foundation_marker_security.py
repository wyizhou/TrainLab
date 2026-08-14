from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.foundation import FoundationConfig, FoundationTool


def _tool(root: Path) -> FoundationTool:
    return FoundationTool(
        FoundationConfig(
            root,
            root / "data.db",
            root / "raw",
            root / "state",
            root / "state" / "foundation-ready.json",
            root / "state" / "locks" / "foundation.lock",
        )
    )


def test_marker_initial_target_race_is_create_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    original_link = os.link

    def race(*args, **kwargs):
        marker.write_text('{"third":true}')
        marker.chmod(0o600)
        return original_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(Exception):
        tool._atomic_json(marker, {"mine": True})
    assert marker.read_text() == '{"third":true}'


@pytest.mark.parametrize("kind", ["zero", "write_error", "fsync"])
def test_marker_write_failures_do_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    ow = os.write
    of = os.fsync

    def bad_write(fd: int, data: bytes) -> int:
        if kind == "zero":
            return 0
        if kind == "write_error":
            raise OSError("write")
        return ow(fd, data)

    def bad_fsync(fd: int) -> None:
        if kind == "fsync":
            raise OSError("fsync")
        of(fd)

    monkeypatch.setattr(os, "write", bad_write)
    monkeypatch.setattr(os, "fsync", bad_fsync)
    with pytest.raises(Exception):
        tool._atomic_json(marker, {"mine": True})
    assert not marker.exists()


def test_marker_partial_write_loops_to_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    original = os.write

    def partial(fd: int, data: bytes) -> int:
        return original(fd, data[:1])

    monkeypatch.setattr(os, "write", partial)
    tool._atomic_json(marker, {"mine": True})
    assert marker.read_text() == '{"mine": true}'


def test_marker_existing_without_expected_does_not_leak_fd(tmp_path: Path) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    marker.write_text('{"x":1}')
    marker.chmod(0o600)
    before = len(list(Path("/dev/fd").iterdir()))
    for _ in range(20):
        with pytest.raises(Exception):
            tool._atomic_json(marker, {"mine": True})
    assert len(list(Path("/dev/fd").iterdir())) <= before + 2


@pytest.mark.parametrize("raw", [b"{", b"[]"])
def test_invalid_marker_loops_do_not_leak_parent_fd(tmp_path: Path, raw: bytes) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    marker.write_bytes(raw)
    marker.chmod(0o600)
    before = len(list(Path("/dev/fd").iterdir()))
    for _ in range(25):
        with pytest.raises(Exception):
            tool._atomic_json(marker, {"mine": True}, expected_existing={})
    assert len(list(Path("/dev/fd").iterdir())) <= before + 2


def test_temp_cleanup_replacement_claim_blocks_second_publish(tmp_path: Path) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    claim = (
        state / ".m.json.marker-cleanup-" + Path("x")
        if False
        else state / ".m.json.marker-cleanup-test"
    )
    claim.write_text('{"unknown":true}')
    claim.chmod(0o600)
    with pytest.raises(Exception):
        tool._atomic_json(marker, {"mine": True})
    assert claim.exists() and not marker.exists()


@pytest.mark.parametrize(
    "kind",
    ["oldclaim_same_payload", "oldclaim_different_payload", "first_parent_fsync"],
)
def test_migration_claim_or_fsync_failure_remains_blocked(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    marker = state / "m.json"
    marker.write_text('{"v":1}')
    marker.chmod(0o600)
    # A retained recognized marker claim is the persistent fail-closed state
    # used after any pre/post-oldclaim or parent-fsync interruption.
    claim = state / f".m.json.marker-old-{kind}"
    claim.write_text('{"v":1}' if kind != "oldclaim_different_payload" else '{"v":2}')
    claim.chmod(0o600)
    with pytest.raises(Exception):
        tool._atomic_json(marker, {"v": 3}, expected_existing={"v": 1})
    assert claim.exists()


def test_success_and_failure_marker_fd_loops(tmp_path: Path) -> None:
    root = tmp_path / "f"
    root.mkdir(mode=0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    tool = _tool(root)
    before = len(list(Path("/dev/fd").iterdir()))
    for index in range(10):
        marker = state / f"m{index}.json"
        tool._atomic_json(marker, {"v": index})
    assert len(list(Path("/dev/fd").iterdir())) <= before + 2
