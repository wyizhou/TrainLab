"""Single-writer FIT collection. Only an explicit caller may start Garmin.

The inventory calendar proves queried membership, not downloaded FIT closure.
Transport intents consume durable budgets before calls; captures precede SQL
results. Recovery reuses captures and files, never resets a job's allowance.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skills._shared.fit_weekly import garmin_fit, storage, sync_calendar

if TYPE_CHECKING:
    from skills._shared.fit_weekly.sync_budget import Bound


@dataclass(frozen=True)
class SyncSpec:
    inventory: sync_calendar.InventoryRequest
    max_download_calls: int
    max_session_starts: int
    timeout_seconds: float
    is_cn: bool
    total_timeout_seconds: float | None = None

    def validate(self) -> None:
        self.inventory.validate()
        if (
            type(self.max_download_calls) is not int
            or self.max_download_calls < 0
            or type(self.max_session_starts) is not int
            or self.max_session_starts < 1
            or type(self.is_cn) is not bool
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("fit_sync_spec_invalid")
        if self.total_timeout_seconds is not None and (
            isinstance(self.total_timeout_seconds, bool)
            or not isinstance(self.total_timeout_seconds, (int, float))
            or not math.isfinite(self.total_timeout_seconds)
            or self.total_timeout_seconds <= 0
        ):
            raise ValueError("fit_sync_total_budget_invalid")


def read_request(value: dict[str, Any]) -> SyncSpec:
    """Read frozen v1 evidence without inventing a collection authorization."""
    try:
        version, data = value["schema_version"], value["request"]
        if version not in ("fit_sync_request_v1", "fit_sync_request_v2"):
            raise ValueError("version")
        if (version == "fit_sync_request_v1") != ("total_timeout_seconds" not in data):
            raise ValueError("version_fields")
        spec = SyncSpec(
            inventory=sync_calendar.InventoryRequest(**data["inventory"]),
            **{k: v for k, v in data.items() if k != "inventory"},
        )
        spec.validate()
        if version == "fit_sync_request_v2" and spec.total_timeout_seconds is None:
            raise ValueError("budget")
        return spec
    except (KeyError, TypeError, ValueError):
        raise ValueError("fit_sync_request_invalid") from None


class CollectionBudget:
    """Absolute durable deadline plus monotonic remaining time within a run."""

    def __init__(self, saved: dict[str, Any], wall: float, monotonic: float):
        self.deadline = saved["deadline_epoch"]
        self.started = saved["started_epoch"]
        self.monotonic_end = monotonic + max(0, self.deadline - wall)

    def remaining(self) -> float:
        now = time.time()
        remaining = min(self.deadline - now, self.monotonic_end - time.monotonic())
        if now < self.started or remaining <= 0:
            raise ValueError("fit_sync_total_budget_exhausted")
        return remaining


def document(db: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT content_json,content_sha256 FROM documents WHERE kind='sync_receipt' AND logical_key=?",
        (key,),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("fit_sync_document_conflict")
    if not rows:
        return None
    if storage.digest(rows[0][0].encode()) != rows[0][1]:
        raise ValueError("fit_sync_document_invalid")
    return json.loads(rows[0][0])


def put(db: sqlite3.Connection, key: str, value: dict[str, Any]) -> None:
    old = document(db, key)
    if old is not None and old != value:
        raise ValueError("fit_sync_document_conflict")
    sha = storage.digest(storage.canonical(value).encode())
    storage.put_document(db, "sync_receipt", key, sha, value)
    sync_calendar.durable(db)


def private_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
    storage.private_entry(path, directory=True)
    # A prior mkdir can be visible despite a failed parent durability barrier.
    storage.sync_dir(path.parent)


def file_manifest(root: Path) -> dict[str, Any]:
    result = {}
    storage.private_entry(root, directory=True)
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            storage.private_entry(path, directory=True)
        else:
            storage.private_entry(path, nonempty=True)
            if path.name.startswith(".pending-"):
                raise ValueError("fit_sync_artifact_incomplete")
            result[path.relative_to(root).as_posix()] = storage.digest(
                path.read_bytes()
            )
    return result


class Journal:
    def __init__(
        self,
        db: sqlite3.Connection,
        root: Path,
        spec: SyncSpec,
        shared: Bound | None = None,
    ):
        self.db, self.root, self.spec = db, root, spec
        self.shared = shared
        self.key = "fit-sync:" + storage.digest(spec.inventory.key.encode())
        self.work = root / "sync" / self.key.removeprefix("fit-sync:")
        self.intents: list[dict[str, Any]] = []
        n = 1
        while (value := document(db, f"{self.key}:intent:{n}")) is not None:
            self.intents.append(value)
            n += 1

    def counts(self) -> dict[str, int]:
        value = {
            kind: sum(i["call_kind"] == kind for i in self.intents)
            for kind in ("initialize", "inventory", "download")
        }
        return {**value, "total": len(self.intents)}

    def reserve(self, kind: str, arguments: dict[str, Any]) -> dict[str, Any]:
        maximum = {
            "initialize": self.spec.max_session_starts,
            "inventory": self.spec.inventory.max_calls,
            "download": self.spec.max_download_calls,
        }[kind]
        if self.counts()[kind] >= maximum:
            raise ValueError("fit_sync_budget_exhausted")
        n = len(self.intents) + 1
        value = {
            "schema_version": "fit_transport_intent_v1",
            "job_key": self.spec.inventory.key,
            "ordinal": n,
            "call_kind": kind,
            "tool": {
                "initialize": None,
                "inventory": "get_activities_by_date",
                "download": "download_activity_file",
            }[kind],
            "arguments": arguments,
        }
        if self.shared:
            self.shared.reserve(value)
        put(self.db, f"{self.key}:intent:{n}", value)
        self.intents.append(value)
        return value

    def outcome_key(self, intent: dict[str, Any]) -> str:
        return f"{self.key}:outcome:{intent['ordinal']}"

    def directory(self, intent: dict[str, Any]) -> Path:
        return self.work / str(intent["ordinal"])

    def capture(
        self,
        intent: dict[str, Any],
        payload: bytes | None,
        value: dict[str, Any] | None,
        error: str | None,
    ) -> dict[str, Any]:
        directory = self.directory(intent)
        private_directory(directory)
        sha = storage.digest(payload) if payload is not None else None
        outcome = {
            "schema_version": "fit_transport_result_v1",
            "intent_sha256": storage.digest(storage.canonical(intent).encode()),
            "capture_sha256": sha,
            "status": "error" if error else "success",
            "error_code": error,
            "value": value,
        }
        # Preserve the adapter's success/error verdict before saving text. Text
        # alone loses MCP isError and must never be reinterpreted as success.
        storage.atomic_file(
            directory / "result.json", storage.canonical(outcome).encode()
        )
        if payload is not None:
            storage.atomic_file(directory / "response.mcp", payload)
        put(self.db, self.outcome_key(intent), outcome)
        return outcome

    def recovered(self, intent: dict[str, Any]) -> dict[str, Any] | None:
        if intent["call_kind"] == "initialize":
            return document(self.db, self.outcome_key(intent))
        directory = self.directory(intent)
        path = directory / "result.json"
        raw = directory / "response.mcp"
        saved = document(self.db, self.outcome_key(intent))
        if not path.exists():
            if saved is not None:
                raise ValueError("fit_sync_capture_missing")
            if not raw.exists():
                return None
            raise ValueError("fit_sync_capture_incomplete")
        storage.private_entry(path, nonempty=True)
        outcome = garmin_fit.strict_object(path.read_bytes())
        if outcome.get("intent_sha256") != storage.digest(
            storage.canonical(intent).encode()
        ):
            raise ValueError("fit_sync_capture_conflict")
        sha = outcome.get("capture_sha256")
        if sha is not None:
            storage.private_entry(raw, nonempty=True)
            if storage.digest(raw.read_bytes()) != sha:
                raise ValueError("fit_sync_capture_conflict")
            storage.atomic_file(raw, raw.read_bytes())
        elif raw.exists():
            raise ValueError("fit_sync_capture_conflict")
        if saved is not None and saved != outcome:
            raise ValueError("fit_sync_capture_conflict")
        storage.atomic_file(path, path.read_bytes())
        if saved is None:
            put(self.db, self.outcome_key(intent), outcome)
        return outcome

    def artifacts(self) -> dict[str, Any]:
        files = file_manifest(self.work)
        permitted = set()
        directories = set()
        for intent in self.intents:
            if intent["call_kind"] == "initialize":
                continue
            n = str(intent["ordinal"])
            directories.add(n)
            permitted.update({f"{n}/result.json", f"{n}/response.mcp"})
            if intent["call_kind"] == "download":
                directories.add(f"{n}/download")
                permitted.add(f"{n}/download/{intent['arguments']['activity_ref']}.fit")
            self.recovered(intent)
        actual_dirs = {
            p.relative_to(self.work).as_posix()
            for p in self.work.rglob("*")
            if p.is_dir()
        }
        if not set(files) <= permitted or not actual_dirs <= directories:
            raise ValueError("fit_sync_artifact_undeclared")
        return files

    def cached(self, kind: str, args: dict[str, Any]) -> dict[str, Any] | None:
        successes = []
        for intent in self.intents:
            if intent["call_kind"] == kind and intent["arguments"] == args:
                result = self.recovered(intent)
                if result and result["status"] == "success":
                    if self.shared:
                        self.shared.settle(intent, result["value"])
                    successes.append({"intent": intent, "value": result["value"]})
        if len(successes) > 1:
            raise ValueError("fit_sync_capture_conflict")
        return successes[0] if successes else None

    def restore_inventory(self) -> None:
        restored = {
            row[0]
            for row in self.db.execute(
                "SELECT c.page FROM sync_calls c JOIN sync_results r USING(job_key,ordinal) WHERE c.job_key=? AND r.status='page'",
                (self.spec.inventory.key,),
            )
        }
        rows = self.db.execute(
            "SELECT c.ordinal,c.request_json,c.page FROM sync_calls c LEFT JOIN sync_results r USING(job_key,ordinal) WHERE c.job_key=? AND r.ordinal IS NULL ORDER BY c.ordinal DESC",
            (self.spec.inventory.key,),
        ).fetchall()
        for row in rows:
            # One page has one accepted result. Earlier unresolved reservations
            # remain historical uncertainty, not additional successful pages.
            if row[2] in restored:
                continue
            cached = self.cached("inventory", json.loads(row[1]))
            if cached:
                value = storage.canonical(cached["value"])
                self.db.execute(
                    "INSERT INTO sync_results VALUES(?,?,'page',?,?)",
                    (
                        self.spec.inventory.key,
                        row[0],
                        value,
                        storage.digest(value.encode()),
                    ),
                )
                sync_calendar.durable(self.db)
                restored.add(row[2])

    def adopt(self, cached: dict[str, Any]) -> dict[str, Any]:
        value = cached["value"]
        if value["status"] == "available":
            source = (
                self.directory(cached["intent"]) / "download" / value["relative_path"]
            )
            relative = storage.import_fit(
                self.db, self.root, value["activity_ref"], source, value["sha256"]
            )
            sync_calendar.durable(self.db)
            return {**value, "relative_path": relative}
        return value


def unfinished_jobs(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Query-complete days can still have unfinished downloads or session audit."""
    result = []
    for row in db.execute(
        "SELECT logical_key,content_json FROM documents WHERE kind='sync_receipt'"
    ):
        value = json.loads(row[1])
        if value.get("schema_version") in (
            "fit_sync_request_v1",
            "fit_sync_request_v2",
        ):
            key = row[0].removesuffix(":request")
            if document(db, key + ":complete") is None:
                result.append(
                    {
                        "request": value["request"],
                        "blocked": document(db, key + ":blocked") is not None
                        or value["schema_version"] == "fit_sync_request_v1",
                    }
                )
    return result


