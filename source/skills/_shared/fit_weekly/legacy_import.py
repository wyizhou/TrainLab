"""One-time migration from a verified archive, never a normal runtime dependency."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import history_archive, storage


def registered_fits(archive: Path) -> list[dict[str, Any]]:
    """Select registered post-2021 activity FITs; a broken binding is not skipped."""
    manifest = json.loads((archive / "manifest.json").read_text())
    files = {item["path"]: item for item in manifest["files"]}
    db = history_archive.immutable_database(archive / "recovery/trainlab.db")
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("""
        SELECT r.*,a.provider AS activity_provider,a.provider_activity_id,a.activity_date
        FROM raw_files r LEFT JOIN activity_inventory a ON r.activity_inventory_id=a.id
        WHERE r.file_format='fit' ORDER BY r.data_date,r.id
        """).fetchall()
    finally:
        db.close()
    result: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for row in rows:
        day = date.fromisoformat(row["data_date"])
        if day.isoformat() != row["data_date"]:
            raise ValueError("legacy_fit_date_invalid")
        if day < date(2022, 1, 1):
            continue
        ref = row["provider_activity_id"]
        if (
            row["provider"] != "garmin"
            or row["activity_provider"] != "garmin"
            or row["data_class"] != "activity"
            or row["activity_binding_state"] != "bound"
            or row["integrity_state"] != "verified"
            or row["activity_date"] != row["data_date"]
            or not isinstance(ref, str)
            or not re.fullmatch(r"[0-9]{1,32}", ref)
        ):
            raise ValueError("legacy_fit_binding_invalid")
        relative = row["relative_path"]
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or str(path) != relative
            or not path.parts
            or path.suffix.lower() != ".fit"
        ):
            raise ValueError("legacy_fit_path_invalid")
        # The old ledger resolves relative_path beneath state/raw.
        member = f"legacy-state/raw/{relative}"
        declared = files.get(member)
        sha = row["sha256"]
        storage.require_sha(sha)
        if (
            declared is None
            or declared["sha256"] != sha
            or declared["size"] != row["byte_size"]
        ):
            raise ValueError("legacy_fit_manifest_mismatch")
        source = archive / member
        storage.private_entry(source, nonempty=True)
        data = source.read_bytes()
        if storage.digest(data) != sha or len(data) != row["byte_size"]:
            raise ValueError("legacy_fit_bytes_invalid")
        storage.require_fit(data)
        if sha in seen:
            if seen[sha] != ref:
                raise ValueError("legacy_fit_binding_invalid")
            continue
        seen[sha] = ref
        result.append(
            {
                "activity_ref": ref,
                "sha256": sha,
                "byte_size": len(data),
                "source_member": member,
            }
        )
    return sorted(result, key=lambda item: (item["activity_ref"], item["sha256"]))


def import_registered(archive: Path, destination: Path) -> dict[str, Any]:
    archive = archive.resolve()
    destination = destination.absolute()
    if (
        destination.resolve() != destination
        or destination == archive
        or archive in destination.parents
        or destination in archive.parents
    ):
        raise ValueError("legacy_import_destination_invalid")
    history_archive.verify_archive(archive)
    before = history_archive.fingerprint(archive)
    rows = registered_fits(archive)
    members = [
        {key: row[key] for key in ("activity_ref", "sha256", "byte_size")}
        for row in rows
    ]
    receipt = {
        "schema_version": "legacy_fit_import_v1",
        "status": "complete",
        "start_date": "2022-01-01",
        "history_coverage": "not_established",
        "fit_count": len(members),
        "byte_size": sum(item["byte_size"] for item in members),
        "members": members,
        "provider_calls": 0,
        "external_actions": 0,
    }
    input_sha = storage.digest(storage.canonical({"members": members}).encode())
    storage.initialize(destination)
    with storage.open_store(destination) as db:
        for row in rows:
            storage.import_fit(
                db,
                destination,
                row["activity_ref"],
                archive / row["source_member"],
                row["sha256"],
            )
        storage.verify_fit_closure(db, destination)
        # The archive is a one-time input. Never persist its absolute location.
        if history_archive.fingerprint(archive) != before:
            raise ValueError("legacy_import_source_changed")
        storage.put_document(
            db, "sync_receipt", "legacy-fit-import", input_sha, receipt
        )
    return receipt
