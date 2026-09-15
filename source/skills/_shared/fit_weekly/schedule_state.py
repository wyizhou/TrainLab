from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import run_config, storage, sync_calendar


def slot_time(slot: str) -> str:
    if not isinstance(slot, str):
        raise ValueError("schedule_slot_invalid")
    if slot.startswith("daily:"):
        day = sync_calendar.day_value(slot[6:])
        return day.isoformat() + "T14:00:00Z"
    if slot.startswith("weekly:"):
        end = slot[7:]
        if sync_calendar.weekly_slot(end)["end_utc"] == end:
            return end
    raise ValueError("schedule_slot_invalid")


def empty() -> dict[str, Any]:
    return {
        "first_day": None,
        "last_seen_utc": None,
        "claims": {},
        "attempts": {},
        "outcomes": {},
        "blocked": {},
        "sequence": 0,
        "sha256": None,
    }


def apply(state: dict[str, Any], event: dict[str, Any]) -> None:
    kind, now = event["kind"], event["now"]
    sync_calendar.utc_time(now)
    if kind == "takeover":
        if state["first_day"] is not None:
            raise ValueError("schedule_takeover_conflict")
        sync_calendar.day_value(event["first_day"])
        state["first_day"] = event["first_day"]
    elif state["first_day"] is None:
        raise ValueError("schedule_takeover_missing")
    elif kind == "observed":
        if state["last_seen_utc"] and now < state["last_seen_utc"]:
            raise ValueError("schedule_clock_rollback")
        state["last_seen_utc"] = now
    elif kind in ("claim", "attempt", "result", "blocked"):
        slot = event["slot"]
        if slot_time(slot) > now:
            raise ValueError("schedule_before_due")
        if kind == "claim":
            value = event["value"]
            if (
                slot in state["claims"]
                or set(value)
                != {
                    "slot",
                    "due_utc",
                    "late",
                    "dates",
                    "unfinished_jobs",
                    "authorization_file",
                    "authorization_key",
                    "authorization_sha256",
                    "business_key",
                }
                or value["slot"] != slot
                or value["due_utc"] != slot_time(slot)
            ):
                raise ValueError("schedule_claim_conflict")
            storage.require_sha(value["authorization_sha256"])
            if type(value["late"]) is not bool or not isinstance(value["dates"], list):
                raise ValueError("schedule_claim_invalid")
            for day in value["dates"]:
                sync_calendar.day_value(day)
            if value["dates"] != sorted(set(value["dates"])):
                raise ValueError("schedule_claim_invalid")
            run_config.relative_path(Path("/instance"), value["authorization_file"])
            state["claims"][slot] = value
        elif kind == "attempt":
            if slot not in state["claims"] or slot in state["outcomes"]:
                raise ValueError("schedule_attempt_invalid")
            if event["number"] != state["attempts"].get(slot, 0) + 1:
                raise ValueError("schedule_attempt_invalid")
            state["attempts"][slot] = event["number"]
        elif kind == "result":
            if slot not in state["attempts"] or slot in state["outcomes"]:
                raise ValueError("schedule_result_invalid")
            if event["value"]["status"] not in (
                "complete",
                "failed",
                "unknown",
                "blocked",
                "pending",
            ):
                raise ValueError("schedule_result_invalid")
            state["outcomes"][slot] = event["value"]
        else:
            if event["value"]["status"] != "blocked":
                raise ValueError("schedule_result_invalid")
            state["blocked"][slot] = event["value"]
    else:
        raise ValueError("schedule_event_invalid")
    if kind in ("claim", "attempt", "result", "blocked"):
        state["last_seen_utc"] = max(state["last_seen_utc"] or now, now)


def read(root: Path) -> dict[str, Any]:
    state = empty()
    folder = root / "runtime/schedule"
    if not folder.exists() and not folder.is_symlink():
        return state
    storage.private_entry(root / "runtime", directory=True)
    storage.private_entry(folder, directory=True)
    for path in sorted(folder.iterdir()):
        storage.private_entry(path)
        if path.name.startswith(".pending-"):
            continue
        if not re.fullmatch(r"[0-9]{12}\.json", path.name):
            raise ValueError("schedule_record_invalid")
        envelope = run_config.read_object(root, path, limit=4 * 1024 * 1024)
        if set(envelope) != {
            "schema_version",
            "sequence",
            "previous_sha256",
            "event",
            "sha256",
        }:
            raise ValueError("schedule_record_invalid")
        digest = envelope.pop("sha256")
        if (
            envelope["schema_version"] != "fit_schedule_event_v1"
            or envelope["sequence"] != state["sequence"] + 1
            or path.name != f"{envelope['sequence']:012d}.json"
            or envelope["previous_sha256"] != state["sha256"]
            or digest != storage.digest(storage.canonical(envelope).encode())
        ):
            raise ValueError("schedule_record_invalid")
        apply(state, envelope["event"])
        state.update(sequence=envelope["sequence"], sha256=digest)
    return state


def append(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    with storage.open_store(root):
        state = read(root)
        apply(state, event)
        for folder in (root / "runtime", root / "runtime/schedule"):
            if not folder.exists() and not folder.is_symlink():
                folder.mkdir(mode=0o700)
            storage.private_entry(folder, directory=True)
            storage.sync_dir(folder.parent)
        value = {
            "schema_version": "fit_schedule_event_v1",
            "sequence": state["sequence"] + 1,
            "previous_sha256": state["sha256"],
            "event": event,
        }
        digest = storage.digest(storage.canonical(value).encode())
        storage.atomic_file(
            root / "runtime/schedule" / f"{value['sequence']:012d}.json",
            storage.canonical({**value, "sha256": digest}).encode(),
        )
        state.update(sequence=value["sequence"], sha256=digest)
        return state


def start(root: Path, first_day: str, now: str) -> dict[str, Any]:
    sync_calendar.day_value(first_day)
    if (
        first_day
        > sync_calendar.utc_time(now)
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    ):
        raise ValueError("schedule_takeover_future")
    state = read(root)
    if state["first_day"] is None:
        append(root, {"kind": "takeover", "now": now, "first_day": first_day})
    elif state["first_day"] != first_day:
        raise ValueError("schedule_takeover_conflict")
    state = observe(root, now)
    return state


def observe(root: Path, now: str) -> dict[str, Any]:
    state = read(root)
    if state["last_seen_utc"] and now < state["last_seen_utc"]:
        raise ValueError("schedule_clock_rollback")
    with storage.open_store(root) as db:
        sync_calendar.record_gaps(db, state["first_day"], now)
    if state["last_seen_utc"] != now:
        state = append(root, {"kind": "observed", "now": now})
    return state


def blocked(root: Path, slot: str, now: str, code: str) -> None:
    value = {"status": "blocked", "error_code": code}
    if read(root)["blocked"].get(slot) != value:
        append(root, {"kind": "blocked", "slot": slot, "now": now, "value": value})


def status(root: Path) -> dict[str, Any]:
    state = read(root)
    return {
        "state": "ready" if state["first_day"] else "unconfigured",
        "first_day": state["first_day"],
        "last_seen_utc": state["last_seen_utc"],
        "slots": {
            slot: {
                "status": state["outcomes"].get(slot, {}).get("status", "unsettled"),
                "attempts": state["attempts"].get(slot, 0),
                "late": claim["late"],
            }
            for slot, claim in state["claims"].items()
        },
        "blocked": state["blocked"],
    }
