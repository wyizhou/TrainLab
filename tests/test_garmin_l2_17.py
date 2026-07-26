"""L2-17 provider-side contracts only; X-02 owns cross-layer E2E."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from trainlab import cli
from trainlab.analysis.boundary import verify_import_boundary
from trainlab.garmin_legacy import (
    LegacyReconciliationError,
    ReconciliationCounts,
    ReconciliationDifference,
    build_legacy_reconciliation_report,
)
from trainlab.orchestration import DownstreamCall
import trainlab.orchestration.subprocess_runner as runner


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/garmin_provider_contract_l2_17.json"
REPORT_SCHEMA = ROOT / "harness/schemas/garmin_legacy_reconciliation_report.schema.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _call(value: dict[str, object]) -> DownstreamCall:
    request = value["request"]
    assert isinstance(request, dict)
    return DownstreamCall(
        layer=request["layer"],  # type: ignore[arg-type]
        mode=request["mode"],  # type: ignore[arg-type]
        invocation_id=request["invocation_id"],  # type: ignore[arg-type]
        request_sha256=None,
        through_local_date=request["through_local_date"],  # type: ignore[arg-type]
    )


def test_provider_fixture_matches_public_invocation_date_receipt_and_exit_contract() -> None:
    value = _fixture()
    call = _call(value)
    receipt = value["receipt"]
    assert isinstance(receipt, dict)
    # Garmin's frozen receipt deliberately has a run_id rather than an echoed
    # invocation_id.  The request/receipt association is therefore the typed
    # invocation plus the validated mode/date/exit boundary, not an invented
    # receipt field.
    assert runner._argv(call)[-len(value["expected_argv_suffix"]) :] == tuple(value["expected_argv_suffix"])
    accepted, receipt_hash = runner._validate_receipt(call, receipt, value["expected_exit_code"])  # type: ignore[arg-type]
    assert accepted is receipt and re.fullmatch(r"[0-9a-f]{64}", str(receipt_hash))
    assert receipt["mode"] == call.mode
    assert receipt["requested_range"] == {"from": None, "through": call.through_local_date}
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,127}", str(receipt["run_id"]))
    assert runner._EXIT_BY_LAYER["garmin"][str(receipt["status"])] == value["expected_exit_code"]


def test_orchestration_has_no_private_garmin_state_write_path() -> None:
    forbidden = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b[^\n;]*\bgarmin_sync_", re.IGNORECASE)
    sources = list((ROOT / "src/trainlab/orchestration").rglob("*.py"))
    assert sources
    assert all(not forbidden.search(path.read_text(encoding="utf-8")) for path in sources)
    # Its provider boundary has no database dependency: it can only invoke a
    # typed process and validate the public receipt. The orchestration layer
    # may still keep its own workflow/incident state in SQLite.
    boundary = (ROOT / "src/trainlab/orchestration/subprocess_runner.py").read_text(encoding="utf-8")
    assert "import sqlite3" not in boundary
    # The receipt-schema filename is permitted; it is the public interface,
    # unlike a private ``garmin_sync_*`` SQL operation.
    assert '"garmin": _ROOT / "harness/schemas/garmin_sync_receipt.schema.json"' in boundary


def test_analysis_has_no_garmin_provider_import_and_uses_its_stable_read_boundary() -> None:
    graph = verify_import_boundary(ROOT / "src/trainlab/analysis")
    assert graph and all(not imports for imports in graph.values())
    stable = (ROOT / "src/trainlab/analysis/stable_views.py").read_text(encoding="utf-8")
    assert "v_open_data_quality_issues" in stable
    assert "garmin_client" not in stable and "GarminConnect" not in stable


def test_mail_layer_may_read_canonical_facts_but_cannot_call_or_modify_garmin() -> None:
    sources = list((ROOT / "src/trainlab/mail_agent").rglob("*.py"))
    assert sources
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    for forbidden in (
        "garminconnect",
        "GarminConnectTransport",
        "GarminCollectionTool",
        "trainlab garmin",
    ):
        assert forbidden not in combined
    assert not re.search(
        r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b[^\n;]*\bgarmin_sync_",
        combined,
        re.IGNORECASE,
    )
    # Layer four's contract permits bounded reads of canonical health/activity
    # facts.  That is data consumption, not a provider or collection-state
    # coupling.
    context = (ROOT / "src/trainlab/mail_agent/context.py").read_text(encoding="utf-8")
    assert "v_current_daily_health" in context
    assert "v_current_activities" in context


def test_legacy_sync_and_ingest_commands_still_parse_without_routing_change() -> None:
    parser = cli._parser()
    sync = parser.parse_args(["sync"])
    ingest = parser.parse_args(["ingest"])
    assert (sync.command, sync.daemon) == ("sync", False)
    assert (ingest.command, ingest.daemon) == ("ingest", False)
    source = (ROOT / "src/trainlab/cli.py").read_text(encoding="utf-8")
    assert "if args.command == \"sync\":" in source
    assert "if args.command == \"ingest\":" in source


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
        differences=(ReconciliationDifference("activity_count_mismatch", "activity", 3, 4),),
    )
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report))
    assert report["shadow_only"] is True
    assert report["canonical_owner"] == "unchanged"
    assert report["decision"] == "investigate"
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in ("token", "email", "gps", "latitude", "longitude", "payload", "heart_rate", "raw_object"):
        assert forbidden not in serialized.lower()
    identical = build_legacy_reconciliation_report(
        report_id="legacy-shadow-001", start_local_date="2026-07-15", end_local_date="2026-07-21", generated_at_utc="2026-07-24T00:00:00Z",
        legacy_counts=ReconciliationCounts(3, 7), garmin_counts=ReconciliationCounts(4, 7),
        legacy_snapshot_sha256="a" * 64, garmin_snapshot_sha256="b" * 64,
        differences=(ReconciliationDifference("activity_count_mismatch", "activity", 3, 4),),
    )
    assert identical == report


def test_shadow_report_rejects_unknown_difference_or_payload_shaped_data() -> None:
    with pytest.raises(LegacyReconciliationError, match="difference_invalid"):
        build_legacy_reconciliation_report(
            report_id="legacy-shadow-002", start_local_date="2026-07-15", end_local_date="2026-07-21", generated_at_utc="2026-07-24T00:00:00Z",
            legacy_counts=ReconciliationCounts(0, 0), garmin_counts=ReconciliationCounts(0, 0),
            legacy_snapshot_sha256="a" * 64, garmin_snapshot_sha256="b" * 64,
            differences=(ReconciliationDifference("contains_payload", "activity", 0, 0),),
        )
    with pytest.raises(LegacyReconciliationError, match="count_invalid"):
        build_legacy_reconciliation_report(
            report_id="legacy-shadow-003", start_local_date="2026-07-15", end_local_date="2026-07-21", generated_at_utc="2026-07-24T00:00:00Z",
            legacy_counts=ReconciliationCounts(-1, 0), garmin_counts=ReconciliationCounts(0, 0),
            legacy_snapshot_sha256="a" * 64, garmin_snapshot_sha256="b" * 64,
        )
