from __future__ import annotations

import copy
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration import OrchestrationRepository, OrchestrationRepositoryError, OrchestrationSchemaIncompatible, SchedulerJobProjection


NOW = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
HASH = "a" * 64


def repository(tmp_path: Path) -> tuple[OrchestrationRepository, Path]:
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock"))
    assert tool.execute(FoundationRequest("init", "s5-03-fixture", "2026-07-23T00:00:00Z")).status == "initialized"
    return OrchestrationRepository(root / "data.db"), root / "data.db"


def workflow(repo: OrchestrationRepository, key: str = "morning:2026-07-23"):
    return repo.create_workflow(workflow_key=key, workflow_kind="morning", trigger_kind="scheduled", started_at_utc=NOW, logical_local_date="2026-07-23")


def test_schema_missing_or_drift_fails_closed_without_repairs(tmp_path: Path) -> None:
    missing = OrchestrationRepository(tmp_path / "missing.db")
    with pytest.raises(OrchestrationSchemaIncompatible):
        missing.recent_workflows()
    repo, db = repository(tmp_path / "drift")
    manifest = json.loads((Path(__file__).resolve().parents[1] / "harness/schemas/foundation_schema_manifest.json").read_text())
    broken = copy.deepcopy(manifest); broken["tables"]["orchestrator_runs"]["columns"].append("unexpected_column")
    manifest_path = tmp_path / "drift-manifest.json"; manifest_path.write_text(json.dumps(broken))
    with pytest.raises(OrchestrationSchemaIncompatible):
        OrchestrationRepository(db, manifest_path=manifest_path).recent_workflows()
    assert repo.recent_workflows() == ()


