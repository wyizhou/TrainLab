#!/usr/bin/env python3
"""Build the exact daily Garmin request window without contacting Garmin."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import record_skill_result  # noqa: E402

HEALTH_D_MINUS_ONE = ["rhr", "hrv", "heart_rates", "max_metrics", "weigh_ins"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, help="D in YYYY-MM-DD")
    parser.add_argument("--backfill-date", default=None)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    run_date = date.fromisoformat(args.run_date)
    previous = run_date - timedelta(days=1)
    if args.backfill_date and args.backfill_date != previous.isoformat():
        payload = {
            "status": "blocked",
            "error_code": "garmin_backfill_not_approved",
            "external_calls": 0,
        }
        if args.database:
            record_skill_result(
                args.database,
                skill_name="garmin-sync",
                operation="daily_sync",
                output_kind="sync_summary",
                logical_key=f"garmin-sync:window:{args.run_date}",
                payload=payload,
                status="blocked",
                error_code=str(payload["error_code"]),
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    payload = {
        "schema_version": "1",
        "status": "planned",
        "timezone": "Asia/Hong_Kong",
        "run_date": run_date.isoformat(),
        "health_dates": {
            resource: previous.isoformat() for resource in HEALTH_D_MINUS_ONE
        },
        "main_sleep_wake_date": run_date.isoformat(),
        "activity_inventory_date": previous.isoformat(),
        "activity_summary": False,
        "history_readback_days": 0,
        "activity_originals": "new_or_incomplete_only",
        "activity_weather": "new_outdoor_only",
        "external_calls": 0,
        "provider": "garmin",
    }
    if args.database:
        record_skill_result(
            args.database,
            skill_name="garmin-sync",
            operation="daily_sync",
            output_kind="sync_summary",
            logical_key=f"garmin-sync:window:{args.run_date}",
            payload=payload,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
