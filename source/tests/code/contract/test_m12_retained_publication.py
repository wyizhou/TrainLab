from __future__ import annotations

import importlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills._shared.fit_weekly import (
    fit_parse,
    garmin_workouts,
    gmail_rest,
    model_job,
    report_artifacts,
    report_markdown,
    report_revisions,
    storage,
)
from skills._shared.fit_weekly import publication_ledger as ledger

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))
f = importlib.import_module("m12_publication_factory")
reports = importlib.import_module("m12_report_factory")
fit = importlib.import_module("m12_fit_factory")
coach = importlib.import_module("m12_coaching_factory")


@pytest.mark.parametrize("response", ["http", "missing", "invalid", "nonobject"])
def test_send_rejection_or_missing_id_never_grants_another_send(
    tmp_path, monkeypatch, response
):
    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    request = session.request

    def reject(method, url, **kwargs):
        result = request(method, url, **kwargs)
        if url.endswith("/send"):
            return SimpleNamespace(
                status_code=403 if response == "http" else 200,
                json=lambda: (
                    []
                    if response == "nonobject"
                    else {"id": "../unsafe"}
                    if response == "invalid"
                    else {}
                ),
            )
        return result

    monkeypatch.setattr(session, "request", reject)
    client = gmail_rest.Client(f.Auth(), session)
    grant = f.authorization([key])
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "unknown"
    )
    monkeypatch.setattr(session, "request", request)
    gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)
    gmail_rest.reconcile(root, key, client, grant, now=lambda: f.NOW)
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


class PublicCrash(BaseException):
    pass


