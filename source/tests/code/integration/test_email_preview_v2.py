from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    init_database,
)


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RENDER = _load(
    "trainlab_email_preview_v2_integration",
    "skills/training-report-publisher/scripts/render_email_v2.py",
)
CANDIDATE = _load(
    "trainlab_email_preview_v2_candidate",
    "skills/training-report-publisher/scripts/build_m11_preview_candidate.py",
)


def _source(database: Path, index: int = 0) -> int:
    context = {
        "schema_version": "daily_ai_context_v1",
        "status": "ready",
        "report_date": "2026-08-21",
        "review_date": "2026-08-20",
        "sleep_wake_date": "2026-08-21",
        "health": [
            {
                "raw_file_id": 10,
                "sha256": "a" * 64,
                "resource": "sleep",
                "data_date": "2026-08-21",
                "metrics": {
                    "resource": "sleep",
                    "duration_seconds": 25200,
                    "completeness": "complete",
                },
            },
            {
                "raw_file_id": 11,
                "sha256": "b" * 64,
                "resource": "rhr",
                "data_date": "2026-08-20",
                "metrics": {"resource": "rhr", "resting_heart_rate_bpm": 50},
            },
        ],
        "activities": [
            {
                "schema_version": "activity_overview_v1",
                "status": "ready",
                "activity_inventory_id": 4,
                "raw_file_id": 12,
                "raw_sha256": "d" * 64,
                "data_date": "2026-08-20",
                "format": "fit",
                "summary": {
                    "activity_kind": "running",
                    "distance_km": 5.0,
                    "duration_seconds": 1800,
                    "lap_count": 1,
                },
                "sequence_resolution_seconds": 30,
                "sequence": [
                    {
                        "offset_seconds": 0,
                        "sample_count": 30,
                        "metrics": {"heart_rate_bpm": 120},
                    },
                    {
                        "offset_seconds": 30,
                        "sample_count": 30,
                        "metrics": {"heart_rate_bpm": 130},
                    },
                ],
                "gps_included": False,
                "provider_calls": 0,
            }
        ],
        "recent_trend": {
            "schema_version": "recent_trend_v1",
            "days_available": 0,
            "sleep": {
                "average_hours": None,
                "insufficient_days": 0,
                "consecutive_insufficient_days": 0,
            },
            "recovery": {
                "caution_days": 0,
                "rhr_average": None,
                "rhr_change": None,
                "hrv_average": None,
                "hrv_change": None,
            },
            "running": {"distance_km": 0, "activity_count": 0, "activity_days": 0},
            "data_gaps": [],
            "sha256": "c" * 64,
        },
        "errors": [],
        "provider_calls": 0,
    }
    payload: dict[str, Any] = {
        "schema_version": "daily_ai_result_v1",
        "status": "succeeded",
        "error_code": None,
        "report_date": "2026-08-21",
        "review_date": "2026-08-20",
        "sleep_wake_date": "2026-08-21",
        "safety": "ready",
        "summary": "今天以恢复为主。",
        "bounded_metrics": [
            {
                "name": "main_sleep_duration",
                "value": 7,
                "unit": "hours",
                "evidence_ref": 10,
            },
            {
                "name": "resting_heart_rate",
                "value": 50,
                "unit": "bpm",
                "evidence_ref": 11,
            },
        ],
        "stop_conditions": ["不适时停止"],
        "evidence_refs": [
            {"raw_file_id": 10, "sha256": "a" * 64, "claim": "睡眠"},
            {"raw_file_id": 11, "sha256": "b" * 64, "claim": "静息心率"},
            {"raw_file_id": 12, "sha256": "d" * 64, "claim": "跑步活动"},
        ],
        "recent_trend_sha256": "c" * 64,
        "today_course": {},
        "provider_calls": 0,
    }
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"email-preview-source-{index}",
            workflow_key="daily:2026-08-21",
            dedupe_key=f"email-preview-source-{index}",
            skill_name="training-coach",
            operation="daily_coach",
            trigger_kind="manual",
            input_manifest={"mode": "daily", "context": context},
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="daily_summary",
            logical_key=f"email-preview-source-{index}",
            schema_name="daily_ai_result_v1",
            schema_version="1",
            title_text="daily",
            content_json=payload,
            content_text=payload["summary"],
            lineage=[],
            period_start_date="2026-08-21",
            period_end_date="2026-08-21",
        )
        finish_run(connection, run_id, status="succeeded")
        return output_id
    finally:
        connection.close()


