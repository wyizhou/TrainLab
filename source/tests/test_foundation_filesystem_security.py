from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.foundation import FoundationConfig, FoundationRequest, FoundationTool

UTC = "2026-07-23T00:00:00Z"


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )


def init(tool: FoundationTool) -> object:
    return tool.execute(FoundationRequest("init", "filesystem-security", UTC))


def test_fresh_init_secures_every_layout_component_and_ready_rejects_intermediate_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "foundation"
    tool = FoundationTool(config(root))
    assert init(tool).status == "initialized"
    directories = [
        root,
        root / "raw",
        root / "raw" / "garmin",
        root / "raw" / "garmin" / "fit",
        root / "raw" / "garmin" / "json",
        root / "raw" / "gmail",
        root / "raw" / "gmail" / "json",
        root / "raw" / "gmail" / "attachments",
        root / "raw" / "legacy",
        root / "raw" / "legacy" / "health_xlsx",
        root / "raw" / "legacy" / "fit",
        root / "state",
        root / "state" / "locks",
    ]
    assert all(
        path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o700
        for path in directories
    )
    for path in (root / "data.db", root / "state" / "foundation-ready.json"):
        assert (
            path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o600
        )
    before = {
        path.relative_to(root): (
            path.read_bytes() if path.is_file() else path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob("*")]
    }
    (root / "raw" / "garmin").chmod(0o755)
    receipt = init(tool)
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert (root / "raw" / "garmin").stat().st_mode & 0o777 == 0o755
    # The only deliberate post-snapshot change is the injected unsafe mode.
    assert (root / "data.db").read_bytes() == before[Path("data.db")]


@pytest.mark.parametrize(
    "data_root,child",
    [
        ("/tmp/escape", "data.db"),
        ("../escape", "data.db"),
        (".", "data.db"),
        ("state/foundation", "../data.db"),
    ],
)
def test_config_load_rejects_root_escape_and_path_aliases(
    tmp_path: Path, data_root: str, child: str
) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / "config" / "foundation.yaml").write_text(
        f"foundation:\n  data_root: {data_root}\n  database_path: {child}\n  raw_root: raw\n  state_root: state\n  ready_marker: state/foundation-ready.json\n  lock_path: state/locks/foundation.lock\n"
    )
    with pytest.raises(ValueError):
        FoundationConfig.load(project)


def test_direct_config_and_symlinked_intermediate_are_rejected_before_init(
    tmp_path: Path,
) -> None:
    root = tmp_path / "foundation"
    outside = tmp_path / "outside"
    outside.mkdir()
    unsafe = FoundationConfig(
        root,
        outside / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )
    assert (
        FoundationTool(unsafe)
        .execute(FoundationRequest("init", "unsafe-config", UTC))
        .status
        == "failed"
    )
    root.mkdir(mode=0o700)
    (root / "raw").symlink_to(outside, target_is_directory=True)
    receipt = FoundationTool(config(root)).execute(
        FoundationRequest("init", "symlink-layout", UTC)
    )
    assert receipt.status in {"failed", "lock_busy"}
    assert (root / "raw").is_symlink()


def test_direct_config_rejects_role_nesting_and_date_only_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "foundation"
    nested = FoundationConfig(
        root,
        root / "raw" / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )
    assert (
        FoundationTool(nested).execute(FoundationRequest("init", "nested", UTC)).status
        == "failed"
    )
    tool = FoundationTool(config(root))
    receipt = tool.execute(FoundationRequest("init", "bad-date", "2026-07-23Z"))
    assert receipt.status == "failed" and not root.exists()


def test_programmatic_nested_root_creates_safe_missing_parents(tmp_path: Path) -> None:
    root = tmp_path / "snapshot" / "nested" / "data"
    tool = FoundationTool(config(root))
    assert init(tool).status == "initialized"
    assert all(
        path.stat().st_mode & 0o777 == 0o700
        for path in (tmp_path / "snapshot", tmp_path / "snapshot" / "nested", root)
    )
    assert init(tool).status == "already_initialized"


def test_fs_a_rejects_ancestor_symlink_and_oversize_read(tmp_path: Path) -> None:
    root = tmp_path / "foundation"
    tool = FoundationTool(config(root))
    assert init(tool).status == "initialized"
    parent = root / "state"
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = root / "state-real"
    parent.rename(moved)
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        tool._fsync_directory(parent)
    parent.unlink()
    moved.rename(parent)
    marker = parent / "large.json"
    marker.write_bytes(b"x" * 32)
    marker.chmod(0o600)
    with pytest.raises(OSError, match="too_large"):
        tool._secure_read_file(marker, 8)


def test_fs_a_read_detects_name_replacement_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "foundation"
    tool = FoundationTool(config(root))
    assert init(tool).status == "initialized"
    target = root / "state" / "read.json"
    target.write_text("old")
    target.chmod(0o600)
    original_read = os.read
    changed = False

    def replace(fd: int, size: int) -> bytes:
        nonlocal changed
        data = original_read(fd, size)
        if not changed:
            changed = True
            replacement = target.with_name("replacement.json")
            replacement.write_text("new")
            replacement.chmod(0o600)
            os.replace(replacement, target)
        return data

    monkeypatch.setattr(os, "read", replace)
    with pytest.raises(OSError, match="replaced"):
        tool._secure_read_file(target)


def test_fs_c_project_ancestors_may_be_0755_but_data_root_is_owner_only(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / "state").mkdir()
    for directory in (project, project / "state"):
        directory.chmod(0o755)
    (project / "config" / "foundation.yaml").write_text(
        "foundation:\n  data_root: state/foundation\n  database_path: data.db\n  raw_root: raw\n  state_root: state\n  ready_marker: state/foundation-ready.json\n  lock_path: state/locks/foundation.lock\n"
    )
    tool = FoundationTool(FoundationConfig.load(project))
    assert init(tool).status == "initialized"
    assert (project / "state" / "foundation").stat().st_mode & 0o777 == 0o700


def test_fs_c_rejects_writable_or_symlink_ancestor_without_creation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    project.chmod(0o777)
    config_bad = FoundationConfig(
        project / "state" / "foundation",
        project / "state" / "foundation" / "data.db",
        project / "state" / "foundation" / "raw",
        project / "state" / "foundation" / "state",
        project / "state" / "foundation" / "state" / "foundation-ready.json",
        project / "state" / "foundation" / "state" / "locks" / "foundation.lock",
        project,
    )
    assert (
        FoundationTool(config_bad)
        .execute(FoundationRequest("init", "bad-ancestor", UTC))
        .status
        == "failed"
    )
    assert not (project / "state").exists()
