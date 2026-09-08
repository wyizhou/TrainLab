"""Small serial coordinator; schema/business policy is explicitly supplied by R3.

No launcher, default adapter, training schema or permissive validator lives here.
Completed/unknown intents are inspected before asking a factory for a launcher.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_detail,
    model_job,
    stage_context,
    stage_policy,
    storage,
    weekly_context,
)
from skills._shared.scripts.schema_validation import validate_payload

AdapterFactory = Callable[[dict[str, Any], str], model_job.Adapter]
Recovery = Callable[[dict[str, Any], str], dict[str, Any]]


@dataclass(frozen=True)
class StageContract:
    response_schema: dict[str, Any]
    validate_result: model_job.ResultValidator
    prepare_adapter: AdapterFactory
    recover: Recovery | None = None


class _LocalOnly:
    """Profile of an existing intent for the shared read-only recovery path."""

    def __init__(self, profile: dict[str, Any]):
        self.profile = model_job.clone(profile)

    def run(
        self,
        payload: dict[str, Any],
        detail: fit_detail.DetailHost,
        response_schema: dict[str, Any],
    ) -> Any:
        raise AssertionError("local_recovery_cannot_launch")


def execute(
    root: Path,
    end: str,
    stage: str,
    payload: dict[str, Any],
    scope: str,
    contract: StageContract,
    validate_input: model_job.InputValidator,
) -> dict[str, Any]:
    def validate_result(output: Any, body: dict[str, Any]) -> None:
        if stage == "summary" and (
            not isinstance(output, dict) or "running_analysis" not in output
        ):
            raise ValueError("weekly_running_analysis_missing")
        contract.validate_result(output, body)

    with storage.open_store(root) as db:
        existing = fit_detail.get(db, stage_policy.job_key(end, stage) + ":intent")
    kwargs = {
        "stage": stage,
        "validate_input": validate_input,
        "validate_result": validate_result,
    }
    if existing is not None:
        result = model_job.recover(
            root,
            end,
            scope,
            payload,
            contract.response_schema,
            _LocalOnly(existing[1]["profile"]),
            read_completed=lambda _: None,
            **kwargs,
        )
        if result["status"] == "unknown" and contract.recover is not None:
            contract.recover(model_job.clone(payload), scope)
            # Never trust a callback's claim: re-read the durable shared ledger.
            result = model_job.recover(
                root,
                end,
                scope,
                payload,
                contract.response_schema,
                _LocalOnly(existing[1]["profile"]),
                read_completed=lambda _: None,
                **kwargs,
            )
        return result
    adapter = contract.prepare_adapter(model_job.clone(payload), scope)
    return model_job.run(
        root, end, scope, payload, contract.response_schema, adapter, **kwargs
    )


def plan_binding(root: Path, end: str, result: dict[str, Any]) -> dict[str, Any]:
    if result["status"] != "succeeded":
        raise ValueError("weekly_plan_missing")
    with storage.open_store(root) as db:
        saved = fit_detail.get(db, stage_policy.job_key(end, "plan") + ":result")
    if saved is None or saved[1]["output"] != result["result"]:
        raise ValueError("weekly_plan_binding_invalid")
    return {
        "period_end_utc": end,
        "request_sha256": saved[0],
        "capture_sha256": model_job.sha(saved[1]),
        "result_sha256": model_job.sha(result["result"]),
        "plan": model_job.clone(result["result"]),
    }


def run(
    root: Path,
    period_end: str,
    *,
    plan: StageContract,
    summary: StageContract,
    validate_history: model_job.ResultValidator,
) -> dict[str, Any]:
    fit_detail.period_key(period_end)
    with storage.open_store(root) as db:
        if fit_detail.get(db, stage_policy.job_key(period_end) + ":intent") is not None:
            raise ValueError("model_legacy_week_occupied")
    for contract in (plan, summary):
        if (
            not isinstance(contract, StageContract)
            or not callable(contract.validate_result)
            or not callable(contract.prepare_adapter)
        ):
            raise ValueError("weekly_stage_contract_missing")
        model_job.schema_validator(contract.response_schema)
    if not callable(validate_history):
        raise ValueError("weekly_stage_contract_missing")
    if "running_analysis" not in summary.response_schema.get(
        "required", []
    ) or "running_analysis" not in summary.response_schema.get("properties", {}):
        raise ValueError("weekly_running_analysis_schema_missing")
    materials = weekly_context.freeze(
        root, period_end, validate_report=validate_history
    )
    scope = materials["scope_sha256"]
    first_input = stage_context.freeze(
        root, period_end, "plan", validate_history=validate_history
    )
    first = execute(
        root,
        period_end,
        "plan",
        first_input,
        scope,
        plan,
        stage_context.validator(
            root, period_end, "plan", validate_history=validate_history
        ),
    )
    result = {
        "status": first["status"],
        "plan": first,
        "summary": None,
        "report": None,
        "publishable": False,
    }
    if first["status"] != "succeeded":
        return result
    binding = plan_binding(root, period_end, first)
    second_input = stage_context.freeze(
        root,
        period_end,
        "summary",
        validate_history=validate_history,
        plan=binding,
        validate_plan=plan.validate_result,
    )
    second = execute(
        root,
        period_end,
        "summary",
        second_input,
        scope,
        summary,
        stage_context.validator(
            root,
            period_end,
            "summary",
            validate_history=validate_history,
            plan=binding,
            validate_plan=plan.validate_result,
        ),
    )
    result.update(status=second["status"], summary=second)
    if second["status"] == "succeeded":
        if (
            not isinstance(second["result"], dict)
            or "running_analysis" not in second["result"]
        ):
            raise ValueError("weekly_running_analysis_missing")
        report = {
            "schema_version": "fit_weekly_stages_result_v1",
            "period_end_utc": period_end,
            "summary": second["result"],
            "running": {
                "analysis": second["result"]["running_analysis"],
                "plan": binding["plan"],
            },
            "plan_binding": binding,
            "summary_receipt": second["receipt"],
        }
        if validate_payload(report, "fit_weekly_stages_result_v1"):
            raise ValueError("weekly_stages_result_invalid")
        with storage.open_store(root) as db:
            fit_detail.put(
                db, "weekly-stages-result:" + period_end, model_job.sha(report), report
            )
        result.update(report=model_job.clone(report), publishable=True)
    return result
