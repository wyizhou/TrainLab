#!/usr/bin/env python3
"""Select bounded daily/weekly output history from SQLite."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import connect, record_skill_result  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--week-ending", required=True)
    args = parser.parse_args()
    ending = date.fromisoformat(args.week_ending)
    start = ending - timedelta(days=6)
    connection = connect(args.database, read_only=True)
    try:
        daily = [
            dict(row)
            for row in connection.execute(
                """SELECT id, logical_key, revision_no, period_start_date, period_end_date,
                      content_sha256 FROM skill_outputs
               WHERE output_kind='daily_summary'
                 AND period_start_date >= ? AND period_end_date <= ?
                 AND revision_no = (
                   SELECT MAX(revision_no) FROM skill_outputs newer
                   WHERE newer.logical_key=skill_outputs.logical_key
                 )
               ORDER BY period_end_date DESC LIMIT 7""",
                (start.isoformat(), ending.isoformat()),
            )
        ]
        weekly = [
            dict(row)
            for row in connection.execute(
                """SELECT id, logical_key, revision_no, period_start_date, period_end_date,
                      content_sha256 FROM skill_outputs
               WHERE output_kind='weekly_summary' AND period_end_date < ?
                 AND revision_no = (
                   SELECT MAX(revision_no) FROM skill_outputs newer
                   WHERE newer.logical_key=skill_outputs.logical_key
                 )
               ORDER BY period_end_date DESC LIMIT 4""",
                (start.isoformat(),),
            )
        ]
    finally:
        connection.close()
    payload = {
        "week_start": start.isoformat(),
        "week_end": ending.isoformat(),
        "daily": daily,
        "weekly": weekly,
    }
    record_skill_result(
        args.database,
        skill_name="weekly-fitness-summary",
        operation="summarize_week",
        output_kind="bounded_evidence",
        logical_key=f"weekly-fitness-summary:history:{args.week_ending}",
        payload=payload,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
