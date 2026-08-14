"""A3-03 read-only configuration and filesystem-boundary loader."""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from src.resources import resource_path

CONFIG_SCHEMA_VERSION = "2"
MAX_CONTEXT_BYTES = 1_100_000
MAX_CODEX_TIMEOUT_SECONDS = 600
MAX_DELIVERY_TIMEOUT_SECONDS = 180


class AnalysisConfigurationError(ValueError):
    """Raised before any operational third-layer component can be constructed."""


def _project_user_config_path(project_root: Path) -> Path:
    """Return the current private project config, with a legacy test fallback.

    ``trainlab.json`` is the public name in the source layout.  The
    ``src.json`` fallback keeps old offline fixtures readable during the
    Foundation v4 transition without creating a second production config.
    """

    current = project_root / "config" / "trainlab.json"
    return current if current.exists() else project_root / "config" / "src.json"


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
    active_race_goal: str | None = None
    active_race_goal_source: str = "default"
    marathon_race_date: str | None = None
    marathon_race_date_source: str = "default"
    half_marathon_race_date: str | None = None
    half_marathon_race_date_source: str = "default"
    available_training_weekdays: tuple[int, ...] | None = None
    preferred_long_run_weekday: int | None = None
    coaching_profile_contract: dict[str, Any] | None = None
    project_config_sha256: str = ""


@dataclass(frozen=True)
class ProjectTrainingControls:
    """Model-visible project controls shared by every analysis entry point."""

    training_difficulty_level: int
    training_difficulty_source: str
    marathon_target_finish_time: str | None
    marathon_target_finish_time_source: str
    half_marathon_target_finish_time: str | None
    half_marathon_target_finish_time_source: str
    active_race_goal: str | None = None
    active_race_goal_source: str = "default"
    marathon_race_date: str | None = None
    marathon_race_date_source: str = "default"
    half_marathon_race_date: str | None = None
    half_marathon_race_date_source: str = "default"
    available_training_weekdays: tuple[int, ...] | None = None
    preferred_long_run_weekday: int | None = None
    coaching_profile_contract: dict[str, Any] | None = None
    project_config_sha256: str = ""

    def as_context(self) -> dict[str, Any]:
        return {
            "contract_version": "1",
            "training_method": "hansons_marathon_method",
            "allowed_future_activity_kinds": ["running", "climbing", "rest"],
            "training_difficulty_level": self.training_difficulty_level,
            "training_difficulty_source": self.training_difficulty_source,
            "marathon_target_finish_time": self.marathon_target_finish_time,
            "marathon_target_finish_time_source": self.marathon_target_finish_time_source,
            "half_marathon_target_finish_time": self.half_marathon_target_finish_time,
            "half_marathon_target_finish_time_source": self.half_marathon_target_finish_time_source,
            "active_race_goal": self.active_race_goal,
            "active_race_goal_source": self.active_race_goal_source,
            "marathon_race_date": self.marathon_race_date,
            "marathon_race_date_source": self.marathon_race_date_source,
            "half_marathon_race_date": self.half_marathon_race_date,
            "half_marathon_race_date_source": self.half_marathon_race_date_source,
            "available_training_weekdays": None
            if self.available_training_weekdays is None
            else list(self.available_training_weekdays),
            "preferred_long_run_weekday": self.preferred_long_run_weekday,
            "coaching_profile_contract": self.coaching_profile_contract
            or {
                "schema_version": "1",
                "status": "unconfigured",
                "weekly_capacity_km": None,
                "weekly_frequency": None,
                "long_run_max_km": None,
                "hard_load_max": None,
                "hard_load_min_gap_days": None,
                "available_weekdays": [],
                "climbing_schedule": [],
                "race_goal": None,
                "progression_rule": "conservative",
            },
            "project_config_sha256": self.project_config_sha256,
        }


def _inside_project_root(project_root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise AnalysisConfigurationError(
            f"analysis_config_path_escapes_project_root:{label}"
        )
    return resolved


def _schema() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).with_name("schemas") / "analysis_config.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _validate_schema(payload: Any) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise AnalysisConfigurationError(
            f"analysis_config_schema_invalid:{location}:{error.message}"
        )
    return payload["analysis"]


def _require_private_directory(path: Path, label: str) -> None:
    if not path.is_dir():
        raise AnalysisConfigurationError(
            f"analysis_config_private_directory_missing:{label}"
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        raise AnalysisConfigurationError(
            f"analysis_config_private_directory_mode:{label}:{mode:03o}"
        )


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


_RACE_GOALS = {"marathon", "half_marathon"}


def _race_goal(payload: dict[str, Any]) -> tuple[str | None, str]:
    if "active_race_goal" not in payload or payload["active_race_goal"] is None:
        return (
            None,
            "default" if "active_race_goal" not in payload else "project_global_config",
        )
    value = payload["active_race_goal"]
    if not isinstance(value, str) or value not in _RACE_GOALS:
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:active_race_goal"
        )
    return value, "project_global_config"


