from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .context import scheduled_run_id
from .db import transaction
from .runner import run_analysis
from .util import atomic_write_json, iso_utc, parse_datetime, utc_now


def _scheduled_datetime(settings: Settings, day, slot: str) -> datetime:
    hour, minute = (int(part) for part in str(settings.values["schedule"][slot]).split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(settings.timezone))


def _record_skipped(settings: Settings, connection, scheduled: datetime, slot: str) -> None:
    run_id = scheduled_run_id(scheduled.date().isoformat(), slot)
    connection.execute(
        """INSERT OR IGNORE INTO analysis_runs(
               run_id, slot, scheduled_local_date, scheduled_local_time, started_at_utc,
               completed_at_utc, runner, status, error_text
           ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            slot,
            scheduled.date().isoformat(),
            scheduled.strftime("%H:%M"),
            iso_utc(),
            iso_utc(),
            "scheduler",
            "skipped",
            "Scheduled minute was missed; offline catch-up is disabled.",
        ),
    )


def scheduler_once(settings: Settings, connection, *, now: datetime | None = None) -> dict[str, Any]:
    timezone = ZoneInfo(settings.timezone)
    current = now or utc_now()
    local = current.astimezone(timezone) if current.tzinfo else current.replace(tzinfo=timezone)
    local_minute = local.replace(second=0, microsecond=0)
    state_path = settings.path("state_directory") / "scheduler_state.json"
    previous = None
    if state_path.exists():
        try:
            previous = parse_datetime(json.loads(state_path.read_text(encoding="utf-8")).get("last_check_local"))
        except Exception:
            previous = None
    skipped: list[str] = []
    if previous:
        previous = previous.astimezone(timezone)
        day = previous.date()
        with transaction(connection):
            while day <= local.date():
                for slot in ("morning", "evening"):
                    scheduled = _scheduled_datetime(settings, day, slot)
                    if previous < scheduled < local_minute:
                        _record_skipped(settings, connection, scheduled, slot)
                        skipped.append(scheduled_run_id(day.isoformat(), slot))
                day += timedelta(days=1)
    triggered = None
    for slot in ("morning", "evening"):
        scheduled = _scheduled_datetime(settings, local.date(), slot)
        if local_minute == scheduled:
            run_id = scheduled_run_id(local.date().isoformat(), slot)
            exists = connection.execute("SELECT 1 FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if not exists:
                triggered = run_analysis(settings, connection, slot=slot, as_of=local)
    atomic_write_json(state_path, {"last_check_local": local_minute.isoformat(), "updated_at_utc": iso_utc()})
    return {"checked_local": local_minute.isoformat(), "skipped": skipped, "triggered": triggered}


def scheduler_daemon(settings: Settings, connection_factory) -> None:
    while True:
        connection = connection_factory()
        try:
            scheduler_once(settings, connection)
        finally:
            connection.close()
        time.sleep(60)
