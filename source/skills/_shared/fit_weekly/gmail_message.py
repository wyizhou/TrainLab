"""Simple UTF-8 mail and strict actual-message identity/content verification."""

from __future__ import annotations

import base64
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from typing import Any

from skills._shared.fit_weekly import storage


def address(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", value
    ):
        raise ValueError("gmail_address_invalid")
    return value.casefold()


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode()


def decode(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", value):
        raise ValueError("gmail_base64_invalid")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except ValueError:
        raise ValueError("gmail_base64_invalid") from None


def build(
    action: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    pdf: bytes | None = None,
) -> dict[str, Any]:
    sender, recipient = address(sender), address(recipient)
    if not subject or any(c in subject for c in "\r\n") or not body:
        raise ValueError("gmail_message_invalid")
    message_id = "<trainlab-" + storage.digest(action.encode()) + "@trainlab.local>"
    mail = EmailMessage(policy=policy.SMTP)
    mail["From"], mail["To"], mail["Subject"], mail["Message-ID"] = (
        sender,
        recipient,
        subject,
        message_id,
    )
    mail.set_content(body, charset="utf-8")
    if pdf is not None:
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("gmail_pdf_invalid")
        mail.add_attachment(
            pdf, maintype="application", subtype="pdf", filename="report.pdf"
        )
        mail.set_boundary("trainlab-" + storage.digest(action.encode())[:40])
    return {
        "sender": sender,
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "message_id": message_id,
        "pdf_sha256": storage.digest(pdf) if pdf is not None else None,
        "raw": encode(mail.as_bytes()),
    }


def verify(raw: bytes, expected: dict[str, Any]) -> str:
    try:
        mail = BytesParser(policy=policy.default).parsebytes(raw)
        for name in ("To", "From", "Subject", "Message-ID"):
            if len(mail.get_all(name, [])) != 1:
                raise ValueError("headers")
        if any(
            mail.get_all(name, [])
            for name in (
                "Cc",
                "Bcc",
                "Resent-To",
                "Resent-Cc",
                "Resent-Bcc",
                "Resent-From",
                "Resent-Message-ID",
            )
        ):
            raise ValueError("extra_recipients")
        for name, field in (("To", "recipient"), ("From", "sender")):
            if [address(a) for _, a in getaddresses(mail.get_all(name, []))] != [
                expected[field]
            ]:
                raise ValueError("address")
        actual_id = str(mail["Message-ID"])
        if str(mail["Subject"]) != expected["subject"] or not re.fullmatch(
            r"<[^<>\s@]+@[^<>\s@]+>", actual_id
        ):
            raise ValueError("identity")
        parts = list(mail.iter_parts()) if mail.is_multipart() else [mail]
        pdf_sha = expected["pdf_sha256"]
        if (
            len(parts) != (2 if pdf_sha else 1)
            or (pdf_sha and mail.get_content_type() != "multipart/mixed")
            or (not pdf_sha and mail.is_multipart())
        ):
            raise ValueError("structure")
        if any(
            p.defects or any(getattr(v, "defects", ()) for _, v in p.items())
            for p in mail.walk()
        ):
            raise ValueError("defects")
        if any(
            len(p.get_all(h, [])) > 1
            for p in mail.walk()
            for h in (
                "Content-Type",
                "Content-Disposition",
                "Content-Transfer-Encoding",
            )
        ):
            raise ValueError("mime_headers")
        plain = parts[0]
        if (
            plain.get_content_type() != "text/plain"
            or plain.is_multipart()
            or plain.get_filename() is not None
            or plain.get_content_disposition() == "attachment"
        ):
            raise ValueError("body_structure")

        def normalize(s: str) -> str:
            return s.replace("\r\n", "\n").rstrip("\n")

        if normalize(plain.get_content()) != normalize(expected["body"]):
            raise ValueError("body")
        if pdf_sha:
            p = parts[1]
            if (
                p.is_multipart()
                or p.get_content_type() != "application/pdf"
                or p.get_content_disposition() != "attachment"
                or p.get_filename() != "report.pdf"
                or storage.digest(p.get_payload(decode=True)) != pdf_sha
            ):
                raise ValueError("attachment")
        return actual_id
    except Exception:
        raise ValueError("gmail_raw_mismatch") from None
