from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import storage

SOURCE = Path(__file__).resolve().parents[3]
DEFAULT_INSTANCE = SOURCE / "state/fit-weekly"
SERVICES = {"garmin", "gmail", "model"}


def instance_path(value: str | Path) -> Path:
    path = Path(value)
    if ".." in path.parts or "\0" in str(path):
        raise ValueError("instance_path_invalid")
    if not path.is_absolute():
        path = SOURCE / path
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise ValueError("instance_path_invalid")
    return path


def relative_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("config_path_invalid")
    path = Path(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("config_path_invalid")
    return root / path


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("private_json_invalid")
        result[key] = value
    return result


def private_path(root: Path, value: Any, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("config_path_invalid")
    path = Path(value)
    if not path.is_absolute():
        path = relative_path(root, value)
    path = instance_path(path)
    storage.private_entry(path, directory=directory, nonempty=not directory)
    storage.private_entry(path if directory else path.parent, directory=True)
    if path.is_relative_to(root):
        parent = root
        for part in path.relative_to(root).parts[:-1]:
            parent /= part
            storage.private_entry(parent, directory=True)
    return path


def read_object(root: Path, path: Path, *, limit: int = 131072) -> dict[str, Any]:
    try:
        root = instance_path(root)
        relative = path.relative_to(root)
        if ".." in relative.parts:
            raise ValueError("path")
        storage.private_entry(root, directory=True)
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            storage.private_entry(parent, directory=True)
        storage.private_entry(path, nonempty=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("size")
        value = json.loads(raw, object_pairs_hook=object_pairs)
        if not isinstance(value, dict):
            raise ValueError("object")
        storage.canonical(value)
        return value
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("private_json_invalid") from None


@dataclass(frozen=True)
class Config:
    root: Path
    goal_path: Path
    _services: dict[str, str] = field(repr=False)

    def service_path(self, name: str) -> Path:
        if name not in SERVICES or name not in self._services:
            raise ValueError("config_service_unavailable")
        value = self._services[name]
        return (
            instance_path(value)
            if Path(value).is_absolute()
            else relative_path(self.root, value)
        )

    def service(self, name: str) -> dict[str, Any]:
        try:
            path = self.service_path(name)
            private_path(self.root, str(path))
            return read_object(
                self.root if path.is_relative_to(self.root) else path.parent, path
            )
        except ValueError:
            raise ValueError("config_service_unavailable") from None


def load(root: Path, filename: str = "config.json") -> Config:
    try:
        root = instance_path(root)
        value = read_object(root, relative_path(root, filename))
        if (
            set(value) != {"schema_version", "goal", "services"}
            or value["schema_version"] != "fit_run_config_v1"
            or not isinstance(value["services"], dict)
            or not set(value["services"]) <= SERVICES
        ):
            raise ValueError("shape")
        for path in value["services"].values():
            if isinstance(path, str) and Path(path).is_absolute():
                instance_path(path)
            else:
                relative_path(root, path)
        goal_path = (
            instance_path(value["goal"])
            if isinstance(value["goal"], str) and Path(value["goal"]).is_absolute()
            else relative_path(root, value["goal"])
        )
        return Config(root, goal_path, dict(value["services"]))
    except (ValueError, TypeError, KeyError):
        raise ValueError("run_config_invalid") from None
