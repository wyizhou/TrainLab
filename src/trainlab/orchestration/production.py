"""Production composition root for the fifth-layer CLI and Supervisor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.gmail_environment import inspect_gmail_environment
from trainlab.util import project_root

from .analysis_workflows import MorningWorkflowService, SundayWorkflowService
from .application import OrchestrationTool
from .contracts import WorkflowRequest, verify_frozen_contracts
from .due_scheduler import DueItem, DueQueueService
from .lease import LeaseManager, Supervisor
from .mail_workflow import MailWorkflow, SqlitePlanRevisionResolver
from .incident_alerts import OperationalAlertService
from .operational_gmail import CurrentEnvironmentOperationalGmail
from .operations import OperatorOperations
from .persistence_adapter import RepositoryReceiptStore, SqliteSubjectProjection
from .recovery_planner import RecoveryContext, plan_recovery
from .repository import OrchestrationRepository
from .scheduling_config import (
    OrchestrationConfigLoader,
    SchedulingProjectionService,
)
from .subprocess_runner import SubprocessRunner
from .supervisor import (
    BusinessIncidentEvents,
    SupervisorRuntime,
    SystemdNotifier,
)
from .workflow_incidents import WorkflowIncidentCoordinator


_SG = ZoneInfo("Asia/Singapore")
_CONFIG = Path("config/orchestration.yaml")
_RECIPIENT = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _ProcessProbe:
    def is_absent(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except (OSError, PermissionError):
            return False
        return False


class ProductionOrchestrationApplication:
    """Fixed-path composition; no public method accepts config or executable paths."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = project_root(root)

    def _components(self):
        verify_frozen_contracts(self._root)
        foundation = FoundationConfig.load(self._root)
        config = OrchestrationConfigLoader(self._root).load(_CONFIG)
        repository = OrchestrationRepository(foundation.database_path)
        subjects = SqliteSubjectProjection(foundation.database_path)
        return foundation, config, repository, subjects

    @staticmethod
    def _active_subject(database_path: Path) -> tuple[int, str]:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT id,subject_key FROM data_subjects WHERE is_active=1 ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        if len(rows) != 1 or not isinstance(rows[0][1], str):
            raise ValueError("orchestration_active_subject_not_unique")
        return int(rows[0][0]), rows[0][1]

    def _configured_recipient(self) -> str:
        try:
            value = json.loads(
                (self._root / "config/trainlab.json").read_text(
                    encoding="utf-8"
                )
            )
            recipient = value["mail"]["recipient_email"]
        except (OSError, TypeError, ValueError, KeyError):
            raise ValueError(
                "orchestration_alert_configuration_invalid"
            ) from None
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("mail"), dict)
            or not isinstance(recipient, str)
            or recipient != recipient.strip()
            or _RECIPIENT.fullmatch(recipient) is None
        ):
            raise ValueError("orchestration_alert_configuration_invalid")
        return recipient.lower()

    def _alert_service(self, config, repository):
        if not config.operational_alerts_enabled:
            return None
        recipient = self._configured_recipient()
        return OperationalAlertService(
            repository,
            CurrentEnvironmentOperationalGmail(recipient),
            configured_recipient=recipient,
        )

    def doctor(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "1", "status": "ready", "checks": {},
        }
        try:
            verify_frozen_contracts(self._root)
            result["checks"]["contracts"] = "ready"
            foundation = FoundationConfig.load(self._root)
            status = FoundationTool(foundation).execute(
                FoundationRequest(
                    "status", "orchestration-doctor",
                    datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                )
            )
            result["checks"]["foundation"] = "ready" if status.ready else "blocked"
            config = OrchestrationConfigLoader(self._root).load(_CONFIG)
            result["checks"]["configuration"] = "ready"
            self._active_subject(foundation.database_path)
            result["checks"]["subject"] = "ready"
            if config.operational_alerts_enabled:
                self._configured_recipient()
                result["checks"]["alert_recipient"] = "ready"
            gmail = inspect_gmail_environment()
            result["checks"]["gmail"] = gmail.code
            if not status.ready:
                result["status"] = "blocked"
        except Exception:
            result["status"] = "blocked"
            result["error_code"] = "orchestration_doctor_failed"
        return result

    def _tool(self, foundation, config, repository, subjects) -> OrchestrationTool:
        runner = SubprocessRunner()
        health = None
        try:
            from .health_workflow import HealthWorkflow
            alerts = self._alert_service(config, repository)
            health = HealthWorkflow(
                database_path=foundation.database_path,
                state_directory=foundation.state_root,
                log_directory=config.log_root,
                storage_directory=foundation.data_root,
                repository=repository,
                clock=lambda: datetime.now(UTC),
                alert_service=alerts,
            )
        except (ImportError, TypeError):
            health = None
        receipt_store = RepositoryReceiptStore(repository, subjects)
        return OrchestrationTool(
            clock=lambda: datetime.now(UTC),
            subject_authorizer=subjects,
            receipt_store=receipt_store,
            operator_retry_authorizer=receipt_store,
            morning=MorningWorkflowService(runner),
            weekly=SundayWorkflowService(runner),
            mail=MailWorkflow(
                runner, SqlitePlanRevisionResolver(foundation.database_path)
            ),
            health_check=health,
            mail_deadline_seconds=min(
                config.workflow_deadline_seconds, 900
            ),
        )

    def run_workflow(
        self, workflow_kind: str, *, logical_date: str | None,
        invocation_id: str | None,
    ) -> object:
        foundation, config, repository, subjects = self._components()
        numeric, subject_key = self._active_subject(foundation.database_path)
        now = datetime.now(UTC)
        local_today = now.astimezone(_SG).date().isoformat()
        kind = workflow_kind.replace("-", "_")
        subject: str | None = None
        logical: str | None = None
        if kind in {"morning", "weekly"}:
            subject = subject_key
            logical = logical_date or local_today
        elif kind == "mail":
            subject = str(numeric)
        elif kind != "health_check":
            raise ValueError("orchestration_workflow_kind_invalid")
        invocation = invocation_id or (
            "manual-" + kind.replace("_", "-") + "-"
            + now.strftime("%Y%m%dT%H%M%S")
        )
        request = WorkflowRequest(
            kind, subject, logical, invocation, "manual", None, (),
            (now + timedelta(seconds=config.workflow_deadline_seconds)).isoformat().replace("+00:00", "Z"),
            now.isoformat().replace("+00:00", "Z"),
        )
        receipt = self._tool(
            foundation, config, repository, subjects
        ).execute(request)
        outcome = receipt.as_json_dict()
        events = WorkflowIncidentCoordinator(repository).observe(
            workflow_key=receipt.workflow_key,
            workflow_kind=receipt.workflow_kind,
            outcome=outcome,
            seen_at_utc=datetime.now(UTC),
        )
        self._notify_business_incidents(
            self._alert_service(config, repository), events
        )
        return outcome

    def _execute_due(self, item: DueItem) -> object:
        foundation, config, repository, subjects = self._components()
        numeric, subject_key = self._active_subject(foundation.database_path)
        if item.workflow_kind == "recovery":
            decision = item.recovery
            if (
                decision is None
                or decision.workflow_key != item.workflow_key
                or decision.action not in {
                    "start_workflow", "resume_workflow", "resume_step"
                }
            ):
                return self.reconcile(item.workflow_key)
            aggregate = repository.load_workflow_definition(item.workflow_key)
            if aggregate is None:
                raise ValueError("orchestration_recovery_workflow_missing")
            workflow = aggregate.workflow
            kind = workflow.workflow_kind
            if kind == "mail":
                prefix = f"mail-poll:{numeric}:"
                if not item.workflow_key.startswith(prefix):
                    raise ValueError("orchestration_due_identity_invalid")
                subject = str(numeric)
                invocation = item.workflow_key.removeprefix(prefix)
            elif kind == "health_check":
                prefix = "health-check:"
                if not item.workflow_key.startswith(prefix):
                    raise ValueError("orchestration_due_identity_invalid")
                subject = None
                invocation = item.workflow_key.removeprefix(prefix)
            elif kind in {"morning", "weekly"}:
                subject = subject_key
                invocation = "scheduled-" + hashlib.sha256(
                    item.workflow_key.encode()
                ).hexdigest()[:24]
            else:
                raise ValueError("orchestration_due_identity_invalid")
            request = WorkflowRequest(
                kind,
                subject,
                workflow.logical_local_date,
                invocation,
                workflow.trigger_kind,
                (
                    None
                    if workflow.parent_workflow_run_id is None
                    else str(workflow.parent_workflow_run_id)
                ),
                (),
                (
                    workflow.deadline_at_utc.isoformat().replace("+00:00", "Z")
                    if workflow.deadline_at_utc is not None
                    else (
                        item.due_at_utc
                        + timedelta(seconds=config.workflow_deadline_seconds)
                    ).isoformat().replace("+00:00", "Z")
                ),
                workflow.started_at_utc.isoformat().replace("+00:00", "Z"),
            )
            return self._tool(
                foundation, config, repository, subjects
            ).execute(request).as_json_dict()
        subject = (
            None if item.workflow_kind == "health_check"
            else str(numeric) if item.workflow_kind == "mail"
            else subject_key
        )
        if item.workflow_kind == "mail":
            prefix = f"mail-poll:{numeric}:"
            if not item.workflow_key.startswith(prefix):
                raise ValueError("orchestration_due_identity_invalid")
            invocation = item.workflow_key.removeprefix(prefix)
        elif item.workflow_kind == "health_check":
            prefix = "health-check:"
            if not item.workflow_key.startswith(prefix):
                raise ValueError("orchestration_due_identity_invalid")
            invocation = item.workflow_key.removeprefix(prefix)
        else:
            invocation = "scheduled-" + hashlib.sha256(
                item.workflow_key.encode()
            ).hexdigest()[:24]
        request = WorkflowRequest(
            item.workflow_kind, subject, item.logical_local_date, invocation,
            item.trigger_kind, None, (),
            (item.deadline_at_utc or item.due_at_utc + timedelta(
                seconds=config.workflow_deadline_seconds
            )).isoformat().replace("+00:00", "Z"),
            item.due_at_utc.isoformat().replace("+00:00", "Z"),
        )
        return self._tool(
            foundation, config, repository, subjects
        ).execute(request).as_json_dict()

    @staticmethod
    def _notify_business_incidents(
        alerts: OperationalAlertService | None,
        events: BusinessIncidentEvents | None,
    ) -> None:
        if alerts is None or events is None:
            return
        for keys, event in (
            (events.opened, "open"),
            (events.recovered, "recovery"),
        ):
            for incident_key in keys:
                try:
                    alerts.deliver(incident_key, event=event)
                except Exception:
                    # The incident transition is already durable. Alert
                    # reconciliation must not invalidate the workflow result.
                    continue

    def supervisor_run(self) -> object:
        # Idempotent bootstrap is the only normal first-layer mutation.
        foundation = FoundationConfig.load(self._root)
        now = datetime.now(UTC)
        bootstrap = FoundationTool(foundation).execute(
            FoundationRequest(
                "init", "orchestration-supervisor-bootstrap",
                now.isoformat().replace("+00:00", "Z"),
            )
        )
        if not bootstrap.ready:
            return {"schema_version": "1", "status": "blocked", "error_code": "foundation_not_ready"}
        foundation, config, repository, _subjects = self._components()
        projections = SchedulingProjectionService().project(config, now)
        for projection in projections:
            repository.upsert_scheduler_job(
                projection, is_enabled=True, updated_at_utc=now
            )
        numeric, _subject_key = self._active_subject(foundation.database_path)
        instance = f"host-{os.getpid()}"
        lease = LeaseManager(
            foundation.database_path, config.state_lock_path, instance,
            os.getpid(), _Clock(), _ProcessProbe(), config.lease_ttl_seconds,
        )
        supervisor = Supervisor(lease)
        queue = DueQueueService(
            repository, lease, _Clock(), subject_id=numeric, host_id=instance
        )
        alerts = self._alert_service(config, repository)
        incidents = WorkflowIncidentCoordinator(repository)
        runtime = SupervisorRuntime(
            supervisor, queue, config, dispatch=self._execute_due,
            watchdog=SystemdNotifier(),
            incident_notifier=(
                None
                if alerts is None
                else lambda incident_key: alerts.deliver(
                    incident_key, event="open"
                )
            ),
            incident_recovery_notifier=(
                None
                if alerts is None
                else lambda incident_key: alerts.deliver(
                    incident_key, event="recovery"
                )
            ),
            business_failure_handler=lambda item, outcome: (
                incidents.observe(
                    workflow_key=item.workflow_key,
                    workflow_kind=item.workflow_kind,
                    outcome=outcome,
                    seen_at_utc=datetime.now(UTC),
                )
            ),
        )
        previous: dict[int, Any] = {}
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(
                signum, lambda number, _frame: runtime.request_stop(number)
            )
        try:
            return runtime.run(
                wait=time.sleep,
                wait_seconds=float(config.heartbeat_interval_seconds),
            ).as_json_dict()
        finally:
            runtime.stop()
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def status(self, workflow_run_id: str | None) -> object:
        _foundation, _config, repository, _subjects = self._components()
        rows = repository.recent_workflows(50)
        if workflow_run_id is not None:
            rows = tuple(
                row for row in rows
                if str(row.id) == workflow_run_id
                or row.workflow_key == workflow_run_id
            )
        return {
            "schema_version": "1",
            "status": "ready",
            "workflows": [
                {
                    "id": str(row.id), "workflow_key": row.workflow_key,
                    "workflow_kind": row.workflow_kind, "status": row.status,
                    "logical_local_date": row.logical_local_date,
                    "completed_at_utc": row.completed_at_utc,
                }
                for row in rows
            ],
            "open_incident_count": len(repository.open_incidents()),
        }

    def reconcile(self, workflow_run_id: str | None) -> object:
        _foundation, _config, repository, _subjects = self._components()
        rows = repository.active_workflow_definitions(200, 0)
        if workflow_run_id is not None:
            rows = tuple(
                row for row in rows
                if str(row.run_record.id) == workflow_run_id
                or row.run_record.workflow_key == workflow_run_id
            )
        decisions = [
            {
                "workflow_key": aggregate.workflow.workflow_key,
                "action": plan_recovery(
                    aggregate, RecoveryContext(datetime.now(UTC))
                ).action,
            }
            for aggregate in rows
        ]
        return {"schema_version": "1", "status": "checked", "decisions": decisions}

    def retry(self, workflow_run_id: str) -> object:
        foundation, config, repository, subjects = self._components()
        numeric, subject_key = self._active_subject(foundation.database_path)
        workflow = (
            repository.get_workflow_by_id(int(workflow_run_id))
            if workflow_run_id.isdecimal()
            else repository.get_workflow(workflow_run_id)
        )
        if (
            workflow is None
            or workflow.status != "failed"
            or workflow.workflow_kind not in {"morning", "weekly"}
            or workflow.subject_id != numeric
            or workflow.logical_local_date is None
        ):
            return {
                "schema_version": "1",
                "status": "rejected",
                "error_code": "workflow_not_recoverable",
            }

        now = datetime.now(UTC)
        invocation = (
            f"retry-{workflow.id}-"
            + now.strftime("%Y%m%dT%H%M%S.%fZ")
        )
        request = WorkflowRequest(
            workflow.workflow_kind,
            subject_key,
            workflow.logical_local_date,
            invocation,
            "manual",
            str(workflow.id),
            (),
            (
                now + timedelta(seconds=config.workflow_deadline_seconds)
            ).isoformat().replace("+00:00", "Z"),
            now.isoformat().replace("+00:00", "Z"),
        )
        receipt = self._tool(
            foundation, config, repository, subjects
        ).execute(request)
        outcome = receipt.as_json_dict()
        events = WorkflowIncidentCoordinator(repository).observe(
            workflow_key=receipt.workflow_key,
            workflow_kind=receipt.workflow_kind,
            outcome=outcome,
            seen_at_utc=datetime.now(UTC),
        )
        self._notify_business_incidents(
            self._alert_service(config, repository), events
        )
        return outcome


def create_cli_runtime(root: Path | None = None):
    app = ProductionOrchestrationApplication(root)
    operations = None
    try:
        foundation = FoundationConfig.load(app._root)
        operations = OperatorOperations(
            OrchestrationRepository(foundation.database_path)
        )
    except Exception:
        pass
    return app, operations
