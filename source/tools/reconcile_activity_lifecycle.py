#!/usr/bin/env python3
"""Audit and repair activity lifecycle states from offline inventory evidence.

The tool reads provider inventory JSON already archived in a Foundation store.
It never contacts Garmin and emits only aggregate, non-content evidence.  A
repair is explicit and is intended for a disposable candidate database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from src.garmin.lifecycle import (  # noqa: E402
    ActivityInventoryObservation,
    next_activity_state,
)


@dataclass(frozen=True)
class InventoryEvidence:
    revision_id: int
    observation_id: str
    mode: str
    start_local_date: date | None
    through_local_date: date
    observed_at_utc: str
    seen_ids: frozenset[str]
    entry_count: int
    payload_sha256: str
    absence_proven: bool = False

    @property
    def reason_codes(self) -> tuple[str, ...]:
        if self.absence_proven:
            return ("absence_proof_available",)
        return ("absence_proof_unavailable", "offline_inventory_only")

    def intersects(self, start: date, through: date) -> bool:
        return self.through_local_date >= start and (
            self.start_local_date is None or self.start_local_date <= through
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _raw_path(state_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("activity_inventory_raw_path_invalid")
    candidates = (state_root / relative, state_root / "raw" / relative)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise RuntimeError("activity_inventory_raw_missing")


def _date_value(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed.date()


def _window(key: str) -> tuple[str, date | None, date] | None:
    parts = key.split(":")
    try:
        if "full" in parts:
            index = parts.index("through") + 1
            return "full", None, date.fromisoformat(parts[index])
        if "repair" in parts:
            index = parts.index("repair") + 1
            return (
                "repair",
                date.fromisoformat(parts[index]),
                date.fromisoformat(parts[index + 1]),
            )
        if "incremental" in parts:
            index = parts.index("incremental") + 1
            return (
                "incremental",
                date.fromisoformat(parts[index]),
                date.fromisoformat(parts[index + 1]),
            )
        if "snapshot" in parts:
            index = parts.index("snapshot") + 1
            day = date.fromisoformat(parts[index])
            return "snapshot", day, day
    except (IndexError, ValueError):
        return None
    return None


def _entries(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("activities"), list):
        values = payload["activities"]
    else:
        raise RuntimeError("activity_inventory_payload_invalid")
    result: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            raise RuntimeError("activity_inventory_entry_invalid")
        identifier = value.get("activityId", value.get("id"))
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
            raise RuntimeError("activity_inventory_id_invalid")
        if not str(identifier).strip():
            raise RuntimeError("activity_inventory_id_invalid")
        result.append(value)
    return result


def _load_evidence(
    connection: sqlite3.Connection,
    state_root: Path,
    start: date,
    through: date,
) -> tuple[list[InventoryEvidence], int, int]:
    rows = connection.execute(
        """SELECT sr.id,sr.provider_object_id,sr.raw_object_id,sr.payload_hash,
                  sr.parsed_at_utc,ro.sha256,ro.relative_path,ro.fetched_at_utc
           FROM source_revisions sr JOIN raw_objects ro ON ro.id=sr.raw_object_id
           WHERE sr.provider='garmin' AND sr.resource_kind='activity_inventory'
             AND sr.parsed_at_utc IS NOT NULL
           ORDER BY ro.fetched_at_utc,sr.id"""
    ).fetchall()
    evidence: list[InventoryEvidence] = []
    parse_failures = 0
    hash_mismatches = 0
    for row in rows:
        parsed_window = _window(str(row[1]))
        if parsed_window is None:
            parse_failures += 1
            continue
        mode, window_start, window_end = parsed_window
        if window_end < start or (window_start is not None and window_start > through):
            continue
        path = _raw_path(state_root, str(row[6]))
        actual_sha = _sha256(path)
        if actual_sha != str(row[5]) or str(row[3]) != actual_sha:
            hash_mismatches += 1
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = _entries(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError):
            parse_failures += 1
            continue
        seen_ids = frozenset(
            str(entry.get("activityId", entry.get("id"))).strip() for entry in entries
        )
        evidence.append(
            InventoryEvidence(
                revision_id=int(row[0]),
                observation_id=str(row[1]),
                mode=mode,
                start_local_date=window_start,
                through_local_date=window_end,
                observed_at_utc=str(row[7]),
                seen_ids=seen_ids,
                entry_count=len(entries),
                payload_sha256=actual_sha,
            )
        )
    return evidence, parse_failures, hash_mismatches


def audit(
    database: Path,
    state_root: Path,
    start: date,
    through: date,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    if not database.is_file() or database.is_symlink():
        raise RuntimeError("activity_lifecycle_database_missing")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        evidence, parse_failures, hash_mismatches = _load_evidence(
            connection, state_root, start, through
        )
        reactivated = 0
        unresolved = 0
        observation_summaries = [
            {
                "revision_id": item.revision_id,
                "observation_id": item.observation_id,
                "mode": item.mode,
                "start_local_date": (
                    item.start_local_date.isoformat()
                    if item.start_local_date is not None
                    else None
                ),
                "through_local_date": item.through_local_date.isoformat(),
                "observed_at_utc": item.observed_at_utc,
                "entry_count": item.entry_count,
                "seen_activity_count": len(item.seen_ids),
                "absence_proven": item.absence_proven,
                "reason_codes": list(item.reason_codes),
                "payload_sha256": item.payload_sha256,
            }
            for item in evidence
        ]
        if apply:
            rows = connection.execute(
                """SELECT id,provider_activity_id,local_date,provider_state
                          ,provider_deleted_at_utc
                   FROM activities WHERE provider='garmin'
                     AND local_date>=? AND local_date<=?""",
                (start.isoformat(), through.isoformat()),
            ).fetchall()
            for row in rows:
                activity_id = str(row["provider_activity_id"])
                state = str(row["provider_state"])
                local_date = date.fromisoformat(str(row["local_date"]))
                for item in evidence:
                    state = next_activity_state(
                        state,
                        activity_id,
                        local_date,
                        ActivityInventoryObservation(
                            observation_id=item.observation_id,
                            mode=item.mode,
                            start_local_date=item.start_local_date,
                            through_local_date=item.through_local_date,
                            seen_ids=item.seen_ids,
                            complete=True,
                            absence_proven=item.absence_proven,
                            observed_at_utc=item.observed_at_utc,
                        ),
                        last_transition_at_utc=(
                            str(row["provider_deleted_at_utc"])
                            if row["provider_deleted_at_utc"]
                            else None
                        ),
                    )
                if state == row["provider_state"]:
                    if state in {"suspected_missing", "provider_deleted"}:
                        unresolved += 1
                    continue
                if state == "active":
                    connection.execute(
                        """UPDATE activities SET provider_state='active',
                                  first_missing_at_utc=NULL,last_missing_at_utc=NULL,
                                  provider_deleted_at_utc=NULL WHERE id=?""",
                        (row["id"],),
                    )
                    reactivated += 1
            connection.commit()
        else:
            unresolved = sum(
                1
                for row in connection.execute(
                    """SELECT provider_activity_id,provider_state FROM activities
                       WHERE provider='garmin' AND local_date>=? AND local_date<=?""",
                    (start.isoformat(), through.isoformat()),
                )
                if row[1] in {"suspected_missing", "provider_deleted"}
            )
        seen_activity_count = len(
            {activity_id for item in evidence for activity_id in item.seen_ids}
        )
        return {
            "schema_version": "1",
            "status": "applied" if apply else "audited",
            "start_local_date": start.isoformat(),
            "end_local_date": through.isoformat(),
            "observation_count": len(evidence),
            "absence_proven_count": sum(1 for item in evidence if item.absence_proven),
            "seen_activity_count": seen_activity_count,
            "reactivated_count": reactivated,
            "unresolved_count": unresolved,
            "parse_failure_count": parse_failures,
            "raw_hash_mismatch_count": hash_mismatches,
            "provider_calls": 0,
            "observations": observation_summaries,
        }
    finally:
        connection.close()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        os.chmod(path.parent, 0o700)
    else:
        info = path.parent.lstat()
        if (
            not path.parent.is_dir()
            or path.parent.is_symlink()
            or info.st_uid != os.getuid()
            or (info.st_mode & 0o777) != 0o700
        ):
            raise RuntimeError("activity_lifecycle_output_directory_unsafe")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--through", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = audit(
        args.database,
        args.state_root,
        date.fromisoformat(args.start),
        date.fromisoformat(args.through),
        apply=args.apply,
    )
    _write_json(args.output_json, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
