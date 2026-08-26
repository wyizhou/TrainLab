from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONTEXT = _load(
    "trainlab_recent_health_context_test",
    "skills/training-coach/scripts/build_context.py",
)
PARSER = _load(
    "trainlab_recent_health_parser_test",
    "skills/training-coach/scripts/parse_raw.py",
)
SCHEMA = _load(
    "trainlab_recent_health_schema_test",
    "skills/_shared/scripts/schema_validation.py",
)
STATE = _load(
    "trainlab_recent_health_state_test",
    "skills/_shared/state.py",
)
INDEX = _load(
    "trainlab_recent_health_index_test",
    "skills/garmin-sync/scripts/index_raw.py",
)


def _row(
    source_root: Path,
    *,
    raw_id: int,
    resource: str,
    day: str,
    revision: int,
    payload: object,
) -> dict[str, object]:
    raw_root = source_root / "state/raw/garmin/health"
    raw_root.mkdir(parents=True, exist_ok=True)
    path = raw_root / f"{day.replace('-', '')}-{resource}-{raw_id}.json"
    data = json.dumps(payload, separators=(",", ":")).encode()
    path.write_bytes(data)
    path.chmod(0o600)
    return {
        "raw_file_id": raw_id,
        "relative_path": path.relative_to(source_root / "state/raw").as_posix(),
        "resource": resource,
        "format": "json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_date": day,
        "revision_no": revision,
        "activity_inventory_id": None,
        "byte_size": len(data),
    }


