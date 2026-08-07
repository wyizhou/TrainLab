"""S5-08/09 typed morning and Monday workflow orchestration.

This module owns neither lower-layer persistence nor business payloads.  It
only builds fixed :class:`DownstreamCall` values and turns data-free receipt
metadata into one conservative workflow result.  A caller that needs durable
crash recovery must persist the returned step identities through S5-05.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Mapping, Protocol
from zoneinfo import ZoneInfo

from .evidence_codes import downstream_failure_evidence
from .subprocess_runner import DownstreamCall, DownstreamResult


HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_TERMINAL_GOOD = frozenset({"succeeded", "unchanged"})
_RETRYABLE = frozenset({"partial", "deferred", "lock_busy"})


class AnalysisWorkflowError(ValueError):
    """A workflow input or lower receipt cannot safely be orchestrated."""


class DownstreamExecutor(Protocol):
    def run(self, call: DownstreamCall) -> DownstreamResult: ...


@dataclass(frozen=True, slots=True)
class AnalysisWorkflowRequest:
    """The fixed identity of a morning or Monday analysis workflow."""
    workflow_key: str
    subject_id: str
    logical_local_date: str
    requested_at_utc: datetime
    # ``sunday`` remains accepted only for replaying old receipts; production
    # scheduling and all new requests use ``monday``.
    workflow_kind: Literal["morning", "monday", "sunday"] = "morning"


@dataclass(frozen=True, slots=True)
class AnalysisWorkflowStep:
    step_key: str
    layer: Literal["garmin", "analysis"]
    mode: str
    invocation_id: str
    status: str
    receipt_sha256: str | None
    next_retry_at_utc: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisWorkflowResult:
    workflow_key: str
    status: Literal["succeeded", "partial", "deferred", "attention_required", "failed"]
    logical_local_date: str
    collection_snapshot_id: str | None
    quality_state: Literal["ready", "ready_with_warnings", "blocked"]
    steps: tuple[AnalysisWorkflowStep, ...]
    next_action: str
    next_retry_at_utc: str | None
    error_code: str | None = None


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise AnalysisWorkflowError("analysis_workflow_time_invalid")
    return value.astimezone(UTC)


def _date(value: str) -> date:
    if type(value) is not str:
        raise AnalysisWorkflowError("analysis_workflow_date_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AnalysisWorkflowError("analysis_workflow_date_invalid") from exc
    if parsed.isoformat() != value:
        raise AnalysisWorkflowError("analysis_workflow_date_invalid")
    return parsed


def _validate(request: AnalysisWorkflowRequest) -> tuple[date, datetime]:
    if type(request) is not AnalysisWorkflowRequest:
        raise AnalysisWorkflowError("analysis_workflow_request_invalid")
    if (not request.workflow_key or not request.subject_id
            or request.workflow_kind not in {"morning", "monday", "sunday"}):
        raise AnalysisWorkflowError("analysis_workflow_request_invalid")
    logical = _date(request.logical_local_date)
    now = _utc(request.requested_at_utc)
    if now.astimezone(HONG_KONG).date() != logical:
        raise AnalysisWorkflowError("analysis_workflow_logical_date_mismatch")
    if request.workflow_kind == "monday" and logical.weekday() != 0:
        raise AnalysisWorkflowError("analysis_workflow_monday_required")
    if request.workflow_kind == "sunday" and logical.weekday() != 6:
        raise AnalysisWorkflowError("analysis_workflow_sunday_required")
    return logical, now


def _invocation(key: str, step: str) -> str:
    # Stable, data-free, bounded ID: a retry/restart uses the exact same one.
    digest = hashlib.sha256((key + "\0" + step).encode()).hexdigest()[:24]
    return f"s5-{step}-{digest}"


def _hash(receipt: Mapping[str, Any] | None, fallback: str | None) -> str | None:
    if fallback is not None:
        return fallback
    if receipt is None:
        return None
    return hashlib.sha256(json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _step(key: str, layer: Literal["garmin", "analysis"], mode: str, result: DownstreamResult) -> AnalysisWorkflowStep:
    receipt = result.receipt
    status = "failed" if result.kind != "accepted" or receipt is None else str(receipt.get("status", "failed"))
    retry = receipt.get("next_retry_at_utc") if receipt is not None else None
    return AnalysisWorkflowStep(
        key, layer, mode,
        _invocation(key.split("/", 1)[0], key.split("/", 1)[1]),
        status, _hash(receipt, result.receipt_sha256),
        retry if type(retry) is str else None,
        None if result.kind == "accepted" else downstream_failure_evidence(result.error_code),
    )


def _run(executor: DownstreamExecutor, workflow_key: str, step_key: str, **kwargs: Any) -> tuple[DownstreamResult, AnalysisWorkflowStep]:
    call = DownstreamCall(invocation_id=_invocation(workflow_key, step_key), request_sha256=None, **kwargs)
    result = executor.run(call)
    receipt = result.receipt
    status = "failed" if result.kind != "accepted" or receipt is None else str(receipt.get("status", "failed"))
    retry = receipt.get("next_retry_at_utc") if receipt else None
    return result, AnalysisWorkflowStep(
        step_key, kwargs["layer"], kwargs["mode"], call.invocation_id or "",
        status, _hash(receipt, result.receipt_sha256),
        retry if type(retry) is str else None,
        None if result.kind == "accepted" else downstream_failure_evidence(result.error_code),
    )


def _receipt(result: DownstreamResult) -> Mapping[str, Any] | None:
    return result.receipt if result.kind == "accepted" and result.receipt is not None else None


def _quality(
    collection: Mapping[str, Any] | None,
    audit: Mapping[str, Any] | None,
) -> Literal["ready", "ready_with_warnings", "blocked"]:
    if (
        collection is None
        or collection.get("status") not in _TERMINAL_GOOD
        or collection.get("coverage_state") != "complete"
        or audit is None
        or audit.get("status") not in _TERMINAL_GOOD
    ):
        return "blocked"
    if audit.get("open_gap_count") != 0:
        return "blocked"
    collection_counts = collection.get("counts")
    audit_counts = audit.get("counts")
    if type(collection_counts) is not dict or type(audit_counts) is not dict:
        return "blocked"
    warning_count = sum(
        int(counts.get(key, 0))
        for counts in (collection_counts, audit_counts)
        for key in ("not_available", "not_enabled")
    )
    return "ready_with_warnings" if warning_count else "ready"


def _stop(request: AnalysisWorkflowRequest, steps: list[AnalysisWorkflowStep], quality: Literal["ready", "ready_with_warnings", "blocked"], status: str) -> AnalysisWorkflowResult:
    # Sunday may complete weekly after a daily failure.  The retry identity is
    # therefore the failed step, not simply the last step in execution order.
    last = next((item for item in reversed(steps) if item.status == status), steps[-1] if steps else None)
    if status in _RETRYABLE:
        return AnalysisWorkflowResult(request.workflow_key, "deferred", request.logical_local_date, None, quality, tuple(steps), "retry_step", last.next_retry_at_utc if last else None, last.error_code if last else None)
    if status == "auth_required":
        return AnalysisWorkflowResult(request.workflow_key, "attention_required", request.logical_local_date, None, quality, tuple(steps), "authenticate_garmin", None, last.error_code if last else None)
    return AnalysisWorkflowResult(request.workflow_key, "failed", request.logical_local_date, None, quality, tuple(steps), "operator_review", None, last.error_code if last else None)


class MorningWorkflowService:
    """Run at most one bounded collection/repair/daily chain for one date."""

    def __init__(self, executor: DownstreamExecutor, *, max_repair_attempts: int = 1) -> None:
        if type(max_repair_attempts) is not int or not 0 <= max_repair_attempts <= 1:
            raise AnalysisWorkflowError("analysis_workflow_repair_budget_invalid")
        self._executor, self._max_repair_attempts = executor, max_repair_attempts
        self._completed: dict[str, AnalysisWorkflowResult] = {}

    def execute(self, request: AnalysisWorkflowRequest) -> AnalysisWorkflowResult:
        logical, _ = _validate(request)
        if request.workflow_key in self._completed:
            return self._completed[request.workflow_key]
        yesterday = (logical - timedelta(days=1)).isoformat()
        today = logical.isoformat()
        steps: list[AnalysisWorkflowStep] = []
        collected, collect_step = _run(self._executor, request.workflow_key, "collect", layer="garmin", mode="incremental", through_local_date=yesterday)
        steps.append(collect_step)
        collection = _receipt(collected)
        if collect_step.status not in _TERMINAL_GOOD:
            return _stop(request, steps, "blocked", collect_step.status)
        # A completed-day incremental run deliberately stops at yesterday.
        # Fetch today's live snapshot separately so the analysis can see a
        # sleep session that ended this morning without pretending that the
        # still-open current day is complete or advancing completed-day
        # cursors.  Snapshot coverage is therefore not part of `_quality`;
        # only its execution status is required here.
        _current, current_step = _run(
            self._executor,
            request.workflow_key,
            "current_snapshot",
            layer="garmin",
            mode="snapshot",
            snapshot_local_date=today,
        )
        steps.append(current_step)
        if current_step.status not in _TERMINAL_GOOD:
            return _stop(request, steps, "blocked", current_step.status)
        audited, audit_step = _run(self._executor, request.workflow_key, "quality", layer="garmin", mode="audit", health_from_local_date=yesterday, through_local_date=yesterday)
        steps.append(audit_step)
        quality_receipt = _receipt(audited)
        if audit_step.status not in _TERMINAL_GOOD:
            return _stop(request, steps, "blocked", audit_step.status)
        quality = _quality(collection, quality_receipt)
        if quality == "blocked" and self._max_repair_attempts:
            repaired, repair_step = _run(self._executor, request.workflow_key, "repair", layer="garmin", mode="repair", health_from_local_date=yesterday, through_local_date=yesterday, repair_strategy="auto")
            steps.append(repair_step)
            if repair_step.status not in _TERMINAL_GOOD:
                return _stop(request, steps, "blocked", repair_step.status)
            audited, audit_step = _run(self._executor, request.workflow_key, "quality_after_repair", layer="garmin", mode="audit", health_from_local_date=yesterday, through_local_date=yesterday)
            steps.append(audit_step); quality_receipt = _receipt(audited); quality = _quality(collection, quality_receipt)
        if quality == "blocked":
            return AnalysisWorkflowResult(request.workflow_key, "deferred", today, None, quality, tuple(steps), "repair_data", None)
        return self._analyse(request, steps, quality, collection, yesterday, today)

    def _analyse(self, request: AnalysisWorkflowRequest, steps: list[AnalysisWorkflowStep], quality: Literal["ready", "ready_with_warnings"], collection: Mapping[str, Any] | None, yesterday: str, today: str) -> AnalysisWorkflowResult:
        daily, daily_step = _run(self._executor, request.workflow_key, "daily", layer="analysis", mode="daily", subject_id=request.subject_id, summary_local_date=yesterday, advice_local_date=today)
        steps.append(daily_step)
        if daily_step.status in _TERMINAL_GOOD:
            result = AnalysisWorkflowResult(request.workflow_key, "succeeded", today, str(collection.get("run_id")) if collection and collection.get("run_id") else None, quality, tuple(steps), "none", None)
            self._completed[request.workflow_key] = result
            return result
        return _stop(request, steps, quality, daily_step.status)


class MondayWorkflowService(MorningWorkflowService):
    """Monday collection snapshot followed by independent daily and weekly calls."""

    def execute(self, request: AnalysisWorkflowRequest) -> AnalysisWorkflowResult:
        if request.workflow_kind not in {"monday", "sunday"}:
            raise AnalysisWorkflowError("analysis_workflow_monday_kind_required")
        logical, _ = _validate(request)
        if request.workflow_key in self._completed:
            return self._completed[request.workflow_key]
        yesterday, today = (logical - timedelta(days=1)).isoformat(), logical.isoformat()
        steps: list[AnalysisWorkflowStep] = []
        collected, item = _run(self._executor, request.workflow_key, "collect", layer="garmin", mode="incremental", through_local_date=yesterday); steps.append(item)
        collection = _receipt(collected)
        if item.status not in _TERMINAL_GOOD: return _stop(request, steps, "blocked", item.status)
        _current, item = _run(self._executor, request.workflow_key, "current_snapshot", layer="garmin", mode="snapshot", snapshot_local_date=today); steps.append(item)
        if item.status not in _TERMINAL_GOOD: return _stop(request, steps, "blocked", item.status)
        audited, item = _run(self._executor, request.workflow_key, "quality", layer="garmin", mode="audit", health_from_local_date=yesterday, through_local_date=yesterday); steps.append(item)
        quality = _quality(collection, _receipt(audited))
        if item.status not in _TERMINAL_GOOD: return _stop(request, steps, "blocked", item.status)
        if quality == "blocked" and self._max_repair_attempts:
            repaired, item = _run(self._executor, request.workflow_key, "repair", layer="garmin", mode="repair", health_from_local_date=yesterday, through_local_date=yesterday, repair_strategy="auto"); steps.append(item)
            if item.status not in _TERMINAL_GOOD: return _stop(request, steps, "blocked", item.status)
            audited, item = _run(self._executor, request.workflow_key, "quality_after_repair", layer="garmin", mode="audit", health_from_local_date=yesterday, through_local_date=yesterday); steps.append(item)
            quality = _quality(collection, _receipt(audited))
            if item.status not in _TERMINAL_GOOD: return _stop(request, steps, "blocked", item.status)
        if quality == "blocked": return AnalysisWorkflowResult(request.workflow_key, "deferred", today, None, quality, tuple(steps), "repair_data", None)
        _daily, item = _run(self._executor, request.workflow_key, "daily", layer="analysis", mode="daily", subject_id=request.subject_id, summary_local_date=yesterday, advice_local_date=today); steps.append(item)
        _weekly, weekly = _run(self._executor, request.workflow_key, "weekly", layer="analysis", mode="weekly", subject_id=request.subject_id, as_of_local_date=today); steps.append(weekly)
        snapshot = str(collection.get("run_id")) if collection and collection.get("run_id") else None
        if weekly.status in _TERMINAL_GOOD and item.status in _TERMINAL_GOOD:
            result = AnalysisWorkflowResult(request.workflow_key, "succeeded", today, snapshot, quality, tuple(steps), "none", None); self._completed[request.workflow_key] = result; return result
        # Daily and weekly are independent: a partial one preserves the other
        # accepted artifact and recovery targets only the unfinished step.
        bad = weekly if weekly.status not in _TERMINAL_GOOD else item
        return _stop(request, steps, quality, bad.status)


# Compatibility alias for old callers and historical receipts.  New routing
# must use ``MondayWorkflowService`` and the ``monday`` workflow kind.
SundayWorkflowService = MondayWorkflowService
