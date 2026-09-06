from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))
factory = importlib.import_module("m12_fit_factory")
START = "2026-08-02T07:00:00Z"
END = "2026-08-09T07:00:00Z"


def module():
    return importlib.import_module("skills._shared.fit_weekly.weekly_evidence")


def stamp(offset):
    return datetime.fromisoformat(START) + timedelta(seconds=offset)


def data(start=3600, duration=600, sport=1):
    return factory.file_bytes(
        [
            factory.record(t, (t - start) * 3, 121)
            for t in range(start, start + duration + 1, 10)
        ]
        + [factory.session(start + duration, start=start, sport=sport, timer=duration)]
    )


class FakeSDK:
    def __init__(self, activities):
        self.activities = activities
        self.calls = []

    @asynccontextmanager
    async def session(self, spec):
        yield self

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name=x)
                for x in ("get_activities_by_date", "download_activity_file")
            ],
            nextCursor=None,
        )

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        if name == "get_activities_by_date":
            value = {
                "page": 0,
                "page_size": 20,
                "has_more": False,
                "count": len(self.activities),
                "date_range": {
                    "start": arguments["start_date"],
                    "end": arguments["end_date"],
                },
                "activities": [
                    {
                        "id": int(ref),
                        "start_time": (stamp(start) + timedelta(hours=8)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "name": "excluded private activity title",
                    }
                    for ref, start, _ in self.activities
                ],
            }
        else:
            ref = str(arguments["activity_id"])
            payload = next(x[2] for x in self.activities if x[0] == ref)
            if payload is None:
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="text", text=f"No fit data returned for activity {ref}"
                        )
                    ],
                    isError=False,
                )
            else:
                p = Path(arguments["output_dir"]) / f"{ref}.fit"
                p.write_bytes(payload)
                p.chmod(0o600)
                value = {
                    "activity_id": int(ref),
                    "file_path": str(p),
                    "format": "fit",
                    "size_bytes": len(payload),
                    "message": "Activity file saved.",
                }
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(value))],
            isError=False,
        )


def setup(tmp_path, monkeypatch, activities=None, **request_changes):
    from skills._shared.fit_weekly import fit_sync, garmin_fit, storage, sync_calendar

    epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(factory, "BASE", int((stamp(0) - epoch).total_seconds()))
    if activities is None:
        activities = [("101", 3600, data()), ("102", 7200, data(7200, sport=31))]
    root = tmp_path / "instance"
    storage.initialize(root)
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    token = tokens / "synthetic.json"
    token.write_text('{"synthetic":true}')
    token.chmod(0o600)
    monkeypatch.setattr(garmin_fit.shutil, "which", lambda _: "/synthetic/uvx")
    args = {
        "key": "weekly:2026-08-09",
        "start_date": "2026-08-02",
        "end_date": "2026-08-09",
        "as_of_utc": "2026-08-09T07:00:10Z",
        "page_size": 20,
        "max_calls": 2,
        **request_changes,
    }
    spec = fit_sync.SyncSpec(sync_calendar.InventoryRequest(**args), 20, 2, 2, True)
    sdk = FakeSDK(activities)
    receipt = asyncio.run(
        fit_sync.synchronize(root, spec, token_root=tokens, session_factory=sdk.session)
    )
    return root, spec.inventory.key, sdk, receipt


def freeze(root, key):
    return module().freeze(root, END, key)


def test_full_real_fake_sdk_to_weekly_evidence_all_sports_and_zero_calls(
    tmp_path, monkeypatch
):
    root, key, sdk, receipt = setup(tmp_path, monkeypatch)
    before = list(sdk.calls)
    body = freeze(root, key)
    assert sdk.calls == before
    assert body["period_start_utc"] == START and body["period_end_utc"] == END
    assert body["next_plan_dates"] == [f"2026-08-{n:02}" for n in range(10, 17)]
    assert [a["activity_ref"] for a in body["activities"]] == ["101", "102"]
    assert {s["sport"] for a in body["activities"] for s in a["sessions"]} == {
        "running",
        "rock_climbing",
    }
    assert body["counts"] == {
        "activities_with_fit": 2,
        "unplaced_no_fit": 0,
        "sync_inventory": 2,
    }
    assert body["provider_calls"] == 0 and body["external_actions"] == 0
    assert len(body["sources"]["sync_receipt_sha256"]) == 64
    assert body["sources"]["inventory_as_of_utc"] == "2026-08-09T07:00:10Z"
    assert body["sources"]["inventory_complete"] is True
    assert len(body["activity_sources"]) == 2
    text = json.dumps(body)
    for secret in (
        str(root),
        "relative_path",
        "file_path",
        "activity_name",
        "excluded private",
        "87654321",
        "position_lat",
        "tokens",
    ):
        assert secret not in text
    module().validate(body)


