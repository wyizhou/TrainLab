#!/usr/bin/env python3
"""Build an owner-only database Candidate for M11 readable-email previews."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote


class CandidateBuildError(ValueError):
    """Stable M11 Candidate construction failure."""


def _load_context_module() -> Any:
    path = (
        Path(__file__).resolve().parents[2] / "training-coach/scripts/build_context.py"
    )
    spec = importlib.util.spec_from_file_location(
        "trainlab_m11_recent_health_context", path
    )
    if spec is None or spec.loader is None:
        raise CandidateBuildError("m11_recent_health_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_owner_file(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size <= 0
    ):
        raise CandidateBuildError("m11_parent_database_invalid")


def _atomic_owner_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise CandidateBuildError("m11_candidate_artifact_empty")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_candidate(
    parent_database: Path,
    candidate_root: Path,
    *,
    recent_health_report_date: date | None = None,
    parent_source_root: Path | None = None,
) -> dict[str, object]:
    """Copy the parent SQLite database with Online Backup and verify the copy."""

    _require_owner_file(parent_database)
    if candidate_root.exists() or candidate_root.is_symlink():
        raise CandidateBuildError("m11_candidate_root_exists")
    candidate_root.mkdir(mode=0o700)
    source_root = candidate_root / "source"
    state_root = source_root / "state"
    source_root.mkdir(mode=0o700)
    state_root.mkdir(mode=0o700)
    candidate_database = state_root / "trainlab.db"
    source_uri = (
        f"file:{quote(str(parent_database.resolve()), safe='/')}?mode=ro&immutable=1"
    )
    source = sqlite3.connect(source_uri, uri=True)
    target = sqlite3.connect(candidate_database)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    candidate_database.chmod(0o600)
    recent_health: dict[str, Any] | None = None
    if recent_health_report_date is not None:
        evidence_root = parent_source_root or parent_database.parent.parent
        context = _load_context_module()
        try:
            recent_health = context.record_recent_health_metrics(
                parent_database,
                evidence_root,
                candidate_database,
                recent_health_report_date,
            )
        except (OSError, ValueError) as exc:
            raise CandidateBuildError("m11_recent_health_snapshot_failed") from exc
    connection = sqlite3.connect(
        f"file:{quote(str(candidate_database.resolve()), safe='/')}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = int(
            connection.execute("PRAGMA foreign_key_check").fetchone() is not None
        )
        source_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM skill_outputs WHERE schema_name IN "
                "('daily_ai_result_v1','weekly_ai_result_v1')"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys != 0 or source_count < 8:
        raise CandidateBuildError("m11_candidate_database_invalid")
    receipt: dict[str, object] = {
        "schema_version": "m11_preview_candidate_receipt_v1",
        "status": "succeeded",
        "parent_database_sha256": _sha256_file(parent_database),
        "candidate_database_sha256": _sha256_file(candidate_database),
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "eligible_source_outputs": source_count,
        "copied_raw_files": 0,
        "copied_credentials": 0,
        "provider_calls": 0,
        "external_actions": 0,
    }
    if recent_health is not None:
        if recent_health_report_date is None:
            raise RuntimeError("m11_recent_health_date_missing")
        receipt["recent_health_snapshot"] = {
            "output_id": int(recent_health["output_id"]),
            "output_sha256": str(recent_health["output_sha256"]),
            "report_date": recent_health_report_date.isoformat(),
            "provider_calls": 0,
        }
    _atomic_owner_write(
        candidate_root / "build-receipt.json",
        (
            json.dumps(
                receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode(),
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-database", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--recent-health-report-date")
    parser.add_argument("--parent-source-root", type=Path)
    args = parser.parse_args()
    report_date = (
        date.fromisoformat(args.recent_health_report_date)
        if args.recent_health_report_date
        else None
    )
    receipt = build_candidate(
        args.parent_database,
        args.candidate_root,
        recent_health_report_date=report_date,
        parent_source_root=args.parent_source_root,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
