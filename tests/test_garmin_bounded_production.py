from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    GarminRepository,
    ProductionBudgetGuard,
    ProductionBudgetSpec,
    SyncReceipt,
    SyncRequest,
)
from trainlab.garmin.cli import _validate_garmin_cli_args, add_root_subparser
from trainlab.garmin_client import GarminConnectTransport, TokenStore


def _spec(**overrides: int | bool) -> ProductionBudgetSpec:
    values: dict[str, int | bool] = {
        "max_provider_entries": 2,
        "max_wall_seconds": 10,
        "max_activities": 1,
        "max_fit_downloads": 1,
        "max_new_raw_objects": 1,
        "cached_tokens_only": True,
    }
    values.update(overrides)
    return ProductionBudgetSpec(
        max_provider_entries=int(values["max_provider_entries"]),
        max_wall_seconds=int(values["max_wall_seconds"]),
        max_activities=int(values["max_activities"]),
        max_fit_downloads=int(values["max_fit_downloads"]),
        max_new_raw_objects=int(values["max_new_raw_objects"]),
        cached_tokens_only=bool(values["cached_tokens_only"]),
    )


def _bounded_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_root_subparser(parser.add_subparsers(dest="root", required=True))
    return parser.parse_args(
        [
            "garmin",
            "sync",
            "full",
            "--health-from",
            "2026-08-03",
            "--through",
            "2026-08-09",
            "--resource",
            "sleep",
            "--bounded-production",
            "--cached-tokens-only",
            "--max-provider-entries",
            "150",
            "--max-wall-seconds",
            "900",
            "--max-activities",
            "20",
            "--max-fit-downloads",
            "20",
            "--max-new-raw-objects",
            "140",
        ]
    )


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("health_from", None),
        ("through", None),
        ("resource", []),
        ("cached_tokens_only", False),
        ("max_provider_entries", 0),
        ("max_wall_seconds", 0),
        ("max_activities", 0),
        ("max_fit_downloads", 0),
        ("max_new_raw_objects", 0),
    ],
)
def test_cli_rejects_incomplete_budget_before_initialization(attribute, value):
    args = _bounded_args()
    setattr(args, attribute, value)
    with pytest.raises(ValueError, match="production_budget"):
        _validate_garmin_cli_args(args)


def test_cli_accepts_exact_explicit_budget():
    _validate_garmin_cli_args(_bounded_args())


def test_guard_stops_before_every_ceiling():
    now = [0.0]
    guard = ProductionBudgetGuard(_spec(), monotonic=lambda: now[0])
    guard.before_provider_entry()
    guard.before_provider_entry()
    with pytest.raises(GarminError, match="provider_entry_budget_exhausted"):
        guard.before_provider_entry()
    guard.before_activity("a")
    guard.before_activity("a")
    with pytest.raises(GarminError, match="activity_budget_exhausted"):
        guard.before_activity("b")
    guard.before_fit_download()
    with pytest.raises(GarminError, match="fit_download_budget_exhausted"):
        guard.before_fit_download()
    guard.before_new_raw_object()
    with pytest.raises(GarminError, match="raw_object_budget_exhausted"):
        guard.before_new_raw_object()
    now[0] = 10.0
    with pytest.raises(GarminError, match="wall_clock_budget_exhausted"):
        guard.before_provider_entry()
    assert guard.report()["counts"] == {
        "provider_entries": 2,
        "activities": 1,
        "fit_downloads": 1,
        "new_raw_objects": 1,
    }


def test_collection_contract_requires_the_matching_runtime_guard(tmp_path):
    spec = _spec()
    request = SyncRequest(
        "full",
        health_from_local_date="2026-08-03",
        through_local_date="2026-08-09",
        resource_kinds=("sleep",),
        production_budget=spec,
    )
    config = GarminConfig(
        tmp_path / "data.db",
        tmp_path / "raw",
        tmp_path / "state",
        "2026-01-01",
    )
    with pytest.raises(ValueError, match="guard_mismatch"):
        GarminCollectionTool(config)._validate(request)
    guard = ProductionBudgetGuard(spec)
    tool = GarminCollectionTool(config, budget_guard=guard)
    tool._validate(request)
    receipt = tool._validated_receipt(
        SyncReceipt(
            mode="full",
            status="succeeded",
            requested_range={"from": "2026-08-03", "through": "2026-08-09"},
            effective_range={"from": "2026-08-03", "through": "2026-08-09"},
            coverage_state="complete",
            completed_at_utc="2026-08-10T00:00:00Z",
        )
    )
    assert receipt.production_budget is not None
    assert receipt.production_budget["limits"] == guard.report()["limits"]
    assert receipt.production_budget["counts"] == guard.report()["counts"]
    assert receipt.production_budget["elapsed_seconds"] >= 0