def test_scheduler_job_projection_is_persisted_but_lease_is_read_only(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    projection = SchedulerJobProjection("morning", "morning", "Asia/Hong_Kong", "daily_at", NOW, "2026-07-23", None, None, "own_incremental", timedelta(hours=12), HASH)
    saved = repo.upsert_scheduler_job(projection, is_enabled=True, updated_at_utc=NOW)
    assert saved.job_key == "morning" and repo.get_scheduler_job("morning") == saved
    assert repo.get_scheduler_lease("supervisor") is None


def test_calendar_projection_preserves_bounded_restart_misfire(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    due = NOW - timedelta(hours=2)
    first = SchedulerJobProjection(
        "morning", "morning", "Asia/Hong_Kong", "daily_at", due,
        "2026-07-22", None, None, "own_incremental", timedelta(hours=12), HASH,
    )
    repo.upsert_scheduler_job(first, is_enabled=True, updated_at_utc=due)
    projected = SchedulerJobProjection(
        "morning", "morning", "Asia/Hong_Kong", "daily_at", NOW + timedelta(days=1),
        "2026-07-24", None, None, "own_incremental", timedelta(hours=12), HASH,
    )
    saved = repo.upsert_scheduler_job(projected, is_enabled=True, updated_at_utc=NOW)
    assert saved.next_due_at_utc == due.isoformat().replace("+00:00", "Z")


def test_workflow_step_uniqueness_recovery_and_status_guards(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    first = workflow(repo)
    assert repo.get_workflow(first.workflow_key) == first and repo.recent_workflows() == (first,)
    assert repo.get_workflow_by_id(first.id) == first
    assert repo.get_workflow_by_id(first.id + 1000) is None
    with pytest.raises(OrchestrationRepositoryError, match="workflow_key_conflict"):
        workflow(repo)
    step = repo.create_step(workflow_key=first.workflow_key, step_key="garmin_incremental", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH, invocation_id="invoke-1", downstream_run_id="garmin-run-1")
    assert repo.get_step(first.workflow_key, step.step_key) == step
    with pytest.raises(OrchestrationRepositoryError, match="ordinal_conflict"):
        repo.create_step(workflow_key=first.workflow_key, step_key="different", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    with pytest.raises(OrchestrationRepositoryError, match="step_key_conflict"):
        repo.create_step(workflow_key=first.workflow_key, step_key="garmin_incremental", ordinal=1, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    running = repo.transition_step(workflow_key=first.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    assert running.attempt_count == 1
    done = repo.transition_step(workflow_key=first.workflow_key, step_key=step.step_key, status="succeeded", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64, controlled_counts={"fetched": 2})
    assert done.receipt_sha256 == "b" * 64
    completed = repo.transition_workflow(first.workflow_key, "succeeded", at_utc=NOW + timedelta(seconds=2))
    assert completed.completed_at_utc is not None
    with pytest.raises(OrchestrationRepositoryError, match="(transition_invalid|timestamp_invalid)"):
        repo.transition_step(workflow_key=first.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    with pytest.raises(OrchestrationRepositoryError, match="transition_invalid"):
        repo.transition_workflow(first.workflow_key, "deferred", at_utc=NOW)


def test_hash_count_payload_and_sql_injection_are_rejected_or_parameterized(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo, "manual:one")
    with pytest.raises(OrchestrationRepositoryError, match="sha256_invalid"):
        repo.create_step(workflow_key=run.workflow_key, step_key="bad-hash", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256="raw request body")
    step = repo.create_step(workflow_key=run.workflow_key, step_key="safe", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    with pytest.raises(OrchestrationRepositoryError, match="controlled_counts_invalid"):
        repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="deferred", at_utc=NOW, controlled_counts={"body": -1})
    with pytest.raises(OrchestrationRepositoryError, match="identifier_invalid"):
        repo.get_workflow("x' OR 1=1 --")
    assert repo.get_workflow(run.workflow_key) is not None
    with pytest.raises(OrchestrationRepositoryError, match="controlled_code_invalid"):
        repo.record_incident(incident_key="secret-incident", category="database", severity="error", seen_at_utc=NOW, error_summary="token=abcd")
    with pytest.raises(OrchestrationRepositoryError, match="controlled_code_invalid"):
        repo.record_incident(incident_key="body-incident", category="database", severity="error", seen_at_utc=NOW, error_summary="用户邮件正文不应进入运维表")
    with pytest.raises(OrchestrationRepositoryError, match="controlled_code_invalid"):
        repo.record_health_check(check_kind="sqlite", target_kind="database", status="ready", checked_at_utc=NOW, metrics={"payload": "health body"})


def test_incident_dedup_state_lifecycle_alert_fk_and_read_only_recovery(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo)
    incident = repo.record_incident(incident_key="database:busy", category="database", severity="error", seen_at_utc=NOW, related_workflow_run_id=run.id, error_code="busy")
    duplicate = repo.record_incident(incident_key="database:busy", category="database", severity="error", seen_at_utc=NOW + timedelta(minutes=1), related_workflow_run_id=run.id, error_code="busy")
    assert duplicate.id == incident.id and duplicate.occurrence_count == 2 and duplicate.first_seen_at_utc == incident.first_seen_at_utc
    acknowledged = repo.transition_incident(incident.incident_key, "acknowledged", at_utc=NOW + timedelta(minutes=1))
    resolved = repo.transition_incident(incident.incident_key, "resolved", at_utc=NOW + timedelta(minutes=2))
    assert acknowledged.resolved_at_utc is None and resolved.resolved_at_utc is not None and repo.open_incidents() == ()
    reopened = repo.transition_incident(incident.incident_key, "open", at_utc=NOW + timedelta(minutes=3))
    assert reopened.resolved_at_utc is None and repo.open_incidents() == (reopened,)
    suppressed = repo.transition_incident(incident.incident_key, "suppressed", at_utc=NOW + timedelta(minutes=3))
    assert suppressed.state == "suppressed" and suppressed.resolved_at_utc is None
    with pytest.raises(OrchestrationRepositoryError, match="transition_invalid"):
        repo.transition_incident(incident.incident_key, "acknowledged", at_utc=NOW)
    alert = repo.create_alert_delivery(incident_key=incident.incident_key, idempotency_key="ops:database:busy")
    assert repo.create_alert_delivery(incident_key=incident.incident_key, idempotency_key="ops:database:busy") == alert
    assert repo.transition_alert_delivery(alert.idempotency_key, "sending").status == "sending"
    with pytest.raises(OrchestrationRepositoryError, match="transition_invalid"):
        repo.transition_alert_delivery(alert.idempotency_key, "pending")
    with pytest.raises(OrchestrationRepositoryError, match="not_found"):
        repo.create_alert_delivery(incident_key="not-found", idempotency_key="ops:nope")


def test_success_resolves_only_earlier_open_mail_failures_for_same_subject(
    tmp_path: Path,
) -> None:
    repo, db_path = repository(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO data_subjects"
            "(subject_key,timezone,is_active,created_at_utc) "
            "VALUES(?,?,1,?)",
            (
                ("subject-one", "Asia/Hong_Kong", "2026-07-23T00:00:00Z"),
                ("subject-two", "Asia/Hong_Kong", "2026-07-23T00:00:00Z"),
            ),
        )
        connection.commit()
        subject_one, subject_two = (
            row[0]
            for row in connection.execute(
                "SELECT id FROM data_subjects ORDER BY id"
            ).fetchall()
        )

    def completed(key: str, subject_id: int, status: str, second: int):
        run = repo.create_workflow(
            workflow_key=key,
            workflow_kind="mail",
            trigger_kind="scheduled",
            subject_id=subject_id,
            started_at_utc=NOW + timedelta(seconds=second),
        )
        return repo.transition_workflow(
            run.workflow_key,
            status,
            at_utc=NOW + timedelta(seconds=second + 1),
        )

    matching = completed("mail:failed:matching", subject_one, "failed", 1)
    other_subject = completed(
        "mail:failed:other-subject", subject_two, "failed", 3
    )
    acknowledged = completed(
        "mail:failed:acknowledged", subject_one, "failed", 5
    )
    safety = completed("mail:failed:safety", subject_one, "failed", 7)
    wrong_code = completed("mail:failed:wrong-code", subject_one, "failed", 9)
    for run, incident_key, category, error_code in (
        (
            matching,
            "workflow:failed:mail:matching",
            "workflow",
            "workflow_execution_failed",
        ),
        (
            other_subject,
            "workflow:failed:mail:other-subject",
            "workflow",
            "workflow_execution_failed",
        ),
        (
            acknowledged,
            "workflow:failed:mail:acknowledged",
            "workflow",
            "workflow_execution_failed",
        ),
        (
            safety,
            "safety:mail:matching",
            "safety",
            "workflow_execution_failed",
        ),
        (
            wrong_code,
            "workflow:failed:mail:wrong-code",
            "workflow",
            "provider_unavailable",
        ),
    ):
        repo.record_incident(
            incident_key=incident_key,
            category=category,
            severity="error",
            seen_at_utc=NOW + timedelta(seconds=11),
            error_code=error_code,
            next_action="operator_review",
            related_workflow_run_id=run.id,
        )
    repo.transition_incident(
        "workflow:failed:mail:acknowledged",
        "acknowledged",
        at_utc=NOW + timedelta(seconds=12),
    )
    success = completed("mail:succeeded:current", subject_one, "succeeded", 13)
    future = completed("mail:failed:future", subject_one, "failed", 15)
    repo.record_incident(
        incident_key="workflow:failed:mail:future",
        category="workflow",
        severity="error",
        seen_at_utc=NOW + timedelta(seconds=17),
        error_code="workflow_execution_failed",
        related_workflow_run_id=future.id,
    )

    recovered = repo.resolve_retryable_workflow_failures(
        success.workflow_key, at_utc=NOW + timedelta(seconds=18)
    )

    assert tuple(item.incident_key for item in recovered) == (
        "workflow:failed:mail:matching",
    )
    assert repo.get_incident("workflow:failed:mail:matching").state == "resolved"
    for key in (
        "workflow:failed:mail:other-subject",
        "workflow:failed:mail:acknowledged",
        "safety:mail:matching",
        "workflow:failed:mail:wrong-code",
        "workflow:failed:mail:future",
    ):
        assert repo.get_incident(key).state != "resolved"


@pytest.mark.parametrize("workflow_kind", ("morning", "weekly"))
def test_analysis_success_recovery_is_scoped_to_subject_and_logical_date(
    tmp_path: Path, workflow_kind: str
) -> None:
    repo, db_path = repository(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO data_subjects"
            "(subject_key,timezone,is_active,created_at_utc) "
            "VALUES(?,?,1,?)",
            (
                ("subject-one", "Asia/Hong_Kong", "2026-07-23T00:00:00Z"),
                ("subject-two", "Asia/Hong_Kong", "2026-07-23T00:00:00Z"),
            ),
        )
        connection.commit()
        subject_one, subject_two = (
            row[0]
            for row in connection.execute(
                "SELECT id FROM data_subjects ORDER BY id"
            ).fetchall()
        )

    def completed(
        suffix: str, subject_id: int, logical_date: str, status: str, second: int
    ):
        run = repo.create_workflow(
            workflow_key=f"{workflow_kind}:{suffix}",
            workflow_kind=workflow_kind,
            trigger_kind="manual",
            subject_id=subject_id,
            logical_local_date=logical_date,
            started_at_utc=NOW + timedelta(seconds=second),
        )
        return repo.transition_workflow(
            run.workflow_key,
            status,
            at_utc=NOW + timedelta(seconds=second + 1),
        )

    matching = completed(
        "failed-matching", subject_one, "2026-07-23", "failed", 1
    )
    other_date = completed(
        "failed-other-date", subject_one, "2026-07-24", "failed", 3
    )
    other_subject = completed(
        "failed-other-subject", subject_two, "2026-07-23", "failed", 5
    )
    for suffix, run in (
        ("matching", matching),
        ("other-date", other_date),
        ("other-subject", other_subject),
    ):
        repo.record_incident(
            incident_key=f"workflow:failed:{workflow_kind}:{suffix}",
            category="workflow",
            severity="error",
            seen_at_utc=NOW + timedelta(seconds=7),
            error_code="workflow_execution_failed",
            related_workflow_run_id=run.id,
        )
    success = completed(
        "succeeded-current", subject_one, "2026-07-23", "succeeded", 9
    )

    recovered = repo.resolve_retryable_workflow_failures(
        success.workflow_key, at_utc=NOW + timedelta(seconds=11)
    )

    assert tuple(item.incident_key for item in recovered) == (
        f"workflow:failed:{workflow_kind}:matching",
    )
    assert repo.get_incident(
        f"workflow:failed:{workflow_kind}:other-date"
    ).state == "open"
    assert repo.get_incident(
        f"workflow:failed:{workflow_kind}:other-subject"
    ).state == "open"


def test_health_success_resolves_only_open_workflow_execution_failures(
    tmp_path: Path,
) -> None:
    repo, _ = repository(tmp_path)
    failed = repo.create_workflow(
        workflow_key="health:failed",
        workflow_kind="health_check",
        trigger_kind="scheduled",
        started_at_utc=NOW,
    )
    failed = repo.transition_workflow(
        failed.workflow_key, "failed", at_utc=NOW + timedelta(seconds=1)
    )
    repo.record_incident(
        incident_key="workflow:failed:health:one",
        category="workflow",
        severity="error",
        seen_at_utc=NOW + timedelta(seconds=2),
        error_code="workflow_execution_failed",
        related_workflow_run_id=failed.id,
    )
    repo.record_incident(
        incident_key="health:sqlite:warning",
        category="health",
        severity="warning",
        seen_at_utc=NOW + timedelta(seconds=2),
        error_code="sqlite_unready",
        related_workflow_run_id=failed.id,
    )
    success = repo.create_workflow(
        workflow_key="health:succeeded",
        workflow_kind="health_check",
        trigger_kind="scheduled",
        started_at_utc=NOW + timedelta(seconds=3),
    )
    success = repo.transition_workflow(
        success.workflow_key,
        "succeeded",
        at_utc=NOW + timedelta(seconds=4),
    )

    recovered = repo.resolve_retryable_workflow_failures(
        success.workflow_key, at_utc=NOW + timedelta(seconds=5)
    )

    assert tuple(item.incident_key for item in recovered) == (
        "workflow:failed:health:one",
    )
    assert repo.get_incident("health:sqlite:warning").state == "open"


def test_workflow_recovery_pages_through_more_than_two_hundred_incidents(
    tmp_path: Path,
) -> None:
    repo, db_path = repository(tmp_path)
    failed = repo.create_workflow(
        workflow_key="health:failed:batch",
        workflow_kind="health_check",
        trigger_kind="scheduled",
        started_at_utc=NOW,
    )
    failed = repo.transition_workflow(
        failed.workflow_key, "failed", at_utc=NOW + timedelta(seconds=1)
    )
    seen = "2026-07-23T00:00:02Z"
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO operational_incidents "
            "(incident_key,category,severity,state,related_workflow_run_id,"
            "first_seen_at_utc,last_seen_at_utc,occurrence_count,error_code,"
            "next_action) VALUES(?, 'workflow', 'error', 'open', ?, ?, ?, 1, "
            "'workflow_execution_failed', 'retry')",
            (
                (f"workflow:failed:health:batch:{index}", failed.id, seen, seen)
                for index in range(205)
            ),
        )
        connection.commit()
    success = repo.create_workflow(
        workflow_key="health:succeeded:batch",
        workflow_kind="health_check",
        trigger_kind="scheduled",
        started_at_utc=NOW + timedelta(seconds=3),
    )
    success = repo.transition_workflow(
        success.workflow_key,
        "succeeded",
        at_utc=NOW + timedelta(seconds=4),
    )

    recovered = repo.resolve_retryable_workflow_failures(
        success.workflow_key, at_utc=NOW + timedelta(seconds=5)
    )

    assert len(recovered) == 205
    assert all(item.state == "resolved" for item in recovered)


def test_short_transactions_rollback_and_other_layer_tables_remain_unchanged(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    with sqlite3.connect(db_path) as conn:
        before = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("garmin_sync_runs", "analysis_runs", "mail_agent_runs", "analysis_deliveries", "mail_deliveries")}
    run = workflow(repo)
    with pytest.raises(OrchestrationRepositoryError, match="reference_invalid"):
        repo.record_incident(incident_key="bad-ref", category="database", severity="error", seen_at_utc=NOW, related_step_id=999999)
    assert repo.get_incident("bad-ref") is None
    health_id = repo.record_health_check(
        check_kind="sqlite", target_kind="database", status="ready",
        checked_at_utc=NOW,
        metrics={"connections": 1, "wal_enabled": True, "load_ratio": 0.25},
    )
    with sqlite3.connect(db_path) as conn:
        after = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in before}
        assert after == before
        assert conn.execute("SELECT count(*) FROM orchestrator_runs WHERE workflow_key=?", (run.workflow_key,)).fetchone()[0] == 1
        metrics = json.loads(conn.execute(
            "SELECT metrics_json FROM service_health_checks WHERE id=?",
            (health_id,),
        ).fetchone()[0])
        assert metrics == {
            "connections": 1, "load_ratio": 0.25, "wal_enabled": True,
        }
    with pytest.raises(OrchestrationRepositoryError, match="metrics_invalid"):
        repo.record_health_check(
            check_kind="sqlite", target_kind="database", status="ready",
            checked_at_utc=NOW, metrics={"load_ratio": float("nan")},
        )


def test_read_only_recovery_queries_do_not_commit_writes(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path); run = workflow(repo)
    incident = repo.record_incident(incident_key="sqlite:busy", category="database", severity="warning", seen_at_utc=NOW)
    with sqlite3.connect(db_path) as observer:
        before = observer.execute("PRAGMA data_version").fetchone()[0]
        assert repo.get_workflow(run.workflow_key) == run
        assert repo.get_incident(incident.incident_key) == incident
        assert repo.recent_workflows() == (run,) and repo.open_incidents() == (incident,)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before


def test_recovery_dtos_expose_complete_audit_state_without_bare_sql(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path)
    projection = SchedulerJobProjection("morning", "morning", "Asia/Hong_Kong", "daily_at", NOW, "2026-07-23", None, None, "own_incremental", timedelta(hours=12), HASH)
    job = repo.upsert_scheduler_job(projection, is_enabled=True, updated_at_utc=NOW)
    run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="collect", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH, invocation_id="invoke_1", downstream_run_id="run_1")
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    step = repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="succeeded", at_utc=NOW, receipt_sha256="b" * 64, controlled_counts={"fetched": 1})
    incident = repo.record_incident(incident_key="sqlite:busy", category="database", severity="warning", seen_at_utc=NOW, related_workflow_run_id=run.id, related_step_id=step.id, error_code="busy", error_summary="busy", next_action="retry")
    alert = repo.create_alert_delivery(incident_key=incident.incident_key, idempotency_key="ops:busy")
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO scheduler_leases (lease_key,owner_instance_id,owner_pid,acquired_at_utc,heartbeat_at_utc,expires_at_utc) VALUES (?,?,?,?,?,?)", ("supervisor", "instance_1", 123, "2026-07-23T00:00:00Z", "2026-07-23T00:00:01Z", "2026-07-23T00:01:00Z")); conn.commit()
    lease = repo.get_scheduler_lease("supervisor")
    assert job.timezone == "Asia/Hong_Kong" and job.schedule_spec_json and job.is_enabled and job.misfire_policy and job.updated_at_utc
    assert run.trigger_kind == "scheduled" and run.result_summary_json and step.layer_no == 2 and step.tool_mode == "incremental" and step.invocation_id == "invoke_1" and step.downstream_run_id == "run_1" and step.next_retry_at_utc is None
    assert incident.category == "database" and incident.related_step_id == step.id and incident.error_code == "busy" and alert.operational_incident_id == incident.id and alert.provider_message_id is None
    assert lease is not None and lease.owner_pid == 123 and lease.acquired_at_utc and lease.heartbeat_at_utc and lease.expires_at_utc


def test_step_summary_merges_and_same_status_is_strict_noop(tmp_path: Path) -> None:
    repo, db_path = repository(tmp_path); run = workflow(repo)
    for key, ordinal, receipt, count in (("one", 0, "b" * 64, 1), ("two", 1, "c" * 64, 2)):
        repo.create_step(workflow_key=run.workflow_key, step_key=key, ordinal=ordinal, layer_no=2, tool_mode="incremental", request_sha256=HASH)
        repo.transition_step(workflow_key=run.workflow_key, step_key=key, status="running", at_utc=NOW)
        repo.transition_step(workflow_key=run.workflow_key, step_key=key, status="succeeded", at_utc=NOW, receipt_sha256=receipt, controlled_counts={"fetched": count})
    before = repo.get_workflow(run.workflow_key); assert before is not None
    parsed = json.loads(before.result_summary_json); assert parsed["schema_version"] == "step_summary_v2" and set(parsed["steps"]) == {"one", "two"}
    with sqlite3.connect(db_path) as observer:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        assert repo.transition_workflow(run.workflow_key, "started", at_utc=NOW) == before
        with pytest.raises(OrchestrationRepositoryError, match="same_status_conflict"):
            repo.transition_step(workflow_key=run.workflow_key, step_key="one", status="succeeded", at_utc=NOW, receipt_sha256="d" * 64, controlled_counts={"fetched": 999})
        assert observer.execute("PRAGMA data_version").fetchone()[0] == version
    assert repo.get_workflow(run.workflow_key) == before


def test_no_receipt_evidence_reopen_alert_conflict_and_stable_order(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo)
    failed = repo.create_step(workflow_key=run.workflow_key, step_key="check", ordinal=0, layer_no=1, tool_mode="verify", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key=failed.step_key, status="running", at_utc=NOW)
    with pytest.raises(OrchestrationRepositoryError, match="payload_invalid"):
        repo.transition_step(workflow_key=run.workflow_key, step_key=failed.step_key, status="failed", at_utc=NOW)
    failed = repo.transition_step(workflow_key=run.workflow_key, step_key=failed.step_key, status="failed", at_utc=NOW, evidence_code="deterministic_check")
    assert failed.receipt_sha256 is None
    one = repo.record_incident(incident_key="database:busy", category="database", severity="warning", seen_at_utc=NOW)
    repo.transition_incident(one.incident_key, "resolved", at_utc=NOW)
    reopened = repo.record_incident(incident_key=one.incident_key, category="database", severity="error", seen_at_utc=NOW + timedelta(seconds=1))
    assert reopened.state == "open" and reopened.resolved_at_utc is None and reopened.occurrence_count == 2 and reopened.severity == "error"
    repo.record_incident(incident_key="database:other", category="database", severity="error", seen_at_utc=NOW)
    repo.create_alert_delivery(incident_key=one.incident_key, idempotency_key="ops:shared")
    with pytest.raises(OrchestrationRepositoryError, match="idempotency_conflict"):
        repo.create_alert_delivery(incident_key="database:other", idempotency_key="ops:shared")
    later = workflow(repo, "morning:later"); assert [item.workflow_key for item in repo.recent_workflows()] == [later.workflow_key, run.workflow_key]


@pytest.mark.parametrize("bad", ["a" * 128, "user@example.com", "72,130,98", "5L2g5aW977yM6YKu5Lu25q2j5paH"])
def test_controlled_serializers_reject_payload_lookalikes(tmp_path: Path, bad: str) -> None:
    repo, _ = repository(tmp_path)
    with pytest.raises(OrchestrationRepositoryError, match="controlled_code_invalid"):
        repo.record_incident(incident_key="payload", category="database", severity="error", seen_at_utc=NOW, error_summary=bad)


def test_attempt_history_deferred_recovery_and_incident_monotonic_identity(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo)
    step = repo.create_step(workflow_key=run.workflow_key, step_key="collect", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="running", at_utc=NOW)
    repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="deferred", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64, controlled_counts={"deferred": 1}, next_retry_at_utc=NOW + timedelta(seconds=2))
    repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="running", at_utc=NOW + timedelta(seconds=2))
    repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="deferred", at_utc=NOW + timedelta(seconds=3), receipt_sha256="c" * 64, controlled_counts={"deferred": 2}, next_retry_at_utc=NOW + timedelta(seconds=4))
    repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="running", at_utc=NOW + timedelta(seconds=4))
    done = repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="succeeded", at_utc=NOW + timedelta(seconds=5), receipt_sha256="d" * 64, controlled_counts={"fetched": 3})
    assert done.attempt_count == 3 and done.next_retry_at_utc is None
    restored = json.loads(repo.get_workflow(run.workflow_key).result_summary_json)["steps"]["collect"]["events"]
    assert [event["status"] for event in restored] == ["running", "deferred", "running", "deferred", "running", "succeeded"]
    incident = repo.record_incident(incident_key="database:busy", category="database", severity="warning", seen_at_utc=NOW + timedelta(seconds=5), related_workflow_run_id=run.id, error_code="busy", error_summary="busy", next_action="retry")
    duplicate = repo.record_incident(incident_key="database:busy", category="database", severity="info", seen_at_utc=NOW, related_workflow_run_id=run.id)
    assert duplicate.last_seen_at_utc == incident.last_seen_at_utc and duplicate.error_code == "busy" and duplicate.severity == "warning"
    with pytest.raises(OrchestrationRepositoryError, match="identity_conflict"):
        repo.record_incident(incident_key="database:busy", category="provider", severity="error", seen_at_utc=NOW + timedelta(seconds=6), related_workflow_run_id=run.id)


