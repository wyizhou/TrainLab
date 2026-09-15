"""Explicit current weekly dependencies; no directory-wide legacy discovery."""

from __future__ import annotations

from pathlib import Path

from skills._shared.scripts.schema_validation import schema_documents

MODULES = (
    "__init__",
    "storage",
    "run_config",
    "sync_calendar",
    "fit_sync",
    "sync_batch",
    "garmin_fit",
    "fit_parse",
    "fit_time",
    "fit_detail",
    "detail_transport",
    "detail_server",
    "weekly_evidence",
    "weekly_context",
    "weekly_history",
    "input_privacy",
    "model_job",
    "model_process",
    "parent_watch",
    "process_capture",
    "command_adapter",
    "command_capability",
    "command_catalog",
    "codex_native",
    "command_environment",
    "command_output",
    "command_runtime",
    "codex_adapter",
    "codex_boundary",
    "codex_capability",
    "codex_isolation",
    "codex_output",
    "codex_recovery",
    "codex_runtime",
    "runtime_resources",
    "stage_policy",
    "stage_context",
    "weekly_stages",
    "coaching_contract",
    "coaching_evidence",
    "coaching_facts",
    "coaching_plan",
    "coaching_summary",
    "coaching",
    "report_revisions",
    "report_artifacts",
    "report_view",
    "report_markdown",
    "report_pdf",
    "publication",
    "publication_ledger",
    "gmail_message",
    "gmail_rest",
    "gmail_auth",
    "email_config",
    "gmail_scopes",
    "gmail_labels",
    "garmin_workouts",
    "garmin_publication",
)
SCHEMAS = (
    "fit_activity_v1",
    "fit_activity_v2",
    "fit_activity_v3",
    "fit_detail_v1",
    "fit_detail_v2",
    "fit_detail_v3",
    "fit_detail_table_v1",
    "fit_detail_table_v2",
    "fit_detail_table_v3",
    "fit_detail_request_v1",
    "fit_detail_request_v2",
    "fit_weekly_evidence_v1",
    "fit_weekly_evidence_v2",
    "fit_weekly_evidence_v3",
    "fit_model_receipt_v1",
    "fit_model_receipt_v2",
    "fit_weekly_stage_input_v1",
    "fit_weekly_stage_input_v2",
    "fit_weekly_stage_input_v3",
    "training_goal_text_v1",
    "fit_weekly_stages_result_v1",
    "training_goal_v1",
    "fit_running_plan_v1",
    "fit_sports_summary_v1",
    "fit_coaching_report_v1",
    "fit_report_revision_v1",
    "fit_report_artifacts_v1",
    "fit_report_publication_v1",
    "fit_delivery_request_v1",
    "fit_delivery_request_v2",
    "fit_delivery_intent_v1",
    "fit_delivery_call_v1",
    "fit_delivery_result_v1",
    "fit_delivery_skipped_v1",
)
COMMON = (
    "requirements.txt",
    "skills/_shared/assets/report-fonts/TrainLabReportSans-Regular.ttf",
    "skills/_shared/prompts/fit-running-plan-v1.txt",
    "skills/_shared/prompts/fit-sports-summary-v1.txt",
    "skills/__init__.py",
    "skills/_shared/__init__.py",
    "skills/_shared/scripts/schema_validation.py",
    "skills/_shared/scripts/structured_outputs_validation.py",
)


COLLECTION = (
    "skills/garmin-sync/scripts/mcp_server_guard.py",
    "skills/garmin-sync/references/live-overrides.txt",
)

HISTORY = (
    "skills/_shared/fit_weekly/legacy_import.py",
    "skills/_shared/fit_weekly/history_archive.py",
)

ENTRYPOINT_MODULES = (
    "__main__",
    "cli",
    "run_authorization",
    "run_state",
    "lifecycle",
    "run_services",
    "run_sync",
    "sync_budget",
    "run_models",
    "run_weekly",
    "run_publication",
    "run_reconcile",
    "run_daemon",
    "schedule_state",
)


def files(
    source: Path,
    *,
    collection: bool = False,
    entrypoint: bool = False,
    history: bool = False,
    legacy_reader: bool = True,
) -> tuple[Path, ...]:
    """Keep v1 only for frozen M12 data, never for old daily execution."""
    schemas = schema_documents(SCHEMAS, source / "skills/_shared/schemas")
    paths = [source / relative for relative in COMMON]
    if collection:
        paths.extend(source / relative for relative in COLLECTION)
    if history:
        paths.extend(source / relative for relative in HISTORY)
    paths.extend(
        source / f"skills/_shared/fit_weekly/{name}.py"
        for name in MODULES
        if legacy_reader
        or name
        not in {"codex_adapter", "codex_capability", "codex_recovery", "codex_runtime"}
    )
    if entrypoint:
        paths.extend(
            source / f"skills/_shared/fit_weekly/{name}.py"
            for name in ENTRYPOINT_MODULES
        )
    paths.extend(
        source / f"skills/_shared/schemas/{name}.schema.json" for name in schemas
    )
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("runtime_dependency_missing")
    return tuple(sorted(paths))
