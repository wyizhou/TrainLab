"""Reusable deterministic provider fake and fault injection for Layer 2 tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.garmin import GarminError


@dataclass
class DeterministicClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


@dataclass
class FakeGarminTransport:
    fit: bytes
    health: dict[str, Any] = field(default_factory=dict)
    faults: dict[str, GarminError | list[GarminError]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def login(self) -> None:
        self._fault("login")

    def _fault(self, key: str) -> None:
        self.calls.append(key)
        if key in self.faults:
            fault = self.faults[key]
            if isinstance(fault, list):
                if fault:
                    raise fault.pop(0)
            else:
                raise fault

    def identity(self) -> str:
        self._fault("identity")
        return "fake-account"

    def fetch_health(self, resource_kind: str, local_date: str) -> Any:
        self._fault(f"health:{resource_kind}")
        return self.health.get(
            resource_kind,
            []
            if resource_kind != "user_summary"
            else {"steps": 1, "calendarDate": local_date},
        )

    def list_activities(self, start: str | None, through: str | None):
        self._fault("activities")
        return [{"activityId": 7}]

    def activity_summary(self, activity_id: str):
        self._fault("summary")
        return {
            "activityId": int(activity_id),
            "activityName": "synthetic",
            "activityType": {"typeKey": "running"},
            "startTimeGMT": "2026-04-15T00:00:00Z",
        }

    def activity_original(self, activity_id: str):
        self._fault("original")
        return self.fit

    def activity_extra(self, activity_id: str, role: str):
        self._fault(f"extra:{role}")
        return None
