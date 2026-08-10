"""Synthetic Garmin workflow receipt tests; no provider or stored raw data."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from trainlab.garmin import SyncRequest
from trainlab.orchestration.fakes import FakeGarmin

ROOT = Path(__file__).resolve().parents[1]
COUNTS = {
    "fetched": 0,
    "empty": 0,
    "unchanged": 1,
    "revised": 0,
    "failed": 0,
    "deferred": 0,
    "not_available": 0,
    "not_enabled": 0,
}


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / "harness/schemas" / name).read_text(encoding="utf-8"))
    )


def _request(mode: str) -> dict[str, object]:
    values: dict[str, Any] = {
        "mode": mode,
        "invocation_id": f"integration-{mode}-001",
    }
    if mode == "incremental":
        values["through_local_date"] = "2026-08-03"
    elif mode == "snapshot":
        values["snapshot_local_date"] = "2026-08-03"
    elif mode == "audit":
        values["health_from_local_date"] = "2026-08-01"
        values["through_local_date"] = "2026-08-03"
    elif mode == "repair":
        values["health_from_local_date"] = "2026-08-03"
        values["repair_strategy"] = "reconcile"
    request = asdict(SyncRequest(**values))
    request["resource_kinds"] = list(request["resource_kinds"])
    request["activity_ids"] = list(request["activity_ids"])
    return request


def _receipt(mode: str) -> dict[str, object]:
    start = (
        "2026-08-03" if mode in {"incremental", "snapshot", "repair"} else "2026-08-01"
    )
    return {
        "schema_version": "1",
        "run_id": f"synthetic-{mode}-receipt",
        "mode": mode,
        "status": "succeeded",
        "requested_range": {"from": None, "through": "2026-08-03"},
        "effective_range": {"from": start, "through": "2026-08-03"},
        "coverage_state": "complete",
        "counts": COUNTS,
        "complete_through_by_resource": {"synthetic": "2026-08-03"},
        "open_gap_count": 0,
        "next_retry_at_utc": None,
        "errors": [],
        "started_at_utc": "2026-08-03T00:00:00Z",
        "completed_at_utc": "2026-08-03T00:00:01Z",
    }


@pytest.mark.parametrize("mode", ("incremental", "snapshot", "audit", "repair"))
def test_garmin_flow_runs_twice_with_schema_valid_unchanged_effect(
    mode: str,
) -> None:
    request = _request(mode)
    receipt = _receipt(mode)
    assert not list(_validator("garmin_sync_request.schema.json").iter_errors(request))
    assert not list(_validator("garmin_sync_receipt.schema.json").iter_errors(receipt))

    fake = FakeGarmin({mode: receipt})
    first, second = fake.execute(request), fake.execute(request)

    assert first == second == receipt
    assert len(fake.invocations) == 2
    # The fake only replays the same durable receipt; it has no provider effect.
    assert {item["invocation_id"] for item in fake.invocations} == {
        request["invocation_id"]
    }
