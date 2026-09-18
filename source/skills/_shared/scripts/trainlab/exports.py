"""Shared contract exports for future skill scripts."""

from __future__ import annotations

from trainlab.ai import (
    AIConfig,
    AIProtocolError,
    HttpCompatibleAIClient,
    ToolDispatcher,
    load_ai_config,
    run_tool_loop,
)
from trainlab.context import ContextError, build_context
from trainlab.contracts.errors import ErrorCode, failure_envelope, success_envelope
from trainlab.contracts.interfaces import (
    JSON_SCHEMA_CONTRACTS,
    REFERENCE_CONTRACTS,
    TOOL_CONTRACTS,
    UNCONFIGURED_POLICIES,
    CapacityPolicy,
    PendingDecision,
    ToolAuthorization,
    validate_payload,
)
from trainlab.contracts.schema import ddl_statements, table_contracts
from trainlab.contracts.time import next_activity_report_run_utc, weekly_window
from trainlab.garmin_sync import (
    AuthRefreshResult,
    GarminActivity,
    GarminActivityPage,
    GarminSyncError,
    GarminSyncResult,
    GarminSyncState,
    extract_single_fit,
    run_garmin_sync,
    should_run_sync,
)
from trainlab.reference_tools import read_reference
from trainlab.report_service import GeneratedReport, ReportGenerationError, ReportService
from trainlab.reports import (
    ReportStorageError,
    get_activity_report,
    get_weekly_report,
    save_activity_report,
    save_weekly_report,
)
from trainlab.running_records import get_running_records, handle_get_running_records

__all__ = [
    "JSON_SCHEMA_CONTRACTS",
    "REFERENCE_CONTRACTS",
    "TOOL_CONTRACTS",
    "UNCONFIGURED_POLICIES",
    "AIConfig",
    "AIProtocolError",
    "AuthRefreshResult",
    "CapacityPolicy",
    "ContextError",
    "ErrorCode",
    "GarminActivity",
    "GarminActivityPage",
    "GarminSyncError",
    "GarminSyncResult",
    "GarminSyncState",
    "GeneratedReport",
    "HttpCompatibleAIClient",
    "PendingDecision",
    "ReportGenerationError",
    "ReportService",
    "ReportStorageError",
    "ToolAuthorization",
    "ToolDispatcher",
    "build_context",
    "ddl_statements",
    "extract_single_fit",
    "failure_envelope",
    "get_activity_report",
    "get_running_records",
    "get_weekly_report",
    "handle_get_running_records",
    "load_ai_config",
    "next_activity_report_run_utc",
    "read_reference",
    "run_garmin_sync",
    "run_tool_loop",
    "save_activity_report",
    "save_weekly_report",
    "should_run_sync",
    "success_envelope",
    "table_contracts",
    "validate_payload",
    "weekly_window",
]
