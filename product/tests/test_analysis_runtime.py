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


def _weekly_receipt(status: str = "partial") -> AnalysisReceipt:
    return AnalysisReceipt(
        run_key="analysis:active_subject:weekly:2026-07-26:invocation",
        invocation_id="invocation",
        mode="weekly",
        status=status,  # type: ignore[arg-type]
        started_at_utc="2026-07-26T00:00:00Z",
        completed_at_utc="2026-07-26T00:00:01Z",
    )


def _revision_receipt(status: str = "partial") -> AnalysisReceipt:
    return AnalysisReceipt(
        run_key="analysis:active_subject:revise_plan:7:9:invocation",
        invocation_id="invocation",
        mode="revise_plan",
        status=status,  # type: ignore[arg-type]
        started_at_utc="2026-07-26T00:00:00Z",
        completed_at_utc="2026-07-26T00:00:01Z",
    )


def test_analysis_only_uses_only_its_current_runtime_and_prints_one_receipt(
    monkeypatch, capsys
):
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        runtime,
        "run_analysis_only",
        lambda **kwargs: calls.append(("run", kwargs)) or _receipt(),
    )

    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--invocation-id",
                "invocation",
            ]
        )
        == 10
    )
    assert calls == [
        ("run", {"invocation_id": "invocation", "summary_date": None, "deliver": False})
    ]
    assert json.loads(capsys.readouterr().out)["status"] == "partial"


@pytest.mark.parametrize(
    "argv",
    [
        [
            "run",
            "--slot",
            "evening",
            "--analysis-only",
            "--invocation-id",
            "invocation",
        ],
        ["run", "--slot", "morning", "--analysis-only"],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--at",
            "2026-07-26T00:00:00Z",
        ],
        ["run", "--slot", "morning", "--summary-date", "2026-07-25"],
        ["run", "--slot", "morning", "--invocation-id", "invocation"],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--retry-delivery",
            "0",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--retry-delivery",
            "1",
            "--deliver",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--reconcile-delivery",
            "1",
            "--summary-date",
            "2026-07-25",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--weekly",
            "--summary-date",
            "2026-07-25",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--as-of-date",
            "2026-07-26",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--retry-delivery",
            "1",
            "--weekly",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--revise-plan",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--plan-id",
            "7",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--revise-plan",
            "--plan-id",
            "7",
            "--reason-event-id",
            "9",
            "--weekly",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--revise-plan",
            "--plan-id",
            "0",
            "--reason-event-id",
            "9",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--retry-delivery",
            "1",
            "--revise-plan",
            "--plan-id",
            "7",
            "--reason-event-id",
            "9",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--resend-authorization",
            "user-confirmed-20260811",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--weekly",
            "--resend-authorization",
            "user-confirmed-20260811",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--weekly",
            "--as-of-date",
            "2026-08-10",
            "--deliver",
            "--resend-authorization",
            "user-confirmed-20260811",
        ],
        [
            "run",
            "--slot",
            "morning",
            "--analysis-only",
            "--invocation-id",
            "invocation",
            "--retry-delivery",
            "1",
            "--resend-authorization",
            "user-confirmed-20260811",
        ],
    ],
)
def test_analysis_only_rejects_invalid_invocations_before_runtime_call(argv):
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
        runtime.build_daily_request(
            subject_id="default", invocation_id="invocation", summary_date="2026-7-26"
        )


def test_daily_request_rejects_unsafe_subject_id():
    with pytest.raises(ValueError, match="analysis_subject_id_invalid"):
        runtime.build_daily_request(
            subject_id="default;drop",
            invocation_id="invocation",
            summary_date="2026-07-25",
        )


def test_daily_request_rejects_today_or_future_summary_before_runtime_setup():
    now = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)
    for summary_date in ("2026-07-26", "2026-07-27"):
        with pytest.raises(
            ValueError, match="analysis_summary_date_must_be_before_today"
        ):
            runtime.build_daily_request(
                subject_id="default",
                invocation_id="invocation",
                summary_date=summary_date,
                now=now,
            )


