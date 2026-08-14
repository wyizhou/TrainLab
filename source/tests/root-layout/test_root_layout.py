from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_source_is_the_only_product_tree() -> None:
    assert not (ROOT / "product").exists()
    assert (ROOT / "source" / "pyproject.toml").is_file()
    assert (ROOT / "source" / "requirements.lock").is_file()
    assert (ROOT / "source" / "src" / "__init__.py").is_file()
    assert (ROOT / "source" / "tests").is_dir()
    assert (
        ROOT / "source" / "src" / "resources" / "harness" / "shared" / "HARNESS.md"
    ).is_file()
    assert not (ROOT / "src").exists()
    assert not (ROOT / "tests").exists()
    assert not (ROOT / "deploy").exists()
    assert not (ROOT / "dist").exists()
    assert not (ROOT / "build").exists()


def test_source_configuration_is_tool_only() -> None:
    document = tomllib.loads(
        (ROOT / "source" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "build-system" not in document
    assert "scripts" not in document.get("project", {})
    assert document["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_ci_runs_from_source_without_retired_runtime_layers() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "working-directory: source" in workflow
    assert "build_product" not in workflow
    assert "supervisor" not in workflow
    assert "orchestrate" not in workflow
    assert "pip install --require-hashes -r requirements.lock" in workflow


def test_private_paths_are_ignored_and_public_examples_remain_visible() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in (
        "/data-backup/",
        "/source/state/**",
        "/source/logs/**",
        "/source/config/**",
    ):
        assert required in ignore
    assert "!/source/config/README.md" in ignore
    assert "!/source/config/examples/" in ignore
    assert not (ROOT / "test_data").exists()


def test_no_second_product_harness_or_orchestration_package_exists() -> None:
    assert not (ROOT / "harness").exists()
    assert not (ROOT / "source" / "src" / "orchestration").exists()
    assert not (ROOT / "source" / "src" / "local_supervisor.py").exists()


def test_source_entrypoint_is_documented() -> None:
    document = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "source/index.py" in document