def test_replay_moving_instance_is_identical_no_rows_bytes_or_provider_increment(
    tmp_path, monkeypatch
):
    root, key, sdk, _ = setup(tmp_path, monkeypatch)
    first = freeze(root, key)
    before = (root / "trainlab-fit.db").read_bytes()
    assert freeze(root, key) == first
    assert (root / "trainlab-fit.db").read_bytes() == before
    moved = tmp_path / "moved"
    shutil.move(str(root), moved)
    assert freeze(moved, key) == first
    assert (moved / "trainlab-fit.db").read_bytes() == before


def test_empty_completed_inventory_not_no_fit(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch, [])
    body = freeze(root, key)
    assert body["activities"] == body["unplaced_no_fit"] == []
    assert body["counts"]["sync_inventory"] == 0


def test_no_fit_remains_explicit_unknown_end_not_invented_zero_activity(
    tmp_path, monkeypatch
):
    root, key, _, _ = setup(tmp_path, monkeypatch, [("201", 3600, None)])
    body = freeze(root, key)
    assert body["activities"] == []
    assert body["unplaced_no_fit"] == [
        {
            "activity_ref": "201",
            "inventory_date": "2026-08-02",
            "reason": "provider_no_fit_end_unknown",
        }
    ]
    assert body["counts"] == {
        "activities_with_fit": 0,
        "unplaced_no_fit": 1,
        "sync_inventory": 1,
    }


def imported(root, tmp_path, ref, payload):
    from skills._shared.fit_weekly import storage

    p = tmp_path / f"synthetic-{ref}.fit"
    p.write_bytes(payload)
    p.chmod(0o600)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, ref, p, storage.digest(payload))


def test_half_open_end_and_long_cross_start_registered_fit_included(
    tmp_path, monkeypatch
):
    root, key, _, _ = setup(tmp_path, monkeypatch, [])
    for ref, a, b in [
        ("1", -600, 0),
        ("2", -90000, 10),
        ("3", 604790, 604800),
        ("4", 604791, 604799),
    ]:
        imported(
            root,
            tmp_path,
            ref,
            factory.file_bytes([factory.session(b, start=a, timer=b - a)]),
        )
    body = freeze(root, key)
    assert [a["activity_ref"] for a in body["activities"]] == ["1", "2", "4"]
    assert all(
        s["inventory_membership"] == "registered_fit_only"
        for s in body["activity_sources"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2026-08-03"},
        {"end_date": "2026-08-08"},
        {"as_of_utc": "2026-08-09T06:59:59Z"},
    ],
)
def test_incomplete_time_coverage_rejected_without_frozen_document(
    tmp_path, monkeypatch, changes
):
    root, key, _, _ = setup(tmp_path, monkeypatch, [], **changes)
    with pytest.raises(ValueError, match="weekly_sync_coverage_invalid"):
        freeze(root, key)
    assert not weekly_rows(root)


def weekly_rows(root):
    from skills._shared.fit_weekly import storage

    with storage.open_store(root) as db:
        return db.execute(
            "SELECT content_json FROM documents WHERE logical_key LIKE 'weekly-evidence:%'"
        ).fetchall()


