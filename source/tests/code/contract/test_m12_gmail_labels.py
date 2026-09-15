from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    gmail_labels,
    gmail_scopes,
    run_authorization,
    run_reconcile,
    run_state,
    run_sync,
    storage,
)
from skills._shared.fit_weekly import publication_ledger as ledger

f = importlib.import_module("test_m12_sync_command")


def setup(tmp_path, monkeypatch):
    import requests

    root, config, grant, _ = f.setup(tmp_path, monkeypatch)
    batch = f.collect(config, grant, f.MCP(root))
    http = f.HTTP()
    monkeypatch.setattr(requests, "Session", lambda: http)
    return root, config, grant, batch, http


def readonly(grant):
    value = grant.value()
    value["key"] += "-readonly"
    value["sync"] = None
    value["publication"]["max_calls"] = {
        k: v
        for k, v in value["publication"]["max_calls"].items()
        if k not in ledger.WRITE_TOOLS
    }
    return run_authorization.parse(value, now=f.NOW)


@pytest.mark.parametrize("exists", [False, True])
def test_complete_label_and_send_are_three_independent_durable_actions(
    tmp_path, monkeypatch, exists
):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    if exists:
        http.labels = [{"id": "Label_synthetic", "name": "TrainLab", "type": "user"}]
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert (
        state["status"]
        == state["mail"]["status"]
        == state["label"]["status"]
        == "success"
    )
    assert sum(m == "POST" and u.endswith("/labels") for m, u in http.calls) == (
        0 if exists else 1
    )
    assert sum(u.endswith("/send") for m, u in http.calls) == 1
    assert sum(u.endswith("/modify") for m, u in http.calls) == 1
    with storage.open_store(root) as db:
        records = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT content_json FROM documents WHERE kind='delivery_receipt' AND logical_key LIKE '%:write'"
            )
        ]
        assert (
            len({r["action_key"] for r in records})
            == len(records)
            == (2 if exists else 3)
        )
        assert run_state.business(db) == {"pending": 0, "unknown": 0, "failed": 0}
    assert "schema_version" not in state
    assert state["mail"]["schema_version"] == "fit_delivery_result_v1"
    before = len(http.calls)
    assert run_sync.notify(config, grant, batch, now=lambda: f.NOW) == state
    assert len(http.calls) == before


@pytest.mark.parametrize(
    ("boundary", "accepted"),
    [
        ("create", True),
        ("create", False),
        ("modify", True),
        ("modify", False),
        ("send", True),
    ],
)
def test_lost_response_never_repeats_write_and_readonly_recovers(
    tmp_path, monkeypatch, boundary, accepted
):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    original = http.request
    suffix = {"create": "/labels", "modify": "/modify", "send": "/send"}[boundary]
    armed = True

    def lost(method, url, **kwargs):
        nonlocal armed
        if armed and method == "POST" and url.endswith(suffix):
            armed = False
            if accepted:
                original(method, url, **kwargs)
            else:
                http.calls.append((method, url))
            raise ConnectionError("synthetic lost response")
        return original(method, url, **kwargs)

    http.request = lost
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["status"] == "unknown"
    if boundary == "modify":
        assert state["mail"]["status"] == "success"
        assert ledger.status(root, state["action_key"])["status"] == "success"
    before = sum(m == "POST" for m, u in http.calls)
    actions = [
        a
        for a in grant.value()["publication"]["action_keys"]
        if ledger.status(root, a)["status"] == "unknown"
    ]
    result = asyncio.run(
        run_reconcile.external(config, readonly(grant), actions, now=lambda: f.NOW)
    )
    assert (
        result["status"] == ("pending" if boundary == "send" else "complete")
        if accepted
        else result["status"] == "unknown"
    )
    assert sum(m == "POST" for m, u in http.calls) == before
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["status"] == ("success" if accepted else "unknown")
    assert sum(m == "POST" and u.endswith(suffix) for m, u in http.calls) == 1


@pytest.mark.parametrize("tool", ["gmail.send", "gmail.modify", "gmail.labels.list"])
def test_missing_permission_means_zero_http(tmp_path, monkeypatch, tool):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    value = grant.value()
    value["key"] += "-missing"
    del value["publication"]["max_calls"][tool]
    with pytest.raises(ValueError):
        run_sync.notify(
            config, run_authorization.parse(value, now=f.NOW), batch, now=lambda: f.NOW
        )
    assert http.calls == []


@pytest.mark.parametrize(
    "scopes",
    [
        sorted(gmail_scopes.LEGACY_SCOPES),
        ["https://www.googleapis.com/auth/gmail.send"],
    ],
)
def test_old_scope_never_sends_new_labelled_mail(tmp_path, monkeypatch, scopes):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    path = Path(config.service("gmail")["token_file"])
    value = json.loads(path.read_text())
    value["scopes"] = scopes
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert http.calls == []


@pytest.mark.parametrize(
    "labels",
    [
        [{"id": "Label_synthetic", "name": "TrainLab", "type": "system"}],
        [{"id": "../other", "name": "TrainLab", "type": "user"}],
        [
            {"id": "Label_a", "name": "TrainLab", "type": "user"},
            {"id": "Label_b", "name": "TrainLab", "type": "user"},
        ],
    ],
)
def test_ambiguous_label_never_sends(tmp_path, monkeypatch, labels):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    http.labels = labels
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["status"] == "prepared"
    assert all(m != "POST" for m, u in http.calls)


