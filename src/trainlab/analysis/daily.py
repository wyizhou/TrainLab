"""A3-17 one-shot daily route orchestration.

This module is deliberately an application seam, not a CLI entry point.  It
coordinates the already bounded A3-05..13 components and accepts a tiny
pending-delivery adapter because A3-14 may be supplied independently.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .config import AnalysisConfig
from .context import (
    ANALYSIS_INPUT_SCHEMA_SHA256, ANALYSIS_INPUT_SCHEMA_VERSION,
    AnalysisContextBuilder, ContextBuildRequest, ContextSource,
)
from .contracts import AnalysisDelivery, AnalysisError, AnalysisReceipt, AnalysisRequest, AnalysisWarning
from .harness import SchemaEvidence, resolve_harness_bundle
from .publisher import AnalysisPublisher, RunEvidence
from .quality_gate import QualityGate, QualityGateRequest
from .result_validation import AnalysisResultValidationError, ResultValidationExpectation
from .run_state import AnalysisRunCoordinator, AnalysisRunStateError
from .stable_views import StableViewRepository
from .training_difficulty import training_control_contracts
from .heart_rate_zones_store import zone_evidence_from_snapshot


_SG = ZoneInfo("Asia/Hong_Kong")


class PendingDailyDelivery(Protocol):
    """A3-14 boundary: persist a pending record only; never send mail."""

    def create_pending(self, **kwargs: Any) -> Any: ...


class _Runner(Protocol):
    def execute(self, bundle: Any, canonical_context: bytes) -> Any: ...


def _validate_with_bounded_corrections(
    *,
    runner: Any,
    bundle: Any,
    canonical_context: bytes,
    run_result: Any,
    validator: Any,
    expectation: ResultValidationExpectation,
) -> tuple[Any, Any]:
    """Validate once, then allow at most two safe-code-only corrections."""

    current = run_result
    correction = getattr(runner, "execute_correction", None)
    for correction_index in range(3):
        try:
            return validator.validate(current.output_bytes, expectation), current
        except AnalysisResultValidationError as error:
            if correction_index == 2 or not callable(correction):
                raise
            current = correction(bundle, canonical_context, error.code)
    raise AssertionError("unreachable")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_code(error: BaseException, fallback: str) -> str:
    """Return a stable code only, never a model/source/exception message."""
    value = getattr(error, "code", None)
    if isinstance(value, str) and value.startswith("analysis_") and len(value) <= 160:
        return value
    prefix = str(error).split(":", 1)[0]
    if re.fullmatch(r"analysis_[a-z0-9_]{1,151}", prefix):
        return prefix
    return fallback


def _default_dates(request: AnalysisRequest) -> AnalysisRequest:
    if request.mode != "daily":
        raise ValueError("analysis_daily_mode_required")
    if (request.summary_local_date is None) != (request.advice_local_date is None):
        raise ValueError("analysis_daily_dates_incomplete")
    if request.summary_local_date is not None:
        return request
    as_of = datetime.fromisoformat(request.requested_at_utc.replace("Z", "+00:00"))
    advice = as_of.astimezone(_SG).date()
    return replace(request, summary_local_date=(advice - timedelta(days=1)).isoformat(), advice_local_date=advice.isoformat())


def daily_primary_item_contract() -> Mapping[str, Any]:
    """Safe versioned templates shown to the generator, with no source data.

    The running template intentionally has no BPM/zone target.  Only the
    deterministic safety validator may later accept exact zones from evidence.
    """
    return {
        "key": "daily_primary_item_contract_v1",
        "algorithm_version": "daily-primary-item-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "allowed_activity_kinds": ["running", "rest"],
        "running_template": {
            "activity_kind": "running", "hansons_session_role": "easy", "course_type": "easy", "warmup": "gentle_warmup",
            "main_set": "talk_test_easy", "cooldown": "gentle_cooldown", "planned_duration_minutes": 30,
            "total_volume": "easy_by_duration", "target_zone": None, "target_bpm_range": None,
            "prescribed_rpe": 4, "talk_test": "full_sentences", "work_intervals": [],
            "stop_conditions": ["acute_pain", "chest_pain", "fainting_or_dizziness", "unusual_shortness_of_breath"],
            "rationale": "recovery_appropriate",
        },
        "rest_template": {
            "activity_kind": "rest", "evidence": ["data_limited"], "uncertainty": "data_limited",
            "daily_activity_allowed": True, "recovery_signals": ["recovery_status_reassessed"],
            "seek_professional_help_if": ["concerning_symptom_appears"],
        },
    }


_USER_SAFETY_FACT_KINDS = frozenset({
    "chest_pain", "fainting", "acute_injury", "acute_pain", "hr_affecting_medication",
})


def _canonical_utc_or_none(value: object) -> str | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    rendered = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value if value == rendered or value == rendered.replace(".000000Z", "Z") else None


def _accepted_user_safety_signals(snapshot: object, *, subject_id: int, as_of_utc: str) -> list[Mapping[str, Any]]:
    """Translate only exact active user-fact keys; never inspect fact values."""
    views = getattr(snapshot, "views", None)
    rows = views.get("v_active_user_facts", ()) if isinstance(views, Mapping) else ()
    signals: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("subject_id") != subject_id:
            continue
        key, fact_id = row.get("fact_key"), row.get("id")
        if key not in _USER_SAFETY_FACT_KINDS or isinstance(fact_id, bool) or not isinstance(fact_id, (str, int)):
            continue
        fact_token = str(fact_id)
        if not fact_token or len(fact_token) > 96:
            continue
        effective = _canonical_utc_or_none(row.get("effective_from_utc")) or as_of_utc
        expires_raw = row.get("expires_at_utc")
        expires = None if expires_raw is None else _canonical_utc_or_none(expires_raw)
        if expires_raw is not None and expires is None:
            continue
        signals.append({"signal_id": f"user-fact:{fact_token}:{key}", "kind": key,
            "origin": "user_asserted", "source_revision_id": f"user-fact:{fact_token}",
            "current": True, "active": True, "effective_from_utc": effective,
            "expires_at_utc": expires})
    return signals


def _safety_base(subject_id: int, advice_date: str, as_of_utc: str, snapshot: object) -> Mapping[str, Any]:
    # Fail-safe first release: no stable zone-evidence adapter exists yet, so
    # exact BPM is impossible.  This is intentionally not inferred from health
    # rows or a model claim.
    return {"schema_version": "1", "subject_id": subject_id, "advice_local_date": advice_date,
            "as_of_utc": as_of_utc, "zone_evidence": zone_evidence_from_snapshot(snapshot),
            "safety_signals": _accepted_user_safety_signals(snapshot, subject_id=subject_id, as_of_utc=as_of_utc),
            "quality_sessions": [], "substitution": None}


class DailyRoute:
    """One daily invocation: gate, one generation, validate, publish, pending delivery."""

    def __init__(self, *, config: AnalysisConfig, coordinator: AnalysisRunCoordinator,
                 stable_views: StableViewRepository, runner: _Runner, publisher: AnalysisPublisher,
                 delivery: PendingDailyDelivery, context_builder: AnalysisContextBuilder | None = None,
                 quality_gate: QualityGate | None = None, validator: Any | None = None,
                 harness_resolver: Any = resolve_harness_bundle, subject_resolver: Any | None = None,
                 clock: Any = _utc_now) -> None:
        self.config, self.coordinator, self.stable_views, self.runner = config, coordinator, stable_views, runner
        self.publisher, self.delivery = publisher, delivery
        self.context_builder, self.quality_gate, self.validator = context_builder or AnalysisContextBuilder(), quality_gate or QualityGate(), validator
        self.harness_resolver, self.clock = harness_resolver, clock
        self.subject_resolver = subject_resolver

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        started = self.clock()
        try:
            request = _default_dates(request); request.validate()
            prepared = self.coordinator.begin(request)
        except AnalysisRunStateError as error:
            # Run-state errors are constructed from controlled codes only.
            candidate = str(error)
            code = candidate if candidate.startswith("analysis_") and len(candidate) <= 160 else "analysis_daily_begin_failed"
            # A3-05 uses this exact code for a nonblocking occupied subject
            # lock.  Other state/schema/subject failures must not masquerade
            # as transient contention and trigger an unsafe retry loop.
            status = "lock_busy" if code == "analysis_lock_busy" else "failed"
            return self._receipt(request, status, started, errors=(self._error("service", code),))
        except Exception as error:
            return self._receipt(request, "failed", started, errors=(self._error("request", _safe_code(error, "analysis_daily_request_invalid")),))
        if prepared.decision.action == "unchanged":
            return self._receipt(request, "unchanged", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), next_action="none")

        try:
            return self._run_started(request, prepared, started)
        except Exception as error:
            # Once begun, terminalise without retaining exception/model content.
            try: self.coordinator.finish(prepared, "failed")
            except AnalysisRunStateError: pass
            return self._receipt(request, "failed", started, run_key=prepared.decision.run_key,
                                 analysis_run_id=str(prepared.decision.run_id),
                                 errors=(self._error("service", _safe_code(error, "analysis_daily_failed")),))

    def _run_started(self, request: AnalysisRequest, prepared: Any, started: str) -> AnalysisReceipt:
        assert request.summary_local_date and request.advice_local_date
        context_request = ContextBuildRequest(route="daily", run_key=prepared.decision.run_key,
            subject_id=self._subject_id(request), as_of_utc=request.requested_at_utc,
            summary_local_date=request.summary_local_date, advice_local_date=request.advice_local_date,
            max_context_bytes=self.config.max_context_bytes)
        start, end = context_request.repository_window()
        snapshot = self.stable_views.snapshot(context_request.subject_id, start, end)
        gate = self.quality_gate.evaluate(QualityGateRequest("daily_summary", context_request.subject_id,
            request.summary_local_date, request.summary_local_date, request.requested_at_utc), snapshot)
        if gate.state == "blocked":
            self.coordinator.finish(prepared, "failed")
            return self._receipt(request, "deferred", started, run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id), quality="blocked", next_action=gate.next_action,
                warnings=tuple(AnalysisWarning(x.code, x.entity, x.summary) for x in gate.blockers))
        output_sha = sha256(Path(self.config.output_schema).read_bytes()).hexdigest()
        bundle = self.harness_resolver(self.config, "daily", SchemaEvidence(
            ANALYSIS_INPUT_SCHEMA_VERSION, ANALYSIS_INPUT_SCHEMA_SHA256, "1", output_sha))
        built = self.context_builder.build(
            context_request,
            ContextSource(snapshot=snapshot),
            quality_gate=gate,
            harness_bundle=bundle,
            deterministic_features=(
                daily_primary_item_contract(),
                *training_control_contracts(self.config),
            ),
        )
        run_result = self.runner.execute(bundle, built.canonical_json.encode("utf-8"))
        expectation = ResultValidationExpectation(prepared.decision.run_key, "daily", context_request.subject_id,
            {"summary": {"start_local_date": request.summary_local_date, "end_local_date": request.summary_local_date},
             "advice": {"start_local_date": request.advice_local_date, "end_local_date": request.advice_local_date}},
            built.context["input_manifest"], gate.as_dict(), _safety_base(context_request.subject_id, request.advice_local_date, request.requested_at_utc, snapshot),
            training_difficulty_level=self.config.training_difficulty_level,
            available_training_weekdays=self.config.available_training_weekdays)
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
            return self._receipt(request, "rejected", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id),
                quality=gate.state, errors=(self._error("service", error.code),))
        evidence = RunEvidence(bundle.harness_version, ANALYSIS_INPUT_SCHEMA_VERSION, "1", built.context,
            built.context_snapshot_sha256, dict(getattr(run_result, "audit", {})))
        published = self.publisher.publish(run_id=prepared.decision.run_id, accepted=accepted,
            input_manifest=built.context["input_manifest"], run_evidence=evidence)
        self.coordinator.finish(prepared, "succeeded")
        ids = tuple(str(published.artifact_ids[k]) for k in ("daily_summary", "daily_training_advice"))
        try:
            delivery = self._create_pending_delivery(published, prepared.decision.run_key)
        except Exception as error:
            return self._receipt(request, "partial", started, run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id), quality=gate.state, artifact_ids=ids,
                input_hash=built.context_snapshot_sha256, harness=bundle.harness_version, next_action="retry_delivery",
                errors=(self._error("service", _safe_code(error, "analysis_daily_delivery_pending_failed")),))
        return self._receipt(request, "partial" if delivery.status == "pending" else "succeeded", started,
            run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), quality=gate.state,
            artifact_ids=ids, delivery=delivery, input_hash=built.context_snapshot_sha256, harness=bundle.harness_version,
            next_action="retry_delivery" if delivery.status == "pending" else "none")

    def _create_pending_delivery(self, published: Any, run_key: str) -> AnalysisDelivery:
        """Adapt A3-14's factory without granting a send/render operation."""
        try:
            value = self.delivery.create_pending(publish_receipt=published, delivery_kind="daily_report")
        except TypeError:
            # Kept for synthetic adapters built before A3-14 landed.
            value = self.delivery.create_pending(run_key=run_key, artifact_ids=tuple(published.artifact_ids.values()), kind="daily_report")
        if isinstance(value, AnalysisDelivery):
            return value
        delivery_id = getattr(value, "delivery_id", None)
        artifacts = getattr(value, "artifacts", ())
        if not isinstance(delivery_id, int) or delivery_id <= 0:
            raise RuntimeError("analysis_daily_delivery_adapter_invalid")
        ids = tuple(str(getattr(item, "artifact_id", "")) for item in artifacts)
        if not ids or any(not item.isdecimal() for item in ids):
            raise RuntimeError("analysis_daily_delivery_adapter_invalid")
        return AnalysisDelivery(str(delivery_id), "pending", ids)

    def _subject_id(self, request: AnalysisRequest) -> int:
        """Resolve the active public subject key before any stable-view read."""
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
        raise RuntimeError("analysis_daily_subject_id_adapter_required")

    @staticmethod
    def _error(stage: str, code: str) -> AnalysisError:
        return AnalysisError(stage, code, code.replace("_", " "))

    def _receipt(self, request: AnalysisRequest, status: str, started: str, *, run_key: str | None = None,
                 analysis_run_id: str | None = None, quality: str = "blocked", artifact_ids: tuple[str, ...] = (),
                 delivery: AnalysisDelivery | None = None, input_hash: str | None = None, harness: str | None = None,
                 warnings: tuple[AnalysisWarning, ...] = (), errors: tuple[AnalysisError, ...] = (), next_action: str = "operator_review") -> AnalysisReceipt:
        summary, advice = request.summary_local_date, request.advice_local_date
        return AnalysisReceipt(run_key or "analysis:invalid:daily:invalid:invalid", request.invocation_id, "daily", status, started, self.clock(),
            analysis_run_id=analysis_run_id, target_periods={"summary": {"start_local_date": summary, "end_local_date": summary} if summary else None,
                "advice": {"start_local_date": advice, "end_local_date": advice} if advice else None, "review": None, "plan": None},
            quality_gate_state=quality, artifact_ids=artifact_ids, delivery=delivery, input_snapshot_sha256=input_hash,
            harness_version=harness, input_schema_version=ANALYSIS_INPUT_SCHEMA_VERSION if input_hash else None,
            output_schema_version="1" if input_hash else None, warnings=warnings, errors=errors, next_action=next_action)


DailyRouteService = DailyRoute
