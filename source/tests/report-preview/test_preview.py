from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.analysis import preview
from src.analysis.delivery import AnalysisDeliveryState, RenderedDelivery


def _fake_pending() -> SimpleNamespace:
    artifact = SimpleNamespace(
        artifact_id=11,
        artifact_kind="weekly_training_plan",
        content_role="weekly_plan",
        revision_no=1,
        content_sha256="a" * 64,
        user_visible_text="未来七天计划",
        period_start_local_date="2026-08-10",
        period_end_local_date="2026-08-16",
        structured_content_json={
            "capacity_assessment": {
                "decision": "hold",
                "allowed_range_km": {"min": 20, "max": 22},
            },
            "course_contract": {"activity_kind": "running", "distance_km": 5},
        },
        created_at_utc="2026-08-14T00:00:00Z",
    )
    return SimpleNamespace(
        delivery_id=7,
        subject_id=1,
        analysis_run_id=4,
        run_key="analysis:preview",
        delivery_kind="plan_revision",
        idempotency_key="analysis-delivery:v2:test",
        artifacts=(artifact,),
    )


def test_preview_writes_owner_only_files_without_state_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = tmp_path / "instance"
    (instance / "state").mkdir(parents=True)
    (instance / "state" / "data.db").touch()
    (instance / "state").chmod(0o700)
    output = tmp_path / "preview"
    pending = _fake_pending()
    state = AnalysisDeliveryState(
        delivery_id=7,
        subject_id=1,
        analysis_run_id=4,
        status="pending",
        provider_message_id=None,
        provider_thread_id=None,
        sent_at_utc=None,
        last_verified_at_utc=None,
        error_code=None,
        error_summary=None,
    )
    monkeypatch.setattr(
        preview.AnalysisDeliveryRepository,
        "load_pending",
        lambda self, delivery_id: pending,
    )
    monkeypatch.setattr(
        preview.AnalysisDeliveryRepository,
        "read_state",
        lambda self, delivery_id: state,
    )
    monkeypatch.setattr(
        preview.AnalysisDeliveryRepository,
        "load_rendered",
        lambda self, delivery_id: RenderedDelivery(
            "预览", {"X-Preview": "1"}, "正文", "<html>预览</html>"
        ),
    )
    result = preview.render_delivery_preview(instance, 7, output)
    assert result["delivery_state_changed"] is False
    assert json.loads((output / "report.json").read_text())["capacity_assessments"]
    assert (output / "report.html").read_text() == "<html>预览</html>"
    assert os.stat(output).st_mode & 0o777 == 0o700
    assert os.stat(output / "report.json").st_mode & 0o777 == 0o600
    assert os.stat(output / "report.html").st_mode & 0o777 == 0o600


def test_preview_rejects_output_inside_instance(tmp_path: Path) -> None:
    instance = tmp_path / "instance"
    (instance / "state").mkdir(parents=True)
    (instance / "state" / "data.db").touch()
    with pytest.raises(preview.PreviewError, match="inside_instance"):
        preview.render_delivery_preview(instance, 1, instance / "preview")


def test_isolated_instance_uses_sqlite_backup_without_credentials(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "state").mkdir()
    (source / "logs").mkdir()
    (source / "config" / "trainlab.json").write_text("{}\n")
    (source / "config" / "foundation.yaml").write_text("foundation: example\n")
    (source / "config" / "garmin.yaml").write_text("should-not-copy\n")
    (source / "state" / "data.db").touch()
    destination = tmp_path / "preview-instance"
    result = preview.create_isolated_preview_instance(source, destination)
    assert result["credentials_copied"] is False
    assert (destination / "config" / "trainlab.json").exists()
    assert not (destination / "config" / "garmin.yaml").exists()
    assert (destination / "state" / "data.db").exists()
    with sqlite3.connect(destination / "state" / "data.db") as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert os.stat(destination / "config" / "trainlab.json").st_mode & 0o777 == 0o600
