"""Durable read-only inventory discovery and Hong Kong calendar rules.

An inventory receipt is not a FIT-download or email receipt. Only a complete
page chain proves a day's queried membership; today's result stays provisional.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from skills._shared.fit_weekly import fit_time, storage

HONG_KONG = ZoneInfo("Asia/Hong_Kong")
PageFetcher = Callable[[str, str, int, int], dict[str, Any]]


def utc_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value
    ):
        raise ValueError("sync_time_invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def day_value(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("sync_date_invalid")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed < date(2022, 1, 1):
        raise ValueError("sync_date_invalid")
    return parsed


def days_between(start: date, end: date) -> list[str]:
    return [
        (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
    ]


def daily_slot(now_utc: str) -> str:
    local = utc_time(now_utc).astimezone(HONG_KONG)
    return (local.date() - timedelta(days=int(local.hour < 22))).isoformat()


def weekly_slot(now_utc: str) -> dict[str, Any]:
    local = utc_time(now_utc).astimezone(HONG_KONG)
    sunday = local.date() - timedelta(days=(local.weekday() + 1) % 7)
    cutoff = datetime.combine(sunday, time(15), HONG_KONG)
    if local < cutoff:
        cutoff -= timedelta(days=7)
    start = cutoff - timedelta(days=7)
    return {
        "start_utc": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_utc": cutoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_dates": days_between(
            cutoff.date() + timedelta(days=1), cutoff.date() + timedelta(days=7)
        ),
    }


def in_week(activity_end_utc: str, slot: dict[str, Any]) -> bool:
    return (
        utc_time(slot["start_utc"])
        <= fit_time.utc_time(activity_end_utc)
        < utc_time(slot["end_utc"])
    )


@dataclass(frozen=True)
class InventoryRequest:
    key: str
    start_date: str
    end_date: str
    as_of_utc: str
    page_size: int
    max_calls: int

    def validate(self) -> None:
        today = utc_time(self.as_of_utc).astimezone(HONG_KONG).date()
        if (
            not isinstance(self.key, str)
            or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,160}", self.key)
            or not day_value(self.start_date) <= day_value(self.end_date) <= today
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= 100
            or type(self.max_calls) is not int
            or self.max_calls < 1
        ):
            raise ValueError("sync_request_invalid")


def durable(db: sqlite3.Connection) -> None:
    db.commit()
    db.execute("BEGIN IMMEDIATE")


def day_status(db: sqlite3.Connection, day: str) -> str:
    day_value(day)
    statuses = {
        row[0] for row in db.execute("SELECT status FROM sync_days WHERE day=?", (day,))
    }
    if "complete" in statuses:
        return "complete"
    if "provisional" in statuses:
        return "provisional"
    if db.execute("SELECT 1 FROM sync_gaps WHERE day=?", (day,)).fetchone():
        return "gap"
    return "unqueried"


def record_gaps(db: sqlite3.Connection, first_day: str, now_utc: str) -> None:
    start = day_value(first_day)
    today = utc_time(now_utc).astimezone(HONG_KONG).date()
    for day in days_between(start, today - timedelta(days=1)):
        if day_status(db, day) != "complete":
            db.execute("INSERT OR IGNORE INTO sync_gaps VALUES(?,?)", (day, now_utc))


def pending_days(db: sqlite3.Connection, now_utc: str) -> list[str]:
    today = utc_time(now_utc).astimezone(HONG_KONG).date()
    pending = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    for row in db.execute("SELECT day FROM sync_gaps"):
        if row[0] <= today.isoformat() and day_status(db, row[0]) != "complete":
            pending.add(row[0])
    return sorted(pending)


def valid_page(
    value: Any, request: InventoryRequest, number: int, seen: set[str]
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"page", "page_size", "has_more", "items"}
        or type(value["page"]) is not int
        or value["page"] != number
        or type(value["page_size"]) is not int
        or value["page_size"] != request.page_size
        or type(value["has_more"]) is not bool
        or not isinstance(value["items"], list)
        or len(value["items"]) > request.page_size
        or (value["has_more"] and not value["items"])
    ):
        raise ValueError("inventory_page_invalid")
    page_seen: set[str] = set()
    for item in value["items"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"activity_ref", "activity_date"}
            or not isinstance(item["activity_ref"], str)
            or not re.fullmatch(r"[0-9]{1,32}", item["activity_ref"])
            or not isinstance(item["activity_date"], str)
            or not request.start_date <= item["activity_date"] <= request.end_date
            or item["activity_ref"] in seen | page_seen
        ):
            raise ValueError("inventory_page_invalid")
        try:
            day_value(item["activity_date"])
        except ValueError as exc:
            raise ValueError("inventory_page_invalid") from exc
        page_seen.add(item["activity_ref"])
    # Detach the durable evidence from the Provider's mutable Python objects.
    return json.loads(storage.canonical(value))


def inventory_steps(
    db: sqlite3.Connection, request: InventoryRequest
) -> Generator[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request.validate()
    text = storage.canonical(asdict(request))
    input_sha = storage.digest(text.encode())
    old = db.execute(
        "SELECT input_json,input_sha256 FROM sync_jobs WHERE job_key=?",
        (request.key,),
    ).fetchone()
    if old is not None and tuple(old) != (text, input_sha):
        raise ValueError("sync_job_conflict")
    if old is None:
        db.execute(
            "INSERT INTO sync_jobs VALUES(?,?,?)", (request.key, text, input_sha)
        )
        durable(db)
    done = db.execute(
        "SELECT content_json,content_sha256 FROM documents WHERE kind='sync_receipt' AND logical_key=? AND input_sha256=?",
        (f"inventory:{request.key}", input_sha),
    ).fetchone()
    if done is not None:
        if storage.digest(done[0].encode()) != done[1]:
            raise ValueError("inventory_receipt_invalid")
        return json.loads(done[0])
    stored = db.execute(
        "SELECT c.page,r.content_json,r.content_sha256 FROM sync_results r JOIN sync_calls c USING(job_key,ordinal) WHERE r.job_key=? AND r.status='page' ORDER BY c.page",
        (request.key,),
    ).fetchall()
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, row in enumerate(stored):
        if (
            row[0] != number
            or storage.digest(row[1].encode()) != row[2]
            or (pages and not pages[-1]["has_more"])
        ):
            raise ValueError("inventory_saved_page_invalid")
        value = valid_page(json.loads(row[1]), request, number, seen)
        pages.append(value)
        seen.update(item["activity_ref"] for item in value["items"])
    while not pages or pages[-1]["has_more"]:
        number = len(pages)
        spent = db.execute(
            "SELECT COUNT(*) FROM sync_calls WHERE job_key=?", (request.key,)
        ).fetchone()[0]
        if spent >= request.max_calls:
            raise ValueError("inventory_budget_exhausted")
        arguments = {
            "start_date": request.start_date,
            "end_date": request.end_date,
            "page": number,
            "page_size": request.page_size,
        }
        ordinal = spent + 1
        db.execute(
            "INSERT INTO sync_calls VALUES(?,?,?,?)",
            (request.key, ordinal, number, storage.canonical(arguments)),
        )
        # The call and its spent budget are durable before touching Provider.
        durable(db)
        code = "inventory_provider_failed"
        try:
            response = yield arguments
            code = "inventory_page_invalid"
            value = valid_page(response, request, number, seen)
        except Exception as exc:
            error = storage.canonical({"error_code": code})
            db.execute(
                "INSERT INTO sync_results VALUES(?,?,'error',?,?)",
                (request.key, ordinal, error, storage.digest(error.encode())),
            )
            durable(db)
            raise ValueError(code) from exc
        content = storage.canonical(value)
        db.execute(
            "INSERT INTO sync_results VALUES(?,?,'page',?,?)",
            (request.key, ordinal, content, storage.digest(content.encode())),
        )
        durable(db)
        pages.append(value)
        seen.update(item["activity_ref"] for item in value["items"])
    items = sorted(
        (item for page in pages for item in page["items"]),
        key=lambda item: (item["activity_date"], item["activity_ref"]),
    )
    today = utc_time(request.as_of_utc).astimezone(HONG_KONG).date()
    for day in days_between(day_value(request.start_date), day_value(request.end_date)):
        status = "complete" if day_value(day) < today else "provisional"
        count = sum(item["activity_date"] == day for item in items)
        db.execute(
            "INSERT INTO sync_days VALUES(?,?,?,?)",
            (day, request.key, status, count),
        )
    result = {
        "schema_version": "fit_inventory_receipt_v1",
        "job_key": request.key,
        "inventory_complete": True,
        "collection_complete": not items,
        "activity_count": len(items),
        "items": items,
        "provider_calls": db.execute(
            "SELECT COUNT(*) FROM sync_calls WHERE job_key=?", (request.key,)
        ).fetchone()[0],
        "unresolved_calls": db.execute(
            "SELECT COUNT(*) FROM sync_calls c LEFT JOIN sync_results r USING(job_key,ordinal) WHERE c.job_key=? AND r.ordinal IS NULL",
            (request.key,),
        ).fetchone()[0],
        "external_actions": 0,
    }
    storage.put_document(
        db, "sync_receipt", f"inventory:{request.key}", input_sha, result
    )
    return result


def collect_inventory(
    root: Path, request: InventoryRequest, fetch: PageFetcher
) -> dict[str, Any]:
    with storage.open_store(root) as db:
        steps = inventory_steps(db, request)
        try:
            arguments = next(steps)
            while True:
                try:
                    response = fetch(
                        arguments["start_date"],
                        arguments["end_date"],
                        arguments["page"],
                        arguments["page_size"],
                    )
                except Exception as exc:
                    arguments = steps.throw(exc)
                else:
                    arguments = steps.send(response)
        except StopIteration as completed:
            return completed.value
        finally:
            steps.close()
