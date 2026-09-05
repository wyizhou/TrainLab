#!/usr/bin/env python3
"""Deterministic privacy and lineage contract for the M11 v4 model input."""

from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
from pathlib import Path
from typing import Any

from skills._shared.scripts.health_contract_v4 import validate_health_facts_vc002
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.state import canonical_json

SCHEMA_VERSION = "m11_v4_weekly_model_context_v2"
FROZEN_WIRE_SCHEMA_SHA256 = (
    "89239ef53a66df5d17766860395c9ca11a23f5f762dacc2d7b14580fb2494dd2"
)
FROZEN_CONTEXT_SCHEMA_SHA256 = (
    "c11847a962e616d2321f1f8518c74fb090c8bcedfb6b7fb7bbade0ad17d14240"
)
FROZEN_TRAINING_GOAL_SCHEMA_SHA256 = (
    "081cc34616d03ba7c87e049708e7a0478bc35aa3593c7416c5634b5e3664d03a"
)
FROZEN_WEEKLY_EVIDENCE_SCHEMA_SHA256 = (
    "5da2c465c361f0db63cec3b97a6524a806b562457e18b37e5041dda878fbc1e3"
)
FROZEN_HEALTH_FACT_SCHEMA_SHA256 = (
    "627bb6c805c43408d19be68566ecd67090d0b214460ea14383fccffb485bb7ed"
)
FROZEN_PROMPT_TEMPLATE_SHA256 = (
    "15828d08b13876b183cc6091e960da9395d89ad788ba08c1c331c4b49ce4dab5"
)
FROZEN_GOAL_TEMPLATE_SHA256 = (
    "362c6dba4a7b0f3668da8a2d8c37e6325efe5498845b77f3f1002b8eb56be136"
)
FROZEN_DECISION_BUSINESS_SCHEMA_SHA256 = (
    "514452525520fc7a334be7eb0778ca2096519d5f86243d2101b4ccd8154ffb8e"
)
FROZEN_DECISION_WIRE_SCHEMA_SHA256 = (
    "9c4962b75aba063c1f7ea03ddf6f85479d1c4b176b37cd1c6e696428b4b468d7"
)
FROZEN_AI_RESULT_V4_SCHEMA_SHA256 = (
    "6beea3b7f6c5451121ab93ade8bafbe5294f570244140f920603b0ac82c09c99"
)
FROZEN_READER_V2_SCHEMA_SHA256 = (
    "5aba6d8eed51e13608ecd736bbf564e00d8cac6c83b3e6ee3df2fce81b5163e7"
)
FROZEN_PROMPT_TEMPLATE_V3_SHA256 = (
    "f0aea3bb5ecb01f608f967cdf1aca2d1e0c276d25fc682060dac9496f422d4b0"
)
FROZEN_PROMPT_TEMPLATE_V4_SHA256 = (
    "faae52bcf6a901b63246429f2086a56673435946a64eeaa64044f0962d36ca84"
)
EXPECTED_ACTIVITY_PERIOD = {
    "activity_start_date": "2026-08-11",
    "activity_end_date": "2026-08-17",
    "sleep_wake_start_date": "2026-08-12",
    "sleep_wake_end_date": "2026-08-18",
}
EXPECTED_PLAN_DATES = tuple(f"2026-08-{day:02d}" for day in range(19, 26))
ROOT_FIELDS = {
    "schema_version",
    "activity_period",
    "next_plan_dates",
    "training_goal",
    "weekly_evidence",
    "allowed_technical_activity_refs",
    "provider_calls",
    "external_actions",
}
PRIVATE_FIELD_FRAGMENTS = (
    "latitude",
    "longitude",
    "gps",
    "activityname",
    "email",
    "token",
    "credential",
    "password",
    "clientsecret",
)
EMAIL_PATTERN = re.compile(
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}", re.IGNORECASE | re.ASCII
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:token|password|credential|client[ _-]?secret)"
    r"(?![A-Za-z0-9])\s*[:=]\s*\S+"
)
GPS_PATTERN = re.compile(r"(?<![A-Za-z0-9])gps(?![A-Za-z0-9])")
BEARER_PATTERN = re.compile(r"(?<![A-Za-z0-9])bearer\s+\S+")
AUTHORIZATION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])authorization(?![A-Za-z0-9])\s*[:=]\s*\S+"
)
ACTIVITY_NAME_LABELS = (
    "activity_name",
    "activity name",
    "activity-name",
    "activityname",
    "活动名称",
    "活动名",
)
ACTIVITY_NAME_DELIMITERS = frozenset((":", "：", "="))
COORDINATE_PAIR_PATTERN = re.compile(
    r"(?<![\d.])([+-]?\d{1,3}\.\d{4,8})[\x09-\x0D\x20]*[,;]"
    r"[\x09-\x0D\x20]*"
    r"([+-]?\d{1,3}\.\d{4,8})(?![\d.])",
    re.ASCII,
)
FIXED_FILENAMES = (
    "README",
    "Dockerfile",
    "Makefile",
    "CMakeLists.txt",
    "pyproject.toml",
    "requirements.txt",
    ".env",
    "goal.md",
    "email.json",
)
FIXED_SUFFIX_PATTERN = re.compile(
    r"\.(?:md|json|fit|gpx|tcx|sqlite|db|toml|yaml|yml|txt|env|ini|cfg|conf|pem|key)"
    r"(?![A-Za-z0-9])"
)
ALLOWED_SLASH_TOKENS = ("跑步/攀岩", "RHR/HRV", "min/km")
VO2_UNIT = "ml/kg/min"
ASCII_LOWER_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "_shared/schemas"


