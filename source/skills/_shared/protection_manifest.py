"""Deterministic byte-preservation manifest helper for synthetic migration tests.

The helper only walks explicit caller-provided roots. It never imports product state,
opens SQLite databases as databases, follows links, unpacks opaque carriers, or calls
external services.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

PRIVATE_FILE_NAMES = {
    ".env",
    "credentials.json",
    "email.json",
    "garmin_tokens.json",
    "gcp-oauth.keys.json",
    "gmail-api-token.json",
    "goal.md",
    "token.json",
}
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
SIDECAR_SUFFIXES = (".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")
OPAQUE_SUFFIXES = (".zip", ".tar", ".tgz", ".gz", ".bundle")
FIT_SUFFIX = ".fit"
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mode(mode: int) -> int:
    return stat.S_IMODE(mode)


def _entry_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "char_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    return "special"


def _meta(path: Path) -> dict[str, Any]:
    info = path.lstat()
    return {
        "type": _entry_type(info.st_mode),
        "mode": _mode(info.st_mode),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
        "nlink": info.st_nlink,
    }


def _stable_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        key: meta[key]
        for key in (
            "type",
            "mode",
            "size",
            "mtime_ns",
            "ctime_ns",
            "device",
            "inode",
        )
    }


def _is_private_candidate(relative: str) -> bool:
    parts = Path(relative).parts
    return any(part in PRIVATE_FILE_NAMES or part.startswith(".env") for part in parts)


def _is_git_material(relative: str) -> bool:
    return ".git" in Path(relative).parts or relative == ".git"


def _classify(relative: str, entry_type: str) -> str:
    path = Path(relative)
    name = path.name.lower()
    if _is_git_material(relative):
        return "git_recovery_material"
    if entry_type == "symlink":
        return "link_text"
    if entry_type not in {"file", "directory"}:
        return "special_lstat_only"
    if entry_type == "directory":
        return "directory"
    if name.endswith(FIT_SUFFIX):
        return "fit_original"
    if name.endswith(SIDECAR_SUFFIXES) or name.endswith(DB_SUFFIXES):
        return "database_sidecar_bytes"
    if name.endswith(OPAQUE_SUFFIXES):
        return "opaque_carrier_bytes"
    if _is_private_candidate(relative):
        return "private_candidate_bytes"
    return "public_synthetic_bytes"


def _db_group(relative: str) -> str | None:
    lower = relative.lower()
    for suffix in SIDECAR_SUFFIXES:
        if lower.endswith(suffix):
            return relative[: -len(suffix)]
    for suffix in DB_SUFFIXES:
        if lower.endswith(suffix):
            return relative[: -len(suffix)]
    return None


def _privacy(relative: str, classification: str) -> str:
    if _is_private_candidate(relative):
        return "private_candidate"
    if classification in {"git_recovery_material", "database_sidecar_bytes"}:
        return "recovery_private"
    return "public_synthetic"


def _ensure_private_dir(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise ValueError("protection_target_not_directory")
    path.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    if _mode(path.stat().st_mode) != PRIVATE_DIR_MODE:
        os.chmod(path, PRIVATE_DIR_MODE)


def _safe_relative(path: Path) -> str:
    relative = path.as_posix()
    if path.is_absolute() or ".." in path.parts or relative in {"", "."}:
        raise ValueError("protection_relative_path_invalid")
    return relative


def _conflict_name(relative: str, digest: str, attempt: int = 0) -> str:
    path = Path(relative)
    suffix = f".{digest[:12]}" if attempt == 0 else f".{digest[:12]}.{attempt}"
    if path.suffix:
        name = f"{path.stem}{suffix}{path.suffix}"
    else:
        name = f"{path.name}{suffix}"
    return (path.parent / name).as_posix() if path.parent != Path(".") else name


def _target_for_bytes(payload_root: Path, relative: str, data: bytes) -> tuple[Path, str]:
    relative = _safe_relative(Path(relative))
    digest = sha256_bytes(data)
    candidate_relative = relative
    attempt = 0
    while True:
        candidate = payload_root / candidate_relative
        if not candidate.exists() and not candidate.is_symlink():
            return candidate, "new_copy"
        if candidate.is_file() and not candidate.is_symlink():
            if sha256_bytes(candidate.read_bytes()) == digest:
                return candidate, "already_present_same_sha"
        candidate_relative = _conflict_name(relative, digest, attempt)
        attempt += 1


def _write_private_bytes(path: Path, data: bytes) -> None:
    _ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    data = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    if path.exists():
        path.unlink()
    _write_private_bytes(path, data)


def _link_lexical_owner(
    source_path: Path, target_text: str, authorized_roots: Iterable[Path]
) -> str:
    target_path = Path(target_text)
    if not target_path.is_absolute():
        target_path = source_path.parent / target_path
    lexical = Path(os.path.normpath(os.fspath(target_path)))
    for root in authorized_roots:
        try:
            lexical.relative_to(Path(os.path.normpath(os.fspath(root))))
        except ValueError:
            continue
        return "inside_authorized_root"
    return "outside_authorized_root"


def _entry_base(
    *,
    source: Path,
    source_root: Path,
    source_index: int,
    relative: str,
    before: dict[str, Any],
    after: dict[str, Any] | None,
    preservation_time_label: str,
) -> dict[str, Any]:
    entry_type = before["type"]
    classification = _classify(relative, entry_type)
    base: dict[str, Any] = {
        "source": str(source),
        "source_root": str(source_root),
        "source_root_index": source_index,
        "relative_path": relative,
        "type": entry_type,
        "classification": classification,
        "privacy_classification": _privacy(relative, classification),
        "mode": before["mode"],
        "size": before["size"],
        "sha256": None,
        "source_meta_before": before,
        "source_meta_after": after,
        "closed": after is not None and _stable_meta(before) == _stable_meta(after),
    }
    if classification == "fit_original":
        base["activity_time"] = {
            "status": "unknown",
            "label": f"activity_time_unknown_preserved_at_{preservation_time_label}",
            "source": "preservation_label_not_filesystem_mtime",
        }
        base["business_import_status"] = "not_evaluated_by_preservation"
        base["fit_parse_status"] = "not_attempted_preservation_only"
    if classification == "opaque_carrier_bytes":
        base["opaque_unpack_status"] = "not_attempted_preservation_only"
    if classification == "git_recovery_material":
        base["git_recovery_material"] = True
    group = _db_group(relative)
    if group:
        base["sidecar_group"] = group
    return base


def _copy_regular_file(
    *,
    source: Path,
    source_root: Path,
    source_index: int,
    relative: str,
    payload_root: Path,
    before: dict[str, Any],
    preservation_time_label: str,
    before_read_hook: Callable[[Path], None] | None,
) -> dict[str, Any]:
    if before_read_hook is not None:
        before_read_hook(source)
    data = source.read_bytes()
    after = _meta(source)
    entry = _entry_base(
        source=source,
        source_root=source_root,
        source_index=source_index,
        relative=relative,
        before=before,
        after=after,
        preservation_time_label=preservation_time_label,
    )
    if not entry["closed"]:
        entry["skip_reason"] = "source_changed_before_copy_closed"
        return entry

    digest = sha256_bytes(data)
    entry["sha256"] = digest
    if not _is_private_candidate(relative) and entry["classification"] in {
        "opaque_carrier_bytes",
        "database_sidecar_bytes",
    }:
        entry["header_hex"] = data[:16].hex()
    target, action = _target_for_bytes(payload_root, relative, data)
    if action == "new_copy":
        _write_private_bytes(target, data)
    target_meta = _meta(target)
    entry.update(
        {
            "target": str(target),
            "target_relative_path": target.relative_to(payload_root).as_posix(),
            "target_mode": target_meta["mode"],
            "target_size": target_meta["size"],
            "target_inode": target_meta["inode"],
            "target_action": action,
        }
    )
    return entry


def _preserve_symlink(
    *,
    source: Path,
    source_root: Path,
    source_index: int,
    relative: str,
    payload_root: Path,
    before: dict[str, Any],
    authorized_roots: tuple[Path, ...],
    preservation_time_label: str,
) -> dict[str, Any]:
    target_text = os.readlink(source)
    after = _meta(source)
    data = target_text.encode("utf-8")
    link_relative = f"{relative}.readlink"
    target, action = _target_for_bytes(payload_root, link_relative, data)
    if action == "new_copy":
        _write_private_bytes(target, data)
    entry = _entry_base(
        source=source,
        source_root=source_root,
        source_index=source_index,
        relative=relative,
        before=before,
        after=after,
        preservation_time_label=preservation_time_label,
    )
    entry.update(
        {
            "sha256": sha256_bytes(data),
            "readlink_text": target_text,
            "link_lexical_owner": _link_lexical_owner(
                source, target_text, authorized_roots
            ),
            "link_followed": False,
            "target": str(target),
            "target_relative_path": target.relative_to(payload_root).as_posix(),
            "target_mode": _meta(target)["mode"],
            "target_action": action,
        }
    )
    return entry


def _preserve_directory(
    *,
    source: Path,
    source_root: Path,
    source_index: int,
    relative: str,
    payload_root: Path,
    before: dict[str, Any],
    preservation_time_label: str,
) -> dict[str, Any]:
    target = payload_root / _safe_relative(Path(relative))
    _ensure_private_dir(target)
    after = _meta(source)
    entry = _entry_base(
        source=source,
        source_root=source_root,
        source_index=source_index,
        relative=relative,
        before=before,
        after=after,
        preservation_time_label=preservation_time_label,
    )
    entry.update(
        {
            "target": str(target),
            "target_relative_path": target.relative_to(payload_root).as_posix(),
            "target_mode": _meta(target)["mode"],
            "source_observed_empty_dir": not any(source.iterdir()),
        }
    )
    return entry


def _preserve_special(
    *,
    source: Path,
    source_root: Path,
    source_index: int,
    relative: str,
    before: dict[str, Any],
    preservation_time_label: str,
) -> dict[str, Any]:
    after = _meta(source)
    entry = _entry_base(
        source=source,
        source_root=source_root,
        source_index=source_index,
        relative=relative,
        before=before,
        after=after,
        preservation_time_label=preservation_time_label,
    )
    entry.update({"skip_reason": "special_lstat_only", "opened": False})
    return entry


def protect_sources(
    sources: Iterable[Path],
    destination: Path,
    *,
    preservation_time_label: str = "unknown_preservation_time",
    before_read_hook: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Copy or record explicit source roots into a private manifest target.

    All inputs are caller supplied; this function does not discover repository data.
    Re-running with the same destination reuses existing same-SHA payload files and
    creates stable hash-suffixed names only when a same lexical target has different
    bytes.
    """

    source_roots = tuple(Path(source) for source in sources)
    if not source_roots:
        raise ValueError("protection_sources_required")
    destination = Path(destination)
    payload_root = destination / "payload"
    _ensure_private_dir(destination)
    _ensure_private_dir(payload_root)
    authorized_roots = tuple(Path(os.path.normpath(os.fspath(root))) for root in source_roots)

    entries: list[dict[str, Any]] = []
    db_groups: dict[str, dict[str, Any]] = {}
    for source_index, source_root in enumerate(source_roots):
        for source in sorted(source_root.rglob("*")):
            relative = source.relative_to(source_root).as_posix()
            before = _meta(source)
            entry_type = before["type"]
            if entry_type == "file":
                entry = _copy_regular_file(
                    source=source,
                    source_root=source_root,
                    source_index=source_index,
                    relative=relative,
                    payload_root=payload_root,
                    before=before,
                    preservation_time_label=preservation_time_label,
                    before_read_hook=before_read_hook,
                )
            elif entry_type == "symlink":
                entry = _preserve_symlink(
                    source=source,
                    source_root=source_root,
                    source_index=source_index,
                    relative=relative,
                    payload_root=payload_root,
                    before=before,
                    authorized_roots=authorized_roots,
                    preservation_time_label=preservation_time_label,
                )
            elif entry_type == "directory":
                entry = _preserve_directory(
                    source=source,
                    source_root=source_root,
                    source_index=source_index,
                    relative=relative,
                    payload_root=payload_root,
                    before=before,
                    preservation_time_label=preservation_time_label,
                )
            else:
                entry = _preserve_special(
                    source=source,
                    source_root=source_root,
                    source_index=source_index,
                    relative=relative,
                    before=before,
                    preservation_time_label=preservation_time_label,
                )
            entries.append(entry)
            group_id = entry.get("sidecar_group")
            if isinstance(group_id, str):
                group = db_groups.setdefault(
                    group_id,
                    {"entries": [], "consistency": "byte_preserved_no_sqlite_open"},
                )
                group["entries"].append(entry["relative_path"])
                relative_lower = entry["relative_path"].lower()
                is_nonzero_wal = relative_lower.endswith(
                    ("-wal", ".db-wal", ".sqlite-wal")
                ) and bool(entry["size"])
                if is_nonzero_wal:
                    group["consistency"] = "consistency_unknown_nonzero_wal"

    empty_dirs = [
        entry["relative_path"]
        for entry in entries
        if entry["type"] == "directory" and entry.get("source_observed_empty_dir")
    ]
    manifest = {
        "schema_version": "protection_manifest_v1",
        "preservation_time_label": preservation_time_label,
        "provider_calls": 0,
        "external_actions": 0,
        "sqlite_connections": 0,
        "sources": [str(source) for source in source_roots],
        "entries": entries,
        "db_groups": db_groups,
        "empty_directories": empty_dirs,
        "final_audit": {
            "destination": str(destination),
            "destination_mode": _mode(destination.stat().st_mode),
            "payload_mode": _mode(payload_root.stat().st_mode),
            "file_mode_required": PRIVATE_FILE_MODE,
            "directory_mode_required": PRIVATE_DIR_MODE,
        },
    }
    _write_manifest(destination / "manifest.json", manifest)
    return manifest