def test_wrong_week_or_unknown_job_fails_before_freeze(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        module().freeze(root, "2026-08-09T07:00:01Z", key)
    with pytest.raises(ValueError, match="weekly_sync_incomplete"):
        freeze(root, "unknown")
    assert weekly_rows(root) == []


def test_late_fit_does_not_rewrite_frozen_week(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    first = freeze(root, key)
    imported(root, tmp_path, "999", data(86400))
    before = (root / "trainlab-fit.db").read_bytes()
    assert freeze(root, key) == first
    assert (root / "trainlab-fit.db").read_bytes() == before


def test_selected_fit_drift_blocks_cached_replay(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    first = freeze(root, key)
    p = root / "fits" / f"{first['activities'][0]['fit_sha256']}.fit"
    p.write_bytes(p.read_bytes() + b"bad")
    with pytest.raises(ValueError, match="fit_sha_mismatch"):
        freeze(root, key)


def test_freeze_sql_failure_rolls_back_parses_and_week(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import storage

    root, key, _, _ = setup(tmp_path, monkeypatch)
    before = (root / "trainlab-fit.db").read_bytes()
    original = storage.put_document

    def fail(db, kind, logical, sha, payload):
        if logical.startswith("weekly-evidence:"):
            raise OSError("synthetic write")
        return original(db, kind, logical, sha, payload)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "put_document", fail)
        with pytest.raises(OSError):
            freeze(root, key)
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert len(freeze(root, key)["activities"]) == 2


@pytest.mark.parametrize("location", ["root", "activity", "source"])
def test_schema_rejects_private_extra_fields(tmp_path, monkeypatch, location):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    body = freeze(root, key)
    target = {
        "root": body,
        "activity": body["activities"][0],
        "source": body["sources"],
    }[location]
    target["gps"] = [12.3, 45.6]
    with pytest.raises(ValueError, match="weekly_evidence_invalid"):
        module().validate(body)


def test_activities_ordered_by_end_not_provider_id(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch, [])
    imported(root, tmp_path, "9", data(3600))
    imported(root, tmp_path, "1", data(7200))
    body = freeze(root, key)
    assert [a["activity_ref"] for a in body["activities"]] == ["9", "1"]
    assert [a["activity_ref"] for a in body["activity_sources"]] == ["9", "1"]


@pytest.mark.parametrize("suffix", [":request", ":complete", "inventory"])
def test_missing_complete_chain_never_creates_week(tmp_path, monkeypatch, suffix):
    from skills._shared.fit_weekly import fit_sync

    root, key, _, _ = setup(tmp_path, monkeypatch)
    original = fit_sync.document

    def missing(db, name):
        if (
            name.startswith("inventory:")
            if suffix == "inventory"
            else name.endswith(suffix)
        ):
            return None
        return original(db, name)

    monkeypatch.setattr(fit_sync, "document", missing)
    with pytest.raises(ValueError, match="weekly_sync_incomplete"):
        freeze(root, key)
    assert not weekly_rows(root)


def test_current_activity_multi_fit_revision_conflict_rolls_back(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    imported(root, tmp_path, "101", data(3700))
    with pytest.raises(ValueError, match="weekly_activity_revision_conflict"):
        freeze(root, key)
    assert not weekly_rows(root)


def test_unparseable_registered_fit_does_not_silently_disappear(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch, [])
    # Storage accepts activity containers; analysis still needs real boundaries.
    payload = factory.file_bytes([factory.message(18, [(5, 0, 1)])])
    imported(root, tmp_path, "800", payload)
    with pytest.raises(ValueError):
        freeze(root, key)
    assert not weekly_rows(root)


@pytest.mark.parametrize("kind", ["wide", "symlink", "hardlink", "missing"])
def test_capture_closure_and_permissions_rechecked_before_freeze(
    tmp_path, monkeypatch, kind
):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    p = next((root / "sync").rglob("response.mcp"))
    if kind == "wide":
        p.chmod(0o644)
    elif kind in ("symlink", "hardlink"):
        original = tmp_path / "synthetic-capture"
        p.rename(original)
        if kind == "symlink":
            p.symlink_to(original)
        else:
            p.hardlink_to(original)
    else:
        p.unlink()
    with pytest.raises(ValueError):
        freeze(root, key)
    assert not weekly_rows(root)


@pytest.mark.parametrize(
    "change", ["count", "parse_sha", "activity_ref", "fit_sha", "period", "plan_date"]
)
def test_semantic_binding_rejects_detached_payload(tmp_path, monkeypatch, change):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    body = freeze(root, key)
    if change == "count":
        body["counts"]["activities_with_fit"] += 1
    elif change == "parse_sha":
        body["activity_sources"][0]["parse_sha256"] = "0" * 64
    elif change == "activity_ref":
        body["activity_sources"][0]["activity_ref"] = "999"
    elif change == "fit_sha":
        body["activity_sources"][0]["fit_sha256"] = "0" * 64
    elif change == "period":
        body["period_start_utc"] = "2026-08-01T07:00:00Z"
    else:
        body["next_plan_dates"][0] = "2026-08-09"
    with pytest.raises(ValueError, match="weekly_evidence_invalid"):
        module().validate(body)


def test_registered_no_fit_conflict_not_converted_to_available(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch, [("201", 3600, None)])
    imported(root, tmp_path, "201", data())
    with pytest.raises(ValueError, match="weekly_sync_source_conflict"):
        freeze(root, key)
    assert not weekly_rows(root)


def test_new_sync_job_cannot_replace_frozen_week(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import fit_sync, sync_calendar

    root, key, _, _ = setup(tmp_path, monkeypatch, [])
    first = freeze(root, key)
    request = sync_calendar.InventoryRequest(
        "new-sync", "2026-08-02", "2026-08-09", "2026-08-09T14:00:00Z", 20, 2
    )
    sdk = FakeSDK([])
    asyncio.run(
        fit_sync.synchronize(
            root,
            fit_sync.SyncSpec(request, 20, 2, 2, True),
            token_root=tmp_path / "tokens",
            session_factory=sdk.session,
        )
    )
    with pytest.raises(ValueError, match="weekly_evidence_frozen_conflict"):
        freeze(root, "new-sync")
    assert freeze(root, key) == first