def _prompt_template_path() -> Path:
    return (
        Path(__file__).resolve().parents[2] / "_shared/prompts/weekly-content-v4-v2.txt"
    )


def _prompt_template_v3_path() -> Path:
    return (
        Path(__file__).resolve().parents[2] / "_shared/prompts/weekly-content-v4-v3.txt"
    )


def _prompt_template_v4_path() -> Path:
    return (
        Path(__file__).resolve().parents[2] / "_shared/prompts/weekly-content-v4-v4.txt"
    )


def _goal_template_path() -> Path:
    return Path(__file__).resolve().parents[3] / "goal.module.md"


def _regular_source_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return not path.is_symlink() and stat.S_ISREG(metadata.st_mode)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_authoritative_contracts() -> dict[str, Any]:
    """Return source-owned contracts only when their frozen bytes still match."""

    wire_path = _schema_root() / "weekly_ai_result_v3_codex.schema.json"
    context_path = _schema_root() / "m11_v4_weekly_model_context_v2.schema.json"
    training_goal_path = _schema_root() / "training_goal_v1.schema.json"
    weekly_evidence_path = _schema_root() / "weekly_training_evidence_v2.schema.json"
    health_fact_path = _schema_root() / "health_fact_v2.schema.json"
    prompt_template_path = _prompt_template_path()
    goal_template_path = _goal_template_path()
    if (
        not _regular_source_file(wire_path)
        or _sha256(wire_path) != FROZEN_WIRE_SCHEMA_SHA256
    ):
        raise ValueError("weekly_model_wire_schema_source_drift")
    if (
        not _regular_source_file(context_path)
        or _sha256(context_path) != FROZEN_CONTEXT_SCHEMA_SHA256
    ):
        raise ValueError("weekly_model_context_schema_source_drift")
    if (
        not _regular_source_file(training_goal_path)
        or _sha256(training_goal_path) != FROZEN_TRAINING_GOAL_SCHEMA_SHA256
    ):
        raise ValueError("weekly_training_goal_schema_source_drift")
    if (
        not _regular_source_file(weekly_evidence_path)
        or _sha256(weekly_evidence_path) != FROZEN_WEEKLY_EVIDENCE_SCHEMA_SHA256
    ):
        raise ValueError("weekly_evidence_schema_source_drift")
    if (
        not _regular_source_file(health_fact_path)
        or _sha256(health_fact_path) != FROZEN_HEALTH_FACT_SCHEMA_SHA256
    ):
        raise ValueError("weekly_health_fact_schema_source_drift")
    if (
        not _regular_source_file(prompt_template_path)
        or _sha256(prompt_template_path) != FROZEN_PROMPT_TEMPLATE_SHA256
    ):
        raise ValueError("weekly_model_prompt_template_source_drift")
    if (
        not _regular_source_file(goal_template_path)
        or _sha256(goal_template_path) != FROZEN_GOAL_TEMPLATE_SHA256
    ):
        raise ValueError("weekly_model_goal_template_source_drift")
    return {
        "wire_schema_path": wire_path,
        "wire_schema_sha256": FROZEN_WIRE_SCHEMA_SHA256,
        "context_schema_path": context_path,
        "context_schema_sha256": FROZEN_CONTEXT_SCHEMA_SHA256,
        "training_goal_schema_path": training_goal_path,
        "training_goal_schema_sha256": FROZEN_TRAINING_GOAL_SCHEMA_SHA256,
        "weekly_evidence_schema_path": weekly_evidence_path,
        "weekly_evidence_schema_sha256": FROZEN_WEEKLY_EVIDENCE_SCHEMA_SHA256,
        "health_fact_schema_path": health_fact_path,
        "health_fact_schema_sha256": FROZEN_HEALTH_FACT_SCHEMA_SHA256,
        "prompt_template_path": prompt_template_path,
        "prompt_template_sha256": FROZEN_PROMPT_TEMPLATE_SHA256,
        "goal_template_path": goal_template_path,
        "goal_template_sha256": FROZEN_GOAL_TEMPLATE_SHA256,
    }


