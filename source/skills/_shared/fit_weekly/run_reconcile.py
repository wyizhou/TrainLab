from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching,
    fit_detail,
    publication,
    publication_ledger,
    run_authorization,
    run_config,
    run_models,
    run_publication,
    stage_context,
    storage,
    weekly_history,
    weekly_stages,
)


def local(root: Path, end: str | None = None) -> dict[str, Any]:
    if end is not None:
        fit_detail.period_key(end)
    with storage.open_store(root) as db:
        ends = sorted(
            {
                key.removeprefix("model-job:")
                .removesuffix(":plan:intent")
                .removesuffix(":summary:intent")
                for (key,) in db.execute(
                    "SELECT logical_key FROM documents WHERE kind='weekly_input'"
                )
                if key.startswith("model-job:")
                and (key.endswith(":plan:intent") or key.endswith(":summary:intent"))
            }
        )
    results = {}
    for period in ends:
        if end is not None and period != end:
            continue
        config = run_config.Config(root, root / "goal.md", {})
        plan, summary, validate = run_models.contracts(
            config, period, None, now=publication_ledger.utc_now
        )
        stages = {}
        for stage, contract in (("plan", plan), ("summary", summary)):
            with storage.open_store(root) as db:
                intent = fit_detail.get(db, f"model-job:{period}:{stage}:intent")
            if intent is None:
                stages[stage] = {"status": "not_started"}
                continue
            payload = intent[1]["payload"]
            check = stage_context.validator(
                root,
                period,
                stage,
                validate_history=validate,
                plan=payload.get("fixed_plan"),
                validate_plan=coaching.validator(root) if stage == "summary" else None,
            )
            stages[stage] = weekly_stages.execute(
                root, period, stage, payload, intent[1]["scope_sha256"], contract, check
            )
        if all(s["status"] == "succeeded" for s in stages.values()):
            weekly_stages.run(
                root, period, plan=plan, summary=summary, validate_history=validate
            )
            weekly_history.archive(root, period, validate_report=validate)
        results[period] = stages
    status = (
        "unknown"
        if any(
            s["status"] == "unknown"
            for stages in results.values()
            for s in stages.values()
        )
        else "failed"
        if any(
            s["status"] == "failed"
            for stages in results.values()
            for s in stages.values()
        )
        else "complete"
    )
    return {"status": status, "mode": "local", "weeks": results}


async def external(
    config: run_config.Config,
    grant: run_authorization.Grant,
    actions: list[str],
    *,
    now: Callable[[], str],
) -> dict[str, Any]:
    grant.check_frozen(config.root)
    auth = grant.publication(now=now())
    if (
        not actions
        or len(actions) != len(set(actions))
        or not set(actions) <= set(auth.action_keys)
        or set(auth.max_calls) & publication_ledger.WRITE_TOOLS
    ):
        raise ValueError("reconcile_readonly_authorization_required")
    requests = {
        action: publication.validate_source(config.root, action) for action in actions
    }
    for action, req in requests.items():
        if not auth.start_date <= req["date"] <= auth.end_date:
            raise ValueError("publication_date_scope_invalid")
        if (
            req["kind"] == "garmin_schedule"
            and req["payload"]["create_action"] not in requests
        ):
            raise ValueError("reconcile_pair_required")
        if (
            req["kind"] == "garmin_create"
            and action.replace(":create:", ":schedule:") not in requests
        ):
            raise ValueError("reconcile_pair_required")
    grant.freeze(config.root, now=now())
    results = {}
    for action, req in requests.items():
        if req["kind"] == "gmail":
            results[action] = run_publication.mail(
                config, action, grant, readonly=True, now=now
            )
        elif req["kind"] in ("gmail_label_ensure", "gmail_label_apply"):
            results[action] = run_publication.label(
                config, action, grant, readonly=True, now=now
            )
        elif req["kind"] == "garmin_create":
            schedule = action.replace(":create:", ":schedule:")
            pair = await run_publication.course(
                config, action, schedule, grant, readonly=True, now=now
            )
            results[action], results[schedule] = pair["create"], pair["schedule"]
    status = (
        "unknown"
        if any(v["status"] == "unknown" for v in results.values())
        else "pending"
        if any(v["status"] == "prepared" for v in results.values())
        else "complete"
    )
    return {"status": status, "mode": "external_readonly", "actions": results}
