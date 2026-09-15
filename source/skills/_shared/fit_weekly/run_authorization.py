from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_sync,
    publication_ledger,
    run_config,
    storage,
    sync_calendar,
)

SYNC_TOOLS = {"garmin.session", "get_activities_by_date", "download_activity_file"}


def keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("shape")


def positive(value: Any, *, zero: bool = False) -> None:
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError("count")


def seconds(value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("seconds")


@dataclass(frozen=True)
class ModelGrant:
    period_end_utc: str
    stage: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class CommandGrant:
    period_end_utc: str
    stage: str
    command_sha256: str
    timeout_seconds: float


@dataclass(frozen=True)
class Grant:
    key: str
    starts_utc: str
    expires_utc: str
    _body: str = field(repr=False)

    def value(self) -> dict[str, Any]:
        import json

        return json.loads(self._body)

    def check_time(self, now: str) -> None:
        if (
            not sync_calendar.utc_time(self.starts_utc)
            <= sync_calendar.utc_time(now)
            < sync_calendar.utc_time(self.expires_utc)
        ):
            raise ValueError("run_authorization_invalid")

    def check_frozen(self, root: Path) -> None:
        root = run_config.instance_path(root)
        with storage.open_store(root):
            directory = root / "authorizations"
            if not directory.exists() and not directory.is_symlink():
                return
            storage.private_entry(directory, directory=True)
            path = directory / (storage.digest(self.key.encode()) + ".json")
            if path.exists() or path.is_symlink():
                storage.private_entry(path, nonempty=True)
                if path.read_bytes() != self._body.encode():
                    raise ValueError("store_file_conflict")

    def freeze(self, root: Path, *, now: str) -> str:
        self.check_time(now)
        root = run_config.instance_path(root)
        with storage.open_store(root):
            directory = root / "authorizations"
            if not directory.exists() and not directory.is_symlink():
                directory.mkdir(mode=0o700)
            storage.private_entry(directory, directory=True)
            storage.sync_dir(root)
            path = directory / (storage.digest(self.key.encode()) + ".json")
            storage.atomic_file(path, self._body.encode())
        return storage.digest(self._body.encode())

    def sync_spec(
        self, dates: list[str], *, is_cn: bool, now: str
    ) -> fit_sync.SyncSpec:
        self.check_time(now)
        value = self.value()["sync"]
        if (
            not value
            or not dates
            or dates != sorted(set(dates))
            or not set(dates) <= set(value["dates"])
        ):
            raise ValueError("run_authorization_invalid")
        if dates != sync_calendar.days_between(
            sync_calendar.day_value(dates[0]), sync_calendar.day_value(dates[-1])
        ):
            raise ValueError("run_authorization_invalid")
        identity = {
            "authorization": self.key,
            "dates": dates,
            "as_of_utc": value["as_of_utc"],
        }
        spec = fit_sync.SyncSpec(
            sync_calendar.InventoryRequest(
                "run-sync:" + storage.digest(storage.canonical(identity).encode()),
                dates[0],
                dates[-1],
                value["as_of_utc"],
                value["page_size"],
                value["max_pages"],
            ),
            value["max_download_calls"],
            value["max_session_starts"],
            value["timeout_seconds"],
            is_cn,
            value["total_timeout_seconds"],
        )
        spec.validate()
        return spec

    def model(self, end: str, stage: str, model: str, *, now: str) -> ModelGrant:
        self.check_time(now)
        matches = [
            v
            for v in self.value()["models"]
            if (v["period_end_utc"], v["stage"], v["model"]) == (end, stage, model)
        ]
        if len(matches) != 1:
            raise ValueError("run_authorization_invalid")
        return ModelGrant(**matches[0])

    def command(
        self, end: str, stage: str, command_sha256: str, *, now: str
    ) -> CommandGrant:
        self.check_time(now)
        value = self.value()
        if value["schema_version"] != "fit_run_authorization_v2":
            raise ValueError("run_authorization_invalid")
        matches = [
            v
            for v in value["models"]
            if (v["period_end_utc"], v["stage"], v["command_sha256"])
            == (end, stage, command_sha256)
        ]
        if len(matches) != 1:
            raise ValueError("run_authorization_invalid")
        return CommandGrant(**matches[0])

    def publication(self, *, now: str) -> publication_ledger.Authorization:
        self.check_time(now)
        value = self.value()["publication"]
        if value is None:
            raise ValueError("run_authorization_invalid")
        return publication_ledger.Authorization(
            self.key,
            tuple(value["action_keys"]),
            value["start_date"],
            value["end_date"],
            self.starts_utc,
            self.expires_utc,
            dict(value["max_calls"]),
        )


def parse(value: Any, *, now: str) -> Grant:
    try:
        keys(
            value,
            {
                "schema_version",
                "key",
                "starts_utc",
                "expires_utc",
                "sync",
                "models",
                "publication",
            },
        )
        if (
            value["schema_version"]
            not in ("fit_run_authorization_v1", "fit_run_authorization_v2")
            or not isinstance(value["key"], str)
            or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,120}", value["key"])
        ):
            raise ValueError("key")
        grant = Grant(
            value["key"],
            value["starts_utc"],
            value["expires_utc"],
            storage.canonical(value),
        )
        grant.check_time(now)
        if value["sync"] is not None:
            sync = value["sync"]
            expected_sync = {
                "dates",
                "as_of_utc",
                "tools",
                "page_size",
                "max_pages",
                "max_activities",
                "max_download_calls",
                "max_session_starts",
                "timeout_seconds",
                "total_timeout_seconds",
            }
            if isinstance(sync, dict) and "max_tool_calls" in sync:
                expected_sync.add("max_tool_calls")
                positive(sync["max_tool_calls"])
            keys(
                sync,
                expected_sync,
            )
            dates = sync["dates"]
            if not isinstance(dates, list) or not dates or dates != sorted(set(dates)):
                raise ValueError("dates")
            today = (
                sync_calendar.utc_time(sync["as_of_utc"])
                .astimezone(sync_calendar.HONG_KONG)
                .date()
            )
            if sync_calendar.utc_time(sync["as_of_utc"]) > sync_calendar.utc_time(
                now
            ) or any(sync_calendar.day_value(d) > today for d in dates):
                raise ValueError("dates")
            if (
                not isinstance(sync["tools"], list)
                or len(sync["tools"]) != len(SYNC_TOOLS)
                or set(sync["tools"]) != SYNC_TOOLS
            ):
                raise ValueError("tools")
            for name in ("page_size", "max_pages", "max_session_starts"):
                positive(sync[name])
            for name in ("max_activities", "max_download_calls"):
                positive(sync[name], zero=True)
            if (
                sync["page_size"] > 100
                or sync["max_activities"] > sync["page_size"] * sync["max_pages"]
            ):
                raise ValueError("activities")
            for name in ("timeout_seconds", "total_timeout_seconds"):
                seconds(sync[name])
            if sync["timeout_seconds"] > sync["total_timeout_seconds"]:
                raise ValueError("timeout")
        if not isinstance(value["models"], list):
            raise ValueError("models")
        seen = set()
        for model in value["models"]:
            identity_key = (
                "model"
                if value["schema_version"] == "fit_run_authorization_v1"
                else "command_sha256"
            )
            identity_pattern = (
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
                if identity_key == "model"
                else r"[0-9a-f]{64}"
            )
            keys(model, {"period_end_utc", "stage", identity_key, "timeout_seconds"})
            end = model["period_end_utc"]
            if (
                sync_calendar.weekly_slot(end)["end_utc"] != end
                or model["stage"] not in ("plan", "summary")
                or not isinstance(model[identity_key], str)
                or not re.fullmatch(identity_pattern, model[identity_key])
            ):
                raise ValueError("model")
            if (end, model["stage"]) in seen:
                raise ValueError("duplicate")
            seen.add((end, model["stage"]))
            seconds(model["timeout_seconds"])
            if sync_calendar.utc_time(end) >= sync_calendar.utc_time(grant.expires_utc):
                raise ValueError("week")
        if value["publication"] is not None:
            keys(
                value["publication"],
                {"action_keys", "start_date", "end_date", "max_calls"},
            )
            if not isinstance(
                value["publication"]["action_keys"], list
            ) or not isinstance(value["publication"]["max_calls"], dict):
                raise ValueError("publication")
            grant.publication(now=now).validate()
        if (
            value["sync"] is None
            and not value["models"]
            and value["publication"] is None
        ):
            raise ValueError("empty")
        return grant
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        raise ValueError("run_authorization_invalid") from None


def load(root: Path, filename: str, *, now: str) -> Grant:
    try:
        root = run_config.instance_path(root)
        return parse(
            run_config.read_object(root, run_config.relative_path(root, filename)),
            now=now,
        )
    except ValueError:
        raise ValueError("run_authorization_invalid") from None
