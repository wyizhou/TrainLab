"""Pure workflow-definition and domain-state projection codec for S5-05A1a.

This module deliberately has no persistence, transition, or recovery behavior.
It defines the immutable identity of a workflow and its steps, maps the richer
domain states to Foundation's compatibility columns, and provides one strict,
canonical JSON representation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Final, Literal, Mapping, NoReturn, cast

from .repository import OrchestrationRepositoryError


WorkflowDomainState = Literal[
    "queued",
    "running",
    "succeeded",
    "partial",
    "deferred",
    "attention_required",
    "failed",
    "cancelled",
]
WorkflowStorageState = Literal[
    "started",
    "succeeded",
    "partial",
    "deferred",
    "failed",
    "cancelled",
]
StepDomainState = Literal[
    "pending",
    "running",
    "succeeded",
    "unchanged",
    "partial",
    "deferred",
    "lock_busy",
    "auth_required",
    "rejected",
    "failed",
    "skipped",
]
StepStorageState = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "deferred",
    "skipped",
]

DOMAIN_STATE_VERSION: Final = "domain_state_v1"
MAX_STEPS: Final = 64
MAX_ENCODED_CHARACTERS: Final = 262_144

WORKFLOW_STORAGE: Final[Mapping[WorkflowDomainState, WorkflowStorageState]] = (
    MappingProxyType(
        {
            "queued": "started",
            "running": "started",
            "succeeded": "succeeded",
            "partial": "partial",
            "deferred": "deferred",
            "attention_required": "partial",
            "failed": "failed",
            "cancelled": "cancelled",
        }
    )
)
STEP_STORAGE: Final[Mapping[StepDomainState, StepStorageState]] = MappingProxyType(
    {
        "pending": "pending",
        "running": "running",
        "succeeded": "succeeded",
        "unchanged": "succeeded",
        "partial": "failed",
        "deferred": "deferred",
        "lock_busy": "failed",
        "auth_required": "failed",
        "rejected": "failed",
        "failed": "failed",
        "skipped": "skipped",
    }
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_TEXT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$"
)

_DOCUMENT_KEYS: Final = frozenset(
    {"version", "definition_sha256", "workflow", "steps"}
)
_WORKFLOW_KEYS: Final = frozenset(
    {
        "workflow_key",
        "workflow_kind",
        "subject_id",
        "logical_local_date",
        "trigger_kind",
        "deadline_at_utc",
        "parent_workflow_run_id",
        "started_at_utc",
        "create_command_sha256",
        "create_evidence_sha256",
        "domain_state",
    }
)
_STEP_KEYS: Final = frozenset(
    {
        "step_key",
        "ordinal",
        "layer_no",
        "tool_mode",
        "request_sha256",
        "invocation_id",
        "downstream_run_id",
        "domain_state",
    }
)


class StateProjectionError(OrchestrationRepositoryError):
    """A projection is malformed, non-canonical, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """Immutable workflow identity plus its independently mutable domain state."""

    workflow_key: str
    workflow_kind: str
    subject_id: int | None
    logical_local_date: str | None
    trigger_kind: str
    deadline_at_utc: datetime | None
    parent_workflow_run_id: int | None
    started_at_utc: datetime
    create_command_sha256: str
    create_evidence_sha256: str
    domain_state: WorkflowDomainState


@dataclass(frozen=True, slots=True)
class StepDefinition:
    """Immutable step identity plus its independently mutable domain state."""

    step_key: str
    ordinal: int
    layer_no: int
    tool_mode: str
    request_sha256: str
    invocation_id: str | None
    downstream_run_id: str | None
    domain_state: StepDomainState


def _invalid() -> NoReturn:
    raise StateProjectionError("domain_state_projection_invalid")


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _invalid()
    return value


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid()
    return value


def _positive_optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        _invalid()
    return value


def _nonnegative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        _invalid()
    return value