def validate_manifest(destination: Path) -> dict[str, Any]:
    """Machine-check a manifest previously written by :func:`protect_sources`."""

    destination = Path(destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "protection_manifest_v1":
        raise ValueError("protection_manifest_schema_invalid")
    for directory in (destination, destination / "payload"):
        if not directory.is_dir() or _mode(directory.stat().st_mode) != PRIVATE_DIR_MODE:
            raise ValueError("protection_manifest_directory_permissions_invalid")
    if _mode(manifest_path.stat().st_mode) != PRIVATE_FILE_MODE:
        raise ValueError("protection_manifest_file_permissions_invalid")
    for entry in manifest["entries"]:
        required = {
            "source",
            "relative_path",
            "type",
            "classification",
            "privacy_classification",
            "mode",
            "size",
            "sha256",
            "source_meta_before",
            "source_meta_after",
        }
        if not required.issubset(entry):
            raise ValueError("protection_manifest_entry_invalid")
        target = entry.get("target")
        if target is None:
            if "skip_reason" not in entry:
                raise ValueError("protection_manifest_entry_target_missing")
            continue
        target_path = Path(target)
        if entry["type"] == "directory":
            if not target_path.is_dir() or _mode(target_path.stat().st_mode) != PRIVATE_DIR_MODE:
                raise ValueError("protection_manifest_target_directory_invalid")
            continue
        if not target_path.is_file() or target_path.is_symlink():
            raise ValueError("protection_manifest_target_file_invalid")
        target_bytes = target_path.read_bytes()
        if _mode(target_path.stat().st_mode) != PRIVATE_FILE_MODE:
            raise ValueError("protection_manifest_target_file_permissions_invalid")
        if entry["sha256"] != sha256_bytes(target_bytes):
            raise ValueError("protection_manifest_target_sha_invalid")
        if entry.get("target_size") is not None and entry["target_size"] != len(target_bytes):
            raise ValueError("protection_manifest_target_size_invalid")
    return {"status": "verified", "entry_count": len(manifest["entries"])}
