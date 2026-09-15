from __future__ import annotations

import asyncio
import base64
import importlib
import json
import runpy
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills._shared.fit_weekly import (
    fit_sync,
    garmin_fit,
    gmail_auth,
    gmail_labels,
    gmail_message,
    publication,
    publication_ledger,
    run_authorization,
    run_config,
    run_state,
    run_sync,
    storage,
    sync_batch,
    sync_budget,
)

NOW = "2026-09-09T00:00:00Z"


def mail_actions(action):
    return [
        action,
        gmail_labels.ensure_key("owner@example.invalid"),
        gmail_labels.apply_key(action),
    ]


def setup(tmp_path, monkeypatch, **limits):
    helper = importlib.import_module("test_m12_entrypoint")
    root = tmp_path / "instance"
    storage.initialize(root)
    private = tmp_path / "private-original"
    private.mkdir(mode=0o700)
    tokens = private / "garmin-tokens"
    tokens.mkdir(mode=0o700)
    helper.private_json(tokens / "synthetic.json", {"synthetic": True})
    helper.private_json(
        private / "gmail-token.json",
        {
            "token": "synthetic-access",
            "expiry": "2099-01-01T00:00:00Z",
            "refresh_token": "synthetic-refresh",
            "client_id": "synthetic-client",
            "client_secret": "synthetic-secret",
            "scopes": sorted(gmail_auth.SCOPES),
        },
    )
    helper.private_json(
        private / "garmin.json", {"token_root": str(tokens), "is_cn": False}
    )
    (private / "Email.md").write_text(
        "填写自己的 Gmail，用于发送和接收。\nowner@example.invalid\n"
    )
    (private / "Email.md").chmod(0o600)
    helper.private_json(
        private / "gmail.json",
        {
            "token_file": str(private / "gmail-token.json"),
            "email_file": str(private / "Email.md"),
        },
    )
    helper.private_json(
        root / "config.json",
        {
            "schema_version": "fit_run_config_v1",
            "goal": "goal.json",
            "services": {
                "garmin": str(private / "garmin.json"),
                "gmail": str(private / "gmail.json"),
            },
        },
    )
    value = helper.authorization()
    value["models"] = []
    value["publication"] = None
    value["sync"].update(
        page_size=2,
        max_pages=4,
        max_activities=8,
        max_download_calls=4,
        max_session_starts=4,
        max_tool_calls=12,
    )
    value["sync"].update(limits)
    if (
        value["sync"]["max_activities"]
        > value["sync"]["page_size"] * value["sync"]["max_pages"]
    ):
        value["sync"]["max_activities"] = (
            value["sync"]["page_size"] * value["sync"]["max_pages"]
        )
    grant = run_authorization.parse(value, now=NOW)
    value["publication"] = {
        "action_keys": mail_actions(run_sync.action_key(grant)),
        "start_date": "2026-09-01",
        "end_date": "2026-09-15",
        "max_calls": {
            "gmail.labels.list": 10,
            "gmail.labels.create": 1,
            "gmail.modify": 1,
            "gmail.send": 1,
            "gmail.profile": 15,
            "gmail.get": 15,
            "gmail.list": 5,
        },
    }
    grant = run_authorization.parse(value, now=NOW)
    helper.private_json(root / "authorization.json", value)
    monkeypatch.setattr(garmin_fit.shutil, "which", lambda _: "/synthetic/uvx")
    return root, run_config.load(root), grant, tokens