def _race_date(payload: dict[str, Any], key: str) -> tuple[str | None, str]:
    if key not in payload or payload[key] is None:
        return None, "default" if key not in payload else "project_global_config"
    value = payload[key]
    if not isinstance(value, str):
        raise AnalysisConfigurationError(f"analysis_project_config_invalid:{key}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AnalysisConfigurationError(
            f"analysis_project_config_invalid:{key}"
        ) from None
    if parsed.isoformat() != value:
        raise AnalysisConfigurationError(f"analysis_project_config_invalid:{key}")
    return value, "project_global_config"


def _weekdays(payload: dict[str, Any]) -> tuple[int, ...] | None:
    if (
        "available_training_weekdays" not in payload
        or payload["available_training_weekdays"] is None
    ):
        return None
    value = payload["available_training_weekdays"]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise AnalysisConfigurationError(
                "analysis_project_config_invalid:available_training_weekdays"
            )
        try:
            values = [int(part) for part in parts]
        except ValueError:
            raise AnalysisConfigurationError(
                "analysis_project_config_invalid:available_training_weekdays"
            ) from None
    elif isinstance(value, list):
        values = value
    else:
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:available_training_weekdays"
        )
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 7
        for item in values
    ):
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:available_training_weekdays"
        )
    result = tuple(sorted(set(values)))
    if len(result) != len(values):
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:available_training_weekdays"
        )
    return result


def _preferred_long_run_weekday(
    payload: dict[str, Any], available: tuple[int, ...] | None
) -> int | None:
    value = payload.get("preferred_long_run_weekday")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 7:
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:preferred_long_run_weekday"
        )
    if available is not None and value not in available:
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:preferred_long_run_weekday"
        )
    return value


def _coaching_profile(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("coaching_profile_contract")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:coaching_profile_contract"
        )
    schema = json.loads(
        resource_path(
            "harness/schemas/coaching_profile_contract_v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise AnalysisConfigurationError(
            f"analysis_project_config_invalid:coaching_profile_contract.{location}"
        )
    return value


def load_project_training_controls(project_root: Path) -> ProjectTrainingControls:
    """Load model-visible training controls without exposing mail routing."""

    path = _project_user_config_path(project_root)
    if not path.exists():
        return ProjectTrainingControls(
            2,
            "default",
            None,
            "default",
            None,
            "default",
            project_config_sha256=sha256(b"missing").hexdigest(),
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:root"
        ) from None
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise AnalysisConfigurationError(
            "analysis_project_config_invalid:schema_version"
        )
    if "training_difficulty_level" not in payload:
        level, difficulty_source = 2, "default"
    else:
        level = payload["training_difficulty_level"]
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 5:
            raise AnalysisConfigurationError(
                "analysis_project_config_invalid:training_difficulty_level"
            )
        difficulty_source = "project_global_config"
    marathon, marathon_source = _finish_time(payload, "marathon_target_finish_time")
    half_marathon, half_marathon_source = _finish_time(
        payload, "half_marathon_target_finish_time"
    )
    active_goal, active_goal_source = _race_goal(payload)
    marathon_date, marathon_date_source = _race_date(payload, "marathon_race_date")
    half_date, half_date_source = _race_date(payload, "half_marathon_race_date")
    available = _weekdays(payload)
    preferred_long_run = _preferred_long_run_weekday(payload, available)
    coaching_profile = _coaching_profile(payload)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return ProjectTrainingControls(
        level,
        difficulty_source,
        marathon,
        marathon_source,
        half_marathon,
        half_marathon_source,
        active_goal,
        active_goal_source,
        marathon_date,
        marathon_date_source,
        half_date,
        half_date_source,
        available,
        preferred_long_run,
        coaching_profile,
        sha256(canonical.encode("utf-8")).hexdigest(),
    )


def load_analysis_config(
    project_root: Path, config_path: Path | None = None
) -> AnalysisConfig:
    """Load a static A3-03 config without creating files or invoking services."""

    root = project_root.resolve()
    if not root.is_dir():
        raise AnalysisConfigurationError("analysis_config_project_root_missing")
    if config_path is None:
        config_file = resource_path("defaults/analysis.yaml")
    else:
        config_file = _inside_project_root(
            root,
            config_path if config_path.is_absolute() else root / config_path,
            "config",
        )
    if not config_file.is_file():
        raise AnalysisConfigurationError("analysis_config_file_missing")
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise AnalysisConfigurationError("analysis_config_yaml_invalid") from error
    analysis = _validate_schema(payload)

    def configured_path(key: str) -> Path:
        return _inside_project_root(root, root / analysis[key], key)

    harness_root = resource_path(analysis["harness_root"])
    input_schema = resource_path(analysis["input_schema"])
    output_schema = resource_path(analysis["output_schema"])
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
        active_race_goal=controls.active_race_goal,
        active_race_goal_source=controls.active_race_goal_source,
        marathon_race_date=controls.marathon_race_date,
        marathon_race_date_source=controls.marathon_race_date_source,
        half_marathon_race_date=controls.half_marathon_race_date,
        half_marathon_race_date_source=controls.half_marathon_race_date_source,
        available_training_weekdays=controls.available_training_weekdays,
        preferred_long_run_weekday=controls.preferred_long_run_weekday,
        coaching_profile_contract=controls.coaching_profile_contract,
        project_config_sha256=controls.project_config_sha256,
    )