def require_authoritative_contracts_v3() -> dict[str, Any]:
    """Return the VC-010 decision/Host/Reader contracts when bytes match."""

    root = _schema_root()
    paths = {
        "business_schema": root / "weekly_model_decision_v1.schema.json",
        "wire_schema": root / "weekly_model_decision_v1_codex.schema.json",
        "ai_result_schema": root / "weekly_ai_result_v4.schema.json",
        "reader_schema": root / "weekly_reader_content_v2.schema.json",
        "context_schema": root / "m11_v4_weekly_model_context_v2.schema.json",
        "training_goal_schema": root / "training_goal_v1.schema.json",
        "weekly_evidence_schema": root / "weekly_training_evidence_v2.schema.json",
        "health_fact_schema": root / "health_fact_v2.schema.json",
        "prompt_template": _prompt_template_v3_path(),
        "goal_template": _goal_template_path(),
    }
    expected = {
        "business_schema": FROZEN_DECISION_BUSINESS_SCHEMA_SHA256,
        "wire_schema": FROZEN_DECISION_WIRE_SCHEMA_SHA256,
        "ai_result_schema": FROZEN_AI_RESULT_V4_SCHEMA_SHA256,
        "reader_schema": FROZEN_READER_V2_SCHEMA_SHA256,
        "context_schema": FROZEN_CONTEXT_SCHEMA_SHA256,
        "training_goal_schema": FROZEN_TRAINING_GOAL_SCHEMA_SHA256,
        "weekly_evidence_schema": FROZEN_WEEKLY_EVIDENCE_SCHEMA_SHA256,
        "health_fact_schema": FROZEN_HEALTH_FACT_SCHEMA_SHA256,
        "prompt_template": FROZEN_PROMPT_TEMPLATE_V3_SHA256,
        "goal_template": FROZEN_GOAL_TEMPLATE_SHA256,
    }
    for name, path in paths.items():
        if not _regular_source_file(path) or _sha256(path) != expected[name]:
            raise ValueError(f"weekly_model_{name}_source_drift")
    return {f"{name}_path": path for name, path in paths.items()} | {
        f"{name}_sha256": digest for name, digest in expected.items()
    }


def require_authoritative_contracts_v4() -> dict[str, Any]:
    """Return VC-010 contracts with the r19 Schema-derived Prompt."""

    contracts = require_authoritative_contracts_v3()
    prompt_path = _prompt_template_v4_path()
    if (
        not _regular_source_file(prompt_path)
        or _sha256(prompt_path) != FROZEN_PROMPT_TEMPLATE_V4_SHA256
    ):
        raise ValueError("weekly_model_prompt_template_source_drift")
    contracts["prompt_template_path"] = prompt_path
    contracts["prompt_template_sha256"] = FROZEN_PROMPT_TEMPLATE_V4_SHA256
    return contracts


def _contains_ascii_email(value: str) -> bool:
    for match in EMAIL_PATTERN.finditer(value):
        before = value[match.start() - 1] if match.start() else ""
        after = value[match.end()] if match.end() < len(value) else ""
        if (before and before.isalnum()) or (after and after.isalnum()):
            continue
        return True
    return False


def _ascii_lower(value: str) -> str:
    """Lower only ASCII A-Z and preserve every other Unicode code point."""

    return value.translate(ASCII_LOWER_TRANSLATION)


