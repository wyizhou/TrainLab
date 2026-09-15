"""Official REST fake-session tests; no real account or credentials."""

import importlib
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import gmail_rest
from skills._shared.fit_weekly import publication_ledger as ledger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_publication_factory")


def test_weekly_actual_identity_attachment_and_success_replay(tmp_path, monkeypatch):
    root, prepared, models = f.prepared(tmp_path, monkeypatch)
    key = prepared["mail"]
    session = f.Gmail()
    client = gmail_rest.Client(f.Auth(), session)
    grant = f.authorization([key])
    result = gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)
    assert result["status"] == "success"
    assert result["evidence"]["message_id"] == "<rewritten@example.invalid>"
    assert result["evidence"]["pdf_sha256"] == prepared["seal"]["pdf_sha256"]
    calls = len(session.calls)
    assert gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW) == result
    assert len(session.calls) == calls
    assert [m.calls for m in models] == [1, 1]
    assert (
        b"synthetic-token-not-for-persistence"
        not in (root / "trainlab-fit.db").read_bytes()
    )


def test_send_capture_recovers_raw_without_resend(tmp_path, monkeypatch):
    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    key = prepared["mail"]
    session = f.Gmail()
    session.fail = "/messages/abc123"
    client = gmail_rest.Client(f.Auth(), session)
    grant = f.authorization([key])
    assert (
        gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "unknown"
    )
    session.fail = None
    assert (
        gmail_rest.reconcile(root, key, client, grant, now=lambda: f.NOW)["status"]
        == "success"
    )
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


@pytest.mark.parametrize("damage", ["recipient", "body", "attachment", "duplicate"])
def test_changed_raw_never_succeeds(tmp_path, monkeypatch, damage):
    from email import policy
    from email.parser import BytesParser
    from typing import Any, cast

    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    key = prepared["mail"]
    session = f.Gmail()

    def change(raw):
        mail = BytesParser(policy=policy.default).parsebytes(raw)
        if damage == "recipient":
            mail["Cc"] = "extra@example.invalid"
        elif damage == "body":
            cast(Any, mail.get_payload())[0].set_content("changed")
        elif damage == "attachment":
            cast(Any, mail.get_payload())[1].set_payload("Y2hhbmdlZA==")
        else:
            raw = b"Subject: duplicate\r\n" + raw
            return raw
        return mail.as_bytes(policy=policy.SMTP)

    session.change = change
    result = gmail_rest.deliver(
        root,
        key,
        gmail_rest.Client(f.Auth(), session),
        f.authorization([key]),
        now=lambda: f.NOW,
    )
    assert result["status"] == "unknown"
    assert ledger.status(root, key)["status"] == "unknown"


def test_auth_refresh_is_atomic_private_and_failure_keeps_previous(
    tmp_path, monkeypatch
):
    import json
    from types import SimpleNamespace

    from skills._shared.fit_weekly import gmail_auth

    directory = tmp_path / "auth"
    directory.mkdir(mode=0o700)
    path = directory / "token.json"
    previous = {
        "token": "synthetic-expired",
        "expiry": "2020-01-01T00:00:00Z",
        "refresh_token": "synthetic-refresh",
        "client_id": "synthetic-client",
        "client_secret": "synthetic-secret",
        "token_uri": gmail_auth.TOKEN_URI,
        "scopes": sorted(gmail_auth.SCOPES),
    }
    old_bytes = json.dumps(previous).encode()
    path.write_bytes(old_bytes)
    path.chmod(0o600)
    requests = []

    class Session:
        def request(self, method, url, **kwargs):
            requests.append((method, url))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "access_token": "synthetic-new",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

    auth = gmail_auth.Auth(path, "owner@example.invalid", session=Session())
    reserved = []
    assert (
        auth.headers(before_refresh=lambda: reserved.append(1))["Authorization"]
        == "Bearer synthetic-new"
    )
    assert len(requests) == len(reserved) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_bytes(old_bytes)
    auth = gmail_auth.Auth(path, "owner@example.invalid", session=Session())

    def failure(*args):
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(gmail_auth.os, "fsync", failure)
    with pytest.raises(ValueError, match="auth_or_refresh"):
        auth.headers(before_refresh=lambda: reserved.append(1))
    assert path.read_bytes() == old_bytes