@pytest.mark.parametrize(
    "boundary",
    [
        "send_before",
        "send_after",
        "readback_before",
        "readback_after",
        "result_before",
        "result_after",
    ],
)
def test_capture_and_result_crashes_keep_original_send_once(
    tmp_path, monkeypatch, boundary
):
    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    session.rewrite = False
    client = gmail_rest.Client(f.Auth(), session)
    grant = f.authorization([key])
    capture, success = ledger.Journal.capture, ledger.Journal.success

    def interrupted_capture(self, call_key, evidence):
        selected = (boundary.startswith("send") and set(evidence) == {"id"}) or (
            boundary.startswith("readback") and "gmail_id" in evidence
        )
        if selected and boundary.endswith("before"):
            raise PublicCrash()
        capture(self, call_key, evidence)
        if selected:
            raise PublicCrash()

    def interrupted_success(self, action, evidence):
        if boundary == "result_before":
            raise PublicCrash()
        result = success(self, action, evidence)
        if boundary == "result_after":
            raise PublicCrash()
        return result

    with monkeypatch.context() as m:
        m.setattr(ledger.Journal, "capture", interrupted_capture)
        m.setattr(ledger.Journal, "success", interrupted_success)
        with pytest.raises(PublicCrash):
            gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)
    moved = tmp_path / "moved"
    root.rename(moved)
    assert (
        gmail_rest.reconcile(moved, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    before = len(session.calls)
    assert (
        gmail_rest.deliver(moved, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert len(session.calls) == before
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


def test_pre_intent_failure_recovery_can_send_only_once(tmp_path, monkeypatch):
    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    client = gmail_rest.Client(f.Auth(), session)
    grant = f.authorization([key])

    def failure(*args):
        raise OSError("public pre-intent failure")

    with monkeypatch.context() as m:
        m.setattr(ledger.Journal, "intent", failure)
        assert (
            gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
            == "prepared"
        )
    assert all(not url.endswith("/send") for _, url, _ in session.calls)
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


@pytest.mark.parametrize("capture", [{}, {"id": ""}, {"id": "../unsafe"}, {"id": True}])
def test_invalid_send_capture_never_authorizes_repeat(tmp_path, capture):
    root, key = f.prepared_sync(tmp_path)
    grant = f.authorization([key])
    session = f.Gmail()
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        journal.intent(key)
        call = journal.reserve(
            key,
            "gmail.send",
            {"raw": ledger.request(journal.db, key)["payload"]["raw"]},
        )
        journal.capture(call, capture)
    for operation in (gmail_rest.deliver, gmail_rest.reconcile):
        assert (
            operation(
                root,
                key,
                gmail_rest.Client(f.Auth(), session),
                grant,
                now=lambda: f.NOW,
            )["status"]
            == "unknown"
        )
    assert all(not url.endswith("/send") for _, url, _ in session.calls)


def test_send_capture_from_another_action_cannot_recover_this_request(tmp_path):
    from dataclasses import replace

    root, key = f.prepared_sync(tmp_path)
    other = key + ":other"
    grant = replace(f.authorization([key]), action_keys=(key, other))
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        request = ledger.request(journal.db, key)
        ledger.put(
            journal.db,
            ledger.key(other, "request"),
            {**request, "action_key": other},
        )
        journal.intent(key)
        journal.intent(other)
        call = journal.reserve(other, "gmail.send", {"raw": request["payload"]["raw"]})
        journal.capture(call, {"id": "abc123"})
    session = f.Gmail()
    for operation in (gmail_rest.deliver, gmail_rest.reconcile):
        result = operation(
            root, key, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
        )
        assert result["status"] == "unknown"
    assert all(method == "GET" for method, _, _ in session.calls)
    assert all(not url.endswith("/messages/abc123") for _, url, _ in session.calls)


def test_single_send_reservation_cannot_gain_duplicate_capture_authority(tmp_path):
    root, key = f.prepared_sync(tmp_path)
    grant = f.authorization([key])
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        journal.intent(key)
        arguments = {"raw": ledger.request(journal.db, key)["payload"]["raw"]}
        call = journal.reserve(key, "gmail.send", arguments)
        journal.capture(call, {"id": "abc123"})
        with pytest.raises(ValueError, match="already_reserved"):
            journal.reserve(key, "gmail.send", arguments)
        with pytest.raises(ValueError, match="content_conflict"):
            journal.capture(call, {"id": "abc456"})
        assert journal.captures(key, "gmail.send") == [{"id": "abc123"}]


@pytest.mark.parametrize("damage", ["request_sha", "capture_sha", "wide_database"])
def test_damaged_send_evidence_or_permissions_never_resends(tmp_path, damage):
    import sqlite3

    root, key = f.prepared_sync(tmp_path)
    grant = f.authorization([key])
    session = f.Gmail()
    session.fail = "/messages/abc123"
    client = gmail_rest.Client(f.Auth(), session)
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "unknown"
    )
    session.fail = None
    if damage == "wide_database":
        (root / "trainlab-fit.db").chmod(0o644)
    else:
        with sqlite3.connect(root / "trainlab-fit.db") as db:
            suffix = (
                ledger.key(key, "request") if damage == "request_sha" else "%:capture"
            )
            digest = (
                db.execute(
                    "SELECT content_sha256 FROM documents WHERE kind='delivery_receipt' AND logical_key LIKE ?",
                    (suffix,),
                )
                .fetchone()[0]
                .encode()
            )
        database = root / "trainlab-fit.db"
        data = database.read_bytes()
        assert digest in data
        database.write_bytes(data.replace(digest, b"0" * 64))
        assert digest not in database.read_bytes()
        with sqlite3.connect(database) as db:
            assert (
                db.execute(
                    "SELECT content_sha256 FROM documents WHERE kind='delivery_receipt' AND logical_key LIKE ?",
                    (suffix,),
                ).fetchone()[0]
                == "0" * 64
            )
    before = len(session.calls)
    for operation in (gmail_rest.deliver, gmail_rest.reconcile):
        if damage == "capture_sha":
            assert (
                operation(root, key, client, grant, now=lambda: f.NOW)["status"]
                == "unknown"
            )
        else:
            with pytest.raises(ValueError):
                operation(root, key, client, grant, now=lambda: f.NOW)
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1
    if damage != "capture_sha":
        assert len(session.calls) == before


def test_new_instance_lock_blocks_before_any_publication_transport(tmp_path):
    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    with storage.open_store(root):
        with pytest.raises(ValueError, match="busy"):
            gmail_rest.deliver(
                root,
                key,
                gmail_rest.Client(f.Auth(), session),
                f.authorization([key]),
                now=lambda: f.NOW,
            )
    assert session.calls == []


@pytest.mark.parametrize("change", ["refresh", "token_bytes", "token_path"])
def test_trusted_auth_change_keeps_frozen_mime_and_one_send(
    tmp_path, monkeypatch, change
):
    from skills._shared.fit_weekly import gmail_auth, gmail_message

    root, key = f.prepared_sync(tmp_path)
    token = f.token(
        tmp_path,
        expiry="2020-01-01T00:00:00Z"
        if change == "refresh"
        else "2099-01-01T00:00:00Z",
    )
    auth = gmail_auth.Auth(token, f.Auth.account, session=f.Refresh())
    session = f.Gmail()
    grant = f.authorization([key])
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        expected = ledger.request(journal.db, key)["payload"]
    request = session.request

    def changed(method, url, **kwargs):
        if url.endswith("/send"):
            if change == "token_bytes":
                value = json.loads(token.read_text())
                value["token"] = "synthetic-replaced"
                token.write_text(json.dumps(value))
            elif change == "token_path":
                moved = token.with_name("moved-token.json")
                token.rename(moved)
                auth.token_file = moved
            assert kwargs["json"]["raw"] == expected["raw"]
        return request(method, url, **kwargs)

    monkeypatch.setattr(session, "request", changed)
    client = gmail_rest.Client(auth, session)
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert (
        gmail_message.verify(session.sent["abc123"], expected)
        == "<rewritten@example.invalid>"
    )
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


@pytest.mark.parametrize(
    "damage",
    ["empty", "wide_file", "hardlink", "directory_link", "wide_directory", "escape"],
)
def test_only_manifested_private_artifacts_can_be_read_or_published(
    tmp_path, monkeypatch, damage
):
    root, _, _ = reports.setup(tmp_path, monkeypatch)
    revision = report_revisions.create(root, reports.END)
    sha = model_job.sha(revision)
    manifest = report_artifacts.render(root, reports.END, "ai", sha)
    directory = root / "reports" / sha
    path = directory / "report.pdf"
    extra = directory / "unrelated.txt"
    extra.write_bytes(b"must not be delivered")
    extra.chmod(0o600)
    before = report_artifacts.read(root, reports.END, "ai", sha)
    assert b"must not be delivered" not in before.markdown + before.pdf
    if damage == "empty":
        path.write_bytes(b"")
    elif damage == "wide_file":
        path.chmod(0o644)
    elif damage == "hardlink":
        os.link(path, tmp_path / "linked.pdf")
    elif damage == "directory_link":
        moved = tmp_path / "moved-reports"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    elif damage == "wide_directory":
        directory.chmod(0o755)
    else:
        manifest = deepcopy(manifest)
        manifest["revision_sha256"] = "../outside"
    with pytest.raises(ValueError):
        report_artifacts.bytes_for(root, manifest)
    if damage != "escape":
        with pytest.raises(ValueError):
            report_artifacts.seal(root, reports.END, "ai", sha)


@pytest.mark.parametrize(
    "damage",
    [
        "id",
        "bool_id",
        "name",
        "description",
        "sport",
        "segment_count",
        "step_count",
        "repeat",
        "dose",
        "phase",
        "target",
        "missing",
    ],
)
def test_garmin_readback_requires_exact_owned_identity_and_full_content(damage):
    day = {**coach.plan()["days"][0], "date": "2026-08-10"}
    day["workout"]["steps"][0]["repeat"] = 2
    dto = garmin_workouts.convert(day)
    actual = f.curated(dto, 123)
    garmin_workouts.verify(actual, dto, 123)
    if damage in ("id", "bool_id", "name", "description", "sport", "segment_count"):
        actual[damage if damage != "bool_id" else "id"] = {
            "id": 124,
            "bool_id": True,
            "name": "similar-name",
            "description": "missing details",
            "sport": "cycling",
            "segment_count": 2,
        }[damage]
    elif damage == "missing":
        actual = {"error": "not found"}
    else:
        group = actual["segments"][0]["steps"][0]
        if damage == "step_count":
            actual["segments"][0]["step_count"] = 99
        elif damage == "repeat":
            group["repeat_count"] = 1
        elif damage == "dose":
            group["steps"][0]["end_condition_value"] += 1
        elif damage == "phase":
            group["steps"][0]["type"] = "cooldown"
        else:
            group["steps"][0]["target_type"] = "heart.rate.zone"
    with pytest.raises(ValueError, match="readback_mismatch"):
        garmin_workouts.verify(actual, dto, 123)


def test_public_templates_and_private_recipient_contract_remain_separate(tmp_path):
    from skills._shared.fit_weekly import gmail_message, run_config

    value = json.loads((SOURCE / "email.module.json").read_text())
    assert value == {"schema_version": "trainlab_email_recipient_v1", "email": ""}
    for p in (SOURCE / "config/examples").glob("*.json"):
        raw = p.read_text()
        assert "@" not in raw and "Bearer " not in raw
    for value in (
        "",
        "a@example.invalid,b@example.invalid",
        "a@example.invalid\nBcc:other@example.invalid",
    ):
        with pytest.raises(ValueError):
            gmail_message.address(value)
    with pytest.raises(ValueError):
        run_config.load(tmp_path)
    assert gmail_message.address("runner@example.invalid") == "runner@example.invalid"


def test_session_zone_tables_preserve_each_identity_and_duration_ratio(
    tmp_path, monkeypatch
):
    records = []
    for ident, durations in [("701", [60, 120, 180]), ("702", [180, 60, 120])]:
        data = fit.regular_fit(extras=[fit.zones(18, durations)])
        summary = fit_parse.summarize(data, ident, storage.digest(data))
        zone = summary["sessions"][0]["hr_zones"]
        assert zone["percentages"] == pytest.approx(
            [v * 100 / sum(durations) for v in durations]
        )
        assert zone["activity_ref"] == ident and zone["fit_sha256"] == storage.digest(
            data
        )
        records.append(zone)
    root, _, _ = reports.setup(tmp_path, monkeypatch)
    revision = report_revisions.create(root, reports.END)
    view = report_revisions.view(root, reports.END, "ai", model_job.sha(revision))
    row = view["facts"]["inventory"][0]
    view["facts"]["inventory"] = [
        {
            **deepcopy(row),
            "activity_ref": z["activity_ref"],
            "fit_sha256": z["fit_sha256"],
            "recorded_session_hr_zones": z,
        }
        for z in records
    ]
    text = report_markdown.render(view).decode()
    assert text.count("设备分区序号") == 2
    assert all(
        "活动 " + z["activity_ref"] in text and z["fit_sha256"][:12] in text
        for z in records
    )
    assert "16.6667" in text and "33.3333" in text and "50" in text


def test_nonrunning_missing_intensity_is_unknown_not_a_training_input(
    tmp_path, monkeypatch
):
    root, _, _ = reports.setup(tmp_path, monkeypatch)
    revision = report_revisions.create(root, reports.END)
    assert revision["summary_content"]["other_sports"]
    assert all(
        x["explanation"]["status"] == "unknown" and x["explanation"]["evidence"] == []
        for x in revision["summary_content"]["other_sports"]
    )
    original = report_revisions.original(root, reports.END)
    plan_input = original["requests"]["plan"]["payload"]
    assert all(
        s["sport"] == "running"
        for a in plan_input["running_activities"]
        for s in a["sessions"]
    )
    assert "other_sports" not in plan_input and "current_week" not in plan_input


@pytest.mark.parametrize(
    "text",
    [
        "Bearer synthetic-private-token",
        "/Users/synthetic/private/raw.fit",
        "client_secret=synthetic-secret",
        "owner@example.invalid",
        "source/state/trainlab.db",
        "file:///private/tmp/a",
        "Bearer credential",
    ],
)
def test_private_revision_rejects_credentials_and_paths_but_preserves_sports_location(
    tmp_path, monkeypatch, text
):
    root, _, _ = reports.setup(
        tmp_path, monkeypatch, activity_name="香港海滨公开合成路线"
    )
    revision = report_revisions.create(root, reports.END)
    sha = model_job.sha(revision)
    content = reports.edited_summary(revision)
    content["core_conclusions"][0]["text"] = text
    with pytest.raises(ValueError):
        report_revisions.edit(
            root,
            reports.END,
            base_revision_id="ai",
            base_revision_sha256=sha,
            revision_id="private",
            target="summary",
            content=content,
        )
    assert (
        "香港海滨公开合成路线"
        in report_markdown.render(
            report_revisions.view(root, reports.END, "ai", sha)
        ).decode()
    )
