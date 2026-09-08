"""Explicit current weekly dependencies; no directory-wide legacy discovery."""

from __future__ import annotations

from pathlib import Path

from skills._shared.scripts.schema_validation import schema_documents

MODULES = (
    "__init__",
    "storage",
    "sync_calendar",
    "fit_sync",
    "garmin_fit",
    "fit_parse",
    "fit_detail",
    "detail_transport",
    "detail_server",
    "weekly_evidence",
    "weekly_context",
    "weekly_history",
    "input_privacy",
    "model_job",
    "model_process",
    "process_capture",
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
)
SCHEMAS = (
    "fit_activity_v1",
    "fit_activity_v2",
    "fit_detail_v1",
    "fit_detail_v2",
    "fit_detail_table_v1",
    "fit_detail_table_v2",
    "fit_detail_request_v1",
    "fit_weekly_evidence_v1",
    "fit_weekly_evidence_v2",
    "fit_model_receipt_v1",
    "fit_model_receipt_v2",
    "fit_weekly_stage_input_v1",
    "fit_weekly_stages_result_v1",
    "training_goal_v1",
)
COMMON = (
    "requirements.txt",
    "skills/__init__.py",
    "skills/_shared/__init__.py",
    "skills/_shared/scripts/schema_validation.py",
    "skills/_shared/scripts/training_goal_v1.py",
    "skills/_shared/scripts/structured_outputs_validation.py",
)


COLLECTION = (
    "skills/garmin-sync/scripts/mcp_server_guard.py",
    "skills/garmin-sync/references/live-overrides.txt",
)


def files(source: Path, *, collection: bool = False) -> tuple[Path, ...]:
    """Keep v1 only for frozen M12 data, never for old daily execution."""
    schemas = schema_documents(SCHEMAS, source / "skills/_shared/schemas")
    paths = [source / relative for relative in COMMON]
    if collection:
        paths.extend(source / relative for relative in COLLECTION)
    paths.extend(source / f"skills/_shared/fit_weekly/{name}.py" for name in MODULES)
    paths.extend(
        source / f"skills/_shared/schemas/{name}.schema.json" for name in schemas
    )
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("runtime_dependency_missing")
    return tuple(sorted(paths))