class _Session:
    def request(self, *_args, **_kwargs):
        return object()


class _Inner:
    def __init__(self, *, expiring: bool = False) -> None:
        self.cs = _Session()
        self._api_session = _Session()
        self._tokenstore_path: str | None = None
        self.expiring = expiring
        self.loaded = False

    def load(self, _path: str) -> None:
        self.loaded = True
        self._tokenstore_path = _path

    def _token_expires_soon(self) -> bool:
        return self.expiring

    def _refresh_session(self) -> None:
        raise AssertionError("refresh must be replaced")

    def dump(self, _path: str) -> None:
        raise AssertionError("dump must be replaced")


class _Facade:
    def __init__(self, inner: _Inner) -> None:
        self.client = inner
        self.profile_loaded = False

    def _load_profile_and_settings(self) -> None:
        self.profile_loaded = True


def _transport(tmp_path: Path, *, expiring: bool = False):
    store = TokenStore(tmp_path / "tokens")
    store.prepare()
    token = store.directory / "garmin_tokens.json"
    token.write_text("synthetic-token")
    token.chmod(0o600)
    guard = ProductionBudgetGuard(_spec(max_provider_entries=3))
    inner = _Inner(expiring=expiring)
    facade = _Facade(inner)
    transport = GarminConnectTransport(
        None,
        None,
        store,
        client=facade,
        budget_guard=guard,
    )
    return transport, facade, inner, guard, token


def test_cached_only_login_blocks_refresh_and_token_writes(tmp_path):
    transport, facade, inner, guard, token = _transport(tmp_path)
    before = token.read_bytes()
    transport.login_cached_only()
    assert inner.loaded and facade.profile_loaded
    assert token.read_bytes() == before
    with pytest.raises(GarminError, match="cached_token_refresh_forbidden"):
        inner._refresh_session()
    with pytest.raises(GarminError, match="token_store_mutation_forbidden"):
        inner.dump("ignored")
    inner._api_session.request("GET", "https://example.invalid")
    assert guard.provider_entries == 1


def test_bounded_transport_constructor_never_prepares_token_store(
    tmp_path, monkeypatch
):
    store = TokenStore(tmp_path / "tokens")
    store.prepare()
    token = store.directory / "garmin_tokens.json"
    token.write_text("synthetic-token")
    token.chmod(0o600)
    monkeypatch.setattr(
        store,
        "prepare",
        lambda: (_ for _ in ()).throw(AssertionError("prepare mutates metadata")),
    )
    GarminConnectTransport(
        None,
        None,
        store,
        client=_Facade(_Inner()),
        budget_guard=ProductionBudgetGuard(_spec()),
    )


def test_cached_only_login_rejects_expiring_token_before_provider(tmp_path):
    transport, _facade, _inner, guard, _token = _transport(tmp_path, expiring=True)
    with pytest.raises(GarminError, match="cached_token_refresh_forbidden"):
        transport.login_cached_only()
    assert guard.provider_entries == 0


def test_raw_guard_reserves_only_before_a_new_object(tmp_path):
    root = tmp_path / "state"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation.json",
        root / "state" / "locks" / "foundation.lock",
    )
    FoundationTool(config).execute(
        FoundationRequest("init", "bounded-foundation", "2026-08-10T00:00:00Z")
    )
    guard = ProductionBudgetGuard(_spec())
    repository = GarminRepository(
        config,
        new_raw_object_guard=guard.before_new_raw_object,
    )
    first = repository.store_raw("sleep", b'{"value":1}', "json", "application/json")
    assert (
        repository.store_raw("sleep", b'{"value":1}', "json", "application/json")
        == first
    )
    with pytest.raises(GarminError, match="raw_object_budget_exhausted"):
        repository.store_raw("sleep", b'{"value":2}', "json", "application/json")
    assert guard.new_raw_objects == 1
