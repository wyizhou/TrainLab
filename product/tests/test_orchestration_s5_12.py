from trainlab.orchestration.delivery_recovery import plan_analysis_delivery_recovery


def receipt(status: str, *, outer: str = "partial") -> dict[str, object]:
    return {"mode": "daily", "status": outer, "delivery": {"delivery_id": "41", "status": status}}


def test_analysis_recovery_is_delivery_only_and_unknown_reconciles() -> None:
    unknown = plan_analysis_delivery_recovery(receipt("delivery_unknown"), subject_id="subject-1", invocation_id="recover-41")
    assert unknown.call is not None
    assert (unknown.action, unknown.call.layer, unknown.call.mode, unknown.call.delivery_id) == ("reconcile_delivery", "analysis", "reconcile_delivery", "41")
    pending = plan_analysis_delivery_recovery(receipt("pending"), subject_id="subject-1", invocation_id="recover-41")
    assert (pending.action, pending.call.mode) == ("retry_delivery", "retry_delivery")  # type: ignore[union-attr]


def test_analysis_recovery_refuses_missing_or_rejected_delivery() -> None:
    assert plan_analysis_delivery_recovery({"mode": "daily"}, subject_id="subject-1", invocation_id="x").action == "attention_required"
    assert plan_analysis_delivery_recovery(receipt("failed", outer="rejected"), subject_id="subject-1", invocation_id="x").action == "attention_required"
