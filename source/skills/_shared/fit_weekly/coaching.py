"""Business assembly over weekly_stages/model_job; no second executor or fallback."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_facts,
    coaching_plan,
    coaching_summary,
    command_adapter,
    command_runtime,
    fit_detail,
    model_job,
    stage_context,
    storage,
    weekly_history,
    weekly_stages,
)
from skills._shared.scripts.schema_validation import validate_payload

LegacyPolicies = Mapping[tuple[str | None, str, str | None], model_job.ResultValidator]


def validator(
    root: Path, *, legacy: LegacyPolicies | None = None
) -> model_job.ResultValidator:
    def validate(output: Any, payload: dict[str, Any]) -> None:
        version = output.get("schema_version") if isinstance(output, dict) else None
        if version == coaching_contract.VERSIONS["plan"]:
            coaching_plan.project(output, payload, root=root)
        elif version == coaching_contract.VERSIONS["summary"]:
            coaching_summary.validate(output, payload, root=root)
        elif (
            legacy is not None
            and (payload.get("stage"), payload.get("schema_version", ""), version)
            in legacy
        ):
            legacy[(payload.get("stage"), payload.get("schema_version", ""), version)](
                output, payload
            )
        else:
            raise ValueError("coaching_version_unknown")

    return validate


def stage_contract(
    root: Path,
    stage: str,
    prepare_adapter: weekly_stages.AdapterFactory,
    *,
    recover: weekly_stages.Recovery | None = None,
) -> weekly_stages.StageContract:
    coaching_contract.check(stage)
    return weekly_stages.StageContract(
        coaching_contract.schema(stage), validator(root), prepare_adapter, recover
    )


def command_contracts(
    root: Path,
    end: str,
    *,
    runtimes: Mapping[
        str, command_runtime.Runtime | Callable[[], command_runtime.Runtime]
    ],
    capability_paths: Mapping[str, Path | Callable[[], Path]],
    legacy: LegacyPolicies | None = None,
) -> tuple[
    weekly_stages.StageContract, weekly_stages.StageContract, model_job.ResultValidator
]:
    """Explicit configured, capability-checked adapter only; does not launch on import."""
    validate = validator(root, legacy=legacy)
    contracts = []
    for stage in ("plan", "summary"):
        coaching_contract.check(stage)
        runtime = runtimes[stage]
        if not callable(runtime) and (
            runtime.stage != stage
            or runtime.prompt_prefix != coaching_contract.prompt(stage)
        ):
            raise ValueError("coaching_runtime_prompt_invalid")
        business = coaching_contract.schema(stage)

        def input_check(
            payload: dict[str, Any], current: str = stage
        ) -> model_job.InputValidator:
            return stage_context.validator(
                root,
                end,
                current,
                validate_history=validate,
                plan=payload.get("fixed_plan"),
                validate_plan=validate if current == "summary" else None,
            )

        def prepare(
            payload: dict[str, Any],
            scope: str,
            current: str = stage,
            chosen: command_runtime.Runtime
            | Callable[[], command_runtime.Runtime] = runtime,
            schema: dict[str, Any] = business,
            check: Any = input_check,
        ) -> model_job.Adapter:
            active = chosen() if callable(chosen) else chosen
            if (
                active.stage != current
                or active.prompt_prefix != coaching_contract.prompt(current)
            ):
                raise ValueError("coaching_runtime_prompt_invalid")
            path = capability_paths[current]
            return command_adapter.prepare(
                root,
                end,
                scope,
                payload,
                schema,
                runtime=active,
                capability_path=path() if callable(path) else path,
                validate_input=check(payload),
                validate_result=validate,
                stage=current,
            )

        def recover(
            payload: dict[str, Any],
            scope: str,
            current: str = stage,
            schema: dict[str, Any] = business,
            check: Any = input_check,
        ) -> dict[str, Any]:
            return command_adapter.recover(
                root,
                end,
                scope,
                payload,
                schema,
                validate_input=check(payload),
                validate_result=validate,
                stage=current,
            )

        contracts.append(
            weekly_stages.StageContract(business, validate, prepare, recover)
        )
    return contracts[0], contracts[1], validate


def report(
    root: Path, end: str, *, legacy: LegacyPolicies | None = None
) -> dict[str, Any]:
    """R4 read-only input: revalidate original captures, retain the one exact plan."""
    validate = validator(root, legacy=legacy)
    with storage.open_store(root) as db:
        history = weekly_history.completed_stages(db, root, end, validate)
        original = history["report"]
        saved = fit_detail.get(db, "weekly-stage-input:" + end + ":summary")
        if saved is None or saved[0] != model_job.sha(saved[1]):
            raise ValueError("coaching_report_input_missing")
        payload = saved[1]
    raw_plan, summary = original["running"]["plan"], original["summary"]
    if (
        raw_plan.get("schema_version") != coaching_contract.VERSIONS["plan"]
        or summary.get("schema_version") != coaching_contract.VERSIONS["summary"]
    ):
        raise ValueError("coaching_report_version_unsupported")
    fixed = original["plan_binding"]
    if payload["fixed_plan"] != fixed:
        raise ValueError("coaching_report_plan_invalid")
    # Reconstruct plan view from its ORIGINAL frozen request, not summary history.
    with storage.open_store(root) as db:
        request = fit_detail.get(db, "model-job:" + end + ":plan:intent")
        summary_request = fit_detail.get(db, "model-job:" + end + ":summary:intent")
        if (
            request is None
            or summary_request is None
            or summary_request[1]["payload"] != payload
        ):
            raise ValueError("coaching_report_input_missing")
    plan = coaching_plan.project(raw_plan, request[1]["payload"], root=root)
    result = {
        "schema_version": "fit_coaching_report_v1",
        "facts": coaching_facts.build(payload),
        "core_conclusions": model_job.clone(summary["core_conclusions"]),
        "running_analysis": model_job.clone(summary["running_analysis"]),
        "other_sports": model_job.clone(summary["other_sports"]),
        "plan": plan,
        "data_limitations": list(summary["data_limitations"]),
        "safety": model_job.clone(summary["safety"]),
        "source_report_sha256": history["report_sha256"],
        "raw_plan_sha256": fixed["result_sha256"],
        "raw_summary_sha256": model_job.sha(summary),
        "validation_limits": [
            "Exact structures, dates, dose, source references and explicit load comparisons validated; arbitrary prose accuracy, goal interpretation and coaching reasonableness are not proven by deterministic checks."
        ],
    }
    if validate_payload(result, "fit_coaching_report_v1"):
        raise ValueError("coaching_host_report_schema_invalid")
    return result
