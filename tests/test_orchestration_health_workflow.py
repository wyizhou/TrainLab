from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from trainlab.orchestration.contracts import WorkflowRequest
from trainlab.orchestration.health_workflow import HealthThresholds, HealthWorkflow


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []
        self.incidents: dict[str, SimpleNamespace] = {}

    def record_health_check(self, **values: object) -> int:
        self.checks.append(values)
        return len(self.checks)

    def latest_health_check_at(
        self, *, check_kind: str, target_kind: str,
        target_id: str | None = None,
    ) -> datetime | None:
        values = [
            item["checked_at_utc"]
            for item in self.checks
            if item["check_kind"] == check_kind
            and item["target_kind"] == target_kind
            and item.get("target_id") == target_id
        ]
        return None if not values else max(values)  # type: ignore[arg-type,return-value]

    def get_incident(self, incident_key: str):
        return self.incidents.get(incident_key)

    def record_incident(self, **values: object) -> None:
        key = str(values["incident_key"])
        current = self.incidents.get(key)
        self.incidents[key] = SimpleNamespace(state="open", occurrence_count=1 if current is None else current.occurrence_count + 1)

    def transition_incident(self, incident_key: str, state: str, *, at_utc: datetime) -> None:
        current = self.incidents[incident_key]
        self.incidents[incident_key] = SimpleNamespace(state=state, occurrence_count=current.occurrence_count)


class Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def deliver(self, incident_key: str, *, event: str = "open") -> None:
        self.calls.append((incident_key, event))


def request() -> WorkflowRequest:
    return WorkflowRequest("health_check", None, None, "health-1", "scheduled", None, (), "2026-07-27T01:00:00Z", "2026-07-27T00:00:00Z")


