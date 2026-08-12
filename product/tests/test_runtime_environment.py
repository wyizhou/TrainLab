from __future__ import annotations

import os
from pathlib import Path

from trainlab.runtime_environment import bounded_runtime_path


def test_bounded_runtime_path_keeps_only_existing_absolute_directories(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    value = os.pathsep.join((str(first), "relative", "", str(first), str(tmp_path / "missing"), str(second)))
    assert bounded_runtime_path(value) == os.pathsep.join((str(first), str(second)))


def test_bounded_runtime_path_rejects_world_writable_but_keeps_group_writable_directories(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    group_writable = tmp_path / "group-writable"
    writable = tmp_path / "world-writable"
    trusted.mkdir(mode=0o755)
    group_writable.mkdir(mode=0o755)
    writable.mkdir(mode=0o755)
    group_writable.chmod(0o775)
    writable.chmod(0o777)
    assert bounded_runtime_path(os.pathsep.join((str(trusted), str(group_writable), str(writable)))) == os.pathsep.join((str(trusted), str(group_writable)))


def test_bounded_runtime_path_rejects_unowned_directories(tmp_path: Path, monkeypatch) -> None:
    owned = tmp_path / "owned"
    owned.mkdir(mode=0o755)
    import trainlab.runtime_environment as module
    monkeypatch.setattr(module.os, "geteuid", lambda: -1)
    assert bounded_runtime_path(str(owned)) == ""


def test_bounded_runtime_path_never_uses_a_non_string_source() -> None:
    assert bounded_runtime_path(None) == bounded_runtime_path()
    assert bounded_runtime_path(42) == ""  # type: ignore[arg-type]
