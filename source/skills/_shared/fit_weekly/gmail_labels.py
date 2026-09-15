from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import gmail_message, storage
from skills._shared.fit_weekly import publication_ledger as ledger

NAME = "TrainLab"


def label_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"Label_[A-Za-z0-9_-]{1,128}", value) is None
    ):
        raise ValueError("gmail_label_id_invalid")
    return value


def ensure_key(account: str) -> str:
    return "gmail-label:" + storage.digest(gmail_message.address(account).encode())


def apply_key(action: str) -> str:
    return action + ":label"


def prepare(root: Path, mail: dict[str, Any]) -> tuple[str, str]:
    if mail["schema_version"] != "fit_delivery_request_v2" or mail["kind"] != "gmail":
        raise ValueError("gmail_label_mail_version_invalid")
    account = gmail_message.address(mail["payload"]["sender"])
    if account != mail["payload"]["recipient"]:
        raise ValueError("gmail_default_account_invalid")
    ensure = ensure_key(account)
    identity = {"account": account, "name": NAME}
    with storage.open_store(root) as db:
        old = ledger.document(db, ledger.key(ensure, "request"))
    if old is None:
        ledger.prepare(
            root,
            {
                "schema_version": "fit_delivery_request_v2",
                "action_key": ensure,
                "kind": "gmail_label_ensure",
                "source_key": ensure,
                "source_sha256": ledger.sha(identity),
                "date": mail["date"],
                "payload": identity,
            },
        )
    apply = apply_key(mail["action_key"])
    ledger.prepare(
        root,
        {
            "schema_version": "fit_delivery_request_v2",
            "action_key": apply,
            "kind": "gmail_label_apply",
            "source_key": mail["action_key"],
            "source_sha256": ledger.sha(mail),
            "date": mail["date"],
            "payload": {
                "mail_action": mail["action_key"],
                "label_action": ensure,
                "account": account,
            },
        },
    )
    return ensure, apply


def validate(root: Path, req: dict[str, Any]) -> dict[str, Any]:
    from skills._shared.fit_weekly import publication

    payload = req["payload"]
    if req["kind"] == "gmail_label_ensure":
        account = gmail_message.address(payload["account"])
        if (
            payload != {"account": account, "name": NAME}
            or req["action_key"] != ensure_key(account)
            or req["source_key"] != req["action_key"]
            or req["source_sha256"] != ledger.sha(payload)
        ):
            raise ValueError("gmail_label_source_invalid")
    else:
        mail = publication.validate_source(root, req["source_key"])
        account = mail["payload"]["sender"]
        if (
            mail["kind"] != "gmail"
            or mail["schema_version"] != "fit_delivery_request_v2"
            or req["action_key"] != apply_key(mail["action_key"])
            or req["source_sha256"] != ledger.sha(mail)
            or req["date"] != mail["date"]
            or payload
            != {
                "mail_action": mail["action_key"],
                "label_action": ensure_key(account),
                "account": account,
            }
        ):
            raise ValueError("gmail_label_source_invalid")
        with storage.open_store(root) as db:
            ensure = ledger.request(db, payload["label_action"])
        validate(root, ensure)
    return req


def listed(value: dict[str, Any]) -> str | None:
    labels = value.get("labels", [])
    if not isinstance(labels, list) or value.get("nextPageToken"):
        raise ValueError("gmail_label_list_invalid")
    matches = [
        item for item in labels if isinstance(item, dict) and item.get("name") == NAME
    ]
    if len(matches) > 1 or matches and matches[0].get("type") != "user":
        raise ValueError("gmail_label_ambiguous")
    return label_id(matches[0].get("id")) if matches else None


def process(
    root: Path,
    action: str,
    client: Any,
    authorization: ledger.Authorization,
    *,
    readonly: bool,
    now: Callable[[], str],
) -> dict[str, Any]:
    from skills._shared.fit_weekly import gmail_rest, publication

    req = publication.validate_source(root, action)
    if (
        req["kind"] not in ("gmail_label_ensure", "gmail_label_apply")
        or client.auth.account != req["payload"]["account"]
    ):
        raise ValueError("gmail_label_account_invalid")
    existing = ledger.status(root, action)
    if existing["status"] == "success" or readonly and existing["status"] == "prepared":
        return existing
    if not readonly:
        client.auth.require_labels()
    with ledger.open_ledger(root, authorization, now=now) as journal:
        try:
            _, profile = client.call(journal, action, "gmail.profile", {})
            if (
                gmail_message.address(profile.get("emailAddress"))
                != req["payload"]["account"]
            ):
                raise ValueError("gmail_account_mismatch")
            prepared = ledger.state(journal.db, action)["status"] == "prepared"
            if req["kind"] == "gmail_label_ensure":
                _, result = client.call(journal, action, "gmail.labels.list", {})
                ident = listed(result)
                if ident is None and prepared and not readonly:
                    journal.intent(action)
                    client.call(journal, action, "gmail.labels.create", {"name": NAME})
                    _, result = client.call(journal, action, "gmail.labels.list", {})
                    ident = listed(result)
                if ident is None:
                    return ledger.state(journal.db, action)
                return journal.success(
                    action,
                    {
                        "account": req["payload"]["account"],
                        "label_id": ident,
                        "name": NAME,
                    },
                )
            mail = ledger.request(journal.db, req["payload"]["mail_action"])
            sent = ledger.state(journal.db, mail["action_key"])
            ensured = ledger.state(journal.db, req["payload"]["label_action"])
            if (
                sent["status"] != "success"
                or ensured["status"] != "success"
                or ensured["evidence"]["account"] != req["payload"]["account"]
            ):
                return ledger.state(journal.db, action)
            ident = gmail_rest.gmail_id(sent["evidence"]["gmail_id"])
            label = label_id(ensured["evidence"]["label_id"])

            def observed() -> bool:
                _, message = client.call(journal, action, "gmail.get", {"id": ident})
                if gmail_rest.gmail_id(message.get("id")) != ident:
                    raise ValueError("gmail_label_message_invalid")
                actual = gmail_message.verify(
                    gmail_message.decode(message.get("raw")), mail["payload"]
                )
                if actual != sent["evidence"]["message_id"]:
                    raise ValueError("gmail_label_message_identity_invalid")
                labels = message.get("labelIds")
                if not isinstance(labels, list) or any(
                    not isinstance(v, str) for v in labels
                ):
                    raise ValueError("gmail_label_response_invalid")
                return label in labels

            present = observed()
            if not present and prepared and not readonly:
                journal.intent(action)
                client.call(
                    journal,
                    action,
                    "gmail.modify",
                    {"id": ident, "addLabelIds": [label]},
                )
                present = observed()
            if not present:
                return ledger.state(journal.db, action)
            return journal.success(
                action,
                {
                    "account": req["payload"]["account"],
                    "gmail_id": ident,
                    "label_id": label,
                    "mail_request_sha256": ledger.sha(mail),
                },
            )
        except Exception as exc:
            state = ledger.state(journal.db, action)
            if str(exc) == "gmail_reauthorization_required":
                return {**state, "error_code": "gmail_reauthorization_required"}
            return state
