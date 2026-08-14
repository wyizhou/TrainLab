"""A3-23 provider-side cross-layer interface compatibility evidence.

These tests exercise only public DTOs and pure quality-gate inputs.  They do
not invoke another layer's implementation, SQLite production database, Gmail,
or a provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analysis.contracts import (
    AnalysisContractError,
    AnalysisDelivery,
    AnalysisReceipt,
    AnalysisRequest,
)
from src.analysis.quality_gate import QualityGate, QualityGateRequest
from src.mail_agent.contracts import MailRequest
from src.resources import resource_bytes

ROOT = Path(__file__).resolve().parents[1]


def _analysis_request(mode: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "mode": mode,
        "subject_id": "subject_a",
        "invocation_id": "invocation_a",
        "run_key": None,
        "summary_local_date": None,
        "advice_local_date": None,
        "as_of_local_date": None,
        "plan_id": None,
        "reason_event_id": None,
        "effective_local_date": None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
        "requested_at_utc": "2026-07-26T00:00:00Z",
    }
    value.update(overrides)
    return value


def test_frozen_layer_snapshot_has_no_retired_scheduler_contract() -> None:
    """The source project retains only the four active product layers."""
    manifest = json.loads(resource_bytes("contracts/frozen_layer_contracts.json"))
    assert all("orchestration" not in key for key in manifest["contract_hashes"])
    assert len(manifest["contract_hashes"]) == 4


def test_l2_quality_gate_accepts_only_bounded_stable_snapshot_input() -> None:
    """Collection facts reach L3 only through the immutable stable-snapshot DTO."""
    result = QualityGate().evaluate(
        QualityGateRequest(
            "daily_summary", 1, "2026-07-25", "2026-07-25", "2026-07-26T00:00:00Z"
        ),
        object(),  # type: ignore[arg-type]  # deliberate non-DTO boundary probe
    )
    assert result.state == "blocked"
    assert result.next_action == "repair_data"
    assert [reason.code for reason in result.blockers] == ["snapshot_malformed"]


def test_l4_reason_event_handoff_is_revise_plan_only_and_mail_cannot_deliver_analysis() -> (
    None
):
    """L4 supplies a reason-event reference; L3 owns plan delivery end to end."""
    revision = AnalysisRequest.from_dict(
        _analysis_request(
            "revise_plan",
            plan_id="41",
            reason_event_id="91",
            effective_local_date="2026-07-27",
        )
    )
    assert revision.plan_id == "41" and revision.reason_event_id == "91"
    with pytest.raises(AnalysisContractError):
        AnalysisRequest.from_dict(
            _analysis_request(
                "revise_plan", plan_id="41", reason_event_id="91", delivery_id="501"
            )
        )

    # M4 may reference accepted analysis artifacts while processing inbound mail,
    # but its delivery modes accept only M4 response/delivery identifiers.
    inbound = MailRequest(
        "process",
        1,
        "mail-invocation",
        "2026-07-26T00:00:00Z",
        mail_message_ids=("message-1",),
        dependency_analysis_artifact_ids=("artifact-1",),
    )
    assert inbound.dependency_analysis_artifact_ids == ("artifact-1",)
    with pytest.raises(
        ValueError, match="mail_delivery_ids_not_allowed_for_deliver_response"
    ):
        MailRequest(
            "deliver_response",
            1,
            "mail-invocation",
            "2026-07-26T00:00:00Z",
            mail_response_artifact_ids=("mail-response-1",),
            mail_delivery_ids=("501",),
        )
    assert "analysis_delivery_id" not in MailRequest.__dataclass_fields__


@pytest.mark.parametrize("mode", ["retry_delivery", "reconcile_delivery"])
def test_delivery_recovery_is_exact_id_only_and_receipt_preserves_status(
    mode: str,
) -> None:
    """A manual delivery recovery remains exact-id only."""
    request = AnalysisRequest.from_dict(_analysis_request(mode, delivery_id="501"))
    assert request.delivery_id == "501"
    with pytest.raises(AnalysisContractError):
        AnalysisRequest.from_dict(
            _analysis_request(mode, delivery_id="501", artifact_id="101")
        )

    receipt = AnalysisReceipt(
        run_key=f"analysis:subject_a:{mode}:501:invocation_a",
        invocation_id="invocation_a",
        mode=mode,
        status="partial",
        started_at_utc="2026-07-26T00:00:00Z",
        completed_at_utc="2026-07-26T00:01:00Z",
        delivery=AnalysisDelivery("501", "delivery_unknown", ("101",)),
        next_action="reconcile_delivery",
    )
    receipt.validate()
    assert receipt.delivery is not None
    assert (receipt.delivery.delivery_id, receipt.delivery.status) == (
        "501",
        "delivery_unknown",
    )