class MCP:
    def __init__(self, root, activities=None):
        self.root = root
        self.activities = activities or {}
        self.calls = []
        self.starts = 0
        self.closed = 0
        self.no_fit = set()
        self.fail = None
        self.bad_fit = False
        self.close_fail = False

    def durable(self, kind):
        import sqlite3

        with sqlite3.connect(self.root / "trainlab-fit.db") as db:
            values = [
                json.loads(r[0])
                for r in db.execute("SELECT content_json FROM documents")
            ]
        assert any(
            v.get("schema_version") == "fit_sync_budget_call_v1" and v["kind"] == kind
            for v in values
        )
        assert any(
            v.get("schema_version") == "fit_transport_intent_v1"
            and v["call_kind"] == kind
            for v in values
        )

    @asynccontextmanager
    async def factory(self, spec):
        self.durable("initialize")
        assert "--offline" in spec["args"]
        assert spec["environment"]["GARMIN_IS_CN"] == "false"
        self.starts += 1
        try:
            yield self
        finally:
            self.closed += 1
            if self.close_fail:
                raise OSError("synthetic close")

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=n) for n in garmin_fit.TOOLS], nextCursor=None
        )

    async def call_tool(self, name, arguments):
        self.durable("inventory" if name == "get_activities_by_date" else "download")
        self.calls.append((name, dict(arguments)))
        if self.fail == name:
            raise ConnectionError("synthetic")
        if name == "get_activities_by_date":
            start, end = arguments["start_date"], arguments["end_date"]
            items = [
                (day, ref)
                for day, refs in self.activities.items()
                if start <= day <= end
                for ref in refs
            ]
            page, size = arguments["page"], arguments["page_size"]
            items = items[page * size : (page + 1) * size]
            more = len(items) == size
            result = {
                "count": len(items),
                "page": page,
                "page_size": size,
                "has_more": more,
                "date_range": {"start": start, "end": end},
                "activities": [
                    {"id": int(ref), "start_time": day + " 01:00:00"}
                    for day, ref in items
                ],
            }
            if more:
                result["next_page"] = page + 1
            raw = json.dumps(result)
        else:
            ref = str(arguments["activity_id"])
            if ref in self.no_fit:
                raw = f"No fit data returned for activity {ref}"
            else:
                path = Path(arguments["output_dir"]) / (ref + ".fit")
                data = importlib.import_module("test_m12_fit_sync").fit_bytes(ref)
                path.write_bytes(b"broken" if self.bad_fit else data)
                path.chmod(0o600)
                raw = json.dumps(
                    {
                        "activity_id": int(ref),
                        "format": "fit",
                        "file_path": str(path),
                        "size_bytes": path.stat().st_size,
                        "message": "Activity file saved.",
                    }
                )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=raw)], isError=False
        )


class HTTP:
    def __init__(self):
        self.calls = []
        self.labels = []
        self.applied_labels = []
        self.raw = None
        self.lost = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-access"
        if url.endswith("/labels"):
            if method == "POST":
                assert kwargs["json"] == {"name": "TrainLab"}
                self.labels = [
                    {"id": "Label_synthetic", "name": "TrainLab", "type": "user"}
                ]
            return SimpleNamespace(
                status_code=200, json=lambda: {"labels": self.labels}
            )
        if url.endswith("/modify"):
            assert kwargs["json"] == {"addLabelIds": ["Label_synthetic"]}
            self.applied_labels = ["Label_synthetic"]
            return SimpleNamespace(status_code=200, json=lambda: {"id": "abc123"})
        if url.endswith("/profile"):
            value: dict[str, Any] = {"emailAddress": "owner@example.invalid"}
        elif url.endswith("/send"):
            raw = gmail_message.decode(kwargs["json"]["raw"])
            from email import policy
            from email.parser import BytesParser

            mail = BytesParser(policy=policy.default).parsebytes(raw)
            mail.replace_header("Message-ID", "<actual@example.invalid>")
            self.raw = base64.urlsafe_b64encode(
                mail.as_bytes(policy=policy.SMTP)
            ).decode()
            if self.lost:
                raise ConnectionError("synthetic response lost")
            value = {"id": "abc123"}
        elif url.endswith("/messages"):
            value = {"messages": [{"id": "abc123"}]} if self.raw else {"messages": []}
        else:
            value = {"id": "abc123", "raw": self.raw, "labelIds": self.applied_labels}
        return SimpleNamespace(status_code=200, json=lambda: value)


def collect(config, grant, fake, dates=None, now=lambda: NOW, recovery=0):
    return asyncio.run(
        run_sync.collect(
            config,
            grant,
            dates=dates,
            now=now,
            session_factory=fake.factory,
            recovery=recovery,
        )
    )


