"""A3-18 one-shot weekly summary and seven-day plan orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from .capacity import WeeklyCapacityError, assess_weekly_capacity
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
    analysis_error_stage,
    analysis_next_action,
    analysis_quality_state,
    analysis_status,
)
from .daily import (
    _safe_code,
    _safety_base,
    _validate_with_bounded_corrections,
    daily_primary_item_contract,
)
from .delivery import PendingDeliveryFactory
from .features import (
    adherence_statistics,
    snapshot_plan_matches,
    training_history_features,
)
from .harness import SchemaEvidence, resolve_harness_bundle
from .publisher import AnalysisPublisher, RunEvidence
from .quality_gate import QualityGate, QualityGateRequest
from .result_validation import (
    AnalysisResultValidationError,
    ResultValidationExpectation,
)
from .run_state import AnalysisRunCoordinator, AnalysisRunStateError
from .stable_views import StableSnapshot, StableViewRepository
from .training_difficulty import training_control_contracts

_SG = ZoneInfo("Asia/Hong_Kong")


class _Runner(Protocol):
    def execute(self, bundle: Any, canonical_context: bytes) -> Any: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_dates(request: AnalysisRequest) -> AnalysisRequest:
    if request.mode != "weekly":
        raise ValueError("analysis_weekly_mode_required")
    if any(
        value is not None
        for value in (
            request.summary_local_date,
            request.advice_local_date,
            request.plan_id,
            request.reason_event_id,
            request.effective_local_date,
            request.artifact_id,
            request.delivery_id,
            request.regeneration_reason_code,
        )
    ):
        raise ValueError("analysis_weekly_fields_invalid")
    local_today = (
        datetime.fromisoformat(request.requested_at_utc.replace("Z", "+00:00"))
        .astimezone(_SG)
        .date()
    )
    as_of = (
        date.fromisoformat(request.as_of_local_date)
        if request.as_of_local_date
        else local_today
    )
    if as_of > local_today:
        raise ValueError("analysis_weekly_as_of_in_future")
    if as_of.weekday() != 0:
        raise ValueError("analysis_weekly_monday_required")
    return replace(request, as_of_local_date=as_of.isoformat())


def _periods(as_of_local_date: str) -> tuple[dict[str, str], dict[str, str]]:
    as_of = date.fromisoformat(as_of_local_date)
    if as_of.weekday() != 0:
        raise ValueError("analysis_weekly_monday_required")
    return (
        {
            "start_local_date": (as_of - timedelta(days=7)).isoformat(),
            "end_local_date": (as_of - timedelta(days=1)).isoformat(),
        },
        {
            "start_local_date": as_of.isoformat(),
            "end_local_date": (as_of + timedelta(days=6)).isoformat(),
        },
    )


def _snapshot_rows(snapshot: object, name: str) -> tuple[Mapping[str, Any], ...]:
    views = getattr(snapshot, "views", None)
    rows = views.get(name, ()) if isinstance(views, Mapping) else ()
    if not isinstance(rows, tuple) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("analysis_weekly_snapshot_invalid")
    return rows


def _prior_artifact_state(
    snapshot: object, review: Mapping[str, str]
) -> dict[str, str]:
    summaries = _snapshot_rows(snapshot, "v_current_weekly_summaries")
    review_start = date.fromisoformat(review["start_local_date"])
    prior_summary_start = (review_start - timedelta(days=7)).isoformat()
    prior_summary_end = (review_start - timedelta(days=1)).isoformat()
    prior_summary = any(
        row.get("artifact_kind") == "weekly_summary"
        and row.get("period_start_local_date") == prior_summary_start
        and row.get("period_end_local_date") == prior_summary_end
        for row in summaries
    )
    plans = _snapshot_rows(snapshot, "v_current_training_plans")
    prior_plan = any(
        isinstance(row.get("plan_start_local_date"), str)
        and isinstance(row.get("plan_end_local_date"), str)
        and row["plan_start_local_date"] <= review["end_local_date"]
        and row["plan_end_local_date"] >= review["start_local_date"]
        for row in plans
    )
    return {
        "summary": "available" if prior_summary else "no_prior_artifact",
        "plan": "available" if prior_plan else "no_prior_artifact",
    }


def weekly_plan_contract(prior_artifact_state: Mapping[str, str]) -> dict[str, Any]:
    daily = daily_primary_item_contract()
    return {
        "key": "weekly_plan_contract_v1",
        "algorithm_version": "weekly-plan-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "prior_artifact_state": dict(prior_artifact_state),
        "days": 7,
        "items_per_day": 1,
        "timezone": "Asia/Hong_Kong",
        "clock_time_forbidden": True,
        "allowed_activity_kinds": list(daily["allowed_activity_kinds"]),
        "running_template": daily["running_template"],
        "climbing_template": daily["climbing_template"],
        "rest_template": daily["rest_template"],
    }


def _plan_adherence(
    snapshot: object, review: Mapping[str, str]
) -> tuple[Mapping[str, Any], ...]:
    plans: list[Mapping[str, Any]] = []
    for row in _snapshot_rows(snapshot, "v_current_training_plans"):
        plan_start = row.get("plan_start_local_date")
        plan_end = row.get("plan_end_local_date")
        if (
            isinstance(plan_start, str)
            and isinstance(plan_end, str)
            and plan_start <= review["end_local_date"]
            and plan_end >= review["start_local_date"]
        ):
            plans.append(row)
    coverage = tuple(
        row
        for row in getattr(snapshot, "coverage", ())
        if isinstance(row, Mapping)
        and row.get("resource_kind") == "activity_inventory"
        and review["start_local_date"]
        <= str(row.get("local_date"))
        <= review["end_local_date"]
    )
    if plans:
        matches = snapshot_plan_matches(snapshot)  # type: ignore[arg-type]
        features = adherence_statistics(
            matches,
            end_local_date=review["end_local_date"],
            window_days=7,
            coverage_complete_dates=coverage,
            plan_applicability="plan_present",
            plan_revision_ids=tuple(row["analysis_artifact_id"] for row in plans),
        )
    else:
        features = adherence_statistics(
            (),
            end_local_date=review["end_local_date"],
            window_days=7,
            coverage_complete_dates=coverage,
            plan_applicability="no_prior_plan",
        )
    return tuple(item.as_dict() for item in features)


def _host_progression_inputs(
    *,
    summary_gate: Any,
    plan_gate: Any,
    adherence: tuple[Mapping[str, Any], ...],
    capacity_assessment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build progression inputs from deterministic host evidence only."""

    unconfirmed = next(
        (
            row.get("value")
            for row in adherence
            if row.get("key") == "plan_adherence.unconfirmed.count.7d"
        ),
        0,
    )
    minimum_evidence = next(
        (
            row.get("value")
            for row in adherence
            if row.get("key") == "plan_adherence.minimum_evidence.7d"
        ),
        0,
    )
    capacity_change = "none"
    if (
        isinstance(capacity_assessment, Mapping)
        and capacity_assessment.get("status") == "ready"
        and capacity_assessment.get("decision") == "advance"
        and summary_gate.state == "ready"
        and plan_gate.state == "ready"
        and minimum_evidence == 1
        and unconfirmed == 0
    ):
        capacity_change = "volume"
    return {
        "recovery_ready": summary_gate.state == "ready" and plan_gate.state == "ready",
        "adherence_stable": minimum_evidence == 1 and unconfirmed == 0,
        # A capacity change is never inferred from model prose.  An explicit
        # future profile/configuration change can opt into it later.
        "capacity_change": capacity_change,
        "evidence": "host_quality_gate_and_plan_adherence_v1",
    }


