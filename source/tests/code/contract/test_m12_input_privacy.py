"""Synthetic input-admission matrix; no private instance or Provider access."""

from __future__ import annotations

import copy
import importlib
import json
from typing import Any

import pytest

helpers = importlib.import_module("test_m12_weekly_context")

# Labels provide geographical meaning; numeric plausibility is not permission.
ROUTES: list[Any] = [
    "route: [[12.34,56.78],[12.35,56.79]]",
    "路线：[[12.34,56.78],[12.35,56.79]]",
    "track = (12.34, 56.78); (12.35,56.79)",
    "轨迹：12.34，56.78；12.35，56.79",
    "route: 12 56 -> 13 57",
    "route: -1.234e1,+5.678E1",
    "route:\n[[12.34,\n56.78], [12.35,56.79]]",
    "‘路线’ = [[12.34,56.78]]",
    'route: {"lat":12.34,"lon":56.78}',
    {"route": [[12.34, 56.78], [12.35, 56.79]]},
    {"training": [{"轨迹": {"points": [[12.34, 56.78]]}}]},
    {"route": {"coordinates": [12.34, 56.78]}},
    {"route": {"lat": 12.34, "lng": 56.78}},
    {"geometry": {"type": "Point", "coordinates": [12.34, 56.78]}},
    {"type": "LineString", "coordinates": [[12.34, 56.78]]},
    {"路线": [999, -999]},
    {"route": [[12.34, "damaged"], [12.35, 56.79]]},
    {"route": {"coordinates": None}},
    "coordinates: [broken]",
    "路线坐标：无效载荷",
    "route: [[999, broken], [12.35,56.79]",
    "route: [12.34, broken]",
    "ｒｏｕｔｅ：［［１２．３４，５６．７８］］",
    "路线：起点 (12.34,56.78)，终点 (12.35,56.79)",
    "route: 12.34°N, 56.78°E",
    "route_points: [broken]",
    {"路线点列": [[12.34, 56.78]]},
    {"type": "Point", "data": [999, "broken"]},
    '地理结构：{"type":"LineString","data":[[12.34,56.78]]}',
    "route: NaN, 56.78",
    "route: broken, 56.78",
    "路线：56.78，broken",
]

PRIVATE: list[Any] = ROUTES + [
    {"raw_fit": "synthetic-base64"},
    {"fit_bytes": [1, 2, 3]},
    {"raw_payload": {"any": "synthetic"}},
    "原始FIT：synthetic-base64",
    "rawPayload = synthetic-data",
    "download: file:///private/synthetic.fit",
    "源文件：/opt/synthetic/activity.fit",
    "附件：../private/synthetic.fit",
    "C:\\synthetic\\activity.fit",
    "\\\\synthetic\\share\\activity.fit",
    {"gps": {"x": 12.34, "y": 56.78}},
    {"latitude": None},
    "lat=12.34; lng=56.78",
    "position_lat：12.34",
    {"activityName": "Synthetic activity"},
    "活动名称：公开合成活动",
    {"athlete_id": 12345},
    "userName：Synthetic person",
    {"deviceSerialNumber": "synthetic-device"},
    "设备序列号：synthetic-device",
    "owner@example.invalid",
    {"email": None},
    {"accessToken": {"value": "synthetic-token"}},
    "‘password’＝synthetic-password",
    "Bearer synthetic-token",
    {"authentication": {"value": "synthetic"}},
    {"clientSecret": None},
    "凭据：synthetic-value",
    "~/synthetic/activity.fit",
    "file_path: fits/synthetic.fit",
    {"file_path": "fits/synthetic.fit"},
    "数据文件 fits/synthetic.fit",
]

