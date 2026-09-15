from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skills._shared.fit_weekly import (
    garmin_fit,
    garmin_publication,
    gmail_labels,
    gmail_rest,
    publication,
    run_authorization,
    run_config,
    run_services,
    sync_calendar,
)
from skills._shared.fit_weekly import (
    publication_ledger as ledger,
)


def permission(
    config: run_config.Config,
    grant: run_authorization.Grant | None,
    actions: list[str],
    tools: set[str],
    *,
    now: Callable[[], str],
) -> ledger.Authorization:
    if grant is None:
        raise ValueError("publication_authorization_required")
    grant.check_frozen(config.root)
    auth = grant.publication(now=now())
    if not set(actions) <= set(auth.action_keys) or not tools <= set(auth.max_calls):
        raise ValueError("publication_authorization_invalid")
    for action in actions:
        req = publication.validate_source(config.root, action)
        if not auth.start_date <= req["date"] <= auth.end_date:
            raise ValueError("publication_date_scope_invalid")
    grant.freeze(config.root, now=now())
    return auth


def send(
    config: run_config.Config,
    action: str,
    grant: run_authorization.Grant | None,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    if grant is not None:
        grant.check_frozen(config.root)
    publication.validate_source(config.root, action)
    state = ledger.status(config.root, action)
    if state["status"] == "success" or readonly and state["status"] == "prepared":
        return state
    required = {"gmail.profile", "gmail.get"}
    if state["status"] == "prepared":
        required.add("gmail.send")
    auth = permission(config, grant, [action], required, now=now)
    client = run_services.gmail(config).client()
    selected = (
        gmail_rest.reconcile
        if readonly or state["status"] == "unknown"
        else gmail_rest.deliver
    )
    return selected(config.root, action, client, auth, now=now)


def label(
    config: run_config.Config,
    action: str,
    grant: run_authorization.Grant | None,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    req = publication.validate_source(config.root, action)
    state = ledger.status(config.root, action)
    if state["status"] == "success" or readonly and state["status"] == "prepared":
        return state
    required = {
        "gmail.profile",
        "gmail.labels.list" if req["kind"] == "gmail_label_ensure" else "gmail.get",
    }
    auth = permission(config, grant, [action], required, now=now)
    return gmail_labels.process(
        config.root,
        action,
        run_services.gmail(config).client(),
        auth,
        readonly=readonly or state["status"] == "unknown",
        now=now,
    )


def mail_result(
    sent: dict[str, Any], applied: dict[str, Any], ensured: dict[str, Any]
) -> dict[str, Any]:
    states = [sent, applied, ensured]
    status = (
        "success"
        if all(v["status"] == "success" for v in states)
        else "unknown"
        if any(v["status"] == "unknown" for v in states)
        else "prepared"
    )
    return {
        **{k: v for k, v in sent.items() if k != "schema_version"},
        "status": status,
        "mail": sent,
        "label": applied,
        "ensure_label": ensured,
    }


def mail_state(config: run_config.Config, action: str) -> dict[str, Any]:
    req = publication.validate_source(config.root, action)
    sent = ledger.status(config.root, action)
    if req["schema_version"] == "fit_delivery_request_v1":
        return sent
    ensure, apply = gmail_labels.prepare(config.root, req)
    return mail_result(
        sent, ledger.status(config.root, apply), ledger.status(config.root, ensure)
    )


def mail(
    config: run_config.Config,
    action: str,
    grant: run_authorization.Grant | None,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    if grant is not None:
        grant.check_frozen(config.root)
    req = publication.validate_source(config.root, action)
    if req["schema_version"] == "fit_delivery_request_v1":
        return send(config, action, grant, readonly=readonly, now=now)
    ensure, apply = gmail_labels.prepare(config.root, req)
    sent = ledger.status(config.root, action)
    applied = ledger.status(config.root, apply)
    ensured = ledger.status(config.root, ensure)
    if sent["status"] == applied["status"] == "success":
        return mail_result(sent, applied, ensured)
    if not readonly:
        required = {"gmail.profile", "gmail.get"}
        if sent["status"] == "prepared":
            required.add("gmail.send")
        if applied["status"] == "prepared":
            required.add("gmail.modify")
        if ensured["status"] != "success":
            required.add("gmail.labels.list")
        pending = [
            a
            for a in (ensure, action, apply)
            if ledger.status(config.root, a)["status"] != "success"
        ]
        permission(config, grant, pending, required, now=now)
    if not readonly or ensured["status"] == "unknown":
        ensured = label(config, ensure, grant, readonly=readonly, now=now)
    if ensured["status"] == "success" or sent["status"] != "prepared":
        sent = send(config, action, grant, readonly=readonly, now=now)
    if sent["status"] == ensured["status"] == "success":
        applied = label(config, apply, grant, readonly=readonly, now=now)
    return mail_result(sent, applied, ensured)


async def course(
    config: run_config.Config,
    create: str,
    schedule: str,
    grant: run_authorization.Grant | None,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    if grant is not None:
        grant.check_frozen(config.root)
    req = publication.validate_source(config.root, create)
    publication.validate_source(config.root, schedule)
    states = {
        "create": ledger.status(config.root, create),
        "schedule": ledger.status(config.root, schedule),
    }
    if (
        not readonly
        and sync_calendar.day_value(req["date"])
        < sync_calendar.utc_time(now()).astimezone(sync_calendar.HONG_KONG).date()
    ):
        for part, action in (("create", create), ("schedule", schedule)):
            if states[part]["status"] == "prepared":
                states[part] = ledger.skip_past(config.root, action, now=now())
    if (
        all(s["status"] in ("success", "skipped") for s in states.values())
        or readonly
        and all(s["status"] != "unknown" for s in states.values())
    ):
        return states
    required = {"garmin.session"}
    if states["create"]["status"] != "success":
        required.add("get_workout_by_id")
    if (
        states["schedule"]["status"] == "unknown"
        or not readonly
        and states["schedule"]["status"] == "prepared"
    ):
        required.add("get_scheduled_workouts")
    if not readonly:
        for part, tool in (
            ("create", "upload_workout"),
            ("schedule", "schedule_workout"),
        ):
            if states[part]["status"] == "prepared":
                required.add(tool)
    auth = permission(config, grant, [create, schedule], required, now=now)
    service = run_services.garmin(config)
    opener = garmin_publication.session_opener(
        service.token_root,
        config.root,
        is_cn=service.is_cn,
        timeout=(
            sync_calendar.utc_time(auth.expires_utc) - sync_calendar.utc_time(now())
        ).total_seconds(),
        factory=garmin_fit.sdk_session,
    )
    selected = garmin_publication.reconcile if readonly else garmin_publication.deliver
    return await selected(config.root, create, schedule, opener, auth, now=now)


async def weekly(
    config: run_config.Config,
    end: str,
    selection: dict[str, Any],
    grant: run_authorization.Grant | None,
    *,
    now: Callable[[], str],
) -> dict[str, Any]:
    if grant is not None:
        grant.check_frozen(config.root)
    prepared = publication.prepare_weekly(
        config.root,
        end,
        selection["revision_id"],
        selection["revision_sha256"],
        recipient=selection["recipient"],
        sender=selection["sender"],
        late=selection["late"],
        mail_version=selection.get("mail_version", 1),
    )
    try:
        email = mail(config, prepared["mail"], grant, readonly=False, now=now)
    except ValueError:
        email = {
            **mail_state(config, prepared["mail"]),
            "error_code": "weekly_mail_unavailable_or_unauthorized",
        }
    workouts = []
    for pair in prepared["workouts"]:
        try:
            outcome = await course(
                config, pair["create"], pair["schedule"], grant, readonly=False, now=now
            )
        except ValueError:
            outcome = {
                "create": ledger.status(config.root, pair["create"]),
                "schedule": ledger.status(config.root, pair["schedule"]),
                "error_code": "weekly_workout_unavailable_or_unauthorized",
            }
        workouts.append(outcome)
    states = [email, *(v[p] for v in workouts for p in ("create", "schedule"))]
    status = (
        "complete"
        if all(s["status"] in ("success", "skipped") for s in states)
        else "unknown"
        if any(s["status"] == "unknown" for s in states)
        else "pending"
    )
    return {
        "status": status,
        "late": selection["late"],
        "mail": email,
        "workouts": workouts,
        "seal": prepared["seal"],
    }
