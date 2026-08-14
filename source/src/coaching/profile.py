"""Explicitly confirmed, owner-only coaching profile workflow.

The model may propose a profile through ``propose_profile``.  Applying it is a
separate command so the coordinator can show the candidate and obtain an
explicit user confirmation before calling ``apply_profile_candidate``.
"""

from __future__ import annotations

import json
import os
import re
import stat
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ..resources import resource_path
from ..util import atomic_write_json, instance_root

_PROFILE_SCHEMA = "harness/schemas/coaching_profile_contract_v1.schema.json"
_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "weekly_capacity_km",
        "weekly_frequency",
        "long_run_max_km",
        "hard_load_max",
        "hard_load_min_gap_days",
        "available_weekdays",
        "climbing_schedule",
        "race_goal",
        "progression_rule",
    }
)
_RACE_CONFIG_FIELDS = (
    "active_race_goal",
    "marathon_target_finish_time",
    "half_marathon_target_finish_time",
    "marathon_race_date",
    "half_marathon_race_date",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "status": "confirmed",
    "weekly_capacity_km": None,
    "weekly_frequency": None,
    "long_run_max_km": None,
    "hard_load_max": 3,
    "hard_load_min_gap_days": 2,
    "available_weekdays": [1, 3, 5, 7],
    "climbing_schedule": [
        {"weekday": 2, "load_level": "moderate", "duration_minutes": None},
        {"weekday": 6, "load_level": "hard", "duration_minutes": None},
    ],
    "race_goal": None,
    "progression_rule": "conservative",
}


