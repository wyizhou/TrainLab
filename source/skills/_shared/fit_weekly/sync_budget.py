from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_sync,
    run_authorization,
    storage,
    sync_calendar,
)


class Budget:
    def __init__(self, grant: run_authorization.Grant, now: Callable[[], str]):
        self.grant, self.now = grant, now
        self.scope = grant.value()["sync"]
        if self.scope is None:
            raise ValueError("sync_authorization_required")
        self.key = "sync-budget:" + storage.digest(grant.key.encode())
        self.observed: tuple[float, float] | None = None

    def claim(self, root: Path) -> None:
        self.grant.freeze(root, now=self.now())
        with storage.open_store(root) as db:
            self.bind(db).remaining()

    def bind(
        self, db: sqlite3.Connection, spec: fit_sync.SyncSpec | None = None
    ) -> Bound:
        if spec is not None:
            dates = sync_calendar.days_between(
                sync_calendar.day_value(spec.inventory.start_date),
                sync_calendar.day_value(spec.inventory.end_date),
            )
            expected = self.grant.sync_spec(dates, is_cn=spec.is_cn, now=self.now())
            if expected != spec:
                raise ValueError("sync_budget_scope_invalid")
        return Bound(self, db)


class Bound:
    def __init__(self, owner: Budget, db: sqlite3.Connection):
        self.owner, self.db = owner, db
        self.key, self.scope = owner.key, owner.scope
        self.clock = sync_calendar.utc_time(owner.now()).timestamp()
        owner.grant.check_time(owner.now())
        saved = fit_sync.document(db, self.key + ":claim")
        identity = storage.digest(owner.grant._body.encode())
        if saved is None:
            saved = {
                "schema_version": "fit_sync_budget_claim_v1",
                "authorization_sha256": identity,
                "started_epoch": self.clock,
                "deadline_epoch": min(
                    self.clock + self.scope["total_timeout_seconds"],
                    sync_calendar.utc_time(owner.grant.expires_utc).timestamp(),
                ),
            }
            fit_sync.put(db, self.key + ":claim", saved)
        if saved["authorization_sha256"] != identity:
            raise ValueError("sync_budget_authorization_conflict")
        self.deadline = saved["deadline_epoch"]
        self.events: list[dict[str, Any]] = []
        while (
            item := fit_sync.document(db, f"{self.key}:clock:{len(self.events) + 1}")
        ) is not None:
            self.events.append(item)
        previous = (
            self.events[-1]
            if self.events
            else {
                "clock_epoch": saved["started_epoch"],
                "effective_epoch": saved["started_epoch"],
            }
        )
        if self.clock < previous["clock_epoch"]:
            raise ValueError("sync_budget_clock_rollback")
        self.effective = max(self.clock, previous["effective_epoch"])
        self.monotonic = time.monotonic()
        if owner.observed is not None:
            effective, monotonic = owner.observed
            self.effective = max(self.effective, effective + self.monotonic - monotonic)

    def remaining(self) -> float:
        clock = sync_calendar.utc_time(self.owner.now()).timestamp()
        if clock < self.clock:
            raise ValueError("sync_budget_clock_rollback")
        effective = max(clock, self.effective + time.monotonic() - self.monotonic)
        value = {"clock_epoch": clock, "effective_epoch": effective}
        fit_sync.put(self.db, f"{self.key}:clock:{len(self.events) + 1}", value)
        self.events.append(value)
        self.clock = clock
        self.owner.observed = (effective, time.monotonic())
        left = self.deadline - effective
        if left <= 0:
            raise ValueError("sync_budget_exhausted")
        return left

    def calls(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        while (
            item := fit_sync.document(self.db, f"{self.key}:call:{len(result) + 1}")
        ) is not None:
            result.append(item)
        return result

    def check(
        self, kind: str, arguments: dict[str, Any], *, include_session: bool = False
    ) -> None:
        self.remaining()
        calls = self.calls()
        limits = {
            "initialize": self.scope["max_session_starts"],
            "inventory": self.scope["max_pages"],
            "download": self.scope["max_download_calls"],
        }
        tool_limit = self.scope.get("max_tool_calls", sum(limits.values()))
        if (
            len(calls) + 1 + int(include_session) > tool_limit
            or sum(c["kind"] == kind for c in calls) >= limits[kind]
        ):
            raise ValueError("sync_budget_exhausted")
        if (
            include_session
            and sum(c["kind"] == "initialize" for c in calls) >= limits["initialize"]
        ):
            raise ValueError("sync_budget_exhausted")
        used = 0
        for call in calls:
            if call["kind"] == "inventory":
                settled = fit_sync.document(
                    self.db, f"{self.key}:activities:{call['ordinal']}"
                )
                used += settled["count"] if settled else call["activity_capacity"]
        if (
            kind == "inventory"
            and used + arguments["page_size"] > self.scope["max_activities"]
        ):
            raise ValueError("sync_activity_budget_exhausted")

    def reserve(self, intent: dict[str, Any]) -> None:
        kind, arguments = intent["call_kind"], intent["arguments"]
        self.check(kind, arguments)
        digest = storage.digest(storage.canonical(intent).encode())
        if any(c["intent_sha256"] == digest for c in self.calls()):
            raise ValueError("sync_budget_call_unknown")
        ordinal = len(self.calls()) + 1
        fit_sync.put(
            self.db,
            f"{self.key}:call:{ordinal}",
            {
                "schema_version": "fit_sync_budget_call_v1",
                "ordinal": ordinal,
                "kind": kind,
                "intent_sha256": digest,
                "job_key": intent["job_key"],
                "activity_capacity": arguments["page_size"]
                if kind == "inventory"
                else 0,
            },
        )

    def settle(self, intent: dict[str, Any], value: dict[str, Any]) -> None:
        if intent["call_kind"] != "inventory":
            return
        digest = storage.digest(storage.canonical(intent).encode())
        matches = [c for c in self.calls() if c["intent_sha256"] == digest]
        if len(matches) != 1 or len(value["items"]) > matches[0]["activity_capacity"]:
            raise ValueError("sync_budget_capture_invalid")
        fit_sync.put(
            self.db,
            f"{self.key}:activities:{matches[0]['ordinal']}",
            {"intent_sha256": digest, "count": len(value["items"])},
        )
