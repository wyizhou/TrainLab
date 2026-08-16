#!/usr/bin/env python3
"""Create bounded raw-file evidence; never print raw payloads or FIT samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import record_skill_result  # noqa: E402


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files_for(root: Path, day: date) -> list[Path]:
    if not root.is_dir():
        return []
    prefix = day.strftime("%Y%m%d") + "-"
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.name.startswith(prefix)
    )


def json_shape(value: Any, *, depth: int = 0) -> dict[str, Any]:
    """Return structure only; never expose scalar raw values."""
    if depth >= 2:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)[:40]
        return {
            "type": "object",
            "key_count": len(value),
            "keys": keys,
            "truncated_keys": len(value) > len(keys),
        }
    if isinstance(value, list):
        item_types = sorted({type(item).__name__ for item in value[:40]})
        return {
            "type": "array",
            "length": len(value),
            "item_types": item_types,
            "truncated_items": len(value) > 40,
        }
    return {"type": type(value).__name__}


def parse_evidence(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return {"parser": "json", "shape": json_shape(value)}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"parser": "json", "error_code": "raw_json_invalid"}
    if suffix in {".gpx", ".tcx"}:
        try:
            root = ET.parse(path).getroot()
            return {
                "parser": suffix[1:],
                "root_tag": root.tag.rsplit("}", 1)[-1],
                "element_count": sum(1 for _ in root.iter()),
            }
        except (OSError, ET.ParseError):
            return {"parser": suffix[1:], "error_code": "raw_xml_invalid"}
    if suffix == ".fit":
        try:
            import fitdecode

            message_count = 0
            message_types: set[str] = set()
            with fitdecode.FitReader(path) as reader:
                for frame in reader:
                    message_count += 1
                    if message_count > 100_000:
                        return {
                            "parser": "fitdecode",
                            "message_count": message_count,
                            "truncated": True,
                        }
                    name = getattr(frame, "name", None)
                    if name:
                        message_types.add(str(name))
            return {
                "parser": "fitdecode",
                "message_count": message_count,
                "message_types": sorted(message_types)[:40],
            }
        except (OSError, ValueError, RuntimeError, ImportError):
            return {"parser": "fitdecode", "error_code": "raw_fit_unavailable"}
    return {"parser": "none", "error_code": "raw_format_unsupported"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    if args.days < 1 or args.days > 14:
        raise SystemExit("days must be between 1 and 14")
    target = date.fromisoformat(args.date)
    health_root = args.source_root / "state/raw/garmin/health"
    activity_root = args.source_root / "state/raw/garmin/activities"
    records: list[dict[str, object]] = []
    for offset in range(args.days):
        day = target - timedelta(days=offset)
        for path in files_for(health_root, day) + files_for(activity_root, day):
            records.append(
                {
                    "relative_path": str(path.relative_to(args.source_root)),
                    "data_date": day.isoformat(),
                    "format": path.suffix.lstrip(".") or "unknown",
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                    "evidence": parse_evidence(path),
                }
            )
    payload = {
        "schema_version": "1",
        "status": "ready",
        "from_date": (target - timedelta(days=args.days - 1)).isoformat(),
        "through_date": target.isoformat(),
        "file_count": len(records),
        "files": records,
        "raw_values_included": False,
    }
    if args.database:
        record_skill_result(
            args.database,
            skill_name="training-coach",
            operation="weekly_coach" if args.days > 1 else "daily_coach",
            output_kind="bounded_evidence",
            logical_key=f"training-coach:raw:{args.date}:{args.days}",
            payload=payload,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