def test_recent_metric_skips_empty_conflicting_and_prefers_latest_valid_revision(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    rows = [
        _row(
            source_root,
            raw_id=1,
            resource="max_metrics",
            day="2026-08-11",
            revision=2,
            payload={},
        ),
        _row(
            source_root,
            raw_id=2,
            resource="max_metrics",
            day="2026-08-11",
            revision=1,
            payload={
                "generic": {
                    "calendarDate": "2026-08-10",
                    "vo2MaxPreciseValue": 59,
                }
            },
        ),
        _row(
            source_root,
            raw_id=3,
            resource="max_metrics",
            day="2026-08-10",
            revision=1,
            payload={
                "generic": {
                    "calendarDate": "2026-08-10",
                    "vo2MaxPreciseValue": 50.5,
                }
            },
        ),
        _row(
            source_root,
            raw_id=4,
            resource="max_metrics",
            day="2026-08-10",
            revision=2,
            payload={
                "generic": {
                    "calendarDate": "2026-08-10",
                    "vo2MaxPreciseValue": 51.0,
                }
            },
        ),
        _row(
            source_root,
            raw_id=5,
            resource="max_metrics",
            day="2026-08-12",
            revision=1,
            payload={
                "generic": {
                    "calendarDate": "2026-08-12",
                    "vo2MaxPreciseValue": 80.0,
                }
            },
        ),
    ]
    result = CONTEXT._select_recent_health_metric(
        source_root,
        rows,
        PARSER,
        report_date=date(2026, 8, 12),
        review_date=date(2026, 8, 11),
        resource="max_metrics",
        field="vo2_max",
        unit="ml/kg/min",
        lookback_days=30,
    )
    assert result == {
        "resource": "max_metrics",
        "status": "ready",
        "value": 51.0,
        "unit": "ml/kg/min",
        "observed_date": "2026-08-10",
        "age_days": 2,
        "selection_kind": "latest_prior",
        "lookback_days": 30,
        "raw_file_id": 4,
        "sha256": rows[3]["sha256"],
    }


@pytest.mark.parametrize(
    ("resource", "field", "unit", "lookback", "boundary", "stale", "payload"),
    [
        (
            "max_metrics",
            "vo2_max",
            "ml/kg/min",
            30,
            "2026-07-13",
            "2026-07-12",
            lambda day: {"generic": {"calendarDate": day, "vo2MaxValue": 49}},
        ),
        (
            "weigh_ins",
            "weight",
            "kg",
            14,
            "2026-07-29",
            "2026-07-28",
            lambda day: {"latestWeight": {"calendarDate": day, "weight": 70300}},
        ),
    ],
)
def test_recent_metric_includes_window_boundary_and_rejects_stale_value(
    tmp_path: Path,
    resource: str,
    field: str,
    unit: str,
    lookback: int,
    boundary: str,
    stale: str,
    payload: Any,
) -> None:
    source_root = tmp_path / resource
    boundary_row = _row(
        source_root,
        raw_id=1,
        resource=resource,
        day=boundary,
        revision=1,
        payload=payload(boundary),
    )
    stale_row = _row(
        source_root,
        raw_id=2,
        resource=resource,
        day=stale,
        revision=1,
        payload=payload(stale),
    )
    selected = CONTEXT._select_recent_health_metric(
        source_root,
        [stale_row, boundary_row],
        PARSER,
        report_date=date(2026, 8, 12),
        review_date=date(2026, 8, 11),
        resource=resource,
        field=field,
        unit=unit,
        lookback_days=lookback,
    )
    assert selected["status"] == "ready"
    assert selected["observed_date"] == boundary

    missing = CONTEXT._select_recent_health_metric(
        source_root,
        [stale_row],
        PARSER,
        report_date=date(2026, 8, 12),
        review_date=date(2026, 8, 11),
        resource=resource,
        field=field,
        unit=unit,
        lookback_days=lookback,
    )
    assert missing == {
        "resource": resource,
        "status": "missing",
        "value": None,
        "unit": unit,
        "observed_date": None,
        "age_days": None,
        "selection_kind": None,
        "lookback_days": lookback,
        "raw_file_id": None,
        "sha256": None,
    }


def test_recent_metric_skips_wrong_units_and_integrity_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    bad = _row(
        source_root,
        raw_id=1,
        resource="max_metrics",
        day="2026-08-11",
        revision=1,
        payload={"value": 99},
    )
    good = _row(
        source_root,
        raw_id=2,
        resource="max_metrics",
        day="2026-08-10",
        revision=1,
        payload={"value": 51},
    )

    class FakeParser:
        @staticmethod
        def parse_evidence(path: Path, **_kwargs: object) -> dict[str, object]:
            if path.name.endswith("-1.json"):
                return {"metrics": {"vo2_max": 99, "unit": "watts"}}
            return {"metrics": {"vo2_max": 51, "unit": "ml/kg/min"}}

    original = CONTEXT._verified_raw_path

    def verify(root: Path, row: dict[str, object]) -> Path:
        if row["raw_file_id"] == 2:
            return original(root, row)
        return original(root, row)

    monkeypatch.setattr(CONTEXT, "_verified_raw_path", verify)
    selected = CONTEXT._select_recent_health_metric(
        source_root,
        [bad, good],
        FakeParser,
        report_date=date(2026, 8, 12),
        review_date=date(2026, 8, 11),
        resource="max_metrics",
        field="vo2_max",
        unit="ml/kg/min",
        lookback_days=30,
    )
    assert selected["raw_file_id"] == 2

    good_path = source_root / "state/raw" / str(good["relative_path"])
    os.chmod(good_path, 0o644)
    missing = CONTEXT._select_recent_health_metric(
        source_root,
        [good],
        FakeParser,
        report_date=date(2026, 8, 12),
        review_date=date(2026, 8, 11),
        resource="max_metrics",
        field="vo2_max",
        unit="ml/kg/min",
        lookback_days=30,
    )
    assert missing["status"] == "missing"


@pytest.mark.parametrize(
    ("resource", "field", "payload"),
    [
        (
            "max_metrics",
            "vo2_max",
            {
                "generic": {
                    "calendarDate": "2026-08-10",
                    "vo2MaxValue": 51,
                    "unit": "watts",
                }
            },
        ),
        (
            "weigh_ins",
            "weight",
            {
                "latestWeight": {
                    "calendarDate": "2026-08-10",
                    "weight": 155,
                    "unit": "lb",
                }
            },
        ),
    ],
)
def test_real_parser_rejects_explicit_incompatible_units(
    tmp_path: Path, resource: str, field: str, payload: object
) -> None:
    path = tmp_path / f"20260810-{resource}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = PARSER.parse_evidence(
        path,
        resource_override=resource,
        expected_date_override="2026-08-10",
    )
    assert field not in parsed["metrics"]


@pytest.mark.parametrize(
    ("resource", "field", "payload"),
    [
        (
            "max_metrics",
            "vo2_max",
            {
                "generic": {
                    "calendarDate": "2026-08-10",
                    "measurementDate": "2026-08-09",
                    "vo2MaxValue": 51,
                }
            },
        ),
        (
            "weigh_ins",
            "weight",
            {
                "latestWeight": {
                    "calendarDate": "2026-08-10",
                    "measurementDate": "2026-08-09",
                    "weight": 70300,
                }
            },
        ),
    ],
)
def test_real_parser_rejects_conflicting_dates(
    tmp_path: Path, resource: str, field: str, payload: object
) -> None:
    path = tmp_path / f"20260810-{resource}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = PARSER.parse_evidence(
        path,
        resource_override=resource,
        expected_date_override="2026-08-10",
    )
    assert field not in parsed["metrics"]


