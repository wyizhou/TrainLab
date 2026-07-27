"""Production wiring for the explicit ``trainlab run --analysis-only`` path.

This module is intentionally a small composition root.  It does not schedule
or poll mail.  Delivery is an explicit second phase over an already-persisted
delivery ID and can never regenerate analysis output.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from ..foundation import FoundationConfig, FoundationTool
from ..util import project_root
from .config import load_analysis_config
from .contracts import AnalysisDelivery, AnalysisError, AnalysisRequest, AnalysisReceipt, build_run_key
from .delivery import AnalysisDeliveryFactory, AnalysisDeliveryRepository
from .delivery_service import AnalysisDeliveryService, DeliveryExecution
from .gmail_delivery import GmailDeliveryError, GmailDeliveryGateway
from .publisher import AnalysisPublisher
from .run_state import AnalysisRunCoordinator, AnalysisRunRepository, SubjectLockManager
from .runner import AnalysisCodexRunner
from .stable_views import StableViewRepository
from ..mail_agent.runtime import _recipient_email


_SINGAPORE = ZoneInfo("Asia/Singapore")
_SUBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _strict_date(
    value: str | None, error_code: str = "analysis_summary_date_invalid"
) -> date | None:
    if value is None:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-" or not (value[:4] + value[5:7] + value[8:]).isdigit():
        raise ValueError(error_code)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(error_code) from error


def build_daily_request(
    *, subject_id: str, invocation_id: str, summary_date: str | None, now: datetime | None = None
) -> AnalysisRequest:
    """Build the sole supported production-analysis request without I/O."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("analysis_invocation_id_required")
    summary = _strict_date(summary_date)
    current = (now or datetime.now(UTC)).astimezone(_SINGAPORE).date()
    summary = summary or current - timedelta(days=1)
    if summary >= current:
        raise ValueError("analysis_summary_date_must_be_before_today")
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1",
        "mode": "daily",
        "subject_id": subject_id,
        "invocation_id": invocation_id,
        "run_key": None,
        "summary_local_date": summary.isoformat(),
        "advice_local_date": (summary + timedelta(days=1)).isoformat(),
        "as_of_local_date": None,
        "plan_id": None,
        "reason_event_id": None,
        "effective_local_date": None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
        "requested_at_utc": requested,
    })


def build_weekly_request(
    *, subject_id: str, invocation_id: str, as_of_date: str | None,
    now: datetime | None = None,
) -> AnalysisRequest:
    """Build one rolling seven-day review plus seven-day plan request."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("analysis_invocation_id_required")
    current = (now or datetime.now(UTC)).astimezone(_SINGAPORE).date()
    as_of = _strict_date(as_of_date) or current
    if as_of > current:
        raise ValueError("analysis_weekly_as_of_date_in_future")
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1",
        "mode": "weekly",
        "subject_id": subject_id,
        "invocation_id": invocation_id,
        "run_key": None,
        "summary_local_date": None,
        "advice_local_date": None,
        "as_of_local_date": as_of.isoformat(),
        "plan_id": None,
        "reason_event_id": None,
        "effective_local_date": None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
        "requested_at_utc": requested,
    })


def build_plan_revision_request(
    *,
    subject_id: str,
    invocation_id: str,
    plan_id: str,
    reason_event_id: str,
    effective_date: str | None,
    now: datetime | None = None,
) -> AnalysisRequest:
    """Build one explicit plan-revision request without reading the event."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("analysis_invocation_id_required")
    for value, code in (
        (plan_id, "analysis_plan_id_invalid"),
        (reason_event_id, "analysis_reason_event_id_invalid"),
    ):
        if (
            not isinstance(value, str)
            or not value.isdecimal()
            or value.startswith("0")
            or int(value) <= 0
        ):
            raise ValueError(code)
    effective = _strict_date(
        effective_date, "analysis_plan_revision_effective_date_invalid"
    )
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1",
        "mode": "revise_plan",
        "subject_id": subject_id,
        "invocation_id": invocation_id,
        "run_key": None,
        "summary_local_date": None,
        "advice_local_date": None,
        "as_of_local_date": None,
        "plan_id": plan_id,
        "reason_event_id": reason_event_id,
        "effective_local_date": effective.isoformat() if effective else None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
        "requested_at_utc": requested,
    })


