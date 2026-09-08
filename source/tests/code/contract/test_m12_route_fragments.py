"""Coordinate fragments and ordinary unit-bearing prose share one admission gate."""

from __future__ import annotations

import importlib

import pytest

matrix = importlib.import_module("test_m12_input_privacy")
helpers = matrix.helpers

FRAGMENTS = [
    "12.34,56.78",
    "-1.234e1;+5.678E1",
    "(12.34,56.78)",
    "(broken,56.78)",
    "(12.34,broken)",
    "[broken,56.78]",
    "[12.34,broken]",
    "(999,-999)",
    "12.34 56.78",
    "broken,56.78",
    "12.34,broken",
    "[[broken,56.78], [12.35,56.79]]",
    "('12.34','56.78')",
    "('broken', '56.78')",
    "(12.34, 'invalid value')",
    "('invalid value', 56.78)",
    "12.34°N 56.78°E",
    "12.34N,56.78E",
    "12°34'56\"N,56°34'12\"E",
]


@pytest.mark.parametrize("prefix", ["起点 ", "途经 ", "start ", "marker "])
@pytest.mark.parametrize("fragment", FRAGMENTS)
@pytest.mark.parametrize("nested", [False, True])
def test_prefixed_coordinates_require_no_place_word_dictionary(
    prefix, fragment, nested
):
    value = (
        {"route": {"description": prefix + fragment}}
        if nested
        else "路线：" + prefix + fragment
    )
    matrix.test_all_declared_private_categories_are_rejected(value)


NORMAL = [
    "路线：（5 km 平坦环线）",
    "route: (5 km flat loop)",
    "route: (5 km, 20 m climbing)",
    "路线：途经（5 km，20 m 爬升）",
    "route: marker (RPE 3, distance 5 km)",
    "route: (3, 5 repetitions)",
    "路线：坡度 12°，气温 20°C",
    {"route": {"description": "(5 km flat loop)", "distance_km": 5}},
    'route: {"description":"(5 km, 20 m climbing)"}',
    {"route": {"description": "(5 km)", "training": [[120, 156], [120, 157]]}},
]


@pytest.mark.parametrize("value", NORMAL)
def test_unit_bearing_route_prose_keeps_whole_numbers_and_units(value):
    matrix.test_normal_sports_and_route_descriptions_are_not_geolocation(value)


PIPELINE = [
    "路线：起点 12.34,56.78；终点 12.35,56.79",
    "路线：起点 (broken, 56.78)",
    "route: marker (12.34, broken)",
    "route: start broken,56.78",
    {"route": {"description": "途经 12.34,56.78"}},
    {"notes": [{"route": "marker [broken,56.78]"}]},
    'route: {"description":"flat loop"} start (12.34,56.78)',
    "route: marker (12.34, 'invalid value')",
    "route: marker 12°34'56\"N,56°34'12\"E",
]


@pytest.mark.parametrize("value", PIPELINE)
@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
@pytest.mark.parametrize("stage", ["freeze", "replay", "preflight", "model"])
def test_fragment_privacy_at_every_existing_lifecycle(
    tmp_path, monkeypatch, value, entry, stage
):
    matrix.test_all_ingresses_stop_before_new_model_intent(
        tmp_path, monkeypatch, value, entry, stage
    )


@pytest.mark.parametrize("value", NORMAL)
def test_legal_history_fragment_preservation_and_model_replay(
    tmp_path, monkeypatch, value
):
    matrix.test_legal_full_history_is_byte_preserved_and_replayed_without_model(
        tmp_path, monkeypatch, value
    )


@pytest.mark.parametrize("value", NORMAL[:5])
def test_legal_goal_fragment_preservation_and_model_replay(
    tmp_path, monkeypatch, value
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = helpers.setup(tmp_path, monkeypatch)
    text = helpers.goal_text().replace("按运动表现安排跑步，保留攀岩时间", value, 1)
    (root / "goal.md").write_text(text)
    context = helpers.modules()[0]
    body = context.freeze(
        root, helpers.fixture.END, validate_report=helpers.valid_report
    )
    assert body["goal_snapshot"]["goal"] == context.parse_training_goal_v1(text)
    before_body = model_job.sha(body)
    adapter = model_job.FakeAdapter({"ok": "synthetic"}, [])

    def run():
        return model_job.run(
            root,
            helpers.fixture.END,
            body["scope_sha256"],
            body,
            matrix.closed_schema({"ok": "synthetic"}),
            adapter,
            validate_input=context.validator(
                root, helpers.fixture.END, validate_report=helpers.valid_report
            ),
            validate_result=lambda result, payload: result == {"ok": "synthetic"},
        )

    assert run()["status"] == "succeeded"
    count = helpers.counts(root)
    assert run()["status"] == "succeeded"
    assert adapter.calls == 1 and helpers.counts(root) == count
    assert model_job.sha(body) == before_body
    assert (
        context.freeze(root, helpers.fixture.END, validate_report=helpers.valid_report)
        == body
    )
    assert (root / "goal.md").read_text() == text
