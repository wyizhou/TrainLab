"""Immutable publication documents, single writer and durable per-call budgets."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import storage, sync_calendar
from skills._shared.scripts.schema_validation import validate_payload

WRITE_TOOLS = {
    "gmail.send",
    "gmail.labels.create",
    "gmail.modify",
    "upload_workout",
    "schedule_workout",
}
TOOLS = WRITE_TOOLS | {
    "garmin.session",
    "gmail.refresh",
    "gmail.profile",
    "gmail.get",
    "gmail.list",
    "gmail.labels.list",
    "get_workout_by_id",
    "get_scheduled_workouts",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(value: dict[str, Any]) -> str:
    return storage.digest(storage.canonical(value).encode())


def document(db: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT content_json,content_sha256 FROM documents WHERE kind='delivery_receipt' AND logical_key=?",
        (key,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or storage.digest(rows[0][0].encode()) != rows[0][1]:
        raise ValueError("publication_document_conflict")
    value = json.loads(rows[0][0])
    if storage.canonical(value) != rows[0][0]:
        raise ValueError("publication_document_invalid")
    return value


def put(db: sqlite3.Connection, key: str, value: dict[str, Any]) -> None:
    old = document(db, key)
    if old is not None and old != value:
        raise ValueError("publication_content_conflict")
    schema = value.get("schema_version")
    if schema and validate_payload(value, schema):
        raise ValueError("publication_schema_invalid")
    storage.put_document(db, "delivery_receipt", key, sha(value), value)
    sync_calendar.durable(db)


def key(action: str, suffix: str) -> str:
    if not isinstance(action, str) or not re.fullmatch(
        r"[A-Za-z0-9:_.-]{1,180}", action
    ):
        raise ValueError("publication_action_invalid")
    return "pub:" + storage.digest(action.encode()) + ":" + suffix


REQUEST_VERSIONS = {"fit_delivery_request_v1", "fit_delivery_request_v2"}


def valid_request(value: dict[str, Any]) -> bool:
    version = value.get("schema_version")
    return version in REQUEST_VERSIONS and not validate_payload(value, version)


def prepare(root: Path, request: dict[str, Any]) -> str:
    if not valid_request(request):
        raise ValueError("publication_request_invalid")
    action = request["action_key"]
    with storage.open_store(root) as db:
        put(db, key(action, "request"), request)
    return action


def request(db: sqlite3.Connection, action: str) -> dict[str, Any]:
    value = document(db, key(action, "request"))
    if value is None or not valid_request(value) or value["action_key"] != action:
        raise ValueError("publication_request_missing_or_invalid")
    return value


def state(db: sqlite3.Connection, action: str) -> dict[str, Any]:
    req = request(db, action)
    result = document(db, key(action, "success"))
    if result is not None:
        if result["request_sha256"] != sha(req):
            raise ValueError("publication_success_binding_invalid")
        return result
    skipped = document(db, key(action, "skipped"))
    if skipped is not None:
        if (
            skipped["request_sha256"] != sha(req)
            or document(db, key(action, "intent")) is not None
        ):
            raise ValueError("publication_skip_binding_invalid")
        return skipped
    return {
        "action_key": action,
        "status": "unknown" if document(db, key(action, "intent")) else "prepared",
    }


def status(root: Path, action: str) -> dict[str, Any]:
    with storage.open_store(root) as db:
        return state(db, action)


def skip_past(root: Path, action: str, *, now: str) -> dict[str, Any]:
    today = (
        sync_calendar.utc_time(now)
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    )
    with storage.open_store(root) as db:
        req = request(db, action)
        if (
            req["kind"] not in ("garmin_create", "garmin_schedule")
            or req["date"] >= today
        ):
            raise ValueError("publication_skip_invalid")
        existing = state(db, action)
        if existing["status"] != "prepared":
            return existing
        value = {
            "schema_version": "fit_delivery_skipped_v1",
            "action_key": action,
            "status": "skipped",
            "request_sha256": sha(req),
            "reason": "past_date",
            "observed_date": today,
        }
        put(db, key(action, "skipped"), value)
        return value


@dataclass(frozen=True)
class Authorization:
    key: str
    action_keys: tuple[str, ...]
    start_date: str
    end_date: str
    starts_utc: str
    expires_utc: str
    max_calls: dict[str, int]

    def validate(self) -> None:
        key(self.key, "auth")
        if (
            not self.action_keys
            or len(set(self.action_keys)) != len(self.action_keys)
            or sync_calendar.day_value(self.start_date)
            > sync_calendar.day_value(self.end_date)
            or sync_calendar.utc_time(self.starts_utc)
            >= sync_calendar.utc_time(self.expires_utc)
            or not self.max_calls
            or not set(self.max_calls) <= TOOLS
            or any(type(n) is not int or n < 1 for n in self.max_calls.values())
        ):
            raise ValueError("publication_authorization_invalid")
        for action in self.action_keys:
            key(action, "auth")


class Journal:
    def __init__(
        self,
        db: sqlite3.Connection,
        authorization: Authorization,
        now: Callable[[], str],
    ):
        authorization.validate()
        self.db, self.authorization, self.now = db, authorization, now
        self.auth_key = key(authorization.key, "authorization")
        body = json.loads(storage.canonical(asdict(authorization)))
        self.deadline = sync_calendar.utc_time(authorization.expires_utc)
        self.remaining()
        self.monotonic_end = (
            time.monotonic()
            + (self.deadline - sync_calendar.utc_time(now())).total_seconds()
        )
        put(db, self.auth_key, body)

    def remaining(self) -> float:
        current = sync_calendar.utc_time(self.now())
        left = (self.deadline - current).total_seconds()
        if hasattr(self, "monotonic_end"):
            left = min(left, self.monotonic_end - time.monotonic())
        if current < sync_calendar.utc_time(self.authorization.starts_utc) or left <= 0:
            raise ValueError("publication_time_budget_exhausted")
        return left

    def check(self, action: str) -> None:
        self.remaining()
        if action not in self.authorization.action_keys:
            raise ValueError("publication_scope_invalid")
        req = document(self.db, key(action, "request"))
        if (
            req
            and not self.authorization.start_date
            <= req["date"]
            <= self.authorization.end_date
        ):
            raise ValueError("publication_date_scope_invalid")

    def intent(self, action: str) -> None:
        self.check(action)
        if state(self.db, action)["status"] == "skipped":
            raise ValueError("publication_action_skipped")
        req = request(self.db, action)
        put(
            self.db,
            key(action, "intent"),
            {
                "schema_version": "fit_delivery_intent_v1",
                "action_key": action,
                "request_sha256": sha(req),
            },
        )

    def reserve(self, action: str, tool: str, arguments: dict[str, Any]) -> str:
        self.check(action)
        limit = self.authorization.max_calls.get(tool)
        if limit is None:
            raise ValueError("publication_tool_scope_invalid")
        prefix = self.auth_key + ":call:"
        rows = self.db.execute(
            "SELECT content_json FROM documents WHERE kind='delivery_receipt' AND substr(logical_key,1,?)=?",
            (len(prefix), prefix),
        ).fetchall()
        calls = [
            value
            for row in rows
            if (value := json.loads(row[0])).get("schema_version")
            == "fit_delivery_call_v1"
        ]
        if sum(c["tool"] == tool for c in calls) >= limit:
            raise ValueError("publication_call_budget_exhausted")
        call = {
            "schema_version": "fit_delivery_call_v1",
            "action_key": action,
            "tool": tool,
            "arguments": arguments,
            "authorization_key": self.authorization.key,
            "ordinal": len(calls) + 1,
        }
        if tool in WRITE_TOOLS:
            if document(self.db, key(action, "write")) is not None:
                raise ValueError("publication_write_already_reserved")
            if document(self.db, key(action, "intent")) is None:
                raise ValueError("publication_intent_required")
            # Both records must commit together before the Provider boundary.
            storage.put_document(
                self.db, "delivery_receipt", key(action, "write"), sha(call), call
            )
        call_key = prefix + str(len(calls) + 1)
        put(self.db, call_key, call)
        return call_key

    def capture(self, call_key: str, evidence: dict[str, Any]) -> None:
        # Callers pass narrowly validated protocol values, never headers/errors.
        put(self.db, call_key + ":capture", evidence)

    def captures(self, action: str, tool: str) -> list[dict[str, Any]]:
        result = []
        for row in self.db.execute(
            "SELECT logical_key,content_json FROM documents WHERE kind='delivery_receipt'"
        ):
            value = json.loads(row[1])
            if (
                value.get("schema_version") == "fit_delivery_call_v1"
                and value["action_key"] == action
                and value["tool"] == tool
                and not row[0].endswith(":write")
            ):
                captured = document(self.db, row[0] + ":capture")
                if captured is not None:
                    result.append(captured)
        return result

    def success(self, action: str, evidence: dict[str, Any]) -> dict[str, Any]:
        result = {
            "schema_version": "fit_delivery_result_v1",
            "action_key": action,
            "status": "success",
            "request_sha256": sha(request(self.db, action)),
            "evidence": evidence,
        }
        put(self.db, key(action, "success"), result)
        return result


@contextmanager
def open_ledger(
    root: Path, authorization: Authorization, *, now: Callable[[], str] = utc_now
) -> Iterator[Journal]:
    with storage.open_store(root) as db:
        yield Journal(db, authorization, now)