@pytest.mark.parametrize("case", ["zero", "duplicate", "pagination"])
def test_unknown_query_ambiguity_does_not_authorize_resend(tmp_path, monkeypatch, case):
    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    key = prepared["mail"]
    session = f.Gmail()
    grant = f.authorization([key])
    with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
        journal.intent(key)
    if case != "zero":
        from skills._shared.fit_weekly import gmail_message

        with ledger.open_ledger(root, grant, now=lambda: f.NOW) as journal:
            raw = gmail_message.decode(
                ledger.request(journal.db, key)["payload"]["raw"]
            )
        session.sent["abc123"] = raw
        if case == "duplicate":
            session.sent["abc456"] = raw
        else:
            session.page = True
    assert (
        gmail_rest.reconcile(
            root, key, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
        )["status"]
        == "unknown"
    )
    assert all(not url.endswith("/send") for _, url, _ in session.calls)


def test_http_whole_call_deadline_interrupts_blocking_transport():
    import time

    started = time.monotonic()
    with pytest.raises(gmail_rest.DeadlineExceeded):
        with gmail_rest.deadline(0.05):
            time.sleep(1)
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    "failure", [gmail_rest.DeadlineExceeded, KeyboardInterrupt, OSError]
)
def test_refresh_interruption_restores_complete_token_and_stops_business(
    tmp_path, monkeypatch, failure
):
    from skills._shared.fit_weekly import gmail_auth, storage

    root, key = f.prepared_sync(tmp_path)
    path = f.token(tmp_path)
    previous = path.read_bytes()
    session = f.Gmail()
    refresh = f.Refresh()
    auth = gmail_auth.Auth(path, f.Auth.account, session=refresh)
    sync_dir = storage.sync_dir
    attempts = []

    def interrupted(directory):
        if directory == path.parent:
            attempts.append(directory)
            if len(attempts) == 1:
                raise failure()
        return sync_dir(directory)

    monkeypatch.setattr(storage, "sync_dir", interrupted)
    client = gmail_rest.Client(auth, session)
    grant = f.authorization([key])
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)
    else:
        assert (
            gmail_rest.deliver(root, key, client, grant, now=lambda: f.NOW)["status"]
            == "prepared"
        )
    assert path.read_bytes() == previous
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(attempts) == 2
    assert list(path.parent.iterdir()) == [path]
    assert session.calls == []
    assert len(refresh.calls) == 1
    with pytest.raises(ValueError, match="gmail_auth_failed"):
        auth.headers(before_refresh=lambda: pytest.fail("failed auth reused"))
    assert session.calls == []