def _recent_health_source(database: Path, report_date: str = "2026-08-21") -> int:
    payload = {
        "schema_version": "recent_health_metrics_v1",
        "status": "ready",
        "report_date": report_date,
        "review_date": "2026-08-20",
        "metrics": {
            "vo2_max": {
                "resource": "max_metrics",
                "status": "ready",
                "value": 51.0,
                "unit": "ml/kg/min",
                "observed_date": "2026-08-18",
                "age_days": 3,
                "selection_kind": "latest_prior",
                "lookback_days": 30,
                "raw_file_id": 105,
                "sha256": "e" * 64,
            },
            "weight": {
                "resource": "weigh_ins",
                "status": "ready",
                "value": 70.3,
                "unit": "kg",
                "observed_date": "2026-08-20",
                "age_days": 1,
                "selection_kind": "exact_date",
                "lookback_days": 14,
                "raw_file_id": 106,
                "sha256": "f" * 64,
            },
        },
        "provider_calls": 0,
    }
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"recent-health-{report_date}",
            workflow_key=f"daily:{report_date}",
            dedupe_key=f"recent-health-{report_date}",
            skill_name="training-report-publisher",
            operation="render_daily",
            trigger_kind="manual",
            input_manifest={"report_date": report_date},
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="bounded_evidence",
            logical_key=f"recent-health-{report_date}",
            schema_name="recent_health_metrics_v1",
            schema_version="1",
            content_json=payload,
            content_text=json.dumps(payload, sort_keys=True),
            period_start_date=report_date,
            period_end_date=report_date,
        )
        finish_run(connection, run_id, status="succeeded")
        return output_id
    finally:
        connection.close()


