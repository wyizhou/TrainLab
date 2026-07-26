"""A3-12 pure validation for one bounded analysis-generation result.

This module deliberately has no runner, persistence, network, or retry behaviour.
It accepts bytes already captured by the runner and returns only a typed accepted
value or a sanitised rejection code/path.  The rejected model output is never
retained by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
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
_MEDICAL = re.compile(r"(?:医学诊断|诊断为|确诊|治疗方案|治愈|疾病|病症|medical diagnosis|diagnosed|treatment plan)", re.IGNORECASE)
_ALL_OUT = re.compile(r"(?:\bRPE\s*10\b|10\s*/\s*10|all[ -]?out|力竭|全力冲刺)", re.IGNORECASE)


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
    if payload["mode"] != "daily":
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
        if (usage["input_role"], usage["source_entity_id"], usage["source_revision_id"]) != known[ordinal]:
            _reject("analysis_result_source_usage_invalid", f"source_usage.{index}")


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
    """Strict daily result validator; future routes intentionally fail closed."""

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
        _validate_daily_shape(payload, expected)
        _validate_source_usage(payload, expected)
        _validate_quality(payload, expected)
        _validate_safety(payload, expected)
        _validate_text_safety(payload)
        return ValidatedAnalysisResult(dict(payload))


def validate_analysis_result(
    raw_output: bytes,
    expected: ResultValidationExpectation,
) -> ValidatedAnalysisResult:
    """Convenience pure entrypoint used by a future runner/publisher."""
    return AnalysisResultValidator().validate(raw_output, expected)
