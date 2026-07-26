"""A3-20 explicit, reason-controlled artifact regeneration route."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Protocol

from .config import AnalysisConfig
from .context import ANALYSIS_INPUT_SCHEMA_SHA256, ANALYSIS_INPUT_SCHEMA_VERSION, AnalysisContextBuilder, ContextBuildRequest, ContextSource
from .contracts import AnalysisDelivery, AnalysisError, AnalysisReceipt, AnalysisRequest, AnalysisWarning
from .daily import _safe_code, _safety_base, daily_primary_item_contract
from .harness import SchemaEvidence, resolve_harness_bundle
from .publisher import AnalysisPublisher, RunEvidence
from .quality_gate import QualityGate, QualityGateRequest
from .result_validation import AnalysisResultValidationError, ResultValidationExpectation
from .run_state import AnalysisRunCoordinator, AnalysisRunStateError
from .stable_views import StableViewRepository
from .weekly import _periods, _prior_artifact_state, _plan_adherence, weekly_plan_contract

_REASONS = frozenset({"source_revision_changed", "policy_version_changed", "harness_version_changed", "quality_issue_resolved", "explicit_user_request", "operator_correction"})

class _Runner(Protocol):
    def execute(self, bundle: Any, canonical_context: bytes) -> Any: ...

class _Delivery(Protocol):
    def create_pending(self, **kwargs: Any) -> Any: ...

def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

def regeneration_contract(source: Mapping[str, Any], reason_code: str) -> Mapping[str, Any]:
    return {
        "key": "regeneration_contract_v1",
        "algorithm_version": "regeneration-contract-v1",
        "value_origin": "derived_statistic",
        "input_revision_ids": [],
        "contract_version": "1",
        "source_artifact_id": str(source["artifact_id"]),
        "source_artifact_kind": str(source["kind"]),
        "source_shape": str(source["shape"]),
        "reason_code": reason_code,
        "period": {
            "start_local_date": str(source["start"]),
            "end_local_date": str(source["end"]),
        },
        "delivery_recovery_forbidden": True,
    }

class RegenerateRoute:
    def __init__(self, *, config: AnalysisConfig, coordinator: AnalysisRunCoordinator, stable_views: StableViewRepository, runner: _Runner, publisher: AnalysisPublisher, delivery: _Delivery, connection: sqlite3.Connection, context_builder: AnalysisContextBuilder | None = None, quality_gate: QualityGate | None = None, validator: Any | None = None, harness_resolver: Any = resolve_harness_bundle, clock: Any = _now) -> None:
        self.config, self.coordinator, self.stable_views, self.runner = config, coordinator, stable_views, runner
        self.publisher, self.delivery, self.connection = publisher, delivery, connection
        self.context_builder, self.quality_gate, self.validator = context_builder or AnalysisContextBuilder(), quality_gate or QualityGate(), validator
        self.harness_resolver, self.clock = harness_resolver, clock

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        started = self.clock(); prepared = None
        try:
            request.validate()
            self._validate_request(request)
            prepared = self.coordinator.begin(request)
        except AnalysisRunStateError as error:
            code = _safe_code(error, "analysis_regeneration_begin_failed")
            return self._receipt(request, "lock_busy" if code == "analysis_lock_busy" else "failed", started, errors=(self._error("service", code),))
        except ValueError as error:
            return self._receipt(request, "rejected", started, errors=(self._error("request", _safe_code(error, "analysis_regeneration_request_invalid")),))
        except Exception as error:
            return self._receipt(request, "failed", started, errors=(self._error("request", _safe_code(error, "analysis_regeneration_request_invalid")),))
        if prepared.decision.action == "unchanged":
            return self._persisted_receipt(request, prepared, started)
        try:
            source = self._source(request)
            return self._run(request, source, prepared, started)
        except ValueError as error:
            try:
                self.coordinator.finish(prepared, "rejected")
            except AnalysisRunStateError:
                pass
            return self._receipt(
                request,
                "rejected",
                started,
                run_key=prepared.decision.run_key,
                analysis_run_id=str(prepared.decision.run_id),
                errors=(
                    self._error(
                        "request",
                        _safe_code(
                            error, "analysis_regeneration_request_invalid"
                        ),
                    ),
                ),
            )
        except Exception as error:
            try: self.coordinator.finish(prepared, "failed")
            except AnalysisRunStateError: pass
            return self._receipt(request, "failed", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), errors=(self._error("service", _safe_code(error, "analysis_regeneration_failed")),))

    @staticmethod
    def _validate_request(request: AnalysisRequest) -> None:
        if (
            request.mode != "regenerate"
            or request.artifact_id is None
            or not request.artifact_id.isdecimal()
            or int(request.artifact_id) <= 0
            or request.regeneration_reason_code not in _REASONS
        ):
            raise ValueError("analysis_regeneration_request_invalid")

    def _persisted_receipt(
        self, request: AnalysisRequest, prepared: Any, started: str
    ) -> AnalysisReceipt:
        run_id = int(prepared.decision.run_id)
        run = self.connection.execute(
            "SELECT harness_version,input_schema_version,output_schema_version,"
            "context_snapshot_sha256 FROM analysis_runs WHERE id=? AND status='succeeded'",
            (run_id,),
        ).fetchone()
        artifacts = self.connection.execute(
            "SELECT id,artifact_kind,period_start_local_date,period_end_local_date,"
            "supersedes_artifact_id FROM analysis_artifacts "
            "WHERE generated_by_run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        if run is None or not artifacts:
            raise RuntimeError("analysis_regeneration_persisted_result_unavailable")
        periods: dict[str, Any] = {
            "summary": None, "advice": None, "review": None, "plan": None
        }
        artifact_ids: list[str] = []
        plan_artifact_id: int | None = None
        superseded_artifact_id: int | None = None
        for row in artifacts:
            artifact_ids.append(str(row["id"]))
            period = {
                "start_local_date": row["period_start_local_date"],
                "end_local_date": row["period_end_local_date"],
            }
            if row["artifact_kind"] == "daily_summary":
                periods["summary"] = period
            elif row["artifact_kind"] == "daily_training_advice":
                periods["advice"] = period
            elif row["artifact_kind"] == "weekly_summary":
                periods["review"] = period
            elif row["artifact_kind"] == "weekly_training_plan":
                periods["plan"] = period
                plan_artifact_id = int(row["id"])
                if row["supersedes_artifact_id"] is not None:
                    superseded_artifact_id = int(row["supersedes_artifact_id"])
        training_plan_id = None
        superseded_plan_id = None
        if plan_artifact_id is not None:
            plan = self.connection.execute(
                "SELECT id FROM training_plans WHERE analysis_artifact_id=?",
                (plan_artifact_id,),
            ).fetchone()
            training_plan_id = str(plan["id"]) if plan is not None else None
        if superseded_artifact_id is not None:
            old_plan = self.connection.execute(
                "SELECT id FROM training_plans WHERE analysis_artifact_id=?",
                (superseded_artifact_id,),
            ).fetchone()
            superseded_plan_id = (
                str(old_plan["id"]) if old_plan is not None else None
            )
        comparison = self.connection.execute(
            "SELECT successor.content_sha256=source.content_sha256 AS content_same "
            "FROM analysis_artifact_relations relation "
            "JOIN analysis_artifacts successor ON successor.id=relation.from_artifact_id "
            "JOIN analysis_artifacts source ON source.id=relation.to_artifact_id "
            "WHERE successor.generated_by_run_id=? "
            "AND relation.relation_type='derived_from' ORDER BY successor.id",
            (run_id,),
        ).fetchall()
        content_same = (
            bool(comparison[0]["content_same"]) if len(comparison) == 1 else None
        )
        return self._receipt(
            request,
            "unchanged",
            started,
            run_key=prepared.decision.run_key,
            analysis_run_id=str(run_id),
            target_periods=periods,
            quality="ready",
            artifact_ids=tuple(artifact_ids),
            training_plan_id=training_plan_id,
            superseded_plan_id=superseded_plan_id,
            input_hash=run["context_snapshot_sha256"],
            harness=run["harness_version"],
            content_same=content_same,
            next_action="none",
        )

    def _source(self, request: AnalysisRequest) -> dict[str, Any]:
        self._validate_request(request)
        row = self.connection.execute("SELECT a.id,a.subject_id,a.artifact_kind,a.period_start_local_date,a.period_end_local_date,a.generated_by_run_id,a.is_current,r.analysis_kind,s.subject_key FROM analysis_artifacts a JOIN analysis_runs r ON r.id=a.generated_by_run_id JOIN data_subjects s ON s.id=a.subject_id WHERE a.id=?", (int(request.artifact_id),)).fetchone()
        if row is None or row["subject_key"] != request.subject_id or row["is_current"] != 1:
            raise ValueError("analysis_regeneration_target_unavailable")
        kind, run_kind = row["artifact_kind"], row["analysis_kind"]
        if kind in {"daily_summary", "daily_training_advice"}: shape = "daily"
        elif kind in {"weekly_summary", "weekly_training_plan"} and run_kind == "weekly": shape = "weekly"
        elif kind == "weekly_training_plan" and run_kind == "plan_revision": shape = "plan_revision"
        else: raise ValueError("analysis_regeneration_target_unsupported")
        return {"artifact_id": int(row["id"]), "subject_id": int(row["subject_id"]), "shape": shape, "kind": kind, "start": row["period_start_local_date"], "end": row["period_end_local_date"]}

    def _run(self, request: AnalysisRequest, source: Mapping[str, Any], prepared: Any, started: str) -> AnalysisReceipt:
        shape = str(source["shape"]); subject_id = int(source["subject_id"])
        if shape == "daily":
            target_day = date.fromisoformat(str(source["start"]))
            if source["kind"] == "daily_training_advice":
                advice = target_day.isoformat()
                summary = (target_day - timedelta(days=1)).isoformat()
            else:
                summary = target_day.isoformat()
                advice = (target_day + timedelta(days=1)).isoformat()
            context_request = ContextBuildRequest(route="regenerate", regenerate_source_route="daily", run_key=prepared.decision.run_key, subject_id=subject_id, as_of_utc=request.requested_at_utc, summary_local_date=summary, advice_local_date=advice, artifact_id=int(source["artifact_id"]), max_context_bytes=self.config.max_context_bytes)
            periods = {"summary": {"start_local_date": summary, "end_local_date": summary}, "advice": {"start_local_date": advice, "end_local_date": advice}}
            gate_kind, feature = "daily_summary", daily_primary_item_contract()
        else:
            if shape == "weekly" and source["kind"] == "weekly_summary":
                anchor = date.fromisoformat(str(source["end"])) + timedelta(days=1)
            else:
                anchor = date.fromisoformat(str(source["start"]))
            review, plan = _periods(anchor.isoformat())
            review_end = review["end_local_date"]
            context_request = ContextBuildRequest(route="regenerate", regenerate_source_route="weekly", run_key=prepared.decision.run_key, subject_id=subject_id, as_of_utc=request.requested_at_utc, review_end_local_date=review_end, artifact_id=int(source["artifact_id"]), max_context_bytes=self.config.max_context_bytes)
            periods = {"review": review, "plan": plan}; gate_kind, feature = "weekly_summary", None
        start, end = context_request.repository_window(); snapshot = self.stable_views.snapshot(subject_id, start, end)
        gate = self.quality_gate.evaluate(QualityGateRequest(gate_kind, subject_id, (periods.get("summary") or periods["review"])["start_local_date"], (periods.get("summary") or periods["review"])["end_local_date"], request.requested_at_utc), snapshot)
        if gate.state == "blocked":
            self.coordinator.finish(prepared, "failed")
            return self._receipt(request, "deferred", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), target_periods=self._complete_target_periods(periods), quality=gate.state, warnings=tuple(AnalysisWarning(x.code, x.entity, x.summary) for x in gate.blockers), next_action=gate.next_action)
        output_sha = sha256(Path(self.config.output_schema).read_bytes()).hexdigest(); bundle = self.harness_resolver(self.config, "regenerate", SchemaEvidence(ANALYSIS_INPUT_SCHEMA_VERSION, ANALYSIS_INPUT_SCHEMA_SHA256, "1", output_sha))
        route_feature = regeneration_contract(
            source, str(request.regeneration_reason_code)
        )
        features = (
            (feature, route_feature)
            if feature is not None
            else (
                weekly_plan_contract(
                    _prior_artifact_state(snapshot, periods["review"])
                ),
                route_feature,
            )
        )
        built = self.context_builder.build(context_request, ContextSource(snapshot=snapshot), quality_gate=gate, harness_bundle=bundle, deterministic_features=features, plan_adherence=None if shape == "daily" else _plan_adherence(snapshot, periods["review"]))
        result = self.runner.execute(bundle, built.canonical_json.encode("utf-8"))
        safety = {} if shape == "daily" else { (date.fromisoformat(periods["plan"]["start_local_date"]) + timedelta(days=i)).isoformat(): _safety_base(subject_id, (date.fromisoformat(periods["plan"]["start_local_date"]) + timedelta(days=i)).isoformat(), request.requested_at_utc, snapshot) for i in range(7) }
        expected = ResultValidationExpectation(prepared.decision.run_key, "regenerate", subject_id, periods, built.context["input_manifest"], gate.as_dict(), _safety_base(subject_id, periods["advice"]["start_local_date"], request.requested_at_utc, snapshot) if shape == "daily" else {}, weekly_safety_request_bases=safety or None, prior_artifact_state=None if shape != "weekly" else _prior_artifact_state(snapshot, periods["review"]), regeneration_source_shape=shape, regeneration_source_artifact_id=str(source["artifact_id"]))
        validator = self.validator
        if validator is None:
            from .result_validation import AnalysisResultValidator
            validator = AnalysisResultValidator()
        try: accepted = validator.validate(result.output_bytes, expected)
        except AnalysisResultValidationError as error:
            self.coordinator.finish(prepared, "rejected")
            return self._receipt(request, "rejected", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), target_periods=self._complete_target_periods(periods), quality=gate.state, errors=(self._error("service", error.code),))
        evidence = RunEvidence(bundle.harness_version, ANALYSIS_INPUT_SCHEMA_VERSION, "1", built.context, built.context_snapshot_sha256, dict(getattr(result, "audit", {})))
        delivery_kind = "daily_report" if shape == "daily" else ("weekly_report" if shape == "weekly" else "plan_revision")
        published, pending = self.publisher.publish_with_pending_delivery(
            run_id=prepared.decision.run_id,
            accepted=accepted,
            input_manifest=built.context["input_manifest"],
            run_evidence=evidence,
            regeneration_source=source,
            delivery_factory=self.delivery,
            delivery_kind=delivery_kind,
        )
        self.coordinator.finish(prepared, "succeeded")
        ids = tuple(str(getattr(x, "artifact_id", "")) for x in getattr(pending, "artifacts", ()))
        delivery = AnalysisDelivery(str(getattr(pending, "delivery_id")), "pending", ids)
        superseded = tuple(getattr(published, "superseded_plan_ids", ()))
        return self._receipt(request, "partial", started, run_key=prepared.decision.run_key, analysis_run_id=str(prepared.decision.run_id), target_periods=self._complete_target_periods(periods), quality=gate.state, artifact_ids=tuple(str(v) for v in published.artifact_ids.values()), training_plan_id=str(published.training_plan_id) if published.training_plan_id else None, superseded_plan_id=str(superseded[0]) if superseded else None, delivery=delivery, input_hash=built.context_snapshot_sha256, harness=bundle.harness_version, content_same=published.content_same, next_action="retry_delivery")

    @staticmethod
    def _error(stage: str, code: str) -> AnalysisError: return AnalysisError(stage, code, code.replace("_", " "))
    @staticmethod
    def _complete_target_periods(periods: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "summary": periods.get("summary"),
            "advice": periods.get("advice"),
            "review": periods.get("review"),
            "plan": periods.get("plan"),
        }

    @staticmethod
    def _target_periods(source: Mapping[str, Any]) -> dict[str, Any]:
        start = date.fromisoformat(str(source["start"]))
        if source["shape"] == "daily":
            if source["kind"] == "daily_training_advice":
                summary, advice = start - timedelta(days=1), start
            else:
                summary, advice = start, start + timedelta(days=1)
            return {
                "summary": {"start_local_date": summary.isoformat(), "end_local_date": summary.isoformat()},
                "advice": {"start_local_date": advice.isoformat(), "end_local_date": advice.isoformat()},
                "review": None,
                "plan": None,
            }
        anchor = date.fromisoformat(str(source["end"])) + timedelta(days=1) if source["shape"] == "weekly" and source["kind"] == "weekly_summary" else start
        review, plan = _periods(anchor.isoformat())
        return {"summary": None, "advice": None, "review": review, "plan": plan}

    def _receipt(self, request: AnalysisRequest, status: str, started: str, *, run_key: str | None = None, analysis_run_id: str | None = None, target_periods: dict[str, Any] | None = None, quality: str = "blocked", artifact_ids: tuple[str, ...] = (), training_plan_id: str | None = None, superseded_plan_id: str | None = None, delivery: AnalysisDelivery | None = None, input_hash: str | None = None, harness: str | None = None, content_same: bool | None = None, warnings: tuple[AnalysisWarning, ...] = (), errors: tuple[AnalysisError, ...] = (), next_action: str = "operator_review") -> AnalysisReceipt:
        return AnalysisReceipt(run_key or "analysis:invalid:regenerate:invalid:invalid", request.invocation_id, "regenerate", status, started, self.clock(), analysis_run_id=analysis_run_id, target_periods=target_periods or {"summary": None, "advice": None, "review": None, "plan": None}, quality_gate_state=quality, artifact_ids=artifact_ids, training_plan_id=training_plan_id, superseded_plan_id=superseded_plan_id, delivery=delivery, input_snapshot_sha256=input_hash, harness_version=harness, input_schema_version=ANALYSIS_INPUT_SCHEMA_VERSION if input_hash else None, output_schema_version="1" if input_hash else None, content_same=content_same, warnings=warnings, errors=errors, next_action=next_action)

RegenerateRouteService = RegenerateRoute