def build_regeneration_request(
    *, subject_id: str, invocation_id: str, artifact_id: str, reason_code: str,
    now: datetime | None = None,
) -> AnalysisRequest:
    """Build one explicit artifact-regeneration request without I/O."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("analysis_invocation_id_required")
    if (
        not isinstance(artifact_id, str)
        or not artifact_id.isdecimal()
        or artifact_id.startswith("0")
        or int(artifact_id) <= 0
    ):
        raise ValueError("analysis_artifact_id_invalid")
    if not isinstance(reason_code, str) or not reason_code:
        raise ValueError("analysis_regeneration_reason_required")
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1", "mode": "regenerate", "subject_id": subject_id,
        "invocation_id": invocation_id, "run_key": None,
        "summary_local_date": None, "advice_local_date": None,
        "as_of_local_date": None, "plan_id": None, "reason_event_id": None,
        "effective_local_date": None, "artifact_id": artifact_id,
        "delivery_id": None, "regeneration_reason_code": reason_code,
        "requested_at_utc": requested,
    })


def build_status_request(
    *, subject_id: str, run_key: str | None = None, now: datetime | None = None,
) -> AnalysisRequest:
    """Build the read-only status request without an invocation identity."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1", "mode": "status", "subject_id": subject_id,
        "invocation_id": None, "run_key": run_key,
        "summary_local_date": None, "advice_local_date": None,
        "as_of_local_date": None, "plan_id": None, "reason_event_id": None,
        "effective_local_date": None, "artifact_id": None, "delivery_id": None,
        "regeneration_reason_code": None, "requested_at_utc": requested,
    })


def _active_subject_key(connection: object) -> str:
    """Read only the active public subject key; fail closed unless it is unique."""
    rows = list(connection.execute(
        "SELECT subject_key FROM data_subjects WHERE is_active=1 ORDER BY id"
    ))  # type: ignore[union-attr]
    if len(rows) != 1:
        raise ValueError("analysis_active_subject_not_unique")
    subject_key = rows[0][0]
    if not isinstance(subject_key, str) or _SUBJECT_KEY.fullmatch(subject_key) is None:
        raise ValueError("analysis_active_subject_invalid")
    return subject_key


