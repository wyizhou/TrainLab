"""A3-12 pure validation for one bounded analysis-generation result.

This module deliberately has no runner, persistence, network, or retry behaviour.
It accepts bytes already captured by the runner and returns only a typed accepted
value or a sanitised rejection code/path.  The rejected model output is never
retained by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from .safety_rules import SafetyRuleError, evaluate_training_safety


RESULT_SCHEMA_VERSION = "1"
_MAX_OUTPUT_BYTES = 250_000
_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _ROOT / "harness" / "schemas" / "analysis_result.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
RESULT_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())

_CJK = re.compile(r"[\u4e00-\u9fff]")
_TRADITIONAL = re.compile(r"[體臺訓練醫療處總結數據這個與為於後當週計畫]")
_IMPERIAL = re.compile(r"(?:\b\d+(?:\.\d+)?\s*(?:mi|mile|miles|ft|feet|lb|lbs|pound|pounds)\b|英里|英尺|磅)", re.IGNORECASE)
_INTERNAL_PATH = re.compile(r"(?:^|\s)(?:/+(?:Users|home|Volumes|tmp|private)/|[A-Za-z]:\\)")
_SECRET = re.compile(r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password|oauth)\s*[:=]", re.IGNORECASE)
_DELIVERY_CLAIM = re.compile(r"(?:已(?:发送|寄出|投递)|发送成功|投递成功|\b(?:sent|delivered)\b)", re.IGNORECASE)
_MEDICAL = re.compile(
    r"(?:医学诊断|诊断为|确诊|治疗方案|治愈|"
    r"(?:患有|存在|属于).{0,20}(?:疾病|病症)|"
    r"medical diagnosis|diagnosed|treatment plan)",
    re.IGNORECASE,
)
_ALL_OUT = re.compile(r"(?:\bRPE\s*10\b|10\s*/\s*10|all[ -]?out|力竭|全力冲刺)", re.IGNORECASE)
_RAW_DEVICE_NARRATION = re.compile(
    r"(?:\bBody\s*Battery\b|训练准备度|睡眠评分|睡眠秒数|"
    r"\b(?:POOR|BEHIND)\b|\d+(?:\.\d+)?\s*秒)",
    re.IGNORECASE,
)
_DEVICE_DIAGNOSIS = re.compile(
    r"(?:低氧血症|心脏(?:可能)?有问题|睡眠呼吸(?:存在)?疾病)"
)
_UNCONFIRMED_ACTIVITY_CLAIM = re.compile(
    r"(?:昨天|昨日).{0,12}(?:没有训练|没有运动|未训练|未执行计划)"
)
_CLOCK_TIME = re.compile(
    r"(?:"
    r"\b(?:[01]?\d|2[0-3])\s*[:：]\s*[0-5]\d\b"
    r"|\b(?:1[0-2]|0?[1-9])(?:\s*[:：]\s*[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)\b"
    r"|(?:凌晨|早上|上午|中午|下午|傍晚|晚上|夜间)\s*(?:[01]?\d|2[0-3])"
    r"(?:\s*(?:点|时)(?:\s*[0-5]?\d\s*分)?)?"
    r"|(?<!第)(?:[01]?\d|2[0-3])\s*(?:点|时)(?:\s*[0-5]?\d\s*分)?"
    r"\s*(?:开始|训练|跑步|攀岩|力量|健身)"
    r")",
    re.IGNORECASE,
)


class AnalysisResultValidationError(ValueError):
    """Sanitised validation failure: code and JSON-like path only."""

    def __init__(self, code: str, path: str = "root") -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}:{path}")

    def as_record(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


@dataclass(frozen=True)
class ResultValidationExpectation:
    run_key: str
    mode: str
    subject_id: int
    target_periods: Mapping[str, Any]
    input_manifest: Sequence[Mapping[str, Any]]
    quality_gate: Mapping[str, Any] | Any
    # A3-09 request minus ``primary_items``.  The model's candidate is injected
    # by this validator so the deterministic engine, rather than the model,
    # decides whether it is acceptable and how it is normalised.
    safety_request_base: Mapping[str, Any]
    # Weekly retains A3-09's one-primary-item contract by supplying one
    # request base per planned Hong Kong local date.  Each base deliberately
    # omits ``primary_items``; the validator supplies the model candidate.
    weekly_safety_request_bases: Mapping[str, Mapping[str, Any]] | None = None
    # The context builder distinguishes an absent first weekly artifact from a
    # failed lookup.  Both new weekly artifacts must repeat this exact state.
    prior_artifact_state: Mapping[str, str] | None = None
    # Revision routes bind the generated suffix to one immutable original plan
    # and one already-accepted revision reason.  They are deliberately
    # supplied by the host, never inferred from model output.
    original_plan: Mapping[str, Any] | None = None
    original_plan_items: Sequence[Mapping[str, Any]] | None = None
    reason_event: Mapping[str, Any] | None = None
    # Regeneration keeps a distinct top-level mode but its accepted artifact
    # shape is determined by host-verified source lineage, never model output.
    regeneration_source_shape: str | None = None
    regeneration_source_artifact_id: str | None = None
    training_difficulty_level: int = 2
    available_training_weekdays: Sequence[int] | None = None


@dataclass(frozen=True)
class ValidatedAnalysisResult:
    """The validated value only; callers must persist it themselves."""

    result: Mapping[str, Any]


def _reject(code: str, path: str = "root") -> None:
    raise AnalysisResultValidationError(code, path)


def _as_mapping(value: Mapping[str, Any] | Any, code: str) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        _reject(code)
    return value


def _schema_validate(payload: Mapping[str, Any]) -> None:
    errors = sorted(
        RESULT_VALIDATOR.iter_errors(payload),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "root"
        _reject("analysis_result_schema_invalid", path)


def _strings(value: Any) -> Sequence[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    def visit(item: Any, path: str) -> None:
        if isinstance(item, str):
            rows.append((path, item))
        elif isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}.{index}" if path else str(index))
    visit(value, "")
    return rows


def _validate_text_safety(payload: Mapping[str, Any]) -> None:
    for path, value in _strings(payload):
        if _INTERNAL_PATH.search(value):
            _reject("analysis_result_internal_path_forbidden", path)
        if _SECRET.search(value):
            _reject("analysis_result_secret_forbidden", path)
        if _DELIVERY_CLAIM.search(value):
            _reject("analysis_result_delivery_claim_forbidden", path)
        if _MEDICAL.search(value):
            _reject("analysis_result_medical_diagnosis_forbidden", path)
        if _ALL_OUT.search(value):
            _reject("analysis_result_all_out_forbidden", path)
        if _IMPERIAL.search(value):
            _reject("analysis_result_imperial_unit_forbidden", path)
        if path.endswith("user_visible_text") and _RAW_DEVICE_NARRATION.search(
            value
        ):
            _reject("analysis_result_raw_device_narration_forbidden", path)
    for index, artifact in enumerate(payload["artifacts"]):
        text = artifact["user_visible_text"]
        if not _CJK.search(text) or _TRADITIONAL.search(text):
            _reject("analysis_result_simplified_chinese_required", f"artifacts.{index}.user_visible_text")


def _expected_period(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    period = value.get(key)
    if not isinstance(period, Mapping):
        _reject("analysis_result_expected_period_invalid", key)
    return period


def _validate_daily_shape(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    if payload["mode"] not in {"daily", "regenerate"}:
        _reject("analysis_result_route_not_implemented", "mode")
    if payload["training_plan"] is not None:
        _reject("analysis_result_daily_plan_forbidden", "training_plan")
    artifacts = payload["artifacts"]
    kinds = [item["artifact_kind"] for item in artifacts]
    if len(artifacts) != 2 or sorted(kinds) != ["daily_summary", "daily_training_advice"]:
        _reject("analysis_result_daily_cardinality_invalid", "artifacts")
    summary_period = _expected_period(expected.target_periods, "summary")
    advice_period = _expected_period(expected.target_periods, "advice")
    for index, artifact in enumerate(artifacts):
        wanted = summary_period if artifact["artifact_kind"] == "daily_summary" else advice_period
        if dict(artifact["period"]) != dict(wanted):
            _reject("analysis_result_date_mismatch", f"artifacts.{index}.period")


def _sentence_count(text: str) -> int:
    return len(
        [
            item
            for item in re.split(r"(?<=[。！？!?])\s*", text.strip())
            if item.strip()
        ]
    )


def _validate_daily_content(
    payload: Mapping[str, Any], expected: ResultValidationExpectation
) -> None:
    by_kind = {item["artifact_kind"]: item for item in payload["artifacts"]}
    summary = by_kind["daily_summary"]
    advice = by_kind["daily_training_advice"]
    summary_content = _as_mapping(
        summary["structured_content"], "analysis_result_daily_summary_invalid"
    )
    advice_content = _as_mapping(
        advice["structured_content"], "analysis_result_daily_advice_invalid"
    )
    configured = expected.training_difficulty_level
    if (
        isinstance(configured, bool)
        or not isinstance(configured, int)
        or not 1 <= configured <= 5
        or advice_content.get("configured_difficulty_level") != configured
    ):
        _reject(
            "analysis_result_training_difficulty_mismatch",
            "artifacts.daily_training_advice.structured_content.configured_difficulty_level",
        )
    selected = advice_content.get("selected_session_difficulty_level")
    adjustment = advice_content.get("difficulty_adjustment_reason")
    if selected != configured and not isinstance(adjustment, str):
        _reject(
            "analysis_result_training_difficulty_adjustment_missing",
            "artifacts.daily_training_advice.structured_content.difficulty_adjustment_reason",
        )

    summary_text = str(summary["user_visible_text"]).strip()
    advice_text = str(advice["user_visible_text"]).strip()
    if re.search(r"(?m)^(?:昨日回顾|今日安排)\s*$", summary_text + "\n" + advice_text):
        _reject("analysis_result_daily_embedded_title_forbidden", "artifacts")
    if not 2 <= _sentence_count(summary_text) <= 4:
        _reject(
            "analysis_result_daily_summary_sentence_count_invalid",
            "artifacts.daily_summary.user_visible_text",
        )

    lines = [line.strip() for line in advice_text.splitlines() if line.strip()]
    confidence_lines = [
        line for line in lines if line.startswith("判断置信度：")
    ]
    limitation_lines = [line for line in lines if line.startswith("数据说明：")]
    body_lines = [
        line
        for line in lines
        if not line.startswith(("判断置信度：", "数据说明："))
    ]
    body = "\n".join(body_lines)
    if not 2 <= _sentence_count(body) <= 4 or len(confidence_lines) != 1:
        _reject(
            "analysis_result_daily_advice_format_invalid",
            "artifacts.daily_training_advice.user_visible_text",
        )
    confidence = advice_content["confidence"]
    confidence_reason = advice_content["confidence_reason"]
    if confidence_lines[0] != f"判断置信度：{confidence}——{confidence_reason}":
        _reject(
            "analysis_result_daily_confidence_mismatch",
            "artifacts.daily_training_advice.user_visible_text",
        )
    limitation = advice_content["data_limitation"]
    wanted_limitations = [] if limitation is None else [f"数据说明：{limitation}"]
    if limitation_lines != wanted_limitations:
        _reject(
            "analysis_result_daily_limitation_mismatch",
            "artifacts.daily_training_advice.user_visible_text",
        )
    completeness = summary_content["data_completeness"]
    if completeness == "limited" and confidence != "较低":
        _reject(
            "analysis_result_daily_confidence_too_high",
            "artifacts.daily_training_advice.structured_content.confidence",
        )
    if completeness == "partial" and confidence == "较高":
        _reject(
            "analysis_result_daily_confidence_too_high",
            "artifacts.daily_training_advice.structured_content.confidence",
        )

    primary = _as_mapping(
        advice_content["primary_item"], "analysis_result_primary_item_missing"
    )
    prefix = {
        "running": "今日跑步。",
        "rest": "今日休息。",
    }.get(primary.get("activity_kind"))
    if prefix is None:
        _reject(
            "analysis_result_daily_item_kind_invalid",
            "artifacts.daily_training_advice.structured_content.primary_item.activity_kind",
        )
    available = expected.available_training_weekdays
    if available is not None and primary.get("activity_kind") == "running":
        advice_day = date.fromisoformat(str(advice_content.get("advice_local_date", expected.target_periods["advice"]["start_local_date"])))
        if advice_day.isoweekday() not in available:
            _reject("analysis_result_training_weekday_forbidden", "artifacts.daily_training_advice.structured_content.primary_item")
    if not body.startswith(prefix):
        _reject(
            "analysis_result_daily_primary_opening_invalid",
            "artifacts.daily_training_advice.user_visible_text",
        )

    all_text = summary_text + "\n" + advice_text
    if _RAW_DEVICE_NARRATION.search(all_text):
        _reject("analysis_result_raw_device_narration_forbidden", "artifacts")
    if _DEVICE_DIAGNOSIS.search(all_text):
        _reject("analysis_result_device_diagnosis_forbidden", "artifacts")
    if (
        summary_content["activity_evidence"] in {"partial", "unconfirmed"}
        and _UNCONFIRMED_ACTIVITY_CLAIM.search(all_text)
    ):
        _reject(
            "analysis_result_unconfirmed_activity_claim_forbidden",
            "artifacts.daily_summary.user_visible_text",
        )


def _period_days(period: Mapping[str, Any], *, path: str) -> tuple[str, ...]:
    try:
        start = date.fromisoformat(str(period["start_local_date"]))
        end = date.fromisoformat(str(period["end_local_date"]))
    except (KeyError, TypeError, ValueError):
        _reject("analysis_result_date_mismatch", path)
    if start > end:
        _reject("analysis_result_date_mismatch", path)
    return tuple((start + timedelta(days=index)).isoformat() for index in range((end - start).days + 1))


def _weekly_prior_state(expected: ResultValidationExpectation) -> dict[str, str]:
    value = expected.prior_artifact_state
    if not isinstance(value, Mapping) or set(value) != {"summary", "plan"}:
        _reject("analysis_result_weekly_prior_artifact_state_invalid", "prior_artifact_state")
    result = {key: value[key] for key in ("summary", "plan")}
    if any(item not in {"available", "no_prior_artifact"} for item in result.values()):
        _reject("analysis_result_weekly_prior_artifact_state_invalid", "prior_artifact_state")
    return result


def _canonicalize_plan_item_kind(item: dict[str, Any], *, path: str) -> None:
    """Canonicalize duplicated running/rest kind before safety validation."""

    prescription = item.get("prescription")
    if not isinstance(prescription, dict):
        _reject("analysis_result_weekly_item_prescription_invalid", path)
    outer = item.get("activity_kind")
    inner = prescription.get("activity_kind")
    if inner is None:
        prescription["activity_kind"] = outer
    elif inner in {"running", "rest"}:
        item["activity_kind"] = inner
    else:
        _reject("analysis_result_weekly_item_prescription_invalid", path)


def _validate_weekly_shape(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    if payload["mode"] not in {"weekly", "regenerate"}:
        _reject("analysis_result_route_not_implemented", "mode")
    artifacts = payload["artifacts"]
    by_kind = {item["artifact_kind"]: item for item in artifacts}
    if len(artifacts) != 2 or set(by_kind) != {"weekly_summary", "weekly_training_plan"}:
        _reject("analysis_result_weekly_cardinality_invalid", "artifacts")
    review = _expected_period(expected.target_periods, "review")
    plan_period = _expected_period(expected.target_periods, "plan")
    review_days = _period_days(review, path="review")
    plan_days = _period_days(plan_period, path="plan")
    if len(review_days) != 7 or len(plan_days) != 7 or date.fromisoformat(plan_days[0]) != date.fromisoformat(review_days[-1]) + timedelta(days=1):
        _reject("analysis_result_weekly_window_invalid", "target_periods")
    if dict(by_kind["weekly_summary"]["period"]) != dict(review):
        _reject("analysis_result_date_mismatch", "artifacts.weekly_summary.period")
    if dict(by_kind["weekly_training_plan"]["period"]) != dict(plan_period):
        _reject("analysis_result_date_mismatch", "artifacts.weekly_training_plan.period")
    training_plan = payload["training_plan"]
    if not isinstance(training_plan, Mapping):
        _reject("analysis_result_weekly_plan_required", "training_plan")
    if dict(training_plan.get("period", {})) != dict(plan_period):
        _reject("analysis_result_date_mismatch", "training_plan.period")
    # The top-level plan is canonical; the artifact embeds the same value only
    # for publication.  Do not let duplicated model serialization diverge.
    by_kind["weekly_training_plan"]["structured_content"] = training_plan
    prior_state = _weekly_prior_state(expected)
    summary_structured = by_kind["weekly_summary"]["structured_content"]
    if not isinstance(summary_structured, dict):
        _reject(
            "analysis_result_weekly_prior_artifact_state_mismatch",
            "artifacts.weekly_summary.structured_content.prior_artifact_state",
        )
    # Prior-artifact availability is a host-owned database fact.  Canonicalize
    # the two repeated model fields instead of allowing transcription drift to
    # decide whether prior context exists.
    summary_structured["prior_artifact_state"] = prior_state
    training_plan["prior_artifact_state"] = prior_state
    items = training_plan.get("items")
    if not isinstance(items, list) or len(items) != 7:
        _reject("analysis_result_weekly_item_cardinality_invalid", "training_plan.items")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            _reject("analysis_result_weekly_item_invalid", f"training_plan.items.{index}")
        if item.get("item_index") != index or item.get("local_date") != plan_days[index]:
            _reject("analysis_result_weekly_item_sequence_invalid", f"training_plan.items.{index}")
        if item.get("activity_kind") not in {"running", "rest"}:
            _reject("analysis_result_weekly_item_kind_invalid", f"training_plan.items.{index}.activity_kind")
        if expected.available_training_weekdays is not None and item.get("activity_kind") == "running":
            if date.fromisoformat(str(item["local_date"])).isoweekday() not in expected.available_training_weekdays:
                _reject("analysis_result_training_weekday_forbidden", f"training_plan.items.{index}.activity_kind")
        assert isinstance(item, dict)
        _canonicalize_plan_item_kind(
            item, path=f"training_plan.items.{index}.prescription"
        )


def _validate_regenerated_plan_shape(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    """Validate a full replacement for a plan-revision artifact.

    Unlike ``revise_plan`` this is not an event-driven suffix rewrite: the
    selected current plan is regenerated as one complete seven-day snapshot.
    """
    artifacts = payload["artifacts"]
    if len(artifacts) != 1 or artifacts[0]["artifact_kind"] != "weekly_training_plan":
        _reject("analysis_result_regeneration_plan_cardinality_invalid", "artifacts")
    plan = payload["training_plan"]
    if not isinstance(plan, Mapping):
        _reject("analysis_result_regeneration_plan_required", "training_plan")
    expected_period = _expected_period(expected.target_periods, "plan")
    if dict(artifacts[0]["period"]) != dict(expected_period) or dict(plan.get("period", {})) != dict(expected_period):
        _reject("analysis_result_date_mismatch", "training_plan.period")
    artifacts[0]["structured_content"] = plan
    items = plan.get("items")
    days = _period_days(expected_period, path="plan")
    if not isinstance(items, list) or len(items) != 7:
        _reject("analysis_result_weekly_item_cardinality_invalid", "training_plan.items")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping) or item.get("item_index") != index or item.get("local_date") != days[index]:
            _reject("analysis_result_weekly_item_sequence_invalid", f"training_plan.items.{index}")
        if item.get("activity_kind") not in {"running", "rest"} or not isinstance(item.get("prescription"), dict):
            _reject("analysis_result_weekly_item_invalid", f"training_plan.items.{index}")
        if expected.available_training_weekdays is not None and item.get("activity_kind") == "running":
            if date.fromisoformat(str(item["local_date"])).isoweekday() not in expected.available_training_weekdays:
                _reject("analysis_result_training_weekday_forbidden", f"training_plan.items.{index}.activity_kind")
        assert isinstance(item, dict)
        _canonicalize_plan_item_kind(
            item, path=f"training_plan.items.{index}.prescription"
        )


def _weekly_bases(expected: ResultValidationExpectation) -> Mapping[str, Mapping[str, Any]]:
    bases = expected.weekly_safety_request_bases
    if not isinstance(bases, Mapping) or len(bases) != 7:
        _reject("analysis_result_weekly_safety_base_invalid", "weekly_safety_request_bases")
    for day, base in bases.items():
        if not isinstance(day, str) or not isinstance(base, Mapping) or "primary_items" in base:
            _reject("analysis_result_weekly_safety_base_invalid", "weekly_safety_request_bases")
        if base.get("advice_local_date") != day:
            _reject("analysis_result_weekly_safety_base_invalid", "weekly_safety_request_bases")
    return bases


def _validate_hansons_sos_spacing(
    normalized: Sequence[Mapping[str, Any]], *, path: str
) -> None:
    """Keep Hansons SOS roles auditable and separated inside a generated plan."""

    sos_roles = {"long", "tempo", "speed", "running_strength"}
    sos_days = sorted(
        date.fromisoformat(str(item["local_date"]))
        for item in normalized
        if item["primary_item"].get("activity_kind") == "running"
        and item["primary_item"].get("hansons_session_role") in sos_roles
    )
    if len(sos_days) > 3:
        _reject("analysis_result_hansons_sos_frequency_exceeded", path)
    if any((right - left).days < 2 for left, right in zip(sos_days, sos_days[1:])):
        _reject("analysis_result_hansons_sos_recovery_insufficient", path)


def _validate_weekly_safety(payload: dict[str, Any], expected: ResultValidationExpectation) -> None:
    training_plan = payload["training_plan"]
    assert isinstance(training_plan, dict)
    items = training_plan["items"]
    assert isinstance(items, list)
    bases = _weekly_bases(expected)
    normalized: list[dict[str, Any]] = []
    exact_bpm_by_day: list[bool] = []
    suspended = False
    for index, item in enumerate(items):
        assert isinstance(item, dict)
        local_date = item["local_date"]
        base = bases.get(local_date)
        if base is None:
            _reject("analysis_result_weekly_safety_base_invalid", f"weekly_safety_request_bases.{local_date}")
        request = dict(base)
        request["primary_items"] = [item["prescription"]]
        try:
            evidence = evaluate_training_safety(request)
        except SafetyRuleError:
            _reject("analysis_result_safety_candidate_invalid", f"training_plan.items.{index}.prescription")
        primary_items = evidence.get("primary_items")
        if evidence.get("status") == "rejected" or not isinstance(primary_items, list) or len(primary_items) != 1 or not isinstance(primary_items[0], Mapping):
            _reject("analysis_result_safety_candidate_rejected", f"training_plan.items.{index}.prescription")
        safe = dict(primary_items[0])
        # Weekly can be safely normalized by the host, but it cannot silently
        # change the date identity.  The item type follows the normalized
        # primary prescription, including a safety-induced rest day.
        item["prescription"] = safe
        item["activity_kind"] = safe.get("activity_kind")
        state = evidence.get("safety_state")
        if state not in {"normal", "warning", "suspended"}:
            _reject("analysis_result_safety_candidate_rejected", f"training_plan.items.{index}.prescription")
        suspended = suspended or state == "suspended"
        exact_bpm_by_day.append(
            bool(evidence.get("zone_selection", {}).get("exact_bpm_allowed"))
        )
        normalized.append({"item_index": item["item_index"], "local_date": local_date,
                           "safety_state": state, "primary_item": safe})
    if suspended and any(item["primary_item"].get("activity_kind") != "rest" for item in normalized):
        _reject("analysis_result_weekly_red_flag_plan_not_suspended", "training_plan.items")
    high_days = [
        date.fromisoformat(str(item["local_date"]))
        for item in normalized
        if item["primary_item"].get("activity_kind") == "running"
        and item["primary_item"].get("target_zone") in {4, 5}
    ]
    if len(high_days) > 2:
        _reject("analysis_result_weekly_high_intensity_frequency_exceeded", "training_plan.items")
    if any((right - left) < timedelta(hours=48) for left, right in zip(high_days, high_days[1:])):
        _reject("analysis_result_weekly_high_intensity_recovery_insufficient", "training_plan.items")
    _validate_hansons_sos_spacing(normalized, path="training_plan.items")
    plan_artifact = next(item for item in payload["artifacts"] if item["artifact_kind"] == "weekly_training_plan")
    # The validated/normalized plan is the sole canonical structured content.
    plan_artifact["structured_content"] = training_plan
    states = {item["safety_state"] for item in normalized}
    overall = "suspended" if "suspended" in states else "warning" if "warning" in states else "normal"
    payload["safety"] = {"safety_state": overall, "plan_items": normalized}
    for item, safety_item in zip(items, normalized):
        if item["item_index"] != safety_item["item_index"] or item["local_date"] != safety_item["local_date"] or item["prescription"] != safety_item["primary_item"]:
            _reject("analysis_result_weekly_safety_mismatch", "safety.plan_items")
    for index, (safety_item, exact_bpm_allowed) in enumerate(
        zip(normalized, exact_bpm_by_day)
    ):
        if not exact_bpm_allowed:
            for path, value in _strings({"plan_item": items[index], "safety": safety_item}):
                if re.search(r"\b\d{2,3}\s*(?:bpm|BPM)\b|\d{2,3}\s*次\s*/\s*分", value):
                    _reject("analysis_result_invented_bpm_forbidden", path)
    # The weekly plan prose is not structurally attributable to one specific
    # day.  Unless every planned day has evidence permitting exact BPM, reject
    # an exact target anywhere in that forward-looking prose.  The completed
    # week summary may still report exact observed heart-rate facts.
    if not all(exact_bpm_by_day):
        for path, value in _strings(
            {"weekly_training_plan": plan_artifact["user_visible_text"]}
        ):
            if re.search(
                r"\b\d{2,3}\s*(?:bpm|BPM)\b|\d{2,3}\s*次\s*/\s*分", value
            ):
                _reject("analysis_result_invented_bpm_forbidden", path)


def _validate_identity(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    if payload["run_key"] != expected.run_key:
        _reject("analysis_result_run_key_mismatch", "run_key")
    if payload["mode"] != expected.mode:
        _reject("analysis_result_mode_mismatch", "mode")
    if payload["subject_id"] != expected.subject_id:
        _reject("analysis_result_subject_mismatch", "subject_id")


def _validate_source_usage(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    known: dict[int, tuple[str, str, str]] = {}
    for row in expected.input_manifest:
        try:
            ordinal = row["ordinal"]
            known[ordinal] = (row["input_role"], row["source_entity_id"], row["source_revision_id"])
        except (KeyError, TypeError):
            _reject("analysis_result_manifest_invalid", "input_manifest")
    seen: set[int] = set()
    for index, usage in enumerate(payload["source_usage"]):
        ordinal = usage["ordinal"]
        if ordinal in seen or ordinal not in known:
            _reject("analysis_result_source_usage_invalid", f"source_usage.{index}")
        seen.add(ordinal)
        # The model selects sources only by the bounded ordinal.  Repeated
        # identity strings are host-owned and canonicalized from the immutable
        # input manifest so harmless transcription drift cannot reject an
        # otherwise valid analysis or forge foreign lineage.
        role, entity_id, revision_id = known[ordinal]
        usage["input_role"] = role
        usage["source_entity_id"] = entity_id
        usage["source_revision_id"] = revision_id


def _validate_regeneration_source_usage(
    payload: Mapping[str, Any], expected: ResultValidationExpectation
) -> None:
    artifact_id = expected.regeneration_source_artifact_id
    if not isinstance(artifact_id, str) or not artifact_id.isdecimal() or int(artifact_id) <= 0:
        _reject(
            "analysis_result_regeneration_source_invalid",
            "regeneration_source_artifact_id",
        )
    matching = [
        row
        for row in expected.input_manifest
        if isinstance(row, Mapping)
        and row.get("input_role") == "regeneration.source_artifact"
        and row.get("source_entity_type") == "analysis_artifact"
        and row.get("source_entity_id") == artifact_id
    ]
    if len(matching) != 1:
        _reject(
            "analysis_result_regeneration_source_invalid",
            "input_manifest",
        )
    used = {row["ordinal"] for row in payload["source_usage"]}
    if matching[0].get("ordinal") not in used:
        _reject(
            "analysis_result_regeneration_source_not_used",
            "source_usage",
        )


def _validate_weekly_prior_source_usage(
    payload: Mapping[str, Any], expected: ResultValidationExpectation
) -> None:
    prior_state = _weekly_prior_state(expected)
    review = _expected_period(expected.target_periods, "review")
    review_days = _period_days(review, path="review")
    review_start = date.fromisoformat(review_days[0])
    prior_summary_period = {
        "start_local_date": (review_start - timedelta(days=7)).isoformat(),
        "end_local_date": (review_start - timedelta(days=1)).isoformat(),
    }
    used = {row["ordinal"] for row in payload["source_usage"]}

    def candidates(kind: str) -> list[Mapping[str, Any]]:
        result: list[Mapping[str, Any]] = []
        for row in expected.input_manifest:
            if (
                not isinstance(row, Mapping)
                or row.get("source_entity_type") != "analysis_artifact"
            ):
                continue
            window = row.get("source_window")
            if not isinstance(window, Mapping):
                continue
            if kind == "summary":
                matches = (
                    row.get("input_role") == "artifact.prior_model_output"
                    and dict(window) == prior_summary_period
                )
            else:
                try:
                    window_start = date.fromisoformat(
                        str(window["start_local_date"])
                    )
                    window_end = date.fromisoformat(str(window["end_local_date"]))
                except (KeyError, TypeError, ValueError):
                    matches = False
                else:
                    matches = (
                        row.get("input_role") == "plan.current_revision"
                        and window_start <= date.fromisoformat(review_days[-1])
                        and window_end >= review_start
                    )
            if matches:
                result.append(row)
        return result

    for kind in ("summary", "plan"):
        if prior_state[kind] != "available":
            continue
        rows = candidates(kind)
        if len(rows) != 1:
            _reject(
                "analysis_result_weekly_prior_source_invalid",
                f"input_manifest.prior_{kind}",
            )
        ordinal = rows[0].get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal not in used:
            _reject(
                "analysis_result_weekly_prior_source_usage_required",
                f"source_usage.prior_{kind}",
            )


def _validate_weekly_clock_time(payload: Mapping[str, Any]) -> None:
    plan_artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_kind"] == "weekly_training_plan"
    )
    for path, value in _strings({"weekly_training_plan": plan_artifact}):
        if _CLOCK_TIME.search(value):
            _reject("analysis_result_training_clock_time_forbidden", path)


def _revision_metadata(expected: ResultValidationExpectation) -> tuple[str, str, Mapping[str, Any], str, str]:
    plan = expected.original_plan
    reason = expected.reason_event
    if not isinstance(plan, Mapping) or not isinstance(reason, Mapping):
        _reject("analysis_result_revision_expectation_invalid", "revision_metadata")
    plan_id, artifact_id, period = plan.get("plan_id"), plan.get("artifact_id"), plan.get("period")
    reason_id, effective = reason.get("reason_event_id"), reason.get("effective_local_date")
    if not all(isinstance(value, str) and value for value in (plan_id, artifact_id, reason_id, effective)) or not isinstance(period, Mapping):
        _reject("analysis_result_revision_expectation_invalid", "revision_metadata")
    return plan_id, artifact_id, period, reason_id, effective


def _original_plan_prescription(
    item: Mapping[str, Any], *, path: str
) -> Mapping[str, Any]:
    value = item.get("prescription")
    if isinstance(value, Mapping):
        return value
    encoded = item.get("prescription_json")
    if isinstance(encoded, str):
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError:
            value = None
    if not isinstance(value, Mapping):
        _reject("analysis_result_revision_original_items_invalid", path)
    return value


def _validate_revision_shape(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    if payload["mode"] != "revise_plan":
        _reject("analysis_result_route_not_implemented", "mode")
    plan_id, artifact_id, original_period, reason_id, effective = _revision_metadata(expected)
    original_days = _period_days(original_period, path="original_plan.period")
    if len(original_days) != 7:
        _reject("analysis_result_revision_original_window_invalid", "original_plan.period")
    if effective not in original_days:
        _reject("analysis_result_revision_effective_date_invalid", "reason_event.effective_local_date")
    artifacts = payload["artifacts"]
    if len(artifacts) != 1 or artifacts[0]["artifact_kind"] != "weekly_training_plan":
        _reject("analysis_result_revision_cardinality_invalid", "artifacts")
    artifact = artifacts[0]
    revision = payload["training_plan"]
    if not isinstance(revision, Mapping):
        _reject("analysis_result_revision_plan_required", "training_plan")
    if dict(artifact["period"]) != dict(original_period) or dict(revision.get("period", {})) != dict(original_period):
        _reject("analysis_result_revision_period_invalid", "training_plan.period")
    artifact["structured_content"] = revision
    if (revision.get("original_plan_id"), revision.get("original_artifact_id"), revision.get("reason_event_id"), revision.get("effective_local_date")) != (plan_id, artifact_id, reason_id, effective):
        _reject("analysis_result_revision_lineage_mismatch", "training_plan")
    expected_days = original_days[original_days.index(effective):]
    items = revision.get("items")
    if not isinstance(items, list) or len(items) != len(expected_days):
        _reject("analysis_result_revision_item_cardinality_invalid", "training_plan.items")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping) or item.get("item_index") != index or item.get("local_date") != expected_days[index]:
            _reject("analysis_result_revision_item_sequence_invalid", f"training_plan.items.{index}")
        if item.get("activity_kind") not in {"running", "rest"} or not isinstance(item.get("prescription"), dict):
            _reject("analysis_result_revision_item_invalid", f"training_plan.items.{index}")
        if expected.available_training_weekdays is not None and item.get("activity_kind") == "running":
            if date.fromisoformat(str(item["local_date"])).isoweekday() not in expected.available_training_weekdays:
                _reject("analysis_result_training_weekday_forbidden", f"training_plan.items.{index}.activity_kind")
        assert isinstance(item, dict)
        _canonicalize_plan_item_kind(
            item, path=f"training_plan.items.{index}.prescription"
        )
    # The output shape has no historical-item field.  Assert the host supplied
    # exactly the immutable prefix too, so a malformed expectation cannot
    # accidentally turn a revision into a rewritten plan.
    originals = expected.original_plan_items
    if not isinstance(originals, Sequence) or isinstance(originals, (str, bytes)) or len(originals) != 7:
        _reject("analysis_result_revision_original_items_invalid", "original_plan_items")
    for index, item in enumerate(originals):
        if (
            not isinstance(item, Mapping)
            or item.get("item_index") != index
            or item.get("local_date") != original_days[index]
        ):
            _reject("analysis_result_revision_original_items_invalid", f"original_plan_items.{index}")
        _original_plan_prescription(
            item, path=f"original_plan_items.{index}.prescription"
        )


def _validate_revision_source_usage(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    _, artifact_id, _, reason_id, _ = _revision_metadata(expected)
    used = {row["ordinal"] for row in payload["source_usage"]}
    required = (("analysis_artifact", artifact_id), ("conversation_event", reason_id))
    for entity_type, entity_id in required:
        rows = [row for row in expected.input_manifest if isinstance(row, Mapping) and row.get("source_entity_type") == entity_type and row.get("source_entity_id") == entity_id]
        if len(rows) != 1 or rows[0].get("ordinal") not in used:
            _reject("analysis_result_revision_source_usage_required", f"source_usage.{entity_type}")


def _validate_revision_safety(payload: dict[str, Any], expected: ResultValidationExpectation) -> None:
    revision = payload["training_plan"]
    assert isinstance(revision, dict)
    items = revision["items"]
    assert isinstance(items, list)
    bases = expected.weekly_safety_request_bases
    if not isinstance(bases, Mapping) or len(bases) < len(items):
        _reject("analysis_result_revision_safety_base_invalid", "weekly_safety_request_bases")
    normalized: list[dict[str, Any]] = []
    exact_bpm_by_day: list[bool] = []
    suspended = False
    for index, item in enumerate(items):
        base = bases.get(item["local_date"])
        if not isinstance(base, Mapping) or "primary_items" in base or base.get("advice_local_date") != item["local_date"]:
            _reject("analysis_result_revision_safety_base_invalid", f"weekly_safety_request_bases.{item['local_date']}")
        try:
            evidence = evaluate_training_safety({**base, "primary_items": [item["prescription"]]})
        except SafetyRuleError:
            _reject("analysis_result_safety_candidate_invalid", f"training_plan.items.{index}.prescription")
        primary = evidence.get("primary_items")
        if evidence.get("status") == "rejected" or not isinstance(primary, list) or len(primary) != 1 or not isinstance(primary[0], Mapping):
            _reject("analysis_result_safety_candidate_rejected", f"training_plan.items.{index}.prescription")
        safe = dict(primary[0])
        item["prescription"], item["activity_kind"] = safe, safe.get("activity_kind")
        state = evidence.get("safety_state")
        if state not in {"normal", "warning", "suspended"}:
            _reject("analysis_result_safety_candidate_rejected", f"training_plan.items.{index}.prescription")
        suspended = suspended or state == "suspended"
        exact_bpm_by_day.append(
            bool(evidence.get("zone_selection", {}).get("exact_bpm_allowed"))
        )
        normalized.append({"item_index": item["item_index"], "local_date": item["local_date"], "safety_state": state, "primary_item": safe})
    if suspended and any(row["primary_item"].get("activity_kind") != "rest" for row in normalized):
        _reject("analysis_result_weekly_red_flag_plan_not_suspended", "training_plan.items")
    _, _, _, _, effective = _revision_metadata(expected)
    originals = expected.original_plan_items
    assert isinstance(originals, Sequence)
    hansons_window = [
        {
            "local_date": str(row.get("local_date")),
            "primary_item": _original_plan_prescription(
                row, path="original_plan_items.prescription"
            ),
        }
        for row in originals
        if isinstance(row, Mapping) and str(row.get("local_date")) < effective
    ]
    hansons_window.extend(normalized)
    high_days = [
        date.fromisoformat(str(row["local_date"]))
        for row in originals
        if isinstance(row, Mapping)
        and str(row.get("local_date")) < effective
        and (
            prescription := _original_plan_prescription(
                row, path="original_plan_items.prescription"
            )
        ).get("activity_kind") == "running"
        and prescription.get("target_zone") in {4, 5}
    ]
    high_days.extend(
        date.fromisoformat(str(row["local_date"]))
        for row in normalized
        if row["primary_item"].get("activity_kind") == "running"
        and row["primary_item"].get("target_zone") in {4, 5}
    )
    high_days.sort()
    if len(high_days) > 2 or any((right - left) < timedelta(hours=48) for left, right in zip(high_days, high_days[1:])):
        _reject("analysis_result_weekly_high_intensity_frequency_exceeded", "training_plan.items")
    _validate_hansons_sos_spacing(hansons_window, path="training_plan.items")
    artifact = payload["artifacts"][0]
    artifact["structured_content"] = revision
    overall = "suspended" if suspended else "warning" if any(row["safety_state"] == "warning" for row in normalized) else "normal"
    payload["safety"] = {"safety_state": overall, "plan_items": normalized}
    for index, (row, exact_bpm) in enumerate(zip(normalized, exact_bpm_by_day)):
        if not exact_bpm:
            for path, value in _strings({"plan_item": items[index], "safety": row}):
                if re.search(r"\b\d{2,3}\s*(?:bpm|BPM)\b|\d{2,3}\s*次\s*/\s*分", value):
                    _reject("analysis_result_invented_bpm_forbidden", path)
    for path, value in _strings({"plan_revision": artifact}):
        if _CLOCK_TIME.search(value):
            _reject("analysis_result_training_clock_time_forbidden", path)


def _validate_quality(payload: Mapping[str, Any], expected: ResultValidationExpectation) -> None:
    gate = _as_mapping(expected.quality_gate, "analysis_result_quality_gate_invalid")
    state = gate.get("state")
    if state not in {"ready", "ready_with_warnings"}:
        _reject("analysis_result_quality_gate_blocked", "quality_gate")
    expected_rows = [*gate.get("blockers", ()), *gate.get("warnings", ())]
    wanted = {(row.get("code"), row.get("entity")) for row in expected_rows if isinstance(row, Mapping)}
    if len(wanted) != len(expected_rows):
        _reject("analysis_result_quality_gate_invalid", "quality_gate")
    actual = {(row["code"], row["entity"]) for row in payload["quality_disclosures"]}
    if actual != wanted:
        _reject("analysis_result_quality_disclosure_mismatch", "quality_disclosures")


def _validate_safety(payload: dict[str, Any], expected: ResultValidationExpectation) -> None:
    advice = next(item for item in payload["artifacts"] if item["artifact_kind"] == "daily_training_advice")
    structured = advice["structured_content"]
    if not isinstance(structured, Mapping) or "primary_item" not in structured:
        _reject("analysis_result_primary_item_missing", "artifacts.daily_training_advice.structured_content.primary_item")
    candidate = structured["primary_item"]
    base = _as_mapping(expected.safety_request_base, "analysis_result_safety_request_invalid")
    if "primary_items" in base:
        _reject("analysis_result_safety_request_invalid", "safety_request_base.primary_items")
    request = dict(base)
    request["primary_items"] = [candidate]
    try:
        evidence = evaluate_training_safety(request)
    except SafetyRuleError:
        _reject("analysis_result_safety_candidate_invalid", "artifacts.daily_training_advice.structured_content.primary_item")
    primary_items = evidence.get("primary_items")
    if evidence.get("status") == "rejected" or not isinstance(primary_items, list) or len(primary_items) != 1:
        _reject("analysis_result_safety_candidate_rejected", "artifacts.daily_training_advice.structured_content.primary_item")
    expected_primary = primary_items[0]
    if (
        not isinstance(expected_primary, Mapping)
        or expected_primary.get("activity_kind") != candidate.get("activity_kind")
    ):
        # A red flag or another hard rule changed the selected activity.  The
        # host cannot safely rewrite the model's user-visible prose, so reject
        # instead of publishing contradictory advice.
        _reject(
            "analysis_result_safety_candidate_rejected",
            "artifacts.daily_training_advice.structured_content.primary_item",
        )
    # The model proposes a candidate; A3-09 owns the final safety state and
    # normalized prescription.  Never require the model to reproduce the rule
    # engine's derived output.
    structured["primary_item"] = expected_primary
    payload["safety"] = {
        "safety_state": evidence.get("safety_state"),
        "primary_item": expected_primary,
    }
    exact_bpm = bool(evidence.get("zone_selection", {}).get("exact_bpm_allowed"))
    if not exact_bpm:
        # Exact observed heart-rate facts may be reported in the completed-day
        # summary.  The no-zone rule applies to the forward prescription and
        # its safety record, where a number would become an invented target.
        for path, value in _strings({"advice": advice, "safety": payload["safety"]}):
            if re.search(r"\b\d{2,3}\s*(?:bpm|BPM)\b|\d{2,3}\s*次\s*/\s*分", value):
                _reject("analysis_result_invented_bpm_forbidden", path)


class AnalysisResultValidator:
    """Strict daily and weekly result validator with host-owned safety output."""

    def validate(
        self,
        raw_output: bytes,
        expected: ResultValidationExpectation,
    ) -> ValidatedAnalysisResult:
        if not isinstance(raw_output, bytes):
            _reject("analysis_result_output_type_invalid")
        if not raw_output or len(raw_output) > _MAX_OUTPUT_BYTES:
            _reject("analysis_result_output_size_invalid")
        try:
            decoded = raw_output.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _reject("analysis_result_json_invalid")
        if not isinstance(payload, Mapping):
            _reject("analysis_result_json_type_invalid")
        payload = dict(payload)
        _schema_validate(payload)
        _validate_identity(payload, expected)
        if expected.mode == "daily":
            _validate_daily_shape(payload, expected)
        elif expected.mode == "weekly":
            _validate_weekly_shape(payload, expected)
        elif expected.mode == "revise_plan":
            _validate_revision_shape(payload, expected)
        elif expected.mode == "regenerate":
            shape = expected.regeneration_source_shape
            if shape == "daily":
                _validate_daily_shape(payload, expected)
            elif shape == "weekly":
                _validate_weekly_shape(payload, expected)
            elif shape == "plan_revision":
                _validate_regenerated_plan_shape(payload, expected)
            else:
                _reject("analysis_result_regeneration_source_invalid", "regeneration_source_shape")
        else:
            _reject("analysis_result_route_not_implemented", "mode")
        _validate_source_usage(payload, expected)
        if expected.mode == "weekly":
            _validate_weekly_prior_source_usage(payload, expected)
        elif expected.mode == "revise_plan":
            _validate_revision_source_usage(payload, expected)
        elif expected.mode == "regenerate":
            _validate_regeneration_source_usage(payload, expected)
        _validate_quality(payload, expected)
        if expected.mode == "daily" or (expected.mode == "regenerate" and expected.regeneration_source_shape == "daily"):
            _validate_safety(payload, expected)
        elif expected.mode == "weekly" or (expected.mode == "regenerate" and expected.regeneration_source_shape in {"weekly", "plan_revision"}):
            _validate_weekly_safety(payload, expected)
            _validate_weekly_clock_time(payload)
        else:
            _validate_revision_safety(payload, expected)
        _validate_text_safety(payload)
        if expected.mode == "daily" or (
            expected.mode == "regenerate"
            and expected.regeneration_source_shape == "daily"
        ):
            _validate_daily_content(payload, expected)
        return ValidatedAnalysisResult(dict(payload))


def validate_analysis_result(
    raw_output: bytes,
    expected: ResultValidationExpectation,
) -> ValidatedAnalysisResult:
    """Convenience pure entrypoint used by a future runner/publisher."""
    return AnalysisResultValidator().validate(raw_output, expected)