def _contains_activity_label(value: str) -> bool:
    """Normalize only a candidate label while preserving raw delimiter semantics."""

    for index, delimiter in enumerate(value):
        if delimiter not in ACTIVITY_NAME_DELIMITERS:
            continue
        if not value[index + 1 :].lstrip():
            continue
        candidate = unicodedata.normalize("NFKC", value[:index].rstrip())
        candidate = _ascii_lower(candidate)
        if any(candidate.endswith(label) for label in ACTIVITY_NAME_LABELS):
            return True
    return False


def _contains_coordinate_pair(value: str) -> bool:
    for match in COORDINATE_PAIR_PATTERN.finditer(value):
        latitude = float(match.group(1))
        longitude = float(match.group(2))
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return True
    return False


def _contains_fixed_filename(value: str) -> bool:
    lowered = _ascii_lower(value)
    for filename in FIXED_FILENAMES:
        target = _ascii_lower(filename)
        start = 0
        while (index := lowered.find(target, start)) >= 0:
            end = index + len(target)
            before = lowered[index - 1] if index else ""
            after = lowered[end] if end < len(lowered) else ""
            if not (before and (before.isalnum() or before in "._-")) and not (
                after and (after.isalnum() or after in "._-")
            ):
                return True
            start = index + 1
    return bool(FIXED_SUFFIX_PATTERN.search(lowered))


def _contains_forbidden_path(
    value: str, *, additional_allowed_tokens: tuple[str, ...] = ()
) -> bool:
    """Apply the finite filename and slash blocker matrix."""

    remaining = value
    for index, token in enumerate((*ALLOWED_SLASH_TOKENS, *additional_allowed_tokens)):
        remaining = remaining.replace(token, f"SAFE_TOKEN_{index}")
    return "/" in remaining or "\\" in remaining or _contains_fixed_filename(remaining)


def _schema_bound_vo2_unit_paths(value: object) -> frozenset[str]:
    """Return the two exact VO2 unit paths only for a valid typed health fact."""

    if not isinstance(value, dict):
        return frozenset()
    evidence = value.get("weekly_evidence")
    if not isinstance(evidence, dict):
        return frozenset()
    paths: set[str] = set()
    for day_index, health_day in enumerate(evidence.get("health_days", [])):
        if not isinstance(health_day, dict):
            continue
        for fact_index, fact in enumerate(health_day.get("facts", [])):
            if not isinstance(fact, dict):
                continue
            fact_value = fact.get("value")
            if (
                fact.get("metric_code") != "max_metrics:vo2_max"
                or fact.get("status") != "available"
                or fact.get("unit") != VO2_UNIT
                or not isinstance(fact_value, dict)
                or fact_value.get("unit") != VO2_UNIT
            ):
                continue
            base = f"$.weekly_evidence.health_days[{day_index}].facts[{fact_index}]"
            paths.add(f"{base}.unit")
            paths.add(f"{base}.value.unit")
    return frozenset(paths)


