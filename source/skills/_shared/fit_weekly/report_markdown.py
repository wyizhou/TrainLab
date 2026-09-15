"""Markdown rendering of the shared ordered report content."""

from __future__ import annotations

import html
from typing import Any

from skills._shared.fit_weekly import report_view


def escape(value: str) -> str:
    # Treat all model/user strings as text, including links and raw HTML.
    text = html.escape(value, quote=False).replace("\\", "\\\\")
    for char in "`*_{}[]()#+|":
        text = text.replace(char, "\\" + char)
    return text.replace("\r", "").replace("\n", "<br>")


def render(view: dict[str, Any]) -> bytes:
    lines = []
    for block in report_view.blocks(view):
        kind = block["kind"]
        if kind == "heading":
            lines.append("#" * block["level"] + " " + escape(block["text"]))
        elif kind == "paragraph":
            lines.append(escape(block["text"]))
        elif kind == "table":
            lines.append("| " + " | ".join(map(escape, block["headers"])) + " |")
            lines.append("| " + " | ".join("---" for _ in block["headers"]) + " |")
            lines.extend(
                "| " + " | ".join(map(escape, row)) + " |" for row in block["rows"]
            )
        elif kind == "chart":
            lines.append(escape(block["title"]))
            lines.extend(
                escape(f"{name}：{report_view.number(value)} 秒；{status}")
                for name, value, status in block["rows"]
            )
        lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")