@pytest.mark.parametrize(
    "case",
    [
        "scope",
        "extra_scope",
        "endpoint",
        "missing_refresh",
        "file_mode",
        "directory_mode",
        "file_link",
        "directory_link",
        "invalid_json",
        "account_binding",
        "profile_account",
        "profile_http",
    ],
)
def test_new_auth_preflight_rejects_invalid_identity_or_private_token(tmp_path, case):
    import json
    from types import SimpleNamespace

    from skills._shared.fit_weekly import gmail_auth

    root, key = f.prepared_sync(tmp_path)
    path = f.token(tmp_path, expiry="2099-01-01T00:00:00Z")
    value = json.loads(path.read_text())
    if case == "scope":
        value["scopes"] = ["https://www.googleapis.com/auth/gmail.send"]
    elif case == "extra_scope":
        value["scopes"].append("https://www.googleapis.com/auth/drive")
    elif case == "endpoint":
        value["token_uri"] = "https://example.invalid/token"
    elif case == "missing_refresh":
        del value["refresh_token"]
    path.write_text(json.dumps(value))
    if case == "file_mode":
        path.chmod(0o644)
    elif case == "directory_mode":
        path.parent.chmod(0o755)
    elif case == "file_link":
        original = path.with_name("original.json")
        path.rename(original)
        path.symlink_to(original)
    elif case == "directory_link":
        link = tmp_path / "auth-link"
        link.symlink_to(path.parent, target_is_directory=True)
        path = link / path.name
    elif case == "invalid_json":
        path.write_text("not json")
    session = f.Gmail()
    refresh = f.Refresh()
    if case in ("profile_account", "profile_http"):

        def bad_profile(method, url, **kwargs):
            session.calls.append((method, url, {}))
            return SimpleNamespace(
                status_code=401 if case == "profile_http" else 200,
                json=lambda: {"emailAddress": "other@example.invalid"},
            )

        session.request = bad_profile
    if case.startswith("profile"):
        auth = gmail_auth.Auth(path, f.Auth.account, session=refresh)
        assert (
            gmail_rest.deliver(
                root,
                key,
                gmail_rest.Client(auth, session),
                f.authorization([key]),
                now=lambda: f.NOW,
            )["status"]
            == "prepared"
        )
    else:
        with pytest.raises(ValueError):
            auth = gmail_auth.Auth(
                path,
                "other@example.invalid"
                if case == "account_binding"
                else f.Auth.account,
                session=refresh,
            )
            gmail_rest.deliver(
                root,
                key,
                gmail_rest.Client(auth, session),
                f.authorization([key]),
                now=lambda: f.NOW,
            )
    assert all(not url.endswith("/send") for _, url, _ in session.calls)
    assert refresh.calls == []


@pytest.mark.parametrize(
    "case", ["http", "scope", "expiry", "type", "missing_access", "redirect"]
)
def test_new_refresh_failure_preserves_token_without_business_request(tmp_path, case):
    from skills._shared.fit_weekly import gmail_auth

    root, key = f.prepared_sync(tmp_path)
    path = f.token(tmp_path)
    previous = path.read_bytes()
    refresh = f.Refresh()
    if case in ("http", "redirect"):
        refresh.status = 401 if case == "http" else 302
    elif case == "scope":
        refresh.value["scope"] = "https://www.googleapis.com/auth/gmail.send"
    elif case == "expiry":
        refresh.value["expires_in"] = -1
    elif case == "type":
        refresh.value["token_type"] = "other"
    else:
        del refresh.value["access_token"]
    session = f.Gmail()
    auth = gmail_auth.Auth(path, f.Auth.account, session=refresh)
    assert (
        gmail_rest.deliver(
            root,
            key,
            gmail_rest.Client(auth, session),
            f.authorization([key]),
            now=lambda: f.NOW,
        )["status"]
        == "prepared"
    )
    assert path.read_bytes() == previous and session.calls == []
    assert len(refresh.calls) == 1
    method, url, kwargs = refresh.calls[0]
    assert method == "POST" and url == gmail_auth.TOKEN_URI
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] > 0


