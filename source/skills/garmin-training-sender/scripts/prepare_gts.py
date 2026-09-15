#!/usr/bin/env python3
"""Prepare a no-network GTS action plan from a validated course JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    canonical_json,
    connect,
    record_skill_result,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("course_json", type=Path)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.course_json.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else None
    errors: list[str] = []
    actions: list[dict[str, object]] = []
    source_output_id: int | None = None
    source_output_sha256: str | None = None
    if args.database:
        connection = connect(args.database, read_only=True, immutable=True)
        try:
            row = connection.execute(
                "SELECT id,content_sha256 FROM skill_outputs "
                "WHERE output_kind='training_plan' AND content_json=? "
                "ORDER BY id DESC LIMIT 1",
                (canonical_json(payload),),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            errors.append("garmin_source_unbound")
        else:
            source_output_id = int(row[0])
            source_output_sha256 = str(row[1])
    try:
        require_valid_payload(payload, "training_plan_v1")
    except ValueError:
        errors.append("garmin_contract_invalid")
    if not isinstance(items, list) or not items:
        errors.append("garmin_contract_invalid")
    else:
        for item in items:
            if not isinstance(item, dict):
                errors.append("garmin_contract_invalid")
                continue
            if (
                item.get("activity_kind") != "running"
                or item.get("garmin_mapping_status") != "candidate"
            ):
                continue
            name = str(item.get("name", ""))
            if not name.endswith("-GTS"):
                errors.append("garmin_contract_invalid")
                continue
            key = hashlib.sha256(
                canonical_json(
                    {
                        "date": item.get("date"),
                        "name": name,
                        "item": item,
                    }
                ).encode("utf-8")
            ).hexdigest()
            actions.append(
                {
                    "date": item.get("date"),
                    "name": name,
                    "idempotency_key": key,
                    "network": False,
                }
            )
    result = {
        "status": "prepared" if not errors else "blocked",
        "errors": sorted(set(errors)),
        "actions": actions,
        "source_output_id": source_output_id,
        "source_output_sha256": source_output_sha256,
        "provider_calls": 0,
    }
    content_marker = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    if args.database:
        lineage = (
            [
                {
                    "output_id": source_output_id,
                    "output_sha256": source_output_sha256,
                }
            ]
            if source_output_id is not None and source_output_sha256 is not None
            else []
        )
        record_skill_result(
            args.database,
            skill_name="garmin-training-sender",
            operation="apply_weekly_plan",
            output_kind="garmin_workout_contract",
            logical_key=f"garmin-training-sender:prepare:{content_marker}",
            payload=result,
            status="succeeded" if not errors else "blocked",
            error_code=errors[0] if errors else None,
            lineage=lineage,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
