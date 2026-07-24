"""A3-03 read-only configuration and filesystem-boundary loader."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


CONFIG_SCHEMA_VERSION = "1"
MAX_CONTEXT_BYTES = 1_000_000
MAX_CODEX_TIMEOUT_SECONDS = 600
MAX_DELIVERY_TIMEOUT_SECONDS = 180


class AnalysisConfigurationError(ValueError):
    """Raised before any operational third-layer component can be constructed."""


@dataclass(frozen=True)
class AnalysisConfig:
    schema_version: str
    project_root: Path
    timezone: str
    harness_root: Path
    input_schema: Path
    output_schema: Path
    max_context_bytes: int
    daily_baseline_days: int
    weekly_baseline_days: int
    max_recent_daily_artifacts: int
    codex_timeout_seconds: int
    delivery_timeout_seconds: int
    lock_path: Path
    temp_root: Path


def _inside_project_root(project_root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise AnalysisConfigurationError(f"analysis_config_path_escapes_project_root:{label}")
    return resolved


def _schema() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("schemas") / "analysis_config.schema.json").read_text(encoding="utf-8"))


def _validate_schema(payload: Any) -> dict[str, Any]:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise AnalysisConfigurationError(f"analysis_config_schema_invalid:{location}:{error.message}")
    return payload["analysis"]


def _require_private_directory(path: Path, label: str) -> None:
    if not path.is_dir():
        raise AnalysisConfigurationError(f"analysis_config_private_directory_missing:{label}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        raise AnalysisConfigurationError(f"analysis_config_private_directory_mode:{label}:{mode:03o}")


def load_analysis_config(project_root: Path, config_path: Path) -> AnalysisConfig:
    """Load a static A3-03 config without creating files or invoking services."""

    root = project_root.resolve()
    if not root.is_dir():
        raise AnalysisConfigurationError("analysis_config_project_root_missing")
    config_file = _inside_project_root(root, config_path if config_path.is_absolute() else root / config_path, "config")
    if not config_file.is_file():
        raise AnalysisConfigurationError("analysis_config_file_missing")
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise AnalysisConfigurationError("analysis_config_yaml_invalid") from error
    analysis = _validate_schema(payload)

    def configured_path(key: str) -> Path:
        return _inside_project_root(root, root / analysis[key], key)

    harness_root = configured_path("harness_root")
    input_schema = configured_path("input_schema")
    output_schema = configured_path("output_schema")
    lock_path = configured_path("lock_path")
    temp_root = configured_path("temp_root")
    _require_private_directory(temp_root, "temp_root")
    _require_private_directory(lock_path.parent, "lock_parent")
    return AnalysisConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        project_root=root,
        timezone=analysis["timezone"],
        harness_root=harness_root,
        input_schema=input_schema,
        output_schema=output_schema,
        max_context_bytes=analysis["max_context_bytes"],
        daily_baseline_days=analysis["daily_baseline_days"],
        weekly_baseline_days=analysis["weekly_baseline_days"],
        max_recent_daily_artifacts=analysis["max_recent_daily_artifacts"],
        codex_timeout_seconds=analysis["codex_timeout_seconds"],
        delivery_timeout_seconds=analysis["delivery_timeout_seconds"],
        lock_path=lock_path,
        temp_root=temp_root,
    )
