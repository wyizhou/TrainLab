"""Repository-relative path contracts that protect private state files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STATE_ROOT = Path("states")
ACTIVITIES_DIR = STATE_ROOT / "activities"
AI_CONFIG_PATH = STATE_ROOT / "ai.json"
GARMIN_CONFIG_PATH = STATE_ROOT / "verification" / "garmin.json"
DATA_DB_PATH = STATE_ROOT / "data.db"
SOURCE_ROOT = Path("source")
WEB_STATIC_DIR = SOURCE_ROOT / "skills" / "local-web" / "web"
TOOLS_README_PATH = SOURCE_ROOT / "tools" / "README.md"

PRIVATE_STATE_PREFIXES = (STATE_ROOT,)
PUBLIC_STATIC_ROOTS = (WEB_STATIC_DIR,)


@dataclass(frozen=True)
class PrivateConfigRef:
    relative_path: Path
    purpose: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.relative_path.as_posix(), "purpose": self.purpose}


def ai_config_reference() -> PrivateConfigRef:
    return PrivateConfigRef(
        relative_path=AI_CONFIG_PATH,
        purpose="OpenAI-compatible API settings; the file is private and must not be printed.",
    )


def garmin_config_reference() -> PrivateConfigRef:
    return PrivateConfigRef(
        relative_path=GARMIN_CONFIG_PATH,
        purpose="Garmin authentication adapter settings; the file is private.",
    )


def activity_fit_name(date_yyyymmdd: str | None, fit_sha256: str) -> str:
    date_part = "unknown" if date_yyyymmdd is None else date_yyyymmdd
    if date_part != "unknown" and (len(date_part) != 8 or not date_part.isascii() or not date_part.isdigit()):
        raise ValueError("date_yyyymmdd must be 8 ASCII digits or None")
    if len(fit_sha256) != 64 or any(char not in "0123456789abcdef" for char in fit_sha256):
        raise ValueError("fit_sha256 must be a lowercase 64-character SHA-256 hex digest")
    return f"{date_part}-{fit_sha256}.fit"


def _lexical_relative(path: Path) -> Path:
    root = Path.cwd().resolve()
    if path.is_absolute():
        try:
            relative = path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise ValueError("path must stay inside the repository instance") from exc
    else:
        relative = path
    normalized = Path(os.path.normpath(relative.as_posix()))
    if normalized.parts and normalized.parts[0] == "..":
        raise ValueError("path must not escape the repository instance")
    return normalized


def is_private_state_path(path: Path) -> bool:
    try:
        normalized = _lexical_relative(path)
    except ValueError:
        return False
    return normalized == STATE_ROOT or STATE_ROOT in normalized.parents


def is_allowed_static_path(path: Path) -> bool:
    try:
        normalized = _lexical_relative(path)
    except ValueError:
        return False
    return normalized == WEB_STATIC_DIR or WEB_STATIC_DIR in normalized.parents


def validate_static_mount(static_dir: Path) -> None:
    normalized = _lexical_relative(static_dir)
    if normalized != WEB_STATIC_DIR:
        raise ValueError("static mount must be exactly source/skills/local-web/web")

    root = Path.cwd().resolve()
    static_path = root / normalized
    state_path = (root / STATE_ROOT).resolve(strict=False)
    resolved_static = static_path.resolve(strict=False)
    if static_path.is_symlink():
        raise ValueError("static mount root must not be a symbolic link")
    if resolved_static == state_path or state_path in resolved_static.parents:
        raise ValueError("static mount must not point at states or private runtime data")