@pytest.mark.parametrize("sql", [
    "UPDATE orchestrator_runs SET status='unknown'",
    "UPDATE orchestrator_runs SET completed_at_utc='2026-07-23T00:00:00Z'",
    "UPDATE orchestrator_runs SET status='succeeded',completed_at_utc=NULL",
    "UPDATE orchestrator_runs SET status='succeeded',completed_at_utc='2026-07-22T00:00:00Z'",
    "UPDATE orchestrator_runs SET status='partial',completed_at_utc=NULL",
    "UPDATE orchestrator_runs SET status='failed',completed_at_utc=NULL",
    "UPDATE orchestrator_runs SET status='deferred',completed_at_utc=NULL",
    "UPDATE orchestrator_runs SET status='cancelled',completed_at_utc=NULL",
    "UPDATE orchestrator_runs SET deadline_at_utc='not-a-date'",
    "UPDATE orchestrator_runs SET deadline_at_utc='2026-07-22T00:00:00Z'",
])
def test_direct_sql_corrupt_run_fails_closed_everywhere(tmp_path: Path, sql: str) -> None:
    repo, db = repository(tmp_path); run = workflow(repo)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON"); conn.execute(sql); conn.commit()
    for call in (lambda: repo.get_workflow(run.workflow_key), lambda: repo.recent_workflows(), lambda: repo.create_step(workflow_key=run.workflow_key, step_key="x", ordinal=0, layer_no=2, tool_mode="verify", request_sha256=HASH)):
        with pytest.raises(OrchestrationRepositoryError): call()