def test_weekly_request_uses_rolling_as_of_date_without_iso_week_assumption():
    request = runtime.build_weekly_request(
        subject_id="default",
        invocation_id="invocation",
        as_of_date=None,
        now=datetime(2026, 7, 26, 1, 0, tzinfo=UTC),
    )
    assert request.mode == "weekly"
    assert request.as_of_local_date == "2026-07-26"
    assert request.summary_local_date is None


def test_weekly_request_records_explicit_resend_authorization():
    request = runtime.build_weekly_request(
        subject_id="default",
        invocation_id="invocation",
        as_of_date="2026-07-20",
        resend_authorization_id="user-confirmed-20260811",
    )
    assert request.resend_authorization_id == "user-confirmed-20260811"


def test_weekly_request_rejects_future_as_of_date():
    with pytest.raises(ValueError, match="analysis_weekly_as_of_date_in_future"):
        runtime.build_weekly_request(
            subject_id="default",
            invocation_id="invocation",
            as_of_date="2026-07-27",
            now=datetime(2026, 7, 26, 1, 0, tzinfo=UTC),
        )


def test_plan_revision_request_keeps_optional_effective_date_for_event_resolution():
    request = runtime.build_plan_revision_request(
        subject_id="default",
        invocation_id="invocation",
        plan_id="7",
        reason_event_id="9",
        effective_date=None,
        now=datetime(2026, 7, 26, 1, 0, tzinfo=UTC),
    )
    assert request.mode == "revise_plan"
    assert request.plan_id == "7"
    assert request.reason_event_id == "9"
    assert request.effective_local_date is None


@pytest.mark.parametrize(
    "plan_id,reason_id,effective,code",
    [
        ("plan-7", "9", None, "analysis_plan_id_invalid"),
        ("7", "event-9", None, "analysis_reason_event_id_invalid"),
        ("7", "9", "2026-7-26", "analysis_plan_revision_effective_date_invalid"),
    ],
)
def test_plan_revision_request_rejects_ambiguous_identifiers_and_dates(
    plan_id: str, reason_id: str, effective: str | None, code: str
) -> None:
    with pytest.raises(ValueError, match=code):
        runtime.build_plan_revision_request(
            subject_id="default",
            invocation_id="invocation",
            plan_id=plan_id,
            reason_event_id=reason_id,
            effective_date=effective,
        )


@pytest.mark.parametrize("rows", [[], [("default",), ("second",)]])
def test_active_subject_query_fails_closed_when_not_unique(rows):
    class Connection:
        def execute(self, _sql):
            return rows

    with pytest.raises(ValueError, match="analysis_active_subject_not_unique"):
        runtime._active_subject_key(Connection())


def test_unique_active_subject_is_used_for_runtime_wiring(monkeypatch):
    class Connection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql):
            self.queries.append(sql)
            return [("default",)]

        def close(self):
            self.closed = True

    connection = Connection()
    foundation = SimpleNamespace(
        database_path=Path("/project/state/foundation/data.db")
    )
    config = SimpleNamespace(lock_path=Path("/project/state/locks/analysis.lock"))
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(
        runtime,
        "FoundationTool",
        lambda _foundation: SimpleNamespace(_connect=lambda _path: connection),
    )
    monkeypatch.setattr(runtime, "load_analysis_config", lambda _root, _path: config)
    monkeypatch.setattr(runtime, "AnalysisRunRepository", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisRunCoordinator", lambda _repository, _locks: object()
    )
    monkeypatch.setattr(
        runtime, "SubjectLockManager", lambda _path, **_kwargs: object()
    )
    monkeypatch.setattr(runtime, "StableViewRepository", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisCodexRunner", lambda _config: object())
    monkeypatch.setattr(runtime, "AnalysisPublisher", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisDeliveryFactory", lambda _connection: object()
    )

    from trainlab.analysis import daily

    captured = {}

    class Route:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self, request):
            captured["request"] = request
            return _receipt()

    monkeypatch.setattr(daily, "DailyRoute", Route)

    receipt = runtime.run_analysis_only(
        invocation_id="invocation", summary_date="2026-07-25", root=Path("/project")
    )
    assert receipt.status == "partial"
    assert captured["request"].subject_id == "default"
    assert connection.queries == [
        "SELECT subject_key FROM data_subjects WHERE is_active=1 ORDER BY id"
    ]
    assert connection.closed


