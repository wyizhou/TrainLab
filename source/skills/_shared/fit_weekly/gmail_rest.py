"""Official Gmail REST one-send publication and read-only reconciliation."""

from __future__ import annotations

import re
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import gmail_message, publication, storage
from skills._shared.fit_weekly import publication_ledger as ledger

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def gmail_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{1,64}", value):
        raise ValueError("gmail_id_invalid")
    return value


class DeadlineExceeded(BaseException):
    """Cannot be swallowed by a requests transport retry/error wrapper."""


@contextmanager
def deadline(seconds: float) -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread() or signal.getitimer(
        signal.ITIMER_REAL
    ) != (0.0, 0.0):
        raise ValueError("gmail_deadline_environment_unavailable")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum: int, frame: Any) -> None:
        raise DeadlineExceeded()

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Client:
    def __init__(self, auth: Any, session: Any = None):
        self.auth = auth
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def call(
        self, journal: ledger.Journal, action: str, tool: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        journal.check(action)
        call_key = journal.reserve(action, tool, arguments)
        method, path = "GET", "/profile"
        kwargs: dict[str, Any] = {}
        if tool == "gmail.send":
            method, path = "POST", "/messages/send"
            kwargs["json"] = arguments
        elif tool == "gmail.get":
            path = "/messages/" + gmail_id(arguments["id"])
            kwargs["params"] = {"format": "raw"}
        elif tool == "gmail.list":
            path = "/messages"
            kwargs["params"] = arguments
        elif tool == "gmail.labels.list":
            path = "/labels"
        elif tool == "gmail.labels.create":
            if arguments != {"name": "TrainLab"}:
                raise ValueError("gmail_label_arguments_invalid")
            method, path = "POST", "/labels"
            kwargs["json"] = arguments
        elif tool == "gmail.modify":
            from skills._shared.fit_weekly.gmail_labels import label_id

            if (
                set(arguments) != {"id", "addLabelIds"}
                or len(arguments["addLabelIds"]) != 1
            ):
                raise ValueError("gmail_label_arguments_invalid")
            label_id(arguments["addLabelIds"][0])
            method, path = "POST", "/messages/" + gmail_id(arguments["id"]) + "/modify"
            kwargs["json"] = {"addLabelIds": arguments["addLabelIds"]}
        elif tool != "gmail.profile":
            raise ValueError("gmail_tool_invalid")
        try:
            with deadline(journal.remaining()):
                headers = self.auth.headers(
                    timeout=journal.remaining(),
                    before_refresh=lambda: journal.reserve(
                        action,
                        "gmail.refresh",
                        {"endpoint": "https://oauth2.googleapis.com/token"},
                    ),
                )
                journal.remaining()
                response = self.session.request(
                    method,
                    BASE + path,
                    headers=headers,
                    timeout=journal.remaining(),
                    allow_redirects=False,
                    **kwargs,
                )
                value = response.json()
            if response.status_code == 401:
                raise ValueError("gmail_reauthorization_required")
            if response.status_code != 200 or not isinstance(value, dict):
                raise ValueError("response")
            # Never capture arbitrary Provider error bodies or authentication.
            if tool == "gmail.send":
                value = {"id": gmail_id(value.get("id"))}
                journal.capture(call_key, value)
            journal.remaining()
            return call_key, value
        except (Exception, DeadlineExceeded) as exc:
            if str(exc) == "gmail_reauthorization_required" or getattr(
                self.auth, "_reauthorization_required", False
            ):
                raise ValueError("gmail_reauthorization_required") from None
            raise ValueError("gmail_request_failed") from None


def process(
    root: Path,
    action: str,
    client: Client,
    authorization: ledger.Authorization,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    existing = ledger.status(root, action)
    if existing["status"] == "success":
        return existing
    req = publication.validate_source(root, action)
    if req["kind"] != "gmail" or client.auth.account != req["payload"]["sender"]:
        raise ValueError("gmail_account_binding_invalid")
    if req["schema_version"] == "fit_delivery_request_v2" and not readonly:
        client.auth.require_labels()
    expected = req["payload"]
    with ledger.open_ledger(root, authorization, now=now) as journal:
        try:
            if readonly and ledger.state(journal.db, action)["status"] == "prepared":
                return ledger.state(journal.db, action)
            _, profile = client.call(journal, action, "gmail.profile", {})
            if gmail_message.address(profile.get("emailAddress")) != expected["sender"]:
                raise ValueError("gmail_account_mismatch")
            captures = journal.captures(action, "gmail.send")
            ids = {gmail_id(c["id"]) for c in captures}
            intent = ledger.document(journal.db, ledger.key(action, "intent"))
            if intent is None and not readonly:
                journal.intent(action)
                _, sent = client.call(
                    journal, action, "gmail.send", {"raw": expected["raw"]}
                )
                ids = {sent["id"]}
            elif not ids:
                _, listed = client.call(
                    journal,
                    action,
                    "gmail.list",
                    {
                        "q": "rfc822msgid:" + expected["message_id"],
                        "includeSpamTrash": True,
                    },
                )
                matches = listed.get("messages", [])
                if (
                    listed.get("nextPageToken")
                    or not isinstance(matches, list)
                    or len(matches) != 1
                ):
                    raise ValueError("gmail_query_ambiguous")
                ids = {gmail_id(matches[0].get("id"))}
            if len(ids) != 1:
                raise ValueError("gmail_identity_ambiguous")
            ident = ids.pop()
            call_key, raw_result = client.call(
                journal, action, "gmail.get", {"id": ident}
            )
            if gmail_id(raw_result.get("id")) != ident:
                raise ValueError("gmail_response_identity_invalid")
            raw = gmail_message.decode(raw_result.get("raw"))
            actual_id = gmail_message.verify(raw, expected)
            evidence = {
                "gmail_id": ident,
                "message_id": actual_id,
                "raw_sha256": storage.digest(raw),
                "pdf_sha256": expected["pdf_sha256"],
            }
            journal.capture(call_key, evidence)
            return journal.success(action, evidence)
        except Exception as exc:
            state = ledger.state(journal.db, action)
            if str(exc) == "gmail_reauthorization_required":
                return {**state, "error_code": "gmail_reauthorization_required"}
            return state


def deliver(
    root: Path,
    action: str,
    client: Client,
    authorization: ledger.Authorization,
    *,
    now: Callable[[], str] = ledger.utc_now,
) -> dict[str, Any]:
    return process(root, action, client, authorization, readonly=False, now=now)


def reconcile(
    root: Path,
    action: str,
    client: Client,
    authorization: ledger.Authorization,
    *,
    now: Callable[[], str] = ledger.utc_now,
) -> dict[str, Any]:
    return process(root, action, client, authorization, readonly=True, now=now)
