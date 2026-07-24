"""Pure S5-05A2 domain transition tables and canonical event validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Mapping, cast

from .state_projection import (
    StateProjectionError,
    StepDomainState,
    WorkflowDomainState,
    _canonical_utc,
    _expect_keys,
    _identifier,
    _invalid,
    _parse_canonical_utc,
    _sha256,
    step_storage_state,
    workflow_storage_state,
)


WORKFLOW_TRANSITIONS: Final[Mapping[WorkflowDomainState, frozenset[WorkflowDomainState]]] = (
    MappingProxyType(
        {
            "queued": frozenset({"running", "cancelled"}),
            "running": frozenset(
                {
                    "succeeded",
                    "partial",
                    "deferred",
                    "attention_required",
                    "failed",
                    "cancelled",
                }
            ),
            "deferred": frozenset(
                {"running", "attention_required", "failed", "cancelled"}
            ),
            "succeeded": frozenset(),
            "partial": frozenset(),
            "attention_required": frozenset(),
            "failed": frozenset(),
            "cancelled": frozenset(),
        }
    )
)

STEP_TRANSITIONS: Final[Mapping[StepDomainState, frozenset[StepDomainState]]] = (
    MappingProxyType(
        {
            "pending": frozenset({"running", "skipped"}),
            "running": frozenset(
                {
                    "succeeded",
                    "unchanged",
                    "partial",
                    "deferred",
                    "lock_busy",
                    "auth_required",
                    "rejected",
                    "failed",
                }
            ),
            "deferred": frozenset({"running", "failed", "skipped"}),
            "lock_busy": frozenset({"running", "failed", "skipped"}),
            "succeeded": frozenset(),
            "unchanged": frozenset(),
            "partial": frozenset(),
            "auth_required": frozenset(),
            "rejected": frozenset(),
            "failed": frozenset(),
            "skipped": frozenset(),
        }
    )
)

WORKFLOW_TERMINAL_STATES: Final = frozenset(
    state for state, targets in WORKFLOW_TRANSITIONS.items() if not targets
)
STEP_TERMINAL_STATES: Final = frozenset(
    state for state, targets in STEP_TRANSITIONS.items() if not targets
)

MAX_WORKFLOW_EVENTS: Final = 64
MAX_STEP_EVENTS: Final = 32
MAX_ATTEMPTS: Final = 16
MAX_CONTROLLED_COUNTS: Final = 64

_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_NO_RECEIPT_EVIDENCE = frozenset(
    {
        "deterministic_check",
        "process_start_failed",
        "process_timeout",
        "provider_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowTransitionEvent:
    event_id: str
    to_state: WorkflowDomainState
    at_utc: datetime
    evidence_code: str


@dataclass(frozen=True, slots=True)
class StepTransitionEvent:
    event_id: str
    step_key: str
    to_state: StepDomainState
    at_utc: datetime
    receipt_sha256: str | None = None
    evidence_code: str | None = None
    next_retry_at_utc: datetime | None = None
    controlled_counts: Mapping[str, int] | tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowEventRecord:
    event_id: str
    from_state: WorkflowDomainState
    to_state: WorkflowDomainState
    at_utc: str
    evidence_code: str


@dataclass(frozen=True, slots=True)
class StepEventRecord:
    event_id: str
    step_key: str
    from_state: StepDomainState
    to_state: StepDomainState
    at_utc: str
    attempt: int
    receipt_sha256: str | None
    evidence_code: str | None
    next_retry_at_utc: str | None
    controlled_counts: tuple[tuple[str, int], ...]


def _code(value: object) -> str:
    if type(value) is not str or _CODE.fullmatch(value) is None:
        _invalid()
    return value


def _workflow_state(value: object) -> WorkflowDomainState:
    workflow_storage_state(value)
    return cast(WorkflowDomainState, value)


def _step_state(value: object) -> StepDomainState:
    step_storage_state(value)
    return cast(StepDomainState, value)


def _counts(value: object) -> tuple[tuple[str, int], ...]:
    if type(value) is dict:
        value = tuple(value.items())
    if type(value) is not tuple or len(value) > MAX_CONTROLLED_COUNTS:
        _invalid()
    result: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            _invalid()
        key, count = item
        key = _code(key)
        if (
            key in seen
            or type(count) is not int
            or not 0 <= count <= 1_000_000_000
        ):
            _invalid()
        seen.add(key)
        result.append((key, count))
    return tuple(sorted(result))


def _counts_from_json(value: object) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        _invalid()
    return _counts(tuple(value.items()))


def _optional_receipt(value: object) -> str | None:
    if value is None:
        return None
    return _sha256(value)


def _optional_evidence(value: object) -> str | None:
    if value is None:
        return None
    return _code(value)


def _optional_retry(value: object) -> str | None:
    if value is None:
        return None
    return _canonical_utc(value)


def _normalize_receipt_evidence(
    receipt: str | None,
    evidence: str | None,
) -> str | None:
    if receipt is not None:
        if evidence not in {None, "receipt_received"}:
            _invalid()
        return "receipt_received"
    return evidence


def normalize_workflow_event(
    event: WorkflowTransitionEvent,
    *,
    from_state: WorkflowDomainState,
) -> WorkflowEventRecord:
    if type(event) is not WorkflowTransitionEvent:
        _invalid()
    event_id = _identifier(event.event_id)
    to_state = _workflow_state(event.to_state)
    _workflow_state(from_state)
    if to_state not in WORKFLOW_TRANSITIONS[from_state]:
        raise StateProjectionError("workflow_domain_transition_invalid")
    return WorkflowEventRecord(
        event_id=event_id,
        from_state=from_state,
        to_state=to_state,
        at_utc=_canonical_utc(event.at_utc),
        evidence_code=_code(event.evidence_code),
    )


def normalize_step_event(
    event: StepTransitionEvent,
    *,
    from_state: StepDomainState,
    prior_attempt: int,
) -> StepEventRecord:
    if type(event) is not StepTransitionEvent:
        _invalid()
    event_id = _identifier(event.event_id)
    step_key = _identifier(event.step_key)
    to_state = _step_state(event.to_state)
    _step_state(from_state)
    if to_state not in STEP_TRANSITIONS[from_state]:
        raise StateProjectionError("step_domain_transition_invalid")
    if type(prior_attempt) is not int or not 0 <= prior_attempt <= MAX_ATTEMPTS:
        _invalid()

    at_utc = _canonical_utc(event.at_utc)
    receipt = _optional_receipt(event.receipt_sha256)
    evidence = _optional_evidence(event.evidence_code)
    retry = _optional_retry(event.next_retry_at_utc)
    counts = _counts(event.controlled_counts)
    evidence = _normalize_receipt_evidence(receipt, evidence)
    attempt = prior_attempt + (1 if to_state == "running" else 0)
    if attempt > MAX_ATTEMPTS:
        raise StateProjectionError("step_domain_attempt_limit")

    if to_state == "running":
        if receipt is not None or evidence is not None or retry is not None or counts:
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state in {"succeeded", "unchanged", "auth_required", "rejected"}:
        if receipt is None or evidence != "receipt_received" or retry is not None:
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state == "partial":
        if (
            receipt is None
            or evidence != "receipt_received"
            or retry is not None
        ):
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state == "lock_busy":
        if (
            receipt is None
            or evidence != "receipt_received"
            or retry is None
        ):
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state == "deferred":
        if receipt is not None:
            if evidence != "receipt_received" or retry is None:
                raise StateProjectionError("step_domain_event_payload_invalid")
        elif evidence not in _NO_RECEIPT_EVIDENCE:
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state == "failed":
        if receipt is not None:
            if evidence != "receipt_received" or retry is not None:
                raise StateProjectionError("step_domain_event_payload_invalid")
        elif evidence not in _NO_RECEIPT_EVIDENCE or retry is not None or counts:
            raise StateProjectionError("step_domain_event_payload_invalid")
    elif to_state == "skipped":
        if (
            receipt is not None
            or evidence not in _NO_RECEIPT_EVIDENCE
            or retry is not None
            or counts
        ):
            raise StateProjectionError("step_domain_event_payload_invalid")

    if retry is not None and _parse_canonical_utc(retry) <= _parse_canonical_utc(
        at_utc
    ):
        raise StateProjectionError("step_domain_event_retry_invalid")
    return StepEventRecord(
        event_id=event_id,
        step_key=step_key,
        from_state=from_state,
        to_state=to_state,
        at_utc=at_utc,
        attempt=attempt,
        receipt_sha256=receipt,
        evidence_code=evidence,
        next_retry_at_utc=retry,
        controlled_counts=counts,
    )


def workflow_record_document(record: WorkflowEventRecord) -> dict[str, object]:
    return {
        "event_id": record.event_id,
        "from_state": record.from_state,
        "to_state": record.to_state,
        "at_utc": record.at_utc,
        "evidence_code": record.evidence_code,
    }


def step_record_document(record: StepEventRecord) -> dict[str, object]:
    return {
        "event_id": record.event_id,
        "step_key": record.step_key,
        "from_state": record.from_state,
        "to_state": record.to_state,
        "at_utc": record.at_utc,
        "attempt": record.attempt,
        "receipt_sha256": record.receipt_sha256,
        "evidence_code": record.evidence_code,
        "next_retry_at_utc": record.next_retry_at_utc,
        "counts": dict(record.controlled_counts),
    }


def storage_summary_event(record: StepEventRecord) -> dict[str, object]:
    return {
        "attempt": record.attempt,
        "status": step_storage_state(record.to_state),
        "at_utc": record.at_utc,
        "counts": dict(record.controlled_counts),
        "receipt_sha256": record.receipt_sha256,
        "evidence_code": record.evidence_code,
        "next_retry_at_utc": record.next_retry_at_utc,
    }


def parse_workflow_history(
    value: object,
    *,
    started_at_utc: str,
) -> tuple[tuple[WorkflowEventRecord, ...], WorkflowDomainState]:
    if type(value) is not list or len(value) > MAX_WORKFLOW_EVENTS:
        _invalid()
    current: WorkflowDomainState = "queued"
    previous_time = _parse_canonical_utc(started_at_utc)
    records: list[WorkflowEventRecord] = []
    for index, item in enumerate(value):
        document = _expect_keys(
            item,
            frozenset(
                {
                    "event_id",
                    "from_state",
                    "to_state",
                    "at_utc",
                    "evidence_code",
                }
            ),
        )
        if _workflow_state(document["from_state"]) != current:
            _invalid()
        request = WorkflowTransitionEvent(
            event_id=_identifier(document["event_id"]),
            to_state=_workflow_state(document["to_state"]),
            at_utc=_parse_canonical_utc(document["at_utc"]),
            evidence_code=_code(document["evidence_code"]),
        )
        record = normalize_workflow_event(request, from_state=current)
        at = _parse_canonical_utc(record.at_utc)
        if (index == 0 and at < previous_time) or (
            index > 0 and at <= previous_time
        ):
            raise StateProjectionError("workflow_domain_event_time_invalid")
        if workflow_record_document(record) != document:
            _invalid()
        records.append(record)
        current = record.to_state
        previous_time = at
    return tuple(records), current


def parse_step_history(
    value: object,
    *,
    step_key: str,
    workflow_started_at_utc: str,
) -> tuple[tuple[StepEventRecord, ...], StepDomainState, int]:
    if type(value) is not list or len(value) > MAX_STEP_EVENTS:
        _invalid()
    current: StepDomainState = "pending"
    attempt = 0
    previous_time = _parse_canonical_utc(workflow_started_at_utc)
    records: list[StepEventRecord] = []
    for index, item in enumerate(value):
        document = _expect_keys(
            item,
            frozenset(
                {
                    "event_id",
                    "step_key",
                    "from_state",
                    "to_state",
                    "at_utc",
                    "attempt",
                    "receipt_sha256",
                    "evidence_code",
                    "next_retry_at_utc",
                    "counts",
                }
            ),
        )
        if _identifier(document["step_key"]) != step_key:
            _invalid()
        if _step_state(document["from_state"]) != current:
            _invalid()
        retry = (
            None
            if document["next_retry_at_utc"] is None
            else _parse_canonical_utc(document["next_retry_at_utc"])
        )
        request = StepTransitionEvent(
            event_id=_identifier(document["event_id"]),
            step_key=step_key,
            to_state=_step_state(document["to_state"]),
            at_utc=_parse_canonical_utc(document["at_utc"]),
            receipt_sha256=_optional_receipt(document["receipt_sha256"]),
            evidence_code=_optional_evidence(document["evidence_code"]),
            next_retry_at_utc=retry,
            controlled_counts=_counts_from_json(document["counts"]),
        )
        record = normalize_step_event(
            request,
            from_state=current,
            prior_attempt=attempt,
        )
        at = _parse_canonical_utc(record.at_utc)
        if (index == 0 and at < previous_time) or (
            index > 0 and at <= previous_time
        ):
            raise StateProjectionError("step_domain_event_time_invalid")
        if type(document["attempt"]) is not int or document["attempt"] != record.attempt:
            _invalid()
        if step_record_document(record) != document:
            _invalid()
        records.append(record)
        current = record.to_state
        attempt = record.attempt
        previous_time = at
    return tuple(records), current, attempt


__all__ = [
    "MAX_ATTEMPTS",
    "MAX_CONTROLLED_COUNTS",
    "MAX_STEP_EVENTS",
    "MAX_WORKFLOW_EVENTS",
    "STEP_TRANSITIONS",
    "STEP_TERMINAL_STATES",
    "WORKFLOW_TRANSITIONS",
    "WORKFLOW_TERMINAL_STATES",
    "StepEventRecord",
    "StepTransitionEvent",
    "WorkflowEventRecord",
    "WorkflowTransitionEvent",
    "normalize_step_event",
    "normalize_workflow_event",
    "parse_step_history",
    "parse_workflow_history",
    "step_record_document",
    "storage_summary_event",
    "workflow_record_document",
]
