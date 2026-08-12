"""S5-12/S5-13 exact delivery-only recovery call planning.

No function here runs analysis, processes mail, reads a body, or contacts a
provider.  It constructs the narrow owner-layer call which an executor may run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .subprocess_runner import DownstreamCall


DeliveryAction = Literal["complete", "retry_delivery", "reconcile_delivery", "attention_required"]


@dataclass(frozen=True, slots=True)
class DeliveryRecoveryDecision:
    action: DeliveryAction
    reason: str
    call: DownstreamCall | None


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name}_required")
    return value


def _analysis_common(*, subject_id: str, invocation_id: str) -> None:
    if type(subject_id) is not str or not subject_id:
        raise ValueError("recovery_subject_id_invalid")
    _id(invocation_id, "recovery_invocation_id")


def _mail_common(*, subject_id: int, invocation_id: str) -> None:
    if type(subject_id) is not int or subject_id <= 0:
        raise ValueError("recovery_subject_id_invalid")
    _id(invocation_id, "recovery_invocation_id")


def plan_analysis_delivery_recovery(
    receipt: Mapping[str, object], *, subject_id: str, invocation_id: str,
    delivery_id: str | None = None,
) -> DeliveryRecoveryDecision:
    """Recover one accepted analysis delivery, never daily/weekly/revise-plan."""
    _analysis_common(subject_id=subject_id, invocation_id=invocation_id)
    if not isinstance(receipt, Mapping) or receipt.get("mode") not in {"daily", "weekly", "revise_plan", "retry_delivery", "reconcile_delivery"}:
        return DeliveryRecoveryDecision("attention_required", "analysis_receipt_invalid", None)
    delivery = receipt.get("delivery")
    if not isinstance(delivery, Mapping):
        return DeliveryRecoveryDecision("attention_required", "analysis_delivery_missing", None)
    exact_id = delivery_id or delivery.get("delivery_id")
    if type(exact_id) is not str or not exact_id or (delivery_id is not None and delivery.get("delivery_id") != delivery_id):
        return DeliveryRecoveryDecision("attention_required", "analysis_delivery_identity_invalid", None)
    status = delivery.get("status")
    if status in {"sent", "already_sent"}:
        return DeliveryRecoveryDecision("complete", "analysis_delivery_complete", None)
    if status == "delivery_unknown":
        return DeliveryRecoveryDecision("reconcile_delivery", "analysis_delivery_unknown", DownstreamCall("analysis", "reconcile_delivery", invocation_id, None, subject_id=subject_id, delivery_id=exact_id))
    if status in {"pending", "failed"} and receipt.get("status") != "rejected":
        return DeliveryRecoveryDecision("retry_delivery", "analysis_delivery_retry", DownstreamCall("analysis", "retry_delivery", invocation_id, None, subject_id=subject_id, delivery_id=exact_id))
    return DeliveryRecoveryDecision("attention_required", "analysis_delivery_not_recoverable", None)


def plan_mail_delivery_recovery(
    receipt: Mapping[str, object], *, subject_id: int, invocation_id: str,
    response_artifact_id: str | None = None, delivery_id: str | None = None,
) -> DeliveryRecoveryDecision:
    """Recover one accepted mail response using only its response/delivery IDs."""
    _mail_common(subject_id=subject_id, invocation_id=invocation_id)
    if not isinstance(receipt, Mapping) or receipt.get("mode") not in {"process", "deliver_response", "reconcile", "run"}:
        return DeliveryRecoveryDecision("attention_required", "mail_receipt_invalid", None)
    response_ids = receipt.get("mail_response_artifact_ids")
    delivery_ids = receipt.get("mail_delivery_ids")
    if type(response_ids) is not list or type(delivery_ids) is not list:
        return DeliveryRecoveryDecision("attention_required", "mail_delivery_identity_missing", None)
    response = response_artifact_id or (response_ids[0] if len(response_ids) == 1 else None)
    delivery = delivery_id or (delivery_ids[0] if len(delivery_ids) == 1 else None)
    if type(response) is not str or not response or (response_artifact_id is not None and response not in response_ids):
        return DeliveryRecoveryDecision("attention_required", "mail_response_identity_invalid", None)
    if type(delivery) is not str or not delivery or (delivery_id is not None and delivery not in delivery_ids):
        return DeliveryRecoveryDecision("attention_required", "mail_delivery_identity_invalid", None)
    action = receipt.get("next_action")
    counts = receipt.get("counts")
    if type(counts) is dict and (counts.get("deliveries_sent", 0) or counts.get("deliveries_already_sent", 0)):
        return DeliveryRecoveryDecision("complete", "mail_delivery_complete", None)
    if action == "reconcile_delivery":
        return DeliveryRecoveryDecision("reconcile_delivery", "mail_delivery_unknown", DownstreamCall("mail", "reconcile", invocation_id, None, subject_id=subject_id, delivery_id=delivery))
    if receipt.get("status") == "rejected":
        return DeliveryRecoveryDecision("attention_required", "mail_delivery_rejected", None)
    return DeliveryRecoveryDecision("retry_delivery", "mail_delivery_retry", DownstreamCall("mail", "deliver_response", invocation_id, None, subject_id=subject_id, mail_response_artifact_id=response))