def test_direct_sql_corrupt_step_summary_fails_closed(tmp_path: Path) -> None:
    repo, db = repository(tmp_path); run = workflow(repo)
    step = repo.create_step(workflow_key=run.workflow_key, step_key="collect", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="deferred", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64, next_retry_at_utc=NOW + timedelta(seconds=2))
    with sqlite3.connect(db) as conn:
        bad = json.loads(conn.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run.id,)).fetchone()[0]); bad["steps"]["collect"]["events"][-1]["next_retry_at_utc"] = None
        conn.execute("UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?", (json.dumps(bad), run.id)); conn.commit()
    for call in (lambda: repo.get_workflow(run.workflow_key), lambda: repo.get_step(run.workflow_key, "collect"), lambda: repo.transition_step(workflow_key=run.workflow_key, step_key="collect", status="running", at_utc=NOW + timedelta(seconds=2))):
        with pytest.raises(OrchestrationRepositoryError): call()


def _corrupt_step(tmp_path: Path, mutate) -> tuple[OrchestrationRepository, str, str]:
    repo, db = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="collect", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="deferred", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64, next_retry_at_utc=NOW + timedelta(seconds=2))
    with sqlite3.connect(db) as conn: conn.execute("PRAGMA ignore_check_constraints=ON"); mutate(conn, run.id, step.id); conn.commit()
    return repo, run.workflow_key, step.step_key


