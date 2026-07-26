from __future__ import annotations
import json,re
from datetime import datetime
from pathlib import Path
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest
from .garmin_fakes import DeterministicClock, FakeGarminTransport
from .test_garmin_l2_01_04 import env

SECRET=re.compile(r"(?i)([\w.+-]+@[\w.-]+|bearer\s+\S+|password\s*[:=]|token\s*[:=])")

def test_manifest_and_synthetic_fixtures_have_safe_metadata_only():
 root=Path(__file__).parent/"fixtures"; manifest=json.loads((root/"garmin_fit_manifest.json").read_text()); health=(root/"garmin_health_synthetic.json").read_text()
 assert "user-provided" in manifest["source"] and len(manifest["files"])==6 and not SECRET.search(health)
 assert all(set(item)=={"sha256","type"} for item in manifest["files"].values())

def test_injected_monotonic_rng_and_fault_sequence_are_deterministic(tmp_path):
 c,t=env(tmp_path); sleeps=[]; ticks=iter([0.0,0.5,0.5]); t.sleep=sleeps.append; t.monotonic=lambda:next(ticks); t.rng=lambda:0.25
 outcomes=[GarminError("temporary",http_status=500),"ok"]
 def call():
  value=outcomes.pop(0)
  if isinstance(value,Exception): raise value
  return value
 # There is no artificial delay before the first provider call.  The retry
 # backoff already exceeds the configured 500 ms request interval.
 assert t._call(call)=="ok" and sleeps==[2.25]

def test_receipt_and_captured_output_do_not_match_secret_patterns(tmp_path,caplog):
 c,t=env(tmp_path); receipt=t.execute(SyncRequest("incremental",through_local_date="2026-04-15",invocation_id="scan"))
 assert not SECRET.search(receipt.json()) and not SECRET.search("\n".join(record.message for record in caplog.records))
