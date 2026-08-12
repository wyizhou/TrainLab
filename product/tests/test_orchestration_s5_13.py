from trainlab.orchestration.delivery_recovery import plan_mail_delivery_recovery


def receipt(*, action: str = "none", status: str = "partial", sent: int = 0) -> dict[str, object]:
    return {"mode": "deliver_response", "status": status, "next_action": action, "mail_response_artifact_ids": ["61"], "mail_delivery_ids": ["71"], "counts": {"deliveries_sent": sent, "deliveries_already_sent": 0}}


def test_mail_recovery_uses_exact_response_or_delivery_only() -> None:
    retry = plan_mail_delivery_recovery(receipt(), subject_id=1, invocation_id="recover-71")
    assert retry.call is not None
    assert (retry.action, retry.call.layer, retry.call.mode, retry.call.mail_response_artifact_id) == ("retry_delivery", "mail", "deliver_response", "61")
    unknown = plan_mail_delivery_recovery(receipt(action="reconcile_delivery"), subject_id=1, invocation_id="recover-71")
    assert (unknown.action, unknown.call.mode, unknown.call.delivery_id) == ("reconcile_delivery", "reconcile", "71")  # type: ignore[union-attr]


def test_mail_recovery_detects_sent_and_identity_mismatch() -> None:
    assert plan_mail_delivery_recovery(receipt(sent=1), subject_id=1, invocation_id="x").action == "complete"
    assert plan_mail_delivery_recovery(receipt(), subject_id=1, invocation_id="x", delivery_id="other").action == "attention_required"
