from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from src.analysis.config import AnalysisConfig
from src.analysis.context import (
    ANALYSIS_INPUT_SCHEMA_SHA256,
    ANALYSIS_INPUT_SCHEMA_VERSION,
)
from src.analysis.contracts import AnalysisRequest
from src.analysis.harness import HarnessBundle, SchemaEvidence
from src.analysis.revise_plan import PlanRevisionRoute, plan_revision_contract
from src.analysis.run_state import RunDecision


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    payload = {
        "current_plan_id": 41,
        "effective_local_date": "2026-07-22",
    }
    connection.executescript("""
    CREATE TABLE data_subjects(
      id INTEGER PRIMARY KEY, subject_key TEXT, is_active INTEGER
    );
    CREATE TABLE analysis_artifacts(
      id INTEGER PRIMARY KEY, artifact_kind TEXT, is_current INTEGER
    );
    CREATE TABLE training_plans(
      id INTEGER PRIMARY KEY, subject_id INTEGER, analysis_artifact_id INTEGER,
      plan_start_local_date TEXT, plan_end_local_date TEXT, timezone TEXT,
      status TEXT
    );
    CREATE TABLE reason_source(
      id INTEGER PRIMARY KEY, subject_id INTEGER, structured_payload_json TEXT
    );
    CREATE VIEW v_plan_revision_reason_events AS SELECT * FROM reason_source;
    INSERT INTO data_subjects VALUES(1,'subject',1);
    INSERT INTO analysis_artifacts VALUES(81,'weekly_training_plan',1);
    INSERT INTO training_plans VALUES(
      41,1,81,'2026-07-20','2026-07-26','Asia/Hong_Kong','active'
    );
    """)
    connection.execute(
        "INSERT INTO reason_source VALUES(91,1,?)",
        (json.dumps(payload),),
    )
    connection.commit()
    return connection


def request(*, effective: str | None = None) -> AnalysisRequest:
    return AnalysisRequest(
        "revise_plan",
        "subject",
        "revision-one",
        "2026-07-21T00:00:00Z",
        plan_id="41",
        reason_event_id="91",
        effective_local_date=effective,
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

    def begin(self, value: AnalysisRequest):
        assert value.effective_local_date == "2026-07-22"
        return SimpleNamespace(
            decision=RunDecision(
                "started",
                7,
                "analysis:subject:revise_plan:41:91:revision-one",
                "started",
                ("run_created",),
            )
        )

    def finish(self, _: object, status: str) -> None:
        self.finished.append(status)


class Views:
    def __init__(self) -> None:
        self.value = SimpleNamespace(
            views={
                "v_training_plan_items": tuple(
                    {
                        "id": index + 1,
                        "subject_id": 1,
                        "training_plan_id": 41,
                        "item_index": index,
                        "local_date": f"2026-07-{20 + index:02d}",
                        "activity_kind": "rest",
                        "prescription_json": "{}",
                        "rationale_text": "旧计划",
                    }
                    for index in range(7)
                )
            },
            plan_reasons=(),
        )

    def snapshot(self, *_: object):
        return self.value


class Gate:
    def __init__(self, state: str = "ready") -> None:
        self.state = state

    def evaluate(self, value: object, _: object):
        assert value.route == "revise_plan"
        assert value.start_local_date == value.end_local_date == "2026-07-22"
        assert value.plan_id == 41 and value.reason_event_id == 91
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
        self.features = ()

    def build(self, *_: object, **kwargs: object):
        self.features = kwargs["deterministic_features"]
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
            artifact_ids={"weekly_training_plan": 82},
            training_plan_id=42,
            superseded_plan_ids=(41,),
        )


class Delivery:
    def __init__(self) -> None:
        self.calls = 0

    def create_pending(self, **kwargs: object):
        self.calls += 1
        assert kwargs["delivery_kind"] == "plan_revision"
        return SimpleNamespace(
            delivery_id=14,
            artifacts=(SimpleNamespace(artifact_id=82),),
        )


def route(tmp_path: Path, *, gate: Gate | None = None):
    connection = database()
    coordinator = Coordinator()
    views, context, runner = Views(), Context(), Runner()
    validator, publisher, delivery = Validator(), Publisher(), Delivery()
    evidence = SchemaEvidence(
        ANALYSIS_INPUT_SCHEMA_VERSION,
        ANALYSIS_INPUT_SCHEMA_SHA256,
        "1",
        "x" * 64,
    )
    bundle = HarnessBundle("revise_plan", "h" * 64, (), evidence)
    service = PlanRevisionRoute(
        config=config(tmp_path),
        coordinator=coordinator,
        stable_views=views,
        runner=runner,
        publisher=publisher,
        delivery=delivery,
        connection=connection,
        context_builder=context,
        quality_gate=gate or Gate(),
        validator=validator,
        harness_resolver=lambda *_: bundle,
        clock=lambda: "2026-07-21T00:00:00Z",
    )
    return (service, coordinator, context, runner, validator, publisher, delivery)


def test_revision_contract_is_suffix_only_and_contains_no_mail_evidence() -> None:
    contract = plan_revision_contract(
        original_plan_id=41,
        original_artifact_id=81,
        reason_event_id=91,
        effective_local_date="2026-07-22",
    )
    assert contract["scope"] == "effective_date_through_original_plan_end_only"
    assert contract["historical_prefix_policy"].startswith("host_copies")
    assert "mail" not in json.dumps(contract)


def test_ready_revision_resolves_reason_publishes_and_only_seeds_delivery(
    tmp_path: Path,
) -> None:
    service, coordinator, context, runner, validator, publisher, delivery = route(
        tmp_path
    )
    receipt = service.execute(request())
    assert receipt.status == "partial"
    assert receipt.target_periods["plan"] == {
        "start_local_date": "2026-07-22",
        "end_local_date": "2026-07-26",
    }
    assert receipt.artifact_ids == ("82",)
    assert receipt.training_plan_id == "42"
    assert receipt.superseded_plan_id == "41"
    assert receipt.delivery is not None and receipt.delivery.status == "pending"
    assert runner.calls == publisher.calls == delivery.calls == 1
    assert coordinator.finished == ["succeeded"]
    assert validator.expectation.original_plan == {
        "plan_id": "41",
        "artifact_id": "81",
        "period": {
            "start_local_date": "2026-07-20",
            "end_local_date": "2026-07-26",
        },
    }
    assert set(validator.expectation.weekly_safety_request_bases) == {
        f"2026-07-{day:02d}" for day in range(22, 27)
    }
    assert context.features[0]["reason_event_id"] == "91"
    assert {item["key"] for item in context.features} >= {
        "training_difficulty_contract_v1",
        "race_goal_contract_v1",
    }


def test_explicit_effective_date_must_match_reason_and_never_runs_generator(
    tmp_path: Path,
) -> None:
    service, coordinator, _, runner, _, publisher, delivery = route(tmp_path)
    receipt = service.execute(request(effective="2026-07-23"))
    assert receipt.status == "rejected"
    assert receipt.errors[0].code == "analysis_plan_revision_effective_date_mismatch"
    assert runner.calls == publisher.calls == delivery.calls == 0
    assert coordinator.finished == []


def test_blocked_revision_never_generates_or_publishes(tmp_path: Path) -> None:
    service, coordinator, _, runner, _, publisher, delivery = route(
        tmp_path, gate=Gate("blocked")
    )
    receipt = service.execute(request())
    assert receipt.status == "deferred"
    assert runner.calls == publisher.calls == delivery.calls == 0
    assert coordinator.finished == ["failed"]
