"""A3-03 read-only configuration and filesystem-boundary loader."""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


CONFIG_SCHEMA_VERSION = "1"
MAX_CONTEXT_BYTES = 1_100_000
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
    training_difficulty_level: int = 2
    training_difficulty_source: str = "default"
    marathon_target_finish_time: str | None = None
    marathon_target_finish_time_source: str = "default"
    half_marathon_target_finish_time: str | None = None
    half_marathon_target_finish_time_source: str = "default"


@dataclass(frozen=True)
class ProjectTrainingControls:
    """Model-visible project controls shared by every analysis entry point."""

    training_difficulty_level: int
    training_difficulty_source: str
    marathon_target_finish_time: str | None
    marathon_target_finish_time_source: str
    half_marathon_target_finish_time: str | None
    half_marathon_target_finish_time_source: str

    def as_context(self) -> dict[str, Any]:
        return {
            "contract_version": "1",
            "training_method": "hansons_marathon_method",
            "allowed_future_activity_kinds": ["running", "rest"],
            "training_difficulty_level": self.training_difficulty_level,
            "training_difficulty_source": self.training_difficulty_source,
            "marathon_target_finish_time": self.marathon_target_finish_time,
            "marathon_target_finish_time_source": self.marathon_target_finish_time_source,
            "half_marathon_target_finish_time": self.half_marathon_target_finish_time,
            "half_marathon_target_finish_time_source": self.half_marathon_target_finish_time_source,
        }


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


_FINISH_TIME = re.compile(r"^(?P<hours>\d{2}):(?P<minutes>[0-5]\d)$")


def _finish_time(payload: dict[str, Any], key: str) -> tuple[str | None, str]:
    if key not in payload:
        return None, "default"
    value = payload[key]
    if value is None:
        return None, "project_global_config"
    match = _FINISH_TIME.fullmatch(value) if isinstance(value, str) else None
    if match is None or (
        int(match.group("hours")) == 0 and int(match.group("minutes")) == 0
    ):
        raise AnalysisConfigurationError(f"analysis_project_config_invalid:{key}")
    return value, "project_global_config"


def load_project_training_controls(project_root: Path) -> ProjectTrainingControls:
    """Load model-visible training controls without exposing mail routing."""

    path = project_root / "config" / "trainlab.json"
    if not path.exists():
        return ProjectTrainingControls(2, "default", None, "default", None, "default")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AnalysisConfigurationError("analysis_project_config_invalid:root") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise AnalysisConfigurationError("analysis_project_config_invalid:schema_version")
    if "training_difficulty_level" not in payload:
        level, difficulty_source = 2, "default"
    else:
        level = payload["training_difficulty_level"]
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 1 <= level <= 5
        ):
            raise AnalysisConfigurationError(
                "analysis_project_config_invalid:training_difficulty_level"
            )
        difficulty_source = "project_global_config"
    marathon, marathon_source = _finish_time(
        payload, "marathon_target_finish_time"
    )
    half_marathon, half_marathon_source = _finish_time(
        payload, "half_marathon_target_finish_time"
    )
    return ProjectTrainingControls(
        level,
        difficulty_source,
        marathon,
        marathon_source,
        half_marathon,
        half_marathon_source,
    )


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
    controls = load_project_training_controls(root)
    return AnalysisConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        project_root=root,
        timezone=analysis["timezone"],
        harness_root=harness_root,
        input_schema=input_schema,
        output_schema=output_schema,
        max_context_bytes=analysis["max_context_bytes"],
        daily_baseline_days=analysis["completed_window_days"],
        weekly_baseline_days=analysis["completed_window_days"],
        max_recent_daily_artifacts=analysis["max_recent_daily_artifacts"],
        codex_timeout_seconds=analysis["codex_timeout_seconds"],
        delivery_timeout_seconds=analysis["delivery_timeout_seconds"],
        lock_path=lock_path,
        temp_root=temp_root,
        training_difficulty_level=controls.training_difficulty_level,
        training_difficulty_source=controls.training_difficulty_source,
        marathon_target_finish_time=controls.marathon_target_finish_time,
        marathon_target_finish_time_source=controls.marathon_target_finish_time_source,
        half_marathon_target_finish_time=controls.half_marathon_target_finish_time,
        half_marathon_target_finish_time_source=controls.half_marathon_target_finish_time_source,
    )