def test_weekly_runtime_wires_the_weekly_route_and_closes_connection(monkeypatch):
    class Connection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql):
            self.queries.append(sql)
            return [("default",)]

        def close(self):
            self.closed = True

    connection = Connection()
    foundation = SimpleNamespace(
        database_path=Path("/project/state/foundation/data.db")
    )
    config = SimpleNamespace(lock_path=Path("/project/state/locks/analysis.lock"))
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(
        runtime,
        "FoundationTool",
        lambda _foundation: SimpleNamespace(_connect=lambda _path: connection),
    )
    monkeypatch.setattr(runtime, "load_analysis_config", lambda _root, _path: config)
    monkeypatch.setattr(runtime, "AnalysisRunRepository", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisRunCoordinator", lambda _repository, _locks: object()
    )
    monkeypatch.setattr(
        runtime, "SubjectLockManager", lambda _path, **_kwargs: object()
    )
    monkeypatch.setattr(runtime, "StableViewRepository", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisCodexRunner", lambda _config: object())
    monkeypatch.setattr(runtime, "AnalysisPublisher", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisDeliveryFactory", lambda _connection: object()
    )

    from trainlab.analysis import weekly

    captured = {}

    class Route:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self, request):
            captured["request"] = request
            return _weekly_receipt()

    monkeypatch.setattr(weekly, "WeeklyRoute", Route)
    receipt = runtime.run_weekly_analysis(
        invocation_id="invocation",
        as_of_date="2026-07-26",
        root=Path("/project"),
    )
    assert receipt.status == "partial"
    assert captured["request"].mode == "weekly"
    assert captured["request"].as_of_local_date == "2026-07-26"
    assert connection.closed


def test_current_weekly_correction_binds_current_artifacts_without_route_or_gateway(
    monkeypatch,
):
    class Connection:
        closed = False

        def execute(self, sql, _parameters=()):
            assert "analysis_artifacts" in sql
            return SimpleNamespace(
                fetchall=lambda: [
                    {
                        "id": 79,
                        "artifact_kind": "weekly_summary",
                        "generated_by_run_id": 9,
                    },
                    {
                        "id": 80,
                        "artifact_kind": "weekly_training_plan",
                        "generated_by_run_id": 9,
                    },
                ]
            )

        def close(self):
            self.closed = True

    connection = Connection()
    captured = {}

    class Factory:
        def create_pending(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                delivery_id=36,
                analysis_run_id=9,
                run_key="analysis:default:weekly:2026-08-10:correction",
                artifacts=(
                    SimpleNamespace(artifact_id=79),
                    SimpleNamespace(artifact_id=80),
                ),
            )

    foundation = SimpleNamespace(
        database_path=Path("/project/state/foundation/data.db")
    )
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(
        runtime,
        "FoundationTool",
        lambda _foundation: SimpleNamespace(_connect=lambda _path: connection),
    )
    monkeypatch.setattr(runtime, "_active_subject_key", lambda _connection: "default")
    monkeypatch.setattr(runtime, "_active_subject_id", lambda _connection: 1)
    monkeypatch.setattr(
        runtime, "AnalysisDeliveryFactory", lambda _connection: Factory()
    )
    receipt = runtime.run_current_weekly_correction(
        invocation_id="correction",
        as_of_date="2026-08-10",
        resend_authorization_id="user-confirmed-20260811",
        root=Path("/project"),
    )
    assert receipt.delivery is not None
    assert receipt.delivery.delivery_id == "36"
    assert receipt.delivery.artifact_ids == ("79", "80")
    assert captured["publish_receipt"] == {
        "run_id": 9,
        "artifact_ids": {"weekly_summary": 79, "weekly_training_plan": 80},
    }
    assert (
        captured["resend_authorization"].authorization_id == "user-confirmed-20260811"
    )
    assert connection.closed