def run_analysis_only(
    *, invocation_id: str, summary_date: str | None = None, deliver: bool = False,
    root: Path | None = None
) -> AnalysisReceipt:
    """Execute one L3 daily route and always release its Foundation connection."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    try:
        request = build_daily_request(
            subject_id=_active_subject_key(connection),
            invocation_id=invocation_id,
            summary_date=summary_date,
        )
        repository = AnalysisRunRepository(connection)
        coordinator = AnalysisRunCoordinator(
            repository,
            SubjectLockManager(config.lock_path, trusted_root=config.lock_path.parent.parent),
        )
        # Delay this import so the production entry remains compatible while
        # the independently-owned daily route is being integrated.
        from .daily import DailyRoute

        route = DailyRoute(
            config=config,
            coordinator=coordinator,
            stable_views=StableViewRepository(connection),
            runner=AnalysisCodexRunner(config),
            publisher=AnalysisPublisher(connection),
            delivery=AnalysisDeliveryFactory(connection),
        )
        receipt = route.execute(request)
        if not deliver or receipt.status not in {"partial", "unchanged", "succeeded"}:
            return receipt
        delivery_id = _daily_delivery_id(connection, receipt)
        if delivery_id is None:
            return replace(
                receipt,
                status="partial",
                errors=receipt.errors + (_error("analysis_delivery_missing"),),
                next_action="retry_delivery",
            )
        artifact_ids = _delivery_artifact_ids(connection, delivery_id)
        receipt = _restore_daily_receipt_evidence(connection, receipt, artifact_ids)
        return _merge_daily_delivery(
            receipt,
            _execute_delivery(connection, config, delivery_id, "retry_delivery"),
            artifact_ids,
        )
    finally:
        connection.close()


def run_weekly_analysis(
    *, invocation_id: str, as_of_date: str | None = None, deliver: bool = False,
    root: Path | None = None,
) -> AnalysisReceipt:
    """Execute one A3-18 weekly route through the sole production entry."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    try:
        request = build_weekly_request(
            subject_id=_active_subject_key(connection),
            invocation_id=invocation_id,
            as_of_date=as_of_date,
        )
        repository = AnalysisRunRepository(connection)
        coordinator = AnalysisRunCoordinator(
            repository,
            SubjectLockManager(
                config.lock_path, trusted_root=config.lock_path.parent.parent
            ),
        )
        from .weekly import WeeklyRoute

        route = WeeklyRoute(
            config=config,
            coordinator=coordinator,
            stable_views=StableViewRepository(connection),
            runner=AnalysisCodexRunner(config),
            publisher=AnalysisPublisher(connection),
            delivery=AnalysisDeliveryFactory(connection),
        )
        receipt = route.execute(request)
        if not deliver or receipt.status not in {"partial", "unchanged", "succeeded"}:
            return receipt
        delivery_id = _analysis_delivery_id(connection, receipt, "weekly_report")
        if delivery_id is None:
            return replace(
                receipt,
                status="partial",
                errors=receipt.errors + (_error("analysis_delivery_missing"),),
                next_action="retry_delivery",
            )
        artifact_ids = _delivery_artifact_ids(connection, delivery_id)
        receipt = _restore_receipt_evidence(
            connection, receipt, artifact_ids, include_training_plan=True
        )
        return _merge_delivery(
            receipt,
            _execute_delivery(connection, config, delivery_id, "retry_delivery"),
            artifact_ids,
        )
    finally:
        connection.close()


