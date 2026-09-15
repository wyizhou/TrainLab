"""Four-tool pinned MCP publisher, one create and one schedule per action."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    garmin_fit,
    garmin_workouts,
    publication,
    sync_calendar,
)
from skills._shared.fit_weekly import publication_ledger as ledger

TOOLS = {
    "upload_workout",
    "get_workout_by_id",
    "schedule_workout",
    "get_scheduled_workouts",
}


@asynccontextmanager
async def open_session(
    token_root: Path,
    work_root: Path,
    *,
    is_cn: bool,
    timeout: float,
    journal: ledger.Journal,
    action: str,
    factory: garmin_fit.SessionFactory = garmin_fit.sdk_session,
) -> AsyncIterator[Any]:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("garmin_timeout_invalid")
    journal.reserve(action, "garmin.session", {"is_cn": is_cn})
    remaining = journal.remaining
    remaining()
    before = garmin_fit.token_snapshot(token_root)
    spec = garmin_fit.launch_spec(token_root, work_root, is_cn=is_cn)
    spec["environment"]["GARMIN_ENABLED_TOOLS"] = ",".join(sorted(TOOLS))
    stack = AsyncExitStack()
    try:
        try:
            async with asyncio.timeout(min(timeout, remaining())):
                session = await stack.enter_async_context(factory(spec))
                await session.initialize()
                declared = await session.list_tools()
                names = [t.name for t in declared.tools]
                if (
                    len(names) != len(TOOLS)
                    or set(names) != TOOLS
                    or getattr(declared, "nextCursor", None)
                ):
                    raise ValueError("tools")
                remaining()
        except Exception:
            raise ValueError("garmin_publication_session_unavailable") from None
        yield session
    finally:
        try:
            try:
                cleanup_seconds = min(timeout, remaining())
            except ValueError:
                # Safety cleanup does not authorize another business call.
                cleanup_seconds = timeout
            async with asyncio.timeout(cleanup_seconds):
                await stack.aclose()
        finally:
            if garmin_fit.token_snapshot(token_root) != before:
                raise ValueError("garmin_token_changed")


async def call(
    journal: ledger.Journal,
    action: str,
    session: Any,
    tool: str,
    arguments: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if tool not in TOOLS:
        raise ValueError("garmin_publication_tool_invalid")
    call_key = journal.reserve(action, tool, arguments)
    try:
        async with asyncio.timeout(journal.remaining()):
            result = await session.call_tool(tool, arguments=arguments)
        if (
            getattr(result, "isError", None) is not False
            or not isinstance(result.content, list)
            or len(result.content) != 1
            or getattr(result.content[0], "type", None) != "text"
            or not isinstance(result.content[0].text, str)
        ):
            raise ValueError("shape")
        value = garmin_fit.strict_object(result.content[0].text.encode())
        if tool == "upload_workout":
            if value.get("status") != "success":
                raise ValueError("create_status")
            value = {"workout_id": garmin_workouts.ident(value.get("workout_id"))}
            journal.capture(call_key, value)
        elif tool == "schedule_workout":
            if (
                value.get("status") != "success"
                or garmin_workouts.ident(value.get("workout_id"))
                != arguments["workout_id"]
                or value.get("scheduled_date") != arguments["calendar_date"]
            ):
                raise ValueError("schedule_status")
            value = {
                "workout_id": arguments["workout_id"],
                "date": arguments["calendar_date"],
            }
            journal.capture(call_key, value)
        journal.remaining()
        return call_key, value
    except Exception:
        raise ValueError("garmin_publication_call_failed") from None


def current_date(now: Callable[[], str], date: str) -> None:
    if (
        sync_calendar.day_value(date)
        < sync_calendar.utc_time(now()).astimezone(sync_calendar.HONG_KONG).date()
    ):
        raise ValueError("garmin_past_date_not_scheduled")


async def process(
    root: Path,
    create: str,
    schedule: str,
    session: Any,
    authorization: ledger.Authorization,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    first, second = ledger.status(root, create), ledger.status(root, schedule)
    if first["status"] == "skipped" or all(
        s["status"] in ("success", "skipped") for s in (first, second)
    ):
        return {"create": first, "schedule": second}
    req = publication.validate_source(root, create)
    scheduled = publication.validate_source(root, schedule)
    if (
        req["kind"] != "garmin_create"
        or scheduled["kind"] != "garmin_schedule"
        or scheduled["payload"]
        != {"create_action": create, "calendar_date": req["date"]}
        or scheduled["source_sha256"] != req["source_sha256"]
    ):
        raise ValueError("garmin_course_pair_invalid")
    dto = req["payload"]["workout_data"]
    with ledger.open_ledger(root, authorization, now=now) as journal:
        stack = AsyncExitStack()
        try:
            journal.check(create)
            journal.check(schedule)
            if first["status"] == "prepared" and not readonly:
                current_date(now, req["date"])
            if callable(session):
                session = await stack.enter_async_context(session(journal, create))
            workout_id = None
            if first["status"] == "success":
                workout_id = garmin_workouts.ident(first["evidence"]["workout_id"])
            else:
                captured = journal.captures(create, "upload_workout")
                ids = {garmin_workouts.ident(c["workout_id"]) for c in captured}
                if first["status"] == "prepared" and not readonly:
                    current_date(now, req["date"])
                    journal.intent(create)
                    _, uploaded = await call(
                        journal,
                        create,
                        session,
                        "upload_workout",
                        {"workout_data": dto},
                    )
                    ids = {uploaded["workout_id"]}
                if len(ids) != 1:
                    return {
                        "create": ledger.state(journal.db, create),
                        "schedule": ledger.state(journal.db, schedule),
                    }
                workout_id = ids.pop()
                call_key, detail = await call(
                    journal,
                    create,
                    session,
                    "get_workout_by_id",
                    {"workout_id": workout_id},
                )
                garmin_workouts.verify(detail, dto, workout_id)
                evidence = {"workout_id": workout_id, "workout_sha256": ledger.sha(dto)}
                journal.capture(call_key, evidence)
                first = journal.success(create, evidence)
            if second["status"] not in ("success", "skipped"):
                if second["status"] == "prepared":
                    if readonly:
                        return {"create": first, "schedule": second}
                    current_date(now, req["date"])
                    journal.intent(schedule)
                    await call(
                        journal,
                        schedule,
                        session,
                        "schedule_workout",
                        {"workout_id": workout_id, "calendar_date": req["date"]},
                    )
                call_key, calendar = await call(
                    journal,
                    schedule,
                    session,
                    "get_scheduled_workouts",
                    {"start_date": req["date"], "end_date": req["date"]},
                )
                entries = calendar.get("scheduled_workouts")
                if (
                    not isinstance(entries, list)
                    or type(calendar.get("count")) is not int
                    or calendar["count"] != len(entries)
                    or calendar.get("date_range")
                    != {"start": req["date"], "end": req["date"]}
                ):
                    raise ValueError("garmin_calendar_invalid")
                matches = [
                    entry
                    for entry in entries
                    if str(entry.get("workout_id")) == str(workout_id)
                ]
                if len(matches) != 1 or matches[0].get("date") != req["date"]:
                    raise ValueError("garmin_calendar_mismatch")
                evidence = {
                    "workout_id": workout_id,
                    "scheduled_workout_id": garmin_workouts.ident(
                        matches[0].get("scheduled_workout_id")
                    ),
                    "date": req["date"],
                }
                journal.capture(call_key, evidence)
                second = journal.success(schedule, evidence)
        except Exception:
            first, second = (
                ledger.state(journal.db, create),
                ledger.state(journal.db, schedule),
            )
        finally:
            await stack.aclose()
        return {"create": first, "schedule": second}


async def deliver(
    root: Path,
    create: str,
    schedule: str,
    session: Any,
    authorization: ledger.Authorization,
    *,
    now: Callable[[], str] = ledger.utc_now,
) -> dict[str, Any]:
    return await process(
        root, create, schedule, session, authorization, readonly=False, now=now
    )


async def reconcile(
    root: Path,
    create: str,
    schedule: str,
    session: Any,
    authorization: ledger.Authorization,
    *,
    now: Callable[[], str] = ledger.utc_now,
) -> dict[str, Any]:
    return await process(
        root, create, schedule, session, authorization, readonly=True, now=now
    )


def session_opener(
    token_root: Path,
    work_root: Path,
    *,
    is_cn: bool,
    timeout: float,
    factory: garmin_fit.SessionFactory = garmin_fit.sdk_session,
) -> Callable[..., Any]:
    def opener(journal: ledger.Journal, action: str) -> Any:
        return open_session(
            token_root,
            work_root,
            is_cn=is_cn,
            timeout=timeout,
            journal=journal,
            action=action,
            factory=factory,
        )

    return opener
