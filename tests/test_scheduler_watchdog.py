from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from trainlab.db import connect
from trainlab.scheduler import scheduler_once
from trainlab.util import atomic_write_json, iso_utc, utc_now
from trainlab.watchdog import heartbeat_path, watchdog_once


def test_scheduler_runs_exact_minute_and_records_missed_without_catchup(settings):
    connection = connect(settings.database_path)
    state_path = settings.path("state_directory") / "scheduler_state.json"
    atomic_write_json(state_path, {"last_check_local": "2026-07-19T19:59:00+08:00"})
    result = scheduler_once(settings, connection, now=datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")))
    assert "trainlab-2026-07-19-evening-v1" in result["skipped"]
    assert result["triggered"]["status"] == "sent"
    skipped = connection.execute("SELECT status FROM analysis_runs WHERE run_id='trainlab-2026-07-19-evening-v1'").fetchone()
    assert skipped["status"] == "skipped"
    connection.close()


def test_watchdog_three_restarts_single_failure_and_single_recovery(settings):
    connection = connect(settings.database_path)
    attempts = {"count": 0}

    def failing_restart(_settings, _service):
        attempts["count"] += 1

    first = watchdog_once(settings, connection, restart=failing_restart, sleeper=lambda _seconds: None)
    assert all(item["restart_attempts"] == 3 for item in first.values())
    mail_count = connection.execute("SELECT COUNT(*) FROM mail_deliveries").fetchone()[0]
    assert mail_count == 2
    failure_ids = [row[0] for row in connection.execute("SELECT run_id FROM mail_deliveries ORDER BY run_id")]
    assert all(run_id.endswith("-failure") and run_id.isascii() for run_id in failure_ids)
    watchdog_once(settings, connection, restart=failing_restart, sleeper=lambda _seconds: None)
    assert connection.execute("SELECT COUNT(*) FROM mail_deliveries").fetchone()[0] == mail_count
    for service in settings.values["watchdog"]["services"].values():
        atomic_write_json(
            heartbeat_path(settings, service),
            {"updated_at_utc": iso_utc(), "pid": os.getpid(), "status": "ok", "details": {}},
        )
    watchdog_once(settings, connection, restart=failing_restart, sleeper=lambda _seconds: None)
    assert connection.execute("SELECT COUNT(*) FROM mail_deliveries").fetchone()[0] == mail_count + 2
    recovery_ids = [row[0] for row in connection.execute("SELECT run_id FROM mail_deliveries WHERE run_id LIKE '%-recovery'")]
    assert len(recovery_ids) == 2 and all(run_id.isascii() for run_id in recovery_ids)
    connection.close()