def run_plan_revision_analysis(
    *,
    invocation_id: str,
    plan_id: str,
    reason_event_id: str,
    effective_date: str | None = None,
    deliver: bool = False,
    root: Path | None = None,
) -> AnalysisReceipt:
    """Execute one A3-19 plan revision through the production entry."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    try:
        request = build_plan_revision_request(
            subject_id=_active_subject_key(connection),
            invocation_id=invocation_id,
            plan_id=plan_id,
            reason_event_id=reason_event_id,
            effective_date=effective_date,
        )
        repository = AnalysisRunRepository(connection)
        coordinator = AnalysisRunCoordinator(
            repository,
            SubjectLockManager(
                config.lock_path, trusted_root=config.lock_path.parent.parent
            ),
        )
        from .revise_plan import PlanRevisionRoute

        route = PlanRevisionRoute(
            config=config,
            coordinator=coordinator,
            stable_views=StableViewRepository(connection),
            runner=AnalysisCodexRunner(config),
            publisher=AnalysisPublisher(connection),
            delivery=AnalysisDeliveryFactory(connection),
            connection=connection,
        )
        receipt = route.execute(request)
        if not deliver or receipt.status not in {"partial", "unchanged", "succeeded"}:
            return receipt
        delivery_id = _analysis_delivery_id(connection, receipt, "plan_revision")
        if delivery_id is None:
            return replace(
                receipt,
                status="partial",
                errors=receipt.errors + (_error("analysis_delivery_missing"),),
                next_action="retry_delivery",
            )
        artifact_ids = _delivery_artifact_ids(connection, delivery_id)
        receipt = _restore_receipt_evidence(
            connection, receipt, artifact_ids, include_training_plan=True
        )
        return _merge_delivery(
            receipt,
            _execute_delivery(connection, config, delivery_id, "retry_delivery"),
            artifact_ids,
        )
    finally:
        connection.close()


def run_regeneration_analysis(
    *, invocation_id: str, artifact_id: str, reason_code: str,
    deliver: bool = False, root: Path | None = None,
) -> AnalysisReceipt:
    """Execute one A3-20 regeneration through the production entry."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    try:
        request = build_regeneration_request(
            subject_id=_active_subject_key(connection), invocation_id=invocation_id,
            artifact_id=artifact_id, reason_code=reason_code,
        )
        repository = AnalysisRunRepository(connection)
        coordinator = AnalysisRunCoordinator(
            repository,
            SubjectLockManager(
                config.lock_path, trusted_root=config.lock_path.parent.parent
            ),
        )
        from .regenerate import RegenerateRoute

        receipt = RegenerateRoute(
            config=config, coordinator=coordinator,
            stable_views=StableViewRepository(connection),
            runner=AnalysisCodexRunner(config), publisher=AnalysisPublisher(connection),
            delivery=AnalysisDeliveryFactory(connection), connection=connection,
        ).execute(request)
        if not deliver or receipt.status not in {"partial", "unchanged", "succeeded"}:
            return receipt
        delivery_id = _receipt_delivery_id(connection, receipt)
        if delivery_id is None:
            return replace(
                receipt, status="partial",
                errors=receipt.errors + (_error("analysis_delivery_missing"),),
                next_action="retry_delivery",
            )
        artifact_ids = _delivery_artifact_ids(connection, delivery_id)
        receipt = _restore_receipt_evidence(
            connection, receipt, artifact_ids, include_training_plan=True
        )
        return _merge_delivery(
            receipt,
            _execute_delivery(connection, config, delivery_id, "retry_delivery"),
            artifact_ids,
        )
    finally:
        connection.close()


def run_analysis_status(
    *, run_key: str | None = None, root: Path | None = None,
) -> AnalysisReceipt:
    """Read A3-21 status using only the Foundation database connection."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    connection = FoundationTool(foundation)._connect(
        foundation.database_path, readonly=True
    )
    try:
        from .status import AnalysisStatusQueryService

        request = build_status_request(
            subject_id=_active_subject_key(connection), run_key=run_key
        )
        return AnalysisStatusQueryService(connection).execute(request)
    finally:
        connection.close()


def run_delivery_recovery(
    *, invocation_id: str, delivery_id: int, reconcile: bool = False,
    root: Path | None = None,
) -> AnalysisReceipt:
    """Recover one persisted delivery without invoking the analysis generator."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    started = _utc_now()
    mode = "reconcile_delivery" if reconcile else "retry_delivery"
    try:
        repository = AnalysisDeliveryRepository(connection)
        pending = repository.load_pending(delivery_id)
        row = connection.execute(
            "SELECT s.subject_key FROM data_subjects s WHERE s.id=? AND s.is_active=1",
            (pending.subject_id,),
        ).fetchone()
        if row is None or not isinstance(row[0], str):
            raise ValueError("analysis_delivery_subject_not_active")
        request = AnalysisRequest.from_dict({
            "schema_version": "1", "mode": mode, "subject_id": row[0],
            "invocation_id": invocation_id, "run_key": None,
            "summary_local_date": None, "advice_local_date": None,
            "as_of_local_date": None, "plan_id": None, "reason_event_id": None,
            "effective_local_date": None, "artifact_id": None,
            "delivery_id": str(delivery_id), "regeneration_reason_code": None,
            "requested_at_utc": started,
        })
        result = _execute_delivery(connection, config, delivery_id, mode)
        delivery = _contract_delivery(result, tuple(str(x.artifact_id) for x in pending.artifacts))
        succeeded = result.status in {"sent", "already_sent"}
        return AnalysisReceipt(
            run_key=build_run_key(request),
            invocation_id=invocation_id, mode=mode,
            status="succeeded" if succeeded else "partial",
            started_at_utc=started, completed_at_utc=_utc_now(),
            analysis_run_id=str(pending.analysis_run_id),
            quality_gate_state="ready",
            artifact_ids=delivery.artifact_ids,
            delivery=delivery,
            errors=() if result.error_code is None else (_error(result.error_code),),
            next_action=result.next_action,
        )
    finally:
        connection.close()


