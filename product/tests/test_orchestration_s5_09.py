from datetime import UTC, datetime

from trainlab.orchestration.analysis_workflows import AnalysisWorkflowRequest, SundayWorkflowService
from trainlab.orchestration.subprocess_runner import DownstreamResult


class Queue:
    def __init__(self, receipts): self.receipts, self.calls = list(receipts), []
    def run(self, call):
        self.calls.append(call)
        return DownstreamResult("accepted", None, self.receipts.pop(0), "a" * 64, "b" * 64, 0)


def g(mode, status="succeeded"):
    return {"mode": mode, "status": status, "run_id": "single-snapshot", "coverage_state": "complete", "open_gap_count": 0, "counts": {"not_available": 0, "not_enabled": 0}, "next_retry_at_utc": None}


def a(mode, status="succeeded"):
    return {"mode": mode, "status": status, "analysis_run_id": mode + "-run", "next_retry_at_utc": "2026-07-26T00:10:00Z" if status == "partial" else None}


def request():
    return AnalysisWorkflowRequest("sunday:7:2026-07-26", "subject-7", "2026-07-26", datetime(2026, 7, 25, 23, tzinfo=UTC), "sunday")


def test_sunday_collects_once_then_daily_and_weekly_share_snapshot() -> None:
    current = g("snapshot"); current["coverage_state"] = "partial"
    queue = Queue([g("incremental"), current, g("audit"), a("daily"), a("weekly")])
    result = SundayWorkflowService(queue).execute(request())
    assert result.status == "succeeded" and result.collection_snapshot_id == "single-snapshot"
    assert [(item.layer, item.mode) for item in queue.calls] == [("garmin", "incremental"), ("garmin", "snapshot"), ("garmin", "audit"), ("analysis", "daily"), ("analysis", "weekly")]
    assert queue.calls[1].snapshot_local_date == "2026-07-26"
    assert queue.calls[-1].as_of_local_date == "2026-07-26"


def test_daily_failure_does_not_prevent_weekly_and_reentry_does_not_repeat_collection() -> None:
    queue = Queue([g("incremental"), g("snapshot"), g("audit"), a("daily", "partial"), a("weekly")])
    service = SundayWorkflowService(queue)
    result = service.execute(request())
    assert result.status == "deferred" and [item.mode for item in queue.calls] == ["incremental", "snapshot", "audit", "daily", "weekly"]
    # A terminal partial is intentionally not cached: durable S5-05 recovery,
    # rather than a new workflow, owns the exact downstream retry.
    assert len(service._completed) == 0


def test_collection_blocked_skips_both_analyses() -> None:
    queue = Queue([g("incremental"), g("snapshot"), g("audit", "deferred")])
    result = SundayWorkflowService(queue).execute(request())
    assert result.status == "deferred"
    assert [item.layer for item in queue.calls] == ["garmin", "garmin", "garmin"]
