"""Durable identities and budgets must survive restarts and relocation."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import publication_ledger as ledger
from skills._shared.fit_weekly import storage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_publication_factory")


def test_identity_conflict_and_unknown_survive_move(tmp_path):
    root = tmp_path / "instance"
    storage.initialize(root)
    request = {
        "schema_version": "fit_delivery_request_v1",
        "action_key": "sync:one:gmail",
        "kind": "gmail",
        "source_key": "sync:one",
        "source_sha256": "a" * 64,
        "date": "2026-08-10",
        "payload": {"synthetic": True},
    }
    ledger.prepare(root, request)
    with pytest.raises(ValueError, match="conflict"):
        ledger.prepare(root, {**request, "source_sha256": "b" * 64})
    auth = f.authorization([request["action_key"]])
    with ledger.open_ledger(root, auth, now=lambda: f.NOW) as journal:
        journal.intent(request["action_key"])
        journal.reserve(request["action_key"], "gmail.send", {"raw_sha256": "c" * 64})
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert ledger.status(moved, request["action_key"])["status"] == "unknown"
    with ledger.open_ledger(moved, auth, now=lambda: f.NOW) as journal:
        with pytest.raises(ValueError, match="already"):
            journal.reserve(
                request["action_key"], "gmail.send", {"raw_sha256": "c" * 64}
            )


def test_budget_and_scope_are_explicit_and_not_refunded(tmp_path):
    root = tmp_path / "instance"
    storage.initialize(root)
    auth = f.authorization(["action"], limits={"gmail.get": 1})
    with ledger.open_ledger(root, auth, now=lambda: f.NOW) as journal:
        journal.reserve("action", "gmail.get", {"id": "abc123"})
        with pytest.raises(ValueError, match="scope"):
            journal.reserve("other", "gmail.get", {})
    with ledger.open_ledger(root, auth, now=lambda: f.NOW) as journal:
        with pytest.raises(ValueError, match="budget"):
            journal.reserve("action", "gmail.get", {})
    with pytest.raises(ValueError, match="time"):
        with ledger.open_ledger(root, auth, now=lambda: "2026-08-10T02:00:00Z"):
            pass


def test_transport_observes_committed_intent_budget_and_private_captures(tmp_path):
    import json
    import sqlite3

    from skills._shared.fit_weekly import gmail_auth, gmail_rest

    root, action = f.prepared_sync(tmp_path)
    token = f.token(tmp_path)
    session, refresh = f.Gmail(), f.Refresh()
    observations = []
    grant = f.authorization(
        [action],
        limits={
            "gmail.profile": 1,
            "gmail.refresh": 1,
            "gmail.send": 1,
            "gmail.get": 1,
        },
    )

    def observed(tool, arguments=None):
        with sqlite3.connect(
            f"file:{root / 'trainlab-fit.db'}?mode=ro", uri=True
        ) as db:
            db.execute("PRAGMA query_only=ON")
            rows = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT content_json FROM documents WHERE kind='delivery_receipt'"
                )
            ]
            calls = [
                r
                for r in rows
                if r.get("schema_version") == "fit_delivery_call_v1"
                and r["tool"] == tool
            ]
            assert calls
            if tool == "gmail.send":
                request = ledger.request(db, action)
                assert ledger.document(db, ledger.key(action, "intent"))[
                    "request_sha256"
                ] == ledger.sha(request)
                write = ledger.document(db, ledger.key(action, "write"))
                assert (
                    write["arguments"]
                    == arguments
                    == {"raw": request["payload"]["raw"]}
                )
            observations.append(tool)

    rest_request, refresh_request = session.request, refresh.request

    def send(method, url, **kwargs):
        suffix = url.rsplit("/", 1)[-1]
        tool = {
            "profile": "gmail.profile",
            "send": "gmail.send",
            "abc123": "gmail.get",
        }[suffix]
        observed(tool, kwargs.get("json"))
        assert method == ("POST" if tool == "gmail.send" else "GET")
        assert (
            url
            == gmail_rest.BASE
            + {
                "gmail.profile": "/profile",
                "gmail.send": "/messages/send",
                "gmail.get": "/messages/abc123",
            }[tool]
        )
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] > 0
        return rest_request(method, url, **kwargs)

    def renew(method, url, **kwargs):
        observed("gmail.refresh")
        assert url == gmail_auth.TOKEN_URI
        return refresh_request(method, url, **kwargs)

    session.request, refresh.request = send, renew
    result = gmail_rest.deliver(
        root,
        action,
        gmail_rest.Client(
            gmail_auth.Auth(token, f.Auth.account, session=refresh), session
        ),
        grant,
        now=lambda: f.NOW,
    )
    assert result["status"] == "success"
    assert observations == ["gmail.refresh", "gmail.profile", "gmail.send", "gmail.get"]
    for path in root.rglob("*"):
        assert path.stat().st_mode & 0o077 == 0
        if path.is_file():
            data = path.read_bytes()
            for secret in (
                b"synthetic-old-access",
                b"synthetic-refreshed-access",
                b"synthetic-secret-only",
                b"synthetic-client-only",
                b"synthetic-refresh-only",
                b"Authorization",
                b"Bearer ",
            ):
                assert secret not in data
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        for tool in grant.max_calls:
            with pytest.raises(ValueError, match="budget"):
                journal.reserve(action, tool, {})


@pytest.mark.parametrize("boundary", ["intent", "write", "profile_call"])
def test_failed_durable_commit_never_enters_write_transport(
    tmp_path, monkeypatch, boundary
):
    from skills._shared.fit_weekly import gmail_rest, sync_calendar

    root, action = f.prepared_sync(tmp_path)
    session = f.Gmail()
    original = sync_calendar.durable
    failures = []

    def fail_commit(db):
        selected = (
            ledger.document(db, ledger.key(action, boundary))
            if boundary != "profile_call"
            else None
        )
        if boundary == "profile_call":
            selected = db.execute(
                "SELECT 1 FROM documents WHERE kind='delivery_receipt' AND content_json LIKE '%\"tool\":\"gmail.profile\"%'"
            ).fetchone()
        if selected:
            failures.append(1)
            raise OSError("synthetic finite commit failure")
        return original(db)

    monkeypatch.setattr(sync_calendar, "durable", fail_commit)
    grant = f.authorization([action])
    result = gmail_rest.deliver(
        root, action, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
    )
    assert result["status"] != "success" and failures
    assert all(not url.endswith("/send") for _, url, _ in session.calls)
    if boundary == "profile_call":
        assert session.calls == []


def test_transport_budget_exhaustion_survives_restart_and_move(tmp_path):
    from skills._shared.fit_weekly import gmail_rest

    root, action = f.prepared_sync(tmp_path)
    session = f.Gmail()
    session.fail = "/messages/abc123"
    grant = f.authorization(
        [action], limits={"gmail.profile": 2, "gmail.send": 1, "gmail.get": 1}
    )
    assert (
        gmail_rest.deliver(
            root, action, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
        )["status"]
        == "unknown"
    )
    moved = root.with_name("moved")
    root.rename(moved)
    session.fail = None
    assert (
        gmail_rest.reconcile(
            moved,
            action,
            gmail_rest.Client(f.Auth(), session),
            grant,
            now=lambda: f.NOW,
        )["status"]
        == "unknown"
    )
    calls = list(session.calls)
    assert (
        gmail_rest.reconcile(
            moved,
            action,
            gmail_rest.Client(f.Auth(), session),
            grant,
            now=lambda: f.NOW,
        )["status"]
        == "unknown"
    )
    assert session.calls == calls
    assert sum(url.endswith("/send") for _, url, _ in calls) == 1
    assert sum(url.endswith("/messages/abc123") for _, url, _ in calls) == 1
    assert sum(url.endswith("/profile") for _, url, _ in calls) == 2


@pytest.mark.parametrize(
    "damage",
    [
        "empty_actions",
        "reversed_dates",
        "expired",
        "reversed_time",
        "tool",
        "count",
        "action",
        "date",
    ],
)
def test_invalid_authorization_stops_before_transport(tmp_path, damage):
    from dataclasses import replace
    from typing import Any

    from skills._shared.fit_weekly import gmail_rest

    root, action = f.prepared_sync(tmp_path)
    grant = f.authorization([action])
    cases: dict[str, dict[str, Any]] = {
        "empty_actions": {"action_keys": ()},
        "reversed_dates": {"start_date": "2026-09-01"},
        "expired": {"starts_utc": "2026-08-09T00:00:00Z", "expires_utc": f.NOW},
        "reversed_time": {"starts_utc": "2026-08-11T00:00:00Z"},
        "tool": {"max_calls": {"unknown": 1}},
        "count": {"max_calls": {"gmail.profile": 0}},
        "action": {"action_keys": ("other",)},
        "date": {"end_date": "2026-08-09"},
    }
    grant = replace(grant, **cases[damage])
    session = f.Gmail()
    if damage in ("action", "date"):
        assert (
            gmail_rest.deliver(
                root,
                action,
                gmail_rest.Client(f.Auth(), session),
                grant,
                now=lambda: f.NOW,
            )["status"]
            == "prepared"
        )
    else:
        with pytest.raises(ValueError):
            gmail_rest.deliver(
                root,
                action,
                gmail_rest.Client(f.Auth(), session),
                grant,
                now=lambda: f.NOW,
            )
    assert session.calls == []
