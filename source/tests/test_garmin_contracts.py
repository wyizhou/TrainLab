from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from src.garmin import ProductionBudgetSpec, SyncReceipt, SyncRequest
from src.garmin_catalog import RESOURCE_CATALOG, catalog_lint
from src.garmin_client import GarminConnectTransport, TokenStore
from src.garmin_config import load_garmin_config
from src.resources import resource_bytes


def _garmin_config_payload(token_store: str = "state/secrets/garmin") -> str:
    return f"""garmin:
  history_start_date: "2026-01-01"
  region: cn
  token_store: {token_store}
  lookback_days: 14
  max_repair_items_per_incremental: 100
  request_min_interval_ms: 500
  request_interval_jitter_ms: 0
  request_timeout_seconds: 30
  max_attempts: 5
  retry_base_seconds: 2
  retry_max_seconds: 60
  inline_retry_after_max_seconds: 120
  rate_limit_fallback_seconds: 900
"""


def test_token_store_locator_is_foundation_state_relative(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / "config" / "garmin.yaml").write_text(
        _garmin_config_payload(),
        encoding="utf-8",
    )
    foundation = SimpleNamespace(
        database_path=project / "runtime" / "data.db",
        raw_root=project / "runtime" / "raw",
        state_root=project / "runtime" / "state",
    )

    config = load_garmin_config(project, foundation)

    assert config.state_root == foundation.state_root
    assert config.region == "cn"
    assert foundation.state_root / "secrets" / "garmin" != (
        project / "state" / "secrets" / "garmin"
    )


@pytest.mark.parametrize(
    "token_store",
    (
        "state/secrets/garmin/alternate",
        "state/secrets/../garmin",
    ),
)
def test_token_store_locator_rejects_alternate_or_traversal_paths(
    tmp_path: Path,
    token_store: str,
) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / "config" / "garmin.yaml").write_text(
        _garmin_config_payload(token_store),
        encoding="utf-8",
    )
    foundation = SimpleNamespace(
        database_path=project / "runtime" / "data.db",
        raw_root=project / "runtime" / "raw",
        state_root=project / "runtime" / "state",
    )

    with pytest.raises(ValueError, match="invalid_garmin_token_store"):
        load_garmin_config(project, foundation)


def test_request_and_receipt_schemas_are_closed_and_roundtrip() -> None:
    request = asdict(
        SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="i")
    )
    request["resource_kinds"] = []
    request["activity_ids"] = []
    receipt = asdict(
        SyncReceipt(
            mode="incremental",
            status="succeeded",
            requested_range={"from": None, "through": "2026-04-15"},
            effective_range={"from": "2026-04-02", "through": "2026-04-15"},
            coverage_state="complete",
            completed_at_utc="2026-04-16T00:00:00Z",
        )
    )
    for name, value in (
        ("garmin_sync_request.schema.json", request),
        ("garmin_sync_receipt.schema.json", receipt),
    ):
        schema = json.loads(resource_bytes(f"harness/schemas/{name}"))
        assert not list(Draft202012Validator(schema).iter_errors(value))
        value["unexpected"] = True
        assert list(Draft202012Validator(schema).iter_errors(value))
        value.pop("unexpected")


def test_request_schema_accepts_bounded_repair_and_rejects_other_bounded_modes() -> (
    None
):
    validator = Draft202012Validator(
        json.loads(resource_bytes("harness/schemas/garmin_sync_request.schema.json"))
    )
    budget = ProductionBudgetSpec(2, 10, 1, 1, 1)
    repair = asdict(
        SyncRequest(
            "repair",
            health_from_local_date="2026-08-03",
            through_local_date="2026-08-09",
            resource_kinds=("activity_inventory",),
            production_budget=budget,
        )
    )
    repair["resource_kinds"] = list(repair["resource_kinds"])
    repair["activity_ids"] = list(repair["activity_ids"])
    assert not list(validator.iter_errors(repair))
    repair["mode"] = "incremental"
    assert list(validator.iter_errors(repair))


def test_catalog_has_all_semantic_groups_and_ignored_reasons() -> None:
    assert not catalog_lint()
    assert {
        "user_profile",
        "devices",
        "sleep",
        "body_composition",
        "training_readiness",
        "activity_inventory",
        "activity_fit",
    } <= set(RESOURCE_CATALOG)
    assert RESOURCE_CATALOG["get_stats"].ignored_reason == "alias:user_summary"


def test_token_store_permissions_and_pinned_adapter_monkeypatch(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "secrets" / "garmin")
    directory = store.prepare()
    assert directory.stat().st_mode & 0o777 == 0o700

    class Client:
        class Session:
            def request(self, *args, **kwargs):
                return object()

        def __init__(self):
            self.kwargs = {}
            self.cs = self.Session()
            self._api_session = self.Session()

        def get_full_name(self):
            return "fake"

        def get_user_summary(self, day):
            return {"day": day}

        def count_activities(self):
            return 0

        def get_activities(self, start, limit):
            return []

        def get_activity(self, activity):
            return {"activityId": activity}

        def download_activity(self, activity, fmt):
            return b"fit"

    transport = GarminConnectTransport(None, None, store, client=Client())
    assert (
        transport.identity() == "fake"
        and transport.fetch_health("user_summary", "2026-01-01")["day"] == "2026-01-01"
        and list(transport.list_activities(None, None)) == []
    )
    token = directory / "token"
    token.write_text("x")
    token.chmod(0o644)
    token_mtime = token.stat().st_mtime_ns
    with pytest.raises(ValueError, match="unsafe_token_file"):
        store.verify()
    store.prepare()
    assert token.read_text() == "x"
    assert token.stat().st_mtime_ns == token_mtime
    assert token.stat().st_mode & 0o777 == 0o600


def test_status_is_read_only_and_does_not_create_subject(tmp_path: Path) -> None:
    from src.foundation import FoundationConfig, FoundationRequest, FoundationTool
    from src.garmin import GarminCollectionTool, GarminConfig, SyncRequest

    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/ready.json",
        root / "state/locks/f.lock",
    )
    assert (
        FoundationTool(foundation)
        .execute(FoundationRequest("init", "f", "2026-01-01T00:00:00Z"))
        .status
        == "initialized"
    )
    before = os.stat(foundation.database_path).st_mtime_ns
    receipt = GarminCollectionTool(
        GarminConfig(
            foundation.database_path,
            foundation.raw_root,
            foundation.state_root,
            "2026-01-01",
        )
    ).execute(SyncRequest("status"))
    after = os.stat(foundation.database_path).st_mtime_ns
    assert receipt.status == "succeeded" and before == after
