"""Versioned, side-effect-free public contracts for the third-layer tool."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from jsonschema import Draft202012Validator, FormatChecker

REQUEST_SCHEMA_VERSION = RECEIPT_SCHEMA_VERSION = "1"
AnalysisMode = Literal["daily", "weekly", "revise_plan", "regenerate", "retry_delivery", "reconcile_delivery", "status"]
AnalysisStatus = Literal["succeeded", "unchanged", "partial", "deferred", "rejected", "failed", "lock_busy"]
class AnalysisContractError(ValueError): pass
def _schema(name: str) -> dict[str, Any]: return json.loads((Path(__file__).with_name("schemas") / name).read_text(encoding="utf-8"))
REQUEST_VALIDATOR = Draft202012Validator(_schema("analysis_request.schema.json"), format_checker=FormatChecker())
RECEIPT_VALIDATOR = Draft202012Validator(_schema("analysis_receipt.schema.json"), format_checker=FormatChecker())
def _validate(validator: Draft202012Validator, payload: dict[str, Any], kind: str) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]; location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise AnalysisContractError(f"analysis_{kind}_schema_invalid:{location}:{error.message}")
def _validate_date(value: str | None, field_name: str) -> None:
    if value is not None:
        try: date.fromisoformat(value)
        except ValueError as error: raise AnalysisContractError(f"analysis_request_date_invalid:{field_name}") from error
def _validate_utc(value: str) -> None:
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error: raise AnalysisContractError("analysis_request_requested_at_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0): raise AnalysisContractError("analysis_request_requested_at_not_utc")
@dataclass(frozen=True)
class AnalysisRequest:
    mode: AnalysisMode; subject_id: str; invocation_id: str | None; requested_at_utc: str
    run_key: str | None = None; summary_local_date: str | None = None; advice_local_date: str | None = None; as_of_local_date: str | None = None; plan_id: str | None = None; reason_event_id: str | None = None; effective_local_date: str | None = None; artifact_id: str | None = None; delivery_id: str | None = None; regeneration_reason_code: str | None = None; schema_version: str = REQUEST_SCHEMA_VERSION
    def as_dict(self) -> dict[str, Any]: return asdict(self)
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisRequest":
        _validate(REQUEST_VALIDATOR, payload, "request"); request = cls(**payload); request.validate(); return request
    def validate(self) -> None:
        _validate(REQUEST_VALIDATOR, self.as_dict(), "request")
        for name in ("summary_local_date", "advice_local_date", "as_of_local_date", "effective_local_date"): _validate_date(getattr(self, name), name)
        _validate_utc(self.requested_at_utc)
@dataclass(frozen=True)
class AnalysisWarning: code: str; entity: str; summary: str
@dataclass(frozen=True)
class AnalysisError: stage: Literal["request", "service", "receipt"]; code: str; summary: str
@dataclass(frozen=True)
class AnalysisDelivery:
    delivery_id: str; status: Literal["pending", "sending", "sent", "already_sent", "delivery_unknown", "failed"]; artifact_ids: tuple[str, ...]; provider_message_id: str | None = None; provider_thread_id: str | None = None; error: dict[str, str] | None = None
@dataclass(frozen=True)
class AnalysisReceipt:
    run_key: str; invocation_id: str | None; mode: AnalysisMode; status: AnalysisStatus; started_at_utc: str; completed_at_utc: str | None
    analysis_run_id: str | None = None; target_periods: dict[str, dict[str, str] | None] = field(default_factory=lambda: {"summary": None, "advice": None, "review": None, "plan": None}); quality_gate_state: Literal["ready", "ready_with_warnings", "blocked"] = "blocked"; artifact_ids: tuple[str, ...] = (); training_plan_id: str | None = None; superseded_plan_id: str | None = None; delivery: AnalysisDelivery | None = None; input_snapshot_sha256: str | None = None; harness_version: str | None = None; input_schema_version: str | None = None; output_schema_version: str | None = None; warnings: tuple[AnalysisWarning, ...] = (); errors: tuple[AnalysisError, ...] = (); next_action: Literal["none", "rerun_collection", "repair_data", "retry_delivery", "explicit_regeneration", "operator_review"] = "operator_review"; next_retry_at_utc: str | None = None; schema_version: str = RECEIPT_SCHEMA_VERSION
    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["artifact_ids"] = list(self.artifact_ids); payload["warnings"] = [asdict(x) for x in self.warnings]; payload["errors"] = [asdict(x) for x in self.errors]
        if self.delivery is not None: payload["delivery"]["artifact_ids"] = list(self.delivery.artifact_ids)
        return payload
    def validate(self) -> None: _validate(RECEIPT_VALIDATOR, self.as_dict(), "receipt")
    def to_json(self) -> str: self.validate(); return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def build_run_key(request: AnalysisRequest) -> str:
    request.validate()
    if request.mode == "status": return request.run_key or f"analysis:{request.subject_id}:status:current:read_only"
    # `:` is the run-key segment delimiter but remains legal in A3-02 IDs.
    # Source IDs never allow `%`, so this reversible canonical escape leaves
    # ordinary documented keys unchanged while preventing delimiter ambiguity.
    component = lambda value: str(value).replace(":", "%3A")
    if request.mode == "daily": target = request.summary_local_date or "default"
    elif request.mode == "weekly": target = request.as_of_local_date or "default"
    elif request.mode == "revise_plan": target = f"{component(request.plan_id)}:{component(request.reason_event_id)}"
    elif request.mode == "regenerate": target = component(request.artifact_id or "missing")
    else: target = component(request.delivery_id or "missing")
    return f"analysis:{request.subject_id}:{request.mode}:{target}:{component(request.invocation_id)}"
