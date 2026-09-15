"""Inventory names retain capture lineage without changing FIT parse identity."""

from __future__ import annotations

import importlib
import json

import pytest

helpers = importlib.import_module("test_m12_weekly_context")
fixture = helpers.fixture


def setup(tmp_path, monkeypatch, value="公园晚间跑步", *, absent=False):
    original = fixture.FakeSDK.call_tool

    async def named(self, name, arguments):
        result = await original(self, name, arguments)
        if name == "get_activities_by_date":
            data = json.loads(result.content[0].text)
            for item in data["activities"]:
                item["workout_name"] = "This is not the activity name"
                if absent:
                    item.pop("name", None)
                else:
                    item["name"] = value
            result.content[0].text = json.dumps(data)
        return result

    monkeypatch.setattr(fixture.FakeSDK, "call_tool", named)
    root, key, sdk, receipt = fixture.setup(tmp_path, monkeypatch)
    goal = root / "Goal.md"
    goal.write_text(helpers.goal_text())
    goal.chmod(0o600)
    return root, key, sdk, receipt


def test_existing_capture_name_reaches_input_with_correct_source_and_no_calls(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import storage

    root, key, sdk, receipt = setup(tmp_path, monkeypatch)
    before_calls = list(sdk.calls)
    body = fixture.freeze(root, key)
    names = [s["activity_name"] for s in body["activity_sources"]]
    assert [n["value"] for n in names] == ["公园晚间跑步"] * 2
    assert [n["source"]["item_index"] for n in names] == [0, 1]
    captures = list((root / "sync").rglob("response.mcp"))
    by_sha = {storage.digest(p.read_bytes()): p for p in captures}
    for name in names:
        assert name["status"] == "available"
        source = name["source"]
        assert source["kind"] == "garmin_mcp_inventory"
        assert source["field"] == "activities[].name"
        assert len(source["intent_sha256"]) == 64
        raw = json.loads(by_sha[source["capture_sha256"]].read_bytes())
        assert raw["activities"][source["item_index"]]["name"] == name["value"]
    assert all("activity_name" not in a for a in body["activities"])
    assert all("This is not" not in json.dumps(a) for a in body["activities"])
    context, _ = helpers.modules()
    current = context.freeze(root, fixture.END, validate_report=helpers.valid_report)
    assert current["current_week"]["activity_sources"] == body["activity_sources"]
    before = (root / "trainlab-fit.db").read_bytes()
    assert fixture.freeze(root, key) == body
    assert (
        context.freeze(root, fixture.END, validate_report=helpers.valid_report)
        == current
    )
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert sdk.calls == before_calls and receipt["external_actions"] == 0


@pytest.mark.parametrize(
    "value,absent,status",
    [
        (None, True, "missing"),
        ("", False, "missing"),
        ("   ", False, "missing"),
        (None, False, "missing"),
        ([], False, "insufficient_data"),
    ],
)
def test_unavailable_name_does_not_drop_activity_or_use_workout_name(
    tmp_path, monkeypatch, value, absent, status
):
    root, key, _, _ = setup(tmp_path, monkeypatch, value, absent=absent)
    body = fixture.freeze(root, key)
    assert len(body["activities"]) == 2
    for source in body["activity_sources"]:
        assert source["activity_name"]["status"] == status
        assert source["activity_name"]["value"] is None


def test_name_containing_credential_is_stopped_before_model_intent(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import model_job

    root, key, sdk, _ = setup(
        tmp_path, monkeypatch, "公园跑步 password: synthetic-only"
    )
    fixture.freeze(root, key)
    before = helpers.counts(root)
    calls = list(sdk.calls)
    with pytest.raises(ValueError, match="weekly_private_text"):
        helpers.modules()[0].freeze(
            root, fixture.END, validate_report=helpers.valid_report
        )
    assert helpers.counts(root) == before and sdk.calls == calls
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


def test_name_capture_drift_stops_frozen_context_replay(tmp_path, monkeypatch):
    root, key, _, _ = setup(tmp_path, monkeypatch)
    fixture.freeze(root, key)
    context, _ = helpers.modules()
    context.freeze(root, fixture.END, validate_report=helpers.valid_report)
    raw = next(
        p
        for p in (root / "sync").rglob("response.mcp")
        if "activities" in json.loads(p.read_bytes())
    )
    data = json.loads(raw.read_bytes())
    data["activities"][0]["name"] = "changed name"
    raw.write_text(json.dumps(data))
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="weekly_context_invalid"):
        context.freeze(root, fixture.END, validate_report=helpers.valid_report)
    assert (root / "trainlab-fit.db").read_bytes() == before
