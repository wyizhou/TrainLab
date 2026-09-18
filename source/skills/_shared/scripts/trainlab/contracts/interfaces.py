"""B0 public DTO, tool and policy contracts for later ADHOC-0031 stages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.json_validation import loads, schema_for, validate

JsonObject = dict[str, Any]
ToolName = Literal["get_running_records", "read_reference"]
ReferenceId = Literal["garmin-fit-parsing", "longdou"]


class PendingDecision(StrEnum):
    ACTIVITY_BATCH_AND_BACKFILL = "D31-03A"
    WEEKLY_TRIGGER_AND_MISSING_REPORTS = "D31-03B"
    RUNNING_RECORDS_QUOTA = "D31-02A"


class DuplicateFitPolicy(StrEnum):
    SAME_BYTES_IDEMPOTENT = "same_bytes_idempotent"
    REMOTE_SOURCE_CONFLICT_FAILS = "remote_source_conflict_fails"
    REPARSE_FAILURE_KEEPS_PREVIOUS = "reparse_failure_keeps_previous"


class ReportWritePolicy(StrEnum):
    ACTIVITY_REPORT_REPLACES_CURRENT_FULL_TEXT = "activity_report_replaces_current_full_text"
    WEEKLY_REPORT_ALLOWS_MULTIPLE_FOR_SAME_T = "weekly_report_allows_multiple_for_same_t"
    BLANK_SUMMARY_IS_INVALID = "blank_summary_is_invalid"
    UNKNOWN_COMMIT_RESULT_IS_NOT_REPLAYED_BLINDLY = "unknown_commit_result_is_not_replayed_blindly"


@dataclass(frozen=True)
class JsonSchemaContract:
    name: str
    schema: JsonObject
    valid_example: JsonObject
    invalid_example: JsonObject


@dataclass(frozen=True)
class ToolContract:
    name: ToolName
    parameters_schema: str
    result_schema: str
    requires_host_authorization: bool
    forbidden_parameters: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceContract:
    reference_id: ReferenceId
    relative_path: Path
    purpose: str


@dataclass(frozen=True)
class ToolAuthorization:
    allowed_activity_ids: frozenset[str]
    allowed_reference_ids: frozenset[ReferenceId]

    def can_read_records(self, activity_id: str) -> bool:
        return activity_id in self.allowed_activity_ids

    def can_read_reference(self, reference_id: ReferenceId) -> bool:
        return reference_id in self.allowed_reference_ids


@dataclass(frozen=True)
class CapacityPolicy:
    storage_bytes_limit: int | None
    model_payload_bytes_limit: int | None

    def check_storage(self, byte_count: int) -> None:
        _check_capacity("storage", byte_count, self.storage_bytes_limit)

    def check_model_payload(self, byte_count: int) -> None:
        _check_capacity("model_payload", byte_count, self.model_payload_bytes_limit)


@dataclass(frozen=True)
class WeeklyReportInputPolicy:
    window_start_inclusive: bool
    window_end_exclusive: bool
    uses_single_run_time_anchor: bool
    empty_week_summary: str
    missing_activity_report_decision: PendingDecision


UNCONFIGURED_POLICIES = {
    PendingDecision.ACTIVITY_BATCH_AND_BACKFILL: "activity selection and missed-run backfill are not configured in B0",
    PendingDecision.WEEKLY_TRIGGER_AND_MISSING_REPORTS: "weekly trigger and missing activity-report behavior are not configured in B0",
    PendingDecision.RUNNING_RECORDS_QUOTA: "running-record quota policy is not configured in B0",
}
REFERENCE_CONTRACTS: dict[ReferenceId, ReferenceContract] = {
    "garmin-fit-parsing": ReferenceContract(
        "garmin-fit-parsing",
        Path("references/garmin-fit-parsing.md"),
        "Public FIT parsing reference.",
    ),
    "longdou": ReferenceContract(
        "longdou", Path("references/longdou.md"), "Public sensor reference."
    ),
}
TOOL_CONTRACTS: dict[ToolName, ToolContract] = {
    "get_running_records": ToolContract(
        "get_running_records",
        "GetRunningRecordsRequest",
        "GetRunningRecordsResult",
        True,
        ("sql", "path", "database", "limit", "cursor", "metrics", "start_time", "end_time"),
    ),
    "read_reference": ToolContract(
        "read_reference",
        "ReadReferenceRequest",
        "ReadReferenceResult",
        True,
        ("path", "url", "database", "sql", "file"),
    ),
}
REPORT_WRITE_POLICIES = tuple(ReportWritePolicy)
DUPLICATE_FIT_POLICIES = tuple(DuplicateFitPolicy)
WEEKLY_REPORT_INPUT_POLICY = WeeklyReportInputPolicy(
    True, True, True, "本周无任何运动记录", PendingDecision.WEEKLY_TRIGGER_AND_MISSING_REPORTS
)
JSON_SCHEMA_CONTRACTS = {
    name: JsonSchemaContract(name, schema_for(name), example, {})
    for name, example in loads(
        files("trainlab_schemas").joinpath("examples.json").read_text(encoding="utf-8")
    ).items()
}


def _check_capacity(name: str, byte_count: int, limit: int | None) -> None:
    if byte_count < 0:
        raise ValueError(f"{name} byte count must be non-negative")
    if limit is not None and byte_count > limit:
        raise ValueError(ErrorCode.RESOURCE_LIMIT.value)


def validate_payload(schema_name: str, payload: JsonObject) -> None:
    validate(schema_name, payload)


def validate_schema_examples() -> None:
    for contract in JSON_SCHEMA_CONTRACTS.values():
        validate_payload(contract.name, contract.valid_example)
        try:
            validate_payload(contract.name, contract.invalid_example)
        except ValueError:
            continue
        raise ValueError(f"invalid example unexpectedly passed for {contract.name}")
