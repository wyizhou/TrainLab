"""A3-19 one-shot, reason-bound revision of one active weekly plan."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from .config import AnalysisConfig
from .context import (
    ANALYSIS_INPUT_SCHEMA_SHA256,
    ANALYSIS_INPUT_SCHEMA_VERSION,
    AnalysisContextBuilder,
    ContextBuildRequest,
    ContextSource,
)
from .contracts import (
    AnalysisDelivery,
    AnalysisError,
    AnalysisReceipt,
    AnalysisRequest,
    AnalysisWarning,
)
from .daily import (
    _safe_code,
    _safety_base,
    _validate_with_bounded_corrections,
    daily_primary_item_contract,
)
from .harness import SchemaEvidence, resolve_harness_bundle
from .publisher import AnalysisPublisher, RunEvidence
from .quality_gate import QualityGate, QualityGateRequest
from .result_validation import AnalysisResultValidationError, ResultValidationExpectation
from .run_state import AnalysisRunCoordinator, AnalysisRunStateError
from .stable_views import StableViewRepository
from .training_difficulty import training_control_contracts


_SG = ZoneInfo("Asia/Singapore")


class PendingPlanRevisionDelivery(Protocol):
    def create_pending(self, **kwargs: Any) -> Any: ...


class _Runner(Protocol):
    def execute(self, bundle: Any, canonical_context: bytes) -> Any: ...


class _PreflightError(ValueError):
    def __init__(self, code: str, *, status: str = "deferred") -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan_revision_contract(
    *, original_plan_id: int, original_artifact_id: int,
    reason_event_id: int, effective_local_date: str,
) -> Mapping[str, Any]:
    """Deterministic output boundary; it contains no user mail text."""
    daily = daily_primary_item_contract()
    return {
        "key": "plan_revision_contract_v1",
        "algorithm_version": "plan-revision-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "original_plan_id": str(original_plan_id),
        "original_artifact_id": str(original_artifact_id),
        "reason_event_id": str(reason_event_id),
        "effective_local_date": effective_local_date,
        "scope": "effective_date_through_original_plan_end_only",
        "historical_prefix_policy": "host_copies_original_rows_byte_for_byte",
        "items_per_remaining_day": 1,
        "timezone": "Asia/Singapore",
        "clock_time_forbidden": True,
        "allowed_activity_kinds": list(daily["allowed_activity_kinds"]),
        "running_template": daily["running_template"],
        "rest_template": daily["rest_template"],
    }


class PlanRevisionRoute:
    """Resolve, gate, generate, validate, publish and seed one revision mail."""

    def __init__(
        self,
        *,
        config: AnalysisConfig,
        coordinator: AnalysisRunCoordinator,
        stable_views: StableViewRepository,
        runner: _Runner,
        publisher: AnalysisPublisher,
        delivery: PendingPlanRevisionDelivery,
        connection: sqlite3.Connection,
        context_builder: AnalysisContextBuilder | None = None,
        quality_gate: QualityGate | None = None,
        validator: Any | None = None,
        harness_resolver: Any = resolve_harness_bundle,
        subject_resolver: Any | None = None,
        clock: Any = _utc_now,
    ) -> None:
        self.config = config
        self.coordinator = coordinator
        self.stable_views = stable_views
        self.runner = runner
        self.publisher = publisher
        self.delivery = delivery
        self.connection = connection
        self.context_builder = context_builder or AnalysisContextBuilder()
        self.quality_gate = quality_gate or QualityGate()
        self.validator = validator
        self.harness_resolver = harness_resolver
        self.subject_resolver = subject_resolver
        self.clock = clock

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        started = self.clock()
        prepared = None
        try:
            request.validate()
            if request.mode != "revise_plan":
                raise _PreflightError(
                    "analysis_plan_revision_mode_required", status="rejected"
                )
            subject_id = self._subject_id(request)
            source = self._resolve_source(request, subject_id)
            request = replace(
                request, effective_local_date=source["effective_local_date"]
            )
            request.validate()
            prepared = self.coordinator.begin(request)
        except _PreflightError as error:
            return self._receipt(
                request,
                error.status,
                started,
                errors=(self._error("request", error.code),),
            )
        except AnalysisRunStateError as error:
            code = _safe_code(error, "analysis_plan_revision_begin_failed")
            return self._receipt(
                request,
                "lock_busy" if code == "analysis_lock_busy" else "failed",
                started,
                errors=(self._error("service", code),),
            )
        except Exception as error:
            return self._receipt(
                request,
                "failed",
                started,
                errors=(
                    self._error(
                        "request",
                        _safe_code(error, "analysis_plan_revision_request_invalid"),
                    ),
                ),
            )
        if prepared.decision.action == "unchanged":
            return self._receipt(
                request,
                "unchanged",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                next_action="none",
            )
        try:
            return self._run_started(request, prepared, started, subject_id, source)
        except Exception as error:
            try:
                self.coordinator.finish(prepared, "failed")
            except AnalysisRunStateError:
                pass
            return self._receipt(
                request,
                "failed",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                errors=(
                    self._error(
                        "service", _safe_code(error, "analysis_plan_revision_failed")
                    ),
                ),
            )

    def _resolve_source(
        self, request: AnalysisRequest, subject_id: int
    ) -> dict[str, Any]:
        if (
            request.plan_id is None
            or not request.plan_id.isascii()
            or not request.plan_id.isdecimal()
            or int(request.plan_id) <= 0
            or request.reason_event_id is None
            or not request.reason_event_id.isascii()
            or not request.reason_event_id.isdecimal()
            or int(request.reason_event_id) <= 0
        ):
            raise _PreflightError(
                "analysis_plan_revision_identifiers_invalid", status="rejected"
            )
        plan_id, reason_id = int(request.plan_id), int(request.reason_event_id)
        plan = self.connection.execute(
            "SELECT p.id,p.analysis_artifact_id,p.plan_start_local_date,"
            "p.plan_end_local_date,p.timezone,p.status,a.is_current,a.artifact_kind "
            "FROM training_plans p JOIN analysis_artifacts a "
            "ON a.id=p.analysis_artifact_id "
            "WHERE p.id=? AND p.subject_id=?",
            (plan_id, subject_id),
        ).fetchone()
        if (
            plan is None
            or plan["status"] != "active"
            or plan["is_current"] != 1
            or plan["artifact_kind"] != "weekly_training_plan"
            or plan["timezone"] != "Asia/Singapore"
        ):
            raise _PreflightError("analysis_plan_revision_source_unavailable")
        try:
            start = date.fromisoformat(plan["plan_start_local_date"])
            end = date.fromisoformat(plan["plan_end_local_date"])
        except (TypeError, ValueError) as error:
            raise _PreflightError("analysis_plan_revision_source_unavailable") from error
        if end - start != timedelta(days=6):
            raise _PreflightError("analysis_plan_revision_source_unavailable")
        reason = self.connection.execute(
            "SELECT structured_payload_json FROM v_plan_revision_reason_events "
            "WHERE id=? AND subject_id=?",
            (reason_id, subject_id),
        ).fetchone()
        if reason is None:
            raise _PreflightError("analysis_plan_revision_reason_unavailable")
        try:
            payload = json.loads(reason["structured_payload_json"])
            effective = date.fromisoformat(payload["effective_local_date"])
        except (TypeError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise _PreflightError("analysis_plan_revision_reason_unavailable") from error
        if (
            not isinstance(payload, dict)
            or payload.get("current_plan_id") != plan_id
            or not start <= effective <= end
        ):
            raise _PreflightError("analysis_plan_revision_reason_unavailable")
        if (
            request.effective_local_date is not None
            and request.effective_local_date != effective.isoformat()
        ):
            raise _PreflightError(
                "analysis_plan_revision_effective_date_mismatch", status="rejected"
            )
        requested = datetime.fromisoformat(
            request.requested_at_utc.replace("Z", "+00:00")
        ).astimezone(_SG).date()
        if effective < requested:
            raise _PreflightError(
                "analysis_plan_revision_effective_date_past", status="rejected"
            )
        return {
            "plan_id": plan_id,
            "artifact_id": int(plan["analysis_artifact_id"]),
            "reason_event_id": reason_id,
            "plan_start_local_date": start.isoformat(),
            "plan_end_local_date": end.isoformat(),
            "effective_local_date": effective.isoformat(),
        }

    def _run_started(
        self, request: AnalysisRequest, prepared: Any, started: str,
        subject_id: int, source: Mapping[str, Any],
    ) -> AnalysisReceipt:
        effective = source["effective_local_date"]
        context_request = ContextBuildRequest(
            route="revise_plan",
            run_key=prepared.decision.run_key,
            subject_id=subject_id,
            as_of_utc=request.requested_at_utc,
            plan_start_local_date=source["plan_start_local_date"],
            plan_end_local_date=source["plan_end_local_date"],
            effective_local_date=effective,
            plan_id=int(source["plan_id"]),
            reason_event_id=int(source["reason_event_id"]),
            max_context_bytes=self.config.max_context_bytes,
        )
        window_start, window_end = context_request.repository_window()
        snapshot = self.stable_views.snapshot(subject_id, window_start, window_end)
        gate = self.quality_gate.evaluate(
            QualityGateRequest(
                "revise_plan",
                subject_id,
                effective,
                effective,
                request.requested_at_utc,
                int(source["plan_id"]),
                int(source["reason_event_id"]),
            ),
            snapshot,
        )
        if gate.state == "blocked":
            self.coordinator.finish(prepared, "failed")
            return self._receipt(
                request,
                "deferred",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                quality="blocked",
                warnings=tuple(
                    AnalysisWarning(item.code, item.entity, item.summary)
                    for item in gate.blockers
                ),
                next_action=gate.next_action,
            )
        output_sha = sha256(Path(self.config.output_schema).read_bytes()).hexdigest()
        bundle = self.harness_resolver(
            self.config,
            "revise_plan",
            SchemaEvidence(
                ANALYSIS_INPUT_SCHEMA_VERSION,
                ANALYSIS_INPUT_SCHEMA_SHA256,
                "1",
                output_sha,
            ),
        )
        contract = plan_revision_contract(
            original_plan_id=int(source["plan_id"]),
            original_artifact_id=int(source["artifact_id"]),
            reason_event_id=int(source["reason_event_id"]),
            effective_local_date=effective,
        )
        built = self.context_builder.build(
            context_request,
            ContextSource(snapshot=snapshot),
            quality_gate=gate,
            harness_bundle=bundle,
            deterministic_features=(
                contract,
                *training_control_contracts(self.config),
            ),
        )
        run_result = self.runner.execute(
            bundle, built.canonical_json.encode("utf-8")
        )
        start = date.fromisoformat(source["plan_start_local_date"])
        end = date.fromisoformat(source["plan_end_local_date"])
        effective_day = date.fromisoformat(effective)
        original_items = sorted(
            (
                row
                for row in snapshot.views["v_training_plan_items"]
                if row.get("training_plan_id") == source["plan_id"]
            ),
            key=lambda row: row["item_index"],
        )
        safety_bases = {
            day.isoformat(): _safety_base(
                subject_id, day.isoformat(), request.requested_at_utc, snapshot
            )
            for day in (
                effective_day + timedelta(days=index)
                for index in range((end - effective_day).days + 1)
            )
        }
        period = {
            "start_local_date": start.isoformat(),
            "end_local_date": end.isoformat(),
        }
        expectation = ResultValidationExpectation(
            prepared.decision.run_key,
            "revise_plan",
            subject_id,
            {
                "plan": {
                    "start_local_date": effective,
                    "end_local_date": end.isoformat(),
                }
            },
            built.context["input_manifest"],
            gate.as_dict(),
            {},
            weekly_safety_request_bases=safety_bases,
            original_plan={
                "plan_id": str(source["plan_id"]),
                "artifact_id": str(source["artifact_id"]),
                "period": period,
            },
            original_plan_items=original_items,
            reason_event={
                "reason_event_id": str(source["reason_event_id"]),
                "effective_local_date": effective,
            },
        )
        validator = self.validator
        if validator is None:
            from .result_validation import AnalysisResultValidator

            validator = AnalysisResultValidator()
        try:
            accepted, run_result = _validate_with_bounded_corrections(
                runner=self.runner,
                bundle=bundle,
                canonical_context=built.canonical_json.encode("utf-8"),
                run_result=run_result,
                validator=validator,
                expectation=expectation,
            )
        except AnalysisResultValidationError as error:
            self.coordinator.finish(prepared, "rejected")
            return self._receipt(
                request,
                "rejected",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                quality=gate.state,
                errors=(self._error("service", error.code),),
            )
        evidence = RunEvidence(
            bundle.harness_version,
            ANALYSIS_INPUT_SCHEMA_VERSION,
            "1",
            built.context,
            built.context_snapshot_sha256,
            dict(getattr(run_result, "audit", {})),
        )
        published = self.publisher.publish(
            run_id=prepared.decision.run_id,
            accepted=accepted,
            input_manifest=built.context["input_manifest"],
            run_evidence=evidence,
        )
        self.coordinator.finish(prepared, "succeeded")
        artifact_ids = (str(published.artifact_ids["weekly_training_plan"]),)
        try:
            delivery = self._create_pending_delivery(
                published, prepared.decision.run_key
            )
        except Exception as error:
            return self._receipt(
                request,
                "partial",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                quality=gate.state,
                artifact_ids=artifact_ids,
                training_plan_id=str(published.training_plan_id),
                superseded_plan_id=str(source["plan_id"]),
                input_hash=built.context_snapshot_sha256,
                harness=bundle.harness_version,
                errors=(
                    self._error(
                        "service",
                        _safe_code(
                            error,
                            "analysis_plan_revision_delivery_pending_failed",
                        ),
                    ),
                ),
                next_action="retry_delivery",
            )
        return self._receipt(
            request,
            "partial" if delivery.status == "pending" else "succeeded",
            started,
            run_key=prepared.decision.run_key,
            analysis_run_id=str(prepared.decision.run_id),
            quality=gate.state,
            artifact_ids=artifact_ids,
            training_plan_id=str(published.training_plan_id),
            superseded_plan_id=str(source["plan_id"]),
            delivery=delivery,
            input_hash=built.context_snapshot_sha256,
            harness=bundle.harness_version,
            next_action="retry_delivery" if delivery.status == "pending" else "none",
        )

    def _create_pending_delivery(
        self, published: Any, run_key: str
    ) -> AnalysisDelivery:
        try:
            value = self.delivery.create_pending(
                publish_receipt=published, delivery_kind="plan_revision"
            )
        except TypeError:
            value = self.delivery.create_pending(
                run_key=run_key,
                artifact_ids=tuple(published.artifact_ids.values()),
                kind="plan_revision",
            )
        if isinstance(value, AnalysisDelivery):
            return value
        delivery_id = getattr(value, "delivery_id", None)
        artifacts = getattr(value, "artifacts", ())
        if not isinstance(delivery_id, int) or delivery_id <= 0:
            raise RuntimeError("analysis_plan_revision_delivery_adapter_invalid")
        ids = tuple(str(getattr(item, "artifact_id", "")) for item in artifacts)
        if len(ids) != 1 or any(not item.isdecimal() for item in ids):
            raise RuntimeError("analysis_plan_revision_delivery_adapter_invalid")
        return AnalysisDelivery(str(delivery_id), "pending", ids)

    def _subject_id(self, request: AnalysisRequest) -> int:
        resolver = self.subject_resolver
        if resolver is None:
            def resolver(subject_key: str) -> int | None:
                row = self.connection.execute(
                    "SELECT id FROM data_subjects "
                    "WHERE subject_key=? AND is_active=1",
                    (subject_key,),
                ).fetchone()
                return int(row[0]) if row is not None else None
        value = resolver(request.subject_id) if callable(resolver) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        raise _PreflightError("analysis_plan_revision_subject_unavailable")

    @staticmethod
    def _error(stage: str, code: str) -> AnalysisError:
        return AnalysisError(stage, code, code.replace("_", " "))

    def _receipt(
        self,
        request: AnalysisRequest,
        status: str,
        started: str,
        *,
        run_key: str | None = None,
        analysis_run_id: str | None = None,
        quality: str = "blocked",
        artifact_ids: tuple[str, ...] = (),
        training_plan_id: str | None = None,
        superseded_plan_id: str | None = None,
        delivery: AnalysisDelivery | None = None,
        input_hash: str | None = None,
        harness: str | None = None,
        warnings: tuple[AnalysisWarning, ...] = (),
        errors: tuple[AnalysisError, ...] = (),
        next_action: str = "operator_review",
    ) -> AnalysisReceipt:
        plan = None
        if request.effective_local_date:
            row = self.connection.execute(
                "SELECT plan_end_local_date FROM training_plans WHERE id=?",
                (
                    int(request.plan_id)
                    if request.plan_id and request.plan_id.isdecimal()
                    else -1,
                ),
            ).fetchone()
            if row is not None:
                plan = {
                    "start_local_date": request.effective_local_date,
                    "end_local_date": row["plan_end_local_date"],
                }
        return AnalysisReceipt(
            run_key
            or "analysis:invalid:revise_plan:invalid:invalid",
            request.invocation_id,
            "revise_plan",
            status,
            started,
            self.clock(),
            analysis_run_id=analysis_run_id,
            target_periods={
                "summary": None,
                "advice": None,
                "review": None,
                "plan": plan,
            },
            quality_gate_state=quality,
            artifact_ids=artifact_ids,
            training_plan_id=training_plan_id,
            superseded_plan_id=superseded_plan_id,
            delivery=delivery,
            input_snapshot_sha256=input_hash,
            harness_version=harness,
            input_schema_version=ANALYSIS_INPUT_SCHEMA_VERSION if input_hash else None,
            output_schema_version="1" if input_hash else None,
            warnings=warnings,
            errors=errors,
            next_action=next_action,
        )


PlanRevisionRouteService = PlanRevisionRoute
