"""R4 seal and independent R5 channels use one exact effective plan."""

import importlib
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import publication, report_artifacts, storage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_publication_factory")


def test_prepare_seals_same_pdf_and_only_running_days(tmp_path, monkeypatch):
    root, prepared, calls = f.prepared(tmp_path, monkeypatch)
    bundle = report_artifacts.read_sealed(root, f.reports.END)
    assert prepared["seal"]["pdf_sha256"] == storage.digest(bundle.pdf)
    assert len(prepared["workouts"]) == sum(
        d["kind"] == "run" for d in bundle.plan["days"]
    )
    assert [c.calls for c in calls] == [1, 1]
    path = root / "reports" / prepared["seal"]["revision_sha256"] / "report.pdf"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        publication.validate_source(root, prepared["mail"])


def test_sync_mail_distinguishes_complete_empty_and_provisional(tmp_path):
    from skills._shared.fit_weekly import publication_ledger as ledger
    from skills._shared.fit_weekly import sync_calendar

    root = tmp_path / "instance"
    storage.initialize(root)
    request = sync_calendar.InventoryRequest(
        "synthetic-sync", "2026-08-09", "2026-08-10", f.NOW, 10, 1
    )
    sync_calendar.collect_inventory(
        root,
        request,
        lambda *a: {"page": 0, "page_size": 10, "has_more": False, "items": []},
    )
    action = publication.prepare_sync(
        root,
        request.key,
        sender="owner@example.invalid",
        recipient="runner@example.invalid",
    )
    with storage.open_store(root) as db:
        payload = ledger.request(db, action)["payload"]
    assert "完整查询确认无运动" in payload["body"]
    assert "当日暂定" in payload["body"]
    assert "FIT收集：完成" in payload["body"]
    assert (
        publication.validate_source(root, action)["source_key"] == "sync:synthetic-sync"
    )


def test_sync_error_and_gap_are_not_claimed_empty(tmp_path):
    from skills._shared.fit_weekly import publication_ledger as ledger
    from skills._shared.fit_weekly import sync_calendar

    root = tmp_path / "instance"
    storage.initialize(root)
    request = sync_calendar.InventoryRequest(
        "failed-sync", "2026-08-09", "2026-08-10", f.NOW, 10, 1
    )
    with storage.open_store(root) as db:
        sync_calendar.record_gaps(db, "2026-08-09", f.NOW)

    def failure(*args):
        raise OSError("public synthetic query failure")

    with pytest.raises(ValueError):
        sync_calendar.collect_inventory(root, request, failure)
    action = publication.prepare_sync(
        root,
        request.key,
        sender="owner@example.invalid",
        recipient="runner@example.invalid",
    )
    with storage.open_store(root) as db:
        body = ledger.request(db, action)["payload"]["body"]
    assert "缺口" in body and "查询不完整" in body and "错误：1" in body
    assert "完整查询确认无运动" not in body


@pytest.mark.parametrize(
    "damage", ["source_sha", "raw_body", "subject", "snapshot", "missing_request"]
)
def test_changed_prepared_source_or_mime_stops_before_provider(
    tmp_path, monkeypatch, damage
):
    from skills._shared.fit_weekly import gmail_message, gmail_rest
    from skills._shared.fit_weekly import publication_ledger as ledger

    prepare = ledger.prepare

    # Inject a malformed preparation input before the immutable write. The
    # persistent store and the complete downstream validator remain real.
    def malformed(root, req):
        action = req["action_key"]
        if damage == "source_sha":
            req["source_sha256"] = "0" * 64
        elif damage == "raw_body":
            req["payload"]["raw"] = gmail_message.build(
                action,
                f.Auth.account,
                "runner@example.invalid",
                req["payload"]["subject"],
                "changed",
            )["raw"]
        elif damage == "subject":
            req["payload"]["subject"] = "changed"
        elif damage == "snapshot":
            req["payload"]["sync_snapshot"]["activity_count"] = 99
        if damage == "missing_request":
            return action
        return prepare(root, req)

    monkeypatch.setattr(ledger, "prepare", malformed)
    root, action = f.prepared_sync(tmp_path)
    session = f.Gmail()
    with pytest.raises(ValueError):
        gmail_rest.deliver(
            root,
            action,
            gmail_rest.Client(f.Auth(), session),
            f.authorization([action]),
            now=lambda: f.NOW,
        )
    assert session.calls == []


def test_damaged_sealed_pdf_stops_weekly_mail_before_transport(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import gmail_rest

    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    path = root / "reports" / prepared["seal"]["revision_sha256"] / "report.pdf"
    path.write_bytes(b"%PDF-damaged")
    session = f.Gmail()
    with pytest.raises(ValueError):
        gmail_rest.deliver(
            root,
            prepared["mail"],
            gmail_rest.Client(f.Auth(), session),
            f.authorization([prepared["mail"]]),
            now=lambda: f.NOW,
        )
    assert session.calls == []