LEGAL: list[Any] = [
    "路线：平坦环线，避免陡坡",
    {"route": "平坦环线"},
    {"路线": {"description": "平坦环线"}},
    "跑步/攀岩；min/km、km/h、m/s、RPE 3/5",
    "跑量 12.34 km；配速 5:56 min/km；心率 156 bpm，功率 250 W",
    {"training": [[12.34, 56.78], [12.35, 56.79]]},
    {"segments": [{"duration_seconds": 120, "heart_rate": 156}]},
    "route: 5 km，含 2 次爬坡",
    "技术 notes：左右脚平衡 49.5/50.5；不提供位置",
    "token；device ID；不需要密码；不回传原始FIT",
    {"activity_ref": "9001", "fit_sha256": "a" * 64},
    {"notes": ["路线：平坦环线", "５：３０ min/km", "RPE 3/5"]},
    {"route": {"distance_km": 5, "elevation_m": 20, "description": "平坦"}},
    'route: {"distance_km":5,"elevation_m":20,"description":"平坦"}',
    '路线：{"description":"5 km 平坦环线，强度 3/5"}',
    '路线：["平坦5公里", "短坡2次"]',
    "路线：(平坦环线，5 km)",
    {"route": {"description": "平坦", "training": [[120, 156], [120, 157]]}},
    'route: {"description":"平坦", "training":[[120,156],[120,157]]}',
    {"route": {"points": "选择平坦路段"}},
]


@pytest.mark.parametrize("value", PRIVATE)
def test_all_declared_private_categories_are_rejected(value):
    original = copy.deepcopy(value)
    with pytest.raises(ValueError, match="^weekly_private_text$"):
        helpers.modules()[0].check_text(value)
    assert value == original


@pytest.mark.parametrize("value", LEGAL)
def test_normal_sports_and_route_descriptions_are_not_geolocation(value):
    original = copy.deepcopy(value)
    helpers.modules()[0].check_text(value)
    assert value == original


def closed_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {k: closed_schema(v) for k, v in value.items()},
            "required": list(value),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        variants = {json.dumps(closed_schema(v), sort_keys=True) for v in value}
        items = [json.loads(v) for v in sorted(variants)]
        return {
            "type": "array",
            "items": items[0] if len(items) == 1 else {"anyOf": items},
        }
    return {
        "type": (
            "null"
            if value is None
            else "number"
            if isinstance(value, (int, float))
            else "string"
        )
    }


def archive_value(root, field, value):
    from skills._shared.fit_weekly import fit_detail, model_job

    end = helpers.end_before(1)
    scope = fit_detail.freeze_scope(root, end, [])
    output: dict[str, Any] = {
        "conclusion": "合成周报",
        "goal": "合成目标",
        "plan": ["合成课"] * 7,
    }
    if field == "plan":
        output["plan"][0] = value
    else:
        output[field] = value
    payload = {"synthetic": True}

    def business(body, context):
        assert body == output and context == payload

    result = model_job.run(
        root,
        end,
        scope["scope_sha256"],
        payload,
        closed_schema(output),
        model_job.FakeAdapter(output, []),
        validate_input=lambda body: body == payload,
        validate_result=business,
    )
    assert result["status"] == "succeeded"
    archive = helpers.modules()[1].archive(root, end, validate_report=business)
    assert archive["report"] == output
    return business


# Every category crosses the same actual storage/freeze/model interface. A
# monkeypatch is used only to manufacture an unsafe legacy snapshot for replay.
PIPELINE_VALUES = [
    *ROUTES[:2],
    ROUTES[9],
    ROUTES[13],
    ROUTES[16],
    ROUTES[19],
    {"raw_fit": "synthetic-bytes"},
    "rawPayload: synthetic-data",
    "file:///private/synthetic.fit",
    {"nested": [{"device_id": "synthetic-id"}]},
    "owner@example.invalid",
    {"password": "synthetic"},
    "Authorization: synthetic",
    {"activityName": "Synthetic activity"},
    "纬度：12.34 经度：56.78",
    "route: broken, 56.78",
    "~/synthetic/activity.fit",
    {"file_path": "fits/synthetic.fit"},
]