def test_plan_revision_runtime_wires_route_and_closes_connection(monkeypatch):
    class Connection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql):
            self.queries.append(sql)
            return [("default",)]

        def close(self):
            self.closed = True

    connection = Connection()
    foundation = SimpleNamespace(
        database_path=Path("/project/state/foundation/data.db")
    )
    config = SimpleNamespace(lock_path=Path("/project/state/locks/analysis.lock"))
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(
        runtime,
        "FoundationTool",
        lambda _foundation: SimpleNamespace(_connect=lambda _path: connection),
    )
    monkeypatch.setattr(runtime, "load_analysis_config", lambda _root, _path: config)
    monkeypatch.setattr(runtime, "AnalysisRunRepository", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisRunCoordinator", lambda _repository, _locks: object()
    )
    monkeypatch.setattr(
        runtime, "SubjectLockManager", lambda _path, **_kwargs: object()
    )
    monkeypatch.setattr(runtime, "StableViewRepository", lambda _connection: object())
    monkeypatch.setattr(runtime, "AnalysisCodexRunner", lambda _config: object())
    monkeypatch.setattr(runtime, "AnalysisPublisher", lambda _connection: object())
    monkeypatch.setattr(
        runtime, "AnalysisDeliveryFactory", lambda _connection: object()
    )

    from trainlab.analysis import revise_plan

    captured = {}

    class Route:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self, request):
            captured["request"] = request
            return _revision_receipt()

    monkeypatch.setattr(revise_plan, "PlanRevisionRoute", Route)
    receipt = runtime.run_plan_revision_analysis(
        invocation_id="invocation",
        plan_id="7",
        reason_event_id="9",
        effective_date=None,
        root=Path("/project"),
    )
    assert receipt.status == "partial"
    assert captured["request"].mode == "revise_plan"
    assert captured["request"].effective_local_date is None
    assert captured["connection"] is connection
    assert connection.closed


def test_analysis_deliver_flag_and_recovery_route_stay_under_trainlab_run(
    monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        runtime,
        "run_analysis_only",
        lambda **kwargs: calls.append(("daily", kwargs)) or _receipt("succeeded"),
    )
    monkeypatch.setattr(
        runtime,
        "run_delivery_recovery",
        lambda **kwargs: calls.append(("recovery", kwargs)) or _receipt("succeeded"),
    )
    monkeypatch.setattr(
        runtime,
        "run_weekly_analysis",
        lambda **kwargs: (
            calls.append(("weekly", kwargs)) or _weekly_receipt("succeeded")
        ),
    )
    monkeypatch.setattr(
        runtime,
        "run_plan_revision_analysis",
        lambda **kwargs: (
            calls.append(("revision", kwargs)) or _revision_receipt("succeeded")
        ),
    )
    monkeypatch.setattr(
        runtime,
        "run_regeneration_analysis",
        lambda **kwargs: calls.append(("regenerate", kwargs)) or _receipt("succeeded"),
    )
    monkeypatch.setattr(
        runtime,
        "run_analysis_status",
        lambda **kwargs: calls.append(("status", kwargs)) or _receipt("succeeded"),
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--invocation-id",
                "one",
                "--deliver",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "daily",
        {"invocation_id": "one", "summary_date": None, "deliver": True},
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--invocation-id",
                "two",
                "--reconcile-delivery",
                "7",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "recovery",
        {"invocation_id": "two", "delivery_id": 7, "reconcile": True},
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--invocation-id",
                "three",
                "--weekly",
                "--as-of-date",
                "2026-07-26",
                "--deliver",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "weekly",
        {"invocation_id": "three", "as_of_date": "2026-07-26", "deliver": True},
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--invocation-id",
                "four",
                "--revise-plan",
                "--plan-id",
                "7",
                "--reason-event-id",
                "9",
                "--effective-date",
                "2026-07-26",
                "--deliver",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "revision",
        {
            "invocation_id": "four",
            "plan_id": "7",
            "reason_event_id": "9",
            "effective_date": "2026-07-26",
            "deliver": True,
        },
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--regenerate",
                "--artifact-id",
                "7",
                "--regenerate-reason",
                "explicit_user_request",
                "--invocation-id",
                "five",
                "--deliver",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "regenerate",
        {
            "invocation_id": "five",
            "artifact_id": "7",
            "reason_code": "explicit_user_request",
            "deliver": True,
        },
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--status",
                "--run-key",
                "analysis:active_subject:daily:2026-07-25:one",
            ]
        )
        == 0
    )
    assert calls[-1] == (
        "status",
        {"run_key": "analysis:active_subject:daily:2026-07-25:one"},
    )
    assert "recipient" not in capsys.readouterr().out


