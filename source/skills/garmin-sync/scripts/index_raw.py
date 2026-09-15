#!/usr/bin/env python3
"""Index existing Garmin raw files without contacting Garmin."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_file,
    sha256_text,
    utc_now,
)

DATE_PREFIX = re.compile(r"^(\d{8})-(.+)$")
FORMATS = {"fit", "gpx", "tcx"}


def _data_date(name: str) -> str:
    match = DATE_PREFIX.match(name)
    if match is None:
        raise ValueError("raw_filename_date_missing")
    value = match.group(1)
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}").isoformat()


def _metadata(path: Path, raw_root: Path) -> dict[str, Any]:
    relative = path.relative_to(raw_root).as_posix()
    parts = Path(relative).parts
    if (
        len(parts) != 3
        or parts[0] != "garmin"
        or parts[1]
        not in {
            "health",
            "activities",
        }
    ):
        raise ValueError("raw_path_outside_allowed_buckets")
    if path.is_symlink() or not path.is_file():
        raise ValueError("raw_file_not_regular")
    if path.stat().st_mode & 0o777 != 0o600:
        raise ValueError("raw_file_mode_invalid")
    data_date = _data_date(path.name)
    is_weather = path.name.endswith(".weather.json")
    suffix = ".json" if is_weather else path.suffix
    file_format = suffix.lstrip(".")
    if file_format not in {"json", *FORMATS}:
        raise ValueError("raw_format_unsupported")
    if parts[1] == "health":
        resource_name = path.name[9:]
        if resource_name.endswith(".json"):
            resource_name = resource_name[:-5]
        resource_kind = resource_name.rsplit("-", 1)[0]
        data_class = "health"
        binding_state = "not_applicable"
    else:
        resource_kind = "activity_weather" if is_weather else f"activity_{file_format}"
        data_class = "activity"
        binding_state = "unresolved"
    return {
        "provider": "garmin",
        "data_class": data_class,
        "resource_kind": resource_kind,
        "logical_key": f"garmin:raw:{relative}",
        "data_date": data_date,
        "relative_path": relative,
        "file_format": file_format,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "activity_binding_state": binding_state,
    }


def index(source_root: Path, database: Path) -> dict[str, Any]:
    raw_root = source_root / "state/raw"
    paths = sorted(
        path
        for bucket in (raw_root / "garmin/health", raw_root / "garmin/activities")
        if bucket.is_dir()
        for path in bucket.iterdir()
        if path.name != ".gitkeep"
    )
    metadata = [_metadata(path, raw_root) for path in paths]
    manifest_sha = sha256_text(canonical_json(metadata))
    connection = connect(database)
    run_id: int | None = None
    try:
        run_id = begin_run(
            connection,
            run_key=f"garmin-sync:index-existing-raw:{manifest_sha}:attempt-1",
            workflow_key="index-existing-raw",
            dedupe_key=manifest_sha,
            skill_name="garmin-sync",
            operation="index_existing_raw",
            trigger_kind="recovery",
            input_manifest={"files": metadata, "manifest_sha256": manifest_sha},
        )
        indexed = 0
        for item in metadata:
            row = connection.execute(
                "SELECT byte_size,sha256 FROM raw_files WHERE relative_path=?",
                (item["relative_path"],),
            ).fetchone()
            if row:
                if int(row[0]) != item["byte_size"] or str(row[1]) != item["sha256"]:
                    raise ValueError("raw_path_collision")
                continue
            now = utc_now()
            connection.execute(
                """INSERT INTO raw_files
                (provider,data_class,resource_kind,logical_key,revision_no,
                 activity_binding_state,data_date,relative_path,file_format,byte_size,
                 sha256,registered_by_run_id,integrity_state,registered_at_utc,
                 last_verified_at_utc)
                VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["provider"],
                    item["data_class"],
                    item["resource_kind"],
                    item["logical_key"],
                    item["activity_binding_state"],
                    item["data_date"],
                    item["relative_path"],
                    item["file_format"],
                    item["byte_size"],
                    item["sha256"],
                    run_id,
                    "verified",
                    now,
                    now,
                ),
            )
            indexed += 1
        summary = {
            "schema_version": "sync_summary_v1",
            "status": "indexed",
            "file_count": len(metadata),
            "new_file_count": indexed,
            "manifest_sha256": manifest_sha,
            "provider_calls": 0,
        }
        require_valid_payload(
            {key: value for key, value in summary.items() if key != "new_file_count"},
            "sync_summary_v1",
        )
        append_output(
            connection,
            skill_run_id=run_id,
            output_kind="sync_summary",
            logical_key="garmin-sync:index-existing-raw",
            schema_name="raw_index_summary",
            schema_version="1",
            content_json={
                key: value for key, value in summary.items() if key != "new_file_count"
            },
            content_text=json.dumps(
                {
                    key: value
                    for key, value in summary.items()
                    if key != "new_file_count"
                },
                sort_keys=True,
            ),
            lineage=[],
        )
        finish_run(connection, run_id, status="succeeded")
        return summary
    except Exception as exc:
        if run_id is not None:
            finish_run(
                connection,
                run_id,
                status="blocked",
                error_code=str(exc),
            )
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = index(args.source_root, args.database)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
