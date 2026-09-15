from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(SOURCE),
    str(SOURCE / "tests/code/fixtures"),
    str(SOURCE / "tests/code/contract"),
]

model_job = importlib.import_module("skills._shared.fit_weekly.model_job")
report_artifacts = importlib.import_module("skills._shared.fit_weekly.report_artifacts")
run_sync = importlib.import_module("skills._shared.fit_weekly.run_sync")
gmail_labels = importlib.import_module("skills._shared.fit_weekly.gmail_labels")
storage = importlib.import_module("skills._shared.fit_weekly.storage")

f = importlib.import_module("m12_weekly_factory")


def test_unified_chain(tmp_path, monkeypatch, capsys):
    root, _, grant, provider, http = f.setup(tmp_path, monkeypatch)
    original_request = http.request
    message_labels: dict[str, list[str]] = {}

    def request(method, url, **kwargs):
        ident = url.removesuffix("/modify").rsplit("/", 1)[-1]
        http.applied_labels = message_labels.get(ident, [])
        response = original_request(method, url, **kwargs)
        if url.endswith("/send"):
            ident = f"abc123{len(message_labels) + 1}"
            http.sent[ident] = http.sent.pop("abc123")
            message_labels[ident] = []
            return SimpleNamespace(status_code=200, json=lambda: {"id": ident})
        if url.endswith("/modify"):
            message_labels[ident] = list(http.applied_labels)
            return SimpleNamespace(status_code=200, json=lambda: {"id": ident})
        return response

    monkeypatch.setattr(http, "request", request)
    helper = importlib.import_module("m12_history_factory")
    old, names = helper.fixture(tmp_path / "public-history")
    raw = provider.inventory.activities[0][2]
    (old / "state/raw/activities/synthetic.fit").write_bytes(raw)
    with sqlite3.connect(old / "state/trainlab.db") as db:
        db.executescript("""
        CREATE TABLE activity_inventory(id INTEGER PRIMARY KEY,provider TEXT,provider_activity_id TEXT,activity_date TEXT);
        CREATE TABLE raw_files(id INTEGER PRIMARY KEY,provider TEXT,data_class TEXT,file_format TEXT,activity_inventory_id INTEGER,activity_binding_state TEXT,integrity_state TEXT,data_date TEXT,relative_path TEXT,sha256 TEXT,byte_size INTEGER);
        INSERT INTO activity_inventory VALUES(1,'garmin','101','2026-08-02');
        """)
        db.execute(
            "INSERT INTO raw_files VALUES(1,'garmin','activity','fit',1,'bound','verified','2026-08-02','activities/synthetic.fit',?,?)",
            (storage.digest(raw), len(raw)),
        )
    archive = helper.pack(old, tmp_path / "archive", names)
    archive_bytes = {
        str(p.relative_to(archive)): p.read_bytes()
        for p in archive.rglob("*")
        if p.is_file()
    }
    assert f.cli(root, monkeypatch, "import-history", "--archive", str(archive)) == 0
    imported = json.loads(capsys.readouterr().out)
    assert (
        imported["fit_count"] == 1
        and imported["provider_calls"] == imported["external_actions"] == 0
    )
    assert not provider.calls and not http.calls
    assert archive_bytes == {
        str(p.relative_to(archive)): p.read_bytes()
        for p in archive.rglob("*")
        if p.is_file()
    }
    shutil.rmtree(archive.parent)
    shutil.rmtree(old.parent)
    value = grant.value()
    sync_action = run_sync.action_key(grant)
    value["publication"]["action_keys"].extend(
        [sync_action, gmail_labels.apply_key(sync_action)]
    )
    (root / "authorization.json").write_text(json.dumps(value))
    assert (
        f.cli(root, monkeypatch, "--authorization", "authorization.json", "sync") == 0
    )
    synced = json.loads(capsys.readouterr().out)
    assert synced["status"] == "complete" and synced["mail"]["status"] == "success"
    assert all(
        synced["mail"][part]["status"] == "success"
        for part in ("ensure_label", "mail", "label")
    )
    assert sum(url.endswith("/modify") for _, url, _ in http.calls) == 1
    assert [
        args["activity_id"]
        for name, args in provider.calls
        if name == "download_activity_file"
    ] == [102]
    assert (
        f.cli(
            root,
            monkeypatch,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            f.END,
        )
        == 0
    )
    weekly = json.loads(capsys.readouterr().out)
    assert weekly["status"] == "complete"
    assert all(
        weekly["publication"]["mail"][part]["status"] == "success"
        for part in ("ensure_label", "mail", "label")
    )
    assert all(v["status"] == "succeeded" for v in weekly["stages"].values())
    assert len(provider.workouts) == len(provider.calendar) == 3
    assert sum(url.endswith("/send") for _, url, _ in http.calls) == 2
    assert sum(url.endswith("/modify") for _, url, _ in http.calls) == 2
    assert len(http.sent) == 2
    assert message_labels == {
        "abc1231": ["Label_synthetic"],
        "abc1232": ["Label_synthetic"],
    }
    assert (
        sum(
            method == "POST" and url.endswith("/labels")
            for method, url, _ in http.calls
        )
        == 1
    )
    bundle = report_artifacts.read_sealed(root, f.END)
    assert "运动表现" in bundle.markdown.decode() and bundle.pdf.startswith(b"%PDF")
    assert weekly["publication"]["mail"]["evidence"]["pdf_sha256"] == storage.digest(
        bundle.pdf
    )
    assert (
        provider.workouts[100]["workoutSegments"][0]["workoutSteps"][0][
            "numberOfIterations"
        ]
        == 2
    )
    capture_hashes = {}
    for stage in ("plan", "summary"):
        process = (
            model_job.capture_path(root, f.END, stage=stage).parent
            / "command/process/capture.json"
        )
        assert process.is_file()
        capture_hashes[stage] = storage.digest(process.read_bytes())
    before = (len(provider.calls), len(http.calls))
    moved = tmp_path / "moved-instance"
    root.rename(moved)
    (moved / "model.json").unlink()
    (moved / "weekly-goal.md").unlink()
    assert f.cli(moved, monkeypatch, "weekly", "--period-end", f.END) == 0
    capsys.readouterr()
    assert f.cli(moved, monkeypatch, "reconcile") == 0
    capsys.readouterr()
    assert f.cli(moved, monkeypatch, "status") == 0
    state = json.loads(capsys.readouterr().out)
    assert state["business"] == {"failed": 0, "pending": 0, "unknown": 0}
    assert (len(provider.calls), len(http.calls)) == before
    for stage in capture_hashes:
        process = (
            model_job.capture_path(moved, f.END, stage=stage).parent
            / "command/process/capture.json"
        )
        assert storage.digest(process.read_bytes()) == capture_hashes[stage]
    report = {
        "imported_fits": 1,
        "downloaded_fits": 1,
        "model_processes": 2,
        "gmail_sends": 2,
        "gmail_label_creates": 1,
        "gmail_label_applies": 2,
        "workouts": 3,
        "schedules": 3,
        "move_repeat_calls": 0,
        "pdf_sha256": storage.digest(bundle.pdf),
        "model_capture_sha256": capture_hashes,
        "business": state["business"],
    }
    if destination := os.environ.get("TRAINLAB_CHAIN_EVIDENCE"):
        Path(destination).write_text(json.dumps(report, sort_keys=True))
