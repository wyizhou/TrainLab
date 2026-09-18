from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

from tests.e2e_support.auth_transport import AuthTransport
from trainlab.contracts.time import format_utc
from trainlab.fit import ParsedActivity, import_activity, initialize_schema, open_database
from trainlab.fit.models import ParsedRecord
from trainlab.garmin_sync import GarminSyncState, save_sync_state
from trainlab.local_web.server import WebAppSettings, create_app
from trainlab.reports import save_activity_report, save_weekly_report


def _add_activity(
    instance_root: Path,
    activity_id: str,
    *,
    sport: str,
    start: datetime,
    report: str | None = None,
) -> None:
    connection = open_database(instance_root / "states/data.db")
    initialize_schema(connection)
    parsed = _valid_activity()
    end = start + timedelta(hours=1)
    parsed = replace(
        parsed,
        sport=sport,
        start_time_utc=start,
        end_time_utc=end,
        basic={
            **parsed.basic,
            "sport": sport,
            "start_time_utc": format_utc(start),
            "end_time_utc": format_utc(end),
        },
    )
    import_activity(
        connection,
        activity_id=activity_id,
        fit_path=f"states/activities/{activity_id}.fit",
        parsed=parsed,
        parsed_at_utc=datetime(2030, 1, 10, tzinfo=UTC),
    )
    if report is not None:
        save_activity_report(connection, activity_id=activity_id, summary=report)
    connection.close()


def _valid_activity() -> ParsedActivity:
    field = {
        "message_number": 20,
        "message_name": "record",
        "field_number": 3,
        "name": "heart_rate",
        "base_type": "uint8",
        "unit": "bpm",
        "origin": "direct",
        "source_ref": None,
        "definition_index": 0,
        "chain_index": 0,
        "component_of": None,
        "value_form": "physical",
    }
    session_field = {
        **field,
        "message_number": 18,
        "message_name": "session",
        "definition_index": 1,
        "field_number": 16,
        "name": "avg_heart_rate",
    }
    message = {
        "message_index": 2,
        "chain_index": 0,
        "message_number": 18,
        "message_name": "session",
        "fields": {"standard": {"f1": 100}, "developer": {}},
    }
    return ParsedActivity(
        "running",
        None,
        None,
        None,
        {
            "sport": "running",
            "sub_sport": None,
            "start_time_utc": None,
            "end_time_utc": None,
            "messages": [],
        },
        {"messages": [message]},
        {"items": []},
        {
            "field_definitions": {"f0": field, "f1": session_field},
            "developer_sources": {},
            "messages": [],
        },
        (
            ParsedRecord(
                None,
                {
                    "standard": {"f0": 0},
                    "developer": {},
                    "time_evidence": {"kind": "missing", "raw": None, "unit": None},
                },
            ),
        ),
    )


def create_instance() -> Path:
    root = Path(tempfile.mkdtemp(prefix="trainlab-web-e2e-"))
    (root / "states/activities").mkdir(parents=True)
    (root / "states/health").mkdir(parents=True)
    (root / "states/verification").mkdir(parents=True)
    _add_activity(
        root,
        "a" * 64,
        sport="running",
        start=datetime(2030, 1, 3, 8, 0, tzinfo=UTC),
        report="安全文本 <strong>不会当 HTML</strong>",
    )
    _add_activity(
        root,
        "b" * 64,
        sport="cycling",
        start=datetime(2030, 1, 4, 8, 0, tzinfo=UTC),
    )
    connection = open_database(root / "states/data.db")
    save_weekly_report(
        connection,
        run_time_utc=datetime(2030, 1, 8, 15, 0, tzinfo=UTC),
        summary="周总结全文",
    )
    connection.close()
    save_sync_state(
        root,
        GarminSyncState(
            last_attempt_at_utc=datetime(2030, 1, 5, tzinfo=UTC),
            last_success_at_utc=datetime(2030, 1, 5, tzinfo=UTC),
        ),
    )
    return root


def main() -> None:
    transport = AuthTransport()
    transport.block_network()
    instance_root = create_instance()
    try:
        app = create_app(
            WebAppSettings(
                instance_root=instance_root,
                project_root=Path(__file__).resolve().parents[3],
            )
        )
        uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning", proxy_headers=False, access_log=False)
    finally:
        shutil.rmtree(instance_root, ignore_errors=True)
        assert transport.external_attempts == 0


if __name__ == "__main__":
    main()