@pytest.mark.parametrize("mutate", [
    lambda c,r,s: c.execute("UPDATE orchestrator_steps SET started_at_utc='2026-07-23T00:00:01Z' WHERE id=?", (s,)),
    lambda c,r,s: c.execute("UPDATE orchestrator_steps SET completed_at_utc='2026-07-23T00:00:01Z' WHERE id=?", (s,)),
    lambda c,r,s: c.execute("UPDATE orchestrator_runs SET result_summary_json=json_set(result_summary_json,'$.steps.unknown',json('{\"events\":[]}')) WHERE id=?", (r,)),
    lambda c,r,s: c.execute("UPDATE orchestrator_runs SET result_summary_json='{" + '"schema_version":"step_summary_v2","steps":{}' + "}' WHERE id=?", (r,)),
])
def test_direct_sql_step_matrix_fails_all_public_paths(tmp_path: Path, mutate) -> None:
    repo, key, step = _corrupt_step(tmp_path, mutate)
    for call in (lambda: repo.get_workflow(key), lambda: repo.recent_workflows(), lambda: repo.get_step(key, step), lambda: repo.create_step(workflow_key=key, step_key="other", ordinal=1, layer_no=2, tool_mode="verify", request_sha256=HASH), lambda: repo.transition_step(workflow_key=key, step_key=step, status="running", at_utc=NOW + timedelta(seconds=2))):
        with pytest.raises(OrchestrationRepositoryError): call()


@pytest.mark.parametrize("column,value", [
    ("status", "'succeeded'"), ("attempt_count", "99"), ("receipt_sha256", "'a'"),
    ("next_retry_at_utc", "NULL"), ("started_at_utc", "'2026-07-23T00:00:01Z'"),
    ("completed_at_utc", "'2026-07-23T00:00:01Z'"),
])
def test_direct_sql_row_tail_columns_fail_closed(tmp_path: Path, column: str, value: str) -> None:
    repo, key, step = _corrupt_step(tmp_path, lambda c,r,s: c.execute(f"UPDATE orchestrator_steps SET {column}={value} WHERE id=?", (s,)))
    for call in (lambda: repo.get_workflow(key), lambda: repo.recent_workflows(), lambda: repo.get_step(key, step), lambda: repo.create_step(workflow_key=key, step_key="other", ordinal=1, layer_no=2, tool_mode="verify", request_sha256=HASH), lambda: repo.transition_step(workflow_key=key, step_key=step, status="running", at_utc=NOW + timedelta(seconds=2))):
        with pytest.raises(OrchestrationRepositoryError): call()


def test_pending_step_summary_entry_survives_restart_read(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo)
    step = repo.create_step(workflow_key=run.workflow_key, step_key="pending", ordinal=0, layer_no=1, tool_mode="verify", request_sha256=HASH)
    assert repo.get_workflow(run.workflow_key) is not None and repo.get_step(run.workflow_key, step.step_key) == step


def test_pending_skipped_is_restart_readable_and_invalid_payload_rolls_back(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo)
    step = repo.create_step(workflow_key=run.workflow_key, step_key="check", ordinal=0, layer_no=1, tool_mode="verify", request_sha256=HASH)
    skipped = repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="skipped", at_utc=NOW, evidence_code="deterministic_check")
    assert skipped.started_at_utc is None and skipped.completed_at_utc == "2026-07-23T00:00:00Z" and repo.get_step(run.workflow_key, step.step_key) == skipped
    run2 = workflow(repo, "morning:two"); step2 = repo.create_step(workflow_key=run2.workflow_key, step_key="run", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run2.workflow_key, step_key=step2.step_key, status="running", at_utc=NOW)
    with pytest.raises(OrchestrationRepositoryError, match="payload_invalid"):
        repo.transition_step(workflow_key=run2.workflow_key, step_key=step2.step_key, status="succeeded", at_utc=NOW, receipt_sha256="b" * 64, evidence_code="deterministic_check")
    assert repo.get_step(run2.workflow_key, step2.step_key).status == "running"