def test_owner_only_preview_persists_and_replays_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    database = init_database(tmp_path / "trainlab.db")
    source_output_id = _source(database)
    output_dir = tmp_path / "previews" / "preview"
    first = RENDER.write_preview(database, source_output_id, output_dir)
    connection = connect(database, read_only=True, immutable=True)
    try:
        before = connection.execute(
            "SELECT COUNT(*),group_concat(id,',') FROM skill_outputs"
        ).fetchone()
    finally:
        connection.close()
    second = RENDER.write_preview(database, source_output_id, output_dir)
    connection = connect(database, read_only=True, immutable=True)
    try:
        after = connection.execute(
            "SELECT COUNT(*),group_concat(id,',') FROM skill_outputs"
        ).fetchone()
        rows = connection.execute(
            "SELECT schema_name,content_json,title_text FROM skill_outputs "
            "WHERE schema_name IN ('daily_email_view_v1','daily_email_render_v2') "
            "ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    assert first == second
    assert tuple(before) == tuple(after)
    assert [row[0] for row in rows] == ["daily_email_view_v1", "daily_email_render_v2"]
    assert json.loads(rows[1][1])["subject"] == rows[1][2]
    assert first["provider_calls"] == 0
    assert first["external_actions"] == 0
    email_html = (output_dir / "report.html").read_text(encoding="utf-8")
    browser_html = (output_dir / "browser-preview.html").read_text(encoding="utf-8")
    assert "cid:" not in browser_html
    assert "assets/" in browser_html
    assert "cid:" in email_html
    assert browser_html != email_html
    expected = {*first["files"], "preview-receipt.json"}
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(output_dir.parent.stat().st_mode) == 0o700
    for path in output_dir.rglob("*"):
        metadata = path.lstat()
        assert not path.is_symlink()
        assert metadata.st_uid == os.getuid()
        if path.is_file():
            assert stat.S_IMODE(metadata.st_mode) == 0o600
            assert metadata.st_nlink == 1
            assert metadata.st_size > 0
        elif path.is_dir():
            assert stat.S_IMODE(metadata.st_mode) == 0o700


def test_daily_preview_overlays_recent_health_without_changing_ai_output(
    tmp_path: Path,
) -> None:
    database = init_database(tmp_path / "trainlab.db")
    source_output_id = _source(database)
    snapshot_output_id = _recent_health_source(database)
    connection = connect(database, read_only=True, immutable=True)
    try:
        before = connection.execute(
            "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
            (source_output_id,),
        ).fetchone()
    finally:
        connection.close()
    output_dir = tmp_path / "previews" / "corrected"
    receipt = RENDER.write_preview(
        database,
        source_output_id,
        output_dir,
        recent_health_output_id=snapshot_output_id,
    )
    view = json.loads((output_dir / "view.json").read_text(encoding="utf-8"))
    plain_text = (output_dir / "report.txt").read_text(encoding="utf-8")
    assert view["metrics"]["vo2_max"]["value"] == "51 ml/kg/min"
    assert view["metrics"]["vo2_max"]["detail"] == "更新于 2026-08-18"
    assert view["metrics"]["weight"]["value"] == "70.3 kg"
    assert "VO₂ Max：51 ml/kg/min｜更新于 2026-08-18" in plain_text
    assert "体重：70.3 kg｜更新于 2026-08-20" in plain_text
    sleep_value = view["metrics"]["sleep"]["value"]
    assert f"主睡眠：{sleep_value}\n" in plain_text
    assert f"主睡眠：{sleep_value}｜" not in plain_text
    assert receipt["provider_calls"] == 0
    connection = connect(database, read_only=True, immutable=True)
    try:
        after = connection.execute(
            "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
            (source_output_id,),
        ).fetchone()
        render_run = connection.execute(
            "SELECT sr.input_manifest_json,so.lineage_json FROM skill_outputs so "
            "JOIN skill_runs sr ON sr.id=so.skill_run_id "
            "WHERE so.id=?",
            (receipt["output_ids"]["email_render"],),
        ).fetchone()
    finally:
        connection.close()
    assert tuple(after) == tuple(before)
    manifest = json.loads(str(render_run[0]))
    lineage = json.loads(str(render_run[1]))
    assert manifest["recent_health_output_id"] == snapshot_output_id
    assert any(item.get("output_id") == snapshot_output_id for item in lineage)


def test_daily_preview_rejects_recent_health_for_another_report_date(
    tmp_path: Path,
) -> None:
    database = init_database(tmp_path / "trainlab.db")
    source_output_id = _source(database)
    snapshot_output_id = _recent_health_source(database, "2026-08-20")
    with pytest.raises(
        RENDER.EmailRenderError, match="email_recent_health_snapshot_invalid"
    ):
        RENDER.write_preview(
            database,
            source_output_id,
            tmp_path / "preview",
            recent_health_output_id=snapshot_output_id,
        )


@pytest.mark.parametrize("mutation", ["extra", "wide", "symlink", "hardlink", "empty"])
def test_preview_verifier_rejects_unmanifested_or_unsafe_artifacts(
    tmp_path: Path, mutation: str
) -> None:
    database = init_database(tmp_path / "trainlab.db")
    source_output_id = _source(database)
    output_dir = tmp_path / "preview"
    RENDER.write_preview(database, source_output_id, output_dir)
    target = output_dir / "report.txt"
    if mutation == "extra":
        extra = output_dir / "extra.txt"
        extra.write_text("unexpected", encoding="utf-8")
        extra.chmod(0o600)
    elif mutation == "wide":
        target.chmod(0o644)
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(output_dir / "report.html")
    elif mutation == "hardlink":
        link = output_dir / "hardlink.txt"
        os.link(target, link)
    else:
        target.write_bytes(b"")
    with pytest.raises(RENDER.EmailRenderError):
        RENDER.verify_preview(output_dir)


def test_preview_verifier_checks_receipt_permissions(tmp_path: Path) -> None:
    database = init_database(tmp_path / "trainlab.db")
    source_output_id = _source(database)
    output_dir = tmp_path / "preview"
    RENDER.write_preview(database, source_output_id, output_dir)
    (output_dir / "preview-receipt.json").chmod(0o644)
    with pytest.raises(RENDER.EmailRenderError, match="email_preview_receipt_invalid"):
        RENDER.verify_preview(output_dir)


def test_m11_candidate_uses_online_backup_and_preserves_parent(tmp_path: Path) -> None:
    parent = init_database(tmp_path / "parent.db")
    for index in range(8):
        _source(parent, index)
    parent_before = parent.read_bytes()
    candidate_root = tmp_path / "m11-candidate"
    receipt = CANDIDATE.build_candidate(parent, candidate_root)
    candidate = candidate_root / "source/state/trainlab.db"
    assert parent.read_bytes() == parent_before
    assert receipt["integrity_check"] == "ok"
    assert receipt["foreign_key_violations"] == 0
    assert receipt["eligible_source_outputs"] == 8
    assert receipt["copied_raw_files"] == 0
    assert receipt["copied_credentials"] == 0
    assert stat.S_IMODE(candidate_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(candidate.stat().st_mode) == 0o600


def test_m11_candidate_rejects_unsafe_parent_or_existing_root(tmp_path: Path) -> None:
    parent = init_database(tmp_path / "parent.db")
    parent.chmod(0o644)
    with pytest.raises(
        CANDIDATE.CandidateBuildError, match="m11_parent_database_invalid"
    ):
        CANDIDATE.build_candidate(parent, tmp_path / "candidate")
    parent.chmod(0o600)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    with pytest.raises(
        CANDIDATE.CandidateBuildError, match="m11_candidate_root_exists"
    ):
        CANDIDATE.build_candidate(parent, candidate_root)
