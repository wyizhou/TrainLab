from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import run_config, storage, sync_calendar

COMMANDS = {"import-history", "sync", "weekly", "daemon", "reconcile", "edit"}


def directory(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    storage.private_entry(path, directory=True)
    storage.sync_dir(path.parent)


def records(root: Path) -> list[dict[str, Any]]:
    runtime = root / "runtime"
    if not runtime.exists() and not runtime.is_symlink():
        return []
    storage.private_entry(runtime, directory=True)
    runs = runtime / "runs"
    if not runs.exists() and not runs.is_symlink():
        return []
    storage.private_entry(runs, directory=True)
    result = []
    for path in sorted(runs.iterdir()):
        if not re.fullmatch(r"[0-9]{12}", path.name):
            raise ValueError("run_state_invalid")
        storage.private_entry(path, directory=True)
        start_path = path / "start.json"
        if not start_path.exists() and not start_path.is_symlink():
            for pending in path.iterdir():
                if not pending.name.startswith(".pending-"):
                    raise ValueError("run_state_invalid")
                storage.private_entry(pending)
            result.append({"sequence": int(path.name), "start": None, "stop": None})
            continue
        start = run_config.read_object(root, path / "start.json")
        if (
            set(start)
            != {"schema_version", "sequence", "pid", "command", "started_utc"}
            or start["schema_version"] != "fit_run_start_v1"
            or type(start["sequence"]) is not int
            or start["sequence"] != int(path.name)
            or start["command"] not in COMMANDS
            or type(start["pid"]) is not int
            or start["pid"] <= 0
        ):
            raise ValueError("run_state_invalid")
        sync_calendar.utc_time(start["started_utc"])
        stop_path = path / "stop.json"
        stop = None
        if stop_path.exists() or stop_path.is_symlink():
            stop = run_config.read_object(root, stop_path)
            if (
                set(stop)
                != {
                    "schema_version",
                    "sequence",
                    "start_sha256",
                    "outcome",
                    "signal",
                    "ended_utc",
                }
                or stop["schema_version"] != "fit_run_stop_v1"
                or type(stop["sequence"]) is not int
                or stop["sequence"] != start["sequence"]
                or stop["start_sha256"]
                != storage.digest(storage.canonical(start).encode())
                or stop["outcome"] not in ("completed", "failed", "stopped")
                or (
                    stop["signal"] not in (2, 15)
                    if stop["outcome"] == "stopped"
                    else stop["signal"] is not None
                )
            ):
                raise ValueError("run_state_invalid")
            sync_calendar.utc_time(stop["ended_utc"])
        result.append({"sequence": int(path.name), "start": start, "stop": stop})
    if [r["sequence"] for r in result] != list(range(1, len(result) + 1)):
        raise ValueError("run_state_invalid")
    return result


def begin(root: Path, command: str, now: str) -> dict[str, Any]:
    if command not in COMMANDS:
        raise ValueError("run_command_invalid")
    sync_calendar.utc_time(now)
    previous = records(root)
    sequence = len(previous) + 1
    runtime = root / "runtime"
    directory(runtime)
    directory(runtime / "runs")
    folder = runtime / "runs" / f"{sequence:012d}"
    directory(folder)
    start = {
        "schema_version": "fit_run_start_v1",
        "sequence": sequence,
        "pid": os.getpid(),
        "command": command,
        "started_utc": now,
    }
    storage.atomic_file(folder / "start.json", storage.canonical(start).encode())
    return start


def finish(
    root: Path, start: dict[str, Any], outcome: str, now: str, signum: int | None = None
) -> None:
    if outcome not in ("completed", "failed", "stopped"):
        raise ValueError("run_outcome_invalid")
    sync_calendar.utc_time(now)
    value = {
        "schema_version": "fit_run_stop_v1",
        "sequence": start["sequence"],
        "start_sha256": storage.digest(storage.canonical(start).encode()),
        "outcome": outcome,
        "signal": signum,
        "ended_utc": now,
    }
    storage.atomic_file(
        root / "runtime/runs" / f"{start['sequence']:012d}" / "stop.json",
        storage.canonical(value).encode(),
    )


def lock_held(root: Path) -> bool:
    path = root / "lifecycle.lock"
    if not path.exists() and not path.is_symlink():
        if (root / "runtime/runs").exists():
            raise ValueError("run_lock_missing")
        return False
    storage.private_entry(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


def business(db: sqlite3.Connection) -> dict[str, int]:
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, key, text, sha in db.execute(
        "SELECT kind,logical_key,content_json,content_sha256 FROM documents"
    ):
        value = json.loads(text)
        if (
            not isinstance(value, dict)
            or storage.canonical(value) != text
            or storage.digest(text.encode()) != sha
            or (kind, key) in documents
        ):
            raise ValueError("status_document_invalid")
        documents[kind, key] = value
    counts = {"pending": 0, "unknown": 0, "failed": 0}
    for (kind, key), value in documents.items():
        version = value.get("schema_version")
        if (
            kind == "delivery_receipt"
            and version in ("fit_delivery_request_v1", "fit_delivery_request_v2")
            and key.endswith(":request")
        ):
            prefix = key.removesuffix(":request")
            if (kind, prefix + ":success") not in documents and (
                kind,
                prefix + ":skipped",
            ) not in documents:
                counts[
                    "unknown" if (kind, prefix + ":intent") in documents else "pending"
                ] += 1
        elif kind == "sync_receipt" and version in (
            "fit_sync_request_v1",
            "fit_sync_request_v2",
        ):
            prefix = key.removesuffix(":request")
            if (kind, prefix + ":complete") not in documents:
                unknown = (kind, prefix + ":blocked") in documents or any(
                    k.startswith(prefix + ":intent:")
                    and (kind, k.replace(":intent:", ":outcome:")) not in documents
                    for kind_key, k in documents
                    if kind_key == kind
                )
                counts["unknown" if unknown else "pending"] += 1
        elif kind == "sync_receipt" and version == "fit_sync_batch_request_v1":
            saved = documents.get((kind, key.removesuffix(":request") + ":sealed"))
            if saved is None:
                counts["pending"] += 1
            elif saved["status"] == "failed":
                counts["failed"] += 1
        elif (
            kind == "weekly_input"
            and key.startswith("model-job:")
            and key.endswith(":intent")
        ):
            saved = documents.get((kind, key.removesuffix(":intent") + ":result"))
            if saved is None:
                counts["unknown"] += 1
            elif saved.get("receipt", {}).get("status") == "failed":
                counts["failed"] += 1
    return counts


def database_status(root: Path) -> dict[str, Any]:
    connection = None
    try:
        for name in ("writer.lock", "trainlab-fit.db"):
            storage.private_entry(root / name, nonempty=name.endswith(".db"))
        storage.private_entry(root / "fits", directory=True)
        for suffix in ("-wal", "-shm"):
            if (root / ("trainlab-fit.db" + suffix)).exists():
                raise ValueError("status_wal_unsupported")
        journal = root / "trainlab-fit.db-journal"
        if journal.exists() or journal.is_symlink():
            storage.private_entry(journal)
        connection = sqlite3.connect(
            (root / "trainlab-fit.db").as_uri() + "?mode=ro", uri=True, timeout=0.05
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        storage.require_schema(connection)
        counts = business(connection)
        return {"database": "readable", "business": counts}
    except (OSError, ValueError, sqlite3.Error, TypeError):
        return {"database": "unreadable", "business": None}
    finally:
        if connection is not None:
            connection.close()


def status(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "instance": "unreadable",
        "lifecycle": "unreadable",
        "database": "unreadable",
        "business": None,
        "last_run": None,
    }
    try:
        root = run_config.instance_path(root)
        if not root.exists():
            return {
                **result,
                "instance": "uninitialized",
                "lifecycle": "not_running",
                "database": "uninitialized",
            }
        storage.private_entry(root, directory=True)
        if not any(
            (root / name).exists() or (root / name).is_symlink()
            for name in (
                "trainlab-fit.db",
                "writer.lock",
                "fits",
                "lifecycle.lock",
                "runtime",
            )
        ):
            return {
                **result,
                "instance": "uninitialized",
                "lifecycle": "not_running",
                "database": "uninitialized",
            }
        result["instance"] = "initialized"
        result.update(database_status(root))
        held = lock_held(root)
        saved = records(root)
        if held != lock_held(root):
            raise ValueError("status_transition")
        last = saved[-1] if saved else None
        if last:
            result["last_run"] = (
                {**last["start"], **(last["stop"] or {})}
                if last["start"] is not None
                else {"sequence": last["sequence"], "start_record": "missing"}
            )
        from skills._shared.fit_weekly import schedule_state

        try:
            result["schedule"] = schedule_state.status(root)
        except (OSError, ValueError, TypeError, KeyError):
            result["schedule"] = {"state": "unreadable"}
        result["lifecycle"] = (
            "running"
            if held
            else "interrupted"
            if last and last["stop"] is None
            else "not_running"
        )
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return result