def test_readonly_rejects_every_new_write_tool(tmp_path, monkeypatch):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    for tool in ("gmail.labels.create", "gmail.modify"):
        value = readonly(grant).value()
        value["publication"]["max_calls"][tool] = 1
        with pytest.raises(ValueError, match="readonly"):
            asyncio.run(
                run_reconcile.external(
                    config,
                    run_authorization.parse(value, now=f.NOW),
                    [run_sync.action_key(grant)],
                    now=lambda: f.NOW,
                )
            )


def test_arbitrary_message_source_is_rejected(tmp_path, monkeypatch):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    with storage.open_store(root) as db:
        req = ledger.request(db, gmail_labels.apply_key(state["action_key"]))
    req["payload"]["gmail_id"] = "deadbeef"
    with pytest.raises(ValueError, match="source_invalid"):
        gmail_labels.validate(root, req)


def test_exhausted_modify_budget_preserves_sent_and_pending_label(
    tmp_path, monkeypatch
):
    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    from skills._shared.fit_weekly import publication

    action = publication.prepare_sync_batch(
        root,
        batch["batch_key"],
        sender="owner@example.invalid",
        recipient="owner@example.invalid",
    )
    with storage.open_store(root) as db:
        req = ledger.request(db, action)
    gmail_labels.prepare(root, req)
    with ledger.open_ledger(
        root, grant.publication(now=f.NOW), now=lambda: f.NOW
    ) as journal:
        prefix = journal.auth_key + ":call:"
        ledger.put(
            journal.db,
            prefix + "1",
            {
                "schema_version": "fit_delivery_call_v1",
                "action_key": action,
                "tool": "gmail.modify",
                "arguments": {},
                "authorization_key": grant.key,
                "ordinal": 1,
            },
        )
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["mail"]["status"] == "success"
    assert "schema_version" not in state
    assert state["mail"]["schema_version"] == "fit_delivery_result_v1"
    assert state["status"] == "unknown"
    assert not any(u.endswith("/modify") for m, u in http.calls)
    assert sum(u.endswith("/send") for m, u in http.calls) == 1


def test_apply_binds_verified_actual_message_id(tmp_path, monkeypatch):
    import base64
    from email import policy
    from email.parser import BytesParser
    from types import SimpleNamespace

    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    original = http.request
    reads = 0

    def change(method, url, **kwargs):
        nonlocal reads
        response = original(method, url, **kwargs)
        if method == "GET" and url.endswith("/messages/abc123"):
            reads += 1
            if reads > 1:
                body = response.json()
                message = BytesParser(policy=policy.default).parsebytes(
                    base64.urlsafe_b64decode(body["raw"])
                )
                message.replace_header("Message-ID", "<different@example.invalid>")
                body["raw"] = base64.urlsafe_b64encode(
                    message.as_bytes(policy=policy.SMTP)
                ).decode()
                return SimpleNamespace(status_code=200, json=lambda: body)
        return response

    http.request = change
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["mail"]["status"] == "success"
    assert state["label"]["status"] == "prepared"
    assert state["status"] == "prepared"
    assert not any(u.endswith("/modify") for m, u in http.calls)


def test_revoked_account_returns_explicit_reauthorization_without_send(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    root, config, grant, batch, http = setup(tmp_path, monkeypatch)

    def revoked(method, url, **kwargs):
        http.calls.append((method, url))
        return SimpleNamespace(status_code=401, json=lambda: {})

    http.request = revoked
    state = run_sync.notify(config, grant, batch, now=lambda: f.NOW)
    assert state["ensure_label"]["error_code"] == "gmail_reauthorization_required"
    assert state["mail"]["status"] == "prepared"
    assert all(method == "GET" for method, url in http.calls)


@pytest.mark.parametrize("lost", [False, True])
def test_frozen_v1_mail_state_preserves_version_and_never_backfills_labels(
    tmp_path, monkeypatch, lost
):
    from skills._shared.fit_weekly import publication, run_publication

    root, config, grant, batch, http = setup(tmp_path, monkeypatch)
    action = publication.prepare_sync_batch(
        root,
        batch["batch_key"],
        sender="owner@example.invalid",
        recipient="owner@example.invalid",
        mail_version=1,
    )
    if lost:
        http.lost = True
    sent = run_publication.mail(
        config, action, grant, readonly=False, now=lambda: f.NOW
    )
    assert sent["status"] == ("unknown" if lost else "success")
    with storage.open_store(root) as db:
        request = ledger.request(db, action)
        before = db.execute(
            "SELECT logical_key,content_json FROM documents ORDER BY logical_key"
        ).fetchall()
    before_calls = list(http.calls)
    config.service_path("gmail").unlink()
    assert run_publication.mail_state(config, action) == sent
    with storage.open_store(root) as db:
        assert ledger.request(db, action) == request
        assert (
            db.execute(
                "SELECT logical_key,content_json FROM documents ORDER BY logical_key"
            ).fetchall()
            == before
        )
    assert request["schema_version"] == "fit_delivery_request_v1"
    assert http.calls == before_calls
    assert not any("/labels" in url or "/modify" in url for _, url in http.calls)
