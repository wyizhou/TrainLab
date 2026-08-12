"""Bounded published readiness and explicit deep Foundation verification."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Protocol


class ReadinessHost(Protocol):
    """Security-sensitive primitives retained by the Foundation owner."""

    def _paths(self, root: Path) -> dict[str, Path]: ...

    def _lstat_kind(self, path: Path, directory: bool) -> str | None: ...

    def _secure_read_file(self, path: Path) -> bytes: ...

    def _manifest_hash(self) -> str: ...

    def _manifest(self) -> dict[str, Any]: ...

    def _required_objects_and_permissions(
        self, paths: dict[str, Path]
    ) -> list[str]: ...

    def _connect(self, path: Path, readonly: bool = False) -> sqlite3.Connection: ...

    def _read_foundation_state(self, connection: sqlite3.Connection) -> sqlite3.Row: ...

    def _migration_receipt_valid(
        self, connection: sqlite3.Connection, manifest_hash: str
    ) -> bool: ...

    def _marker_error(
        self, paths: dict[str, Path], expected_hash: str
    ) -> str | None: ...


def read_published_status(
    host: ReadinessHost,
    root: Path,
    receipt: Any,
    *,
    supported_schema_version: int,
    canonical_utc: Callable[[Any], bool],
) -> None:
    """Read the bounded published summary without opening SQLite."""
    paths = host._paths(root)
    database_kind = host._lstat_kind(paths["db"], False)
    if database_kind is None:
        receipt.status = "incompatible"
        receipt.next_action = "explicit_migrate"
        return
    if database_kind != "ok":
        receipt.status = "incompatible"
        receipt.next_action = "operator_review"
        receipt.warnings.append(
            {
                "code": "foundation_filesystem_unsafe",
                "summary": "database object is unsafe",
            }
        )
        return
    if host._lstat_kind(paths["ready"], False) is None:
        receipt.status = "incompatible"
        receipt.next_action = "operator_review"
        receipt.warnings.append(
            {"code": "foundation_not_ready", "summary": "marker_missing"}
        )
        return
    try:
        marker = json.loads(host._secure_read_file(paths["ready"]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        missing = isinstance(exc, OSError) and str(exc) == "foundation_file_missing"
        receipt.status = "incompatible"
        receipt.next_action = "operator_review"
        receipt.warnings.append(
            {
                "code": "foundation_not_ready",
                "summary": (
                    "marker_missing" if missing else "marker_missing_or_invalid"
                ),
            }
        )
        return
    if (
        not isinstance(marker, dict)
        or set(marker)
        != {
            "schema_version",
            "manifest_sha256",
            "ready",
            "initialized_at_utc",
        }
        or type(marker.get("schema_version")) is not int
    ):
        receipt.status = "incompatible"
        receipt.next_action = "operator_review"
        receipt.warnings.append(
            {
                "code": "foundation_not_ready",
                "summary": "marker_shape_mismatch",
            }
        )
        return
    receipt.foundation_schema_version = marker["schema_version"]
    if receipt.foundation_schema_version > supported_schema_version:
        receipt.status = "incompatible"
        receipt.next_action = "operator_review"
        receipt.warnings.append(
            {
                "code": "foundation_not_ready",
                "summary": "marker_schema_version_mismatch",
            }
        )
        return
    if receipt.foundation_schema_version < supported_schema_version:
        receipt.status = "incompatible"
        receipt.next_action = "explicit_migrate"
        receipt.warnings.append(
            {
                "code": "foundation_schema_upgrade_required",
                "summary": "run explicit foundation migrate",
            }
        )
        return
    errors: list[str] = []
    if marker.get("ready") is not True:
        errors.append("marker_not_ready")
    if marker.get("manifest_sha256") != host._manifest_hash():
        errors.append("marker_manifest_mismatch")
    if not canonical_utc(marker.get("initialized_at_utc")):
        errors.append("marker_timestamp_mismatch")
    errors.extend(host._required_objects_and_permissions(paths))
    receipt.ready = not errors
    if errors:
        receipt.warnings.append({"code": "foundation_not_ready", "summary": errors[0]})
    receipt.status = "ready" if receipt.ready else "incompatible"
    receipt.next_action = "none" if receipt.ready else "operator_review"
    receipt.verified_count = 1


def read_full_verification(
    host: ReadinessHost,
    root: Path,
    receipt: Any,
    *,
    supported_schema_version: int,
    canonical_utc: Callable[[Any], bool],
    validate_manifest: Callable[[sqlite3.Connection, dict[str, Any]], list[str]],
    incompatible_error: type[Exception],
    corrupt_error: type[Exception],
) -> None:
    """Run the complete, explicit Foundation compatibility verification."""
    paths = host._paths(root)
    try:
        connection = host._connect(paths["db"], readonly=True)
    except sqlite3.DatabaseError as exc:
        raise corrupt_error("cannot_open_sqlite") from exc
    try:
        state = host._read_foundation_state(connection)
        receipt.foundation_schema_version = int(state["schema_version"])
        if receipt.foundation_schema_version > supported_schema_version:
            raise incompatible_error("higher_schema_version")
        if receipt.foundation_schema_version < supported_schema_version:
            receipt.status = "incompatible"
            receipt.next_action = "explicit_migrate"
            receipt.warnings.append(
                {
                    "code": "foundation_schema_upgrade_required",
                    "summary": "run explicit foundation migrate",
                }
            )
            return
        expected_hash = host._manifest_hash()
        errors: list[str] = []
        if state["state"] != "ready":
            errors.append("database_not_ready")
        if state["manifest_sha256"] != expected_hash:
            errors.append("database_manifest_mismatch")
        if state["implementation_version"] != "foundation-v3":
            errors.append("database_implementation_version_mismatch")
        if not canonical_utc(state["initialized_at_utc"]) or not canonical_utc(
            state["updated_at_utc"]
        ):
            errors.append("database_timestamp_mismatch")
        if not host._migration_receipt_valid(connection, expected_hash):
            errors.append("migration_receipt_mismatch")
        marker_error = host._marker_error(paths, expected_hash)
        if marker_error:
            errors.append(marker_error)
        errors.extend(host._required_objects_and_permissions(paths))
        errors.extend(validate_manifest(connection, host._manifest()))
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            errors.append("sqlite_integrity_mismatch")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            errors.append("sqlite_foreign_key_mismatch")
        receipt.ready = not errors
        if errors:
            receipt.warnings.append(
                {"code": "foundation_not_ready", "summary": errors[0]}
            )
        receipt.status = "ready" if receipt.ready else "incompatible"
        receipt.next_action = "none" if receipt.ready else "operator_review"
    except sqlite3.DatabaseError as exc:
        raise corrupt_error("sqlite_metadata_read_failed") from exc
    finally:
        connection.close()


def verify_foundation(
    host: ReadinessHost,
    root: Path,
    receipt: Any,
    *,
    supported_schema_version: int,
    verified_object_count: int,
    canonical_utc: Callable[[Any], bool],
    validate_manifest: Callable[[sqlite3.Connection, dict[str, Any]], list[str]],
    incompatible_error: type[Exception],
    corrupt_error: type[Exception],
) -> None:
    """Require the published gate before running the deep verification."""
    read_published_status(
        host,
        root,
        receipt,
        supported_schema_version=supported_schema_version,
        canonical_utc=canonical_utc,
    )
    if receipt.status != "ready":
        return
    read_full_verification(
        host,
        root,
        receipt,
        supported_schema_version=supported_schema_version,
        canonical_utc=canonical_utc,
        validate_manifest=validate_manifest,
        incompatible_error=incompatible_error,
        corrupt_error=corrupt_error,
    )
    if receipt.status != "ready":
        return
    receipt.status = "ready"
    receipt.next_action = "none"
    receipt.verified_count = verified_object_count