def foundation_database(root: Path, *, include_cursor: bool = True) -> Path:
    database = root / "data.db"
    state = root / "state"
    state.mkdir()
    (state / "foundation-ready.json").write_text('{"ready":true}', encoding="utf-8")
    (root / "logs").mkdir()
    conn = sqlite3.connect(database)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE foundation_state(id INTEGER PRIMARY KEY,state TEXT,schema_version INTEGER);
        CREATE TABLE garmin_sync_cursors(complete_through_local_date TEXT);
        CREATE TABLE garmin_sync_gaps(status TEXT);
        CREATE TABLE analysis_deliveries(status TEXT);
        CREATE TABLE mail_messages(processing_state TEXT);
        CREATE TABLE mail_poll_cursors(observed_through_utc TEXT);
        CREATE TABLE scheduler_leases(lease_key TEXT,heartbeat_at_utc TEXT,expires_at_utc TEXT);
        """)
        conn.execute("INSERT INTO foundation_state VALUES(1,'ready',3)")
        if include_cursor:
            conn.execute("INSERT INTO garmin_sync_cursors VALUES('2026-07-26')")
        conn.execute("INSERT INTO mail_poll_cursors VALUES('2026-07-27T00:00:00Z')")
        conn.execute("INSERT INTO scheduler_leases VALUES('supervisor','2026-07-27T00:00:00Z','2026-07-27T00:02:00Z')")
        conn.commit()
    finally:
        conn.close()
    return database


def test_health_workflow_records_only_metadata_and_never_changes_foundation_database(tmp_path: Path) -> None:
    database = foundation_database(tmp_path)
    before = sha256(database.read_bytes()).hexdigest()
    repository = Repository()
    workflow = HealthWorkflow(
        database_path=database, state_directory=tmp_path / "state", log_directory=tmp_path / "logs",
        storage_directory=tmp_path, repository=repository, clock=lambda: NOW,
    )

    outcome = workflow.execute(request())

    assert outcome.status == "succeeded"
    assert outcome.next_action == "none"
    assert len(repository.checks) == 9
    assert sha256(database.read_bytes()).hexdigest() == before
    assert all("body" not in str(check).lower() and "payload" not in str(check).lower() for check in repository.checks)
    assert {check["check_kind"] for check in repository.checks} == {
        "foundation", "sqlite", "garmin", "analysis", "mail", "supervisor", "disk", "logs",
    }
    sqlite_targets = {
        str(check["target_kind"])
        for check in repository.checks
        if check["check_kind"] == "sqlite"
    }
    assert sqlite_targets == {"readiness", "integrity"}


def test_health_workflow_reports_counts_and_times_but_not_lower_layer_content(tmp_path: Path) -> None:
    database = foundation_database(tmp_path, include_cursor=False)
    conn = sqlite3.connect(database)
    try:
        conn.execute("INSERT INTO garmin_sync_gaps VALUES('open')")
        conn.execute("INSERT INTO analysis_deliveries VALUES('failed')")
        conn.execute("INSERT INTO mail_messages VALUES('queued')")
        conn.execute("DELETE FROM scheduler_leases")
        conn.commit()
    finally:
        conn.close()
    repository = Repository()
    workflow = HealthWorkflow(
        database_path=database, state_directory=tmp_path / "state", log_directory=tmp_path / "logs",
        storage_directory=tmp_path, repository=repository, clock=lambda: NOW,
    )

    outcome = workflow.execute(request())

    assert outcome.status == "partial"
    assert outcome.next_action == "review_health"
    assert {item["code"] for item in outcome.warnings} == {
        "health_garmin_cursor", "health_analysis_delivery", "health_mail_backlog", "health_supervisor_lease",
    }
    values = {str(check["check_kind"]): check["metrics"] for check in repository.checks}
    assert values["garmin"] == {"cursor_count": 0, "open_gaps": 1, "lag_days": None}
    assert values["analysis"] == {"attention_count": 1}
    assert values["mail"] == {"pending_count": 1, "cursor_count": 1, "cursor_age_seconds": 0}
    assert all("content" not in str(value).lower() and "email" not in str(value).lower() for value in values.values())


def test_health_ignores_retryable_delivery_superseded_by_later_sent_report(
    tmp_path: Path,
) -> None:
    database = foundation_database(tmp_path)
    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP TABLE analysis_deliveries")
        conn.execute(
            "CREATE TABLE analysis_deliveries("
            "id INTEGER PRIMARY KEY,subject_id INTEGER,delivery_kind TEXT,status TEXT,"
            "created_at_utc TEXT)"
        )
        conn.executemany(
            "INSERT INTO analysis_deliveries VALUES(?,?,?,?,?)",
            (
                (1, 1, "daily_report", "pending", "2026-07-26T00:00:00Z"),
                (2, 1, "daily_report", "failed", "2026-07-26T00:01:00Z"),
                (3, 1, "daily_report", "sent", "2026-07-26T00:02:00Z"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    repository = Repository()
    outcome = HealthWorkflow(
        database_path=database,
        state_directory=tmp_path / "state",
        log_directory=tmp_path / "logs",
        storage_directory=tmp_path,
        repository=repository,
        clock=lambda: NOW,
    ).execute(request())
    analysis = next(
        item for item in repository.checks if item["check_kind"] == "analysis"
    )
    assert analysis["status"] == "ready"
    assert analysis["metrics"] == {"attention_count": 0}
    assert outcome.status == "succeeded"


def test_health_workflow_marks_missing_database_attention_without_attempting_repair(tmp_path: Path) -> None:
    repository = Repository()
    workflow = HealthWorkflow(
        database_path=tmp_path / "missing.db", state_directory=tmp_path / "state", log_directory=tmp_path / "logs",
        storage_directory=tmp_path, repository=repository, clock=lambda: NOW,
        thresholds=HealthThresholds(),
    )

    outcome = workflow.execute(request())

    assert outcome.status == "attention_required"
    assert outcome.next_action == "operator_review"
    assert not (tmp_path / "missing.db").exists()
    assert any(item["code"] == "health_foundation_schema" for item in outcome.errors)


def test_health_workflow_rejects_non_health_request_without_database_access(tmp_path: Path) -> None:
    workflow = HealthWorkflow(
        database_path=tmp_path / "missing.db", state_directory=tmp_path, log_directory=tmp_path,
        repository=Repository(), clock=lambda: NOW,
    )
    invalid = WorkflowRequest("morning", "1", "2026-07-27", "morning-1", "scheduled", None, (), "2026-07-27T01:00:00Z", "2026-07-27T00:00:00Z")

    outcome = workflow.execute(invalid)

    assert outcome.status == "failed"
    assert outcome.errors == ({"code": "health_request_invalid", "summary": "health check requires operator review"},)


def test_health_workflow_routes_open_and_recovery_alerts_without_affecting_result(
    tmp_path: Path,
) -> None:
    database = foundation_database(tmp_path, include_cursor=False)
    repository = Repository()
    alerts = Alerts()
    workflow = HealthWorkflow(
        database_path=database,
        state_directory=tmp_path / "state",
        log_directory=tmp_path / "logs",
        storage_directory=tmp_path,
        repository=repository,
        clock=lambda: NOW,
        alert_service=alerts,
    )
    first = workflow.execute(request())
    assert first.status == "partial"
    assert ("health:garmin:cursor", "open") in alerts.calls

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO garmin_sync_cursors VALUES('2026-07-26')"
        )
        connection.commit()
    finally:
        connection.close()
    alerts.calls.clear()
    second = workflow.execute(request())
    assert second.status == "succeeded"
    assert ("health:garmin:cursor", "recovery") in alerts.calls


def test_sqlite_deep_integrity_check_runs_at_daily_cadence(
    tmp_path: Path,
) -> None:
    database = foundation_database(tmp_path)
    repository = Repository()
    current = [NOW]
    workflow = HealthWorkflow(
        database_path=database,
        state_directory=tmp_path / "state",
        log_directory=tmp_path / "logs",
        storage_directory=tmp_path,
        repository=repository,
        clock=lambda: current[0],
    )

    assert workflow.execute(request()).status == "succeeded"
    assert sum(
        item["check_kind"] == "sqlite" and item["target_kind"] == "integrity"
        for item in repository.checks
    ) == 1

    current[0] += timedelta(minutes=1)
    assert workflow.execute(request()).status == "succeeded"
    assert sum(
        item["check_kind"] == "sqlite" and item["target_kind"] == "integrity"
        for item in repository.checks
    ) == 1

    current[0] += timedelta(days=1)
    workflow.execute(request())
    assert sum(
        item["check_kind"] == "sqlite" and item["target_kind"] == "integrity"
        for item in repository.checks
    ) == 2
