"""Immutable TrainLab product resources shipped with the source project.

The package contains product Harness text, JSON schemas, policies and public
defaults.  Mutable instance configuration, state, logs and credentials never
belong here.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path, PurePosixPath


class TrainLabResourceError(RuntimeError):
    """An immutable package resource is missing or not filesystem-backed."""


def _parts(logical_path: str) -> tuple[str, ...]:
    if not isinstance(logical_path, str) or not logical_path:
        raise ValueError("trainlab_resource_path_invalid")
    candidate = PurePosixPath(logical_path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != logical_path
    ):
        raise ValueError("trainlab_resource_path_invalid")
    return candidate.parts


def resource_path(logical_path: str) -> Path:
    """Return one installed resource path without consulting the current cwd."""

    candidate = files(__package__).joinpath(*_parts(logical_path))
    if not isinstance(candidate, Path):
        raise TrainLabResourceError("trainlab_resource_not_filesystem_backed")
    return candidate


def resource_bytes(logical_path: str) -> bytes:
    """Read one immutable resource with a stable, content-free failure."""

    path = resource_path(logical_path)
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        return path.read_bytes()
    except OSError as exc:
        raise TrainLabResourceError("trainlab_resource_unavailable") from exc


def resource_text(logical_path: str) -> str:
    try:
        return resource_bytes(logical_path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrainLabResourceError("trainlab_resource_encoding_invalid") from exc


def resource_root() -> Path:
    """Return the root used by legacy fixed-relative package readers."""

    return resource_path("harness").parent


__all__ = [
    "TrainLabResourceError",
    "resource_bytes",
    "resource_path",
    "resource_root",
    "resource_text",
]
