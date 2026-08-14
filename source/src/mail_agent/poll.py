"""M4-04 one-shot Gmail discovery, raw archive and normalization.

This module deliberately stops before eligibility, facts, Codex and delivery.
All provider access is through the restricted M4-03 adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, cast

from .contracts import MailCounts, MailReceipt, MailRequest, mail_status
from .eligibility import CanonicalMessage
from .gmail_adapter import (
    GmailAdapterError,
    GmailIdentity,
    GmailMCPAdapter,
    GmailThreadEvidence,
)
from .locks import MailLockBusyError, MailWriteLock
from .repository import (
    _PUBLIC_SUMMARIES,
    MailRepository,
    MailRepositoryError,
    utc_now,
    validate_poll_receipt,
)

_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_MAX_WINDOW_SPLIT_DEPTH = 32
_MAX_PROVIDER_WINDOW = timedelta(days=7)


class MailPollError(RuntimeError):
    pass


class _SafeText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {
            "script",
            "style",
            "noscript",
            "template",
            "iframe",
            "object",
        }:
            self._hidden += 1
        elif self._hidden == 0 and tag.lower() in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.lower()
            in {"script", "style", "noscript", "template", "iframe", "object"}
            and self._hidden
        ):
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden == 0:
            self.parts.append(data)


def safe_html_text(value: str) -> str:
    parser = _SafeText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _parse_utc(value: object) -> str:
    if not isinstance(value, str) or not value or not value.endswith("Z"):
        raise MailPollError("gmail_message_time_invalid")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MailPollError("gmail_message_time_invalid") from None
    if instant.tzinfo is None:
        raise MailPollError("gmail_message_time_invalid")
    canonical = instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if value != canonical:
        raise MailPollError("gmail_message_time_invalid")
    return canonical


def _as_utc(value: str) -> datetime:
    return datetime.fromisoformat(_parse_utc(value).replace("Z", "+00:00"))


@dataclass(frozen=True)
class MailPollConfig:
    raw_root: Path
    lock_path: Path
    provider_page_limit: int = 100
    initial_window_hours: int = 48
    overlap_hours: int = 48
    max_raw_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if (
            not isinstance(self.raw_root, Path)
            or not isinstance(self.lock_path, Path)
            or not isinstance(self.provider_page_limit, int)
            or isinstance(self.provider_page_limit, bool)
            or not 1 <= self.provider_page_limit <= 500
            or not isinstance(self.initial_window_hours, int)
            or isinstance(self.initial_window_hours, bool)
            or self.initial_window_hours <= 0
            or self.overlap_hours != 48
            or not isinstance(self.max_raw_bytes, int)
            or isinstance(self.max_raw_bytes, bool)
            or self.max_raw_bytes <= 0
        ):
            raise ValueError("invalid_mail_poll_config")


@dataclass
class _Budget:
    limit: int | None
    used: int = 0

    def take(self) -> bool:
        if self.limit is not None and self.used >= self.limit:
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class _StreamProgress:
    start: datetime
    end: datetime
    is_continuation: bool = False
    continuation_run_count: int = 0
    candidate_thread_ids: frozenset[str] = frozenset()
    completed_thread_ids: frozenset[str] = frozenset()
    failed_thread_ids: frozenset[str] = frozenset()


class MailPollService:
    """A finite poll invocation; it owns no loop, timer, model or sender."""

    def __init__(
        self,
        repository: MailRepository,
        adapter: GmailMCPAdapter,
        config: MailPollConfig,
        *,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.config = config
        self._clock = clock

    def execute(self, request: MailRequest) -> MailReceipt:
        if request.mode != "poll":
            raise MailPollError("poll_request_required")
        started = request.requested_at_utc
        lock: MailWriteLock | None = None
        run_id: int | None = None
        try:
            lock = MailWriteLock(self.config.lock_path, request.stable_run_key)
            lock.acquire()
        except MailLockBusyError:
            return self._receipt(
                request,
                "lock_busy",
                MailCounts(),
                (),
                (),
                (
                    {
                        "stage": "lock",
                        "code": "lock_busy",
                        "summary": "mail writer is active",
                    },
                ),
                started,
            )
        try:
            run = self.repository.start_or_resume_run(request)
            run_id = run.id
            if run.status != "started":
                # Terminal invocations are receipts, never provider retries.
                replay = self._terminal_replay(request, run)
                if replay is not None:
                    return replay
                return self._receipt(
                    request,
                    "failed",
                    MailCounts(failed=1),
                    (),
                    (),
                    (
                        {
                            "stage": "replay",
                            "code": "terminal_receipt_invalid",
                            "summary": "terminal run requires operator review",
                        },
                    ),
                    started,
                    run.id,
                )
            try:
                verified_identity = self.adapter.prepare(
                    self.repository.connection, request.subject_id
                )
            except GmailAdapterError as error:
                code = self._safe_adapter_code(error.code)
                return self._persist_terminal(
                    request,
                    run.id,
                    "auth_required" if code == "auth_required" else "failed",
                    MailCounts(failed=1),
                    (),
                    (),
                    (
                        {
                            "stage": "prepare",
                            "code": code,
                            "summary": "gmail adapter unavailable",
                        },
                    ),
                    started,
                )
            identity_id = self.adapter.verified_identity_id
            if identity_id is None:
                return self._persist_terminal(
                    request,
                    run.id,
                    "failed",
                    MailCounts(failed=1),
                    (),
                    (),
                    (
                        {
                            "stage": "prepare",
                            "code": "verified_identity_required",
                            "summary": "gmail identity unavailable",
                        },
                    ),
                    started,
                )
            now = _as_utc(self._clock())
            budget = _Budget(request.max_threads)
            tracked_at_start = {
                str(row[0])
                for row in self.repository.connection.execute(
                    "SELECT provider_thread_id FROM mail_threads WHERE subject_id=? AND is_current=1",
                    (request.subject_id,),
                ).fetchall()
            }
            # A thread may belong to both streams.  Cache its completed result,
            # not merely that a read was attempted, so both cursors inherit a
            # failure while the provider/budget are consumed only once.
            read_results: dict[str, bool] = {}
            counts = {name: 0 for name in MailCounts.__dataclass_fields__}
            states: list[dict[str, str]] = []
            errors: list[dict[str, str]] = []
            label_progress = self._stream_progress(
                request.subject_id, identity_id, "trainlab_label", now
            )
            tracked_progress = self._stream_progress(
                request.subject_id, identity_id, "tracked_threads", now
            )

            def poll_label() -> tuple[bool, dict[str, str]]:
                return self._poll_label(
                    run.id,
                    request,
                    identity_id,
                    verified_identity,
                    label_progress,
                    budget,
                    read_results,
                    counts,
                    errors,
                )

            def poll_tracked() -> tuple[bool, dict[str, str]]:
                return self._poll_tracked(
                    run.id,
                    request,
                    identity_id,
                    verified_identity,
                    tracked_progress,
                    budget,
                    read_results,
                    tracked_at_start,
                    counts,
                    errors,
                )

            # A continuing stream must not be starved by a newly opened overlap
            # window in the other stream.  When both are partial, alternating
            # first access by durable run id gives each stream bounded progress;
            # same-thread reads still deduplicate through ``read_results``.
            tracked_first = tracked_progress.is_continuation and (
                not label_progress.is_continuation
                or max(
                    label_progress.continuation_run_count,
                    tracked_progress.continuation_run_count,
                )
                % 2
                == 1
            )
            if tracked_first:
                tracked_ok, tracked_state = poll_tracked()
                label_ok, label_state = poll_label()
            else:
                label_ok, label_state = poll_label()
                tracked_ok, tracked_state = poll_tracked()
            states.extend((label_state, tracked_state))
            status = "succeeded" if label_ok and tracked_ok else "partial"
            if (
                status == "succeeded"
                and counts["archived"] == 0
                and counts["discovered"] == 0
            ):
                status = "unchanged"
            # ``unchanged`` is a receipt outcome, not a persisted run state in
            # the frozen Foundation enum.  A complete no-op is persisted as a
            # successful finite run while retaining its stronger public result.
            receipt = self._persist_terminal(
                request,
                run.id,
                status,
                MailCounts(**counts),
                tuple(states),
                (),
                tuple(errors),
                started,
            )
            return receipt
        except Exception as error:
            # A public receipt is constructed before persistence.  The short
            # repository transaction either saves both terminal state and receipt
            # or rolls both back; no terminal row can lack a replay receipt.
            if (
                run_id is None
                and isinstance(error, MailRepositoryError)
                and str(error) == "invocation_id_conflicts_with_existing_run"
            ):
                existing = self.repository.connection.execute(
                    "SELECT id,status FROM mail_agent_runs WHERE invocation_id=?",
                    (request.invocation_id,),
                ).fetchone()
                if existing is not None and existing["status"] != "started":
                    return self._receipt(
                        request,
                        "failed",
                        MailCounts(failed=1),
                        (),
                        (),
                        (
                            {
                                "stage": "replay",
                                "code": "terminal_receipt_invalid",
                                "summary": ("terminal run requires operator review"),
                            },
                        ),
                        started,
                        int(existing["id"]),
                    )
            code = (
                self._safe_adapter_code(error.code)
                if isinstance(error, GmailAdapterError)
                else "poll_failed"
            )
            if run_id is not None:
                try:
                    receipt = self._persist_terminal(
                        request,
                        run_id,
                        "failed",
                        MailCounts(failed=1),
                        (),
                        (),
                        (
                            {
                                "stage": "poll",
                                "code": code,
                                "summary": "poll did not complete",
                            },
                        ),
                        started,
                    )
                    return receipt
                except Exception:
                    pass
            return self._receipt(
                request,
                "failed",
                MailCounts(failed=1),
                (),
                (),
                (
                    {
                        "stage": "poll",
                        "code": "terminal_persistence_failed",
                        "summary": "poll requires operator review",
                    },
                ),
                started,
                run_id,
            )
        finally:
            # Cleanup cannot replace an already committed public result.  Both
            # implementations are required to be idempotent; retain any lock
            # fail-closed evidence rather than attempting destructive recovery.
            try:
                self.adapter.close()
            except Exception:
                pass
            try:
                if lock is not None:
                    lock.release()
            except Exception:
                pass

    @staticmethod
    def _run_status_for_public(status: str) -> str:
        mapping = {
            "succeeded": "succeeded",
            "unchanged": "succeeded",
            "partial": "partial",
            "deferred": "deferred",
            "failed": "failed",
            "auth_required": "failed",
            "rejected": "rejected",
        }
        try:
            return mapping[status]
        except KeyError as exc:
            raise MailPollError("poll_terminal_status_invalid") from exc

    @staticmethod
    def _safe_adapter_code(code: object) -> str:
        environment_mapping = {
            "gmail_reply_auth_required": "auth_required",
            "gmail_reply_forbidden": "forbidden",
            "gmail_reply_rate_limited": "rate_limited",
            "gmail_reply_timeout": "gmail_transport_failed",
            "gmail_reply_transport_error": "gmail_transport_failed",
            "gmail_reply_provider_error": "gmail_transport_failed",
        }
        if isinstance(code, str):
            code = environment_mapping.get(code, code)
        allowed = {
            "auth_required",
            "gmail_transport_failed",
            "forbidden",
            "rate_limited",
            "identity_mismatch",
            "gmail_mapping_invalid",
            "gmail_tools_unavailable",
        }
        return (
            code
            if isinstance(code, str) and code in allowed
            else "gmail_adapter_failed"
        )

    def _persist_terminal(
        self,
        request: MailRequest,
        run_id: int,
        status: str,
        counts: MailCounts,
        poll_state: tuple[dict[str, str], ...],
        processed: tuple[str, ...],
        errors: tuple[dict[str, str], ...],
        started: str,
        next_retry_at_utc: str | None = None,
    ) -> MailReceipt:
        receipt = self._receipt(
            request,
            status,
            counts,
            poll_state,
            processed,
            errors,
            started,
            run_id,
            next_retry_at_utc,
        )
        self.repository.finish_poll_with_receipt(
            run_id, self._run_status_for_public(status), receipt.to_dict()
        )
        return receipt

    def _terminal_replay(self, request: MailRequest, run: object) -> MailReceipt | None:
        """Decode only an exact, internally consistent persisted receipt."""
        try:
            stored = self.repository.load_poll_receipt(run.id)  # type: ignore[attr-defined]
            if stored is None:
                return None
            validate_poll_receipt(stored)
            payload = dict(stored)
            payload["counts"] = MailCounts(**payload["counts"])  # type: ignore[arg-type]
            for name in (
                "processed_message_ids",
                "mail_response_artifact_ids",
                "mail_delivery_ids",
                "pending_dependencies",
                "poll_state",
                "warnings",
                "errors",
            ):
                payload[name] = tuple(cast(Iterable[Any], payload.get(name, ())))
            receipt = MailReceipt(**payload)  # type: ignore[arg-type]
            if (
                receipt.run_key != request.stable_run_key
                or receipt.invocation_id != request.invocation_id
                or receipt.mode != request.mode
                or receipt.mail_agent_run_id != str(run.id)  # type: ignore[attr-defined]
                or self._run_status_for_public(receipt.status) != run.status  # type: ignore[attr-defined]
                or receipt.to_dict() != stored
            ):
                return None
            return receipt
        except (TypeError, ValueError, KeyError, MailPollError, MailRepositoryError):
            return None

    def _window(
        self, subject_id: int, identity_id: int, stream: str, now: datetime
    ) -> tuple[datetime, datetime]:
        row = self.repository.connection.execute(
            "SELECT observed_through_utc FROM mail_poll_cursors WHERE subject_id=? AND identity_id=? AND stream_kind=?",
            (subject_id, identity_id, stream),
        ).fetchone()
        if row is None or not row[0]:
            return now - timedelta(hours=self.config.initial_window_hours), now
        cursor = _as_utc(row[0])
        if cursor > now:
            raise MailPollError("mail_cursor_invalid")
        return cursor - timedelta(hours=self.config.overlap_hours), now

    def _stream_progress(
        self, subject_id: int, identity_id: int, stream: str, now: datetime
    ) -> _StreamProgress:
        """Resume only the latest exact partial window for this stream.

        The terminal receipt freezes the incomplete window across invocations.
        Thread stage rows prove which provider reads reached normalization.
        Once a cursor advances, the window-start check invalidates all older
        continuation evidence so the next overlap window is scanned afresh.
        """
        default_start, default_end = self._window(subject_id, identity_id, stream, now)
        row = self.repository.connection.execute(
            "SELECT json_extract(state.value,'$.window_start_utc') AS window_start,"
            "json_extract(state.value,'$.window_end_utc') AS window_end "
            "FROM mail_agent_runs AS run "
            "JOIN json_each(run.context_snapshot_json,'$.mail_poll_receipt.poll_state') AS state "
            "WHERE run.subject_id=? AND run.request_kind='poll' AND run.status='partial' "
            "AND json_extract(state.value,'$.stream')=? "
            "AND json_extract(state.value,'$.status')='partial' "
            "ORDER BY run.id DESC LIMIT 1",
            (subject_id, stream),
        ).fetchone()
        if row is None:
            return _StreamProgress(default_start, default_end)
        try:
            start = _as_utc(row["window_start"])
            end = _as_utc(row["window_end"])
        except (KeyError, TypeError, MailPollError):
            return _StreamProgress(default_start, default_end)
        if start >= end or end > now:
            return _StreamProgress(default_start, default_end)
        cursor = self.repository.get_poll_cursor(subject_id, identity_id, stream)
        if cursor is not None:
            cursor_time = _as_utc(cursor.observed_through_utc)
            expected_start = cursor_time - timedelta(hours=self.config.overlap_hours)
            if start != expected_start or end < cursor_time:
                return _StreamProgress(default_start, default_end)
        candidate_rows = self.repository.connection.execute(
            "SELECT DISTINCT item.logical_item_id "
            "FROM mail_agent_items AS item "
            "JOIN mail_agent_runs AS run ON run.id=item.mail_agent_run_id "
            "JOIN json_each(run.context_snapshot_json,'$.mail_poll_receipt.poll_state') AS state "
            "WHERE run.subject_id=? AND run.request_kind='poll' AND run.status='partial' "
            "AND item.logical_item_kind=? AND item.stage='discover' "
            "AND json_extract(state.value,'$.stream')=? "
            "AND json_extract(state.value,'$.status')='partial' "
            "AND json_extract(state.value,'$.window_start_utc')=? "
            "AND json_extract(state.value,'$.window_end_utc')=?",
            (
                subject_id,
                self._candidate_kind(stream),
                stream,
                start.isoformat().replace("+00:00", "Z"),
                end.isoformat().replace("+00:00", "Z"),
            ),
        ).fetchall()
        candidates = {
            str(item["logical_item_id"])
            for item in candidate_rows
            if _PROVIDER_ID.fullmatch(str(item["logical_item_id"]))
        }
        progress_rows: list[sqlite3.Row]
        if candidates:
            placeholders = ",".join("?" for _ in candidates)
            progress_rows = self.repository.connection.execute(
                "SELECT item.logical_item_id,"
                "MAX(CASE WHEN item.status IN ('succeeded','unchanged') THEN 1 ELSE 0 END) AS completed,"
                "MAX(CASE WHEN item.status='failed' THEN 1 ELSE 0 END) AS failed "
                "FROM mail_agent_items AS item "
                "JOIN mail_agent_runs AS run ON run.id=item.mail_agent_run_id "
                "JOIN json_each(run.context_snapshot_json,'$.mail_poll_receipt.poll_state') AS state "
                "WHERE run.subject_id=? AND run.request_kind='poll' AND run.status='partial' "
                "AND item.logical_item_kind='thread' AND item.stage='normalize' "
                "AND json_extract(state.value,'$.stream')=? "
                "AND json_extract(state.value,'$.status')='partial' "
                "AND json_extract(state.value,'$.window_start_utc')=? "
                "AND json_extract(state.value,'$.window_end_utc')=? "
                f"AND item.logical_item_id IN ({placeholders}) "
                "GROUP BY item.logical_item_id",
                (
                    subject_id,
                    stream,
                    start.isoformat().replace("+00:00", "Z"),
                    end.isoformat().replace("+00:00", "Z"),
                    *sorted(candidates),
                ),
            ).fetchall()
        else:
            progress_rows = []
        completed = {
            str(item["logical_item_id"]) for item in progress_rows if item["completed"]
        }
        failed = {
            str(item["logical_item_id"])
            for item in progress_rows
            if item["failed"] and not item["completed"]
        }
        continuation_count = self.repository.connection.execute(
            "SELECT COUNT(DISTINCT run.id) "
            "FROM mail_agent_runs AS run "
            "JOIN json_each(run.context_snapshot_json,'$.mail_poll_receipt.poll_state') AS state "
            "WHERE run.subject_id=? AND run.request_kind='poll' AND run.status='partial' "
            "AND json_extract(state.value,'$.stream')=? "
            "AND json_extract(state.value,'$.status')='partial' "
            "AND json_extract(state.value,'$.window_start_utc')=? "
            "AND json_extract(state.value,'$.window_end_utc')=?",
            (
                subject_id,
                stream,
                start.isoformat().replace("+00:00", "Z"),
                end.isoformat().replace("+00:00", "Z"),
            ),
        ).fetchone()[0]
        return _StreamProgress(
            start,
            end,
            True,
            continuation_count,
            frozenset(candidates),
            frozenset(completed),
            frozenset(failed),
        )

    def _advance_cursor(
        self,
        run_id: int,
        subject_id: int,
        identity_id: int,
        stream: str,
        observed: datetime,
        start: datetime,
    ) -> None:
        self.repository.advance_poll_cursor(
            run_id,
            subject_id,
            identity_id,
            stream,
            observed.isoformat().replace("+00:00", "Z"),
            start.isoformat().replace("+00:00", "Z"),
            stream_completed=True,
        )

    def _poll_label(
        self,
        run_id: int,
        request: MailRequest,
        identity_id: int,
        identity: GmailIdentity,
        progress: _StreamProgress,
        budget: _Budget,
        read_results: dict[str, bool],
        counts: dict[str, int],
        errors: list[dict[str, str]],
    ) -> tuple[bool, dict[str, str]]:
        start, end = progress.start, progress.end
        thread_ids = self._discover_label_window(
            start,
            end,
            counts,
            errors,
            depth=0,
        )
        if thread_ids is not None:
            thread_ids |= set(progress.candidate_thread_ids)
            self._record_candidates(run_id, "trainlab_label", thread_ids)
        complete = thread_ids is not None and self._process_thread_ids(
            run_id,
            request,
            identity,
            thread_ids,
            progress,
            budget,
            read_results,
            counts,
            errors,
            error_summary="label window incomplete",
        )
        if complete:
            self._advance_cursor(
                run_id, request.subject_id, identity_id, "trainlab_label", end, start
            )
        return complete, {
            "stream": "trainlab_label",
            "status": "succeeded" if complete else "partial",
            "window_start_utc": start.isoformat().replace("+00:00", "Z"),
            "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        }

    def _discover_label_window(
        self,
        start: datetime,
        end: datetime,
        counts: dict[str, int],
        errors: list[dict[str, str]],
        *,
        depth: int,
    ) -> set[str] | None:
        if depth >= _MAX_WINDOW_SPLIT_DEPTH:
            errors.append(
                {
                    "stage": "discover",
                    "code": "provider_page_limit_unsplittable",
                    "summary": "label window incomplete",
                }
            )
            counts["deferred"] += 1
            return None
        if end - start > _MAX_PROVIDER_WINDOW:
            midpoint = start + (end - start) / 2
            left = self._discover_label_window(
                start,
                midpoint,
                counts,
                errors,
                depth=depth + 1,
            )
            if left is None:
                return None
            right = self._discover_label_window(
                midpoint,
                end,
                counts,
                errors,
                depth=depth + 1,
            )
            return None if right is None else left | right
        try:
            matches = self.adapter.search_trainlab_window(
                start_date=start,
                end_date=end,
                max_results=self.config.provider_page_limit,
            )
        except GmailAdapterError as error:
            errors.append(
                {
                    "stage": "discover",
                    "code": self._safe_adapter_code(error.code),
                    "summary": "label discovery failed",
                }
            )
            counts["failed"] += 1
            return None
        if not isinstance(matches, (list, tuple)):
            errors.append(
                {
                    "stage": "discover",
                    "code": "provider_thread_id_invalid",
                    "summary": "label result rejected",
                }
            )
            counts["failed"] += 1
            return None
        if len(matches) >= self.config.provider_page_limit:
            midpoint = start + (end - start) / 2
            if (
                midpoint <= start
                or midpoint >= end
                or (end - start).total_seconds() <= 1
            ):
                errors.append(
                    {
                        "stage": "discover",
                        "code": "provider_page_limit_unsplittable",
                        "summary": "label window incomplete",
                    }
                )
                counts["deferred"] += 1
                return None
            left = self._discover_label_window(
                start,
                midpoint,
                counts,
                errors,
                depth=depth + 1,
            )
            if left is None:
                return None
            right = self._discover_label_window(
                midpoint,
                end,
                counts,
                errors,
                depth=depth + 1,
            )
            return None if right is None else left | right
        thread_ids: set[str] = set()
        for match in matches:
            thread_id = self._provider_thread_id(match)
            if thread_id is None:
                errors.append(
                    {
                        "stage": "discover",
                        "code": "provider_thread_id_invalid",
                        "summary": "label result rejected",
                    }
                )
                counts["failed"] += 1
                return None
            thread_ids.add(thread_id)
        return thread_ids

    def _process_thread_ids(
        self,
        run_id: int,
        request: MailRequest,
        identity: GmailIdentity,
        thread_ids: set[str],
        progress: _StreamProgress,
        budget: _Budget,
        read_results: dict[str, bool],
        counts: dict[str, int],
        errors: list[dict[str, str]],
        *,
        error_summary: str,
    ) -> bool:
        unseen = sorted(
            thread_id
            for thread_id in thread_ids
            if thread_id not in progress.completed_thread_ids
            and thread_id not in progress.failed_thread_ids
        )
        retries = sorted(thread_ids & progress.failed_thread_ids)
        for thread_id in unseen + retries:
            if thread_id in read_results:
                if not read_results[thread_id]:
                    return False
                continue
            if not budget.take():
                errors.append(
                    {
                        "stage": "discover",
                        "code": "max_threads_reached",
                        "summary": error_summary,
                    }
                )
                counts["deferred"] += 1
                return False
            result = self._read_archive(
                run_id, request, identity, thread_id, counts, errors
            )
            read_results[thread_id] = result
            if not result:
                return False
        return True

    def _record_candidates(
        self, run_id: int, stream: str, thread_ids: set[str]
    ) -> None:
        """Durably freeze every discovered thread before a shared budget is used.

        A provider's next overlap query can legitimately omit a previously
        discovered thread (for example after a label change).  Candidate rows
        therefore belong to the exact partial stream/window and make its
        continuation deterministic rather than relying on another search to
        rediscover deferred work.
        """
        for thread_id in sorted(thread_ids):
            self.repository.record_item(
                run_id,
                logical_item_kind=self._candidate_kind(stream),
                logical_item_id=thread_id,
                stage="discover",
                status="succeeded",
            )

    @staticmethod
    def _candidate_kind(stream: str) -> str:
        kinds = {
            "trainlab_label": "label_candidate",
            "tracked_threads": "tracked_candidate",
        }
        try:
            return kinds[stream]
        except KeyError as exc:
            raise MailPollError("poll_stream_invalid") from exc

    @staticmethod
    def _provider_thread_id(match: object) -> str | None:
        if not isinstance(match, dict):
            return None
        candidates = [
            match[name]
            for name in ("thread_id", "threadId")
            if name in match and match[name] not in (None, "")
        ]
        if (
            not candidates
            or any(not isinstance(value, str) for value in candidates)
            or len(set(candidates)) != 1
            or _PROVIDER_ID.fullmatch(candidates[0]) is None
        ):
            return None
        return candidates[0]

    def _poll_tracked(
        self,
        run_id: int,
        request: MailRequest,
        identity_id: int,
        identity: GmailIdentity,
        progress: _StreamProgress,
        budget: _Budget,
        read_results: dict[str, bool],
        tracked_at_start: set[str],
        counts: dict[str, int],
        errors: list[dict[str, str]],
    ) -> tuple[bool, dict[str, str]]:
        start, end = progress.start, progress.end
        thread_ids = tracked_at_start | set(progress.candidate_thread_ids)
        complete = True
        for thread_id in sorted(thread_ids):
            if _PROVIDER_ID.fullmatch(thread_id) is None:
                errors.append(
                    {
                        "stage": "discover",
                        "code": "provider_thread_id_invalid",
                        "summary": "label result rejected",
                    }
                )
                counts["failed"] += 1
                complete = False
                break
        if complete:
            self._record_candidates(run_id, "tracked_threads", thread_ids)
            complete = self._process_thread_ids(
                run_id,
                request,
                identity,
                thread_ids,
                progress,
                budget,
                read_results,
                counts,
                errors,
                error_summary="tracked stream incomplete",
            )
        if complete:
            self._advance_cursor(
                run_id, request.subject_id, identity_id, "tracked_threads", end, start
            )
        return complete, {
            "stream": "tracked_threads",
            "status": "succeeded" if complete else "partial",
            "window_start_utc": start.isoformat().replace("+00:00", "Z"),
            "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        }

    def _read_archive(
        self,
        run_id: int,
        request: MailRequest,
        identity: GmailIdentity,
        thread_id: str,
        counts: dict[str, int],
        errors: list[dict[str, str]],
    ) -> bool:
        try:
            self.repository.record_item(
                run_id,
                logical_item_kind="thread",
                logical_item_id=thread_id,
                stage="discover",
                status="succeeded",
            )
            evidence = self.adapter.read_thread_evidence(thread_id)
            if evidence.thread.provider_thread_id != thread_id:
                raise MailPollError("gmail_thread_identity_conflict")
            outcome = self._archive_normalize(
                run_id, request.subject_id, identity, evidence
            )
            self.repository.record_item(
                run_id,
                logical_item_kind="thread",
                logical_item_id=thread_id,
                stage="normalize",
                status="unchanged"
                if outcome["changed"] == 0 and not outcome["thread_revised"]
                else "succeeded",
            )
        except (GmailAdapterError, MailPollError, sqlite3.Error, RuntimeError) as error:
            code = (
                self._safe_adapter_code(error.code)
                if isinstance(error, GmailAdapterError)
                else "archive_or_normalize_failed"
            )
            errors.append(
                {"stage": "archive", "code": code, "summary": "thread not completed"}
            )
            try:
                self.repository.record_item(
                    run_id,
                    logical_item_kind="thread",
                    logical_item_id=thread_id,
                    stage="archive",
                    status="failed",
                    error_code=code,
                    error_summary="thread not completed",
                )
            except Exception:
                pass
            try:
                self.repository.record_item(
                    run_id,
                    logical_item_kind="thread",
                    logical_item_id=thread_id,
                    stage="normalize",
                    status="failed",
                    error_code=code,
                    error_summary="thread not completed",
                )
            except Exception:
                pass
            counts["failed"] += 1
            return False
        if outcome["changed"] == 0 and not outcome["thread_revised"]:
            counts["unchanged"] += outcome["unchanged"]
        else:
            counts["discovered"] += outcome["changed"]
            counts["archived"] += (
                1 if outcome["thread_revised"] or outcome["changed"] else 0
            )
        counts["queued"] += outcome.get("queued", 0)
        counts["ignored"] += outcome.get("ignored", 0)
        return True

    def _archive_normalize(
        self,
        run_id: int,
        subject_id: int,
        identity: GmailIdentity,
        evidence: GmailThreadEvidence,
    ) -> dict[str, int]:
        raw = evidence.raw_payload
        if not isinstance(raw, dict) or not raw:
            raise MailPollError("gmail_raw_payload_invalid")
        self._validate_evidence(evidence, identity)
        payload = json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if not payload or len(payload) > self.config.max_raw_bytes:
            raise MailPollError("gmail_raw_payload_invalid")
        digest = hashlib.sha256(payload).hexdigest()
        observed = max(
            _as_utc(message.received_at_utc or "")
            for message in evidence.thread.messages
        )
        relative, created = self._archive_raw(payload, digest, observed)
        message_raw: dict[str, tuple[str, str, int]] = {}
        for item in raw["messages"]:
            assert isinstance(item, dict)
            message_id = str(item.get("message_id") or item.get("id"))
            item_payload = json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            item_digest = hashlib.sha256(item_payload).hexdigest()
            raw_timestamp = item.get("internal_date_utc") or item.get("received_at_utc")
            if not isinstance(raw_timestamp, str):
                raise MailPollError("gmail_raw_payload_invalid")
            item_relative, _ = self._archive_raw(
                item_payload,
                item_digest,
                _as_utc(raw_timestamp),
            )
            message_raw[message_id] = (item_digest, item_relative, len(item_payload))
        # This is intentionally outside the following projection transaction:
        # durable evidence remains recorded even when normalization rolls back.
        self.repository.record_item(
            run_id,
            logical_item_kind="thread",
            logical_item_id=evidence.thread.provider_thread_id,
            stage="archive",
            status="succeeded",
        )
        try:
            with self.repository._write_transaction():
                conn = self.repository.connection
                current = conn.execute(
                    "SELECT id FROM source_revisions WHERE provider='gmail' AND resource_kind='thread_json' AND provider_object_id=? AND payload_hash=? AND is_current=1",
                    (evidence.thread.provider_thread_id, digest),
                ).fetchone()
                # A thread snapshot may be unchanged while individual message
                # revisions are independently current; projection below decides
                # message-level no-op semantics.
                raw_row = conn.execute(
                    "SELECT id FROM raw_objects WHERE sha256=?", (digest,)
                ).fetchone()
                if raw_row is None:
                    conn.execute(
                        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,original_name,fetched_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            digest,
                            relative,
                            "application/json",
                            len(payload),
                            "gmail",
                            "thread_json",
                            f"{evidence.thread.provider_thread_id}.json",
                            self._clock(),
                        ),
                    )
                    raw_id = conn.execute(
                        "SELECT id FROM raw_objects WHERE sha256=?", (digest,)
                    ).fetchone()[0]
                else:
                    raw_id = raw_row[0]
                if current is None:
                    revision = conn.execute(
                        "SELECT COALESCE(MAX(revision_no),0)+1 FROM source_revisions WHERE provider='gmail' AND resource_kind='thread_json' AND provider_object_id=?",
                        (evidence.thread.provider_thread_id,),
                    ).fetchone()[0]
                    conn.execute(
                        "UPDATE source_revisions SET is_current=0 WHERE provider='gmail' AND resource_kind='thread_json' AND provider_object_id=? AND is_current=1",
                        (evidence.thread.provider_thread_id,),
                    )
                    conn.execute(
                        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,parser_name,parser_version,is_current,parsed_at_utc) VALUES('gmail','thread_json',?,?,?,?,'mail_poll','1',1,?)",
                        (
                            evidence.thread.provider_thread_id,
                            revision,
                            raw_id,
                            digest,
                            self._clock(),
                        ),
                    )
                    revision_id = conn.execute(
                        "SELECT id FROM source_revisions WHERE provider='gmail' AND resource_kind='thread_json' AND provider_object_id=? AND revision_no=?",
                        (evidence.thread.provider_thread_id, revision),
                    ).fetchone()[0]
                else:
                    revision_id = current[0]
                message_raw_ids: dict[str, int] = {}
                for message_id, (
                    item_digest,
                    item_relative,
                    item_size,
                ) in message_raw.items():
                    row = conn.execute(
                        "SELECT id FROM raw_objects WHERE sha256=?", (item_digest,)
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,original_name,fetched_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                            (
                                item_digest,
                                item_relative,
                                "application/json",
                                item_size,
                                "gmail",
                                "message_json",
                                f"{message_id}.json",
                                self._clock(),
                            ),
                        )
                        row = conn.execute(
                            "SELECT id FROM raw_objects WHERE sha256=?", (item_digest,)
                        ).fetchone()
                    message_raw_ids[message_id] = row[0]
                outcome = self._project(
                    conn,
                    run_id,
                    subject_id,
                    identity,
                    evidence,
                    revision_id,
                    message_raw_ids,
                )
                outcome["thread_revised"] = current is None
        except Exception:
            # Raw evidence is intentionally retained if the DB transaction fails.
            raise
        return outcome

    def _validate_evidence(
        self, evidence: GmailThreadEvidence, identity: GmailIdentity
    ) -> None:
        if (
            _PROVIDER_ID.fullmatch(evidence.thread.provider_thread_id or "") is None
            or not evidence.thread.messages
        ):
            raise MailPollError("gmail_thread_evidence_invalid")
        self_email = identity.email.strip().lower()
        if not self_email:
            raise MailPollError("gmail_identity_invalid")
        raw_messages = evidence.raw_payload.get("messages")
        if not isinstance(raw_messages, list) or len(raw_messages) != len(
            evidence.thread.messages
        ):
            raise MailPollError("gmail_raw_typed_message_mismatch")
        typed_ids = {
            message.provider_message_id for message in evidence.thread.messages
        }
        if len(typed_ids) != len(evidence.thread.messages):
            raise MailPollError("gmail_raw_typed_message_mismatch")
        raw_ids: set[str] = set()
        for raw in raw_messages:
            if not isinstance(raw, dict):
                raise MailPollError("gmail_raw_typed_message_mismatch")
            raw_id = raw.get("message_id") or raw.get("id")
            raw_thread_id = raw.get("thread_id") or raw.get("threadId")
            raw_time = raw.get("internal_date_utc") or raw.get("received_at_utc")
            headers = raw.get("headers")
            attachments = raw.get("attachments", [])
            labels = raw.get("label_ids", [])
            if (
                not isinstance(raw_id, str)
                or _PROVIDER_ID.fullmatch(raw_id) is None
                or raw_thread_id != evidence.thread.provider_thread_id
                or not isinstance(headers, dict)
                or not isinstance(attachments, list)
                or any(not isinstance(item, dict) for item in attachments)
                or not isinstance(labels, list)
                or any(not isinstance(item, str) or not item for item in labels)
            ):
                raise MailPollError("gmail_raw_typed_message_mismatch")
            _parse_utc(raw_time)
            raw_ids.add(raw_id)
        if raw_ids != typed_ids:
            raise MailPollError("gmail_raw_typed_message_mismatch")
        for message in evidence.thread.messages:
            if (
                _PROVIDER_ID.fullmatch(message.provider_message_id or "") is None
                or message.provider_thread_id != evidence.thread.provider_thread_id
            ):
                raise MailPollError("gmail_message_id_invalid")
            _parse_utc(message.received_at_utc)
            raw = next(
                item
                for item in raw_messages
                if (item.get("message_id") or item.get("id"))
                == message.provider_message_id
            )
            headers = raw["headers"]
            raw_to = tuple(
                str(v)
                for v in (
                    raw.get("to")
                    if isinstance(raw.get("to"), list)
                    else [raw.get("to")]
                    if raw.get("to")
                    else []
                )
            )
            if (
                _parse_utc(raw.get("internal_date_utc") or raw.get("received_at_utc"))
                != _parse_utc(message.received_at_utc)
                or raw.get("from") != message.sender
                or raw_to != message.recipients
                or raw.get("subject") != message.subject
                or tuple(str(v) for v in raw.get("label_ids", [])) != message.label_ids
                or headers.get("message_id") != message.message_id_header
                or headers.get("in_reply_to") != message.in_reply_to
                or tuple(str(v) for v in headers.get("references", []))
                != message.references
                or headers.get("x_trainlab_run_id") != message.trainlab_run_id
                or bool(raw.get("has_html")) != message.has_html
                or str(raw.get("plain_text") or raw.get("body_text") or "")
                != message.body_text
                or tuple(raw.get("attachments", [])) != message.attachments
            ):
                raise MailPollError("gmail_raw_typed_message_mismatch")
            # A well-formed message with an unverified actor is archived and
            # later quarantined; it is not a provider/normalization failure.

    def _archive_raw(
        self, payload: bytes, digest: str, observed: datetime
    ) -> tuple[str, bool]:
        root_fd = self._open_raw_root()
        final_fd = root_fd
        try:
            for component in (
                "gmail",
                "json",
                f"{observed.year:04d}",
                f"{observed.month:02d}",
            ):
                next_fd = self._mkdir_openat(final_fd, component)
                if final_fd != root_fd:
                    os.close(final_fd)
                final_fd = next_fd
            anchor = getattr(self, "_raw_anchor", None)
            current = os.stat(self.config.raw_root, follow_symlinks=False)
            if anchor is None or (current.st_dev, current.st_ino) != anchor:
                raise MailPollError("gmail_raw_path_invalid")
            final_name = f"{digest}.json"
            try:
                self._verify_raw_fd(final_fd, final_name, payload, digest)
                return (
                    f"raw/gmail/json/{observed.year:04d}/{observed.month:02d}/{final_name}",
                    False,
                )
            except FileNotFoundError:
                pass
            temp_name = f".{digest}.{secrets.token_hex(12)}.tmp"
            temp_created = False
            winner = False
            try:
                descriptor = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=final_fd,
                )
            except OSError as exc:
                raise MailPollError("gmail_raw_write_failed") from exc
            temp_created = True
            try:
                offset = 0
                while offset < len(payload):
                    try:
                        written = os.write(descriptor, payload[offset:])
                    except OSError as exc:
                        raise MailPollError("gmail_raw_write_failed") from exc
                    if written <= 0:
                        raise MailPollError("gmail_raw_write_failed")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            # Validate the exact durable temporary inode before it can acquire
            # the canonical name.  A short/corrupt write therefore leaves no
            # published raw object.
            self._verify_raw_fd(final_fd, temp_name, payload, digest)
            try:
                os.link(
                    temp_name,
                    final_name,
                    src_dir_fd=final_fd,
                    dst_dir_fd=final_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                self._verify_raw_fd(final_fd, final_name, payload, digest)
            else:
                winner = True
                self._verify_raw_fd(final_fd, final_name, payload, digest)
            os.unlink(temp_name, dir_fd=final_fd)
            temp_created = False
            os.fsync(final_fd)
        except Exception:
            if "temp_created" in locals() and temp_created:
                try:
                    os.unlink(temp_name, dir_fd=final_fd)
                    os.fsync(final_fd)
                except OSError:
                    pass
            raise
        finally:
            if final_fd != root_fd:
                os.close(final_fd)
            os.close(root_fd)
        return (
            f"raw/gmail/json/{observed.year:04d}/{observed.month:02d}/{digest}.json",
            winner,
        )

    def _open_raw_root(self) -> int:
        data_root = self.config.raw_root.parent
        if (
            self.config.raw_root.name != "raw"
            or self.config.raw_root.parent != data_root
        ):
            raise MailPollError("gmail_raw_path_invalid")
        try:
            before = os.lstat(data_root)
            data_fd = os.open(
                data_root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            info, after = os.fstat(data_fd), os.lstat(data_root)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                or (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino)
            ):
                raise MailPollError("gmail_raw_path_invalid")
            raw_name = self.config.raw_root.name
            raw_before = os.stat(raw_name, dir_fd=data_fd, follow_symlinks=False)
            fd = os.open(
                raw_name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=data_fd,
            )
            raw, raw_named = (
                os.fstat(fd),
                os.stat(raw_name, dir_fd=data_fd, follow_symlinks=False),
            )
            if (
                not stat.S_ISDIR(raw.st_mode)
                or raw.st_uid != os.getuid()
                or raw.st_mode & 0o077
                or (raw.st_dev, raw.st_ino) != (raw_before.st_dev, raw_before.st_ino)
                or (raw.st_dev, raw.st_ino) != (raw_named.st_dev, raw_named.st_ino)
            ):
                raise MailPollError("gmail_raw_path_invalid")
            self._raw_anchor = (raw.st_dev, raw.st_ino)
            return fd
        except (OSError, MailPollError) as exc:
            if "fd" in locals():
                os.close(fd)
            raise MailPollError("gmail_raw_path_invalid") from exc
        finally:
            if "data_fd" in locals():
                os.close(data_fd)

    @staticmethod
    def _mkdir_openat(parent_fd: int, name: str) -> int:
        try:
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise MailPollError("gmail_raw_path_invalid") from exc
        fd: int | None = None
        try:
            fd = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            info, named = (
                os.fstat(fd),
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False),
            )
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise MailPollError("gmail_raw_path_invalid")
            return fd
        except Exception as exc:
            if fd is not None:
                os.close(fd)
            if isinstance(exc, MailPollError):
                raise
            raise MailPollError("gmail_raw_path_invalid") from exc

    @staticmethod
    def _verify_raw_fd(
        directory_fd: int, name: str, payload: bytes, digest: str
    ) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
            try:
                info = os.fstat(descriptor)
                named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                    raise MailPollError("gmail_raw_path_invalid")
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_size != len(payload)
                ):
                    raise MailPollError("gmail_raw_path_invalid")
                hasher = hashlib.sha256()
                while True:
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
                if hasher.hexdigest() != digest:
                    raise MailPollError("gmail_raw_path_invalid")
                named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != (
                    named_after.st_dev,
                    named_after.st_ino,
                ):
                    raise MailPollError("gmail_raw_path_invalid")
            finally:
                os.close(descriptor)
        except MailPollError:
            raise
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise MailPollError("gmail_raw_path_invalid") from exc

    def _project(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        subject_id: int,
        identity: GmailIdentity,
        evidence: GmailThreadEvidence,
        revision_id: int,
        message_raw_ids: dict[str, int],
    ) -> dict[str, int]:
        messages = tuple(
            sorted(
                evidence.thread.messages,
                key=lambda item: (
                    _as_utc(item.received_at_utc or ""),
                    item.provider_message_id,
                ),
            )
        )
        first = _parse_utc(messages[0].received_at_utc)
        last = _parse_utc(messages[-1].received_at_utc)
        subject = next((item.subject for item in messages if item.subject), None)
        labels = sorted({label for item in messages for label in item.label_ids})
        raw_thread_labels = evidence.raw_payload.get(
            "label_ids", evidence.raw_payload.get("labelIds", [])
        )
        if not isinstance(raw_thread_labels, list) or any(
            not isinstance(label, str) for label in raw_thread_labels
        ):
            raise MailPollError("gmail_raw_typed_message_mismatch")
        thread_label_present = "TrainLab" in raw_thread_labels
        prior_thread = conn.execute(
            "SELECT id FROM mail_threads WHERE subject_id=? AND provider_thread_id=? AND is_current=1",
            (subject_id, evidence.thread.provider_thread_id),
        ).fetchone()
        thread_was_tracked = prior_thread is not None
        conn.execute(
            "INSERT INTO mail_threads(subject_id,provider_thread_id,normalized_subject,first_message_at_utc,last_message_at_utc,message_count,trainlab_label_state,is_current) VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(subject_id,provider_thread_id) DO UPDATE SET normalized_subject=excluded.normalized_subject,first_message_at_utc=excluded.first_message_at_utc,last_message_at_utc=excluded.last_message_at_utc,message_count=excluded.message_count,trainlab_label_state=excluded.trainlab_label_state,is_current=1",
            (
                subject_id,
                evidence.thread.provider_thread_id,
                subject,
                first,
                last,
                len(messages),
                "present"
                if ("TrainLab" in labels or thread_label_present)
                else "absent",
            ),
        )
        thread_id = conn.execute(
            "SELECT id FROM mail_threads WHERE subject_id=? AND provider_thread_id=?",
            (subject_id, evidence.thread.provider_thread_id),
        ).fetchone()[0]
        raw_value = evidence.raw_payload.get("messages")
        raw_messages: list[dict[str, Any]] = (
            [item for item in raw_value if isinstance(item, dict)]
            if isinstance(raw_value, list)
            else []
        )
        raw_by_id = {
            str(item.get("message_id") or item.get("id")): item
            for item in raw_messages
            if isinstance(item, dict)
        }
        if len(raw_by_id) != len(raw_messages) or set(raw_by_id) != {
            item.provider_message_id for item in messages
        }:
            raise MailPollError("gmail_raw_typed_message_mismatch")
        # A thread-level label is a current-thread signal, not a historical
        # union label.  In a first snapshot it can only nominate the newest
        # canonical message; older private messages must never be upgraded.
        thread_label_candidate = (
            messages[-1].provider_message_id if thread_label_present else None
        )
        # This is a cursor within the canonical chronological message order,
        # not a retroactive property of the whole thread snapshot.
        tracked_for_later_messages = thread_was_tracked
        changed = 0
        unchanged = 0
        queued = 0
        ignored = 0
        for message in messages:
            raw_message = raw_by_id.get(message.provider_message_id, {})
            html = raw_message.get("html") or raw_message.get("html_body") or ""
            body = message.body_text or safe_html_text(str(html))
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            timestamp = _parse_utc(message.received_at_utc)
            message_payload = json.dumps(
                raw_message, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            message_hash = hashlib.sha256(message_payload).hexdigest()
            current_revision = conn.execute(
                "SELECT id FROM source_revisions WHERE provider='gmail' AND resource_kind='message_json' AND provider_object_id=? AND payload_hash=? AND is_current=1",
                (message.provider_message_id, message_hash),
            ).fetchone()
            message_revision_id: int | None = None
            if current_revision is not None:
                message_revision_id = current_revision[0]
                unchanged += 1
            else:
                number = conn.execute(
                    "SELECT COALESCE(MAX(revision_no),0)+1 FROM source_revisions WHERE provider='gmail' AND resource_kind='message_json' AND provider_object_id=?",
                    (message.provider_message_id,),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE source_revisions SET is_current=0 WHERE provider='gmail' AND resource_kind='message_json' AND provider_object_id=? AND is_current=1",
                    (message.provider_message_id,),
                )
                conn.execute(
                    "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,parser_name,parser_version,is_current,parsed_at_utc) VALUES('gmail','message_json',?,?,?,?,'mail_poll','1',1,?)",
                    (
                        message.provider_message_id,
                        number,
                        message_raw_ids[message.provider_message_id],
                        message_hash,
                        self._clock(),
                    ),
                )
                message_revision_id = conn.execute(
                    "SELECT id FROM source_revisions WHERE provider='gmail' AND resource_kind='message_json' AND provider_object_id=? AND revision_no=?",
                    (message.provider_message_id, number),
                ).fetchone()[0]
                changed += 1
            existing = conn.execute(
                "SELECT m.id,t.subject_id,t.provider_thread_id "
                "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                "WHERE m.provider_message_id=?",
                (message.provider_message_id,),
            ).fetchone()
            if existing is not None and (
                existing["subject_id"] != subject_id
                or existing["provider_thread_id"] != evidence.thread.provider_thread_id
            ):
                raise MailPollError("gmail_message_identity_conflict")
            if existing is None:
                conn.execute(
                    "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,subject,body_text,body_sha256,in_reply_to_provider_message_id,labels_json,source_revision_id,processing_state) VALUES(?,?, 'unknown','unknown',?,?,?,?,?,?,?,'normalized')",
                    (
                        thread_id,
                        message.provider_message_id,
                        timestamp,
                        message.subject,
                        body,
                        body_hash,
                        message.in_reply_to,
                        json.dumps(list(message.label_ids), sort_keys=True),
                        message_revision_id,
                    ),
                )
                message_id = conn.execute(
                    "SELECT id FROM mail_messages WHERE provider_message_id=?",
                    (message.provider_message_id,),
                ).fetchone()[0]
            elif current_revision is None:
                message_id = existing["id"]
                conn.execute(
                    "UPDATE mail_messages SET mail_thread_id=?,received_at_utc=?,subject=?,body_text=?,body_sha256=?,in_reply_to_provider_message_id=?,labels_json=?,source_revision_id=?,processing_state='normalized' WHERE id=?",
                    (
                        thread_id,
                        timestamp,
                        message.subject,
                        body,
                        body_hash,
                        message.in_reply_to,
                        json.dumps(list(message.label_ids), sort_keys=True),
                        message_revision_id,
                        message_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM mail_attachments WHERE mail_message_id=?",
                    (message_id,),
                )
            else:
                message_id = existing["id"]
            if existing is None or current_revision is None:
                for attachment in message.attachments:
                    size = (
                        attachment.get("size_bytes")
                        if "size_bytes" in attachment
                        else attachment.get("size")
                    )
                    if size is not None and (
                        not isinstance(size, int) or isinstance(size, bool) or size < 0
                    ):
                        raise MailPollError("gmail_attachment_metadata_invalid")
                    conn.execute(
                        "INSERT INTO mail_attachments(mail_message_id,provider_attachment_id,filename,media_type,size_bytes,raw_object_id,content_disposition) VALUES(?,?,?,?,?,?,?)",
                        (
                            message_id,
                            attachment.get("id") or attachment.get("attachment_id"),
                            attachment.get("filename"),
                            attachment.get("media_type") or attachment.get("mime_type"),
                            size,
                            None,
                            attachment.get("content_disposition"),
                        ),
                    )
            current_row = conn.execute(
                "SELECT processing_state FROM mail_messages WHERE id=?", (message_id,)
            ).fetchone()
            assert current_row is not None
            if current_row["processing_state"] == "normalized":
                raw_headers = raw_message.get("headers", {})
                auto = raw_headers.get("auto_submitted") or raw_headers.get(
                    "Auto-Submitted"
                )
                self_email = identity.email.strip().lower()
                sender = (message.sender or "").strip().lower()
                recipients = {item.strip().lower() for item in message.recipients}
                decision = self.repository._classify_normalized_message_txn(
                    run_id,
                    subject_id,
                    message_id,
                    # The configured recipient is the authorized mailbox.  A
                    # reply from it is private even when the Gmail login is a
                    # distinct delivery account; unrelated recipients are not.
                    CanonicalMessage(
                        message.provider_message_id,
                        sender == self_email,
                        self_email in {sender, *recipients},
                        frozenset(message.label_ids),
                        message.subject,
                        body,
                        len(message.attachments),
                        str(auto) if auto is not None else None,
                        "mailer-daemon" in sender or "postmaster" in sender,
                    ),
                    tracked_for_later_messages,
                    bool(message.trainlab_run_id),
                    thread_label_candidate == message.provider_message_id,
                )
                if decision.processing_state == "queued":
                    queued += 1
                elif decision.processing_state in {
                    "ignored",
                    "store_only",
                    "quarantined",
                }:
                    ignored += 1
                # A locally proven outbound, or a genuinely accepted labeled
                # request, establishes the thread only for later messages.
                if decision.actor_role == "trainlab" or (
                    decision.event_type == "new_request_received"
                    and decision.actor_role == "user"
                ):
                    tracked_for_later_messages = True
            item_status = "succeeded" if current_revision is None else "unchanged"
            for stage in ("discover", "archive", "normalize"):
                conn.execute(
                    "INSERT INTO mail_agent_items(mail_agent_run_id,logical_item_kind,logical_item_id,mail_message_id,stage,status,attempt_count,started_at_utc,completed_at_utc) VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(mail_agent_run_id,logical_item_kind,logical_item_id,stage) DO NOTHING",
                    (
                        run_id,
                        "message",
                        message.provider_message_id,
                        message_id,
                        stage,
                        item_status,
                        1,
                        self._clock(),
                        self._clock(),
                    ),
                )
        return {
            "changed": changed,
            "unchanged": unchanged,
            "queued": queued,
            "ignored": ignored,
        }

    def _receipt(
        self,
        request: MailRequest,
        status: str,
        counts: MailCounts,
        poll_state: tuple[dict[str, str], ...],
        processed: tuple[str, ...],
        errors: tuple[dict[str, str], ...],
        started: str,
        run_id: int | None = None,
        next_retry_at_utc: str | None = None,
    ) -> MailReceipt:
        action = {
            "succeeded": "none",
            "unchanged": "none",
            "partial": "continue_poll",
            "deferred": "continue_poll",
            "auth_required": "reauthenticate",
            "rejected": "operator_review",
            "failed": "operator_review",
            "lock_busy": "continue_poll",
        }.get(status, "operator_review")
        public_errors: list[dict[str, str]] = []
        for item in errors:
            stage = item.get("stage") if isinstance(item, dict) else None
            code = item.get("code") if isinstance(item, dict) else None
            key = (stage, code)
            if key not in _PUBLIC_SUMMARIES:
                key = ("poll", "poll_failed")
            public_errors.append(
                {"stage": key[0], "code": key[1], "summary": _PUBLIC_SUMMARIES[key]}
            )
        return MailReceipt(
            run_key=request.stable_run_key,
            mail_agent_run_id=None if run_id is None else str(run_id),
            invocation_id=request.invocation_id,
            mode="poll",
            status=mail_status(status),
            counts=counts,
            poll_state=poll_state,
            processed_message_ids=processed,
            errors=tuple(public_errors),
            next_action=action,
            next_retry_at_utc=next_retry_at_utc,
            started_at_utc=started,
            completed_at_utc=self._clock(),
        )