async def synchronize(
    root: Path,
    spec: SyncSpec,
    *,
    token_root: Path,
    session_factory: garmin_fit.SessionFactory = garmin_fit.sdk_session,
    shared_budget: Callable[[sqlite3.Connection, SyncSpec], Bound] | None = None,
) -> dict[str, Any]:
    wall, monotonic = time.time(), time.monotonic()
    spec.validate()
    with storage.open_store(root) as db:
        journal = Journal(db, root, spec)
        request = {"schema_version": "fit_sync_request_v2", "request": asdict(spec)}
        old = document(db, journal.key + ":request")
        if old is not None and read_request(old) != spec:
            raise ValueError("fit_sync_request_conflict")
        done = document(db, journal.key + ":complete")
        if done is not None:
            storage.verify_fit_closure(db, root)
            if journal.artifacts() != done["files"]:
                raise ValueError("fit_sync_capture_conflict")
            return done
        if spec.total_timeout_seconds is None or (
            old is not None and old["schema_version"] == "fit_sync_request_v1"
        ):
            raise ValueError("fit_sync_total_budget_required")
        if document(db, journal.key + ":blocked") is not None:
            raise ValueError("fit_sync_audit_blocked")
        shared = shared_budget(db, spec) if shared_budget else None
        journal.shared = shared
        saved_budget = document(db, journal.key + ":budget")
        if old is not None and saved_budget is None:
            raise ValueError("fit_sync_total_budget_missing")
        if saved_budget is None:
            saved_budget = {
                "schema_version": "fit_sync_budget_v1",
                "request_sha256": storage.digest(storage.canonical(request).encode()),
                "started_epoch": wall,
                "deadline_epoch": wall + spec.total_timeout_seconds,
            }
            put(db, journal.key + ":budget", saved_budget)
        if saved_budget.get("request_sha256") != storage.digest(
            storage.canonical(request).encode()
        ):
            raise ValueError("fit_sync_request_conflict")
        budget = CollectionBudget(saved_budget, wall, monotonic)

        def remaining() -> float:
            return (
                min(budget.remaining(), shared.remaining())
                if shared
                else budget.remaining()
            )

        put(db, journal.key + ":request", request)
        private_directory(root / "sync")
        private_directory(journal.work)
        journal.restore_inventory()
        stack = AsyncExitStack()
        client: garmin_fit.FitClient | None = None
        session_intent: dict[str, Any] | None = None

        async def connected() -> garmin_fit.FitClient:
            nonlocal client, session_intent
            if client is None:
                remaining()
                session_intent = journal.reserve("initialize", {})
                try:
                    client = await stack.enter_async_context(
                        garmin_fit.open_session(
                            token_root,
                            journal.work,
                            is_cn=spec.is_cn,
                            timeout=spec.timeout_seconds,
                            remaining=remaining,
                            factory=session_factory,
                        )
                    )
                except Exception:
                    put(
                        db,
                        journal.outcome_key(session_intent),
                        {"status": "error", "error_code": "garmin_session_unavailable"},
                    )
                    raise ValueError("fit_sync_session_unavailable") from None
            return client

        async def call(kind: str, args: dict[str, Any]) -> dict[str, Any]:
            cached = journal.cached(kind, args)
            if cached is not None:
                return cached
            # Exhausted tool budget must not spend another initialization.
            maximum = (
                spec.inventory.max_calls
                if kind == "inventory"
                else spec.max_download_calls
            )
            if journal.counts()[kind] >= maximum:
                raise ValueError("fit_sync_budget_exhausted")
            if shared:
                shared.check(kind, args, include_session=client is None)
            remaining()
            active = await connected()
            remaining()
            intent = journal.reserve(kind, args)
            directory = journal.directory(intent)
            private_directory(directory)
            try:
                if kind == "inventory":
                    captured = await active.inventory(
                        args["start_date"],
                        args["end_date"],
                        args["page"],
                        args["page_size"],
                    )
                else:
                    private_directory(directory / "download")
                    captured = await active.download(
                        args["activity_ref"], directory / "download"
                    )
            except garmin_fit.CallFailure as exc:
                journal.capture(intent, exc.payload, None, str(exc))
                raise
            journal.capture(intent, captured.payload, captured.value, None)
            if shared:
                shared.settle(intent, captured.value)
            return {"intent": intent, "value": captured.value}

        members = []
        try:
            steps = sync_calendar.inventory_steps(db, spec.inventory)
            try:
                args = next(steps)
                while True:
                    try:
                        captured = await call("inventory", args)
                    except garmin_fit.CallFailure as exc:
                        args = steps.throw(exc)
                    else:
                        args = steps.send(captured["value"])
            except StopIteration as completed:
                inventory = completed.value
            finally:
                steps.close()
            sync_calendar.durable(db)
            for item in inventory["items"]:
                ref = item["activity_ref"]
                garmin_fit.activity_ref(ref)
                existing = db.execute(
                    "SELECT f.sha256,f.relative_path,f.byte_size FROM fits f JOIN activity_fits a ON f.sha256=a.fit_sha256 WHERE a.activity_ref=?",
                    (ref,),
                ).fetchall()
                if len(existing) > 1:
                    raise ValueError("fit_sync_activity_revision_conflict")
                if existing:
                    row = existing[0]
                    path = root / row[1]
                    storage.private_entry(path, nonempty=True)
                    if (
                        storage.digest(path.read_bytes()) != row[0]
                        or path.stat().st_size != row[2]
                    ):
                        raise ValueError("fit_sha_mismatch")
                    member = {
                        "status": "available",
                        "activity_ref": ref,
                        "relative_path": row[1],
                        "sha256": row[0],
                        "byte_size": row[2],
                    }
                else:
                    member = journal.adopt(
                        await call("download", {"activity_ref": ref})
                    )
                members.append({**item, **member})
            # A prior process may have stopped after its calls but before its
            # session audit. A fresh bounded read-only session closes that gap.
            if client is None and any(
                i["call_kind"] == "initialize"
                and document(db, journal.outcome_key(i)) is None
                for i in journal.intents
            ):
                await connected()
        finally:
            try:
                await stack.aclose()
            except Exception:
                put(
                    db,
                    journal.key + ":blocked",
                    {
                        "schema_version": "fit_sync_blocked_v1",
                        "error_code": "session_audit_failed",
                    },
                )
                raise ValueError("fit_sync_session_audit_failed") from None
            if session_intent is not None and client is not None:
                put(
                    db,
                    journal.outcome_key(session_intent),
                    {"status": "closed", "token_unchanged": True},
                )
        if shared:
            shared.remaining()
        storage.verify_fit_closure(db, root)
        result = {
            "schema_version": "fit_sync_receipt_v1",
            "status": "complete",
            "job_key": spec.inventory.key,
            "activity_count": len(members),
            "fit_count": sum(i["status"] == "available" for i in members),
            "no_fit_count": sum(i["status"] == "no_fit" for i in members),
            "members": members,
            "files": journal.artifacts(),
            "provider_calls": journal.counts(),
            "external_actions": 0,
        }
        put(db, journal.key + ":complete", result)
        return result
