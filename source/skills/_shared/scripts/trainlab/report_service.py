"""Synthetic-report generation services that save only complete AI results."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trainlab.ai import AICompletion, AIConfig, CompatibleAIClient, ToolDispatcher, run_tool_loop
from trainlab.context import ContextError, append_exchange, build_context
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.session import InMemoryConversationHistory
from trainlab.contracts.time import NO_ACTIVITY_WEEKLY_SUMMARY
from trainlab.reports import save_activity_report, save_weekly_report


class ReportGenerationError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GeneratedReport:
    summary: str
    saved: dict[str, object]
    ai_messages: tuple[dict[str, Any], ...]


@dataclass
class ReportService:
    connection: sqlite3.Connection
    project_root: Path
    ai_client: CompatibleAIClient
    ai_config: AIConfig
    dispatcher: ToolDispatcher
    history: InMemoryConversationHistory

    def generate_activity_report(
        self,
        *,
        activity_id: str,
        current_user_message: str,
        now_utc: datetime,
    ) -> GeneratedReport:
        context = build_context(
            mode="activity",
            current_user_message=current_user_message,
            project_root=self.project_root,
            history=self.history,
            connection=self.connection,
            activity_id=activity_id,
        )
        completion = self._complete(context.messages)
        saved = save_activity_report(
            self.connection,
            activity_id=activity_id,
            summary=completion.content,
            capacity=self.dispatcher.capacity,
        )
        append_exchange(
            self.history,
            user_message=current_user_message,
            assistant_message=completion.content,
            now_utc=now_utc,
        )
        return GeneratedReport(completion.content, saved, completion.messages)

    def generate_weekly_report(
        self,
        *,
        run_time_utc: datetime,
        current_user_message: str,
    ) -> GeneratedReport:
        context = build_context(
            mode="weekly",
            current_user_message=current_user_message,
            project_root=self.project_root,
            history=self.history,
            connection=self.connection,
            run_time_utc=run_time_utc,
        )
        if context.metadata["mode"].get("empty_week_summary") == NO_ACTIVITY_WEEKLY_SUMMARY:
            saved = save_weekly_report(
                self.connection,
                run_time_utc=run_time_utc,
                summary=NO_ACTIVITY_WEEKLY_SUMMARY,
                capacity=self.dispatcher.capacity,
            )
            return GeneratedReport(NO_ACTIVITY_WEEKLY_SUMMARY, saved, context.messages)
        completion = self._complete(context.messages)
        saved = save_weekly_report(
            self.connection,
            run_time_utc=run_time_utc,
            summary=completion.content,
            capacity=self.dispatcher.capacity,
        )
        return GeneratedReport(completion.content, saved, completion.messages)

    def build_daily_placeholder(self, *, current_user_message: str) -> tuple[dict[str, str], ...]:
        return build_context(
            mode="daily",
            current_user_message=current_user_message,
            project_root=self.project_root,
            history=self.history,
        ).messages

    def _complete(self, messages: tuple[dict[str, str], ...]) -> AICompletion:
        try:
            return run_tool_loop(
                self.ai_client,
                model=self.ai_config.model,
                messages=messages,
                dispatcher=self.dispatcher,
                max_tool_rounds=self.ai_config.max_tool_rounds,
            )
        except ContextError as exc:
            raise ReportGenerationError(exc.code, exc.message) from exc