def _privacy_errors(
    value: object,
    path: str = "$",
    *,
    allowed_vo2_unit_paths: frozenset[str] = frozenset(),
) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(
                r"[^a-z0-9]", "", unicodedata.normalize("NFKC", str(key)).lower()
            )
            if any(fragment in normalized for fragment in PRIVATE_FIELD_FRAGMENTS):
                errors.append(f"{path}.{key}:private_field")
            errors.extend(
                _privacy_errors(
                    child,
                    f"{path}.{key}",
                    allowed_vo2_unit_paths=allowed_vo2_unit_paths,
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(
                _privacy_errors(
                    child,
                    f"{path}[{index}]",
                    allowed_vo2_unit_paths=allowed_vo2_unit_paths,
                )
            )
    elif isinstance(value, str):
        ascii_lowered_value = _ascii_lower(value)
        additional_allowed_tokens = (
            (VO2_UNIT,) if path in allowed_vo2_unit_paths and value == VO2_UNIT else ()
        )
        if (
            _contains_ascii_email(value)
            or SECRET_ASSIGNMENT_PATTERN.search(ascii_lowered_value)
            or BEARER_PATTERN.search(ascii_lowered_value)
            or AUTHORIZATION_PATTERN.search(ascii_lowered_value)
            or GPS_PATTERN.search(ascii_lowered_value)
            or _contains_activity_label(value)
            or _contains_coordinate_pair(value)
            or _contains_forbidden_path(
                value, additional_allowed_tokens=additional_allowed_tokens
            )
        ):
            errors.append(f"{path}:private_value")
    return errors


def _technical_identity_errors(evidence: object) -> list[str]:
    if not isinstance(evidence, dict):
        return []
    errors: list[str] = []
    owners: dict[str, int] = {}
    for activity in evidence.get("all_activities", []):
        if not isinstance(activity, dict):
            continue
        activity_id = activity.get("activity_inventory_id")
        raw_file_id = activity.get("raw_file_id")
        raw_sha256 = activity.get("raw_sha256")
        if not isinstance(activity_id, int) or not isinstance(raw_file_id, int):
            continue
        for metric in activity.get("technical_metrics", []):
            if not isinstance(metric, dict) or not isinstance(
                metric.get("metric_code"), str
            ):
                errors.append("weekly_evidence:technical_identity")
                continue
            reference = (
                f"activity:{activity_id}:raw:{raw_file_id}:{raw_sha256}:"
                f"metric:{metric['metric_code']}"
            )
            if metric.get("evidence_refs") != [reference]:
                errors.append("weekly_evidence:technical_identity")
                continue
            previous_owner = owners.get(reference)
            if previous_owner is not None and previous_owner != activity_id:
                errors.append("weekly_evidence:technical_identity")
            owners[reference] = activity_id
    return errors


def validate_model_context_v2(value: object) -> list[str]:
    """Return stable errors for the complete bounded weekly model context."""

    context_schema_errors = validate_payload(value, SCHEMA_VERSION)
    allowed_vo2_unit_paths = (
        _schema_bound_vo2_unit_paths(value)
        if not context_schema_errors
        else frozenset()
    )
    privacy_errors = _privacy_errors(
        value, allowed_vo2_unit_paths=allowed_vo2_unit_paths
    )
    if not isinstance(value, dict):
        return sorted({"$:object_required", *privacy_errors})
    errors = list(privacy_errors)
    if context_schema_errors:
        errors.append("$:context_schema")
    if set(value) != ROOT_FIELDS:
        errors.append("$:fields")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version:const")
    goal = value.get("training_goal")
    if validate_payload(goal, "training_goal_v1"):
        errors.append("training_goal:schema")
    evidence = value.get("weekly_evidence")
    if not isinstance(evidence, dict):
        errors.append("weekly_evidence:object_required")
    else:
        if validate_payload(evidence, "weekly_training_evidence_v2"):
            errors.append("weekly_evidence:schema")
        for index, health_day in enumerate(evidence.get("health_days", [])):
            if not isinstance(health_day, dict):
                errors.append(f"weekly_evidence:health_day_{index}")
                continue
            if validate_health_facts_vc002(
                health_day.get("facts"),
                health_date=str(health_day.get("health_date")),
                sleep_wake_date=str(health_day.get("sleep_wake_date")),
            ):
                errors.append(f"weekly_evidence:health_day_{index}")
        errors.extend(_technical_identity_errors(evidence))
        if evidence.get("period") != EXPECTED_ACTIVITY_PERIOD:
            errors.append("weekly_evidence:period")
        if value.get("activity_period") != evidence.get("period"):
            errors.append("activity_period:lineage")
        if value.get("allowed_technical_activity_refs") != evidence.get("key_run_refs"):
            errors.append("allowed_technical_activity_refs:lineage")
        if evidence.get("provider_calls") != 0 or evidence.get("raw_reads") != 0:
            errors.append("weekly_evidence:external_boundary")
    if value.get("activity_period") != EXPECTED_ACTIVITY_PERIOD:
        errors.append("activity_period:dates")
    if value.get("next_plan_dates") != list(EXPECTED_PLAN_DATES):
        errors.append("next_plan_dates:dates")
    if value.get("provider_calls") != 0:
        errors.append("provider_calls:const")
    if value.get("external_actions") != 0:
        errors.append("external_actions:const")
    return sorted(set(errors))


def require_model_context_v2(value: object) -> dict[str, Any]:
    errors = validate_model_context_v2(value)
    if errors:
        raise ValueError("weekly_model_context_invalid:" + ",".join(errors[:5]))
    assert isinstance(value, dict)
    return value


def canonical_prompt(template_bytes: bytes, context: object) -> bytes:
    """Bind the frozen prompt template to the canonical validated context."""

    require_model_context_v2(context)
    return template_bytes + b"\n" + canonical_json(context).encode("utf-8") + b"\n"
