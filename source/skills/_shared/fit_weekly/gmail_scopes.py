from __future__ import annotations

from typing import Any

SCOPES = frozenset({"https://www.googleapis.com/auth/gmail.modify"})
LEGACY_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    }
)


def valid(value: Any, *, labels: bool) -> bool:
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
        not isinstance(v, str) for v in value
    ):
        return False
    granted = set(value)
    return granted <= SCOPES | LEGACY_SCOPES and (
        SCOPES <= granted or not labels and LEGACY_SCOPES <= granted
    )
