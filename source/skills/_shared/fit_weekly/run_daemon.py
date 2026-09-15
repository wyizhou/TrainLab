from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_sync,
    gmail_labels,
    lifecycle,
    model_job,
    publication_ledger,
    run_authorization,
    run_config,
    run_reconcile,
    run_services,
    run_sync,
    run_weekly,
    schedule_state,
    storage,
    sync_calendar,
)


@dataclass(frozen=True)
class Schedule:
    first_day: str
    grants: dict[str, str]


def load(root: Path, filename: str, *, now: str) -> Schedule:
    try:
        value = run_config.read_object(root, run_config.relative_path(root, filename))
        if (
            set(value) != {"schema_version", "first_day", "grants"}
            or value["schema_version"] != "fit_schedule_config_v1"
        ):
            raise ValueError("shape")
        first = sync_calendar.day_value(value["first_day"])
        today = sync_calendar.utc_time(now).astimezone(sync_calendar.HONG_KONG).date()
        if (
            first > today
            or not isinstance(value["grants"], dict)
            or len(value["grants"]) > 1000
        ):
            raise ValueError("shape")
        for slot, filename in value["grants"].items():
            schedule_state.slot_time(slot)
            run_config.relative_path(root, filename)
        return Schedule(value["first_day"], dict(value["grants"]))
    except (ValueError, KeyError, TypeError):
        raise ValueError("schedule_config_invalid") from None


def due_slots(now: str, first_day: str) -> list[str]:
    local = sync_calendar.utc_time(now).astimezone(sync_calendar.HONG_KONG)
    end = sync_calendar.weekly_slot(now)["end_utc"]
    weekly_day = (
        sync_calendar.utc_time(end)
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    )
    result = [f"weekly:{end}"] if weekly_day >= first_day else []
    if local.hour >= 22 and local.date().isoformat() >= first_day:
        result.append("daily:" + local.date().isoformat())
    return result


def grant_for(
    root: Path, filename: str, now: str, expected: dict[str, Any] | None = None
) -> run_authorization.Grant:
    value = run_config.read_object(root, run_config.relative_path(root, filename))
    if expected is not None:
        if (
            storage.digest(storage.canonical(value).encode())
            != expected["authorization_sha256"]
        ):
            raise ValueError("schedule_authorization_conflict")
    grant = run_authorization.parse(value, now=now)
    grant.check_frozen(root)
    return grant


def claim(
    root: Path,
    slot: str,
    filename: str,
    grant: run_authorization.Grant,
    now: str,
    *,
    late: bool,
    config: run_config.Config | None = None,
) -> dict[str, Any]:
    grant.check_frozen(root)
    grant.check_time(now)
    if slot.startswith("daily:"):
        selection = run_sync.daily_dates(root, grant, now=now)
        dates, unfinished = selection["dates"], selection["unfinished_jobs"]
        business_key = run_sync.batch_key(grant, dates)
        action = run_sync.action_key(grant, dates)
        authorization = grant.publication(now=now)
        if action not in authorization.action_keys or not {
            "gmail.send",
            "gmail.get",
            "gmail.profile",
            "gmail.modify",
            "gmail.labels.list",
        } <= set(authorization.max_calls):
            raise ValueError("schedule_mail_authorization_required")
        if not authorization.start_date <= dates[-1] <= authorization.end_date:
            raise ValueError("schedule_mail_authorization_required")
        as_of = grant.value()["sync"]["as_of_utc"]
        if as_of < schedule_state.slot_time(slot):
            raise ValueError("schedule_sync_as_of_invalid")
    else:
        end = slot[7:]
        week = sync_calendar.weekly_slot(end)
        dates = sync_calendar.days_between(
            *[
                sync_calendar.utc_time(week[k])
                .astimezone(sync_calendar.HONG_KONG)
                .date()
                for k in ("start_utc", "end_utc")
            ]
        )
        value = grant.value()
        if (
            value["sync"] is None
            or not set(dates) <= set(value["sync"]["dates"])
            or value["sync"]["as_of_utc"] < end
        ):
            raise ValueError("schedule_weekly_authorization_required")
        if {m["stage"] for m in value["models"] if m["period_end_utc"] == end} != {
            "plan",
            "summary",
        }:
            raise ValueError("schedule_weekly_authorization_required")
        authorization = grant.publication(now=now)
        if f"weekly:{end}:gmail" not in authorization.action_keys:
            raise ValueError("schedule_mail_authorization_required")
        with storage.open_store(root) as db:
            unfinished = fit_sync.unfinished_jobs(db)
        business_key = end
    config = config or run_config.load(root)
    envelope = run_services.gmail_envelope(config)
    mail_action = action if slot.startswith("daily:") else f"weekly:{slot[7:]}:gmail"
    required_actions = {
        gmail_labels.ensure_key(envelope["account"]),
        gmail_labels.apply_key(mail_action),
    }
    if not required_actions <= set(authorization.action_keys) or not {
        "gmail.modify",
        "gmail.labels.list",
        "gmail.get",
        "gmail.profile",
        "gmail.send",
    } <= set(authorization.max_calls):
        raise ValueError("schedule_mail_authorization_required")
    digest = grant.freeze(root, now=now)
    value = {
        "slot": slot,
        "due_utc": schedule_state.slot_time(slot),
        "late": late,
        "dates": dates,
        "unfinished_jobs": unfinished,
        "authorization_file": filename,
        "authorization_key": grant.key,
        "authorization_sha256": digest,
        "business_key": business_key,
    }
    schedule_state.append(
        root, {"kind": "claim", "now": now, "slot": slot, "value": value}
    )
    return value