@pytest.mark.parametrize(
    ("resource", "field", "expected", "payload"),
    [
        (
            "max_metrics",
            "vo2_max",
            51,
            {
                "generic": {
                    "calendarDate": "2026-08-10",
                    "vo2MaxValue": 51,
                    "unit": "ml/kg/min",
                }
            },
        ),
        (
            "weigh_ins",
            "weight",
            70.3,
            {
                "latestWeight": {
                    "calendarDate": "2026-08-10",
                    "weight": 70300,
                    "unit": "g",
                }
            },
        ),
        (
            "weigh_ins",
            "weight",
            70.3,
            {
                "latestWeight": {
                    "calendarDate": "2026-08-10",
                    "weight": 70.3,
                    "unit": "kg",
                }
            },
        ),
    ],
)
def test_real_parser_accepts_compatible_explicit_units(
    tmp_path: Path,
    resource: str,
    field: str,
    expected: float,
    payload: object,
) -> None:
    path = tmp_path / f"20260810-{resource}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = PARSER.parse_evidence(
        path,
        resource_override=resource,
        expected_date_override="2026-08-10",
    )
    assert parsed["metrics"][field] == expected


def test_recent_health_schema_rejects_partial_ready_or_missing_records() -> None:
    ready: dict[str, Any] = {
        "schema_version": "recent_health_metrics_v1",
        "status": "ready",
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "metrics": {
            "vo2_max": {
                "resource": "max_metrics",
                "status": "ready",
                "value": 51,
                "unit": "ml/kg/min",
                "observed_date": "2026-08-10",
                "age_days": 2,
                "selection_kind": "latest_prior",
                "lookback_days": 30,
                "raw_file_id": 1,
                "sha256": "a" * 64,
            },
            "weight": {
                "resource": "weigh_ins",
                "status": "missing",
                "value": None,
                "unit": "kg",
                "observed_date": None,
                "age_days": None,
                "selection_kind": None,
                "lookback_days": 14,
                "raw_file_id": None,
                "sha256": None,
            },
        },
        "provider_calls": 0,
    }
    assert SCHEMA.validate_payload(ready, "recent_health_metrics_v1") == []
    ready["metrics"]["weight"]["value"] = 70.3
    assert SCHEMA.validate_payload(ready, "recent_health_metrics_v1")
    ready["metrics"]["weight"]["value"] = None
    ready["metrics"]["vo2_max"]["raw_file_id"] = None
    assert SCHEMA.validate_payload(ready, "recent_health_metrics_v1")


def test_recent_health_snapshot_persists_raw_lineage_and_replays(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    health = source_root / "state/raw/garmin/health"
    health.mkdir(parents=True)
    vo2 = health / ("20260810-max_metrics-" + "a" * 64 + ".json")
    vo2.write_text(
        json.dumps({"generic": {"calendarDate": "2026-08-10", "vo2MaxValue": 51}}),
        encoding="utf-8",
    )
    weight = health / ("20260807-weigh_ins-" + "b" * 64 + ".json")
    weight.write_text(
        json.dumps({"latestWeight": {"calendarDate": "2026-08-07", "weight": 70300}}),
        encoding="utf-8",
    )
    vo2.chmod(0o600)
    weight.chmod(0o600)
    database = STATE.init_database(source_root / "state/trainlab.db")
    INDEX.index(source_root, database)
    first = CONTEXT.record_recent_health_metrics(
        database, source_root, database, date(2026, 8, 12)
    )
    second = CONTEXT.record_recent_health_metrics(
        database, source_root, database, date(2026, 8, 12)
    )
    assert first == second
    assert first["payload"]["provider_calls"] == 0
    assert first["payload"]["metrics"]["vo2_max"]["value"] == 51
    assert first["payload"]["metrics"]["weight"]["value"] == 70.3
    connection = STATE.connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT lineage_json FROM skill_outputs WHERE id=?",
            (first["output_id"],),
        ).fetchone()
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM skill_outputs "
                "WHERE schema_name='recent_health_metrics_v1'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    lineage = json.loads(str(row[0]))
    assert count == 1
    assert {item["raw_file_id"] for item in lineage} == {
        first["payload"]["metrics"]["vo2_max"]["raw_file_id"],
        first["payload"]["metrics"]["weight"]["raw_file_id"],
    }
    assert all("raw_sha256" in item for item in lineage)
