from __future__ import annotations

from pathlib import Path

import pytest

from src.util import instance_root, project_root


def _instance(root: Path) -> Path:
    root.mkdir()
    for name in ("config", "state", "logs"):
        (root / name).mkdir()
    return root


def test_instance_root_uses_an_external_runtime_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "instance"
    for name in ("config", "state", "logs"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("TRAINLAB_INSTANCE_ROOT", str(root))
    assert instance_root() == root.resolve()
    assert project_root() == root.resolve()


@pytest.mark.parametrize("value", ("relative/project", "/missing/project"))
def test_project_root_rejects_invalid_environment_root(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TRAINLAB_INSTANCE_ROOT", value)
    with pytest.raises(RuntimeError, match="environment invalid"):
        project_root()


def test_project_root_still_validates_environment_markers_and_does_not_override_explicit_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "configured"
    configured.mkdir()
    explicit = _instance(tmp_path / "explicit")
    monkeypatch.setenv("TRAINLAB_INSTANCE_ROOT", str(configured))
    with pytest.raises(RuntimeError, match="markers missing"):
        project_root()
    assert project_root(explicit) == explicit.resolve()


def test_legacy_project_root_environment_is_not_a_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _instance(tmp_path / "project")
    monkeypatch.delenv("TRAINLAB_INSTANCE_ROOT", raising=False)
    monkeypatch.setenv("TRAINLAB_PROJECT_ROOT", str(root))
    monkeypatch.chdir(root)
    with pytest.raises(RuntimeError, match="environment missing"):
        instance_root()


def test_instance_root_does_not_discover_runtime_markers_from_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _instance(tmp_path / "instance")
    monkeypatch.delenv("TRAINLAB_INSTANCE_ROOT", raising=False)
    monkeypatch.chdir(root)

    with pytest.raises(RuntimeError, match="environment missing"):
        instance_root()
