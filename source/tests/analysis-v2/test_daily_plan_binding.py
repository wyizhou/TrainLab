from types import SimpleNamespace

from src.analysis.daily import _today_plan_binding


def test_daily_plan_binding_requires_one_item_for_the_report_date():
    snapshot = SimpleNamespace(
        views={
            "v_current_training_plans": (
                {
                    "id": 7,
                    "plan_start_local_date": "2026-08-10",
                    "plan_end_local_date": "2026-08-16",
                },
            ),
            "v_training_plan_items": (
                {
                    "training_plan_id": 7,
                    "local_date": "2026-08-13",
                    "activity_kind": "running",
                    "prescription_json": '{"activity_kind":"running","hansons_session_role":"easy"}',
                },
            ),
        }
    )
    state, item = _today_plan_binding(snapshot, "2026-08-13")
    assert state == "available"
    assert item == {
        "local_date": "2026-08-13",
        "activity_kind": "running",
        "prescription": {
            "activity_kind": "running",
            "hansons_session_role": "easy",
        },
    }


def test_daily_plan_binding_marks_duplicate_items_ambiguous():
    snapshot = SimpleNamespace(
        views={
            "v_current_training_plans": (
                {
                    "id": 7,
                    "plan_start_local_date": "2026-08-10",
                    "plan_end_local_date": "2026-08-16",
                },
            ),
            "v_training_plan_items": (
                {
                    "training_plan_id": 7,
                    "local_date": "2026-08-13",
                    "activity_kind": "rest",
                    "prescription_json": "{}",
                },
                {
                    "training_plan_id": 7,
                    "local_date": "2026-08-13",
                    "activity_kind": "running",
                    "prescription_json": "{}",
                },
            ),
        }
    )
    assert _today_plan_binding(snapshot, "2026-08-13") == ("ambiguous", None)
