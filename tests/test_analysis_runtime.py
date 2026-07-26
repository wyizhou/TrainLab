from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from trainlab import cli
from trainlab.analysis import runtime
from trainlab.analysis.contracts import AnalysisReceipt


def _receipt(status: str = "partial") -> AnalysisReceipt:
    return AnalysisReceipt(
        run_key="analysis:active_subject:daily:2026-07-25:invocation",
        invocation_id="invocation",
        mode="daily",
        status=status,  # type: ignore[arg-type]
        started_at_utc="2026-07-26T00:00:00Z",
        completed_at_utc="2026-07-26T00:00:01Z",
    )


def test_analysis_only_bypasses_legacy_runtime_and_prints_only_receipt(monkeypatch, capsys):
    calls: list[tuple[str, object]] = []

    def forbidden(*_args: object, **_kwargs: object):
        raise AssertionError("legacy runtime must not be called")

    monkeypatch.setattr(cli, "load_settings", forbidden)
    monkeypatch.setattr(cli, "connect", forbidden)
    monkeypatch.setattr(cli, "run_analysis", forbidden)
    monkeypatch.setattr(runtime, "run_analysis_only", lambda **kwargs: calls.append(("run", kwargs)) or _receipt())

    assert cli.main(["run", "--slot", "morning", "--analysis-only", "--invocation-id", "invocation"]) == 10
    assert calls == [("run", {"invocation_id": "invocation", "summary_date": None})]
    assert json.loads(capsys.readouterr().out)["status"] == "partial"


@pytest.mark.parametrize("argv", [
    ["run", "--slot", "evening", "--analysis-only", "--invocation-id", "invocation"],
    ["run", "--slot", "morning", "--analysis-only"],
    ["run", "--slot", "morning", "--analysis-only", "--invocation-id", "invocation", "--at", "2026-07-26T00:00:00Z"],
    ["run", "--slot", "morning", "--summary-date", "2026-07-25"],
    ["run", "--slot", "morning", "--invocation-id", "invocation"],
])
def test_analysis_only_validates_before_legacy_loading(monkeypatch, argv):
    monkeypatch.setattr(cli, "load_settings", lambda: (_ for _ in ()).throw(AssertionError("legacy settings loaded")))
    with pytest.raises(SystemExit, match="2"):
        cli.main(argv)


def test_daily_request_defaults_to_singapore_yesterday_and_next_advice_day():
    request = runtime.build_daily_request(
        invocation_id="invocation",
        subject_id="default",
        summary_date=None,
        now=datetime(2026, 7, 26, 1, 0, tzinfo=UTC),
    )
    assert request.summary_local_date == "2026-07-25"
    assert request.advice_local_date == "2026-07-26"


def test_daily_request_rejects_non_date_summary():
    with pytest.raises(ValueError, match="analysis_summary_date_invalid"):
        runtime.build_daily_request(subject_id="default", invocation_id="invocation", summary_date="2026-7-26")


def test_daily_request_rejects_unsafe_subject_id():
    with pytest.raises(ValueError, match="analysis_subject_id_invalid"):
        runtime.build_daily_request(subject_id="default;drop", invocation_id="invocation", summary_date="2026-07-25")


def test_daily_request_rejects_today_or_future_summary_before_runtime_setup():
    now = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)
    for summary_date in ("2026-07-26", "2026-07-27"):
        with pytest.raises(ValueError, match="analysis_summary_date_must_be_before_today"):
            runtime.build_daily_request(subject_id="default", invocation_id="invocation", summary_date=summary_date, now=now)


@pytest.mark.parametrize("rows", [[], [("default",), ("second",)]])
def test_active_subject_query_fails_closed_when_not_unique(rows):
    class Connection:
        def execute(self, _sql):
            return rows

    with pytest.raises(ValueError, match="analysis_active_subject_not_unique"):
        runtime._active_subject_key(Connection())


def test_unique_active_subject_is_used_for_runtime_wiring(monkeypatch):
    class Connection:
        def __init__(self): self.queries = []; self.closed = False
        def execute(self, sql): self.queries.append(sql); return [("default",)]
        def close(self): self.closed = True

    connection = Connection()
    foundation = SimpleNamespace(database_path=Path("/project/state/foundation/data.db"))
    config = SimpleNamespace(lock_path=Path("/project/state/locks/analysis.lock"))
    monkeypatch.setattr(runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation))
    monkeypatch.setattr(runtime, "FoundationTool", lambda _foundation: SimpleNamespace(_connect=lambda _path: connection))
    monkeypatch.setattr(runtime, "load_analysis_config", lambda _root, _path: config)
    monkeypatch.setattr(runtime, "AnalysisRunRepository", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisRunCoordinator", lambda _repository, _locks: object())
    monkeypatch.setattr(runtime, "SubjectLockManager", lambda _path, **_kwargs: object())
    monkeypatch.setattr(runtime, "StableViewRepository", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisCodexRunner", lambda _config: object())
    monkeypatch.setattr(runtime, "AnalysisPublisher", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisDeliveryFactory", lambda _connection: object())

    from trainlab.analysis import daily
    captured = {}
    class Route:
        def __init__(self, **kwargs): captured.update(kwargs)
        def execute(self, request):
            captured["request"] = request
            return _receipt()
    monkeypatch.setattr(daily, "DailyRoute", Route)

    receipt = runtime.run_analysis_only(invocation_id="invocation", summary_date="2026-07-25", root=Path("/project"))
    assert receipt.status == "partial"
    assert captured["request"].subject_id == "default"
    assert connection.queries == ["SELECT subject_key FROM data_subjects WHERE is_active=1 ORDER BY id"]
    assert connection.closed
