from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trainlab.garmin import SyncReceipt, SyncRequest
from trainlab.garmin_catalog import RESOURCE_CATALOG, catalog_lint
from trainlab.garmin_client import GarminConnectTransport, TokenStore


def test_request_and_receipt_schemas_are_closed_and_roundtrip() -> None:
    root = Path(__file__).resolve().parents[1] / "harness" / "schemas"
    request = asdict(SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="i")); request["resource_kinds"] = []; request["activity_ids"] = []
    receipt = asdict(SyncReceipt(mode="incremental", status="succeeded", requested_range={"from": None, "through": "2026-04-15"}, effective_range={"from": "2026-04-02", "through": "2026-04-15"}, coverage_state="complete", completed_at_utc="2026-04-16T00:00:00Z"))
    for name, value in (("garmin_sync_request.schema.json", request), ("garmin_sync_receipt.schema.json", receipt)):
        schema=json.loads((root/name).read_text()); assert not list(Draft202012Validator(schema).iter_errors(value)); value["unexpected"] = True; assert list(Draft202012Validator(schema).iter_errors(value)); value.pop("unexpected")


def test_catalog_has_all_semantic_groups_and_ignored_reasons() -> None:
    assert not catalog_lint()
    assert {"user_profile","devices","sleep","body_composition","training_readiness","activity_inventory","activity_fit"} <= set(RESOURCE_CATALOG)
    assert RESOURCE_CATALOG["get_stats"].ignored_reason == "alias:user_summary"


def test_token_store_permissions_and_pinned_adapter_monkeypatch(tmp_path: Path) -> None:
    store=TokenStore(tmp_path / "secrets" / "garmin"); directory=store.prepare(); assert directory.stat().st_mode & 0o777 == 0o700
    class Client:
        class Session:
            def request(self, *args, **kwargs): return object()
        def __init__(self): self.kwargs={}; self.cs=self.Session(); self._api_session=self.Session()
        def get_full_name(self): return "fake"
        def get_user_summary(self, day): return {"day":day}
        def count_activities(self): return 0
        def get_activities(self, start, limit): return []
        def get_activity(self, activity): return {"activityId":activity}
        def download_activity(self, activity, fmt): return b"fit"
    transport=GarminConnectTransport(None,None,store,client=Client())
    assert transport.identity() == "fake" and transport.fetch_health("user_summary","2026-01-01")["day"] == "2026-01-01" and list(transport.list_activities(None,None)) == []
    token=directory/"token"; token.write_text("x"); token.chmod(0o644)
    with pytest.raises(ValueError, match="unsafe_token_file"): store.verify()


def test_status_is_read_only_and_does_not_create_subject(tmp_path: Path) -> None:
    from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
    from trainlab.garmin import GarminCollectionTool, GarminConfig, SyncRequest
    root=tmp_path/"data"; foundation=FoundationConfig(root,root/"data.db",root/"raw",root/"state",root/"state/ready.json",root/"state/locks/f.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init","f","2026-01-01T00:00:00Z")).status == "initialized"
    before=os.stat(foundation.database_path).st_mtime_ns
    receipt=GarminCollectionTool(GarminConfig(foundation.database_path,foundation.raw_root,foundation.state_root,"2026-01-01")).execute(SyncRequest("status"))
    after=os.stat(foundation.database_path).st_mtime_ns
    assert receipt.status == "succeeded" and before == after
