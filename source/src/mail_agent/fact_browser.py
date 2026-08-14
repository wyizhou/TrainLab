"""Deterministic, read-only fact browser for the user mail command.

The command is intentionally tiny and exact.  It never accepts a fact value,
mutation verb, shell-like option, or free-form filter, so a mail message can
only request a bounded view of append-only facts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_COMMAND = re.compile(
    r"^\s*(?:FACTS|事实)(?:\s+(all|active|pending|future|expired|revoked))?\s*$",
    re.IGNORECASE,
)
_STATUSES = frozenset({"all", "active", "pending", "future", "expired", "revoked"})
_MAX_OUTPUT_BYTES = 24_000


@dataclass(frozen=True, slots=True)
class FactBrowserCommand:
    status: str = "all"


def parse_fact_browser_command(value: object) -> FactBrowserCommand | None:
    """Return a command only for an exact one-line FACTS/事实 request."""
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return None
    match = _COMMAND.fullmatch(value)
    if match is None:
        return None
    status = (match.group(1) or "all").casefold()
    return FactBrowserCommand(status if status in _STATUSES else "all")


def render_fact_browser_text(rows: Sequence[Mapping[str, Any]], *, status: str) -> str:
    """Render a bounded, user-facing read-only view without internal paths."""
    if status not in _STATUSES:
        raise ValueError("fact_browser_status_invalid")
    lines = [f"TrainLab 事实浏览（{status}）", ""]
    if not rows:
        lines.append("没有符合条件的事实。")
    else:
        for row in rows[:100]:
            value = row.get("value")
            try:
                value_text = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError):
                value_text = "<不可显示>"
            lines.append(
                f"FACT-ID {row.get('id')}: {row.get('fact_key')} "
                f"[{row.get('state')}] {value_text}"
            )
            if row.get("effective_from_utc") or row.get("expires_at_utc"):
                lines.append(
                    "  生效: "
                    + str(row.get("effective_from_utc") or "立即")
                    + "；失效: "
                    + str(row.get("expires_at_utc") or "未设置")
                )
    text = "\n".join(lines)
    encoded = text.encode("utf-8")
    if len(encoded) > _MAX_OUTPUT_BYTES:
        text = encoded[:_MAX_OUTPUT_BYTES].decode("utf-8", "ignore")
        text += "\n（结果已按固定上限截断；请使用 CLI 分页/筛选。）"
    return text


__all__ = [
    "FactBrowserCommand",
    "parse_fact_browser_command",
    "render_fact_browser_text",
]
