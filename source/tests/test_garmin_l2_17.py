"""Provider-side contracts after the scheduler/orchestration removal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src import cli
from src.analysis.boundary import verify_import_boundary
from src.garmin_legacy import (
    LegacyReconciliationError,
    ReconciliationCounts,
    ReconciliationDifference,
    build_legacy_reconciliation_report,
)
from src.resources import resource_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/garmin_provider_contract_l2_17.json"
REPORT_SCHEMA = resource_path(
    "harness/schemas/garmin_legacy_reconciliation_report.schema.json"
)


def test_analysis_has_no_garmin_provider_import_and_uses_its_stable_read_boundary() -> (
    None
):
    graph = verify_import_boundary(ROOT / "src" / "analysis")
    assert graph and all(not imports for imports in graph.values())
    stable = (ROOT / "src" / "analysis" / "stable_views.py").read_text(encoding="utf-8")
    assert "v_open_data_quality_issues" in stable
    assert "garmin_client" not in stable and "GarminConnect" not in stable


def test_mail_layer_may_read_canonical_facts_but_cannot_call_garmin() -> None:
    sources = list((ROOT / "src" / "mail_agent").rglob("*.py"))
    assert sources
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    for forbidden in (
        "garminconnect",
        "GarminConnectTransport",
        "GarminCollectionTool",
    ):
        assert forbidden not in combined
    context = (ROOT / "src" / "mail_agent" / "context.py").read_text(encoding="utf-8")
    assert "v_current_daily_health" in context
    assert "v_current_activities" in context


@pytest.mark.parametrize("command", ("supervisor", "orchestrate", "run"))
def test_retired_scheduler_commands_are_not_registered(command: str) -> None:
    parser = cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args([command])


def test_current_root_commands_are_manual_only() -> None:
    parser = cli._parser()
    action = next(
        item for item in parser._actions if isinstance(item, argparse._SubParsersAction)
    )
    assert set(action.choices) == {"foundation", "garmin", "analysis", "mail", "facts"}
    assert parser.parse_args(["foundation", "status"]).command == "foundation"
    assert (
        parser.parse_args(["analysis", "daily", "--report-date", "2026-08-13"]).command
        == "analysis"
    )


def test_shadow_report_is_schema_valid_deterministic_and_payload_free() -> None:
    report = build_legacy_reconciliation_report(
        report_id="legacy-shadow-001",
        start_local_date="2026-07-15",
        end_local_date="2026-07-21",
        generated_at_utc="2026-07-24T00:00:00Z",
        legacy_counts=ReconciliationCounts(3, 7),
        garmin_counts=ReconciliationCounts(4, 7),
        legacy_snapshot_sha256="a" * 64,
        garmin_snapshot_sha256="b" * 64,
        differences=(
            ReconciliationDifference("activity_count_mismatch", "activity", 3, 4),
        ),
    )
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    assert not list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report)
    )
    assert report["shadow_only"] is True
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "token",
        "email",
        "gps",
        "latitude",
        "longitude",
        "payload",
        "heart_rate",
        "raw_object",
    ):
        assert forbidden not in serialized.lower()


def test_shadow_report_rejects_unknown_difference_or_payload_shaped_data() -> None:
    with pytest.raises(LegacyReconciliationError, match="difference_invalid"):
        build_legacy_reconciliation_report(
            report_id="legacy-shadow-002",
            start_local_date="2026-07-15",
            end_local_date="2026-07-21",
            generated_at_utc="2026-07-24T00:00:00Z",
            legacy_counts=ReconciliationCounts(3, 7),
            garmin_counts=ReconciliationCounts(4, 7),
            legacy_snapshot_sha256="a" * 64,
            garmin_snapshot_sha256="b" * 64,
            differences=(ReconciliationDifference("unknown", "payload", 1, 2),),
        )
