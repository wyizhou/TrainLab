from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[3]
PYTHON = sys.executable


def _workflow_module():
    spec = importlib.util.spec_from_file_location(
        "trainlab_offline_workflow",
        SOURCE / "skills/_shared/scripts/offline_workflow.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init(candidate: Path) -> Path:
    state = candidate / "state"
    state.mkdir(parents=True)
    db = state / "trainlab.db"
    result = subprocess.run(
        [
            PYTHON,
            str(SOURCE / "skills/_shared/scripts/init_state.py"),
            "--database",
            str(db),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return db


def _raw(candidate: Path, day: str) -> None:
    root = candidate / "state/raw/garmin/health"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day.replace('-', '')}-sleep-test.json"
    path.write_text(
        json.dumps(
            {
                "sleep": {
                    "duration": 28800,
                    "wake_date": day,
                    "startTime": f"{day}T00:00:00+08:00",
                    "endTime": f"{day}T08:00:00+08:00",
                }
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    rhr = root / f"{day.replace('-', '')}-rhr-test.json"
    rhr.write_text(json.dumps({"rhr": {"value": 55, "date": day}}), encoding="utf-8")
    rhr.chmod(0o600)


def _activity(candidate: Path, day: str) -> None:
    root = candidate / "state/raw/garmin/activities"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day.replace('-', '')}-activity.gpx"
    path.write_text(
        "<gpx version='1.1'><trk><trkseg>"
        "<trkpt lat='1' lon='2'/><trkpt lat='1.001' lon='2.001'/>"
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _run(candidate: Path, db: Path, mode: str, day: str) -> dict[str, object]:
    out = candidate / f"out-{mode}"
    result = subprocess.run(
        [
            PYTHON,
            str(SOURCE / "skills/_shared/scripts/offline_workflow.py"),
            "--mode",
            mode,
            "--date",
            day,
            "--database",
            str(db),
            "--output-dir",
            str(out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_daily_then_weekly_offline_candidate(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    db = _init(candidate)
    # Daily D consumes D-1 and D sleep; provide one bounded synthetic file per day.
    for day in [
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
    ]:
        _raw(candidate, day)
    for day in ["2026-08-02", "2026-08-04", "2026-08-06", "2026-08-08"]:
        _activity(candidate, day)
    for day in [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
    ]:
        _run(candidate, db, "daily", day)
    weekly = _run(candidate, db, "weekly", "2026-08-09")
    assert weekly["status"] == "succeeded"
    assert weekly["provider_calls"] == 0
    assert (candidate / "out-weekly/report.html").stat().st_mode & 0o777 == 0o600
    assert (candidate / "out-weekly/report.json").stat().st_mode & 0o777 == 0o600
    connection = sqlite3.connect(db)
    kinds = {
        row[0]
        for row in connection.execute("SELECT DISTINCT output_kind FROM skill_outputs")
    }
    connection.close()
    assert {
        "sync_summary",
        "bounded_evidence",
        "daily_summary",
        "weekly_fitness_review",
        "weekly_summary",
        "training_plan",
        "garmin_workout_contract",
        "report_artifact",
        "email_render",
        "execution_summary",
    }.issubset(kinds)
    check = sqlite3.connect(db)
    before = check.execute("SELECT COUNT(*) FROM skill_outputs").fetchone()[0]
    weekly_review = json.loads(
        check.execute(
            "SELECT content_json FROM skill_outputs "
            "WHERE output_kind='weekly_fitness_review'"
        ).fetchone()[0]
    )
    check.close()
    assert weekly_review["activity_days"] == 4
    repeated = _run(candidate, db, "daily", "2026-08-15")
    check = sqlite3.connect(db)
    after = check.execute("SELECT COUNT(*) FROM skill_outputs").fetchone()[0]
    check.close()
    assert repeated["status"] == "succeeded"
    assert before == after


def test_daily_blocks_when_review_exists_but_wake_day_sleep_is_missing(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    db = _init(candidate)
    _raw(candidate, "2026-08-02")
    output = candidate / "out"
    result = subprocess.run(
        [
            PYTHON,
            str(SOURCE / "skills/_shared/scripts/offline_workflow.py"),
            "--mode",
            "daily",
            "--date",
            "2026-08-03",
            "--database",
            str(db),
            "--output-dir",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["error_code"] == "daily_sleep_evidence_missing"


def test_daily_marks_recovery_red_flags_as_caution(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    db = _init(candidate)
    root = candidate / "state/raw/garmin/health"
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        (
            "20260815-rhr.json",
            {"rhr": {"value": 90}},
        ),
        (
            "20260816-sleep.json",
            {
                "sleep": {
                    "duration": 7200,
                    "startTime": "2026-08-16T02:00:00+08:00",
                    "endTime": "2026-08-16T04:00:00+08:00",
                }
            },
        ),
    ):
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
    result = subprocess.run(
        [
            PYTHON,
            str(SOURCE / "skills/_shared/scripts/offline_workflow.py"),
            "--mode",
            "daily",
            "--date",
            "2026-08-16",
            "--database",
            str(db),
            "--output-dir",
            str(candidate / "out"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "succeeded"
    connection = sqlite3.connect(db)
    summary = connection.execute(
        "SELECT content_json FROM skill_outputs WHERE output_kind='daily_summary'"
    ).fetchone()[0]
    connection.close()
    assert json.loads(summary)["safety"] == "caution"


def test_daily_keeps_yesterday_and_wake_day_evidence_separate(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    db = _init(candidate)
    root = candidate / "state/raw/garmin/health"
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "20260804-rhr.json": {"rhr": {"value": 55}},
        "20260805-sleep.json": {
            "sleep": {
                "duration": 7200,
                "startTime": "2026-08-05T02:00:00+08:00",
                "endTime": "2026-08-05T04:00:00+08:00",
            }
        },
        "20260805-rhr.json": {"rhr": {"value": 55}},
        "20260806-sleep.json": {
            "sleep": {
                "duration": 28800,
                "startTime": "2026-08-06T00:00:00+08:00",
                "endTime": "2026-08-06T08:00:00+08:00",
            }
        },
    }
    for name, payload in files.items():
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)

    first = _run(candidate, db, "daily", "2026-08-05")
    second = _run(candidate, db, "daily", "2026-08-06")
    assert first["status"] == "succeeded"
    assert second["status"] == "succeeded"
    connection = sqlite3.connect(db)
    rows = connection.execute(
        "SELECT period_start_date, content_json FROM skill_outputs "
        "WHERE output_kind='daily_summary' ORDER BY period_start_date"
    ).fetchall()
    connection.close()
    summaries = {row[0]: json.loads(row[1]) for row in rows}
    assert summaries["2026-08-05"]["safety"] == "caution"
    assert summaries["2026-08-06"]["safety"] == "ready"
    assert not any(
        metric.get("data_date") == "2026-08-05"
        and metric.get("metrics", {}).get("resource") == "sleep"
        for metric in summaries["2026-08-06"]["bounded_metrics"]
    )


def test_recovery_red_flag_plan_keeps_climbing_step_dose_consistent() -> None:
    module = _workflow_module()
    daily = [
        {
            "safety": "caution",
            "bounded_metrics": [
                {"metrics": {"resource": "rhr", "aggregate": {"average": 90}}}
            ],
        }
        for _ in range(7)
    ]
    plan = module._weekly_plan(date(2026, 8, 17), daily)
    climbing = [item for item in plan["items"] if item["activity_kind"] == "climbing"]
    assert climbing
    for item in climbing:
        assert item["duration_minutes"] == 60
        assert item["steps"][0]["end_condition"] == "完成 60 分钟"