@pytest.mark.parametrize("status,kwargs", [
    ("running", {"receipt_sha256": "b" * 64}), ("running", {"evidence_code": "deterministic_check"}),
    ("running", {"next_retry_at_utc": NOW + timedelta(seconds=2)}),
    ("succeeded", {}), ("succeeded", {"receipt_sha256": "b" * 64, "evidence_code": "deterministic_check"}),
    ("succeeded", {"receipt_sha256": "b" * 64, "next_retry_at_utc": NOW + timedelta(seconds=2)}),
    ("failed", {}), ("skipped", {"next_retry_at_utc": NOW + timedelta(seconds=2)}),
    ("failed", {"receipt_sha256": "b" * 64, "evidence_code": "deterministic_check"}),
    ("skipped", {"receipt_sha256": "b" * 64, "evidence_code": "deterministic_check"}),
    ("skipped", {"evidence_code": "receipt_received"}),
    ("deferred", {"receipt_sha256": "b" * 64}), ("deferred", {"evidence_code": "receipt_received"}),
    ("deferred", {"receipt_sha256": "b" * 64, "evidence_code": "deterministic_check", "next_retry_at_utc": NOW + timedelta(seconds=2)}),
    ("deferred", {"next_retry_at_utc": NOW}), ("deferred", {}),
])
def test_payload_truth_table_rejects_without_write(tmp_path: Path, status: str, kwargs: dict) -> None:
    repo, db = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="x", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key="x", status="running", at_utc=NOW)
    before = repo.get_step(run.workflow_key, "x")
    with sqlite3.connect(db) as observer:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        with pytest.raises(OrchestrationRepositoryError): repo.transition_step(workflow_key=run.workflow_key, step_key="x", status=status, at_utc=NOW + timedelta(seconds=1), **kwargs)
        assert observer.execute("PRAGMA data_version").fetchone()[0] == version
    assert repo.get_step(run.workflow_key, "x") == before


def _e1_state(tmp_path: Path, state: str):
    repo, db = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="e1", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    if state != "pending": repo.transition_step(workflow_key=run.workflow_key, step_key="e1", status="running", at_utc=NOW)
    if state == "deferred": repo.transition_step(workflow_key=run.workflow_key, step_key="e1", status="deferred", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64, next_retry_at_utc=NOW + timedelta(seconds=2))
    if state == "succeeded": repo.transition_step(workflow_key=run.workflow_key, step_key="e1", status="succeeded", at_utc=NOW + timedelta(seconds=1), receipt_sha256="b" * 64)
    if state == "failed": repo.transition_step(workflow_key=run.workflow_key, step_key="e1", status="failed", at_utc=NOW + timedelta(seconds=1), evidence_code="deterministic_check")
    if state == "skipped":
        repo = OrchestrationRepository(db); run = repo.get_workflow(run.workflow_key); step = repo.get_step(run.workflow_key, "e1")
    return repo, db, run.workflow_key, step.id


def _e1_summary_mutation(conn, run_id: int, mutate) -> None:
    payload = json.loads(conn.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run_id,)).fetchone()[0]); mutate(payload["steps"]["e1"]["events"][-1]); conn.execute("UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?", (json.dumps(payload), run_id))


@pytest.mark.parametrize("case_id,state,mutation", [
    ("E1-01-row-status", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET status='running' WHERE id=?", (s,))),
    ("E1-02-row-attempt", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET attempt_count=9 WHERE id=?", (s,))),
    ("E1-03-row-receipt", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET receipt_sha256=? WHERE id=?", ("c" * 64, s))),
    ("E1-04-row-retry", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET next_retry_at_utc=NULL WHERE id=?", (s,))),
    ("E1-05-row-start", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET started_at_utc='2026-07-23T00:00:01Z' WHERE id=?", (s,))),
    ("E1-06-running-completed", "running", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET completed_at_utc='2026-07-23T00:00:00Z' WHERE id=?", (s,))),
    ("E1-07-deferred-completed", "deferred", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET completed_at_utc='2026-07-23T00:00:01Z' WHERE id=?", (s,))),
    ("E1-08-succeeded-null-complete", "succeeded", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET completed_at_utc=NULL WHERE id=?", (s,))),
    ("E1-09-failed-null-complete", "failed", lambda c,r,s: c.execute("UPDATE orchestrator_steps SET completed_at_utc=NULL WHERE id=?", (s,))),
    ("E1-10-tail-status", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(status="running"))),
    ("E1-11-tail-attempt", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(attempt=7))),
    ("E1-12-tail-receipt", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(receipt_sha256="c"*64))),
    ("E1-13-tail-evidence", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(evidence_code="deterministic_check"))),
    ("E1-14-tail-retry-past", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(next_retry_at_utc="2026-07-23T00:00:01Z"))),
    ("E1-15-tail-time", "deferred", lambda c,r,s: _e1_summary_mutation(c,r,lambda e:e.update(at_utc="bad"))),
])
def test_e1_step_sql_consistency_matrix(tmp_path: Path, case_id: str, state: str, mutation) -> None:
    repo, db, key, step_id = _e1_state(tmp_path, state)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON"); run_id = conn.execute("SELECT id FROM orchestrator_runs WHERE workflow_key=?", (key,)).fetchone()[0]; mutation(conn, run_id, step_id); conn.commit()
    observer = sqlite3.connect(db)
    try:
        before_version = observer.execute("PRAGMA data_version").fetchone()[0]
        before_counts = tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs", "orchestrator_steps"))
        before_summary = observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run_id,)).fetchone()[0]
        before_row = observer.execute("SELECT * FROM orchestrator_steps WHERE id=?", (step_id,)).fetchone()
        for call in (lambda: repo.get_workflow(key), lambda: repo.recent_workflows(), lambda: repo.get_step(key, "e1"), lambda: repo.create_step(workflow_key=key, step_key="new", ordinal=1, layer_no=2, tool_mode="verify", request_sha256=HASH), lambda: repo.transition_step(workflow_key=key, step_key="e1", status="running", at_utc=NOW + timedelta(seconds=3))):
            with pytest.raises(OrchestrationRepositoryError): call()
            assert observer.execute("PRAGMA data_version").fetchone()[0] == before_version
            assert tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs", "orchestrator_steps")) == before_counts
            assert observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run_id,)).fetchone()[0] == before_summary
            assert observer.execute("SELECT * FROM orchestrator_steps WHERE id=?", (step_id,)).fetchone() == before_row
    finally:
        observer.close()


