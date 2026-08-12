from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from trainlab.orchestration import (
    FoundationAdapter,
    FoundationAdapterError,
    FoundationBootstrapAlreadyCalled,
)


ROOT = Path(__file__).resolve().parents[1]


def receipt(status: str, *, mode: str = "init", ready: bool = True, schema_version: int | None = 3) -> dict:
    return {
        "schema_version": "1", "invocation_id": "invocation-001", "mode": mode, "status": status,
        "foundation_schema_version": schema_version, "ready": ready,
        "created_count": 0, "existing_count": 12, "verified_count": 12,
        "migration_start_version": None, "migration_end_version": None, "applied_migration_ids": [],
        "next_action": "none", "warnings": [], "errors": [],
        "started_at_utc": "2026-07-23T00:00:00Z", "completed_at_utc": "2026-07-23T00:00:01Z",
    }


class Recorder:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def __call__(self, request: dict) -> dict:
        self.requests.append(deepcopy(request))
        response = deepcopy(self.responses.pop(0))
        response["mode"] = request["mode"]
        response["invocation_id"] = request["invocation_id"]
        return response


def bootstrap(adapter: FoundationAdapter) -> object:
    return adapter.bootstrap(invocation_id="bootstrap-001", requested_at_utc="2026-07-23T00:00:00Z")


def test_bootstrap_accepts_only_compatible_already_initialized_once() -> None:
    recorder = Recorder([receipt("already_initialized")])
    result = bootstrap(FoundationAdapter(recorder))
    assert result.gate == "ready" and result.may_start_workflow
    assert result.incident_category is None and result.audit.status == "already_initialized"
    assert recorder.requests == [{"mode": "init", "invocation_id": "bootstrap-001", "requested_at_utc": "2026-07-23T00:00:00Z", "target_schema_version": None}]
    assert "migrate" not in {item["mode"] for item in recorder.requests}


@pytest.mark.parametrize(
    ("status", "ready", "schema_version", "gate", "incident", "maintenance"),
    [
        ("incompatible", False, 3, "attention_required", "foundation_incompatible", True),
        ("failed", False, None, "attention_required", "foundation_failed", False),
        ("lock_busy", False, None, "deferred", "foundation_lock_busy", False),
        ("ready", False, 3, "attention_required", "foundation_incompatible", True),
        ("ready", True, 1, "attention_required", "foundation_incompatible", True),
        ("initialized", True, 2, "attention_required", "foundation_incompatible", True),
        ("ready", True, 2, "attention_required", "foundation_incompatible", True),
    ],
)
def test_bootstrap_blocks_workflow_on_failure_or_incompatibility(status: str, ready: bool, schema_version: int | None, gate: str, incident: str, maintenance: bool) -> None:
    result = bootstrap(FoundationAdapter(Recorder([receipt(status, ready=ready, schema_version=schema_version)])))
    assert result.gate == gate and not result.may_start_workflow
    assert result.incident_category == incident and result.maintenance_required is maintenance


def test_bootstrap_never_calls_twice_or_offers_migrate() -> None:
    recorder = Recorder([receipt("already_initialized")])
    adapter = FoundationAdapter(recorder)
    bootstrap(adapter)
    with pytest.raises(FoundationBootstrapAlreadyCalled):
        bootstrap(adapter)
    assert [request["mode"] for request in recorder.requests] == ["init"]


def test_status_and_verify_are_read_only_after_bootstrap() -> None:
    recorder = Recorder([receipt("already_initialized"), receipt("ready", mode="status"), receipt("ready", mode="verify")])
    adapter = FoundationAdapter(recorder)
    bootstrap(adapter)
    status = adapter.status(invocation_id="status-001", requested_at_utc="2026-07-23T01:00:00Z")
    verify = adapter.verify(invocation_id="verify-001", requested_at_utc="2026-07-23T02:00:00Z")
    assert status.gate == verify.gate == "ready"
    assert [request["mode"] for request in recorder.requests] == ["init", "status", "verify"]
    assert all(request["target_schema_version"] is None for request in recorder.requests)
    assert all(set(request) == {"mode", "invocation_id", "requested_at_utc", "target_schema_version"} for request in recorder.requests)


def test_read_only_checks_require_bootstrap() -> None:
    adapter = FoundationAdapter(Recorder([]))
    with pytest.raises(FoundationAdapterError, match="foundation_bootstrap_required"):
        adapter.status(invocation_id="status-001", requested_at_utc="2026-07-23T01:00:00Z")


@pytest.mark.parametrize("mutation", ["missing", "receipt_schema", "mode", "invocation"])
def test_strict_receipt_validation_rejects_untrusted_or_mismatched_receipts(mutation: str) -> None:
    value = receipt("initialized")
    if mutation == "missing":
        value.pop("created_count")
    elif mutation == "receipt_schema":
        value["schema_version"] = "unknown"
    elif mutation == "mode":
        class WrongMode(Recorder):
            def __call__(self, request: dict) -> dict:
                result = super().__call__(request); result["mode"] = "verify"; return result
        with pytest.raises(FoundationAdapterError, match="foundation_receipt_mode_mismatch"):
            bootstrap(FoundationAdapter(WrongMode([value])))
        return
    else:
        class WrongInvocation(Recorder):
            def __call__(self, request: dict) -> dict:
                result = super().__call__(request); result["invocation_id"] = "other"; return result
        with pytest.raises(FoundationAdapterError, match="foundation_receipt_invocation_mismatch"):
            bootstrap(FoundationAdapter(WrongInvocation([value])))
        return
    pattern = "invalid_foundation_receipt" if mutation == "missing" else "unsupported_foundation_receipt_schema"
    with pytest.raises(FoundationAdapterError, match=pattern):
        bootstrap(FoundationAdapter(Recorder([value])))
