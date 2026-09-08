"""A-022 changes sports admission, not credential or Host authority boundaries."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SOURCE), str(Path(__file__).parent)]
privacy = importlib.import_module("skills._shared.fit_weekly.input_privacy")
helpers = importlib.import_module("test_m12_weekly_context")
models = importlib.import_module("skills._shared.fit_weekly.model_job")
parser = importlib.import_module("skills._shared.fit_weekly.fit_parse")
matrix = importlib.import_module("test_m12_input_privacy")
fragments = importlib.import_module("test_m12_route_fragments")

SPORTS = [
    "route: 12.34°N / 56.78°E",
    "route: N12.34 E56.78",
    "路线：12.34°北纬，56.78°东经",
    "路线：[[12.34,56.78],[12.35,56.79]]",
    "活动名称：公园晚间跑步；GPS 可用",
    {"type": "LineString", "coordinates": [[12.34, 56.78], [12.35, 56.79]]},
    {"activity_name": "公园晚间跑步", "position_lat": 12.34, "position_long": 56.78},
]


@pytest.mark.parametrize("value", SPORTS)
def test_authorized_sports_admission_does_not_modify_content(value) -> None:
    before = models.clone(value)
    privacy.check(value, allow_sports_location=True)
    assert value == before


@pytest.mark.parametrize(
    "value",
    [
        {"route": {"points": [[12, 45]], "access_token": "synthetic-only"}},
        "活动名称：公园跑步；Authorization: Bearer synthetic-only",
        {"latitude": 12, "credential": "synthetic-only"},
        {"route": {"file_path": "/private/synthetic.fit"}},
        {"raw_fit_bytes": "synthetic-not-fit"},
        {"device_serial_number": "synthetic-device"},
    ],
)
def test_open_geography_does_not_open_credentials_paths_or_unrelated_identity(
    value,
) -> None:
    with pytest.raises(ValueError, match="weekly_private_text"):
        privacy.check(value, allow_sports_location=True)


@pytest.mark.parametrize("value", SPORTS[:5])
def test_new_context_allows_sports_goal_through_actual_fake_call_and_replay(
    tmp_path, monkeypatch, value
) -> None:
    monkeypatch.setattr(parser, "VERSION", "fit-summary-2")
    root, evidence, _ = helpers.setup(
        tmp_path, monkeypatch, parser_version="fit-summary-2"
    )
    (root / "goal.md").write_text(
        helpers.goal_text().replace("按运动表现安排跑步，保留攀岩时间", value, 1)
    )
    context, _ = helpers.modules()
    body = context.freeze(
        root, helpers.fixture.END, validate_report=helpers.valid_report
    )
    assert evidence["schema_version"] == "fit_weekly_evidence_v2"
    assert body["schema_version"] == "fit_weekly_context_v2"
    assert all("location" in a for a in body["current_week"]["activities"])
    adapter = models.FakeAdapter({"ok": "synthetic"}, [])
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "string", "const": "synthetic"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    def result_check(result, payload):
        assert result == {"ok": "synthetic"} and payload == body

    def run():
        return models.run(
            root,
            helpers.fixture.END,
            body["scope_sha256"],
            body,
            schema,
            adapter,
            validate_input=context.validator(
                root, helpers.fixture.END, validate_report=helpers.valid_report
            ),
            validate_result=result_check,
        )

    result = run()
    assert result["status"] == "succeeded" and adapter.calls == 1
    before = (root / "trainlab-fit.db").read_bytes()
    replay = run()
    assert replay == {**result, "invocation_adapter_calls": 0} and adapter.calls == 1
    assert (root / "trainlab-fit.db").read_bytes() == before


def test_legacy_frozen_context_is_unchanged_after_current_parser_upgrade(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(parser, "VERSION", "fit-summary-1")
    root, _, _ = helpers.setup(tmp_path, monkeypatch, parser_version="fit-summary-1")
    context, _ = helpers.modules()
    old = context.freeze(
        root, helpers.fixture.END, validate_report=helpers.valid_report
    )
    before = (root / "trainlab-fit.db").read_bytes()
    monkeypatch.setattr(parser, "VERSION", "fit-summary-2")
    (root / "goal.md").unlink()
    assert (
        context.freeze(root, helpers.fixture.END, validate_report=helpers.valid_report)
        == old
    )
    assert (root / "trainlab-fit.db").read_bytes() == before


def test_current_tool_contract_changes_but_only_known_old_surface_can_recover() -> None:
    boundary = importlib.import_module("skills._shared.fit_weekly.codex_boundary")
    server = importlib.import_module("skills._shared.fit_weekly.detail_server")
    old = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_cli_tools.json").read_text()
    )
    new = models.clone(old)
    next(t for t in new if t["name"] == "mcp__fit")["tools"][0]["description"] = (
        server.TOOL_DESCRIPTION
    )
    boundary.require_tool_surface(new)
    with pytest.raises(ValueError, match="codex_capabilities_invalid"):
        boundary.require_tool_surface(old)
    boundary.require_tool_surface(
        old, expected_sha256=boundary.LEGACY_TOOL_SURFACE_SHA256
    )
    with pytest.raises(ValueError, match="codex_capabilities_invalid"):
        boundary.require_tool_surface(old, expected_sha256="0" * 64)


@pytest.mark.parametrize("value", SPORTS)
def test_complete_history_preserves_authorized_location(
    tmp_path, monkeypatch, value
) -> None:
    matrix = importlib.import_module("test_m12_input_privacy")
    monkeypatch.setattr(parser, "VERSION", "fit-summary-2")
    root, _, _ = helpers.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")

    business = matrix.archive_value(root, "conclusion", value)
    context, _ = helpers.modules()
    body = context.freeze(root, helpers.fixture.END, validate_report=business)
    assert body["history_reports"][0]["report"]["conclusion"] == value
    before = (root / "trainlab-fit.db").read_bytes()
    assert context.freeze(root, helpers.fixture.END, validate_report=business) == body
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize(
    "value", [matrix.PIPELINE_VALUES[i] for i in (6, 7, 8, 9, 10, 11, 12, 16, 17)]
)
@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
@pytest.mark.parametrize("stage", ["freeze", "replay", "preflight", "model"])
def test_v2_protected_categories_at_all_ingresses(
    tmp_path, monkeypatch, value, entry, stage
):
    # Same original refusal/count/SHA assertions, now through the active parser.
    matrix.test_all_ingresses_stop_before_new_model_intent(
        tmp_path, monkeypatch, value, entry, stage, parser_version="fit-summary-2"
    )


@pytest.mark.parametrize("value", [*matrix.ROUTES, *fragments.PIPELINE, *SPORTS])
@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
def test_geography_expectation_migration_reaches_model_and_replays(
    tmp_path, monkeypatch, value, entry
):
    root, _, sdk = helpers.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    business = helpers.valid_report
    if entry == "goal":
        # The existing goal contract is one Markdown field per line. Represent
        # multiline text as JSON text there; history still preserves raw newlines.
        text = (
            value
            if isinstance(value, str) and "\n" not in value
            else json.dumps(value, ensure_ascii=False)
        )
        (root / "goal.md").write_text(
            helpers.goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
        )
    else:
        business = matrix.archive_value(root, entry.removeprefix("history_"), value)
    source_goal = (root / "goal.md").read_bytes()
    calls_before = list(sdk.calls)
    context, _ = helpers.modules()
    body = context.freeze(root, helpers.fixture.END, validate_report=business)
    if entry == "goal":
        assert body["goal_snapshot"]["goal"] == context.parse_training_goal_v1(
            source_goal.decode()
        )
    else:
        actual = body["history_reports"][0]["report"][entry.removeprefix("history_")]
        assert (actual[0] if entry == "history_plan" else actual) == value
    adapter = models.FakeAdapter({"ok": "synthetic"}, [])

    def result_check(output, payload):
        assert output == {"ok": "synthetic"} and payload == body

    def run():
        return models.run(
            root,
            helpers.fixture.END,
            body["scope_sha256"],
            body,
            matrix.closed_schema({"ok": "synthetic"}),
            adapter,
            validate_input=context.validator(
                root, helpers.fixture.END, validate_report=business
            ),
            validate_result=result_check,
        )

    assert run()["status"] == "succeeded" and adapter.calls == 1
    before = (root / "trainlab-fit.db").read_bytes()
    assert run()["invocation_adapter_calls"] == 0 and adapter.calls == 1
    assert context.freeze(root, helpers.fixture.END, validate_report=business) == body
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert (root / "goal.md").read_bytes() == source_goal
    assert sdk.calls == calls_before


def test_active_defaults_create_v2_without_parser_override(tmp_path, monkeypatch):
    root, key, _, _ = helpers.fixture.setup(tmp_path, monkeypatch)
    evidence = helpers.fixture.freeze(root, key)
    path = root / "goal.md"
    path.write_text(helpers.goal_text())
    path.chmod(0o600)
    context, _ = helpers.modules()
    body = context.freeze(
        root, helpers.fixture.END, validate_report=helpers.valid_report
    )
    assert parser.VERSION == "fit-summary-2"
    assert evidence["schema_version"] == "fit_weekly_evidence_v2"
    assert body["schema_version"] == "fit_weekly_context_v2"
    context.validator(root, helpers.fixture.END, validate_report=helpers.valid_report)(
        body
    )


def test_old_evidence_without_context_finishes_in_saved_version(tmp_path, monkeypatch):
    root, old, _ = helpers.setup(tmp_path, monkeypatch, parser_version="fit-summary-1")
    monkeypatch.setattr(parser, "VERSION", "fit-summary-2")
    context, _ = helpers.modules()
    body = context.freeze(
        root, helpers.fixture.END, validate_report=helpers.valid_report
    )
    assert body["schema_version"] == "fit_weekly_context_v1"
    assert body["current_week"]["activities"] == old["activities"]
    assert "location" not in json.dumps(old["activities"])
    storage = importlib.import_module("skills._shared.fit_weekly.storage")
    with storage.open_store(root) as db:
        versions = [
            r[0] for r in db.execute("SELECT DISTINCT parser_version FROM parses")
        ]
        assert versions == ["fit-summary-1"]


AUTH_HEADER_LABELS = (
    "认证头",
    "认证请求头",
    "授权头",
    "授权请求头",
    "authentication_header",
    "authorization_header",
)
SYNTHETIC_BASIC = "Basic c3ludGhldGljOnB1YmxpYy1maXh0dXJl"


@pytest.mark.parametrize("label", AUTH_HEADER_LABELS)
@pytest.mark.parametrize("separator", [":", "：", "="])
@pytest.mark.parametrize("allow_sports_location", [False, True])
def test_explicit_authentication_header_text_is_not_sports_data(
    label, separator, allow_sports_location
):
    value = f"活动结束后；{label}{separator}{SYNTHETIC_BASIC}"
    with pytest.raises(ValueError, match="^weekly_private_text$") as failure:
        privacy.check(value, allow_sports_location=allow_sports_location)
    assert SYNTHETIC_BASIC not in str(failure.value)


@pytest.mark.parametrize("label", AUTH_HEADER_LABELS)
@pytest.mark.parametrize("allow_sports_location", [False, True])
def test_nested_authentication_headers_are_rejected_without_mutating_sports(
    label, allow_sports_location
):
    value = {"notes": [{label: SYNTHETIC_BASIC}]}
    original = models.clone(value)
    with pytest.raises(ValueError, match="^weekly_private_text$"):
        privacy.check(value, allow_sports_location=allow_sports_location)
    assert value == original


@pytest.mark.parametrize(
    "value",
    [f"认证头：{SYNTHETIC_BASIC}", {"认证头": SYNTHETIC_BASIC}],
)
@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
@pytest.mark.parametrize("stage", ["freeze", "replay", "preflight", "model"])
def test_authentication_header_cannot_cross_any_v2_model_ingress(
    tmp_path, monkeypatch, value, entry, stage
):
    matrix.test_all_ingresses_stop_before_new_model_intent(
        tmp_path, monkeypatch, value, entry, stage, parser_version="fit-summary-2"
    )


def test_sports_location_and_header_discussion_are_not_rewritten_or_overblocked():
    value = {
        "activity_name": "公园跑步",
        "route": [[12.34, 56.78]],
        "notes": "不提供认证头或授权请求头；跑步/攀岩与 RPE 3/5。",
    }
    original = models.clone(value)
    privacy.check(value, allow_sports_location=True)
    assert value == original