class CoachingProfileError(ValueError):
    """A safe, content-free coaching profile failure."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_mode(path: Path, mode: int, *, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise CoachingProfileError(f"coaching_profile_{label}_missing") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CoachingProfileError(f"coaching_profile_{label}_unsafe")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
        raise CoachingProfileError(f"coaching_profile_{label}_permissions")


def _private_tree(root: Path) -> Path:
    tree = root / "state" / "coaching-profile"
    try:
        tree.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(tree, 0o700)
        for name in ("candidates", "backups"):
            child = tree / name
            child.mkdir(mode=0o700, exist_ok=True)
            os.chmod(child, 0o700)
    except OSError as error:
        raise CoachingProfileError("coaching_profile_storage_unavailable") from error
    return tree


def _config_path(root: Path) -> Path:
    current = root / "config" / "trainlab.json"
    legacy = root / "config" / "src.json"
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    raise CoachingProfileError("coaching_profile_config_missing")


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        _ensure_mode(path, 0o600, label=label)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CoachingProfileError(f"coaching_profile_{label}_invalid") from error
    if not isinstance(payload, dict):
        raise CoachingProfileError(f"coaching_profile_{label}_invalid")
    return payload


def _schema() -> dict[str, Any]:
    try:
        return json.loads(resource_path(_PROFILE_SCHEMA).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CoachingProfileError("coaching_profile_schema_unavailable") from error


def _validate_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoachingProfileError("coaching_profile_invalid")
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise CoachingProfileError(f"coaching_profile_invalid:{location}")
    return deepcopy(value)


def _validate_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise CoachingProfileError(f"coaching_profile_{label}_invalid")
    return value


def _load_config(root: Path) -> tuple[Path, dict[str, Any], bytes]:
    path = _config_path(root)
    raw = path.read_bytes()
    payload = _read_object(path, label="config")
    if payload.get("schema_version") not in {1, 2}:
        raise CoachingProfileError("coaching_profile_config_schema_invalid")
    return path, payload, raw


def _profile_from_config(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("coaching_profile_contract")
    if value is None:
        return deepcopy(DEFAULT_PROFILE)
    return _validate_profile(value)


def current_profile(root: Path | None = None) -> dict[str, Any]:
    """Return only the current profile, never the surrounding private config."""

    resolved = instance_root(root) if root is None else root.resolve()
    _, payload, _ = _load_config(resolved)
    return _profile_from_config(payload)


def _candidate_storage(root: Path, candidate_id: str) -> Path:
    candidate_id = _validate_id(candidate_id, label="candidate_id")
    return _private_tree(root) / "candidates" / f"{candidate_id}.json"


def _input_profile(input_path: Path) -> dict[str, Any]:
    try:
        if input_path.is_symlink() or not input_path.is_file():
            raise OSError
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CoachingProfileError("coaching_profile_input_invalid") from error
    if not isinstance(payload, dict):
        raise CoachingProfileError("coaching_profile_input_invalid")
    if set(payload) == {"profile"}:
        payload = payload["profile"]
    if not isinstance(payload, dict) or not set(payload).issubset(_PROFILE_FIELDS):
        raise CoachingProfileError("coaching_profile_input_fields_invalid")
    return deepcopy(payload)


def propose_profile(
    root: Path | None, *, request_id: str, input_path: Path
) -> dict[str, Any]:
    """Persist a validated candidate without touching formal configuration."""

    resolved = instance_root(root) if root is None else root.resolve()
    request_id = _validate_id(request_id, label="request_id")
    _, config, _ = _load_config(resolved)
    current = _profile_from_config(config)
    requested = _input_profile(input_path)
    candidate = deepcopy(current)
    candidate.update(requested)
    candidate["status"] = "confirmed"
    candidate = _validate_profile(candidate)
    profile_hash = sha256(
        json.dumps(
            candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    candidate_id = f"candidate-{request_id}-{profile_hash[:12]}"
    changes = [
        {
            "field": field,
            "before": current.get(field),
            "after": candidate.get(field),
            "changed": current.get(field) != candidate.get(field),
        }
        for field in sorted(_PROFILE_FIELDS)
        if current.get(field) != candidate.get(field)
    ]
    result = {
        "schema_version": "1",
        "candidate_id": candidate_id,
        "request_id": request_id,
        "created_at_utc": _utc_now(),
        "profile_sha256": profile_hash,
        "profile": candidate,
        "impact": {
            "changed_fields": changes,
            "formal_config_modified": False,
            "user_confirmation_required": True,
            "race_fields_cleared_on_apply": list(_RACE_CONFIG_FIELDS),
        },
    }
    path = _candidate_storage(resolved, candidate_id)
    atomic_write_json(path, result)
    os.chmod(path, 0o600)
    return result


def _append_audit(path: Path, record: dict[str, Any]) -> None:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise CoachingProfileError("coaching_profile_audit_write_failed") from error


def apply_profile_candidate(root: Path | None, *, candidate_id: str) -> dict[str, Any]:
    """Atomically apply one shown candidate after external user confirmation."""

    resolved = instance_root(root) if root is None else root.resolve()
    candidate_path = _candidate_storage(resolved, candidate_id)
    candidate = _read_object(candidate_path, label="candidate")
    if candidate.get("candidate_id") != candidate_id:
        raise CoachingProfileError("coaching_profile_candidate_id_mismatch")
    profile = _validate_profile(candidate.get("profile"))
    profile_hash = sha256(
        json.dumps(
            profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if candidate.get("profile_sha256") != profile_hash or not candidate_id.endswith(
        f"-{profile_hash[:12]}"
    ):
        raise CoachingProfileError("coaching_profile_candidate_tampered")
    config_path, config, original = _load_config(resolved)
    _ensure_mode(config_path, 0o600, label="config")
    updated = deepcopy(config)
    updated["coaching_profile_contract"] = profile
    updated["available_training_weekdays"] = ",".join(
        str(value) for value in profile["available_weekdays"]
    )
    for key in _RACE_CONFIG_FIELDS:
        updated[key] = None
    _validate_profile(updated["coaching_profile_contract"])

    tree = _private_tree(resolved)
    backup_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    original_hash = sha256(original).hexdigest()
    backup_path = tree / "backups" / f"{backup_id}-{original_hash[:12]}.json"
    backup_path.write_bytes(original)
    os.chmod(backup_path, 0o600)
    if backup_path.read_bytes() != original:
        raise CoachingProfileError("coaching_profile_backup_mismatch")

    atomic_write_json(config_path, updated)
    os.chmod(config_path, 0o600)
    updated_hash = sha256(config_path.read_bytes()).hexdigest()
    _append_audit(
        tree / "audit.jsonl",
        {
            "schema_version": "1",
            "event": "apply",
            "candidate_id": candidate_id,
            "applied_at_utc": _utc_now(),
            "backup_relative_path": backup_path.relative_to(tree).as_posix(),
            "previous_config_sha256": original_hash,
            "new_config_sha256": updated_hash,
            "changed_fields": candidate.get("impact", {}).get("changed_fields", []),
        },
    )
    return {
        "schema_version": "1",
        "status": "applied",
        "candidate_id": candidate_id,
        "profile": profile,
        "backup_relative_path": backup_path.relative_to(tree).as_posix(),
        "config_sha256": updated_hash,
        "formal_config_modified": True,
    }
