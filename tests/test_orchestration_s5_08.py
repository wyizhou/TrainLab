from datetime import UTC, datetime

from trainlab.orchestration.analysis_workflows import AnalysisWorkflowRequest, MorningWorkflowService
from trainlab.orchestration.subprocess_runner import DownstreamResult


class Queue:
    def __init__(self, receipts): self.receipts, self.calls = list(receipts), []
    def run(self, call):
        self.calls.append(call)
        receipt = self.receipts.pop(0)
        return DownstreamResult("accepted", None, receipt, "a" * 64, "b" * 64, 0)


def garmin(mode, status="succeeded", coverage="complete", gaps=0):
    return {"mode": mode, "status": status, "run_id": "collection-1", "coverage_state": coverage, "open_gap_count": gaps, "counts": {"not_available": 0, "not_enabled": 0}, "next_retry_at_utc": None}


def analysis(mode, status="succeeded", retry=None):
    return {"mode": mode, "status": status, "next_retry_at_utc": retry, "analysis_run_id": "analysis-1"}


def request():
    return AnalysisWorkflowRequest("morning:7:2026-07-24", "subject-7", "2026-07-24", datetime(2026, 7, 23, 23, tzinfo=UTC))


def test_morning_uses_explicit_singapore_yesterday_and_today_once() -> None:
    audit = garmin("audit")
    audit["coverage_state"] = None
    queue = Queue([garmin("incremental"), audit, analysis("daily")])
    result = MorningWorkflowService(queue).execute(request())
    assert result.status == "succeeded"
    assert [(call.layer, call.mode) for call in queue.calls] == [("garmin", "incremental"), ("garmin", "audit"), ("analysis", "daily")]
    assert queue.calls[0].through_local_date == "2026-07-23"
    assert (queue.calls[-1].summary_local_date, queue.calls[-1].advice_local_date) == ("2026-07-23", "2026-07-24")
    assert MorningWorkflowService(queue).execute if False else True


def test_collection_coverage_remains_the_quality_authority() -> None:
    queue = Queue([
        garmin("incremental", coverage="partial"),
        garmin("audit", coverage=None),
        garmin("repair"),
        garmin("audit", coverage=None),
    ])
    result = MorningWorkflowService(queue).execute(request())
    assert result.status == "deferred" and result.next_action == "repair_data"
    assert [item.mode for item in queue.calls] == ["incremental", "audit", "repair", "audit"]


def test_blocked_quality_is_repaired_once_then_does_not_call_daily_when_still_blocked() -> None:
    queue = Queue([garmin("incremental"), garmin("audit", coverage="partial", gaps=1), garmin("repair"), garmin("audit", coverage="partial", gaps=1)])
    result = MorningWorkflowService(queue).execute(request())
    assert result.status == "deferred" and result.next_action == "repair_data"
    assert [item.mode for item in queue.calls] == ["incremental", "audit", "repair", "audit"]


def test_deferred_and_auth_do_not_call_quality_or_daily() -> None:
    retry = "2026-07-24T00:10:00Z"
    deferred = garmin("incremental", "deferred"); deferred["next_retry_at_utc"] = retry
    queue = Queue([deferred])
    assert MorningWorkflowService(queue).execute(request()).next_retry_at_utc == retry
    assert len(queue.calls) == 1
    queue = Queue([garmin("incremental", "auth_required")])
    assert MorningWorkflowService(queue).execute(request()).status == "attention_required"
    assert len(queue.calls) == 1


def test_completed_reentry_returns_same_result_without_second_artifact() -> None:
    queue = Queue([garmin("incremental"), garmin("audit"), analysis("daily")])
    service = MorningWorkflowService(queue)
    assert service.execute(request()).status == "succeeded"
    assert service.execute(request()).status == "succeeded"
    assert len(queue.calls) == 3
