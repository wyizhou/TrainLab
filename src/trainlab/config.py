from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .util import project_root


@dataclass(frozen=True)
class Settings:
    root: Path
    values: dict[str, Any]
    profile: dict[str, Any]
    compression: dict[str, Any]
    metric_catalog: dict[str, Any]
    decision_policy: dict[str, Any]
    running_policy: dict[str, Any]
    strength_policy: dict[str, Any]
    exercise_catalog: dict[str, Any]

    def path(self, key: str) -> Path:
        value = self.values["paths"][key]
        return (self.root / value).resolve()

    @property
    def database_path(self) -> Path:
        return self.path("database")

    @property
    def timezone(self) -> str:
        return str(self.values.get("timezone", "Asia/Singapore"))


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle)
    if not isinstance(content, dict):
        raise ValueError(f"Expected mapping in {path}")
    return content


def load_settings(root: Path | None = None) -> Settings:
    actual_root = project_root(root)
    config_dir = actual_root / "config"
    configured_path = os.environ.get("TRAINLAB_CONFIG")
    values_path = Path(configured_path).expanduser() if configured_path else config_dir / "trainlab.yaml"
    if not values_path.is_absolute():
        values_path = actual_root / values_path
    values = load_yaml(values_path.resolve())
    _validate(actual_root / "harness" / "schemas" / "config.schema.json", values, "config/trainlab.yaml")
    required_paths = {"database", "health_workbook", "fit_directory", "state_directory", "log_directory"}
    missing = required_paths - set(values.get("paths", {}))
    if missing:
        raise ValueError(f"Missing configured paths: {', '.join(sorted(missing))}")
    profile = load_yaml(config_dir / "profile.yaml")
    compression = load_yaml(config_dir / "compression.yaml")
    decision_policy = load_yaml(config_dir / "decision_policy.yaml")
    running_policy = load_yaml(config_dir / "running_policy.yaml")
    _validate(actual_root / "harness" / "schemas" / "profile.schema.json", profile, "config/profile.yaml")
    _validate(actual_root / "harness" / "schemas" / "compression.schema.json", compression, "config/compression.yaml")
    _validate(actual_root / "harness" / "schemas" / "decision_policy.schema.json", decision_policy, "config/decision_policy.yaml")
    _validate(actual_root / "harness" / "schemas" / "running_policy.schema.json", running_policy, "config/running_policy.yaml")
    strength_policy = load_yaml(config_dir / "strength_policy.yaml")
    _validate(actual_root / "harness" / "schemas" / "strength_policy.schema.json", strength_policy, "config/strength_policy.yaml")
    return Settings(
        root=actual_root,
        values=values,
        profile=profile,
        compression=compression,
        metric_catalog=load_yaml(config_dir / "metric_catalog.yaml"),
        decision_policy=decision_policy,
        running_policy=running_policy,
        strength_policy=strength_policy,
        exercise_catalog=load_yaml(config_dir / "exercise_catalog.yaml"),
    )


def _validate(schema_path: Path, value: dict[str, Any], label: str) -> None:
    schema = load_yaml(schema_path) if schema_path.suffix in {".yaml", ".yml"} else __import__("json").loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        path = ".".join(str(item) for item in first.path) or "<root>"
        raise ValueError(f"{label} failed Schema validation at {path}: {first.message}")