class WeeklyRoute:
    """One weekly invocation: gate, generate, validate, publish, seed delivery."""

    def __init__(
        self,
        *,
        config: AnalysisConfig,
        coordinator: AnalysisRunCoordinator,
        stable_views: StableViewRepository,
        runner: _Runner,
        publisher: AnalysisPublisher,
        delivery: PendingDeliveryFactory,
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
        self.context_builder = context_builder or AnalysisContextBuilder()
        self.quality_gate = quality_gate or QualityGate()
        self.validator = validator
        self.harness_resolver = harness_resolver
        self.subject_resolver = subject_resolver
        self.clock = clock

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        started = self.clock()
        try:
            request = _default_dates(request)
            request.validate()
            prepared = self.coordinator.begin(request)
        except AnalysisRunStateError as error:
            code = _safe_code(error, "analysis_weekly_begin_failed")
            status = "lock_busy" if code == "analysis_lock_busy" else "failed"
            return self._receipt(
                request, status, started, errors=(self._error("service", code),)
            )
        except Exception as error:
            return self._receipt(
                request,
                "failed",
                started,
                errors=(
                    self._error(
                        "request",
                        _safe_code(error, "analysis_weekly_request_invalid"),
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
            return self._run_started(request, prepared, started)
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
                    self._error("service", _safe_code(error, "analysis_weekly_failed")),
                ),
            )

    def _run_started(
        self, request: AnalysisRequest, prepared: Any, started: str
    ) -> AnalysisReceipt:
        assert request.as_of_local_date is not None
        review, plan = _periods(request.as_of_local_date)
        context_request = ContextBuildRequest(
            route="weekly",
            run_key=prepared.decision.run_key,
            subject_id=self._subject_id(request),
            as_of_utc=request.requested_at_utc,
            review_end_local_date=review["end_local_date"],
            max_context_bytes=self.config.max_context_bytes,
        )
        start, end = context_request.repository_window()
        snapshot = self.stable_views.snapshot(context_request.subject_id, start, end)
        gate = self.quality_gate.evaluate(
            QualityGateRequest(
                "weekly_summary",
                context_request.subject_id,
                review["start_local_date"],
                review["end_local_date"],
                request.requested_at_utc,
            ),
            snapshot,
        )
        plan_gate = self.quality_gate.evaluate(
            QualityGateRequest(
                "weekly_plan",
                context_request.subject_id,
                review["start_local_date"],
                review["end_local_date"],
                request.requested_at_utc,
            ),
            snapshot,
        )
        blocked = gate if gate.state == "blocked" else plan_gate
        if blocked.state == "blocked":
            self.coordinator.finish(prepared, "failed")
            return self._receipt(
                request,
                "deferred",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                quality="blocked",
                next_action=blocked.next_action,
                warnings=tuple(
                    AnalysisWarning(item.code, item.entity, item.summary)
                    for item in blocked.blockers
                ),
            )
        prior_state = _prior_artifact_state(snapshot, review)
        adherence = _plan_adherence(snapshot, review)
        capacity_assessment: Mapping[str, Any] | None = None
        profile = self.config.coaching_profile_contract
        if isinstance(profile, Mapping) and profile.get("status") == "confirmed":
            try:
                capacity_assessment = assess_weekly_capacity(
                    activities=_snapshot_rows(snapshot, "v_current_activities"),
                    coverage=tuple(
                        row for row in snapshot.coverage if isinstance(row, Mapping)
                    ),
                    plan_start=date.fromisoformat(plan["start_local_date"]),
                    recovery_ready=gate.state == "ready" and plan_gate.state == "ready",
                    adherence_stable=(
                        next(
                            (
                                row.get("value")
                                for row in adherence
                                if row.get("key")
                                == "plan_adherence.unconfirmed.count.7d"
                            ),
                            0,
                        )
                        == 0
                        and next(
                            (
                                row.get("value")
                                for row in adherence
                                if row.get("key")
                                == "plan_adherence.minimum_evidence.7d"
                            ),
                            0,
                        )
                        == 1
                    ),
                    available_weekdays=tuple(
                        profile.get("available_weekdays", (1, 3, 5, 7))
                    ),
                    hard_load_max=int(profile.get("hard_load_max", 3)),
                    hard_load_min_gap_days=int(
                        profile.get("hard_load_min_gap_days", 2)
                    ),
                )
            except (TypeError, ValueError, WeeklyCapacityError):
                capacity_assessment = {
                    "schema_version": "1",
                    "status": "deferred",
                    "decision": "hold",
                    "reason": "capacity_assessment_failed_closed",
                }
            if capacity_assessment.get("status") != "ready":
                self.coordinator.finish(prepared, "failed")
                return self._receipt(
                    request,
                    "deferred",
                    started,
                    run_key=prepared.decision.run_key,
                    analysis_run_id=str(prepared.decision.run_id),
                    quality=gate.state,
                    next_action="repair_data",
                    warnings=(
                        AnalysisWarning(
                            "weekly_capacity_unavailable",
                            "weekly_capacity",
                            str(
                                capacity_assessment.get(
                                    "reason", "weekly_capacity_unavailable"
                                )
                            ),
                        ),
                    ),
                )
        output_sha = sha256(Path(self.config.output_schema).read_bytes()).hexdigest()
        bundle = self.harness_resolver(
            self.config,
            "weekly",
            SchemaEvidence(
                ANALYSIS_INPUT_SCHEMA_VERSION,
                ANALYSIS_INPUT_SCHEMA_SHA256,
                "1",
                output_sha,
            ),
        )
        capacity_features = (
            (("weekly_capacity_assessment_v1", capacity_assessment),)
            if capacity_assessment is not None
            else ()
        )
        built = self.context_builder.build(
            context_request,
            ContextSource(snapshot=snapshot),
            quality_gate=gate,
            harness_bundle=bundle,
            deterministic_features=(
                weekly_plan_contract(prior_state),
                *training_control_contracts(self.config),
                *capacity_features,
                *(
                    training_history_features(
                        snapshot, end_local_date=review["end_local_date"]
                    )
                    if isinstance(snapshot, StableSnapshot)
                    else ()
                ),
            ),
            plan_adherence=adherence,
        )
        run_result = self.runner.execute(bundle, built.canonical_json.encode("utf-8"))
        safety_bases = {
            (
                date.fromisoformat(plan["start_local_date"]) + timedelta(days=index)
            ).isoformat(): _safety_base(
                context_request.subject_id,
                (
                    date.fromisoformat(plan["start_local_date"]) + timedelta(days=index)
                ).isoformat(),
                request.requested_at_utc,
                snapshot,
            )
            for index in range(7)
        }
        expectation = ResultValidationExpectation(
            prepared.decision.run_key,
            "weekly",
            context_request.subject_id,
            {"review": review, "plan": plan},
            built.context["input_manifest"],
            gate.as_dict(),
            {},
            weekly_safety_request_bases=safety_bases,
            prior_artifact_state=prior_state,
            available_training_weekdays=self.config.available_training_weekdays,
            coaching_profile=self.config.coaching_profile_contract,
            capacity_assessment=capacity_assessment,
            progression_inputs=_host_progression_inputs(
                summary_gate=gate,
                plan_gate=plan_gate,
                adherence=adherence,
                capacity_assessment=capacity_assessment,
            ),
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
        ids = tuple(
            str(published.artifact_ids[kind])
            for kind in ("weekly_summary", "weekly_training_plan")
        )
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
                artifact_ids=ids,
                training_plan_id=str(published.training_plan_id),
                input_hash=built.context_snapshot_sha256,
                harness=bundle.harness_version,
                next_action="retry_delivery",
                errors=(
                    self._error(
                        "service",
                        _safe_code(error, "analysis_weekly_delivery_pending_failed"),
                    ),
                ),
            )
        superseded = tuple(getattr(published, "superseded_plan_ids", ()))
        return self._receipt(
            request,
            "partial" if delivery.status == "pending" else "succeeded",
            started,
            run_key=prepared.decision.run_key,
            analysis_run_id=str(prepared.decision.run_id),
            quality=gate.state,
            artifact_ids=ids,
            training_plan_id=str(published.training_plan_id),
            superseded_plan_id=str(superseded[0]) if superseded else None,
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
                publish_receipt=published, delivery_kind="weekly_report"
            )
        except TypeError:
            legacy_create_pending = getattr(self.delivery, "create_pending")
            value = legacy_create_pending(
                run_key=run_key,
                artifact_ids=tuple(published.artifact_ids.values()),
                kind="weekly_report",
            )
        if isinstance(value, AnalysisDelivery):
            return value
        delivery_id = getattr(value, "delivery_id", None)
        artifacts = getattr(value, "artifacts", ())
        if not isinstance(delivery_id, int) or delivery_id <= 0:
            raise RuntimeError("analysis_weekly_delivery_adapter_invalid")
        ids = tuple(str(getattr(item, "artifact_id", "")) for item in artifacts)
        if len(ids) != 2 or any(not item.isdecimal() for item in ids):
            raise RuntimeError("analysis_weekly_delivery_adapter_invalid")
        return AnalysisDelivery(str(delivery_id), "pending", ids)

    def _subject_id(self, request: AnalysisRequest) -> int:
        resolver = self.subject_resolver
        if resolver is None:
            repository = getattr(self.coordinator, "_repository", None)
            connection = getattr(repository, "_conn", None)
            if connection is not None:

                def resolver(subject_key: str) -> int | None:
                    row = connection.execute(
                        "SELECT id FROM data_subjects WHERE subject_key=? AND is_active=1",
                        (subject_key,),
                    ).fetchone()
                    return int(row[0]) if row is not None else None

        value = resolver(request.subject_id) if callable(resolver) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        raise RuntimeError("analysis_weekly_subject_id_adapter_required")

    @staticmethod
    def _error(stage: str, code: str) -> AnalysisError:
        return AnalysisError(analysis_error_stage(stage), code, code.replace("_", " "))

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
        review = plan = None
        if request.as_of_local_date:
            review, plan = _periods(request.as_of_local_date)
        return AnalysisReceipt(
            run_key or "analysis:invalid:weekly:invalid:invalid",
            request.invocation_id,
            "weekly",
            analysis_status(status),
            started,
            self.clock(),
            analysis_run_id=analysis_run_id,
            target_periods={
                "summary": None,
                "advice": None,
                "review": review,
                "plan": plan,
            },
            quality_gate_state=analysis_quality_state(quality),
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
            next_action=analysis_next_action(next_action),
        )


WeeklyRouteService = WeeklyRoute
