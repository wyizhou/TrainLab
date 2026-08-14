from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.analysis.config import AnalysisConfig
from src.analysis.context import (
    ANALYSIS_INPUT_SCHEMA_SHA256,
    ANALYSIS_INPUT_SCHEMA_VERSION,
)
from src.analysis.contracts import AnalysisRequest
from src.analysis.harness import HarnessBundle, SchemaEvidence
from src.analysis.run_state import RunDecision
from src.analysis.weekly import (
    WeeklyRoute,
    _periods,
    _prior_artifact_state,
    weekly_plan_contract,
)


def request(invocation: str = "weekly-one") -> AnalysisRequest:
    return AnalysisRequest(
        "weekly",
        "subject",
        invocation,
        "2026-07-27T00:00:00Z",
        as_of_local_date="2026-07-27",
    )


def config(tmp_path: Path) -> AnalysisConfig:
    schema = tmp_path / "result.json"
    schema.write_text("{}")
    return AnalysisConfig(
        "1",
        tmp_path,
        "Asia/Hong_Kong",
        tmp_path,
        schema,
        schema,
        1_000_000,
        14,
        28,
        7,
        60,
        60,
        tmp_path / "lock",
        tmp_path,
    )


class Coordinator:
    def __init__(self) -> None:
        self.finished: list[str] = []

    def begin(self, _: AnalysisRequest):
        return SimpleNamespace(
            decision=RunDecision(
                "started",
                7,
                "analysis:subject:weekly:2026-07-27:weekly-one",
                "started",
                ("run_created",),
            )
        )

    def finish(self, _: object, status: str) -> None:
        self.finished.append(status)


def _coverage() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": index + 1,
            "subject_id": 1,
            "provider": "garmin",
            "resource_kind": "activity_inventory",
            "local_date": f"2026-07-{20 + index:02d}",
            "availability_state": "empty",
            "observed_at_utc": "2026-07-27T00:00:00Z",
            "source_revision_id": f"coverage-{index}",
            "current_revision": True,
        }
        for index in range(7)
    )


class Views:
    def __init__(self) -> None:
        self.value = SimpleNamespace(
            views={
                "v_current_weekly_summaries": (),
                "v_current_training_plans": (),
            },
            coverage=_coverage(),
        )

    def snapshot(self, *_: object):
        return self.value


class Gate:
    def __init__(self, state: str = "ready") -> None:
        self.state = state
        self.calls: list[str] = []

    def evaluate(self, request: object, _: object):
        self.calls.append(request.route)
        return SimpleNamespace(
            state=self.state,
            next_action="repair_data",
            blockers=(),
            warnings=(),
            as_dict=lambda: {
                "state": self.state,
                "blockers": [],
                "warnings": [],
            },
        )


class Context:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def build(self, *_: object, **kwargs: object):
        self.kwargs = kwargs
        return SimpleNamespace(
            canonical_json="{}",
            context={"input_manifest": []},
            context_snapshot_sha256="a" * 64,
        )


class Runner:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_: object):
        self.calls += 1
        return SimpleNamespace(
            output_bytes=b"{}", audit={"runner_adapter_version": "fake"}
        )


class Validator:
    def __init__(self) -> None:
        self.expectation = None

    def validate(self, _: bytes, expectation: object):
        self.expectation = expectation
        return {"accepted": True}


class Publisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, **_: object):
        self.calls += 1
        return SimpleNamespace(
            run_id=7,
            artifact_ids={
                "weekly_summary": 11,
                "weekly_training_plan": 12,
            },
            training_plan_id=13,
            superseded_plan_ids=(),
        )


class Delivery:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def create_pending(self, **kwargs: object):
        self.calls += 1
        assert kwargs["delivery_kind"] == "weekly_report"
        if self.fail:
            raise RuntimeError("provider details must not escape")
        return SimpleNamespace(
            delivery_id=14,
            artifacts=(
                SimpleNamespace(artifact_id=11),
                SimpleNamespace(artifact_id=12),
            ),
        )


def route(
    tmp_path: Path, *, gate: Gate | None = None, delivery: Delivery | None = None
):
    coordinator = Coordinator()
    views = Views()
    context = Context()
    runner = Runner()
    validator = Validator()
    publisher = Publisher()
    pending = delivery or Delivery()
    evidence = SchemaEvidence(
        ANALYSIS_INPUT_SCHEMA_VERSION,
        ANALYSIS_INPUT_SCHEMA_SHA256,
        "1",
        "x" * 64,
    )
    bundle = HarnessBundle("weekly", "h" * 64, (), evidence)
    service = WeeklyRoute(
        config=config(tmp_path),
        coordinator=coordinator,
        stable_views=views,
        runner=runner,
        publisher=publisher,
        delivery=pending,
        context_builder=context,
        quality_gate=gate or Gate(),
        validator=validator,
        subject_resolver=lambda _: 1,
        harness_resolver=lambda *_: bundle,
        clock=lambda: "2026-07-27T00:00:00Z",
    )
    return service, coordinator, context, runner, validator, publisher, pending