def _execute_delivery(
    connection: object, config: object, delivery_id: int, mode: str
) -> DeliveryExecution:
    try:
        recipient = _recipient_email(project_root())
    except ValueError:
        state = AnalysisDeliveryRepository(connection).read_state(delivery_id)  # type: ignore[arg-type]
        return DeliveryExecution(
            delivery_id, state.status, state.provider_message_id,
            state.provider_thread_id, "analysis_delivery_recipient_not_configured",
            "reconcile_delivery" if state.status in {"sending", "delivery_unknown"} else "retry_delivery",
        )
    try:
        gateway = GmailDeliveryGateway(
            recipient, timeout_seconds=int(config.delivery_timeout_seconds)
        )
    except GmailDeliveryError as error:
        state = AnalysisDeliveryRepository(connection).read_state(delivery_id)  # type: ignore[arg-type]
        return DeliveryExecution(
            delivery_id, state.status, state.provider_message_id,
            state.provider_thread_id, f"analysis_delivery_{error.code.removeprefix('gmail_')}",
            "reconcile_delivery" if state.status in {"sending", "delivery_unknown"} else "retry_delivery",
        )
    service = AnalysisDeliveryService(AnalysisDeliveryRepository(connection), gateway)  # type: ignore[arg-type]
    return service.execute(delivery_id, mode)  # type: ignore[arg-type]


def _daily_delivery_id(connection: object, receipt: AnalysisReceipt) -> int | None:
    return _analysis_delivery_id(connection, receipt, "daily_report")


def _analysis_delivery_id(
    connection: object, receipt: AnalysisReceipt, delivery_kind: str
) -> int | None:
    if receipt.delivery is not None and receipt.delivery.delivery_id.isdecimal():
        return int(receipt.delivery.delivery_id)
    row = connection.execute(  # type: ignore[union-attr]
        "SELECT d.id FROM analysis_deliveries d JOIN analysis_runs r ON r.id=d.analysis_run_id "
        "WHERE r.run_key=? AND d.delivery_kind=? ORDER BY d.id",
        (receipt.run_key, delivery_kind),
    ).fetchall()
    return int(row[0][0]) if len(row) == 1 else None


def _receipt_delivery_id(connection: object, receipt: AnalysisReceipt) -> int | None:
    """Resolve the single delivery attached to an already-persisted run."""
    if receipt.delivery is not None and receipt.delivery.delivery_id.isdecimal():
        return int(receipt.delivery.delivery_id)
    rows = connection.execute(  # type: ignore[union-attr]
        "SELECT d.id FROM analysis_deliveries d JOIN analysis_runs r ON r.id=d.analysis_run_id "
        "WHERE r.run_key=? ORDER BY d.id",
        (receipt.run_key,),
    ).fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def _contract_delivery(result: DeliveryExecution, artifact_ids: tuple[str, ...]) -> AnalysisDelivery:
    error = None if result.error_code is None else {
        "code": result.error_code,
        "summary": "analysis delivery did not complete",
    }
    return AnalysisDelivery(
        str(result.delivery_id), result.status, artifact_ids,
        provider_message_id=result.provider_message_id,
        provider_thread_id=result.provider_thread_id, error=error,
    )