def test_cli_routes_authorized_weekly_correction_without_deliver(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        runtime,
        "run_weekly_analysis",
        lambda **kwargs: calls.append(kwargs) or _weekly_receipt("partial"),
    )
    assert (
        cli.main(
            [
                "run",
                "--slot",
                "morning",
                "--analysis-only",
                "--weekly",
                "--as-of-date",
                "2026-08-10",
                "--invocation-id",
                "correction",
                "--resend-authorization",
                "user-confirmed-20260811",
            ]
        )
        == 10
    )
    assert calls == [
        {
            "invocation_id": "correction",
            "as_of_date": "2026-08-10",
            "deliver": False,
            "resend_authorization_id": "user-confirmed-20260811",
        }
    ]
    assert json.loads(capsys.readouterr().out)["status"] == "partial"


def test_analysis_delivery_uses_the_shared_project_recipient_config(monkeypatch):
    captured = {}

    def recipient(root):
        captured["root"] = root
        return "configured@example.com"

    monkeypatch.setattr(runtime, "_recipient_email", recipient)
    monkeypatch.setattr(
        runtime,
        "GmailDeliveryGateway",
        lambda recipient, timeout_seconds: (
            captured.update(recipient=recipient, timeout=timeout_seconds) or object()
        ),
    )

    class Service:
        def __init__(self, repository, gateway):
            captured.update(repository=repository, gateway=gateway)

        def execute(self, delivery_id, mode):
            captured.update(delivery_id=delivery_id, mode=mode)
            return "delivered"

    monkeypatch.setattr(
        runtime, "AnalysisDeliveryRepository", lambda connection: connection
    )
    monkeypatch.setattr(runtime, "AnalysisDeliveryService", Service)
    config = SimpleNamespace(delivery_timeout_seconds=30)
    assert (
        runtime._execute_delivery(object(), config, 7, "retry_delivery") == "delivered"
    )
    assert captured["recipient"] == "configured@example.com"
    assert captured["delivery_id"] == 7


def test_status_runtime_opens_only_foundation_database_and_status_service(monkeypatch):
    class Connection:
        closed = False

        def execute(self, sql):
            assert "data_subjects" in sql
            return [("default",)]

        def close(self):
            self.closed = True

    connection = Connection()
    foundation = SimpleNamespace(
        database_path=Path("/project/state/foundation/data.db")
    )
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(
        runtime,
        "FoundationTool",
        lambda _foundation: SimpleNamespace(
            _connect=lambda _path, *, readonly=False: (
                connection
                if readonly
                else (_ for _ in ()).throw(
                    AssertionError("status connection is writable")
                )
            )
        ),
    )
    monkeypatch.setattr(
        runtime,
        "load_analysis_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("analysis config loaded")),
    )

    from trainlab.analysis import status

    captured = {}

    class Service:
        def __init__(self, actual_connection):
            captured["connection"] = actual_connection

        def execute(self, request):
            captured["request"] = request
            return _receipt("succeeded")

    monkeypatch.setattr(status, "AnalysisStatusQueryService", Service)
    assert (
        runtime.run_analysis_status(
            run_key="analysis:default:daily:2026-07-25:one", root=Path("/project")
        ).status
        == "succeeded"
    )
    assert captured["connection"] is connection
    assert captured["request"].invocation_id is None
    assert connection.closed