def test_true_module_discrete_sync_and_real_gmail_default_chain(
    tmp_path, monkeypatch, capsys
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake = MCP(root, {"2026-09-07": ["101", "102"], "2026-09-09": ["103"]})
    fake.no_fit.add("103")
    http = HTTP()
    monkeypatch.setattr(garmin_fit, "sdk_session", fake.factory)
    monkeypatch.setattr(requests, "Session", lambda: http)
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: NOW)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fit_weekly",
            "--instance",
            str(root),
            "--authorization",
            "authorization.json",
            "sync",
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_module("skills._shared.fit_weekly", run_name="__main__")
    assert result.value.code == 0
    output = json.loads(capsys.readouterr().out)
    batch = sync_batch.read(root, output["batch_key"])
    assert batch["status"] == "complete"
    assert [s["snapshot"]["fit_count"] for s in batch["segments"]] == [2, 0]
    assert [s["snapshot"]["no_fit_count"] for s in batch["segments"]] == [0, 1]
    assert batch["segments"][1]["snapshot"]["days"][0]["status"] == "provisional"
    queried = {
        (args["start_date"], args["end_date"])
        for name, args in fake.calls
        if name == "get_activities_by_date"
    }
    assert queried == {("2026-09-07", "2026-09-07"), ("2026-09-09", "2026-09-09")}
    assert fake.starts == fake.closed == 2
    assert sum(url.endswith("/send") for _, url in http.calls) == 1
    assert output["mail"]["evidence"]["message_id"] == "<actual@example.invalid>"
    calls = (len(fake.calls), len(http.calls))
    assert collect(config, grant, fake) == batch
    assert run_sync.notify(config, grant, batch, now=lambda: NOW)["status"] == "success"
    assert (len(fake.calls), len(http.calls)) == calls


@pytest.mark.parametrize(
    "limit,value,expected_starts,expected_calls",
    [
        ("max_pages", 1, 1, 1),
        ("max_session_starts", 1, 1, 1),
        ("max_tool_calls", 2, 1, 1),
    ],
)
def test_total_call_budget_across_subjobs(
    tmp_path, monkeypatch, limit, value, expected_starts, expected_calls
):
    root, config, grant, _ = setup(tmp_path, monkeypatch, **{limit: value})
    fake = MCP(root)
    result = collect(config, grant, fake)
    assert result["status"] == "failed"
    assert fake.starts == expected_starts and len(fake.calls) == expected_calls
    assert result["segments"][0]["status"] == "complete"
    assert result["segments"][1]["status"] == "failed"
    assert run_state.status(root)["business"]["failed"] == 1
    assert collect(config, grant, fake) == result
    assert fake.starts == expected_starts and len(fake.calls) == expected_calls


def test_total_download_limit_and_activity_capacity(tmp_path, monkeypatch):
    root, config, grant, _ = setup(tmp_path, monkeypatch, max_download_calls=1)
    fake = MCP(root, {"2026-09-07": ["101"], "2026-09-09": ["102"]})
    result = collect(config, grant, fake)
    assert result["status"] == "failed"
    assert sum(n == "download_activity_file" for n, _ in fake.calls) == 1
    assert result["segments"][1]["snapshot"]["collection_complete"] is False
    assert result["segments"][1]["snapshot"]["inventory_complete"] is True


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_activity_limit_is_reserved_before_query(tmp_path, monkeypatch, limit):
    root, config, grant, _ = setup(tmp_path, monkeypatch, max_activities=limit)
    fake = MCP(root, {"2026-09-07": ["101"], "2026-09-09": ["102"]})
    result = collect(config, grant, fake)
    assert sum(n == "get_activities_by_date" for n, _ in fake.calls) == (
        0 if limit < 2 else 1 if limit == 2 else 2
    )
    assert result["status"] == ("complete" if limit == 3 else "failed")


