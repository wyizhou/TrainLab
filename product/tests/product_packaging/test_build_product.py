from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "trainlab_build_product", ROOT / "tools" / "build_product.py"
)
assert SPEC is not None and SPEC.loader is not None
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


@pytest.mark.parametrize(
    "relative",
    (
        "state/data.db",
        "logs/runtime.log",
        "test_data/new/Running.fit",
        "config/foundation.yaml",
        "src/trainlab/token.json",
        ".orchestration/plan.json",
        "docs/exec-plans/active/example.md",
        "docs/memory.md",
        "docs/PLANS.md",
    ),
)
def test_private_or_development_material_is_rejected(relative: str) -> None:
    with pytest.raises(RuntimeError, match="product_build_"):
        BUILD._validate(Path(relative))


@pytest.mark.parametrize(
    "relative",
    (
        "pyproject.toml",
        "requirements.lock",
        "src/trainlab/__init__.py",
        "harness/shared/HARNESS.md",
        "config/trainlab.example.json",
        "deploy/launchd/install-local-supervisor.sh",
    ),
)
def test_runtime_allowlist_accepts_public_product_files(relative: str) -> None:
    BUILD._validate(Path(relative))