def test_unchanged_daily_receipt_recovers_persisted_delivery_artifact_ids():
    result = SimpleNamespace(
        delivery_id=7,
        status="sent",
        provider_message_id="message-1",
        provider_thread_id=None,
        error_code=None,
        next_action="none",
    )
    merged = runtime._merge_daily_delivery(_receipt("unchanged"), result, ("11", "12"))
    assert merged.status == "unchanged"
    assert merged.delivery is not None
    assert merged.delivery.artifact_ids == ("11", "12")
    assert merged.artifact_ids == ("11", "12")


def test_status_retries_only_controlled_transient_wal_change(monkeypatch):
    class Connection:
        def execute(self, sql, *_args):
            assert "data_subjects" in sql
            return [("default",)]

        def close(self):
            pass

    connection = Connection()
    attempts = []

    class Tool:
        def _connect(self, _path, *, readonly=False):
            assert readonly
            attempts.append(readonly)
            if len(attempts) < 3:
                raise runtime.IncompatibleError("sqlite_wal_state_unsafe")
            return connection

    foundation = SimpleNamespace(database_path=Path("/project/state/data.db"))
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(runtime, "FoundationTool", lambda _foundation: Tool())

    from trainlab.analysis import status

    monkeypatch.setattr(
        status,
        "AnalysisStatusQueryService",
        lambda _connection: SimpleNamespace(
            execute=lambda _request: _receipt("succeeded")
        ),
    )

    assert runtime.run_analysis_status(root=Path("/project")).status == "succeeded"
    assert attempts == [True, True, True]


def test_status_does_not_retry_other_foundation_error(monkeypatch):
    attempts = []

    class Tool:
        def _connect(self, _path, *, readonly=False):
            attempts.append(readonly)
            raise runtime.IncompatibleError("sqlite_path_unsafe")

    foundation = SimpleNamespace(database_path=Path("/project/state/data.db"))
    monkeypatch.setattr(
        runtime, "FoundationConfig", SimpleNamespace(load=lambda _root: foundation)
    )
    monkeypatch.setattr(runtime, "FoundationTool", lambda _foundation: Tool())

    with pytest.raises(runtime.IncompatibleError, match="sqlite_path_unsafe"):
        runtime.run_analysis_status(root=Path("/project"))
    assert attempts == [True]


def test_unchanged_daily_receipt_restores_stored_run_evidence_without_generation():
    class Connection:
        def execute(self, sql, values):
            assert "FROM analysis_runs" in sql
            assert values == ("analysis:active_subject:daily:2026-07-25:invocation",)
            return SimpleNamespace(
                fetchone=lambda: (
                    17,
                    "succeeded",
                    "harness-v1",
                    "1",
                    "1",
                    "a" * 64,
                )
            )

    restored = runtime._restore_daily_receipt_evidence(
        Connection(), _receipt("unchanged"), ("1", "2")
    )
    assert restored.analysis_run_id == "17"
    assert restored.quality_gate_state == "ready"
    assert restored.artifact_ids == ("1", "2")
    assert restored.input_snapshot_sha256 == "a" * 64


def test_unchanged_weekly_receipt_restores_exact_plan_and_run_evidence():
    class Connection:
        def execute(self, sql, values):
            if "FROM analysis_runs" in sql:
                return SimpleNamespace(
                    fetchone=lambda: (
                        21,
                        "succeeded",
                        "weekly-harness-v1",
                        "1",
                        "1",
                        "b" * 64,
                    )
                )
            assert "FROM training_plans" in sql
            assert values == (21,)
            return SimpleNamespace(fetchall=lambda: [(31,)])

    restored = runtime._restore_receipt_evidence(
        Connection(),
        _weekly_receipt("unchanged"),
        ("41", "42"),
        include_training_plan=True,
    )
    assert restored.analysis_run_id == "21"
    assert restored.training_plan_id == "31"
    assert restored.artifact_ids == ("41", "42")
    assert restored.input_snapshot_sha256 == "b" * 64