@pytest.mark.parametrize("with_pdf", [False, True])
@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_to",
        "duplicate_from",
        "duplicate_subject",
        "duplicate_message_id",
        "extra_to",
        "wrong_from",
        "wrong_subject",
        "invalid_message_id",
        "missing_message_id",
        "bcc",
        "resent",
        "body",
        "extra_html",
        "nested",
        "duplicate_content_type",
        "duplicate_encoding",
        "attachment_name",
        "attachment_bytes",
    ],
)
def test_new_raw_rejects_ambiguous_headers_content_and_parts(with_pdf, damage):
    from email import policy
    from email.message import EmailMessage
    from email.parser import BytesParser
    from typing import Any, cast

    from skills._shared.fit_weekly import gmail_message

    expected = gmail_message.build(
        "sync:public:gmail",
        f.Auth.account,
        "runner@example.invalid",
        "中文主题",
        "中文正文",
        b"%PDF-public" if with_pdf else None,
    )
    raw = gmail_message.decode(expected["raw"])
    mail = BytesParser(policy=policy.default).parsebytes(raw)
    if damage.startswith("duplicate_"):
        header = {
            "duplicate_to": "To: runner@example.invalid",
            "duplicate_from": "From: owner@example.invalid",
            "duplicate_subject": "Subject: other",
            "duplicate_message_id": "Message-ID: <other@example.invalid>",
            "duplicate_content_type": "Content-Type: text/plain",
            "duplicate_encoding": "Content-Transfer-Encoding: base64",
        }[damage]
        # The root of a PDF message normally has no transfer encoding.
        if damage == "duplicate_encoding" and with_pdf:
            mail["Content-Transfer-Encoding"] = "7bit"
        raw = (header + "\r\n").encode() + mail.as_bytes(policy=policy.SMTP)
    else:
        if damage == "extra_to":
            mail.replace_header("To", "runner@example.invalid, extra@example.invalid")
        elif damage == "wrong_from":
            mail.replace_header("From", "other@example.invalid")
        elif damage == "wrong_subject":
            mail.replace_header("Subject", "不同主题")
        elif damage == "invalid_message_id":
            mail.replace_header("Message-ID", "not-an-id")
        elif damage == "missing_message_id":
            del mail["Message-ID"]
        elif damage == "bcc":
            mail["Bcc"] = "extra@example.invalid"
        elif damage == "resent":
            mail["Resent-To"] = "extra@example.invalid"
        elif damage in ("extra_html", "nested"):
            extra = EmailMessage()
            extra.set_content("extra", subtype="html")
            if damage == "nested":
                extra.make_alternative()
            if not mail.is_multipart():
                mail.make_mixed()
            mail.attach(extra)
        elif damage in ("attachment_name", "attachment_bytes"):
            if with_pdf:
                attachment = cast(Any, mail.get_payload())[1]
                if damage == "attachment_name":
                    attachment.replace_header(
                        "Content-Disposition", 'attachment; filename="other.pdf"'
                    )
                else:
                    attachment.set_payload("Y2hhbmdlZA==")
            else:
                mail.add_attachment(
                    b"unexpected",
                    maintype="application",
                    subtype="pdf",
                    filename="report.pdf",
                )
        else:
            plain = cast(Any, mail.get_payload())[0] if with_pdf else mail
            plain.set_content("different body")
        raw = mail.as_bytes(policy=policy.SMTP)
    with pytest.raises(ValueError, match="gmail_raw_mismatch"):
        gmail_message.verify(raw, expected)


@pytest.mark.parametrize("with_pdf", [False, True])
def test_new_mime_identity_is_directory_independent_and_accepts_service_reencoding(
    tmp_path, monkeypatch, with_pdf
):
    from email import policy
    from email.parser import BytesParser
    from typing import Any, cast

    from skills._shared.fit_weekly import gmail_message

    def build():
        return gmail_message.build(
            "sync:public:gmail",
            f.Auth.account,
            "runner@example.invalid",
            "中文主题",
            "中文正文\nsecond line",
            b"%PDF-public" if with_pdf else None,
        )

    expected = build()
    monkeypatch.chdir(tmp_path)
    assert build() == expected
    mail = BytesParser(policy=policy.default).parsebytes(
        gmail_message.decode(expected["raw"])
    )
    mail.replace_header("Message-ID", "<service-assigned@example.invalid>")
    plain = cast(Any, mail.get_payload())[0] if with_pdf else mail
    plain.set_content(expected["body"], charset="utf-8", cte="base64")
    assert (
        gmail_message.verify(mail.as_bytes(policy=policy.SMTP), expected)
        == "<service-assigned@example.invalid>"
    )


