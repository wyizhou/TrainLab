"""Prompt context construction for activity, daily placeholder and weekly report modes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.session import InMemoryConversationHistory
from trainlab.contracts.time import NO_ACTIVITY_WEEKLY_SUMMARY, format_utc, weekly_window
from trainlab.fit import get_activity_facts

ContextMode = Literal["activity", "daily", "weekly"]


class ContextError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ContextBundle:
    mode: ContextMode
    messages: tuple[dict[str, str], ...]
    metadata: dict[str, Any]


def build_context(
    *,
    mode: ContextMode,
    current_user_message: str,
    project_root: Path,
    history: InMemoryConversationHistory | None = None,
    connection: sqlite3.Connection | None = None,
    activity_id: str | None = None,
    run_time_utc: datetime | None = None,
) -> ContextBundle:
    common = {
        "role": "TrainLab local AI coach. Use tools only when the tool index allows it.",
        "tools_readme": _read_text(project_root / "source/tools/README.md"),
        "references_index": _read_text(project_root / "references/README.md"),
        "history": [
            {"role": turn.role, "content": turn.content, "created_at_utc": format_utc(turn.created_at_utc)}
            for turn in (() if history is None else history.snapshot())
        ],
    }
    mode_payload: dict[str, Any]
    if mode == "activity":
        if connection is None or activity_id is None:
            raise ContextError(ErrorCode.INVALID_ARGUMENT, "activity context requires connection and activity_id")
        mode_payload = {"activity_facts": get_activity_facts(connection, activity_id)}
    elif mode == "daily":
        mode_payload = {
            "daily_placeholder": "日报模式仅占位：不读取健康数据、不生成日报、不写数据库。"
        }
    elif mode == "weekly":
        if connection is None or run_time_utc is None:
            raise ContextError(ErrorCode.INVALID_ARGUMENT, "weekly context requires connection and run_time_utc")
        mode_payload = _weekly_payload(connection, run_time_utc)
    else:
        raise ContextError(ErrorCode.INVALID_ARGUMENT, "unknown context mode")
    metadata = {"common": common, "mode": mode_payload, "current_user_message": current_user_message}
    return ContextBundle(
        mode=mode,
        metadata=metadata,
        messages=(
            {"role": "system", "content": json.dumps(common, ensure_ascii=False, sort_keys=True)},
            {"role": "system", "content": json.dumps({"mode": mode, **mode_payload}, ensure_ascii=False, sort_keys=True)},
            {"role": "user", "content": current_user_message},
        ),
    )


def append_exchange(
    history: InMemoryConversationHistory,
    *,
    user_message: str,
    assistant_message: str,
    now_utc: datetime,
) -> None:
    history.append("user", user_message, now_utc)
    history.append("assistant", assistant_message, now_utc)


def _weekly_payload(connection: sqlite3.Connection, run_time_utc: datetime) -> dict[str, Any]:
    start, end = weekly_window(run_time_utc)
    start_text = format_utc(start)
    end_text = format_utc(end)
    activities = connection.execute(
        "SELECT activity_id,start_time_utc FROM activities WHERE start_time_utc IS NOT NULL AND start_time_utc>=? AND start_time_utc<? ORDER BY start_time_utc,activity_id",
        (start_text, end_text),
    ).fetchall()
    summaries: list[dict[str, str]] = []
    missing: list[str] = []
    for activity_id, start_time in activities:
        row = connection.execute(
            "SELECT summary FROM activties_report WHERE activity_id=?", (activity_id,)
        ).fetchone()
        if row is None:
            missing.append(activity_id)
        else:
            summaries.append(
                {"activity_id": activity_id, "start_time_utc": start_time, "summary": row[0]}
            )
    if missing:
        raise ContextError(ErrorCode.POLICY_UNCONFIGURED, "weekly missing activity reports policy is not configured")
    if not activities:
        return {
            "run_time_utc": end_text,
            "window_start_utc": start_text,
            "window_end_utc": end_text,
            "activity_summaries": [],
            "empty_week_summary": NO_ACTIVITY_WEEKLY_SUMMARY,
        }
    return {
        "run_time_utc": end_text,
        "window_start_utc": start_text,
        "window_end_utc": end_text,
        "activity_summaries": summaries,
        "empty_week_summary": None,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextError(ErrorCode.CONFIG_UNAVAILABLE, "context material is unavailable") from exc