def _layer_number(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 5:
        _invalid()
    return value


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return _identifier(value)


def _workflow_kind(value: object) -> str:
    return _identifier(value)


def _trigger_kind(value: object) -> str:
    return _identifier(value)


def _canonical_local_date(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _LOCAL_DATE.fullmatch(value) is None:
        _invalid()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _invalid()
    if parsed.isoformat() != value:
        _invalid()
    return value


def _canonical_utc(value: object) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        _invalid()
    try:
        offset = value.utcoffset()
    except (TypeError, ValueError, OverflowError):
        _invalid()
    if offset != UTC.utcoffset(None):
        _invalid()
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _parse_canonical_utc(value: object) -> datetime:
    if type(value) is not str or _UTC_TEXT.fullmatch(value) is None:
        _invalid()
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _invalid()
    if _canonical_utc(parsed) != value:
        _invalid()
    return parsed


def workflow_storage_state(state: object) -> WorkflowStorageState:
    """Return the exact Foundation-compatible state for a domain workflow state."""

    if type(state) is not str or state not in WORKFLOW_STORAGE:
        _invalid()
    domain_state = cast(WorkflowDomainState, state)
    return WORKFLOW_STORAGE[domain_state]


def step_storage_state(state: object) -> StepStorageState:
    """Return the exact Foundation-compatible state for a domain step state."""

    if type(state) is not str or state not in STEP_STORAGE:
        _invalid()
    domain_state = cast(StepDomainState, state)
    return STEP_STORAGE[domain_state]


def _workflow_domain_state(value: object) -> WorkflowDomainState:
    workflow_storage_state(value)
    return cast(WorkflowDomainState, value)


def _step_domain_state(value: object) -> StepDomainState:
    step_storage_state(value)
    return cast(StepDomainState, value)


def validate(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
) -> None:
    """Validate an in-memory definition without performing any external action."""

    if type(workflow) is not WorkflowDefinition or type(steps) is not tuple:
        _invalid()
    if not 1 <= len(steps) <= MAX_STEPS:
        _invalid()

    _identifier(workflow.workflow_key)
    _workflow_kind(workflow.workflow_kind)
    _positive_optional_integer(workflow.subject_id)
    _canonical_local_date(workflow.logical_local_date)
    _trigger_kind(workflow.trigger_kind)
    deadline = (
        None
        if workflow.deadline_at_utc is None
        else _parse_canonical_utc(_canonical_utc(workflow.deadline_at_utc))
    )
    _positive_optional_integer(workflow.parent_workflow_run_id)
    started = _parse_canonical_utc(_canonical_utc(workflow.started_at_utc))
    if deadline is not None and deadline < started:
        _invalid()
    _sha256(workflow.create_command_sha256)
    _sha256(workflow.create_evidence_sha256)
    _workflow_domain_state(workflow.domain_state)

    ordinals: list[int] = []
    step_keys: set[str] = set()
    for step in steps:
        if type(step) is not StepDefinition:
            _invalid()
        _identifier(step.step_key)
        ordinals.append(_nonnegative_integer(step.ordinal))
        _layer_number(step.layer_no)
        _identifier(step.tool_mode)
        _sha256(step.request_sha256)
        _optional_identifier(step.invocation_id)
        _optional_identifier(step.downstream_run_id)
        _step_domain_state(step.domain_state)
        if step.step_key in step_keys:
            _invalid()
        step_keys.add(step.step_key)

    if ordinals != list(range(len(steps))):
        _invalid()


def _workflow_document(
    workflow: WorkflowDefinition,
    *,
    include_state: bool,
) -> dict[str, object]:
    document: dict[str, object] = {
        "workflow_key": workflow.workflow_key,
        "workflow_kind": workflow.workflow_kind,
        "subject_id": workflow.subject_id,
        "logical_local_date": workflow.logical_local_date,
        "trigger_kind": workflow.trigger_kind,
        "deadline_at_utc": (
            None
            if workflow.deadline_at_utc is None
            else _canonical_utc(workflow.deadline_at_utc)
        ),
        "parent_workflow_run_id": workflow.parent_workflow_run_id,
        "started_at_utc": _canonical_utc(workflow.started_at_utc),
        "create_command_sha256": workflow.create_command_sha256,
        "create_evidence_sha256": workflow.create_evidence_sha256,
    }
    if include_state:
        document["domain_state"] = workflow.domain_state
    return document


def _step_document(
    step: StepDefinition,
    *,
    include_state: bool,
) -> dict[str, object]:
    document: dict[str, object] = {
        "step_key": step.step_key,
        "ordinal": step.ordinal,
        "layer_no": step.layer_no,
        "tool_mode": step.tool_mode,
        "request_sha256": step.request_sha256,
        "invocation_id": step.invocation_id,
        "downstream_run_id": step.downstream_run_id,
    }
    if include_state:
        document["domain_state"] = step.domain_state
    return document


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _invalid()


def definition_sha256(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
) -> str:
    """Hash every immutable workflow/step field and no mutable domain state."""

    validate(workflow, steps)
    immutable_definition = {
        "workflow": _workflow_document(workflow, include_state=False),
        "steps": [
            _step_document(step, include_state=False)
            for step in steps
        ],
    }
    return hashlib.sha256(
        _canonical_json(immutable_definition).encode("utf-8")
    ).hexdigest()


def encode(
    workflow: WorkflowDefinition,
    steps: tuple[StepDefinition, ...],
) -> str:
    """Encode a validated projection as its one canonical JSON spelling."""

    validate(workflow, steps)
    document = {
        "version": DOMAIN_STATE_VERSION,
        "definition_sha256": definition_sha256(workflow, steps),
        "workflow": _workflow_document(workflow, include_state=True),
        "steps": [
            _step_document(step, include_state=True)
            for step in steps
        ],
    }
    encoded = _canonical_json(document)
    if len(encoded) > MAX_ENCODED_CHARACTERS:
        _invalid()
    return encoded


def _object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _expect_keys(value: object, expected: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != expected:
        _invalid()
    return value


def _decode_workflow(document: dict[str, object]) -> WorkflowDefinition:
    deadline_value = document["deadline_at_utc"]
    return WorkflowDefinition(
        workflow_key=_identifier(document["workflow_key"]),
        workflow_kind=_workflow_kind(document["workflow_kind"]),
        subject_id=_positive_optional_integer(document["subject_id"]),
        logical_local_date=_canonical_local_date(document["logical_local_date"]),
        trigger_kind=_trigger_kind(document["trigger_kind"]),
        deadline_at_utc=(
            None
            if deadline_value is None
            else _parse_canonical_utc(deadline_value)
        ),
        parent_workflow_run_id=_positive_optional_integer(
            document["parent_workflow_run_id"]
        ),
        started_at_utc=_parse_canonical_utc(document["started_at_utc"]),
        create_command_sha256=_sha256(document["create_command_sha256"]),
        create_evidence_sha256=_sha256(document["create_evidence_sha256"]),
        domain_state=_workflow_domain_state(document["domain_state"]),
    )


def _decode_step(document: dict[str, object]) -> StepDefinition:
    return StepDefinition(
        step_key=_identifier(document["step_key"]),
        ordinal=_nonnegative_integer(document["ordinal"]),
        layer_no=_layer_number(document["layer_no"]),
        tool_mode=_identifier(document["tool_mode"]),
        request_sha256=_sha256(document["request_sha256"]),
        invocation_id=_optional_identifier(document["invocation_id"]),
        downstream_run_id=_optional_identifier(document["downstream_run_id"]),
        domain_state=_step_domain_state(document["domain_state"]),
    )


def decode(
    raw: str,
) -> tuple[WorkflowDefinition, tuple[StepDefinition, ...]]:
    """Decode only canonical, complete, and hash-consistent projections."""

    if type(raw) is not str or not raw or len(raw) > MAX_ENCODED_CHARACTERS:
        _invalid()
    try:
        document = json.loads(raw, object_pairs_hook=_object_without_duplicates)
    except StateProjectionError:
        raise
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _invalid()

    root = _expect_keys(document, _DOCUMENT_KEYS)
    if root["version"] != DOMAIN_STATE_VERSION:
        _invalid()
    _sha256(root["definition_sha256"])
    workflow_object = _expect_keys(root["workflow"], _WORKFLOW_KEYS)
    step_objects = root["steps"]
    if type(step_objects) is not list:
        _invalid()

    workflow = _decode_workflow(workflow_object)
    steps = tuple(
        _decode_step(_expect_keys(item, _STEP_KEYS))
        for item in step_objects
    )

    validate(workflow, steps)
    if definition_sha256(workflow, steps) != root["definition_sha256"]:
        _invalid()
    if encode(workflow, steps) != raw:
        _invalid()
    return workflow, steps


__all__ = [
    "DOMAIN_STATE_VERSION",
    "MAX_STEPS",
    "STEP_STORAGE",
    "WORKFLOW_STORAGE",
    "StateProjectionError",
    "StepDefinition",
    "StepDomainState",
    "StepStorageState",
    "WorkflowDefinition",
    "WorkflowDomainState",
    "WorkflowStorageState",
    "decode",
    "definition_sha256",
    "encode",
    "step_storage_state",
    "validate",
    "workflow_storage_state",
]