@pytest.mark.parametrize("recoverable", [False, True])
def test_lost_send_response_only_queries_unique_original_id_without_resend(
    tmp_path, recoverable
):
    from skills._shared.fit_weekly import gmail_message, storage

    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    session.rewrite = False
    original = session.request
    queries = []

    def lost(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if url.endswith("/send"):
            if not recoverable:
                session.sent.clear()
            raise OSError("synthetic response lost after accepted write")
        if url.endswith("/messages"):
            queries.append(kwargs["params"]["q"])
        return response

    session.request = lost
    grant = f.authorization([key])
    assert (
        gmail_rest.deliver(
            root, key, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
        )["status"]
        == "unknown"
    )
    moved = root.with_name("moved-instance")
    root.rename(moved)
    result = gmail_rest.reconcile(
        moved, key, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
    )
    assert result["status"] == ("success" if recoverable else "unknown")
    with storage.open_store(moved) as db:
        expected = ledger.request(db, key)["payload"]
    assert queries == ["rfc822msgid:" + expected["message_id"]]
    if recoverable:
        assert result["evidence"]["message_id"] == gmail_message.verify(
            session.sent["abc123"], expected
        )
    gmail_rest.deliver(
        moved, key, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
    )
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1


@pytest.mark.parametrize("status", [401, 500])
def test_read_http_failure_remains_unknown_and_never_resends(tmp_path, status):
    from types import SimpleNamespace

    root, key = f.prepared_sync(tmp_path)
    session = f.Gmail()
    original = session.request

    def failure(method, url, **kwargs):
        result = original(method, url, **kwargs)
        if url.endswith("/messages/abc123"):
            return SimpleNamespace(
                status_code=status, json=lambda: {"error": "synthetic-private-error"}
            )
        return result

    session.request = failure
    grant = f.authorization([key])
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
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1
    assert b"synthetic-private-error" not in (root / "trainlab-fit.db").read_bytes()


@pytest.mark.parametrize("point", ["before_replace", "after_replace"])
def test_refresh_interrupt_at_replace_boundary_preserves_old_token(
    tmp_path, monkeypatch, point
):
    from skills._shared.fit_weekly import gmail_auth

    path = f.token(tmp_path)
    previous = path.read_bytes()
    replace = gmail_auth.os.replace
    calls = []

    def interrupted(source, destination):
        calls.append((source, destination))
        if len(calls) == 1 and point == "before_replace":
            raise gmail_rest.DeadlineExceeded()
        replace(source, destination)
        if len(calls) == 1:
            raise gmail_rest.DeadlineExceeded()

    monkeypatch.setattr(gmail_auth.os, "replace", interrupted)
    with pytest.raises(gmail_rest.DeadlineExceeded):
        gmail_auth.replace_token(path, b'{"public": "replacement"}')
    assert path.read_bytes() == previous
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "identifier", ["../abc", "/tmp/abc", "abc?format=full", "", None]
)
def test_new_provider_id_cannot_select_arbitrary_path(identifier):
    with pytest.raises(ValueError, match="gmail_id_invalid"):
        gmail_rest.gmail_id(identifier)


def test_saved_send_id_recovery_does_not_depend_on_original_message_id_query(tmp_path):
    root, action = f.prepared_sync(tmp_path)
    session = f.Gmail()
    session.fail = "/messages/abc123"
    grant = f.authorization([action])
    assert (
        gmail_rest.deliver(
            root, action, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
        )["status"]
        == "unknown"
    )
    session.fail = None
    result = gmail_rest.reconcile(
        root, action, gmail_rest.Client(f.Auth(), session), grant, now=lambda: f.NOW
    )
    assert result["status"] == "success"
    assert result["evidence"]["message_id"] == "<rewritten@example.invalid>"
    assert all(not url.endswith("/messages") for _, url, _ in session.calls)
    assert sum(url.endswith("/send") for _, url, _ in session.calls) == 1
