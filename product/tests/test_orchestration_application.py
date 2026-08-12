from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trainlab.orchestration.analysis_workflows import (
    AnalysisWorkflowResult,
    AnalysisWorkflowStep,
)
from trainlab.orchestration.application import (
    HealthWorkflowOutcome,
    OrchestrationApplicationError,
    OrchestrationTool,
)
from trainlab.orchestration.contracts import WorkflowRequest
from trainlab.orchestration.mail_workflow import MailWorkflowOutcome
from trainlab.orchestration.subprocess_runner import DownstreamCall

NOW = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


class Subjects:
    def __init__(self, active: bool = True):
        self.active = active
        self.calls = []

    def is_active(self, subject_id):
        self.calls.append(subject_id)
        return self.active

    def workflow_identity(self, subject_id):
        return "7"


class Store:
    def __init__(self, fail: bool = False):
        self.rows = []
        self.fail = fail

    def record_orchestration_receipt(self, request, receipt):
        if self.fail:
            raise RuntimeError("email body should never surface")
        self.rows.append((request, receipt))


class RetryAuthorizer:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.requests = []

    def permits_operator_retry(self, request):
        self.requests.append(request)
        return self.allowed


class Analysis:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return AnalysisWorkflowResult(
            request.workflow_key,
            "succeeded",
            request.logical_local_date,
            None,
            "ready",
            (
                AnalysisWorkflowStep(
                    "daily", "analysis", "daily", "inv-daily", "succeeded", "a" * 64
                ),
            ),
            "none",
            None,
        )


class Mail:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        call = DownstreamCall(
            "mail",
            "run",
            kwargs["invocation_id"],
            None,
            subject_id=kwargs["subject_id"],
            max_items=kwargs["max_items"],
            deadline_seconds=kwargs["deadline_seconds"],
        )
        return MailWorkflowOutcome("succeeded", "none", (call,), ("b" * 64,))


class Health:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return HealthWorkflowOutcome("succeeded", "none")


def request(
    kind="morning", *, subject="subject-7", logical="2026-07-27", trigger="scheduled"
):
    if kind == "health_check":
        subject, logical = None, None
    if kind == "mail":
        logical = None
    return WorkflowRequest(
        kind,
        subject,
        logical,
        f"invoke-{kind}",
        trigger,
        None,
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )


def tool(**kwargs):
    return OrchestrationTool(
        clock=lambda: NOW,
        subject_authorizer=Subjects(),
        receipt_store=Store(),
        **kwargs,
    )


def test_morning_routes_only_to_injected_analysis_and_persists_data_free_receipt() -> (
    None
):
    analysis, store = Analysis(), Store()
    receipt = OrchestrationTool(
        clock=lambda: NOW,
        subject_authorizer=Subjects(),
        receipt_store=store,
        morning=analysis,
    ).execute(request())
    assert receipt.status == "succeeded" and receipt.workflow_kind == "morning"
    assert analysis.requests[0].workflow_kind == "morning"
    assert receipt.steps[0].receipt_sha256 == "a" * 64
    assert store.rows == [(request(), receipt)]
    assert receipt.workflow_key == "morning:7:2026-07-27"