_E2A_BAD = [("none",None),("int",7),("list",[]),("text","bad"),("naive",datetime(2026,7,23))]
_E2A_ENTRIES = ["create_start","create_deadline","workflow_at","step_at","step_retry"]
_E2A_CASES = [(entry, f"E2A-{entry}-{kind}", bad) for entry in _E2A_ENTRIES for kind,bad in _E2A_BAD if not (bad is None and entry in {"create_deadline", "step_retry"})]
@pytest.mark.parametrize("entry,case_id,bad", _E2A_CASES, ids=[item[1] for item in _E2A_CASES])
def test_e2a_public_timestamp_matrix(tmp_path: Path, entry: str, case_id: str, bad) -> None:
    repo, db = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="e2a", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    if entry == "step_retry": repo.transition_step(workflow_key=run.workflow_key, step_key="e2a", status="running", at_utc=NOW)
    observer = sqlite3.connect(db)
    try:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        counts = tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs","orchestrator_steps"))
        summary = observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run.id,)).fetchone()[0]
        row = observer.execute("SELECT * FROM orchestrator_steps WHERE id=?", (step.id,)).fetchone()
        if entry == "create_start": call = lambda: repo.create_workflow(workflow_key="e2a:"+case_id, workflow_kind="morning", trigger_kind="manual", started_at_utc=bad)
        elif entry == "create_deadline": call = lambda: repo.create_workflow(workflow_key="e2a:"+case_id, workflow_kind="morning", trigger_kind="manual", started_at_utc=NOW, deadline_at_utc=bad)
        elif entry == "workflow_at": call = lambda: repo.transition_workflow(run.workflow_key,"succeeded",at_utc=bad)
        elif entry == "step_at": call = lambda: repo.transition_step(workflow_key=run.workflow_key,step_key="e2a",status="running",at_utc=bad)
        else: call = lambda: repo.transition_step(workflow_key=run.workflow_key,step_key="e2a",status="deferred",at_utc=NOW+timedelta(seconds=1),next_retry_at_utc=bad,evidence_code="deterministic_check")
        with pytest.raises(OrchestrationRepositoryError, match="timestamp"): call()
        assert observer.execute("PRAGMA data_version").fetchone()[0] == version
        assert tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs","orchestrator_steps")) == counts
        assert observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run.id,)).fetchone()[0] == summary
        assert observer.execute("SELECT * FROM orchestrator_steps WHERE id=?", (step.id,)).fetchone() == row
    finally: observer.close()


def test_e2a_deadline_none_is_explicitly_legal(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    saved = repo.create_workflow(workflow_key="e2a:deadline-none", workflow_kind="morning", trigger_kind="manual", started_at_utc=NOW, deadline_at_utc=None)
    assert saved.deadline_at_utc is None and repo.get_workflow(saved.workflow_key) == saved


def test_e2a_deferred_none_with_evidence_is_explicitly_legal(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="deferred-none", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="running", at_utc=NOW)
    saved = repo.transition_step(workflow_key=run.workflow_key, step_key=step.step_key, status="deferred", at_utc=NOW + timedelta(seconds=1), evidence_code="deterministic_check")
    assert saved.status == "deferred" and saved.next_retry_at_utc is None and repo.get_step(run.workflow_key, step.step_key) == saved


@pytest.mark.parametrize("case_id", ["E2A-26-offset-start","E2A-27-offset-deadline","E2A-28-offset-step"])
def test_e2a_aware_offset_normalizes_to_z(tmp_path: Path, case_id: str) -> None:
    from datetime import timezone
    offset = datetime(2026,7,23,8,0,tzinfo=timezone(timedelta(hours=8)))
    repo, _ = repository(tmp_path)
    if case_id.endswith("start"):
        run = repo.create_workflow(workflow_key="offset:start",workflow_kind="morning",trigger_kind="manual",started_at_utc=offset); assert run.started_at_utc == "2026-07-23T00:00:00Z"
    elif case_id.endswith("deadline"):
        run = repo.create_workflow(workflow_key="offset:deadline",workflow_kind="morning",trigger_kind="manual",started_at_utc=NOW,deadline_at_utc=offset); assert run.deadline_at_utc == "2026-07-23T00:00:00Z"
    else:
        run=workflow(repo); step=repo.create_step(workflow_key=run.workflow_key,step_key="offset",ordinal=0,layer_no=2,tool_mode="incremental",request_sha256=HASH); saved=repo.transition_step(workflow_key=run.workflow_key,step_key="offset",status="running",at_utc=offset); assert saved.started_at_utc == "2026-07-23T00:00:00Z"


_E2B_VALUES = [("int", 7), ("blob", sqlite3.Binary(b"x")), ("invalid", "bad"), ("naive", "2026-07-23T00:00:00"), ("offset", "2026-07-23T08:00:00+08:00"), ("noncanonical", "2026-07-23T00:00:00.0000000Z")]
_E2B_CASES = [(f"E2B-started-{kind}", "started_at_utc", value, False) for kind,value in _E2B_VALUES] + [(f"E2B-deadline-{kind}", "deadline_at_utc", value, False) for kind,value in _E2B_VALUES] + [(f"E2B-completed-{kind}", "completed_at_utc", value, True) for kind,value in _E2B_VALUES] + [("E2B-completed-null", "completed_at_utc", None, True)]
@pytest.mark.parametrize("case_id,column,value,terminal", _E2B_CASES, ids=[item[0] for item in _E2B_CASES])
def test_e2b_run_time_sql_pollution_fails_closed(tmp_path: Path, case_id: str, column: str, value, terminal: bool) -> None:
    repo, db = repository(tmp_path); run = workflow(repo)
    if terminal: repo.transition_workflow(run.workflow_key, "succeeded", at_utc=NOW + timedelta(seconds=1))
    with sqlite3.connect(db) as mutator:
        mutator.execute("PRAGMA ignore_check_constraints=ON"); mutator.execute(f"UPDATE orchestrator_runs SET {column}=? WHERE id=?", (value, run.id)); mutator.commit()
    observer = sqlite3.connect(db)
    try:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        counts = tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs", "orchestrator_steps"))
        summary = observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run.id,)).fetchone()[0]
        for call in (lambda: repo.get_workflow(run.workflow_key), lambda: repo.recent_workflows(), lambda: repo.create_step(workflow_key=run.workflow_key, step_key="new", ordinal=0, layer_no=1, tool_mode="verify", request_sha256=HASH), lambda: repo.transition_workflow(run.workflow_key, "failed", at_utc=NOW + timedelta(seconds=2))):
            with pytest.raises(OrchestrationRepositoryError): call()
            assert observer.execute("PRAGMA data_version").fetchone()[0] == version
            assert tuple(observer.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("orchestrator_runs", "orchestrator_steps")) == counts
            assert observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run.id,)).fetchone()[0] == summary
    finally: observer.close()


def test_e2b_legal_null_deadline_and_canonical_z_survive(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path); run = repo.create_workflow(workflow_key="e2b:legal", workflow_kind="morning", trigger_kind="manual", started_at_utc=NOW, deadline_at_utc=None)
    assert repo.get_workflow(run.workflow_key).deadline_at_utc is None


