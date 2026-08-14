"""Strict, non-secret reads of project-scoped user controls.

Only validated values are returned.  Callers receive a stable error code and
never receive raw configuration content, so a malformed ignored local config
cannot leak through receipts or logs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ProjectConfigurationError(ValueError):
    """Stable non-secret project configuration failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def configured_recipient_email(root: Path) -> str:
    """Return the sole user-authorized recipient from ``config/trainlab.json``.

    The recipient is intentionally project configuration rather than a Gmail
    identity lookup.  It is used unchanged as the fixed target authority by
    the mail and analysis layers after canonical lower-casing.
    """

    path = root / "config" / "trainlab.json"
    if not path.exists():
        path = root / "config" / "src.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        email = value["mail"]["recipient_email"]
    except (OSError, TypeError, ValueError, KeyError):
        raise ProjectConfigurationError("mail_runtime_configuration_invalid") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("mail"), dict)
        or not isinstance(email, str)
        or email != email.strip()
        or _EMAIL.fullmatch(email) is None
    ):
        raise ProjectConfigurationError("mail_runtime_configuration_invalid")
    return email.lower()
