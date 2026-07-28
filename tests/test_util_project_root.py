from __future__ import annotations

from pathlib import Path

import pytest

from trainlab.util import project_root


def _project(root: Path) -> Path:
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "harness").mkdir()
    return root


def test_project_root_uses_a_valid_absolute_environment_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    monkeypatch.setenv("TRAINLAB_PROJECT_ROOT", str(root))
    assert project_root() == root.resolve()


@pytest.mark.parametrize("value", ("relative/project", "/missing/project"))
def test_project_root_rejects_invalid_environment_root(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TRAINLAB_PROJECT_ROOT", value)
    with pytest.raises(RuntimeError, match="environment invalid"):
        project_root()


def test_project_root_still_validates_environment_markers_and_does_not_override_explicit_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    configured.mkdir()
    explicit = _project(tmp_path / "explicit")
    monkeypatch.setenv("TRAINLAB_PROJECT_ROOT", str(configured))
    with pytest.raises(RuntimeError, match="not found"):
        project_root()
    assert project_root(explicit) == explicit.resolve()
