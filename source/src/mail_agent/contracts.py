"""Stable, side-effect-free contracts for the fourth-layer Mail Agent.

M4-01 establishes only the public boundary.  Provider access, persistence,
Codex execution, delivery and recovery remain deliberately absent until their
respective development units are implemented.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, cast

MAIL_REQUEST_SCHEMA_VERSION = "1"
MAIL_RECEIPT_SCHEMA_VERSION = "1"

MailMode = Literal["run", "poll", "process", "deliver_response", "reconcile", "status"]
MailStatus = Literal[
    "succeeded",
    "unchanged",
    "partial",
    "deferred",
    "lock_busy",
    "auth_required",
    "rejected",
    "failed",
]


def mail_mode(value: str) -> MailMode:
    if value not in _MODES:
        raise ValueError("invalid_mail_mode")
    return cast(MailMode, value)


def mail_status(value: str) -> MailStatus:
    if value not in _STATUSES:
        raise ValueError("invalid_mail_receipt_status")
    return cast(MailStatus, value)


_MODES = frozenset(
    {"run", "poll", "process", "deliver_response", "reconcile", "status"}
)
_STATUSES = frozenset(
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
)
_EXIT_CODES = {
    "succeeded": 0,
    "unchanged": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "auth_required": 20,
    "rejected": 21,
    "failed": 22,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}_required")


def _non_negative(value: int | None, name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(f"{name}_must_be_non_negative_integer")


def _json_safe(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class MailRequest:
    """The complete public request surface; no provider or content fields exist."""

    mode: MailMode
    subject_id: int
    invocation_id: str
    requested_at_utc: str
    mail_message_ids: tuple[str, ...] = ()
    mail_response_artifact_ids: tuple[str, ...] = ()
    dependency_analysis_artifact_ids: tuple[str, ...] = ()
    mail_delivery_ids: tuple[str, ...] = ()
    run_key: str | None = None
    thread_id: str | None = None
    max_items: int | None = None
    max_threads: int | None = None
    deadline_seconds: int | None = None
    regeneration_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError("invalid_mail_mode")
        if (
            not isinstance(self.subject_id, int)
            or isinstance(self.subject_id, bool)
            or self.subject_id <= 0
        ):
            raise ValueError("subject_id_must_be_positive_integer")
        _non_empty(self.invocation_id, "invocation_id")
        _non_empty(self.requested_at_utc, "requested_at_utc")
        for name, identifiers in (
            ("mail_message_ids", self.mail_message_ids),
            ("mail_response_artifact_ids", self.mail_response_artifact_ids),
            ("dependency_analysis_artifact_ids", self.dependency_analysis_artifact_ids),
            ("mail_delivery_ids", self.mail_delivery_ids),
        ):
            if not isinstance(identifiers, tuple) or any(
                not isinstance(item, str) or not item for item in identifiers
            ):
                raise ValueError(f"{name}_must_be_tuple_of_non_empty_strings")
        _non_negative(self.max_items, "max_items")
        _non_negative(self.max_threads, "max_threads")
        _non_negative(self.deadline_seconds, "deadline_seconds")
        if self.thread_id is not None:
            _non_empty(self.thread_id, "thread_id")
        if self.run_key is not None:
            _non_empty(self.run_key, "run_key")
        if self.regeneration_reason_code is not None:
            _non_empty(self.regeneration_reason_code, "regeneration_reason_code")
        self._validate_mode_fields()

    def _validate_mode_fields(self) -> None:
        allowed: dict[str, set[str]] = {
            "run": {"max_items", "deadline_seconds"},
            "poll": {"max_threads"},
            "process": {
                "mail_message_ids",
                "dependency_analysis_artifact_ids",
                "regeneration_reason_code",
            },
            "deliver_response": {"mail_response_artifact_ids"},
            "reconcile": {"mail_delivery_ids"},
            "status": {"mail_message_ids", "run_key", "thread_id"},
        }
        values = {
            "mail_message_ids": self.mail_message_ids,
            "mail_response_artifact_ids": self.mail_response_artifact_ids,
            "dependency_analysis_artifact_ids": self.dependency_analysis_artifact_ids,
            "mail_delivery_ids": self.mail_delivery_ids,
            "run_key": self.run_key,
            "thread_id": self.thread_id,
            "max_items": self.max_items,
            "max_threads": self.max_threads,
            "deadline_seconds": self.deadline_seconds,
            "regeneration_reason_code": self.regeneration_reason_code,
        }
        for name, value in values.items():
            if value not in (None, ()) and name not in allowed[self.mode]:
                raise ValueError(f"{name}_not_allowed_for_{self.mode}")
        if self.mode == "process" and len(self.mail_message_ids) != 1:
            raise ValueError("process_requires_exactly_one_mail_message_id")
        if (
            self.mode == "deliver_response"
            and len(self.mail_response_artifact_ids) != 1
        ):
            raise ValueError(
                "deliver_response_requires_exactly_one_mail_response_artifact_id"
            )
        if self.mode == "reconcile" and len(self.mail_delivery_ids) > 1:
            raise ValueError("reconcile_accepts_at_most_one_mail_delivery_id")
        if self.mode == "status" and len(self.mail_message_ids) > 1:
            raise ValueError("status_accepts_at_most_one_mail_message_id")

    @property
    def stable_run_key(self) -> str:
        """Stable M4-01 identity; later units add item-level provenance separately."""
        return f"mail:{self.subject_id}:{self.mode}:{self.invocation_id}"

    def to_dict(self) -> dict[str, object]:
        return _json_safe(asdict(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MailCounts:
    discovered: int = 0
    archived: int = 0
    unchanged: int = 0
    queued: int = 0
    processed: int = 0
    ignored: int = 0
    responses_accepted: int = 0
    deliveries_sent: int = 0
    deliveries_already_sent: int = 0
    failed: int = 0
    deferred: int = 0

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in asdict(self).values()
        ):
            raise ValueError("mail_counts_must_be_non_negative_integers")


@dataclass(frozen=True, slots=True)
class MailReceipt:
    schema_version: str = MAIL_RECEIPT_SCHEMA_VERSION
    run_key: str = ""
    mail_agent_run_id: str | None = None
    invocation_id: str = ""
    mode: MailMode = "status"
    status: MailStatus = "failed"
    counts: MailCounts = field(default_factory=MailCounts)
    processed_message_ids: tuple[str, ...] = ()
    mail_response_artifact_ids: tuple[str, ...] = ()
    mail_delivery_ids: tuple[str, ...] = ()
    pending_dependencies: tuple[dict[str, str], ...] = ()
    poll_state: tuple[dict[str, str], ...] = ()
    next_action: str = "operator_review"
    next_retry_at_utc: str | None = None
    warnings: tuple[dict[str, str], ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    started_at_utc: str = field(default_factory=utc_now)
    completed_at_utc: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != MAIL_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported_mail_receipt_schema_version")
        _non_empty(self.run_key, "run_key")
        _non_empty(self.invocation_id, "invocation_id")
        if self.mode not in _MODES:
            raise ValueError("invalid_mail_receipt_mode")
        if self.status not in _STATUSES:
            raise ValueError("invalid_mail_receipt_status")
        _non_empty(self.next_action, "next_action")

    def to_dict(self) -> dict[str, object]:
        return _json_safe(asdict(self))  # type: ignore[return-value]

    def json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def exit_code_for_status(status: MailStatus) -> int:
    try:
        return _EXIT_CODES[status]
    except KeyError as exc:
        raise ValueError("invalid_mail_receipt_status") from exc


class MailApplicationService(Protocol):
    def execute(self, request: MailRequest) -> MailReceipt: ...


class BoundaryOnlyMailService:
    """M4-01 placeholder that proves lifecycle without touching any external system."""

    def execute(self, request: MailRequest) -> MailReceipt:
        receipt_run_key = (
            request.run_key
            if request.mode == "status" and request.run_key
            else request.stable_run_key
        )
        completed = utc_now()
        return MailReceipt(
            run_key=receipt_run_key,
            invocation_id=request.invocation_id,
            mode=request.mode,
            status="failed",
            errors=(
                {
                    "stage": "boundary",
                    "code": "mail_agent_not_implemented",
                    "summary": "M4-01 boundary only",
                },
            ),
            started_at_utc=request.requested_at_utc,
            completed_at_utc=completed,
        )


class MailTool:
    """The single stable public API entry point for all fourth-layer callers."""

    def __init__(self, service: MailApplicationService | None = None) -> None:
        self._service = service or BoundaryOnlyMailService()

    def execute(self, request: MailRequest) -> MailReceipt:
        receipt = self._service.execute(request)
        expected_run_key = (
            request.run_key
            if request.mode == "status" and request.run_key
            else request.stable_run_key
        )
        if (
            receipt.invocation_id != request.invocation_id
            or receipt.mode != request.mode
            or receipt.run_key != expected_run_key
        ):
            raise ValueError("mail_service_returned_inconsistent_receipt")
        return receipt
