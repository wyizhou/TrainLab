#!/usr/bin/env python3
"""Read a bounded activity segment under the daily drill-down budget."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from activity_evidence import build_activity_evidence  # noqa: E402

from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    record_skill_result,
    sha256_text,
    workflow_lock,
)

MAX_CALLS = 5
MAX_SINGLE_SECONDS = 10 * 60
MAX_TOTAL_SECONDS = 30 * 60


def _expected_workflow_key(database: Path, inventory_id: int) -> str:
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT activity_date FROM activity_inventory WHERE id=?",
            (inventory_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("activity_segment_inventory_unknown")
    try:
        report_date = date.fromisoformat(str(row[0])) + timedelta(days=1)
    except ValueError as exc:
        raise ValueError("activity_segment_inventory_date_invalid") from exc
    return f"daily:{report_date.isoformat()}"


def _budget(database: Path, workflow_key: str) -> tuple[int, int]:
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT input_manifest_json FROM skill_runs WHERE workflow_key=? "
            "AND operation='daily_coach' AND status='succeeded'",
            (workflow_key,),
        ).fetchall()
    finally:
        connection.close()
    total = 0
    calls = 0
    for row in rows:
        try:
            item = json.loads(str(row[0]))
        except json.JSONDecodeError:
            continue
        seconds = item.get("segment_seconds")
        if (
            isinstance(seconds, (int, float))
            and not isinstance(seconds, bool)
            and seconds > 0
        ):
            calls += 1
            total += int(seconds)
    return calls, total


def read_segment(
    database: Path,
    source_root: Path,
    inventory_id: int,
    start: int,
    end: int,
    resolution: int,
    reason_code: str,
    workflow_key: str,
) -> dict[str, Any]:
    segment_seconds = end - start
    if segment_seconds <= 0 or segment_seconds > MAX_SINGLE_SECONDS:
        raise ValueError("activity_segment_single_budget_exceeded")
    if resolution not in {1, 5}:
        raise ValueError("activity_segment_resolution_invalid")
    if workflow_key != _expected_workflow_key(database, inventory_id):
        raise ValueError("activity_segment_workflow_invalid")
    request = {
        "inventory_id": inventory_id,
        "start_offset_seconds": start,
        "end_offset_seconds": end,
        "resolution_seconds": resolution,
        "reason_code": reason_code,
        "workflow_key": workflow_key,
    }
    request_key = sha256_text(canonical_json(request))
    # The filesystem lock serializes the budget check, evidence read and run
    # reservation.  Without that lock, two processes could both observe the
    # same succeeded-call count before either commits a new segment.
    try:
        with workflow_lock(database):
            connection = connect(database)
            try:
                logical_key = f"training-coach:activity-segment:{request_key}"
                existing = connection.execute(
                    "SELECT content_json FROM skill_outputs WHERE logical_key=? ORDER BY revision_no DESC LIMIT 1",
                    (logical_key,),
                ).fetchone()
                if existing:
                    return json.loads(str(existing[0]))
                calls, total = _budget(database, workflow_key)
                if calls >= MAX_CALLS or total + segment_seconds > MAX_TOTAL_SECONDS:
                    raise ValueError("activity_segment_daily_budget_exceeded")
                payload = build_activity_evidence(
                    database,
                    source_root,
                    inventory_id,
                    resolution_seconds=resolution,
                    start_offset_seconds=start,
                    end_offset_seconds=end,
                )
                payload["reason_code"] = reason_code
                payload["workflow_key"] = workflow_key
                require_valid_payload(payload, "activity_segment_v1")
                run_id = begin_run(
                    connection,
                    run_key=f"{logical_key}:attempt-1",
                    workflow_key=workflow_key,
                    dedupe_key=request_key,
                    skill_name="training-coach",
                    operation="daily_coach",
                    trigger_kind="skill",
                    input_manifest={**request, "segment_seconds": segment_seconds},
                )
                append_output(
                    connection,
                    skill_run_id=run_id,
                    output_kind="bounded_evidence",
                    logical_key=logical_key,
                    schema_name="activity_segment_v1",
                    schema_version="1",
                    title_text="bounded activity segment",
                    content_json=payload,
                    content_text=json.dumps(
                        payload, ensure_ascii=False, sort_keys=True
                    ),
                    lineage=[
                        {
                            "raw_file_id": payload["raw_file_id"],
                            "raw_sha256": payload["raw_sha256"],
                        }
                    ],
                )
                finish_run(connection, run_id, status="succeeded")
                return payload
            finally:
                connection.close()
    except RuntimeError as exc:
        if str(exc) != "state_lock_unavailable":
            raise
        blocked = {
            "schema_version": "activity_segment_v1",
            "status": "blocked",
            "error_code": "state_lock_unavailable",
            "workflow_key": workflow_key,
            "activity_inventory_id": inventory_id,
            "reason_code": reason_code,
            "provider_calls": 0,
        }
        record_skill_result(
            database,
            skill_name="training-coach",
            operation="daily_coach",
            output_kind="bounded_evidence",
            logical_key=(f"training-coach:activity-segment:{request_key}:lock-blocked"),
            payload=blocked,
            status="blocked",
            error_code="state_lock_unavailable",
        )
        return blocked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--activity-inventory-id", type=int, required=True)
    parser.add_argument("--start-offset-seconds", type=int, required=True)
    parser.add_argument("--end-offset-seconds", type=int, required=True)
    parser.add_argument("--resolution-seconds", type=int, choices=(1, 5), required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--workflow-key", required=True)
    args = parser.parse_args()
    try:
        payload = read_segment(
            args.database,
            args.source_root,
            args.activity_inventory_id,
            args.start_offset_seconds,
            args.end_offset_seconds,
            args.resolution_seconds,
            args.reason_code,
            args.workflow_key,
        )
    except ValueError as exc:
        payload = {
            "schema_version": "activity_segment_v1",
            "status": "blocked",
            "error_code": str(exc),
            "provider_calls": 0,
        }
    require_valid_payload(payload, "activity_segment_v1")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("status") == "ready" else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