_E2C_VALUES = [("int",7),("blob",sqlite3.Binary(b"x")),("invalid","bad"),("naive","2026-07-23T00:00:00"),("offset","2026-07-23T08:00:00+08:00"),("noncanonical","2026-07-23T00:00:00.0000000Z")]
_E2C_CASES = [(f"E2C-row-{field}-{kind}", "row", field, value) for field in ("started_at_utc","completed_at_utc","next_retry_at_utc") for kind,value in _E2C_VALUES] + [(f"E2C-event-{field}-{kind}", "event", field, value) for field in ("at_utc","next_retry_at_utc") for kind,value in _E2C_VALUES] + [("E2C-row-deferred-completed", "row", "completed_at_utc", "2026-07-23T00:00:01Z"), ("E2C-event-retry-null", "event", "next_retry_at_utc", None)]
@pytest.mark.parametrize("case_id,target,field,value", _E2C_CASES, ids=[item[0] for item in _E2C_CASES])
def test_e2c_step_and_event_time_sql_pollution(tmp_path: Path, case_id: str, target: str, field: str, value) -> None:
    repo, db = repository(tmp_path); run = workflow(repo); step = repo.create_step(workflow_key=run.workflow_key, step_key="e2c", ordinal=0, layer_no=2, tool_mode="incremental", request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key, step_key="e2c", status="running", at_utc=NOW)
    repo.transition_step(workflow_key=run.workflow_key, step_key="e2c", status="deferred", at_utc=NOW+timedelta(seconds=1), receipt_sha256="b"*64, next_retry_at_utc=NOW+timedelta(seconds=2))
    with sqlite3.connect(db) as mutator:
        mutator.execute("PRAGMA ignore_check_constraints=ON")
        if target == "row": mutator.execute(f"UPDATE orchestrator_steps SET {field}=? WHERE id=?", (value,step.id))
        else:
            payload=json.loads(mutator.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?",(run.id,)).fetchone()[0]); payload["steps"]["e2c"]["events"][-1][field]=(["blob"] if isinstance(value, memoryview) else value); mutator.execute("UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",(json.dumps(payload),run.id))
        mutator.commit()
    observer=sqlite3.connect(db)
    try:
        version=observer.execute("PRAGMA data_version").fetchone()[0]; counts=tuple(observer.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("orchestrator_runs","orchestrator_steps")); summary=observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?",(run.id,)).fetchone()[0]; row=observer.execute("SELECT * FROM orchestrator_steps WHERE id=?",(step.id,)).fetchone()
        for call in (lambda:repo.get_workflow(run.workflow_key),lambda:repo.recent_workflows(),lambda:repo.get_step(run.workflow_key,"e2c"),lambda:repo.create_step(workflow_key=run.workflow_key,step_key="new",ordinal=1,layer_no=1,tool_mode="verify",request_sha256=HASH),lambda:repo.transition_step(workflow_key=run.workflow_key,step_key="e2c",status="running",at_utc=NOW+timedelta(seconds=2))):
            with pytest.raises(OrchestrationRepositoryError): call()
            assert observer.execute("PRAGMA data_version").fetchone()[0]==version and tuple(observer.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("orchestrator_runs","orchestrator_steps"))==counts and observer.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?",(run.id,)).fetchone()[0]==summary and observer.execute("SELECT * FROM orchestrator_steps WHERE id=?",(step.id,)).fetchone()==row
    finally: observer.close()


@pytest.mark.parametrize("case_id,kind", [("E2C2-01-retry-equal","retry_equal"),("E2C2-02-retry-before","retry_before"),("E2C2-03-terminal-before-start","terminal_before"),("E2C2-04-event-backwards","event_backwards"),("E2C2-05-start-after-event","start_after")])
def test_e2c2_joint_step_time_semantics(tmp_path: Path, case_id: str, kind: str) -> None:
    repo, db = repository(tmp_path); run=workflow(repo); step=repo.create_step(workflow_key=run.workflow_key,step_key="joint",ordinal=0,layer_no=2,tool_mode="incremental",request_sha256=HASH)
    repo.transition_step(workflow_key=run.workflow_key,step_key="joint",status="running",at_utc=NOW)
    repo.transition_step(workflow_key=run.workflow_key,step_key="joint",status="deferred",at_utc=NOW+timedelta(seconds=1),receipt_sha256="b"*64,next_retry_at_utc=NOW+timedelta(seconds=2))
    with sqlite3.connect(db) as c:
        p=json.loads(c.execute("SELECT result_summary_json FROM orchestrator_runs WHERE id=?",(run.id,)).fetchone()[0]); ev=p["steps"]["joint"]["events"]
        if kind.startswith("retry"):
            value="2026-07-23T00:00:01Z" if kind.endswith("equal") else "2026-07-23T00:00:00Z"; ev[-1]["next_retry_at_utc"]=value; c.execute("UPDATE orchestrator_steps SET next_retry_at_utc=? WHERE id=?",(value,step.id))
        elif kind=="event_backwards": ev[-1]["at_utc"]="2026-07-22T23:59:59Z"; c.execute("UPDATE orchestrator_steps SET next_retry_at_utc='2026-07-23T00:00:02Z' WHERE id=?",(step.id,))
        elif kind=="start_after": ev[0]["at_utc"]="2026-07-23T00:00:02Z"; c.execute("UPDATE orchestrator_steps SET started_at_utc='2026-07-23T00:00:02Z' WHERE id=?",(step.id,))
        else:
            ev[-1]["status"]="succeeded"; ev[-1]["at_utc"]="2026-07-22T23:59:59Z"; ev[-1]["next_retry_at_utc"]=None; c.execute("UPDATE orchestrator_steps SET status='succeeded',completed_at_utc='2026-07-22T23:59:59Z',next_retry_at_utc=NULL WHERE id=?",(step.id,))
        c.execute("UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",(json.dumps(p),run.id)); c.commit()
    observer=sqlite3.connect(db)
    try:
        version=observer.execute("PRAGMA data_version").fetchone()[0]
        for call in (lambda:repo.get_workflow(run.workflow_key),lambda:repo.recent_workflows(),lambda:repo.get_step(run.workflow_key,"joint"),lambda:repo.transition_step(workflow_key=run.workflow_key,step_key="joint",status="running",at_utc=NOW+timedelta(seconds=3))):
            with pytest.raises(OrchestrationRepositoryError): call()
            assert observer.execute("PRAGMA data_version").fetchone()[0]==version
    finally: observer.close()


@pytest.mark.parametrize("case_id,column", [("E2C2-06-run-completed-before","completed_at_utc"),("E2C2-07-run-deadline-before","deadline_at_utc")])
def test_e2c2_joint_run_time_semantics(tmp_path: Path, case_id: str, column: str) -> None:
    repo,db=repository(tmp_path); run=workflow(repo)
    if column=="completed_at_utc": repo.transition_workflow(run.workflow_key,"succeeded",at_utc=NOW+timedelta(seconds=1))
    with sqlite3.connect(db) as c: c.execute("UPDATE orchestrator_runs SET %s='2026-07-22T23:59:59Z' WHERE id=?" % column,(run.id,)); c.commit()
    with pytest.raises(OrchestrationRepositoryError): repo.get_workflow(run.workflow_key)
