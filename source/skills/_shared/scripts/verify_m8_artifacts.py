#!/usr/bin/env python3
"""Verify an owner-only M8 output tree against an explicit manifest."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any


def _relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("artifact_path_invalid")
    return relative.as_posix()


def _manifest_entries(manifest_path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("artifact_manifest_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "artifact_manifest_v1"
    ):
        raise ValueError("artifact_manifest_invalid")
    raw_entries = payload.get("files")
    if not isinstance(raw_entries, list):
        raise ValueError("artifact_manifest_invalid")
    entries: dict[str, dict[str, Any]] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise ValueError("artifact_manifest_invalid")
        path = Path(raw["path"])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("artifact_manifest_path_invalid")
        normalized = path.as_posix()
        if normalized in entries:
            raise ValueError("artifact_manifest_duplicate_path")
        entries[normalized] = {
            "allow_empty": bool(raw.get("allow_empty", False)),
            "json": bool(raw.get("json", False)),
        }
    return entries


def verify_artifacts(root: Path, manifest_path: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("artifact_root_invalid")
    root_stat = root.stat()
    if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o777 != 0o700:
        raise ValueError("artifact_root_permissions")
    entries = _manifest_entries(manifest_path)
    paths = set(entries)
    parent_dirs = {
        parent.as_posix()
        for path in paths
        for parent in Path(path).parents
        if parent != Path(".")
    }
    seen_inodes: set[tuple[int, int]] = set()
    observed: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = _relative(path, root)
        observed.add(relative)
        metadata = path.lstat()
        mode = metadata.st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"artifact_entry_type_invalid:{relative}")
        if metadata.st_uid != os.getuid():
            raise ValueError(f"artifact_owner_invalid:{relative}")
        if stat.S_ISDIR(mode):
            if mode & 0o777 != 0o700:
                raise ValueError(f"artifact_directory_permissions:{relative}")
            if relative not in parent_dirs and relative not in paths:
                raise ValueError(f"artifact_undeclared_directory:{relative}")
            continue
        if mode & 0o777 != 0o600:
            raise ValueError(f"artifact_file_permissions:{relative}")
        if relative not in paths:
            raise ValueError(f"artifact_undeclared_file:{relative}")
        if metadata.st_nlink != 1:
            raise ValueError(f"artifact_hardlink:{relative}")
        if metadata.st_size == 0 and not entries[relative]["allow_empty"]:
            raise ValueError(f"artifact_empty_file:{relative}")
        if entries[relative]["json"]:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"artifact_json_invalid:{relative}") from exc
        inode = (int(metadata.st_dev), int(metadata.st_ino))
        if inode in seen_inodes:
            raise ValueError(f"artifact_hardlink:{relative}")
        seen_inodes.add(inode)
    missing = sorted(paths - observed)
    if missing:
        raise ValueError(f"artifact_missing:{','.join(missing)}")
    return {
        "schema_version": "artifact_verification_v1",
        "root": str(root),
        "file_count": len(paths),
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_artifacts(args.root, args.manifest)
    except ValueError as exc:
        print(
            json.dumps({"verified": False, "error_code": str(exc)}, ensure_ascii=False)
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
