from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.resources import resource_bytes, resource_path
from src.util import instance_root, project_root

ROOT = Path(__file__).resolve().parents[2]


RUNTIME_RESOURCES = (
    "harness/shared/HARNESS.md",
    "harness/analysis/HARNESS.md",
    "harness/analysis/daily.md",
    "harness/analysis/weekly.md",
    "harness/mail/HARNESS.md",
    "harness/mail/process-message.md",
    "harness/schemas/foundation.schema.json",
    "harness/schemas/garmin_sync_request.schema.json",
    "harness/schemas/analysis_input.schema.json",
    "harness/schemas/mail_agent_input.schema.json",
    "defaults/analysis.yaml",
)


@pytest.mark.parametrize("logical_path", RUNTIME_RESOURCES)
def test_runtime_resource_is_inside_the_trainlab_package(logical_path: str) -> None:
    path = resource_path(logical_path)
    assert path.is_file()
    assert path.is_relative_to(ROOT / "src" / "resources")
    assert resource_bytes(logical_path) == path.read_bytes()


def test_runtime_schemas_are_valid_json_objects() -> None:
    for logical_path in RUNTIME_RESOURCES:
        if logical_path.endswith(".json"):
            assert isinstance(json.loads(resource_bytes(logical_path)), dict)


def test_product_harness_has_no_second_root_authority() -> None:
    assert not (ROOT / "harness").exists()
    assert not (ROOT / "src.egg-info").exists()
    assert not resource_path("harness/runtime/HARNESS.md").exists()


def test_instance_root_does_not_require_a_source_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "instance"
    (runtime / "config").mkdir(parents=True)
    (runtime / "state").mkdir()
    (runtime / "logs").mkdir()
    monkeypatch.setenv("TRAINLAB_INSTANCE_ROOT", str(runtime))
    assert instance_root() == runtime.resolve()
    assert project_root() == runtime.resolve()
    assert not (runtime / "pyproject.toml").exists()
    assert not (runtime / "harness").exists()


@pytest.mark.parametrize(
    "value",
    (
        "/absolute/path",
        "../escape",
        "harness/../escape",
        "",
    ),
)
def test_runtime_resource_rejects_unsafe_logical_paths(value: str) -> None:
    with pytest.raises(ValueError, match="trainlab_resource_path_invalid"):
        resource_bytes(value)