def test_weekly_requires_monday_and_routes_to_monday_adapter() -> None:
    weekly = Analysis()
    monday = WorkflowRequest(
        "weekly",
        "subject-7",
        "2026-07-27",
        "invoke-weekly",
        "scheduled",
        None,
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    receipt = tool(weekly=weekly).execute(monday)
    assert (
        receipt.status == "succeeded" and weekly.requests[0].workflow_kind == "monday"
    )
    invalid = request("weekly", logical="2026-07-26")
    assert (
        tool(weekly=Analysis()).execute(invalid).errors[0]["code"]
        == "orchestration_request_invalid"
    )


@pytest.mark.parametrize(
    ("kind", "logical"),
    (("morning", "2026-07-26"), ("weekly", "2026-07-20")),
)
def test_operator_retry_can_preserve_an_earlier_logical_date(
    kind: str, logical: str
) -> None:
    analysis = Analysis()
    retry_authorizer = RetryAuthorizer()
    retry = WorkflowRequest(
        kind,
        "subject-7",
        logical,
        f"retry-{kind}",
        "manual",
        "41",
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    adapter = tool(
        operator_retry_authorizer=retry_authorizer,
        **({"morning": analysis} if kind == "morning" else {"weekly": analysis}),
    )

    receipt = adapter.execute(retry)

    assert receipt.status == "succeeded"
    assert receipt.workflow_key == f"manual:{kind}:retry-{kind}"
    assert analysis.requests[0].logical_local_date == logical
    assert retry_authorizer.requests == [retry]

    unparented = WorkflowRequest(
        kind,
        "subject-7",
        logical,
        f"rerun-{kind}",
        "manual",
        None,
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    rejected = tool(
        **({"morning": Analysis()} if kind == "morning" else {"weekly": Analysis()})
    ).execute(unparented)
    assert rejected.errors[0]["code"] == "orchestration_request_invalid"


def test_untrusted_parent_is_rejected_before_analysis_execution() -> None:
    analysis = Analysis()
    retry = WorkflowRequest(
        "morning",
        "subject-7",
        "2026-07-27",
        "retry-forged-parent",
        "manual",
        "999",
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )

    receipt = tool(
        operator_retry_authorizer=RetryAuthorizer(False), morning=analysis
    ).execute(retry)

    assert receipt.status == "failed"
    assert receipt.errors[0]["code"] == "orchestration_request_invalid"
    assert analysis.requests == []


def test_mail_uses_only_fixed_limits_and_numeric_subject() -> None:
    mail = Mail()
    receipt = tool(mail=mail).execute(request("mail", subject="7"))
    assert receipt.status == "succeeded"
    assert mail.calls == [
        {
            "subject_id": 7,
            "invocation_id": "invoke-mail",
            "max_items": 100,
            "deadline_seconds": 120,
        }
    ]
    rejected = tool(mail=mail).execute(request("mail", subject="not-a-number"))
    assert rejected.errors[0]["code"] == "orchestration_request_invalid"


def test_mail_lock_contention_is_persisted_as_deferred_not_failed() -> None:
    retry_at = "2026-07-27T00:05:00Z"

    class DeferredMail:
        def execute(self, **kwargs):
            call = DownstreamCall(
                "mail",
                "run",
                kwargs["invocation_id"],
                None,
                subject_id=kwargs["subject_id"],
                max_items=kwargs["max_items"],
                deadline_seconds=kwargs["deadline_seconds"],
            )
            return MailWorkflowOutcome(
                "deferred",
                "continue_poll",
                (call,),
                ("c" * 64,),
                next_retry_at_utc=retry_at,
            )

    receipt = tool(mail=DeferredMail()).execute(request("mail", subject="7"))
    assert receipt.status == "deferred"
    assert receipt.next_retry_at_utc == retry_at
    assert receipt.steps[0].status == "deferred"
    assert receipt.steps[0].receipt_sha256 == "c" * 64
    assert receipt.errors == ()


def test_health_requires_global_identity_and_injected_adapter() -> None:
    health = Health()
    receipt = tool(health_check=health).execute(request("health_check"))
    assert receipt.status == "succeeded" and health.requests
    assert len(receipt.steps) == 1
    assert receipt.steps[0].step_id == "health_check"
    assert receipt.steps[0].status == "succeeded"
    assert receipt.steps[0].layer == "orchestration"
    assert len(receipt.steps[0].receipt_sha256 or "") == 64
    interval = WorkflowRequest(
        "health_check",
        None,
        None,
        "host-7:20260727T000000.123456Z",
        "scheduled",
        None,
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    assert tool(health_check=health).execute(interval).status == "succeeded"
    bad = WorkflowRequest(
        "health_check",
        "7",
        None,
        "invoke-health",
        "scheduled",
        None,
        (),
        "2026-07-27T01:00:00Z",
        "2026-07-27T00:00:00Z",
    )
    assert (
        tool(health_check=health).execute(bad).errors[0]["code"]
        == "orchestration_request_invalid"
    )


@pytest.mark.parametrize("kind", ["morning", "weekly", "mail", "health_check"])
def test_missing_required_adapter_fails_closed(kind: str) -> None:
    supplied = (
        WorkflowRequest(
            "weekly",
            "subject-7",
            "2026-07-27",
            "invoke-weekly",
            "scheduled",
            None,
            (),
            "2026-07-27T01:00:00Z",
            "2026-07-27T00:00:00Z",
        )
        if kind == "weekly"
        else request(kind, subject="7" if kind == "mail" else "subject-7")
    )
    receipt = tool().execute(supplied)
    assert receipt.status == "failed"
    assert receipt.errors[0]["code"] == "orchestration_dependency_missing"


def test_inactive_subject_and_invalid_time_are_rejected_without_provider_call() -> None:
    analysis = Analysis()
    inactive = OrchestrationTool(
        clock=lambda: NOW,
        subject_authorizer=Subjects(False),
        receipt_store=Store(),
        morning=analysis,
    )
    assert (
        inactive.execute(request()).errors[0]["code"]
        == "orchestration_subject_inactive"
    )
    invalid = request()
    invalid = WorkflowRequest(
        *(
            (*invalid.__dict__.values(),)
            if False
            else (
                "morning",
                "subject-7",
                "2026-07-27",
                "invoke",
                "scheduled",
                None,
                (),
                "2026-07-27T01:00:00Z",
                "bad",
            )
        )
    )
    assert (
        tool(morning=analysis).execute(invalid).errors[0]["code"]
        == "orchestration_request_invalid"
    )
    assert not analysis.requests


def test_exception_and_store_failure_are_sanitized() -> None:
    class Bad:
        def execute(self, request):
            raise RuntimeError("token=secret private body")

    receipt = tool(morning=Bad()).execute(request())
    assert receipt.errors[0]["code"] == "orchestration_execution_failed"
    assert "secret" not in str(receipt.as_json_dict())
    receipt = OrchestrationTool(
        clock=lambda: NOW,
        subject_authorizer=Subjects(),
        receipt_store=Store(True),
        morning=Analysis(),
    ).execute(request())
    assert receipt.errors[0]["code"] == "orchestration_receipt_persistence_failed"


def test_safe_downstream_failure_code_reaches_workflow_receipt() -> None:
    class FailedAnalysis:
        def execute(self, request):
            return AnalysisWorkflowResult(
                request.workflow_key,
                "failed",
                request.logical_local_date,
                None,
                "blocked",
                (
                    AnalysisWorkflowStep(
                        "quality",
                        "garmin",
                        "audit",
                        "inv-audit",
                        "failed",
                        None,
                        error_code="receipt_schema_invalid",
                    ),
                ),
                "operator_review",
                None,
                "receipt_schema_invalid",
            )

    receipt = tool(morning=FailedAnalysis()).execute(request())
    assert receipt.status == "failed"
    assert receipt.errors[0]["code"] == "receipt_schema_invalid"


def test_non_contract_request_type_raises_before_any_side_effect() -> None:
    with pytest.raises(OrchestrationApplicationError):
        tool(morning=Analysis()).execute(object())  # type: ignore[arg-type]
