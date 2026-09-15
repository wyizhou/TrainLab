from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_sync,
    garmin_fit,
    publication,
    publication_ledger,
    run_authorization,
    run_config,
    run_publication,
    run_services,
    storage,
    sync_batch,
    sync_budget,
    sync_calendar,
)


def ranges(dates: list[str]) -> list[list[str]]:
    if not dates or dates != sorted(set(dates)):
        raise ValueError("sync_dates_invalid")
    result: list[list[str]] = []
    for day in dates:
        parsed = sync_calendar.day_value(day)
        if result and parsed == sync_calendar.day_value(result[-1][-1]) + timedelta(
            days=1
        ):
            result[-1].append(day)
        else:
            result.append([day])
    return result


def selected(grant: run_authorization.Grant, dates: list[str] | None) -> list[str]:
    scope = grant.value()["sync"]
    if scope is None:
        raise ValueError("sync_authorization_required")
    result = list(scope["dates"] if dates is None else dates)
    ranges(result)
    if not set(result) <= set(scope["dates"]):
        raise ValueError("sync_dates_not_authorized")
    return result


def batch_key(
    grant: run_authorization.Grant, dates: list[str] | None = None, *, recovery: int = 0
) -> str:
    if type(recovery) is not int or not 0 <= recovery <= 999:
        raise ValueError("sync_recovery_invalid")
    value = {
        "authorization": grant.key,
        "dates": selected(grant, dates),
        "as_of_utc": grant.value()["sync"]["as_of_utc"],
    }
    key = "sync-batch:" + storage.digest(storage.canonical(value).encode())
    return key + f":recovery:{recovery}" if recovery else key


def action_key(
    grant: run_authorization.Grant, dates: list[str] | None = None, *, recovery: int = 0
) -> str:
    return batch_key(grant, dates, recovery=recovery) + ":gmail"


def daily_dates(
    root: Path, grant: run_authorization.Grant, *, now: str
) -> dict[str, Any]:
    grant.check_frozen(root)
    grant.check_time(now)
    with storage.open_store(root) as db:
        dates = sync_calendar.pending_days(db, now)
        unfinished = fit_sync.unfinished_jobs(db)
    selected(grant, dates)
    return {"dates": dates, "ranges": ranges(dates), "unfinished_jobs": unfinished}


async def collect(
    config: run_config.Config,
    grant: run_authorization.Grant,
    *,
    dates: list[str] | None = None,
    now: Callable[[], str] = publication_ledger.utc_now,
    session_factory: garmin_fit.SessionFactory | None = None,
    recovery: int = 0,
) -> dict[str, Any]:
    root = config.root
    grant.check_frozen(root)
    dates = selected(grant, dates)
    key = batch_key(grant, dates, recovery=recovery)
    saved = sync_batch.read(root, key)
    if saved is not None:
        return saved
    previous = None
    unfinished = []
    if recovery:
        previous = sync_batch.read(root, batch_key(grant, dates, recovery=recovery - 1))
        if previous is None or previous["status"] != "failed":
            raise ValueError("sync_recovery_source_invalid")
        with storage.open_store(root) as db:
            unfinished = fit_sync.unfinished_jobs(db)
    grant.freeze(root, now=now())
    service = run_services.garmin(config)
    specs = [
        grant.sync_spec(chunk, is_cn=service.is_cn, now=now())
        for chunk in ranges(dates)
    ]
    if previous is not None:
        with storage.open_store(root) as db:
            predecessor = fit_sync.document(db, previous["batch_key"] + ":request")
        if predecessor is None or predecessor["specs"] != [
            asdict(spec) for spec in specs
        ]:
            raise ValueError("sync_recovery_scope_invalid")
        expected = {spec.inventory.key: asdict(spec) for spec in specs}
        for job in unfinished:
            key_value = job["request"]["inventory"]["key"]
            if key_value in expected and job["request"] != expected[key_value]:
                raise ValueError("sync_recovery_scope_invalid")
    budget = sync_budget.Budget(grant, now)
    budget.claim(root)
    with storage.open_store(root) as db:
        fit_sync.put(
            db,
            key + ":request",
            {
                "schema_version": "fit_sync_batch_request_v1",
                "batch_key": key,
                "authorization_sha256": storage.digest(grant._body.encode()),
                "dates": dates,
                "specs": [asdict(spec) for spec in specs],
                "previous_sha256": publication_ledger.sha(previous)
                if previous is not None
                else None,
            },
        )
    segments = []
    stopped = False
    for spec in specs:
        status, error = "complete", None
        try:
            if stopped:
                with storage.open_store(root) as db:
                    complete = fit_sync.document(
                        db,
                        "fit-sync:"
                        + storage.digest(spec.inventory.key.encode())
                        + ":complete",
                    )
                if complete is None:
                    raise ValueError("sync_previous_segment_failed")
            await fit_sync.synchronize(
                root,
                spec,
                token_root=service.token_root,
                session_factory=session_factory or garmin_fit.sdk_session,
                shared_budget=budget.bind,
            )
        except ValueError:
            status, error = "failed", "sync_segment_failed"
            stopped = True
        try:
            snapshot = publication.sync_snapshot(root, spec.inventory.key)
        except ValueError as exc:
            if str(exc) != "publication_sync_source_missing":
                raise
            snapshot = None
        segments.append(
            {
                "job_key": spec.inventory.key,
                "status": status,
                "error_code": error,
                "snapshot": snapshot,
            }
        )
    return sync_batch.seal(root, key, segments)


def notify(
    config: run_config.Config,
    grant: run_authorization.Grant,
    batch: dict[str, Any],
    *,
    now: Callable[[], str] = publication_ledger.utc_now,
) -> dict[str, Any]:
    grant.check_frozen(config.root)
    action = batch["batch_key"] + ":gmail"
    with storage.open_store(config.root) as db:
        prepared = publication_ledger.document(
            db, publication_ledger.key(action, "request")
        )
    if prepared is None:
        authorization = grant.publication(now=now())
        if (
            action not in authorization.action_keys
            or not authorization.start_date
            <= batch["dates"][-1]
            <= authorization.end_date
        ):
            raise ValueError("sync_mail_authorization_required")
        required = {
            "gmail.profile",
            "gmail.get",
            "gmail.send",
            "gmail.modify",
            "gmail.labels.list",
        }
        if not required <= set(authorization.max_calls):
            raise ValueError("sync_mail_authorization_required")
        grant.freeze(config.root, now=now())
        envelope = run_services.gmail_envelope(config)
        from skills._shared.fit_weekly import gmail_labels

        if not {
            gmail_labels.ensure_key(envelope["account"]),
            gmail_labels.apply_key(action),
        } <= set(authorization.action_keys):
            raise ValueError("sync_mail_authorization_required")
        grant.freeze(config.root, now=now())
        publication.prepare_sync_batch(
            config.root,
            batch["batch_key"],
            recipient=envelope["recipient"],
            sender=envelope["account"],
        )
    return run_publication.mail(config, action, grant, readonly=False, now=now)
