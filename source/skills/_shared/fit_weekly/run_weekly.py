from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching,
    fit_detail,
    fit_sync,
    garmin_fit,
    model_job,
    publication_ledger,
    report_artifacts,
    report_revisions,
    run_authorization,
    run_config,
    run_models,
    run_publication,
    run_services,
    storage,
    sync_budget,
    sync_calendar,
    weekly_context,
    weekly_evidence,
    weekly_history,
    weekly_stages,
)


def record(
    root: Path, end: str, part: str, value: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    fit_detail.period_key(end)
    if part not in ("sync", "publication"):
        raise ValueError("weekly_record_invalid")
    key = (
        report_revisions.selection_key(end)
        if part == "publication"
        else f"weekly-run:{end}:{part}"
    )
    with storage.open_store(root) as db:
        if value is not None:
            fit_detail.put(db, key, model_job.sha(value), value)
        saved = fit_detail.get(db, key)
        if saved is not None and saved[0] != model_job.sha(saved[1]):
            raise ValueError("weekly_record_conflict")
        return saved[1] if saved else None


async def collect(
    config: run_config.Config,
    grant: run_authorization.Grant | None,
    end: str,
    *,
    now: Callable[[], str],
) -> dict[str, Any]:
    root = config.root
    _, slot = fit_detail.period_key(end)
    if sync_calendar.utc_time(now()) < sync_calendar.utc_time(end):
        raise ValueError("weekly_before_cutoff")
    if grant is not None:
        grant.check_frozen(root)
    with storage.open_store(root) as db:
        frozen = fit_detail.get(db, "weekly-evidence:" + end)
    if frozen is not None:
        return weekly_evidence.freeze(root, end, frozen[1]["sources"]["sync_job_key"])
    if grant is None:
        raise ValueError("weekly_sync_authorization_required")
    dates = sync_calendar.days_between(
        *[
            sync_calendar.utc_time(slot[k]).astimezone(sync_calendar.HONG_KONG).date()
            for k in ("start_utc", "end_utc")
        ]
    )
    scope = grant.value()["sync"]
    if (
        scope is None
        or not set(dates) <= set(scope["dates"])
        or sync_calendar.utc_time(scope["as_of_utc"]) < sync_calendar.utc_time(end)
    ):
        raise ValueError("weekly_sync_coverage_invalid")
    grant.freeze(root, now=now())
    old = record(root, end, "sync")
    if old is not None and old["authorization_sha256"] != storage.digest(
        grant._body.encode()
    ):
        raise ValueError("weekly_original_sync_required")
    service = run_services.garmin(config)
    spec = grant.sync_spec(dates, is_cn=service.is_cn, now=now())
    record(
        root,
        end,
        "sync",
        {
            "period_end_utc": end,
            "authorization_sha256": storage.digest(grant._body.encode()),
            "sync_job_key": spec.inventory.key,
            "dates": dates,
        },
    )
    budget = sync_budget.Budget(grant, now)
    budget.claim(root)
    await fit_sync.synchronize(
        root,
        spec,
        token_root=service.token_root,
        session_factory=garmin_fit.sdk_session,
        shared_budget=budget.bind,
    )
    return weekly_evidence.freeze(root, end, spec.inventory.key)


async def run(
    config: run_config.Config,
    end: str,
    grant: run_authorization.Grant | None,
    *,
    phase: str = "all",
    revision_id: str | None = None,
    revision_sha: str | None = None,
    late: bool | None = None,
    now: Callable[[], str] = publication_ledger.utc_now,
) -> dict[str, Any]:
    root = config.root
    fit_detail.period_key(end)
    if (
        phase not in ("all", "draft", "publish")
        or (revision_id is None) != (revision_sha is None)
        or (late is not None and type(late) is not bool)
    ):
        raise ValueError("weekly_options_invalid")
    if grant is not None:
        grant.check_frozen(root)
    prepared = record(root, end, "publication")
    if prepared is not None:
        if revision_id is not None and (revision_id, revision_sha) != (
            prepared["revision_id"],
            prepared["revision_sha256"],
        ):
            raise ValueError("weekly_revision_frozen")
        revision_id, revision_sha = prepared["revision_id"], prepared["revision_sha256"]
    stages = None
    if phase != "publish":
        await collect(config, grant, end, now=now)
        weekly_context.freeze(
            root,
            end,
            validate_report=coaching.validator(root),
            goal_path=config.goal_path,
        )
        plan, summary, validate = run_models.contracts(config, end, grant, now=now)
        stages = weekly_stages.run(
            root, end, plan=plan, summary=summary, validate_history=validate
        )
        if not stages["publishable"]:
            return {
                "period_end_utc": end,
                "status": stages["status"],
                "stages": stages,
                "publication": None,
            }
    weekly_history.archive(root, end, validate_report=coaching.validator(root))
    if revision_id is None:
        revision = report_revisions.create(root, end)
        revision_id, revision_sha = "ai", model_job.sha(revision)
    assert revision_sha is not None
    if prepared is None:
        manifest = report_artifacts.render(root, end, revision_id, revision_sha)
    else:
        manifest = report_artifacts.read(root, end, revision_id, revision_sha).manifest
    result = {
        "period_end_utc": end,
        "status": "draft",
        "stages": stages,
        "revision_id": revision_id,
        "revision_sha256": revision_sha,
        "pdf_sha256": manifest["pdf_sha256"],
        "publication": None,
    }
    if phase == "draft":
        return result
    if prepared is None:
        if grant is None:
            raise ValueError("weekly_publication_authorization_required")
        grant.freeze(root, now=now())
        envelope = run_services.gmail_envelope(config)
        today = sync_calendar.utc_time(now()).astimezone(sync_calendar.HONG_KONG).date()
        original_day = (
            sync_calendar.utc_time(end).astimezone(sync_calendar.HONG_KONG).date()
        )
        prepared = {
            "mail_version": 2,
            "revision_id": revision_id,
            "revision_sha256": revision_sha,
            "sender": envelope["account"],
            "recipient": envelope["recipient"],
            "late": today > original_day if late is None else late,
        }
        record(root, end, "publication", prepared)
    delivered = await run_publication.weekly(config, end, prepared, grant, now=now)
    result.update(status=delivered["status"], publication=delivered)
    return result
