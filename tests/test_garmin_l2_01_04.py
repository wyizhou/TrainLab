from __future__ import annotations
import hashlib, json, sqlite3
from datetime import datetime
from pathlib import Path
import pytest
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest
from .garmin_fakes import DeterministicClock, FakeGarminTransport

def env(tmp_path: Path):
 root=tmp_path/"data"; f=FoundationConfig(root,root/"data.db",root/"raw",root/"state",root/"state/r.json",root/"state/locks/f.lock")
 assert FoundationTool(f).execute(FoundationRequest("init","f","2026-01-01T00:00:00Z")).status in {"initialized","already_initialized"}
 fit=(Path(__file__).parents[1]/"test_data/new/Running.fit").read_bytes(); c=GarminConfig(f.database_path,f.raw_root,f.state_root,"2026-04-15")
 t=GarminCollectionTool(c,FakeGarminTransport(fit),sleep=lambda _:None,clock=DeterministicClock(datetime(2026,4,17)))
 assert t.execute(SyncRequest("auth")).status=="succeeded"; return c,t

@pytest.mark.parametrize("sync_request",[SyncRequest("auth",through_local_date="2026-01-01"),SyncRequest("status",resource_kinds=("steps",)),SyncRequest("snapshot",health_from_local_date="2026-01-01"),SyncRequest("full",snapshot_local_date="2026-01-01"),SyncRequest("repair",snapshot_local_date="2026-01-01",resource_kinds=("steps",))])
def test_mode_parameters_are_mutually_exclusive(sync_request):
 with pytest.raises(ValueError): GarminCollectionTool(GarminConfig(Path("x"),Path("x"),Path("x"),"2026-01-01")).execute(sync_request)

def test_invocation_replay_returns_original_receipt(tmp_path: Path):
 c,t=env(tmp_path); first=t.execute(SyncRequest("full",through_local_date="2026-04-15",invocation_id="same")); second=t.execute(SyncRequest("full",through_local_date="2026-04-15",invocation_id="same"))
 assert first.run_id==second.run_id and first.completed_at_utc==second.completed_at_utc and first.counts==second.counts
 conn=sqlite3.connect(c.database_path); assert conn.execute("select count(*) from garmin_sync_runs").fetchone()[0]==1; conn.close()

def test_manifest_hashes_and_no_sensitive_strings(tmp_path: Path):
 manifest=json.loads((Path(__file__).parent/"fixtures/garmin_fit_manifest.json").read_text())
 root=Path(__file__).parents[1]/"test_data/new"
 assert {p.name for p in root.glob("*.fit")} == set(manifest["files"])
 assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==entry["sha256"] for name,entry in manifest["files"].items())
 assert b"fake-account" not in (root/"Running.fit").read_bytes()

def test_auth_required_before_facts_and_long_rate_limit_is_structured(tmp_path: Path):
 c,t=env(tmp_path); unauth=GarminCollectionTool(c,FakeGarminTransport(b"x"),sleep=lambda _:None,clock=DeterministicClock(datetime(2026,4,17)))
 # different subject identity is not automatically authenticated: a fresh db proves no Garmin write before auth
 root=tmp_path/"fresh"; f=FoundationConfig(root,root/"data.db",root/"raw",root/"state",root/"state/r.json",root/"state/locks/f.lock"); FoundationTool(f).execute(FoundationRequest("init","x","2026-01-01T00:00:00Z")); new=GarminCollectionTool(GarminConfig(f.database_path,f.raw_root,f.state_root,"2026-04-15"),FakeGarminTransport(b"x"),sleep=lambda _:None,clock=DeterministicClock(datetime(2026,4,17)))
 assert new.execute(SyncRequest("incremental",through_local_date="2026-04-15")).status=="auth_required"
 conn=sqlite3.connect(f.database_path); assert conn.execute("select count(*) from raw_objects where provider='garmin'").fetchone()[0]==0; conn.close()

def test_dead_lock_without_active_run_is_recovered(tmp_path: Path):
 c,t=env(tmp_path); lock=c.state_root/"locks/garmin.lock"; lock.parent.mkdir(parents=True,exist_ok=True); lock.write_text('{"pid":999999999,"started_at_utc":"2020-01-01T00:00:00Z"}')
 assert t.execute(SyncRequest("repair",health_from_local_date="2026-04-15",through_local_date="2026-04-15",resource_kinds=("user_summary",),repair_strategy="refetch",invocation_id="stale")).status=="succeeded"

def test_401_refresh_once_then_success_and_second_failure_stops(tmp_path: Path):
 c,t=env(tmp_path); t.transport.faults["health:user_summary"]=[GarminError("one",http_status=401)]
 assert t.execute(SyncRequest("repair",health_from_local_date="2026-04-15",through_local_date="2026-04-15",resource_kinds=("user_summary",),repair_strategy="refetch",invocation_id="refresh-ok")).status=="succeeded"
 assert t.transport.calls.count("login") >= 3
 c,t=env(tmp_path); t.transport.faults["health:user_summary"]=[GarminError("one",http_status=401),GarminError("two",http_status=401)]
 receipt=t.execute(SyncRequest("repair",health_from_local_date="2026-04-15",through_local_date="2026-04-15",resource_kinds=("user_summary",),repair_strategy="refetch",invocation_id="refresh-fail"))
 assert receipt.status=="auth_required" and "health:steps" not in t.transport.calls