@pytest.mark.parametrize("value", PIPELINE_VALUES)
@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
@pytest.mark.parametrize("stage", ["freeze", "replay", "preflight", "model"])
def test_all_ingresses_stop_before_new_model_intent(
    tmp_path, monkeypatch, value, entry, stage, *, parser_version="fit-summary-1"
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = helpers.setup(tmp_path, monkeypatch, parser_version=parser_version)
    context = helpers.modules()[0]
    business = helpers.valid_report
    if entry == "goal":
        text = (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )
        (root / "goal.md").write_text(
            helpers.goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
        )
    else:
        business = archive_value(root, entry.removeprefix("history_"), value)
    original_goal = (root / "goal.md").read_bytes()
    body = None
    if stage != "freeze":
        with monkeypatch.context() as patch:
            patch.setattr(context, "check_text", lambda _, **_policy: None)
            body = context.freeze(root, helpers.fixture.END, validate_report=business)
    before = helpers.counts(root)
    adapter = model_job.FakeAdapter({}, [])
    with pytest.raises(
        ValueError,
        match="^(weekly_goal_invalid|weekly_private_text|weekly_context_invalid|model_job_input_invalid)$",
    ):
        if stage in {"freeze", "replay"}:
            context.freeze(root, helpers.fixture.END, validate_report=business)
        elif stage == "preflight":
            context.validator(root, helpers.fixture.END, validate_report=business)(body)
        else:
            assert body is not None
            model_job.run(
                root,
                helpers.fixture.END,
                body["scope_sha256"],
                body,
                helpers.report_schema(),
                adapter,
                validate_input=context.validator(
                    root, helpers.fixture.END, validate_report=business
                ),
                validate_result=business,
            )
    assert adapter.calls == 0
    assert helpers.counts(root) == before
    assert (root / "goal.md").read_bytes() == original_goal
    assert not model_job.capture_path(root, helpers.fixture.END).parent.exists()


@pytest.mark.parametrize("value", LEGAL)
def test_legal_full_history_is_byte_preserved_and_replayed_without_model(
    tmp_path, monkeypatch, value
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = helpers.setup(tmp_path, monkeypatch)
    business = archive_value(root, "goal", value)
    context = helpers.modules()[0]
    body = context.freeze(root, helpers.fixture.END, validate_report=business)
    assert body["history_reports"][0]["report"]["goal"] == value
    original = model_job.sha(body)
    adapter = model_job.FakeAdapter({"ok": "synthetic"}, [])

    def run():
        return model_job.run(
            root,
            helpers.fixture.END,
            body["scope_sha256"],
            body,
            closed_schema({"ok": "synthetic"}),
            adapter,
            validate_input=context.validator(
                root, helpers.fixture.END, validate_report=business
            ),
            validate_result=lambda result, payload: result == {"ok": "synthetic"},
        )

    assert run()["status"] == "succeeded"
    before = helpers.counts(root)
    assert run()["status"] == "succeeded"
    assert adapter.calls == 1 and helpers.counts(root) == before
    assert model_job.sha(body) == original
    assert (
        model_job.sha(
            context.freeze(root, helpers.fixture.END, validate_report=business)
        )
        == original
    )


def test_evidence_projection_preserves_all_allowed_facts_but_not_host_sources(
    tmp_path, monkeypatch
):
    root, evidence, _ = helpers.setup(tmp_path, monkeypatch)
    context = helpers.modules()[0]
    original = copy.deepcopy(evidence)
    projected = context.project_evidence(evidence)
    assert "sources" not in projected
    for key in (
        "parser_version",
        "period_start_utc",
        "period_end_utc",
        "next_plan_dates",
        "activities",
        "activity_sources",
        "unplaced_no_fit",
        "counts",
        "limitations",
        "provider_calls",
        "external_actions",
    ):
        assert projected[key] == evidence[key]
    assert evidence == original
    assert root.exists()
    bad = {**evidence, "undeclared": "synthetic-host-field"}
    with pytest.raises(ValueError):
        context.project_evidence(bad)
