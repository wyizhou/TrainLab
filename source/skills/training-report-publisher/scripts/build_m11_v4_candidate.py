#!/usr/bin/env python3
"""Build the owner-only M11 v4 content-review Candidate.

Preparation reuses immutable v2 health prose, derives seven complete daily
observations while daily raw access is permitted, and writes the bounded weekly
model context.  Finalization accepts one already-generated weekly v3 result.
Neither mode invokes a Provider or a model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.scripts.training_goal_v1 import (
    TrainingGoalContractError,
    parse_training_goal_v1,
)
from skills._shared.state import (
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
)

REPORT_DATES = tuple(f"2026-08-{day:02d}" for day in range(12, 19))
ACTIVITY_DATES = tuple(f"2026-08-{day:02d}" for day in range(11, 18))
PLAN_DATES = tuple(f"2026-08-{day:02d}" for day in range(19, 26))
HEALTH_FACT_SPECS = {
    "sleep:main_sleep": ("sleep", "seconds"),
    "rhr:resting_heart_rate": ("rhr", "bpm"),
    "hrv:hrv": ("hrv", "ms"),
    "heart_rates:heart_rate": ("heart_rates", "bpm"),
    "max_metrics:vo2_max": ("max_metrics", "ml/kg/min"),
    "weigh_ins:weight": ("weigh_ins", "kg"),
}
SOURCE_SCHEMAS = {
    "daily_ai_result_v2": 7,
    "daily_presentation_evidence_v1": 7,
    "training_plan_v2": 2,
}


class CandidateV4Error(ValueError):
    """The content Candidate cannot be built without weakening A-018."""


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateV4Error("m11_v4_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
COACH = _load_module(
    "trainlab_content_first_v4_builder",
    SCRIPT_ROOT / "training-coach/scripts/content_first_v4.py",
)
ACTIVITY = _load_module(
    "trainlab_activity_evidence_v4_builder",
    SCRIPT_ROOT / "training-coach/scripts/activity_evidence.py",
)
CONTEXT = _load_module(
    "trainlab_build_context_v4_builder",
    SCRIPT_ROOT / "training-coach/scripts/build_context.py",
)
MODEL_CONTEXT = _load_module(
    "trainlab_model_context_v4_builder",
    SCRIPT_ROOT / "training-coach/scripts/model_context_v4.py",
)
READER = _load_module(
    "trainlab_reader_content_v4_builder",
    SCRIPT_ROOT / "training-report-publisher/scripts/reader_content_v4.py",
)


def _read_only(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"file:{quote(str(database.resolve()), safe='/')}?mode=ro&immutable=1",
        uri=True,
    )


def _owner_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CandidateV4Error("m11_v4_directory_not_owner_only")


def _atomic_owner_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise CandidateV4Error("m11_v4_artifact_empty")
    _owner_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup_database(source: Path, target: Path) -> None:
    _owner_directory(target.parent)
    source_connection = _read_only(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    target.chmod(0o600)


def _copy_registered_raw(
    parent_database: Path, parent_source: Path, candidate_source: Path
) -> dict[str, Any]:
    connection = _read_only(parent_database)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,byte_size,sha256 FROM raw_files "
            "WHERE integrity_state='verified' ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise CandidateV4Error("m11_v4_registered_raw_missing")
    total = 0
    manifest: list[dict[str, Any]] = []
    source_root = (parent_source / "state/raw").resolve()
    target_root = (candidate_source / "state/raw").absolute()
    _owner_directory(target_root)
    for raw_id, relative_text, byte_size, digest in rows:
        relative = Path(str(relative_text))
        if relative.is_absolute() or ".." in relative.parts:
            raise CandidateV4Error("m11_v4_registered_raw_path_invalid")
        source = (source_root / relative).absolute()
        target = (target_root / relative).absolute()
        metadata = source.lstat()
        if (
            source.resolve(strict=True) != source
            or not source.is_relative_to(source_root)
            or source.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != int(byte_size)
            or _sha(source) != str(digest)
        ):
            raise CandidateV4Error("m11_v4_registered_raw_invalid")
        _owner_directory(target.parent)
        temporary = target.with_name(f".{target.name}.copy")
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            os.fchmod(target_handle.fileno(), 0o600)
            shutil.copyfileobj(source_handle, target_handle, 1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        if temporary.stat().st_size != int(byte_size) or _sha(temporary) != str(digest):
            temporary.unlink(missing_ok=True)
            raise CandidateV4Error("m11_v4_registered_raw_copy_invalid")
        os.replace(temporary, target)
        total += int(byte_size)
        manifest.append(
            {
                "raw_file_id": int(raw_id),
                "relative_path": str(relative),
                "byte_size": int(byte_size),
                "sha256": str(digest),
            }
        )
    return {
        "count": len(manifest),
        "bytes": total,
        "manifest_sha256": sha256_text(canonical_json(manifest)),
    }


def _load_outputs(database: Path, schema_name: str) -> list[dict[str, Any]]:
    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT id,period_start_date,period_end_date,content_json,content_sha256 "
            "FROM skill_outputs WHERE schema_name=? ORDER BY period_start_date,id",
            (schema_name,),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "output_id": int(row[0]),
            "period_start_date": row[1],
            "period_end_date": row[2],
            "payload": json.loads(str(row[3])),
            "sha256": str(row[4]),
        }
        for row in rows
    ]


def _output_sha(database: Path, output_id: int) -> str:
    connection = _read_only(database)
    try:
        row = connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise CandidateV4Error("m11_v4_output_missing")
    return str(row[0])


def _append(
    database: Path,
    *,
    skill_name: str,
    operation: str,
    schema_name: str,
    logical_key: str,
    payload: dict[str, Any],
    output_kind: str,
    period_start: str,
    period_end: str,
    lineage: Iterable[dict[str, Any]],
    text: str | None = None,
    html_text: str | None = None,
) -> int:
    errors = validate_payload(payload, schema_name)
    if errors:
        raise CandidateV4Error(f"m11_v4_{schema_name}_invalid:" + ",".join(errors[:3]))
    if text is None and output_kind in {"daily_summary", "weekly_summary"}:
        text = canonical_json(payload)
    manifest = {
        "schema_name": schema_name,
        "logical_key": logical_key,
        "payload_sha256": sha256_text(canonical_json(payload)),
        "provider_calls": 0,
        "external_actions": 0,
    }
    dedupe = sha256_text(canonical_json(manifest))
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"m11-v4:{dedupe}:attempt-1",
            workflow_key="weekly:2026-08-18",
            dedupe_key=dedupe,
            skill_name=skill_name,
            operation=operation,
            trigger_kind="manual",
            input_manifest=manifest,
            target_from_date=period_start,
            target_through_date=period_end,
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind=output_kind,
            logical_key=logical_key,
            schema_name=schema_name,
            schema_version=schema_name.rsplit("_v", 1)[-1],
            content_json=payload,
            content_text=text,
            content_html=html_text,
            lineage=lineage,
            period_start_date=period_start,
            period_end_date=period_end,
        )
        finish_run(connection, run_id, status="succeeded")
        return output_id
    finally:
        connection.close()


def _independent_activity_inventory(database: Path, activity_date: str) -> list[int]:
    """Read the authoritative activity set independently from report artifacts."""

    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT inventory.id,inventory.collection_state,"
            "SUM(CASE WHEN raw.integrity_state='verified' "
            "AND raw.file_format IN ('fit','gpx','tcx') THEN 1 ELSE 0 END) "
            "FROM activity_inventory inventory LEFT JOIN raw_files raw "
            "ON raw.activity_inventory_id=inventory.id "
            "WHERE inventory.activity_date=? GROUP BY inventory.id "
            "ORDER BY inventory.id",
            (activity_date,),
        ).fetchall()
    finally:
        connection.close()
    if any(
        str(state) != "complete" or int(raw_count) < 1 for _, state, raw_count in rows
    ):
        raise CandidateV4Error("m11_v4_activity_inventory_incomplete")
    return [int(row[0]) for row in rows]


def _health_facts_from_context(
    context: dict[str, Any], *, health_date: str, sleep_wake_date: str
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {code: [] for code in HEALTH_FACT_SPECS}
    for item in context.get("health", []):
        if not isinstance(item, dict) or not isinstance(item.get("metrics"), dict):
            raise CandidateV4Error("m11_v4_health_evidence_invalid")
        metrics = deepcopy_json(item["metrics"])
        resource = str(item.get("resource"))
        code = f"{resource}:{metrics.get('metric', 'summary')}"
        if code in grouped:
            grouped[code].append(item)
    result: list[dict[str, Any]] = []
    for code, (resource, unit) in HEALTH_FACT_SPECS.items():
        items = grouped[code]
        if not items:
            result.append(
                {
                    "metric_code": code,
                    "status": "missing",
                    "value": None,
                    "unit": None,
                    "observed_date": None,
                    "raw_refs": [],
                    "reason_code": "not_found",
                    "uncertainty": [],
                }
            )
            continue
        raw_refs = [
            {
                "raw_file_id": int(item["raw_file_id"]),
                "raw_sha256": str(item["sha256"]),
            }
            for item in items
        ]
        if len(items) != 1:
            result.append(
                {
                    "metric_code": code,
                    "status": "insufficient_data",
                    "value": None,
                    "unit": None,
                    "observed_date": None,
                    "raw_refs": raw_refs,
                    "reason_code": "conflicting_records",
                    "uncertainty": ["同一健康指标存在多个候选记录。"],
                }
            )
            continue
        item = items[0]
        metrics = deepcopy_json(item["metrics"])
        observed_date = str(
            metrics.get("observed_date")
            or (sleep_wake_date if resource == "sleep" else health_date)
        )
        if code in {"max_metrics:vo2_max", "weigh_ins:weight"}:
            try:
                observed = date.fromisoformat(observed_date)
                age_days = (date.fromisoformat(health_date) - observed).days
            except ValueError:
                result.append(
                    {
                        "metric_code": code,
                        "status": "insufficient_data",
                        "value": None,
                        "unit": None,
                        "observed_date": None,
                        "raw_refs": raw_refs,
                        "reason_code": "date_mismatch",
                        "uncertainty": ["已登记 raw 的观测日期无法验证。"],
                    }
                )
                continue
            metrics["age_days"] = age_days
            metrics["selection_kind"] = (
                "exact_date" if age_days == 0 else "latest_prior"
            )
        candidate = {
            "metric_code": code,
            "status": "available",
            "value": metrics,
            "unit": unit,
            "observed_date": observed_date,
            "raw_refs": raw_refs,
            "reason_code": None,
            "uncertainty": [],
        }
        if validate_payload(candidate, "health_fact_v2"):
            candidate = {
                "metric_code": code,
                "status": "insufficient_data",
                "value": None,
                "unit": None,
                "observed_date": None,
                "raw_refs": raw_refs,
                "reason_code": "incomplete",
                "uncertainty": ["已登记 raw 缺少完整的命名健康字段。"],
            }
        result.append(candidate)
    return result


def _independent_health_raw_ids(
    database: Path,
    *,
    health_date: str,
    sleep_wake_date: str,
    selected_facts: list[dict[str, Any]],
) -> list[int]:
    """Close exact-date health resources plus approved recent VO2/weight selections."""

    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT id FROM raw_files WHERE data_class='health' "
            "AND integrity_state='verified' AND ((data_date=? "
            "AND resource_kind NOT IN ('sleep','max_metrics','weigh_ins')) "
            "OR (data_date=? AND resource_kind='sleep')) ORDER BY id",
            (health_date, sleep_wake_date),
        ).fetchall()
    finally:
        connection.close()
    expected = {int(row[0]) for row in rows}
    expected.update(
        int(reference["raw_file_id"])
        for item in selected_facts
        if str(item.get("metric_code", "")).startswith(("max_metrics:", "weigh_ins:"))
        for reference in item.get("raw_refs", [])
        if isinstance(reference, dict) and isinstance(reference.get("raw_file_id"), int)
    )
    return sorted(expected)


def deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _source_lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {"output_id": row["output_id"], "output_sha256": row["sha256"]}


def _prepare_daily(
    parent_database: Path,
    parent_source: Path,
    candidate_database: Path,
    candidate_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    daily_ai_rows = _load_outputs(parent_database, "daily_ai_result_v2")
    presentation_rows = _load_outputs(parent_database, "daily_presentation_evidence_v1")
    plans = _load_outputs(parent_database, "training_plan_v2")
    if len(daily_ai_rows) != 7 or len(presentation_rows) != 7 or len(plans) != 2:
        raise CandidateV4Error("m11_v4_source_output_count_invalid")
    ai_by_date = {str(row["period_start_date"]): row for row in daily_ai_rows}
    presentation_by_date = {
        str(row["period_start_date"]): row for row in presentation_rows
    }
    original_plan_row = next(
        (row for row in plans if row["period_start_date"] == "2026-08-12"), None
    )
    if original_plan_row is None:
        raise CandidateV4Error("m11_v4_original_plan_missing")
    plan_items = {
        str(item["date"]): item
        for item in original_plan_row["payload"].get("items", [])
    }
    if set(REPORT_DATES) - set(plan_items):
        raise CandidateV4Error("m11_v4_original_plan_dates_missing")
    observations: list[dict[str, Any]] = []
    health_analyses: list[dict[str, Any]] = []
    daily_manifest: dict[str, Any] = {}
    for report_date, activity_date in zip(REPORT_DATES, ACTIVITY_DATES):
        source_ai = ai_by_date[report_date]
        source_presentation = presentation_by_date[report_date]
        ai_payload = source_ai["payload"]
        presentation = source_presentation["payload"]
        if (
            ai_payload.get("report_date") != report_date
            or presentation.get("report_date") != report_date
            or presentation.get("review_date") != activity_date
            or presentation.get("sleep_wake_date") != report_date
        ):
            raise CandidateV4Error("m11_v4_daily_date_contract_invalid")
        health_analysis = COACH.daily_health_analysis_v3_from_v2(ai_payload)
        health_id = _append(
            candidate_database,
            skill_name="training-coach",
            operation="daily_coach",
            schema_name="daily_health_analysis_v3",
            logical_key=f"training-coach:daily-health-v3:{report_date}",
            payload=health_analysis,
            output_kind="daily_summary",
            period_start=report_date,
            period_end=report_date,
            lineage=[_source_lineage(source_ai)],
        )
        authoritative_activity_ids = _independent_activity_inventory(
            parent_database, activity_date
        )
        presentation_activities = {
            int(item["activity_inventory_id"]): item
            for item in presentation.get("activities", [])
            if isinstance(item, dict)
            and isinstance(item.get("activity_inventory_id"), int)
        }
        if set(authoritative_activity_ids) != set(presentation_activities):
            raise CandidateV4Error("m11_v4_daily_activity_inventory_mismatch")
        activity_inputs: list[dict[str, Any]] = []
        for activity_id in authoritative_activity_ids:
            item = presentation_activities[activity_id]
            activity = ACTIVITY.build_activity_technical_input(
                parent_database,
                parent_source,
                activity_id,
                raw_file_id=int(item["raw_file_id"]),
            )
            for source_key, target_key in (
                ("activity_kind", "activity_kind"),
                ("distance_km", "distance_km"),
                ("duration_seconds", "duration_seconds"),
                ("heart_rate_average_bpm", "average_heart_rate_bpm"),
                ("heart_rate_maximum_bpm", "maximum_heart_rate_bpm"),
            ):
                if source_key in item:
                    activity[target_key] = item[source_key]
            activity_inputs.append(activity)
        bounded_context = CONTEXT.build_daily_context(
            parent_database,
            parent_source,
            date.fromisoformat(report_date),
        )
        if bounded_context.get("status") != "ready":
            raise CandidateV4Error("m11_v4_daily_bounded_context_blocked")
        health_facts = _health_facts_from_context(
            bounded_context,
            health_date=activity_date,
            sleep_wake_date=report_date,
        )
        expected_health_raw_ids = _independent_health_raw_ids(
            parent_database,
            health_date=activity_date,
            sleep_wake_date=report_date,
            selected_facts=health_facts,
        )
        observation = COACH.build_daily_completed_observation(
            report_date=report_date,
            activity_date=activity_date,
            health_date=activity_date,
            sleep_wake_date=report_date,
            activities=activity_inputs,
            expected_activity_count=len(authoritative_activity_ids),
            health_facts=health_facts,
            expected_health_raw_file_ids=expected_health_raw_ids,
            health_analysis_ref={
                "output_id": health_id,
                "sha256": _output_sha(candidate_database, health_id),
            },
        )
        observation_id = _append(
            candidate_database,
            skill_name="training-coach",
            operation="daily_coach",
            schema_name="daily_completed_observation_v1",
            logical_key=f"training-coach:daily-observation-v1:{report_date}",
            payload=observation,
            output_kind="bounded_evidence",
            period_start=report_date,
            period_end=report_date,
            lineage=[
                _source_lineage(source_presentation),
                {
                    "output_id": health_id,
                    "output_sha256": _output_sha(candidate_database, health_id),
                },
            ],
        )
        observation["observation_ref"] = {
            "output_id": observation_id,
            "sha256": _output_sha(candidate_database, observation_id),
        }
        fixed_course = COACH.fixed_course_v3_from_v2(plan_items[report_date])
        course_ref = {
            "plan_output_id": original_plan_row["output_id"],
            "plan_output_sha256": original_plan_row["sha256"],
            "course_sha256": sha256_text(canonical_json(fixed_course)),
        }
        reader = READER.build_daily_reader_content_v1(
            observation,
            health_analysis,
            planned_course=fixed_course,
            planned_course_ref=course_ref,
        )
        markdown = READER.render_reader_markdown(reader)
        lowfi = READER.render_lowfi_html(reader)
        reader_id = _append(
            candidate_database,
            skill_name="training-report-publisher",
            operation="render_daily",
            schema_name="daily_reader_content_v1",
            logical_key=f"training-report-publisher:daily-reader-v1:{report_date}",
            payload=reader,
            output_kind="report_artifact",
            period_start=report_date,
            period_end=report_date,
            lineage=[
                {
                    "output_id": observation_id,
                    "output_sha256": observation["observation_ref"]["sha256"],
                },
                {
                    "output_id": health_id,
                    "output_sha256": _output_sha(candidate_database, health_id),
                },
                _source_lineage(original_plan_row),
            ],
            text=markdown,
            html_text=lowfi,
        )
        artifact_root = candidate_root / "artifacts/daily" / report_date
        _atomic_owner_write(
            artifact_root / "reader.json", canonical_json(reader).encode()
        )
        _atomic_owner_write(artifact_root / "report.md", markdown.encode())
        _atomic_owner_write(artifact_root / "report.html", lowfi.encode())
        observations.append(observation)
        health_analyses.append(health_analysis)
        daily_manifest[report_date] = {
            "source_ai": _source_lineage(source_ai),
            "source_presentation": _source_lineage(source_presentation),
            "health_output_id": health_id,
            "observation_output_id": observation_id,
            "reader_output_id": reader_id,
            "planned_course_ref": course_ref,
        }
    return observations, health_analyses, daily_manifest


def _parse_training_goal_v1(goal_text: str) -> dict[str, Any]:
    try:
        return parse_training_goal_v1(goal_text)
    except TrainingGoalContractError as exc:
        raise CandidateV4Error("m11_v4_training_goal_contract_invalid") from exc


def _bounded_model_context(
    evidence: dict[str, Any], training_goal: dict[str, Any]
) -> dict[str, Any]:
    context = {
        "schema_version": "m11_v4_weekly_model_context_v2",
        "activity_period": evidence["period"],
        "next_plan_dates": list(PLAN_DATES),
        "training_goal": training_goal,
        "weekly_evidence": evidence,
        "allowed_technical_activity_refs": evidence["key_run_refs"],
        "provider_calls": 0,
        "external_actions": 0,
    }
    try:
        MODEL_CONTEXT.require_model_context_v2(context)
    except ValueError as exc:
        if "private_field" in str(exc) or "private_value" in str(exc):
            raise CandidateV4Error("m11_v4_model_context_private_field") from exc
        raise CandidateV4Error("m11_v4_model_context_invalid") from exc
    return context


def _separate_model_work_root(candidate_root: Path) -> Path:
    name = tempfile.mkdtemp(prefix="trainlab-m11-v4-model-", dir=candidate_root.parent)
    work_root = Path(name)
    work_root.chmod(0o700)
    resolved_candidate = candidate_root.resolve()
    resolved_work = work_root.resolve()
    if (
        resolved_candidate == resolved_work
        or resolved_candidate in resolved_work.parents
        or resolved_work in resolved_candidate.parents
    ):
        raise CandidateV4Error("m11_v4_model_work_root_not_isolated")
    return work_root


def prepare_candidate(parent_candidate: Path, candidate_root: Path) -> dict[str, Any]:
    try:
        authoritative_contracts = MODEL_CONTEXT.require_authoritative_contracts()
    except ValueError as exc:
        raise CandidateV4Error(str(exc)) from exc
    if candidate_root.exists():
        raise CandidateV4Error("m11_v4_candidate_exists")
    _owner_directory(candidate_root)
    parent_source = parent_candidate / "source"
    parent_database = parent_source / "state/trainlab.db"
    candidate_source = candidate_root / "source"
    candidate_database = candidate_source / "state/trainlab.db"
    _backup_database(parent_database, candidate_database)
    raw_summary = _copy_registered_raw(parent_database, parent_source, candidate_source)
    observations, _health, daily_manifest = _prepare_daily(
        parent_database, parent_source, candidate_database, candidate_root
    )
    planned_dates = {
        str(item["date"])
        for row in _load_outputs(parent_database, "training_plan_v2")
        if row["period_start_date"] == "2026-08-12"
        for item in row["payload"].get("items", [])
        if item.get("session_type") != "rest"
    }
    evidence = COACH.build_weekly_training_evidence_v2(
        observations, planned_activity_dates=planned_dates
    )
    evidence_id = _append(
        candidate_database,
        skill_name="weekly-fitness-summary",
        operation="summarize_week",
        schema_name="weekly_training_evidence_v2",
        logical_key="weekly-fitness-summary:evidence-v2:2026-08-11/2026-08-17",
        payload=evidence,
        output_kind="bounded_evidence",
        period_start="2026-08-11",
        period_end="2026-08-17",
        lineage=[
            {
                "output_id": int(item["observation_ref"]["output_id"]),
                "output_sha256": str(item["observation_ref"]["sha256"]),
            }
            for item in observations
        ],
    )
    goal_path = parent_source / "goal.md"
    goal_bytes = goal_path.read_bytes()
    goal_text = goal_bytes.decode("utf-8")
    training_goal = _parse_training_goal_v1(goal_text)
    context = _bounded_model_context(evidence, training_goal)
    ai_root = _separate_model_work_root(candidate_root)
    context_path = ai_root / "context.json"
    prompt_template = Path(authoritative_contracts["prompt_template_path"])
    prompt_payload = MODEL_CONTEXT.canonical_prompt(
        prompt_template.read_bytes(), context
    )
    prompt_path = ai_root / "prompt.txt"
    schema_source = Path(authoritative_contracts["wire_schema_path"])
    schema_path = ai_root / "weekly_ai_result_v3_codex.schema.json"
    _atomic_owner_write(context_path, canonical_json(context).encode())
    _atomic_owner_write(prompt_path, prompt_payload)
    _atomic_owner_write(schema_path, schema_source.read_bytes())
    manifest = {
        "schema_version": "m11_v4_content_candidate_v2",
        "status": "prepared",
        "parent_candidate": str(parent_candidate),
        "parent_database_sha256": _sha(parent_database),
        "candidate_database_sha256_before_ai": _sha(candidate_database),
        "raw_summary": raw_summary,
        "daily": daily_manifest,
        "weekly_evidence_output_id": evidence_id,
        "weekly_evidence_sha256": _output_sha(candidate_database, evidence_id),
        "ai_work_root": str(ai_root),
        "prompt_template_sha256": _sha(prompt_template),
        "repository_prompt_template_sha256": authoritative_contracts[
            "prompt_template_sha256"
        ],
        "goal_template_sha256": _sha(
            Path(authoritative_contracts["goal_template_path"])
        ),
        "repository_goal_template_sha256": authoritative_contracts[
            "goal_template_sha256"
        ],
        "prompt_sha256": _sha(prompt_path),
        "context_sha256": _sha(context_path),
        "wire_schema_sha256": _sha(schema_path),
        "repository_wire_schema_sha256": authoritative_contracts["wire_schema_sha256"],
        "context_contract_schema_sha256": authoritative_contracts[
            "context_schema_sha256"
        ],
        "training_goal_contract_schema_sha256": authoritative_contracts[
            "training_goal_schema_sha256"
        ],
        "training_goal_source_sha256": hashlib.sha256(goal_bytes).hexdigest(),
        "weekly_evidence_contract_schema_sha256": authoritative_contracts[
            "weekly_evidence_schema_sha256"
        ],
        "health_fact_contract_schema_sha256": authoritative_contracts[
            "health_fact_schema_sha256"
        ],
        "model_calls_authorized": 1,
        "model_calls_completed": 0,
        "provider_calls": 0,
        "external_actions": 0,
    }
    _atomic_owner_write(
        candidate_root / "candidate-manifest.json", canonical_json(manifest).encode()
    )
    return manifest


def finalize_candidate(candidate_root: Path, ai_result_path: Path) -> dict[str, Any]:
    manifest_path = candidate_root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "model_succeeded"
        or manifest.get("model_calls_completed") != 1
    ):
        raise CandidateV4Error("m11_v4_candidate_not_prepared")
    database = candidate_root / "source/state/trainlab.db"
    evidence_rows = _load_outputs(database, "weekly_training_evidence_v2")
    if len(evidence_rows) != 1:
        raise CandidateV4Error("m11_v4_weekly_evidence_missing")
    evidence_row = evidence_rows[0]
    result = json.loads(ai_result_path.read_text(encoding="utf-8"))
    errors = COACH.validate_weekly_ai_result_v3(result, evidence_row["payload"])
    if errors:
        raise CandidateV4Error(
            "m11_v4_weekly_ai_result_invalid:" + ",".join(errors[:3])
        )
    weekly_id = _append(
        database,
        skill_name="training-coach",
        operation="weekly_coach",
        schema_name="weekly_ai_result_v3",
        logical_key="training-coach:weekly-ai-v3:2026-08-11/2026-08-17",
        payload=result,
        output_kind="weekly_summary",
        period_start="2026-08-11",
        period_end="2026-08-17",
        lineage=[_source_lineage(evidence_row)],
    )
    reader = READER.build_weekly_reader_content_v1(result, evidence_row["payload"])
    markdown = READER.render_reader_markdown(reader)
    lowfi = READER.render_lowfi_html(reader)
    reader_id = _append(
        database,
        skill_name="training-report-publisher",
        operation="render_weekly",
        schema_name="weekly_reader_content_v1",
        logical_key="training-report-publisher:weekly-reader-v1:2026-08-11/2026-08-17",
        payload=reader,
        output_kind="report_artifact",
        period_start="2026-08-11",
        period_end="2026-08-17",
        lineage=[
            {"output_id": weekly_id, "output_sha256": _output_sha(database, weekly_id)},
            _source_lineage(evidence_row),
        ],
        text=markdown,
        html_text=lowfi,
    )
    artifact_root = candidate_root / "artifacts/weekly/2026-08-11--2026-08-17"
    _atomic_owner_write(artifact_root / "reader.json", canonical_json(reader).encode())
    _atomic_owner_write(artifact_root / "report.md", markdown.encode())
    _atomic_owner_write(artifact_root / "report.html", lowfi.encode())
    manifest.update(
        {
            "status": "ready_for_validation",
            "model_calls_completed": 1,
            "weekly_ai_output_id": weekly_id,
            "weekly_reader_output_id": reader_id,
            "ai_result_sha256": _sha(ai_result_path),
            "candidate_database_sha256_after_ai": _sha(database),
        }
    )
    _atomic_owner_write(manifest_path, canonical_json(manifest).encode())
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--parent-candidate", type=Path, required=True)
    prepare.add_argument("--candidate-root", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--candidate-root", type=Path, required=True)
    finalize.add_argument("--ai-result", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            prepare_candidate(args.parent_candidate, args.candidate_root)
            if args.command == "prepare"
            else finalize_candidate(args.candidate_root, args.ai_result)
        )
    except (CandidateV4Error, OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": result["status"], "provider_calls": 0, "external_actions": 0},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
