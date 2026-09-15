#!/usr/bin/env python3
"""Resolve the current Hong Kong noon slot without accepting a date argument."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import (  # noqa: E402
    require_valid_payload,
)
from state import connect, state_path  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")
NOON = time(12, 0)


@dataclass(frozen=True)
class Slot:
    slot_date: str
    slot_start: str
    slot_end: str
    workflow_keys: tuple[str, ...]
    weekday: int


def resolve_slot(now: datetime | None = None) -> Slot:
    observed = (now or datetime.now(HKT)).astimezone(HKT)
    anchor = (
        observed.date()
        if observed.timetz().replace(tzinfo=None) >= NOON
        else observed.date() - timedelta(days=1)
    )
    start = datetime.combine(anchor, NOON, HKT)
    end = start + timedelta(days=1)
    keys = [f"daily:{anchor.isoformat()}"]
    if anchor.weekday() == 6:
        keys.append(f"weekly:{anchor.isoformat()}")
    return Slot(
        slot_date=anchor.isoformat(),
        slot_start=start.isoformat(),
        slot_end=end.isoformat(),
        workflow_keys=tuple(keys),
        weekday=anchor.weekday(),
    )


def _receipt_exists(connection, workflow_key: str) -> bool:
    row = connection.execute(
        """SELECT content_json FROM skill_outputs
           WHERE output_kind='execution_summary' AND logical_key=?
           ORDER BY revision_no DESC LIMIT 1""",
        (f"workflow:{workflow_key}",),
    ).fetchone()
    if not row or not row[0]:
        return False
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("status") != "succeeded"
        or payload.get("workflow_key") != workflow_key
    ):
        return False
    try:
        require_valid_payload(payload, "workflow_receipt_v1")
    except ValueError:
        return False
    return True


def resolve_due(database: Path, now: datetime | None = None) -> dict[str, object]:
    slot = resolve_slot(now)
    if not database.is_file():
        return {
            "status": "blocked",
            "outcome": "blocked",
            "error_code": "state_missing",
            **asdict(slot),
        }
    connection = connect(database, read_only=True, immutable=True)
    try:
        daily_key = slot.workflow_keys[0]
        daily_done = _receipt_exists(connection, daily_key)
        weekly_key = slot.workflow_keys[1] if len(slot.workflow_keys) == 2 else None
        weekly_done = bool(weekly_key and _receipt_exists(connection, weekly_key))
    finally:
        connection.close()
    if daily_done and (weekly_key is None or weekly_done):
        outcome = "no_due"
    elif weekly_key and not daily_done:
        outcome = "daily_due_weekly_waiting"
    elif weekly_key and daily_done and not weekly_done:
        outcome = "weekly_due"
    else:
        outcome = "daily_due"
    return {
        "status": "succeeded",
        "outcome": outcome,
        **asdict(slot),
        "daily_complete": daily_done,
        "weekly_complete": weekly_done if weekly_key else None,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=state_path())
    args = parser.parse_args()
    payload = resolve_due(args.database)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