@pytest.mark.parametrize("damage", ["bad_fit", "download", "page", "close"])
def test_failed_download_page_and_close_have_frozen_failure_mail(
    tmp_path, monkeypatch, damage
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake = MCP(root, {"2026-09-07": ["101"]})
    fake.bad_fit = damage == "bad_fit"
    fake.close_fail = damage == "close"
    fake.fail = (
        "download_activity_file"
        if damage == "download"
        else "get_activities_by_date"
        if damage == "page"
        else None
    )
    http = HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    result = collect(config, grant, fake)
    assert result["status"] == "failed"
    assert result["segments"][0]["snapshot"]["collection_complete"] is False
    assert (
        run_sync.notify(config, grant, result, now=lambda: NOW)["status"] == "success"
    )
    request = publication.validate_source(root, run_sync.action_key(grant))
    assert request["payload"]["sync_batch"] == result
    assert "未完成" in request["payload"]["body"]


def test_missing_mail_grant_never_loads_gmail_or_calls_http(tmp_path, monkeypatch):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    value = grant.value()
    value["publication"] = None
    grant = run_authorization.parse(value, now=NOW)
    batch = collect(config, grant, MCP(root))
    monkeypatch.setattr(
        gmail_auth, "Auth", lambda *a, **k: pytest.fail("not authorized")
    )
    with pytest.raises(ValueError):
        run_sync.notify(config, grant, batch, now=lambda: NOW)


def test_lost_send_response_only_reconciles_and_frozen_mail_survives_move(
    tmp_path, monkeypatch
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake, http = MCP(root), HTTP()
    http.lost = True
    monkeypatch.setattr(requests, "Session", lambda: http)
    batch = collect(config, grant, fake)
    assert run_sync.notify(config, grant, batch, now=lambda: NOW)["status"] == "unknown"
    before = publication.validate_source(root, run_sync.action_key(grant))
    moved = root.with_name("moved")
    root.rename(moved)
    config = run_config.load(moved)
    assert run_sync.notify(config, grant, batch, now=lambda: NOW)["status"] == "success"
    assert publication.validate_source(moved, run_sync.action_key(grant)) == before
    assert sum(url.endswith("/send") for _, url in http.calls) == 1


def test_same_grant_different_batch_keys_share_allowance(tmp_path, monkeypatch):
    root, config, grant, _ = setup(tmp_path, monkeypatch, max_pages=1)
    fake = MCP(root)
    first = collect(config, grant, fake, ["2026-09-07"])
    second = collect(config, grant, fake, ["2026-09-09"])
    assert first["batch_key"] != second["batch_key"]
    assert first["status"] == "complete" and second["status"] == "failed"
    assert fake.starts == 1 and len(fake.calls) == 1


def test_budget_wall_deadline_and_rollback_survive_reopen_and_move(
    tmp_path, monkeypatch
):
    root, _, grant, _ = setup(
        tmp_path, monkeypatch, total_timeout_seconds=30, timeout_seconds=10
    )
    clock = [NOW]
    budget = sync_budget.Budget(grant, lambda: clock[0])
    budget.claim(root)
    clock[0] = "2026-09-09T00:00:10Z"
    with storage.open_store(root) as db:
        assert 0 < budget.bind(db).remaining() <= 20
    moved = root.with_name("relocated")
    root.rename(moved)
    clock[0] = "2026-09-09T00:00:09Z"
    with pytest.raises(ValueError, match="rollback"):
        sync_budget.Budget(grant, lambda: clock[0]).claim(moved)
    clock[0] = "2026-09-09T00:00:30Z"
    with pytest.raises(ValueError, match="exhausted"):
        sync_budget.Budget(grant, lambda: clock[0]).claim(moved)


def test_wall_time_consumed_across_separate_jobs(tmp_path, monkeypatch):
    root, config, grant, _ = setup(
        tmp_path, monkeypatch, total_timeout_seconds=30, timeout_seconds=10
    )
    clock = [NOW]
    fake = MCP(root)
    original = fake.call_tool

    async def elapsed(name, arguments):
        value = await original(name, arguments)
        clock[0] = (
            "2026-09-09T00:00:20Z" if len(fake.calls) == 1 else "2026-09-09T00:00:30Z"
        )
        return value

    monkeypatch.setattr(fake, "call_tool", elapsed)
    result = collect(config, grant, fake, now=lambda: clock[0])
    assert result["segments"][0]["status"] == "complete"
    assert result["segments"][1]["status"] == "failed"
    assert fake.closed == 2
    before = len(fake.calls)
    assert collect(config, grant, fake, now=lambda: clock[0]) == result
    assert len(fake.calls) == before


def test_real_process_crash_after_claim_consumes_session_and_relocates(
    tmp_path, monkeypatch
):
    import multiprocessing
    import os

    root, config, grant, _ = setup(tmp_path, monkeypatch, max_session_starts=1)

    def child():
        original = fit_sync.put

        def crash(db, key, value):
            result = original(db, key, value)
            if (
                value.get("schema_version") == "fit_sync_budget_call_v1"
                and value["kind"] == "initialize"
            ):
                os._exit(91)
            return result

        fit_sync.put = crash
        collect(config, grant, MCP(root))

    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join()
    assert process.exitcode == 91
    moved = root.with_name("moved-after-claim")
    root.rename(moved)
    fake = MCP(moved)
    result = collect(run_config.load(moved), grant, fake)
    assert result["status"] == "failed" and fake.starts == 0 and fake.calls == []


def test_capture_crash_before_settlement_recovers_without_second_page(
    tmp_path, monkeypatch
):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake = MCP(root, {"2026-09-07": ["101"]})
    original = fit_sync.put
    armed = True

    def crash(db, key, value):
        nonlocal armed
        if armed and ":outcome:" in key and "items" in (value.get("value") or {}):
            armed = False
            raise OSError("synthetic capture before db")
        return original(db, key, value)

    monkeypatch.setattr(fit_sync, "put", crash)
    with pytest.raises(OSError):
        collect(config, grant, fake)
    assert sync_batch.read(root, run_sync.batch_key(grant)) is None
    result = collect(config, grant, fake)
    assert result["status"] == "complete"
    assert (
        sum(
            n == "get_activities_by_date" and a["start_date"] == "2026-09-07"
            for n, a in fake.calls
        )
        == 1
    )


def test_batch_seal_and_mail_prepare_interruptions_preserve_content(
    tmp_path, monkeypatch
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake, http = MCP(root), HTTP()
    original = fit_sync.put
    armed = True

    def crash(db, key, value):
        nonlocal armed
        if armed and key.endswith(":sealed"):
            armed = False
            raise OSError("synthetic sealing interrupt")
        return original(db, key, value)

    monkeypatch.setattr(fit_sync, "put", crash)
    with pytest.raises(OSError):
        collect(config, grant, fake)
    with pytest.raises(ValueError, match="unsealed"):
        publication.prepare_sync_batch(
            root,
            run_sync.batch_key(grant),
            recipient="reader@example.invalid",
            sender="owner@example.invalid",
        )
    result = collect(config, grant, fake)
    assert fake.starts == 2 and len(fake.calls) == 2
    prepare = publication_ledger.prepare
    prepared = []

    def crash_prepare(root, request):
        prepare(root, request)
        prepared.append(request)
        raise OSError("synthetic after prepare")

    monkeypatch.setattr(publication_ledger, "prepare", crash_prepare)
    with pytest.raises(OSError):
        run_sync.notify(config, grant, result, now=lambda: NOW)
    assert http.calls == []
    monkeypatch.setattr(publication_ledger, "prepare", prepare)
    monkeypatch.setattr(requests, "Session", lambda: http)
    assert (
        run_sync.notify(config, grant, result, now=lambda: NOW)["status"] == "success"
    )
    assert publication.validate_source(root, run_sync.action_key(grant)) == prepared[0]


@pytest.mark.parametrize(
    "case", ["wide", "hardlink", "symlink", "parent_symlink", "owner"]
)
def test_external_explicit_private_paths_keep_safety_boundary(
    tmp_path, monkeypatch, case
):
    import os

    root, config, _, _ = setup(tmp_path, monkeypatch)
    path = config.service_path("gmail")
    if case == "wide":
        path.chmod(0o644)
    elif case == "hardlink":
        os.link(path, path.with_name("hardlink"))
    elif case == "symlink":
        path.rename(path.with_name("target"))
        path.symlink_to(path.with_name("target"))
    elif case == "parent_symlink":
        directory = path.parent
        directory.rename(directory.with_name("target"))
        directory.symlink_to(directory.with_name("target"), target_is_directory=True)
    else:
        monkeypatch.setattr(storage.os, "getuid", lambda: -1)
    with pytest.raises(ValueError, match="config_service_unavailable"):
        config.service("gmail")


def test_existing_fit_reuse_and_complete_empty_day(tmp_path, monkeypatch):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    path = tmp_path / "original.fit"
    path.write_bytes(importlib.import_module("test_m12_fit_sync").fit_bytes("101"))
    path.chmod(0o600)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", path, storage.digest(path.read_bytes()))
    result = collect(config, grant, MCP(root, {"2026-09-07": ["101"]}))
    assert result["status"] == "complete"
    assert result["segments"][0]["snapshot"]["fit_count"] == 1
    assert all(
        call["kind"] != "download"
        for segment in result["segments"]
        for call in segment["calls"]
    )
    assert result["segments"][1]["snapshot"]["activity_count"] == 0


def test_explicit_recovery_uses_original_unfinished_jobs_and_keeps_sent_batch(
    tmp_path, monkeypatch
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake, http = MCP(root, {"2026-09-07": ["101"]}), HTTP()
    fake.fail = "download_activity_file"
    monkeypatch.setattr(requests, "Session", lambda: http)
    original = collect(config, grant, fake)
    assert original["status"] == "failed"
    assert (
        run_sync.notify(config, grant, original, now=lambda: NOW)["status"] == "success"
    )
    request = publication.validate_source(root, run_sync.action_key(grant))
    fake.fail = None
    recovered = collect(config, grant, fake, recovery=1)
    assert recovered["status"] == "complete"
    assert (
        sum(
            n == "get_activities_by_date" and a["start_date"] == "2026-09-07"
            for n, a in fake.calls
        )
        == 1
    )
    assert publication.validate_source(root, run_sync.action_key(grant)) == request
    assert sync_batch.read(root, original["batch_key"]) == original
    with pytest.raises(ValueError):
        run_sync.notify(config, grant, recovered, now=lambda: NOW)
    assert sum(url.endswith("/send") for _, url in http.calls) == 1
    assert collect(config, grant, fake, recovery=1) == recovered
    with pytest.raises(ValueError, match="recovery_source"):
        collect(config, grant, fake, recovery=2)


def test_tool_budget_cannot_pay_only_for_unusable_session(tmp_path, monkeypatch):
    root, config, grant, _ = setup(tmp_path, monkeypatch, max_tool_calls=1)
    fake = MCP(root)
    assert collect(config, grant, fake)["status"] == "failed"
    assert fake.starts == 0 and fake.calls == []


def test_daily_selection_includes_exact_gaps_and_unfinished_jobs(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import sync_calendar

    root, _, grant, _ = setup(tmp_path, monkeypatch)
    value = grant.value()
    value["sync"]["dates"] = ["2026-09-05", "2026-09-08", "2026-09-09"]
    grant = run_authorization.parse(value, now=NOW)
    with storage.open_store(root) as db:
        db.execute("INSERT INTO sync_gaps VALUES('2026-09-05',?)", (NOW,))
        sync_calendar.durable(db)
    result = run_sync.daily_dates(root, grant, now=NOW)
    assert result["dates"] == ["2026-09-05", "2026-09-08", "2026-09-09"]
    assert result["ranges"] == [["2026-09-05"], ["2026-09-08", "2026-09-09"]]
    assert result["unfinished_jobs"] == []
    value["sync"]["dates"].remove("2026-09-05")
    with pytest.raises(ValueError, match="not_authorized"):
        run_sync.daily_dates(root, run_authorization.parse(value, now=NOW), now=NOW)


def test_no_config_or_provider_read_when_successfully_replaying_batch(
    tmp_path, monkeypatch
):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake = MCP(root)
    saved = collect(config, grant, fake)
    config.service_path("garmin").unlink()
    assert collect(config, grant, fake) == saved
    assert fake.starts == 2


def observe_service_reads(monkeypatch):
    reads = []
    original = run_config.Config.service

    def service(config, name):
        reads.append(name)
        return original(config, name)

    monkeypatch.setattr(run_config.Config, "service", service)
    return reads


def test_initial_sync_freezes_complete_grant_before_service_reads(
    tmp_path, monkeypatch
):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    frozen = root / "authorizations" / (storage.digest(grant.key.encode()) + ".json")
    service = run_config.Config.service

    def verify_before_service(config, name):
        assert frozen.read_bytes() == grant._body.encode()
        return service(config, name)

    monkeypatch.setattr(run_config.Config, "service", verify_before_service)
    assert collect(config, grant, MCP(root))["status"] == "complete"


def test_daily_selection_rejects_changed_frozen_grant(tmp_path, monkeypatch):
    root, _, grant, _ = setup(tmp_path, monkeypatch)
    value = grant.value()
    value["sync"]["dates"] = ["2026-09-08", "2026-09-09"]
    grant = run_authorization.parse(value, now=NOW)
    grant.freeze(root, now=NOW)
    assert run_sync.daily_dates(root, grant, now=NOW)["dates"] == value["sync"]["dates"]
    value["sync"]["max_pages"] += 1
    with pytest.raises(ValueError, match="conflict"):
        run_sync.daily_dates(root, run_authorization.parse(value, now=NOW), now=NOW)


@pytest.mark.parametrize("entry", ["collect", "notify"])
def test_frozen_grant_cannot_add_mail_permission(tmp_path, monkeypatch, entry):
    import requests

    root, config, changed, _ = setup(tmp_path, monkeypatch)
    value = changed.value()
    value["publication"] = None
    original = run_authorization.parse(value, now=NOW)
    fake, http = MCP(root), HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    batch = collect(config, original, fake)
    frozen = root / "authorizations" / (storage.digest(original.key.encode()) + ".json")
    before = frozen.read_bytes()
    assert json.loads(before)["publication"] is None
    calls = (fake.starts, len(fake.calls))
    reads = observe_service_reads(monkeypatch)
    with pytest.raises(ValueError, match="conflict"):
        if entry == "collect":
            collect(config, changed, fake)
        else:
            run_sync.notify(config, changed, batch, now=lambda: NOW)
    assert reads == [] and http.calls == []
    assert (fake.starts, len(fake.calls)) == calls
    assert frozen.read_bytes() == before


@pytest.mark.parametrize("change", ["budget", "window", "models"])
@pytest.mark.parametrize(
    "entry",
    ["sealed", "other_dates", "recovery", "notify", "prepared", "unknown", "success"],
)
def test_frozen_grant_conflict_precedes_every_service_path(
    tmp_path, monkeypatch, change, entry
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake, http = MCP(root, {"2026-09-07": ["101"]}), HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    if entry == "recovery":
        fake.fail = "download_activity_file"
    batch = collect(
        config, grant, fake, ["2026-09-07"] if entry == "other_dates" else None
    )
    if entry == "prepared":
        publication.prepare_sync_batch(
            root,
            batch["batch_key"],
            recipient="reader@example.invalid",
            sender="owner@example.invalid",
        )
    if entry in ("unknown", "success"):
        http.lost = entry == "unknown"
        assert run_sync.notify(config, grant, batch, now=lambda: NOW)["status"] == entry
    value = grant.value()
    if change == "budget":
        value["sync"]["max_download_calls"] += 1
    elif change == "window":
        value["expires_utc"] = "2026-09-16T00:00:00Z"
    else:
        value["models"] = importlib.import_module(
            "test_m12_entrypoint"
        ).authorization()["models"]
    changed = run_authorization.parse(value, now=NOW)
    calls = (fake.starts, len(fake.calls), len(http.calls))
    reads = observe_service_reads(monkeypatch)
    with pytest.raises(ValueError, match="conflict"):
        if entry in ("sealed", "other_dates", "recovery"):
            collect(
                config,
                changed,
                fake,
                ["2026-09-09"] if entry == "other_dates" else None,
                recovery=1 if entry == "recovery" else 0,
            )
        else:
            run_sync.notify(config, changed, batch, now=lambda: NOW)
    assert reads == []
    assert (fake.starts, len(fake.calls), len(http.calls)) == calls


def test_identical_grant_success_replay_after_expiry_and_move_is_service_free(
    tmp_path, monkeypatch
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake, http = MCP(root), HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    batch = collect(config, grant, fake)
    state = run_sync.notify(config, grant, batch, now=lambda: NOW)
    assert state["status"] == "success"
    frozen = {p.name: p.read_bytes() for p in (root / "authorizations").iterdir()}
    moved = root.with_name("moved-complete")
    root.rename(moved)
    config = run_config.load(moved)
    reads = observe_service_reads(monkeypatch)
    calls = (fake.starts, len(fake.calls), len(http.calls))

    def expired():
        return "2026-09-16T00:00:00Z"

    assert collect(config, grant, fake, now=expired) == batch
    assert run_sync.notify(config, grant, batch, now=expired) == state
    assert reads == []
    assert (fake.starts, len(fake.calls), len(http.calls)) == calls
    assert {
        p.name: p.read_bytes() for p in (moved / "authorizations").iterdir()
    } == frozen


@pytest.mark.parametrize("readonly", [False, True])
def test_new_precise_mail_grant_freezes_full_content_and_preserves_action(
    tmp_path, monkeypatch, readonly
):
    import requests

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    value = grant.value()
    if not readonly:
        value["publication"] = None
    original = run_authorization.parse(value, now=NOW)
    fake, http = MCP(root), HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    batch = collect(config, original, fake)
    if readonly:
        http.lost = True
        assert (
            run_sync.notify(config, original, batch, now=lambda: NOW)["status"]
            == "unknown"
        )
    value = grant.value()
    value.update(
        key="explicit-new-mail-grant",
        starts_utc="2026-09-16T00:00:00Z",
        expires_utc="2026-09-17T00:00:00Z",
        sync=None,
    )
    if readonly:
        del value["publication"]["max_calls"]["gmail.send"]
    later = "2026-09-16T01:00:00Z"
    fresh = run_authorization.parse(value, now=later)
    frozen = root / "authorizations" / (storage.digest(fresh.key.encode()) + ".json")
    service = run_config.Config.service

    def verify_before_service(config, name):
        assert frozen.read_bytes() == fresh._body.encode()
        return service(config, name)

    monkeypatch.setattr(run_config.Config, "service", verify_before_service)
    assert (
        run_sync.notify(config, fresh, batch, now=lambda: later)["status"] == "success"
    )
    assert sum(url.endswith("/send") for _, url in http.calls) == 1
    assert len(list((root / "authorizations").iterdir())) == 2
    calls = len(http.calls)
    value["expires_utc"] = "2026-09-18T00:00:00Z"
    changed = run_authorization.parse(value, now=later)
    with pytest.raises(ValueError, match="conflict"):
        run_sync.notify(config, changed, batch, now=lambda: later)
    assert len(http.calls) == calls


def test_shared_scope_or_changed_authorization_fails_without_more_calls(
    tmp_path, monkeypatch
):
    root, config, grant, token = setup(tmp_path, monkeypatch)
    fake = MCP(root)
    collect(config, grant, fake, ["2026-09-07"])
    value = grant.value()
    value["sync"]["max_download_calls"] += 1
    changed = run_authorization.parse(value, now=NOW)
    with pytest.raises(ValueError, match="conflict"):
        collect(config, changed, fake, ["2026-09-09"])
    outside = grant.sync_spec(["2026-09-09"], is_cn=False, now=NOW)
    from dataclasses import replace

    outside = replace(outside, max_download_calls=99)
    budget = sync_budget.Budget(grant, lambda: NOW)
    with pytest.raises(ValueError, match="scope"):
        asyncio.run(
            fit_sync.synchronize(
                root,
                outside,
                token_root=token,
                session_factory=fake.factory,
                shared_budget=budget.bind,
            )
        )
    assert fake.starts == 1 and len(fake.calls) == 1


def test_already_completed_later_job_retains_actual_result_after_earlier_failure(
    tmp_path, monkeypatch
):
    root, config, grant, _ = setup(tmp_path, monkeypatch)
    fake = MCP(root)
    assert collect(config, grant, fake, ["2026-09-09"])["status"] == "complete"
    fake.fail = "get_activities_by_date"
    result = collect(config, grant, fake)
    assert result["status"] == "failed"
    assert result["segments"][1]["status"] == "complete"


def test_batch_sealing_rejects_unbacked_snapshot(tmp_path, monkeypatch):
    import copy

    root, config, grant, _ = setup(tmp_path, monkeypatch)
    batch = collect(config, grant, MCP(root))
    segments = copy.deepcopy(batch["segments"])
    segments[0]["snapshot"]["fit_count"] = 999
    with pytest.raises(ValueError, match="snapshot_conflict"):
        sync_batch.seal(root, batch["batch_key"], segments)


def test_total_deadline_during_slow_close_retains_audit_without_success(
    tmp_path, monkeypatch
):
    root, config, grant, _ = setup(
        tmp_path, monkeypatch, total_timeout_seconds=0.15, timeout_seconds=0.15
    )
    fake = MCP(root)
    original = fake.factory

    @asynccontextmanager
    async def delayed_close(spec):
        async with original(spec) as client:
            try:
                yield client
            finally:
                await asyncio.sleep(0.12)

    monkeypatch.setattr(fake, "factory", delayed_close)
    result = collect(config, grant, fake)
    assert result["status"] == "failed"
    assert fake.closed == fake.starts
    count = len(fake.calls)
    assert collect(config, grant, fake) == result
    assert len(fake.calls) == count


def test_precise_contiguous_ranges() -> None:
    assert run_sync.ranges(["2026-09-01", "2026-09-03", "2026-09-04"]) == [
        ["2026-09-01"],
        ["2026-09-03", "2026-09-04"],
    ]
    with pytest.raises(ValueError):
        run_sync.ranges(["2026-09-03", "2026-09-01"])


def test_real_module_import_initializes_and_replays_without_services(
    tmp_path: Path,
) -> None:
    helper = importlib.import_module("test_m12_legacy_fit_import")
    entry = importlib.import_module("test_m12_entrypoint")
    archive = helper.archive_fixture(tmp_path)
    root = tmp_path / "new-instance"
    first = entry.cli(root, "import-history", "--archive", str(archive))
    assert first.returncode == 0, first.stderr
    receipt = json.loads(first.stdout)
    assert receipt["fit_count"] == 1
    assert receipt["history_coverage"] == "not_established"
    assert entry.cli(root, "import-history", "--archive", str(archive)).returncode == 0
    with storage.open_store(root) as db:
        assert storage.verify_fit_closure(db, root) == 1


def test_batch_action_is_stable_and_bound_to_exact_dates() -> None:
    entry = importlib.import_module("test_m12_entrypoint")
    grant = run_authorization.parse(entry.authorization(), now=entry.NOW)
    first = run_sync.action_key(grant)
    assert first == run_sync.action_key(grant)
    assert first != run_sync.action_key(grant, ["2026-09-07"])
