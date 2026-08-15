from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.analysis.config import AnalysisConfig
from src.analysis.context import (
    ANALYSIS_INPUT_SCHEMA_SHA256,
    ANALYSIS_INPUT_SCHEMA_VERSION,
)
from src.analysis.contracts import AnalysisRequest
from src.analysis.daily import (
    DailyRoute,
    _safe_code,
    _safety_base,
    _validate_with_bounded_corrections,
    daily_primary_item_contract,
)
from src.analysis.harness import HarnessBundle, SchemaEvidence
from src.analysis.quality_gate import QualityGateResult
from src.analysis.result_validation import _candidate_for_safety
from src.analysis.run_state import AnalysisRunStateError, RunDecision
from src.analysis.safety_rules import evaluate_training_safety


def request(invocation: str = "one") -> AnalysisRequest:
    return AnalysisRequest(
        "daily",
        "subject",
        invocation,
        "2026-07-24T00:00:00Z",
        summary_local_date="2026-07-23",
        advice_local_date="2026-07-24",
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
        1000000,
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
        self.calls = 0

    def begin(self, _: AnalysisRequest):
        self.calls += 1
        return SimpleNamespace(
            decision=RunDecision(
                "started",
                7,
                "analysis:subject:daily:2026-07-23:one",
                "started",
                ("run_created",),
            )
        )

    def finish(self, _: object, status: str) -> None:
        self.finished.append(status)


class Views:
    def snapshot(self, *_: object):
        return object()


class Gate:
    def __init__(self, state: str = "ready") -> None:
        self.state = state

    def evaluate(self, *_: object) -> QualityGateResult:
        return SimpleNamespace(
            state=self.state,
            next_action="repair_data",
            blockers=(),
            as_dict=lambda: {"state": self.state, "blockers": [], "warnings": []},
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
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def execute(self, *_: object):
        self.calls += 1
        if self.fail:
            raise RuntimeError("raw model body must not leak")
        return SimpleNamespace(
            output_bytes=b"{}", audit={"runner_adapter_version": "fake"}
        )


class Validator:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def validate(self, *_: object):
        if self.fail:
            from src.analysis.result_validation import AnalysisResultValidationError

            raise AnalysisResultValidationError("analysis_result_json_invalid")
        return {"accepted": True}


class Publisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, **_: object):
        self.calls += 1
        return SimpleNamespace(
            run_id=7, artifact_ids={"daily_summary": 11, "daily_training_advice": 12}
        )


class Delivery:
    def __init__(self) -> None:
        self.calls = 0

    def create_pending(self, **_: object):
        self.calls += 1
        return SimpleNamespace(
            delivery_id=9,
            artifacts=(
                SimpleNamespace(artifact_id=11),
                SimpleNamespace(artifact_id=12),
            ),
        )


def route(
    tmp_path: Path,
    *,
    gate: Gate | None = None,
    runner: Runner | None = None,
    validator: Validator | None = None,
):
    coordinator, publisher, delivery = Coordinator(), Publisher(), Delivery()
    evidence = SchemaEvidence(
        ANALYSIS_INPUT_SCHEMA_VERSION, ANALYSIS_INPUT_SCHEMA_SHA256, "1", "x" * 64
    )
    bundle = HarnessBundle("daily", "h" * 64, (), evidence)
    service = DailyRoute(
        config=config(tmp_path),
        coordinator=coordinator,
        stable_views=Views(),
        runner=runner or Runner(),
        publisher=publisher,
        delivery=delivery,
        context_builder=Context(),
        quality_gate=gate or Gate(),
        validator=validator or Validator(),
        subject_resolver=lambda _: 1,
        harness_resolver=lambda *_: bundle,
        clock=lambda: "2026-07-24T00:00:00Z",
    )
    return service, coordinator, publisher, delivery


def test_ready_publishes_two_artifacts_and_only_pending_delivery(tmp_path: Path):
    service, coordinator, publisher, delivery = route(tmp_path)
    receipt = service.execute(request())
    assert receipt.status == "partial" and receipt.next_action == "retry_delivery"
    assert (
        receipt.artifact_ids == ("11", "12")
        and receipt.delivery
        and receipt.delivery.status == "pending"
    )
    assert publisher.calls == delivery.calls == 1 and coordinator.finished == [
        "succeeded"
    ]
    assert {item["key"] for item in service.context_builder.features} >= {
        "training_difficulty_contract_v1",
        "race_goal_contract_v1",
    }


def test_every_daily_primary_item_template_is_accepted_by_safety_policy():
    contract = daily_primary_item_contract()
    for key in (
        "running_template",
        "rest_template",
        "climbing_template",
    ):
        candidate = _candidate_for_safety(contract[key])
        result = evaluate_training_safety(
            {
                "schema_version": "1",
                "subject_id": 1,
                "advice_local_date": "2026-07-24",
                "as_of_utc": "2026-07-24T00:00:00Z",
                "zone_evidence": [],
                "safety_signals": [],
                "quality_sessions": [],
                "substitution": None,
                "primary_items": [candidate],
            }
        )
        assert result["status"] != "rejected", key
        assert len(result["primary_items"]) == 1
    assert contract["allowed_activity_kinds"] == ["running", "climbing", "rest"]
    assert "climbing_template" in contract
    assert "strength_template" not in contract


def test_blocked_never_runs_codex_or_publishes(tmp_path: Path):
    runner = Runner()
    service, coordinator, publisher, delivery = route(
        tmp_path, gate=Gate("blocked"), runner=runner
    )
    receipt = service.execute(request())
    assert (
        receipt.status == "deferred"
        and runner.calls == publisher.calls == delivery.calls == 0
    )
    assert coordinator.finished == ["failed"]


def test_same_invocation_unchanged_does_not_reenter_runner(tmp_path: Path):
    service, coordinator, publisher, delivery = route(tmp_path)
    coordinator.begin = lambda _: SimpleNamespace(
        decision=RunDecision(
            "unchanged",
            7,
            "analysis:subject:daily:2026-07-23:one",
            "succeeded",
            ("existing_succeeded",),
        )
    )
    receipt = service.execute(request())
    assert receipt.status == "unchanged" and publisher.calls == delivery.calls == 0


def test_only_explicit_lock_busy_begin_error_is_classified_as_lock_busy(tmp_path: Path):
    service, coordinator, _, _ = route(tmp_path)
    coordinator.begin = lambda _: (_ for _ in ()).throw(
        AnalysisRunStateError("analysis_subject_not_active")
    )
    receipt = service.execute(request())
    assert (
        receipt.status == "failed"
        and receipt.errors[0].code == "analysis_subject_not_active"
    )
    service, coordinator, _, _ = route(tmp_path)
    coordinator.begin = lambda _: (_ for _ in ()).throw(
        AnalysisRunStateError("analysis_lock_busy")
    )
    receipt = service.execute(request())
    assert (
        receipt.status == "lock_busy" and receipt.errors[0].code == "analysis_lock_busy"
    )


def test_runner_or_validator_failure_does_not_publish_current(tmp_path: Path):
    service, coordinator, publisher, _ = route(tmp_path, runner=Runner(True))
    assert service.execute(request()).status == "failed" and publisher.calls == 0
    service, coordinator, publisher, _ = route(tmp_path, validator=Validator(True))
    assert (
        service.execute(request()).status == "rejected"
        and publisher.calls == 0
        and coordinator.finished == ["rejected"]
    )


def test_validation_allows_only_one_safe_code_correction() -> None:
    from src.analysis.result_validation import AnalysisResultValidationError

    class CorrectingRunner:
        def __init__(self) -> None:
            self.codes: list[str] = []

        def execute_correction(self, _bundle, _context, code):
            self.codes.append(code)
            return SimpleNamespace(output_bytes=b"corrected", audit={})

    class CorrectingValidator:
        def __init__(self) -> None:
            self.calls = 0

        def validate(self, output_bytes, _expectation):
            self.calls += 1
            if self.calls == 1:
                raise AnalysisResultValidationError(
                    "analysis_result_raw_device_narration_forbidden"
                )
            assert output_bytes == b"corrected"
            return {"accepted": True}

    runner = CorrectingRunner()
    validator = CorrectingValidator()
    accepted, corrected = _validate_with_bounded_corrections(
        runner=runner,
        bundle=object(),
        canonical_context=b"{}",
        run_result=SimpleNamespace(output_bytes=b"first", audit={}),
        validator=validator,
        expectation=object(),
    )
    assert accepted == {"accepted": True}
    assert corrected.output_bytes == b"corrected"
    assert runner.codes == ["analysis_result_raw_device_narration_forbidden"]
    assert validator.calls == 2


def test_validation_stops_after_two_failed_corrections() -> None:
    from src.analysis.result_validation import AnalysisResultValidationError

    class RejectingRunner:
        def __init__(self) -> None:
            self.calls = 0

        def execute_correction(self, *_args):
            self.calls += 1
            return SimpleNamespace(output_bytes=b"still-invalid", audit={})

    class RejectingValidator:
        def __init__(self) -> None:
            self.calls = 0

        def validate(self, *_args):
            self.calls += 1
            raise AnalysisResultValidationError("analysis_result_json_invalid")

    runner = RejectingRunner()
    validator = RejectingValidator()
    try:
        _validate_with_bounded_corrections(
            runner=runner,
            bundle=object(),
            canonical_context=b"{}",
            run_result=SimpleNamespace(output_bytes=b"invalid", audit={}),
            validator=validator,
            expectation=object(),
        )
    except AnalysisResultValidationError as error:
        assert error.code == "analysis_result_json_invalid"
    else:
        raise AssertionError("validation accepted three invalid candidates")
    assert runner.calls == 2
    assert validator.calls == 3


def test_safe_code_preserves_only_controlled_analysis_prefix():
    assert (
        _safe_code(
            ValueError("analysis_context_limit_exceeded:sensitive detail"),
            "analysis_daily_failed",
        )
        == "analysis_context_limit_exceeded"
    )
    assert (
        _safe_code(
            ValueError("sensitive detail"),
            "analysis_daily_failed",
        )
        == "analysis_daily_failed"
    )


def test_active_acute_injury_fact_forces_rest_and_rejects_running_model_safety_claim():
    from src.analysis.result_validation import (
        AnalysisResultValidationError,
        AnalysisResultValidator,
        ResultValidationExpectation,
    )
    from src.analysis.safety_rules import evaluate_training_safety

    snapshot = SimpleNamespace(
        views={
            "v_active_user_facts": (
                {
                    "id": 42,
                    "subject_id": 1,
                    "fact_key": "acute_injury",
                    "effective_from_utc": None,
                    "expires_at_utc": None,
                    "fact_value_json": '{"untrusted":"ignored"}',
                },
            )
        }
    )
    base = _safety_base(1, "2026-07-24", "2026-07-24T00:00:00Z", snapshot)
    assert base["safety_signals"] == [
        {
            "signal_id": "user-fact:42:acute_injury",
            "kind": "acute_injury",
            "origin": "user_asserted",
            "source_revision_id": "user-fact:42",
            "current": True,
            "active": True,
            "effective_from_utc": "2026-07-24T00:00:00Z",
            "expires_at_utc": None,
        }
    ]
    running = {
        "activity_kind": "running",
        "hansons_session_role": "easy",
        "course_type": "easy",
        "warmup": "gentle_warmup",
        "main_set": "talk_test_easy",
        "cooldown": "gentle_cooldown",
        "planned_duration_minutes": 30,
        "total_volume": "easy_by_duration",
        "target_zone": None,
        "target_bpm_range": None,
        "prescribed_rpe": 4,
        "talk_test": "full_sentences",
        "work_intervals": [],
        "stop_conditions": [
            "acute_pain",
            "chest_pain",
            "fainting_or_dizziness",
            "unusual_shortness_of_breath",
        ],
        "rationale": "recovery_appropriate",
    }
    evidence = evaluate_training_safety({**base, "primary_items": [running]})
    assert (
        evidence["safety_state"] == "suspended"
        and evidence["primary_items"][0]["activity_kind"] == "rest"
    )
    output = {
        "schema_version": "1",
        "run_key": "analysis:subject:daily:2026-07-23:one",
        "mode": "daily",
        "subject_id": 1,
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "daily_summary",
                "period": {
                    "start_local_date": "2026-07-23",
                    "end_local_date": "2026-07-23",
                },
                "structured_content": {
                    "overall_state": "恢复证据存在安全阻断",
                    "decision_factors": ["用户报告急性伤情"],
                    "activity_evidence": "unconfirmed",
                    "plan_evidence": "unavailable",
                    "data_completeness": "partial",
                },
                "user_visible_text": "昨日恢复情况需要谨慎看待。用户报告的急性伤情是当前最重要的因素，活动记录尚未确认。",
            },
            {
                "artifact_kind": "daily_training_advice",
                "period": {
                    "start_local_date": "2026-07-24",
                    "end_local_date": "2026-07-24",
                },
                "structured_content": {
                    "primary_item": running,
                    "configured_difficulty_level": 2,
                    "selected_session_difficulty_level": 2,
                    "difficulty_adjustment_reason": None,
                    "confidence": "一般",
                    "confidence_reason": "活动记录尚未确认，但伤情信息足以支持保守判断。",
                    "data_limitation": None,
                },
                "user_visible_text": "今日跑步。完成包含热身、轻松主训练和放松的30分钟课程，全程保持能说完整句子。如有急性疼痛、胸痛、晕厥或异常呼吸困难，请立即停止。\n判断置信度：一般——活动记录尚未确认，但伤情信息足以支持保守判断。",
            },
        ],
        "training_plan": None,
        "source_usage": [
            {
                "ordinal": 0,
                "input_role": "health",
                "source_entity_id": "daily:2026-07-23",
                "source_revision_id": "health-revision-1",
            }
        ],
        "quality_disclosures": [],
        "safety": {"safety_state": "suspended", "primary_item": running},
        "warnings": [],
    }
    manifest = [
        {
            "ordinal": 0,
            "input_role": "health",
            "source_entity_id": "daily:2026-07-23",
            "source_revision_id": "health-revision-1",
        }
    ]
    expectation = ResultValidationExpectation(
        output["run_key"],
        "daily",
        1,
        {
            "summary": output["artifacts"][0]["period"],
            "advice": output["artifacts"][1]["period"],
        },
        manifest,
        {"state": "ready", "blockers": [], "warnings": []},
        base,
    )
    try:
        AnalysisResultValidator().validate(
            __import__("json").dumps(output, ensure_ascii=False).encode(), expectation
        )
    except AnalysisResultValidationError as error:
        assert error.code == "analysis_result_safety_candidate_rejected"
    else:
        raise AssertionError("A3-12 accepted a running candidate despite acute injury")