def _delivery_artifact_ids(connection: object, delivery_id: int) -> tuple[str, ...]:
    rows = connection.execute(  # type: ignore[union-attr]
        "SELECT analysis_artifact_id FROM analysis_delivery_artifacts "
        "WHERE analysis_delivery_id=? ORDER BY ordinal",
        (delivery_id,),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _restore_daily_receipt_evidence(
    connection: object, receipt: AnalysisReceipt, artifact_ids: tuple[str, ...]
) -> AnalysisReceipt:
    """Restore persisted public evidence for an unchanged successful run."""
    return _restore_receipt_evidence(connection, receipt, artifact_ids)


def _restore_receipt_evidence(
    connection: object,
    receipt: AnalysisReceipt,
    artifact_ids: tuple[str, ...],
    *,
    include_training_plan: bool = False,
) -> AnalysisReceipt:
    if receipt.status != "unchanged":
        return receipt
    row = connection.execute(  # type: ignore[union-attr]
        "SELECT id,status,harness_version,input_schema_version,output_schema_version,"
        "context_snapshot_sha256 FROM analysis_runs WHERE run_key=?",
        (receipt.run_key,),
    ).fetchone()
    if row is None or row[1] != "succeeded":
        return receipt
    training_plan_id = receipt.training_plan_id
    if include_training_plan:
        plans = connection.execute(  # type: ignore[union-attr]
            "SELECT p.id FROM training_plans p "
            "JOIN analysis_artifacts a ON a.id=p.analysis_artifact_id "
            "WHERE a.generated_by_run_id=? ORDER BY p.id",
            (row[0],),
        ).fetchall()
        if len(plans) == 1:
            training_plan_id = str(plans[0][0])
    content_same = receipt.content_same
    if receipt.mode == "regenerate":
        content_same = _regeneration_content_same(connection, int(row[0]))
    return replace(
        receipt,
        analysis_run_id=str(row[0]),
        artifact_ids=artifact_ids,
        training_plan_id=training_plan_id,
        quality_gate_state="ready",
        harness_version=row[2],
        input_schema_version=row[3],
        output_schema_version=row[4],
        input_snapshot_sha256=row[5],
        content_same=content_same,
    )


def _regeneration_content_same(connection: object, run_id: int) -> bool | None:
    """Recover the persisted direct-source content comparison for a rerun."""
    rows = connection.execute(  # type: ignore[union-attr]
        "SELECT successor.content_sha256=source.content_sha256 "
        "FROM analysis_artifact_relations relation "
        "JOIN analysis_artifacts successor ON successor.id=relation.from_artifact_id "
        "JOIN analysis_artifacts source ON source.id=relation.to_artifact_id "
        "WHERE successor.generated_by_run_id=? AND relation.relation_type='derived_from' "
        "ORDER BY successor.id",
        (run_id,),
    ).fetchall()
    if len(rows) != 1:
        return None
    return bool(rows[0][0])


def _merge_daily_delivery(
    receipt: AnalysisReceipt, result: DeliveryExecution,
    persisted_artifact_ids: tuple[str, ...],
) -> AnalysisReceipt:
    return _merge_delivery(receipt, result, persisted_artifact_ids)


def _merge_delivery(
    receipt: AnalysisReceipt, result: DeliveryExecution,
    persisted_artifact_ids: tuple[str, ...],
) -> AnalysisReceipt:
    artifacts = receipt.artifact_ids or persisted_artifact_ids
    delivery = _contract_delivery(result, artifacts)
    terminal = result.status in {"sent", "already_sent"}
    status = ("unchanged" if receipt.status == "unchanged" else "succeeded") if terminal else "partial"
    errors = receipt.errors
    if result.error_code is not None:
        errors += (_error(result.error_code),)
    return replace(
        receipt, status=status, artifact_ids=artifacts, delivery=delivery, errors=errors,
        next_action=result.next_action,
    )


def _error(code: str) -> AnalysisError:
    return AnalysisError("service", code, code.replace("_", " "))