def test_weekly_window_is_rolling_not_iso_week() -> None:
    assert _periods("2026-07-27") == (
        {
            "start_local_date": "2026-07-20",
            "end_local_date": "2026-07-26",
        },
        {
            "start_local_date": "2026-07-27",
            "end_local_date": "2026-08-02",
        },
    )


def test_ready_weekly_route_publishes_plan_and_only_seeds_pending_delivery(
    tmp_path: Path,
) -> None:
    service, coordinator, context, runner, validator, publisher, delivery = route(
        tmp_path
    )
    receipt = service.execute(request())
    assert receipt.status == "partial"
    assert receipt.artifact_ids == ("11", "12")
    assert receipt.training_plan_id == "13"
    assert receipt.delivery is not None and receipt.delivery.status == "pending"
    assert runner.calls == publisher.calls == delivery.calls == 1
    assert coordinator.finished == ["succeeded"]
    assert validator.expectation.target_periods == {
        "review": {
            "start_local_date": "2026-07-20",
            "end_local_date": "2026-07-26",
        },
        "plan": {
            "start_local_date": "2026-07-27",
            "end_local_date": "2026-08-02",
        },
    }
    assert validator.expectation.prior_artifact_state == {
        "summary": "no_prior_artifact",
        "plan": "no_prior_artifact",
    }
    assert set(validator.expectation.weekly_safety_request_bases) == {
        f"2026-07-{day:02d}" for day in range(27, 32)
    } | {"2026-08-01", "2026-08-02"}
    assert context.kwargs["plan_adherence"]
    assert {item["key"] for item in context.kwargs["deterministic_features"]} >= {
        "training_difficulty_contract_v1",
        "race_goal_contract_v1",
    }


def test_first_run_contract_marks_absent_prior_artifacts() -> None:
    contract = weekly_plan_contract(
        {"summary": "no_prior_artifact", "plan": "no_prior_artifact"}
    )
    assert contract["prior_artifact_state"] == {
        "summary": "no_prior_artifact",
        "plan": "no_prior_artifact",
    }
    assert contract["days"] == 7 and contract["items_per_day"] == 1


def test_prior_artifact_state_requires_the_immediately_preceding_summary() -> None:
    review = {
        "start_local_date": "2026-08-03",
        "end_local_date": "2026-08-09",
    }
    snapshot = SimpleNamespace(
        views={
            "v_current_weekly_summaries": (
                {
                    "artifact_kind": "weekly_summary",
                    "period_start_local_date": "2026-07-20",
                    "period_end_local_date": "2026-07-26",
                },
            ),
            "v_current_training_plans": (),
        }
    )
    assert _prior_artifact_state(snapshot, review) == {
        "summary": "no_prior_artifact",
        "plan": "no_prior_artifact",
    }

    snapshot.views["v_current_weekly_summaries"] = (
        {
            "artifact_kind": "weekly_summary",
            "period_start_local_date": "2026-07-27",
            "period_end_local_date": "2026-08-02",
        },
    )
    snapshot.views["v_current_training_plans"] = (
        {
            "plan_start_local_date": "2026-08-03",
            "plan_end_local_date": "2026-08-09",
        },
    )
    assert _prior_artifact_state(snapshot, review) == {
        "summary": "available",
        "plan": "available",
    }


def test_blocked_week_never_runs_generator_publisher_or_delivery(
    tmp_path: Path,
) -> None:
    gate = Gate("blocked")
    service, coordinator, _, runner, _, publisher, delivery = route(tmp_path, gate=gate)
    receipt = service.execute(request())
    assert receipt.status == "deferred"
    assert runner.calls == publisher.calls == delivery.calls == 0
    assert coordinator.finished == ["failed"]


def test_same_invocation_is_unchanged_without_generation(tmp_path: Path) -> None:
    service, coordinator, _, runner, _, publisher, delivery = route(tmp_path)
    coordinator.begin = lambda _: SimpleNamespace(
        decision=RunDecision(
            "unchanged",
            7,
            "analysis:subject:weekly:2026-07-27:weekly-one",
            "succeeded",
            ("existing_succeeded",),
        )
    )
    receipt = service.execute(request())
    assert receipt.status == "unchanged"
    assert runner.calls == publisher.calls == delivery.calls == 0


def test_delivery_seed_failure_does_not_rollback_published_week(tmp_path: Path) -> None:
    service, coordinator, _, runner, _, publisher, delivery = route(
        tmp_path, delivery=Delivery(fail=True)
    )
    receipt = service.execute(request())
    assert receipt.status == "partial"
    assert receipt.training_plan_id == "13"
    assert receipt.artifact_ids == ("11", "12")
    assert receipt.next_action == "retry_delivery"
    assert receipt.errors[0].code == "analysis_weekly_delivery_pending_failed"
    assert runner.calls == publisher.calls == delivery.calls == 1
    assert coordinator.finished == ["succeeded"]