class Scheduler:
    def __init__(
        self,
        config: run_config.Config,
        schedule: Schedule,
        *,
        now: Callable[[], str] = publication_ledger.utc_now,
    ):
        self.config, self.schedule, self.now = config, schedule, now
        self.started = now()
        self.state = schedule_state.start(config.root, schedule.first_day, self.started)
        self.seen: set[str] = set()
        self.recovered = False
        self.observed = self.started

    def current_time(self) -> str:
        now = self.now()
        if now < schedule_state.read(self.config.root)["last_seen_utc"]:
            raise ValueError("schedule_clock_rollback")
        return now

    async def execute(
        self, saved: dict[str, Any], grant: run_authorization.Grant
    ) -> None:
        root, slot = self.config.root, saved["slot"]
        now = self.current_time()
        state = schedule_state.observe(root, now)
        grant.check_time(now)
        schedule_state.append(
            root,
            {
                "kind": "attempt",
                "slot": slot,
                "now": now,
                "number": state["attempts"].get(slot, 0) + 1,
            },
        )
        try:
            if slot.startswith("daily:"):
                batch = await run_sync.collect(
                    self.config, grant, dates=saved["dates"], now=self.now
                )
                try:
                    mail = run_sync.notify(self.config, grant, batch, now=self.now)
                except (ValueError, OSError):
                    mail = {"status": "blocked"}
                result = {
                    "status": "complete"
                    if batch["status"] == "complete" and mail["status"] == "success"
                    else "unknown"
                    if mail["status"] == "unknown"
                    else "failed",
                    "batch_key": batch["batch_key"],
                    "sync": batch["status"],
                    "mail": mail["status"],
                }
            else:
                result = await run_weekly.run(
                    self.config, slot[7:], grant, late=saved["late"], now=self.now
                )
                result = {
                    "status": result["status"],
                    "period_end_utc": slot[7:],
                    "revision_id": result.get("revision_id"),
                    "revision_sha256": result.get("revision_sha256"),
                }
                if result["status"] not in (
                    "complete",
                    "failed",
                    "unknown",
                    "blocked",
                    "pending",
                ):
                    result["status"] = "failed"
            lifecycle.check_stop()
        except model_job.AdapterInterrupted:
            lifecycle.check_stop()
            result = {"status": "unknown", "error_code": "schedule_capture_unavailable"}
        except (ValueError, OSError):
            lifecycle.check_stop()
            result = {"status": "failed", "error_code": "schedule_business_failed"}
        with storage.open_store(root) as db:
            result["unfinished_jobs"] = fit_sync.unfinished_jobs(db)
        schedule_state.append(
            root,
            {
                "kind": "result",
                "slot": slot,
                "now": max(self.now(), saved["due_utc"]),
                "value": result,
            },
        )

    async def tick(self) -> None:
        lifecycle.check_stop()
        root, now = self.config.root, self.current_time()
        state = schedule_state.read(root)
        slots = due_slots(now, self.schedule.first_day)
        if now[:10] != self.observed[:10] or slots != due_slots(
            self.observed, self.schedule.first_day
        ):
            schedule_state.observe(root, now)
            self.observed = now
        if not self.recovered:
            for slot, saved in state["claims"].items():
                if slot.startswith("daily:") or slot in slots:
                    if slot not in state["outcomes"]:
                        slots.insert(0, slot)
            self.recovered = True
        for slot in dict.fromkeys(slots):
            if slot in self.seen:
                continue
            now = self.current_time()
            self.seen.add(slot)
            state = schedule_state.read(root)
            saved = state["claims"].get(slot)
            filename = (
                saved["authorization_file"] if saved else self.schedule.grants.get(slot)
            )
            if filename is None:
                schedule_state.blocked(
                    root, slot, now, "schedule_authorization_missing"
                )
                continue
            try:
                grant = grant_for(root, filename, now, saved)
                if (
                    slot in state["outcomes"]
                    and state["outcomes"][slot]["status"] == "unknown"
                    and slot.startswith("weekly:")
                ):
                    run_reconcile.local(root, slot[7:])
                if saved is None:
                    due = schedule_state.slot_time(slot)
                    late = self.started > due or sync_calendar.utc_time(
                        now
                    ) - sync_calendar.utc_time(due) >= timedelta(days=7)
                    saved = claim(
                        root, slot, filename, grant, now, late=late, config=self.config
                    )
                if slot not in state["outcomes"]:
                    await self.execute(saved, grant)
                    self.current_time()
            except (ValueError, OSError) as exc:
                lifecycle.check_stop()
                if str(exc) == "schedule_clock_rollback":
                    raise
                code = (
                    "schedule_authorization_conflict"
                    if str(exc)
                    in ("schedule_authorization_conflict", "store_file_conflict")
                    else "schedule_authorization_or_business_unavailable"
                )
                schedule_state.blocked(
                    root,
                    slot,
                    max(self.current_time(), schedule_state.slot_time(slot)),
                    code,
                )
        lifecycle.check_stop()


async def run(
    config: run_config.Config,
    schedule: Schedule,
    *,
    now: Callable[[], str] = publication_ledger.utc_now,
) -> None:
    scheduler = Scheduler(config, schedule, now=now)
    while True:
        await scheduler.tick()
        await asyncio.sleep(0.25)
