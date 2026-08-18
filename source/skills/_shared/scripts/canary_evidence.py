#!/usr/bin/env python3
"""Shared public-canary location checks for producers and consumers."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Collection
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_ROOT_PARENT = Path(tempfile.gettempdir())
PUBLIC_ROOT_PREFIX = "trainlab-m9-schema-canary-r07."


class PublicCanaryRootError(ValueError):
    """The path is not an isolated public-canary root."""


def require_public_canary_root(path: Path, *, allowed_entries: Collection[str]) -> Path:
    """Require one owner-only, repository-external, non-Candidate temp root."""

    root = Path(os.path.abspath(path))
    try:
        metadata = root.lstat()
        public_parent = PUBLIC_ROOT_PARENT.resolve(strict=True)
        root.relative_to(public_parent)
    except (OSError, ValueError) as exc:
        raise PublicCanaryRootError("schema_canary_root_invalid") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or root.is_symlink()
        or root.resolve(strict=True) != root
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o700
        or root == public_parent
        or root.parent != public_parent
        or not root.name.startswith(PUBLIC_ROOT_PREFIX)
        or root == SOURCE_ROOT
        or SOURCE_ROOT in root.parents
    ):
        raise PublicCanaryRootError("schema_canary_root_invalid")
    for ancestor in (root, *root.parents):
        if ancestor == public_parent:
            break
        if ancestor.name.startswith("trainlab-m9-candidate-"):
            raise PublicCanaryRootError("schema_canary_root_invalid")
        if (ancestor / "source/state/trainlab.db").exists() or (
            ancestor / "state/trainlab.db"
        ).exists():
            raise PublicCanaryRootError("schema_canary_root_invalid")
    allowed = set(allowed_entries)
    if any(entry.name not in allowed for entry in root.iterdir()):
        raise PublicCanaryRootError("schema_canary_root_invalid")
    return root
