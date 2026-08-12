"""Isolated daily/weekly workflow contracts with repeat-safe fake effects."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest
from jsonschema import Draft202012Validator

from trainlab.orchestration.analysis_workflows import (
    AnalysisWorkflowRequest,
    AnalysisWorkflowResult,
    AnalysisWorkflowStep,
)
from trainlab.orchestration.application import OrchestrationTool
from trainlab.orchestration.contracts import WorkflowReceipt, WorkflowRequest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / "harness/schemas" / name).read_text(encoding="utf-8"))
    )


class _Subjects:
    def is_active(self, subject_id: str) -> bool:
        return subject_id == "synthetic-subject"

    def workflow_identity(self, subject_id: str) -> str:
        assert subject_id == "synthetic-subject"
        return "1"


class _ReceiptStore:
    """A disposable receipt projection: a repeated receipt cannot add state."""

    def __init__(self) -> None:
        self.by_key: dict[str, dict[str, object]] = {}

    def record_orchestration_receipt(
        self, _request: WorkflowRequest, receipt: WorkflowReceipt
    ) -> None:
        value = receipt.as_json_dict()
        prior = self.by_key.setdefault(str(value["workflow_key"]), value)
        assert prior == value


class _IdempotentAnalysis:
    """Synthetic lower layer whose stable workflow key is its effect key."""

    def __init__(self) -> None:
        self.effects: dict[str, AnalysisWorkflowResult] = {}

    def execute(self, request: AnalysisWorkflowRequest) -> AnalysisWorkflowResult:
        key = request.workflow_key
        if key not in self.effects:
            self.effects[key] = AnalysisWorkflowResult(
                key,
                "succeeded",
                request.logical_local_date,
                "synthetic-snapshot",
                "ready",
                (
                    AnalysisWorkflowStep(
                        "analysis",
                        "analysis",
                        "daily",
                        "synthetic-analysis-invocation",
                        "succeeded",
                        "a" * 64,
                    ),
                ),
                "none",
                None,
            )
        return self.effects[key]


def _request(kind: str) -> WorkflowRequest:
    return WorkflowRequest(
        cast(Literal["morning", "weekly", "mail", "health_check"], kind),
        "synthetic-subject",
        "2026-08-03",
        f"integration-{kind}-001",
        "scheduled",
        None,
        (),
        "2026-08-03T01:00:00Z",
        "2026-08-03T00:00:00Z",
    )


@pytest.mark.parametrize("kind", ("morning", "weekly"))
def test_daily_and_weekly_workflows_validate_and_repeat_without_duplicate_effect(
    kind: str,
) -> None:
    request = _request(kind)
    # Monday is required for the current weekly production contract.
    assert request.logical_local_date == "2026-08-03"
    assert not list(
        _validator("orchestration_workflow_request.schema.json").iter_errors(
            request.as_json_dict()
        )
    )

    store, analysis = _ReceiptStore(), _IdempotentAnalysis()
    tool = OrchestrationTool(
        clock=lambda: NOW,
        subject_authorizer=_Subjects(),
        receipt_store=store,
        **({"morning": analysis} if kind == "morning" else {"weekly": analysis}),
    )
    first, second = tool.execute(request), tool.execute(request)

    assert first.as_json_dict() == second.as_json_dict()
    assert not list(
        _validator("orchestration_workflow_receipt.schema.json").iter_errors(
            first.as_json_dict()
        )
    )
    assert len(store.by_key) == len(analysis.effects) == 1
    assert first.status == "succeeded"
