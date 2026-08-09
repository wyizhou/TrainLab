"""Collection lifecycle, locking, retries and provider-call control."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import *  # noqa: F403
from .repository import GarminRepository


class _LiveAuthAtomicReplaceError(OSError):
    """Redacted outcome of the one allowed credential replacement."""

    def __init__(self, stage: str, *, replaced: bool) -> None:
        super().__init__(stage)
        self.stage = stage
        self.replaced = replaced


class _LiveAcceptancePreflightError(OSError):
    """A redacted stable-authority preflight failure.

    The message is deliberately a fixed code rather than an operating-system
    error.  Preflight evidence is permitted to say *what class* of guard
    failed, but must never turn a production path or file metadata into a
    durable receipt.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GarminCollectionBase:
    def __init__(
        self,
        config: GarminConfig,
        transport: GarminTransport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(TZ),
        monotonic: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] | None = None,
    ) -> None:
        (
            self.config,
            self.transport,
            self.repo,
            self.sleep,
            self.clock,
            self.monotonic,
        ) = config, transport, GarminRepository(config), sleep, clock, monotonic
        self.rng = rng or random.Random().random
        self._last_request: float | None = None

    def execute(self, request: SyncRequest) -> SyncReceipt:
        if request.invocation_id is None:
            request = replace(request, invocation_id=f"garmin-{uuid.uuid4()}")
        receipt = SyncReceipt(
            mode=request.mode,
            requested_range={
                "from": request.health_from_local_date,
                "through": request.through_local_date or request.snapshot_local_date,
            },
            effective_range={"from": None, "through": None},
        )
        self._validate(request)
        if request.mode == "status":
            return self._validated_receipt(self._status(receipt))
        if request.mode == "auth":
            return self._validated_receipt(self._auth(receipt))
        lock = self.config.state_root / "locks" / "garmin.lock"
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not self._recover_stale_lock(lock, request.invocation_id):
                receipt.status, receipt.completed_at_utc = "lock_busy", utc_now()
                return self._validated_receipt(receipt)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(
                fd,
                stable_json(
                    {
                        "pid": os.getpid(),
                        "invocation_id": request.invocation_id,
                        "started_at_utc": receipt.started_at_utc,
                    }
                ),
            )
            os.fsync(fd)
            return self._validated_receipt(self._execute_locked(request, receipt))
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)

    def _recover_stale_lock(
        self,
        lock: Path,
        requested_invocation_id: str | None = None,
    ) -> bool:
        """Clear a dead-PID lock only when resuming its exact invocation.

        A matching started run is intentionally recoverable because
        ``start_run`` resets an interrupted running item to pending and reuses
        the same run.  A different invocation must remain ``lock_busy`` so it
        cannot strand or overlap the interrupted run.
        """
        try:
            payload = json.loads(lock.read_text())
            pid = int(payload["pid"])
            invocation_id = payload.get("invocation_id")
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            pass
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return False
        conn = self.repo.connect()
        try:
            active = (
                conn.execute(
                    "SELECT 1 FROM garmin_sync_runs WHERE invocation_id=? AND status='started'",
                    (invocation_id,),
                ).fetchone()
                if invocation_id
                else None
            )
            if active and requested_invocation_id != invocation_id:
                return False
        finally:
            conn.close()
        lock.unlink(missing_ok=True)
        return True

    def _execute_locked(
        self, request: SyncRequest, receipt: SyncReceipt
    ) -> SyncReceipt:
        conn = self.repo.connect()
        run = 0
        actual_start: date | None = None
        actual_through: date | None = None
        try:
            subject = self.repo.subject(conn)
            # Repair legacy implicit-default metadata before every controlled
            # collection/audit entry.  It is local, idempotent and performs no
            # provider call, so a small repair can heal an existing database.
            self.repo.reconcile_legacy_capability_environment(
                conn,
                subject,
                self.config.region,
            )
            run = self.repo.start_run(conn, request, subject, receipt)
            if receipt.status != "started":
                return receipt
            # Reparse and reconcile are deliberately offline operations.  In
            # particular they must remain usable while a token is expired or
            # Garmin is unavailable; the immutable raw object is the input.
            repair_strategy = self._repair_strategy(conn, subject, request, receipt)
            offline_repair = request.mode == "repair" and repair_strategy in {
                "reparse",
                "reconcile",
            }
            if request.mode == "repair" and repair_strategy == "deferred":
                receipt.status = "deferred"
                self.repo.finish_run(conn, run, receipt, None, None)
                return receipt
            if not offline_repair:
                identity = conn.execute(
                    "SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND is_verified=1",
                    (subject,),
                ).fetchone()
                if identity is None:
                    receipt.status = "auth_required"
                    receipt.errors.append(
                        {
                            "code": "verified_identity_required",
                            "resource": "auth",
                            "logical_object_key": "garmin:account:identity",
                            "summary": "authenticate before sync",
                        }
                    )
                    self.repo.finish_run(conn, run, receipt, None, None)
                    return receipt
                try:
                    self._transport().login()
                    actual = self._identity_hmac(self._transport().identity())
                    verified = conn.execute(
                        "SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND identity_hmac=? AND is_verified=1",
                        (subject, actual),
                    ).fetchone()
                    if verified is None:
                        receipt.status = "failed"
                        receipt.errors.append(
                            {
                                "code": "identity_mismatch",
                                "resource": "auth",
                                "logical_object_key": "garmin:account:identity",
                                "summary": "identity mismatch",
                            }
                        )
                        self.repo.finish_run(conn, run, receipt, None, None)
                        return receipt
                except GarminError as exc:
                    receipt.status = (
                        "auth_required" if exc.http_status == 401 else "failed"
                    )
                    receipt.errors.append(
                        {
                            "code": exc.code,
                            "resource": "auth",
                            "logical_object_key": "garmin:account:identity",
                            "summary": "provider authentication failed",
                        }
                    )
                    self.repo.finish_run(conn, run, receipt, None, None)
                    return receipt
            today = self._today_local()
            yesterday = today - timedelta(days=1)
            if request.mode == "repair" and offline_repair:
                actual_through = (
                    date.fromisoformat(request.through_local_date)
                    if request.through_local_date
                    else yesterday
                )
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                self._offline_repair(
                    conn,
                    run,
                    subject,
                    replace(request, repair_strategy=repair_strategy),
                    receipt,
                )
                self._advance_repair_health_cursors(
                    conn,
                    run,
                    subject,
                    request,
                    actual_through,
                )
            elif request.mode in {"full", "incremental", "snapshot"}:
                plan = self._build_mode_plan(conn, subject, request, today)
                prior_gap_ceiling = (
                    int(
                        conn.execute(
                            "SELECT coalesce(max(id),0) FROM garmin_sync_gaps"
                        ).fetchone()[0]
                    )
                    if request.mode == "incremental"
                    else 0
                )
                actual_start, actual_through = (
                    plan.effective_start,
                    plan.effective_through,
                )
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                if plan.snapshot:
                    receipt.coverage_state = "partial"
                self._account_basics(
                    conn, run, subject, plan.effective_through, request, receipt
                )
                self._account_b1(
                    conn, run, subject, plan.effective_through, request, receipt
                )
                selected = set(request.resource_kinds)
                for window in plan.health_windows:
                    scoped = replace(request, resource_kinds=(window.resource_kind,))
                    self._health(
                        conn,
                        run,
                        subject,
                        window.start,
                        window.through,
                        scoped,
                        receipt,
                    )
                # Explicit account-only repair is a closed provider scope: it
                # must not enumerate activities merely because activities are
                # normally part of a full collection invocation.
                activity_scope = {
                    "activity_inventory",
                    "activity_summary",
                    "activity_fit",
                    "activity_details_fallback",
                    "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if (
                    request.activity_ids
                    or not selected
                    or selected.intersection(activity_scope)
                ):
                    self._activities(
                        conn,
                        run,
                        subject,
                        plan.activity_start,
                        plan.activity_through,
                        request,
                        receipt,
                        not selected or "activity_fit" in selected,
                    )
                if request.mode == "incremental":
                    self._process_due_gaps(
                        conn,
                        run,
                        subject,
                        request,
                        receipt,
                        plan.activity_start,
                        plan.activity_through,
                        prior_gap_ceiling,
                    )
                if not plan.snapshot:
                    for window in plan.health_windows:
                        self.repo.advance_cursor(
                            conn,
                            subject,
                            window.resource_kind,
                            window.through.isoformat(),
                            run,
                        )
                    if receipt.coverage_state != "partial":
                        receipt.coverage_state = (
                            "complete"
                            if self._health_windows_complete(
                                conn, subject, plan.health_windows
                            )
                            else "partial"
                        )
            elif request.mode == "audit":
                actual_through = (
                    date.fromisoformat(request.through_local_date)
                    if request.through_local_date
                    else today
                )
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                self._audit(conn, subject, receipt, actual_start, actual_through)
            elif request.mode == "repair":
                actual_through = (
                    date.fromisoformat(request.through_local_date)
                    if request.through_local_date
                    else yesterday
                )
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                self._account_basics(
                    conn, run, subject, actual_through, request, receipt
                )
                self._account_b1(conn, run, subject, actual_through, request, receipt)
                selected = set(request.resource_kinds)
                if not selected or selected.intersection(COLLECTED_HEALTH_RESOURCES):
                    self._health(
                        conn,
                        run,
                        subject,
                        actual_start,
                        actual_through,
                        request,
                        receipt,
                    )
                activity_scope = {
                    "activity_inventory",
                    "activity_summary",
                    "activity_fit",
                    "activity_details_fallback",
                    "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if (
                    request.activity_ids
                    or not selected
                    or selected.intersection(activity_scope)
                ):
                    self._activities(
                        conn,
                        run,
                        subject,
                        actual_start,
                        actual_through,
                        request,
                        receipt,
                        not selected or "activity_fit" in selected,
                    )
                self._advance_repair_health_cursors(
                    conn,
                    run,
                    subject,
                    request,
                    actual_through,
                )
            receipt.status = (
                "deferred"
                if receipt.counts["deferred"]
                else (
                    "partial"
                    if receipt.counts["failed"]
                    or (
                        request.mode != "snapshot"
                        and receipt.coverage_state == "partial"
                    )
                    else "succeeded"
                )
            )
            receipt.open_gap_count = int(
                conn.execute(
                    "SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred')",
                    (subject,),
                ).fetchone()[0]
            )
            receipt.complete_through_by_resource = {
                r["resource_kind"]: r["complete_through_local_date"]
                for r in conn.execute(
                    "SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?",
                    (subject,),
                )
            }
            if receipt.next_retry_at_utc is None:
                pending_retry = conn.execute(
                    """SELECT min(next_retry_at_utc) FROM garmin_sync_gaps
                       WHERE subject_id=? AND status='deferred'
                         AND next_retry_at_utc IS NOT NULL""",
                    (subject,),
                ).fetchone()[0]
                receipt.next_retry_at_utc = pending_retry
            self.repo.finish_run(
                conn,
                run,
                receipt,
                actual_start.isoformat() if actual_start else None,
                actual_through.isoformat() if actual_through else None,
            )
            return receipt
        except GarminError as exc:
            receipt.status = "auth_required" if exc.http_status == 401 else "failed"
            receipt.errors.append(
                {
                    "code": exc.code,
                    "resource": "garmin",
                    "logical_object_key": "garmin:run",
                    "summary": exc.code,
                }
            )
            try:
                self.repo.finish_run(
                    conn,
                    run,
                    receipt,
                    actual_start.isoformat() if actual_start else None,
                    actual_through.isoformat() if actual_through else None,
                )
            except Exception:
                receipt.completed_at_utc = utc_now()
            return receipt
        finally:
            conn.close()

    def _today_local(self) -> date:
        value = self.clock()
        if value.tzinfo is not None:
            value = value.astimezone(TZ)
        return value.date()

    def _build_mode_plan(
        self,
        conn: sqlite3.Connection,
        subject: int,
        request: SyncRequest,
        today: date,
    ) -> CollectionModePlan:
        selected = set(request.resource_kinds)
        health_resources = tuple(
            resource
            for resource in COLLECTED_HEALTH_RESOURCES
            if not selected or resource in selected
        )
        cursors = {
            row["resource_kind"]: row["complete_through_local_date"]
            for row in conn.execute(
                """SELECT resource_kind,complete_through_local_date
                   FROM garmin_sync_cursors
                   WHERE subject_id=? AND cursor_grain='local_date'""",
                (subject,),
            )
        }
        history_start = (
            request.health_from_local_date
            or self.config.history_start_date
            or today.isoformat()
        )
        return build_collection_mode_plan(
            mode=request.mode,  # type: ignore[arg-type]
            today_local=today,
            history_start_date=history_start,
            requested_health_from=request.health_from_local_date,
            requested_through=request.through_local_date,
            requested_snapshot_date=request.snapshot_local_date,
            health_resources=health_resources,
            complete_through_by_resource=cursors,
            lookback_days=self.config.lookback_days,
        )

    @staticmethod
    def _repair_cursor_resources(request: SyncRequest) -> tuple[str, ...]:
        """Return only date-grained health resources in a repair's scope.

        Account and activity observations have no complete-day cursor.  An
        empty repair scope means the normal all-health scope, matching
        ``_health``.
        """
        selected = set(request.resource_kinds)
        return tuple(
            resource
            for resource in COLLECTED_HEALTH_RESOURCES
            if not selected or resource in selected
        )

    def _advance_repair_health_cursors(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        request: SyncRequest,
        actual_through: date,
    ) -> None:
        """Advance repaired health cursors only across verified continuity.

        ``advance_cursor`` checks the latest day coverage and open/deferred
        gaps one date at a time.  Calling it per eligible resource therefore
        allows a successful health repair to recover an old cursor even when
        the same repair has unrelated activity/FIT failures, while still
        stopping at every unresolved health gap.
        """
        for resource in self._repair_cursor_resources(request):
            self.repo.advance_cursor(
                conn,
                subject,
                resource,
                actual_through.isoformat(),
                run,
            )

    @staticmethod
    def _health_windows_complete(
        conn: sqlite3.Connection,
        subject: int,
        windows: Iterable[ResourceDateWindow],
    ) -> bool:
        closed_states = {
            "fetched",
            "empty",
            "not_enabled",
            "not_available",
            "not_supported",
        }
        for window in windows:
            rows = conn.execute(
                """SELECT local_date,availability_state
                   FROM resource_coverage
                   WHERE subject_id=? AND provider='garmin'
                     AND resource_kind=? AND local_date>=? AND local_date<=?
                   ORDER BY id""",
                (
                    subject,
                    window.resource_kind,
                    window.start.isoformat(),
                    window.through.isoformat(),
                ),
            )
            latest = {row["local_date"]: row["availability_state"] for row in rows}
            expected = (window.through - window.start).days + 1
            if len(latest) != expected or any(
                state not in closed_states for state in latest.values()
            ):
                return False
            blocking_gap = conn.execute(
                """SELECT 1 FROM garmin_sync_gaps
                   WHERE subject_id=? AND resource_kind=?
                     AND status IN ('open','deferred')
                     AND window_start_local_date<=?
                     AND window_end_local_date>=?
                   LIMIT 1""",
                (
                    subject,
                    window.resource_kind,
                    window.through.isoformat(),
                    window.start.isoformat(),
                ),
            ).fetchone()
            if blocking_gap is not None:
                return False
        return True

    def _process_due_gaps(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        request: SyncRequest,
        receipt: SyncReceipt,
        activity_start: date,
        activity_through: date,
        prior_gap_ceiling: int,
    ) -> None:
        """Retry a bounded set of due gaps through the normal resource pipeline."""
        limit = self.config.max_repair_items_per_incremental
        if limit <= 0:
            return
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        gaps = list(
            conn.execute(
                """SELECT id,resource_kind,logical_object_key,
                      window_start_local_date,window_end_local_date,stage
               FROM garmin_sync_gaps
               WHERE id<=?
                 AND (
                     status='open'
                     OR (
                         status='deferred'
                         AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                     )
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM garmin_sync_items item
                     WHERE item.garmin_sync_run_id=?
                       AND item.resource_kind=garmin_sync_gaps.resource_kind
                       AND item.logical_object_key=garmin_sync_gaps.logical_object_key
                 )
               ORDER BY priority DESC,
                        CASE WHEN next_retry_at_utc IS NULL THEN 0 ELSE 1 END,
                        next_retry_at_utc,id
               LIMIT ?""",
                (prior_gap_ceiling, now, run, limit),
            )
        )
        activity_resources = {
            "activity_inventory",
            "activity_summary",
            "activity_fit",
            "activity_details_fallback",
            "activities",
            *ACTIVITY_ENRICHMENT_RESOURCES,
        }
        for gap in gaps:
            still_due = conn.execute(
                """SELECT 1 FROM garmin_sync_gaps
                   WHERE id=? AND (
                       status='open'
                       OR (
                           status='deferred'
                           AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                       )
                   )""",
                (gap["id"], now),
            ).fetchone()
            if still_due is None:
                continue
            try:
                start = date.fromisoformat(gap["window_start_local_date"])
                through = date.fromisoformat(gap["window_end_local_date"])
            except (TypeError, ValueError):
                continue
            if start > through:
                continue
            resource = str(gap["resource_kind"])
            if resource in COLLECTED_HEALTH_RESOURCES:
                scoped = replace(
                    request,
                    resource_kinds=(resource,),
                    activity_ids=(),
                )
                self._health(
                    conn,
                    run,
                    subject,
                    start,
                    through,
                    scoped,
                    receipt,
                )
                continue
            if resource not in activity_resources:
                continue
            logical_key = str(gap["logical_object_key"])
            activity_id = self._activity_id_from_key(logical_key)
            selected_resource = (
                "activity_summary" if resource == "activities" else resource
            )
            scoped = replace(
                request,
                resource_kinds=(selected_resource,),
                activity_ids=(activity_id,) if activity_id else (),
            )
            self._activities(
                conn,
                run,
                subject,
                start if activity_id else activity_start,
                through if activity_id else activity_through,
                scoped,
                receipt,
                selected_resource == "activity_fit",
            )

    @staticmethod
    def _activity_id_from_key(logical_key: str) -> str | None:
        prefix = "garmin:activity:"
        if not logical_key.startswith(prefix):
            return None
        value = logical_key[len(prefix) :].strip()
        return value if value and ":" not in value else None

    def _now_utc(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.astimezone(UTC)

    def _classify(
        self, error: GarminError, *, allows_404: bool = False
    ) -> RetryClassification:
        return classify_garmin_error(
            error,
            allows_404=allows_404,
            inline_retry_after_max_seconds=self.config.inline_retry_after_max_seconds,
            rate_limit_fallback_seconds=self.config.rate_limit_fallback_seconds,
        )

    def _next_retry(self, error: GarminError, attempt: int) -> str:
        seconds = error.retry_after
        if seconds is None:
            # Garmin documents no Retry-After as a long cooldown.  It grows
            # between separate attempts while retaining a bounded value.
            seconds = min(
                86_400,
                self.config.rate_limit_fallback_seconds * (2**attempt),
            )
        return (
            (self._now_utc() + timedelta(seconds=seconds))
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _cooldown_error(
        self,
        conn: sqlite3.Connection | None,
        subject: int | None,
        resource: str | None,
        key: str | None,
    ) -> GarminError | None:
        if conn is None or subject is None or resource is None or key is None:
            return None
        row = conn.execute(
            """SELECT next_retry_at_utc FROM garmin_sync_gaps
               WHERE subject_id=? AND resource_kind=? AND logical_object_key=?
                 AND status='deferred' AND next_retry_at_utc IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (subject, resource, key),
        ).fetchone()
        if row is None:
            return None
        try:
            due = datetime.fromisoformat(
                row["next_retry_at_utc"].replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return GarminError("cooldown_corrupt")
        remaining = (due - self._now_utc()).total_seconds()
        return (
            GarminError(
                "cooldown_active", http_status=429, retry_after=max(1, int(remaining))
            )
            if remaining > 0
            else None
        )

    def _call(
        self,
        fn: Callable[[], Any],
        *,
        conn: sqlite3.Connection | None = None,
        run: int | None = None,
        subject: int | None = None,
        resource: str | None = None,
        key: str | None = None,
        stage: str = "fetch",
        allows_404: bool = False,
    ) -> Any:
        """Execute one provider call with controlled retry and durable attempts."""
        cooldown = self._cooldown_error(conn, subject, resource, key)
        if cooldown is not None:
            raise cooldown
        last: GarminError | None = None
        refreshed = False
        for attempt in range(self.config.max_attempts):
            try:
                if conn is not None and run is not None and resource and key:
                    self.repo.item(conn, run, resource, key, stage, "running")
                if self._last_request is not None:
                    target_interval = (
                        self.config.request_min_interval_ms
                        + self.config.request_interval_jitter_ms * self.rng()
                    ) / 1000
                    # A sleep implementation may return early.  Recheck the
                    # monotonic clock until the actual transport-entry lower
                    # bound is reached, rather than trusting the requested
                    # sleep duration.
                    while True:
                        remaining = target_interval - (
                            self.monotonic() - self._last_request
                        )
                        if remaining <= 0:
                            break
                        self.sleep(remaining)
                # Item persistence can take material time.  Record immediately
                # before transport entry so both successful and failed calls
                # pace from the real provider-call boundary.
                self._last_request = self.monotonic()
                return fn()
            except GarminError as exc:
                last = exc
                # The one-shot live acceptance driver has already completed
                # its only approved refresh.  Its closed adapter sets this
                # flag so no generic retry, implicit 401 login, or fallback
                # can re-enter authentication after data collection begins.
                if getattr(self, "_live_acceptance_no_retry", False):
                    if exc.http_status == 401:
                        raise exc.__class__(
                            "live_acceptance_401_blocked", http_status=401
                        )
                    raise exc
                # A persisted long-rate-limit cooldown is never converted
                # into an inline wait just because less than 120 seconds now
                # remain; the provider call must not be made before its due
                # timestamp.
                if exc.code == "cooldown_active":
                    raise exc
                classification = self._classify(exc, allows_404=allows_404)
                if exc.http_status == 401 and not refreshed:
                    refreshed = True
                    try:
                        self._transport().login()
                    except GarminError:
                        raise GarminError("auth_required", http_status=401) from None
                    continue
                if (
                    classification.status != "retry"
                    or attempt + 1 == self.config.max_attempts
                ):
                    raise exc
                if exc.http_status == 429:
                    # Short Retry-After is honoured precisely; long cooldowns
                    # were rejected by the classification above.
                    self.sleep(
                        float(
                            exc.retry_after
                            if exc.retry_after is not None
                            else self.config.rate_limit_fallback_seconds
                        )
                    )
                else:
                    delay = min(
                        self.config.retry_max_seconds,
                        self.config.retry_base_seconds * (2**attempt) + self.rng(),
                    )
                    self.sleep(delay)
        raise last or GarminError("unknown")

    @staticmethod
    def _canonical_live_acceptance_sha256(document: Mapping[str, Any]) -> str:
        """Hash redacted acceptance JSON excluding its own digest field.

        The canonical payload is UTF-8 JSON with lexicographically sorted keys,
        compact separators, no ASCII escaping, and no non-finite numbers. A
        checkpoint excludes only ``checkpoint_sha256`` and a final result
        excludes only ``result_sha256``; referenced checkpoint digests remain
        part of the final-result payload.
        """
        try:
            payload = json.loads(
                json.dumps(document, allow_nan=False, ensure_ascii=False)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("live_acceptance_not_json") from exc
        kind = payload.get("document_kind")
        if kind == "garmin_live_acceptance_checkpoint":
            payload.pop("checkpoint_sha256", None)
        elif kind == "garmin_live_acceptance_result":
            payload.pop("result_sha256", None)
        elif kind == "garmin_live_auth_refresh_receipt":
            payload.pop("auth_refresh_receipt_sha256", None)
        elif kind == "garmin_live_acceptance_stop":
            payload.pop("stop_sha256", None)
        elif kind == "garmin_live_acceptance_preflight_stop":
            payload.pop("stop_sha256", None)
        else:
            raise ValueError("live_acceptance_document_kind")
        canonical = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _stable_regular_file_sha256(
        path: Path, *, chunk_size: int = 65_536
    ) -> dict[str, Any]:
        """Hash one authority file through a no-follow, stable descriptor."""
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError("live_acceptance_chunk_size_invalid")
        fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_mtime_ns",
            "st_ctime_ns",
        )

        def facts(value: os.stat_result) -> tuple[int, ...]:
            return tuple(int(getattr(value, field)) for field in fields)

        try:
            opened_entry = os.lstat(path)
            if stat.S_ISLNK(opened_entry.st_mode):
                raise _LiveAcceptancePreflightError("stable_file_symlink")
            if not stat.S_ISREG(opened_entry.st_mode):
                raise _LiveAcceptancePreflightError("stable_file_not_regular")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except _LiveAcceptancePreflightError:
            raise
        except FileNotFoundError as exc:
            raise _LiveAcceptancePreflightError("stable_file_missing") from exc
        except OSError as exc:
            raise _LiveAcceptancePreflightError("stable_file_open_failed") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise _LiveAcceptancePreflightError("stable_file_not_regular")
            if facts(opened_entry) != facts(before):
                raise _LiveAcceptancePreflightError("stable_file_replaced")
            remaining = before.st_size
            digest = hashlib.sha256()
            while remaining:
                block = os.read(descriptor, min(chunk_size, remaining))
                if not block:
                    raise _LiveAcceptancePreflightError("stable_file_short_read")
                digest.update(block)
                remaining -= len(block)
            if os.read(descriptor, 1):
                raise _LiveAcceptancePreflightError("stable_file_growth")
            after = os.fstat(descriptor)
            final_entry = os.lstat(path)
            if not stat.S_ISREG(after.st_mode) or stat.S_ISLNK(final_entry.st_mode):
                raise _LiveAcceptancePreflightError("stable_file_not_regular")
            if facts(before) != facts(after):
                raise _LiveAcceptancePreflightError("stable_file_metadata_drift")
            if facts(after) != facts(final_entry):
                raise _LiveAcceptancePreflightError("stable_file_replaced")
            return {"sha256": digest.hexdigest(), "byte_count": before.st_size}
        except _LiveAcceptancePreflightError:
            raise
        except OSError as exc:
            raise _LiveAcceptancePreflightError("stable_file_read_failed") from exc
        finally:
            os.close(descriptor)

    def _make_live_acceptance_preflight_stop(
        self,
        *,
        failure_code: str,
        plan_id: str,
        plan_version: int,
        plan_hash: str,
        attempt_id: str,
        authority_file_count: int,
        authority_byte_count: int,
        authority_aggregate_sha256: str,
    ) -> dict[str, Any]:
        """Build minimal durable evidence available before any auth evidence."""
        document: dict[str, Any] = {
            "schema_version": "1",
            "document_kind": "garmin_live_acceptance_preflight_stop",
            "timezone": "Asia/Hong_Kong",
            "failure_stage": "preflight",
            "failure_code": failure_code,
            "plan_id": plan_id,
            "plan_version": plan_version,
            "plan_hash": plan_hash,
            "attempt_id": attempt_id,
            "authority_file_count": authority_file_count,
            "authority_byte_count": authority_byte_count,
            "authority_aggregate_sha256": authority_aggregate_sha256,
            "provider_entry_count": 0,
            "credential_content_read_count": 0,
            "credential_write_count": 0,
            "production_authority_write_count": 0,
            "stop_sha256": "0" * 64,
        }
        document["stop_sha256"] = self._canonical_live_acceptance_sha256(document)
        return document

    def _run_live_acceptance_preflight(
        self,
        *,
        authority_paths: Mapping[str, Path],
        stop_destination: Path,
        plan_id: str,
        plan_version: int,
        plan_hash: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        """Prove authority files stable or atomically stop before auth access."""
        aggregate, file_count, byte_count = hashlib.sha256(), 0, 0
        failure_code: str | None = None
        try:
            for authority_id in sorted(authority_paths):
                result = self._stable_regular_file_sha256(authority_paths[authority_id])
                aggregate.update(authority_id.encode("utf-8"))
                aggregate.update(b"\0")
                aggregate.update(result["sha256"].encode("ascii"))
                aggregate.update(b"\0")
                aggregate.update(str(result["byte_count"]).encode("ascii"))
                aggregate.update(b"\n")
                file_count += 1
                byte_count += result["byte_count"]
        except _LiveAcceptancePreflightError as exc:
            failure_code = exc.code
        except Exception:
            failure_code = "stable_file_unknown"
        if failure_code is not None:
            stopped = self._make_live_acceptance_preflight_stop(
                failure_code=failure_code,
                plan_id=plan_id,
                plan_version=plan_version,
                plan_hash=plan_hash,
                attempt_id=attempt_id,
                authority_file_count=file_count,
                authority_byte_count=byte_count,
                authority_aggregate_sha256=aggregate.hexdigest(),
            )
            try:
                self._persist_live_acceptance_document(stop_destination, stopped)
            except Exception:
                raise RuntimeError(
                    "live_acceptance_preflight_stop_persist_failed"
                ) from None
            raise RuntimeError("live_acceptance_preflight_failed") from None
        return {
            "authority_file_count": file_count,
            "authority_byte_count": byte_count,
            "authority_aggregate_sha256": aggregate.hexdigest(),
        }

    @staticmethod
    def _live_acceptance_schema() -> dict[str, Any]:
        schema_path = (
            Path(__file__).resolve().parents[3]
            / "harness"
            / "schemas"
            / "garmin_live_acceptance_receipt.schema.json"
        )
        return json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate_live_acceptance_document(self, document: Mapping[str, Any]) -> None:
        """Fail closed unless a redacted checkpoint/result is semantically sound."""
        errors = sorted(
            Draft202012Validator(
                self._live_acceptance_schema(), format_checker=FormatChecker()
            ).iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError("live_acceptance_schema_invalid")
        kind = document["document_kind"]
        digest_key = {
            "garmin_live_acceptance_checkpoint": "checkpoint_sha256",
            "garmin_live_acceptance_result": "result_sha256",
            "garmin_live_auth_refresh_receipt": "auth_refresh_receipt_sha256",
            "garmin_live_acceptance_stop": "stop_sha256",
            "garmin_live_acceptance_preflight_stop": "stop_sha256",
        }[kind]
        if document[digest_key] != self._canonical_live_acceptance_sha256(document):
            raise ValueError("live_acceptance_digest_invalid")
        if kind == "garmin_live_acceptance_checkpoint":
            self._validate_live_acceptance_checkpoint(document)
            return
        if kind == "garmin_live_acceptance_result":
            self._validate_live_acceptance_result(document)
            return
        if kind == "garmin_live_acceptance_stop":
            self._validate_live_acceptance_stop(document)
            return
        if kind == "garmin_live_acceptance_preflight_stop":
            self._validate_live_acceptance_preflight_stop(document)
            return
        self._validate_live_auth_refresh_document(document)

    @staticmethod
    def _validate_live_acceptance_checkpoint(document: Mapping[str, Any]) -> None:
        operation = document["operation"]
        for range_name in ("requested_local_dates", "effective_local_dates"):
            local_range = operation[range_name]
            start, through = local_range["from"], local_range["through"]
            # FormatChecker has already established the non-null values as
            # ISO calendar dates, whose fixed-width lexical order is calendar
            # order. Keeping this comparison string-based avoids reparsing a
            # separate date representation after schema validation.
            if start is not None and through is not None and start > through:
                raise ValueError("live_acceptance_date_range_reversed")
        ordinal = operation["ordinal"]
        previous_digest = document["previous_checkpoint_sha256"]
        if (ordinal == 1) != (previous_digest == "0" * 64):
            raise ValueError("live_acceptance_checkpoint_sequence")
        prior_count = document["prior_provider_entry_count"]
        total_count = document["provider_entry_count"]
        if total_count < prior_count:
            raise ValueError("live_acceptance_provider_count_regressed")
        intervals = document["adjacent_controlled_provider_intervals_ns"]
        if len(intervals) != max(total_count - 1, 0):
            raise ValueError("live_acceptance_interval_count")
        minimum = document["configured_minimum_interval_ns"]
        if any(interval < minimum for interval in intervals):
            raise ValueError("live_acceptance_interval_subminimum")
        ledger = document["controlled_provider_entry_ledger"]
        if len(ledger) != total_count:
            raise ValueError("live_acceptance_ledger_count")
        if [entry["ordinal"] for entry in ledger] != list(range(1, total_count + 1)):
            raise ValueError("live_acceptance_ledger_ordinal")
        if [
            ledger[index]["monotonic_ns"] - ledger[index - 1]["monotonic_ns"]
            for index in range(1, len(ledger))
        ] != intervals:
            raise ValueError("live_acceptance_ledger_intervals")
        bounds = operation["provider_entry_ordinals"]
        first, last = bounds["first"], bounds["last"]
        if total_count == prior_count:
            if first is not None or last is not None:
                raise ValueError("live_acceptance_empty_entry_bounds")
            return
        if first != prior_count + 1 or last != total_count or first > last:
            raise ValueError("live_acceptance_entry_bounds")

    def _validate_live_acceptance_result(self, document: Mapping[str, Any]) -> None:
        checkpoints = document["checkpoints"]
        expected_modes = ("auth", "incremental", "incremental", "snapshot", "audit")
        previous_digest = "0" * 64
        previous_count = 0
        previous_intervals: list[int] = []
        for expected_ordinal, (expected_mode, checkpoint) in enumerate(
            zip(expected_modes, checkpoints, strict=True), start=1
        ):
            self._validate_live_acceptance_document(checkpoint)
            if checkpoint["operation"]["ordinal"] != expected_ordinal:
                raise ValueError("live_acceptance_checkpoint_ordinal")
            if checkpoint["operation"]["mode"] != expected_mode:
                raise ValueError("live_acceptance_checkpoint_mode")
            if checkpoint["previous_checkpoint_sha256"] != previous_digest:
                raise ValueError("live_acceptance_checkpoint_chain")
            if checkpoint["prior_provider_entry_count"] != previous_count:
                raise ValueError("live_acceptance_checkpoint_prefix")
            if (
                checkpoint["configured_minimum_interval_ns"]
                != document["configured_minimum_interval_ns"]
            ):
                raise ValueError("live_acceptance_checkpoint_minimum")
            intervals = checkpoint["adjacent_controlled_provider_intervals_ns"]
            if intervals[: len(previous_intervals)] != previous_intervals:
                raise ValueError("live_acceptance_interval_history")
            if checkpoint["controlled_provider_entry_ledger"][:previous_count] != (
                checkpoints[expected_ordinal - 2]["controlled_provider_entry_ledger"]
                if expected_ordinal > 1
                else []
            ):
                raise ValueError("live_acceptance_ledger_history")
            previous_digest = checkpoint["checkpoint_sha256"]
            previous_count = checkpoint["provider_entry_count"]
            previous_intervals = intervals
        if document["final_checkpoint_sha256"] != previous_digest:
            raise ValueError("live_acceptance_final_checkpoint")
        if document["provider_entry_count"] != previous_count:
            raise ValueError("live_acceptance_final_provider_count")
        intervals = document["adjacent_controlled_provider_intervals_ns"]
        if intervals != checkpoints[-1]["adjacent_controlled_provider_intervals_ns"]:
            raise ValueError("live_acceptance_final_interval_prefix")
        if (
            document["controlled_provider_entry_ledger"]
            != checkpoints[-1]["controlled_provider_entry_ledger"]
        ):
            raise ValueError("live_acceptance_final_ledger_prefix")
        failure = document["failure_evidence"]
        if (
            failure["outcome"] != "none"
            or failure["last_checkpoint_preserved"] is not None
        ):
            raise ValueError("live_acceptance_result_failure_evidence")
        auth = document["auth_refresh"]
        counts = auth["counts"]
        if (
            counts["refresh_provider_entry_count"] != 1
            or counts["credential_replace_count"] != 1
            or counts["social_profile_http_count"] != 1
            or counts["user_settings_http_count"] != 1
        ):
            raise ValueError("live_acceptance_auth_count")
        if not all(auth["credential_authority"].values()):
            raise ValueError("live_acceptance_auth_authority")
        self._validate_auth_progress(auth["progress"])
        if not all(progress["completed"] for progress in auth["progress"].values()):
            raise ValueError("live_acceptance_auth_progress")
        if any(
            counts[name] != 0
            for name in (
                "password_login_attempt_count",
                "mfa_attempt_count",
                "credential_fallback_attempt_count",
                "library_token_dump_attempt_count",
                "legacy_refresh_attempt_count",
                "implicit_401_refresh_attempt_count",
                "second_refresh_attempt_count",
                "auth_profile_retry_attempt_count",
                "unreviewed_profile_attempt_count",
            )
        ):
            raise ValueError("live_acceptance_auth_blocked_path")
        drift = document["drift_evidence"]
        if any(
            drift[name] != 0
            for name in (
                "stable_repeat_violation_count",
                "changed_revision_violation_count",
                "changed_current_provenance_violation_count",
            )
        ):
            raise ValueError("live_acceptance_drift_violation")

    @staticmethod
    def _validate_live_acceptance_preflight_stop(document: Mapping[str, Any]) -> None:
        """Pre-auth stops must never claim auth or authority side effects."""
        if document["failure_stage"] != "preflight":
            raise ValueError("live_acceptance_preflight_stage")
        if any(
            document[name] != 0
            for name in (
                "provider_entry_count",
                "credential_content_read_count",
                "credential_write_count",
                "production_authority_write_count",
            )
        ):
            raise ValueError("live_acceptance_preflight_nonzero_boundary")

    def _validate_live_acceptance_stop(self, document: Mapping[str, Any]) -> None:
        ledger = document["controlled_provider_entry_ledger"]
        count = document["provider_entry_count"]
        if len(ledger) != count:
            raise ValueError("live_acceptance_stop_ledger_count")
        intervals = document["adjacent_controlled_provider_intervals_ns"]
        if len(intervals) != max(count - 1, 0):
            raise ValueError("live_acceptance_stop_interval_count")
        if any(
            interval < document["configured_minimum_interval_ns"]
            for interval in intervals
        ):
            raise ValueError("live_acceptance_stop_interval_subminimum")
        if [entry["ordinal"] for entry in ledger] != list(range(1, count + 1)):
            raise ValueError("live_acceptance_stop_ledger_ordinal")
        if [
            ledger[index]["monotonic_ns"] - ledger[index - 1]["monotonic_ns"]
            for index in range(1, len(ledger))
        ] != intervals:
            raise ValueError("live_acceptance_stop_ledger_intervals")
        checkpoints = document["checkpoints"]
        previous_digest = "0" * 64
        previous_count = 0
        for checkpoint in checkpoints:
            self._validate_live_acceptance_checkpoint(checkpoint)
            if checkpoint["previous_checkpoint_sha256"] != previous_digest:
                raise ValueError("live_acceptance_stop_checkpoint_chain")
            if checkpoint["prior_provider_entry_count"] != previous_count:
                raise ValueError("live_acceptance_stop_checkpoint_prefix")
            previous_digest = checkpoint["checkpoint_sha256"]
            previous_count = checkpoint["provider_entry_count"]
        if ledger[:previous_count] != (
            checkpoints[-1]["controlled_provider_entry_ledger"] if checkpoints else []
        ):
            raise ValueError("live_acceptance_stop_checkpoint_ledger")
        auth = document["auth_refresh"]
        if not all(auth["credential_authority"].values()) or not all(
            progress["completed"] for progress in auth["progress"].values()
        ):
            raise ValueError("live_acceptance_stop_auth_authority")
        if any(
            auth["counts"][name] != expected
            for name, expected in (
                ("refresh_provider_entry_count", 1),
                ("credential_replace_count", 1),
                ("social_profile_http_count", 1),
                ("user_settings_http_count", 1),
                ("cached_identity_http_count", 0),
                ("password_login_attempt_count", 0),
                ("mfa_attempt_count", 0),
                ("credential_fallback_attempt_count", 0),
                ("library_token_dump_attempt_count", 0),
                ("legacy_refresh_attempt_count", 0),
                ("implicit_401_refresh_attempt_count", 0),
                ("second_refresh_attempt_count", 0),
                ("auth_profile_retry_attempt_count", 0),
                ("unreviewed_profile_attempt_count", 0),
            )
        ):
            raise ValueError("live_acceptance_stop_auth_counts")

    def _persist_live_acceptance_document(
        self, destination: Path, document: Mapping[str, Any]
    ) -> None:
        """Atomically persist a previously validated redacted receipt document."""
        self._validate_live_acceptance_document(document)
        payload = (
            json.dumps(
                document,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        parent = destination.parent
        if destination.is_symlink():
            raise ValueError("live_acceptance_destination_symlink")
        ancestor = parent
        while True:
            if ancestor.is_symlink():
                raise ValueError("live_acceptance_ancestor_symlink")
            if ancestor == ancestor.parent:
                break
            ancestor = ancestor.parent
        directory_flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(parent, directory_flags)
        temporary_name = f".{destination.name}.{uuid.uuid4().hex}.tmp"
        temporary_fd: int | None = None
        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(temporary_fd, 0o600)
            written = 0
            while written < len(payload):
                count = os.write(temporary_fd, payload[written:])
                if count <= 0:
                    raise OSError("live_acceptance_short_write")
                written += count
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace(
                temporary_name,
                destination.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(directory_fd)

    @staticmethod
    def _token_authority_snapshot(destination: Path) -> dict[str, Any]:
        """Return private comparison facts for an existing, owner-only token.

        The values are intentionally only for local comparison.  Callers must
        convert them to booleans before a receipt is persisted: token hashes,
        paths, names, ownership ids and credential bytes are never evidence.
        """
        parent = destination.parent
        ancestor = parent
        while True:
            if os.path.islink(ancestor):
                raise ValueError("live_auth_token_ancestor_symlink")
            if ancestor == ancestor.parent:
                break
            ancestor = ancestor.parent
        parent_stat = os.stat(parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_mode & 0o777 != 0o700
        ):
            raise ValueError("live_auth_token_parent_invalid")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        token_fd = os.open(destination, flags)
        try:
            token_stat = os.fstat(token_fd)
            if (
                not stat.S_ISREG(token_stat.st_mode)
                or token_stat.st_mode & 0o777 != 0o600
            ):
                raise ValueError("live_auth_token_permissions_invalid")
            content = bytearray()
            while True:
                block = os.read(token_fd, 65_536)
                if not block:
                    break
                content.extend(block)
                if len(content) > 1_048_576:
                    raise ValueError("live_auth_token_too_large")
        finally:
            os.close(token_fd)
        structure: list[tuple[str, int, int, int]] = []
        for root, directories, files in os.walk(parent, followlinks=False):
            entries = sorted((*directories, *files))
            for name in entries:
                candidate = Path(root) / name
                entry = os.lstat(candidate)
                if os.path.islink(candidate):
                    raise ValueError("live_auth_token_structure_symlink")
                structure.append(
                    (
                        str(candidate.relative_to(parent)),
                        entry.st_mode,
                        entry.st_uid,
                        entry.st_gid,
                    )
                )
        return {
            "parent_device": parent_stat.st_dev,
            "parent_inode": parent_stat.st_ino,
            "parent_uid": parent_stat.st_uid,
            "parent_gid": parent_stat.st_gid,
            "parent_mode": parent_stat.st_mode & 0o777,
            "token_uid": token_stat.st_uid,
            "token_gid": token_stat.st_gid,
            "token_mode": token_stat.st_mode & 0o777,
            "token_device": token_stat.st_dev,
            "token_inode": token_stat.st_ino,
            "token_size": token_stat.st_size,
            "structure_sha256": hashlib.sha256(
                json.dumps(
                    structure,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _credential_authority_facts(
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        *,
        reloaded_nonexpiring: bool,
    ) -> dict[str, bool]:
        """Reduce secret-bearing authority snapshots to redacted booleans."""
        return {
            "token_path_unchanged": True,
            "token_directory_unchanged": (
                before["parent_device"] == after["parent_device"]
                and before["parent_inode"] == after["parent_inode"]
            ),
            "owner_unchanged": (
                before["parent_uid"] == after["parent_uid"]
                and before["token_uid"] == after["token_uid"]
            ),
            "group_unchanged": (
                before["parent_gid"] == after["parent_gid"]
                and before["token_gid"] == after["token_gid"]
            ),
            "directory_mode_0700": (
                before["parent_mode"] == after["parent_mode"] == 0o700
            ),
            "file_mode_0600": before["token_mode"] == after["token_mode"] == 0o600,
            "structure_unchanged": before["structure_sha256"]
            == after["structure_sha256"],
            "content_changed_exactly_once": (
                before["content_sha256"] != after["content_sha256"]
            ),
            "reloaded_nonexpiring": reloaded_nonexpiring,
        }

    @staticmethod
    def _preflight_live_acceptance_destination(destination: Path) -> None:
        """Check a fresh receipt target without creating or following links.

        The subsequent prepared receipt is the durability probe before the
        sole provider entry; this preflight deliberately does not create a
        disposable file that could obscure the actual evidence sequence.
        """
        if destination.is_symlink() or destination.exists():
            raise ValueError("live_auth_receipt_destination_symlink")
        ancestor = destination.parent
        while True:
            if ancestor.is_symlink():
                raise ValueError("live_auth_receipt_ancestor_symlink")
            if ancestor == ancestor.parent:
                break
            ancestor = ancestor.parent
        directory_fd = os.open(
            destination.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            directory_stat = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise ValueError("live_auth_receipt_parent_invalid")
            if not os.access(destination.parent, os.W_OK):
                raise ValueError("live_auth_receipt_destination_unwritable")
        finally:
            os.close(directory_fd)

    @staticmethod
    def _atomic_replace_existing_token(
        destination: Path,
        serialized: bytes,
        *,
        expected_token_identity: tuple[int, int, int, int, int, int] | None = None,
        stage_callback: Any = None,
    ) -> None:
        """Replace the one existing token with no-follow, fsync and rename.

        The refreshed serialization never escapes this method.  It is not
        returned or logged, preventing an otherwise useful digest from turning
        into a durable token correlator.
        """
        if not isinstance(serialized, bytes) or not serialized:
            raise ValueError("live_auth_invalid_serialization")
        before = GarminCollectionBase._token_authority_snapshot(destination)
        observed_identity = (
            before["token_device"],
            before["token_inode"],
            before["token_size"],
            before["token_mode"],
            before["token_uid"],
            before["token_gid"],
        )
        if (
            expected_token_identity is not None
            and observed_identity != expected_token_identity
        ):
            raise _LiveAuthAtomicReplaceError("token_revalidated", replaced=False)
        parent = destination.parent
        directory_fd = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        temporary_name = f".{destination.name}.{uuid.uuid4().hex}.tmp"
        temporary_fd: int | None = None
        renamed = False
        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(temporary_fd, 0o600)
            os.fchown(temporary_fd, before["token_uid"], before["token_gid"])
            written = 0
            while written < len(serialized):
                count = os.write(temporary_fd, serialized[written:])
                if count <= 0:
                    raise OSError("live_auth_token_short_write")
                written += count
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace(
                temporary_name,
                destination.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            renamed = True
            try:
                if stage_callback is not None:
                    stage_callback("parent_fsync_entered")
                os.fsync(directory_fd)
                if stage_callback is not None:
                    stage_callback("parent_fsync_completed")
            except Exception as exc:
                raise _LiveAuthAtomicReplaceError(
                    "parent_fsync", replaced=True
                ) from exc
        except _LiveAuthAtomicReplaceError:
            raise
        except Exception as exc:
            raise _LiveAuthAtomicReplaceError("rotation", replaced=renamed) from exc
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(directory_fd)

    @staticmethod
    def _empty_auth_refresh_counts() -> dict[str, int]:
        return {
            "refresh_provider_entry_count": 0,
            "credential_replace_count": 0,
            "social_profile_http_count": 0,
            "user_settings_http_count": 0,
            "cached_identity_http_count": 0,
            "password_login_attempt_count": 0,
            "mfa_attempt_count": 0,
            "credential_fallback_attempt_count": 0,
            "library_token_dump_attempt_count": 0,
            "legacy_refresh_attempt_count": 0,
            "implicit_401_refresh_attempt_count": 0,
            "second_refresh_attempt_count": 0,
            "auth_profile_retry_attempt_count": 0,
            "unreviewed_profile_attempt_count": 0,
        }

    @staticmethod
    def _empty_auth_refresh_progress() -> dict[str, dict[str, bool]]:
        """Return only redacted, monotonic auth boundary state."""
        return {
            name: {"attempted": False, "entered": False, "completed": False}
            for name in (
                "precondition",
                "prepared_receipt",
                "refresh",
                "credential_replace",
                "parent_fsync",
                "reload",
                "authority_recheck",
                "rotation_checkpoint_receipt",
                "social_profile",
                "cached_identity",
                "user_settings",
                "final_receipt",
            )
        }

    @staticmethod
    def _auth_phase_entered(progress: dict[str, dict[str, bool]], name: str) -> None:
        progress[name]["attempted"] = True
        progress[name]["entered"] = True

    @staticmethod
    def _auth_phase_completed(progress: dict[str, dict[str, bool]], name: str) -> None:
        GarminCollectionBase._auth_phase_entered(progress, name)
        progress[name]["completed"] = True

    @staticmethod
    def _validate_auth_progress(progress: Mapping[str, Any]) -> None:
        for phase in progress.values():
            if phase["completed"] and not phase["entered"]:
                raise ValueError("live_auth_progress_completed_without_entry")
            if phase["entered"] and not phase["attempted"]:
                raise ValueError("live_auth_progress_entry_without_attempt")

    def _make_live_auth_refresh_document(
        self,
        *,
        status: str,
        failure_stage: str,
        counts: Mapping[str, int],
        authority: Mapping[str, bool],
        progress: Mapping[str, Mapping[str, bool]],
        previous_digest: str,
    ) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": "1",
            "document_kind": "garmin_live_auth_refresh_receipt",
            "status": status,
            "failure_stage": failure_stage,
            "refresh_client_distribution": "python-garminconnect-0.3.6",
            "counts": dict(counts),
            "ordering": {
                "refresh_before_credential_replace": True,
                "credential_replaced_before_profile": True,
                "checkpoint_persisted_before_profile": True,
                "first_profile_stops_second_on_error": True,
                "cached_identity_zero_http": True,
            },
            "credential_authority": dict(authority),
            "progress": {name: dict(state) for name, state in progress.items()},
            "previous_auth_receipt_sha256": previous_digest,
            "auth_refresh_receipt_sha256": "0" * 64,
        }
        document["auth_refresh_receipt_sha256"] = (
            self._canonical_live_acceptance_sha256(document)
        )
        return document

    @staticmethod
    def _validate_live_auth_refresh_document(document: Mapping[str, Any]) -> None:
        counts = document["counts"]
        progress = document["progress"]
        GarminCollectionBase._validate_auth_progress(progress)
        for count_name, phase_name in (
            ("refresh_provider_entry_count", "refresh"),
            ("social_profile_http_count", "social_profile"),
            ("user_settings_http_count", "user_settings"),
        ):
            if bool(counts[count_name]) != bool(progress[phase_name]["entered"]):
                raise ValueError("live_auth_count_progress_mismatch")
        if (
            counts["credential_replace_count"]
            and not progress["credential_replace"]["completed"]
        ):
            raise ValueError("live_auth_rotation_progress_mismatch")
        if document["status"] == "prepared":
            if any(value != 0 for value in counts.values()):
                raise ValueError("live_auth_prepared_counts")
            if not progress["precondition"]["completed"]:
                raise ValueError("live_auth_prepared_precondition")
            if not (
                progress["prepared_receipt"]["entered"]
                and not progress["prepared_receipt"]["completed"]
            ):
                raise ValueError("live_auth_prepared_receipt_progress")
            return
        if document["status"] == "stopped":
            if (
                counts["social_profile_http_count"]
                or counts["user_settings_http_count"]
            ) and counts["credential_replace_count"] != 1:
                raise ValueError("live_auth_stop_profile_before_rotation")
            if counts["user_settings_http_count"] > counts["social_profile_http_count"]:
                raise ValueError("live_auth_profile_order")
            return
        if counts["refresh_provider_entry_count"] != 1:
            raise ValueError("live_auth_refresh_count")
        if counts["credential_replace_count"] != 1:
            raise ValueError("live_auth_rotation_count")
        if document["status"] == "rotation_checkpoint":
            if (
                counts["social_profile_http_count"]
                or counts["user_settings_http_count"]
            ):
                raise ValueError("live_auth_checkpoint_future_profile_count")
            if not all(
                progress[name]["completed"]
                for name in (
                    "precondition",
                    "prepared_receipt",
                    "refresh",
                    "credential_replace",
                    "parent_fsync",
                    "reload",
                    "authority_recheck",
                )
            ):
                raise ValueError("live_auth_checkpoint_progress")
            if not (
                progress["rotation_checkpoint_receipt"]["entered"]
                and not progress["rotation_checkpoint_receipt"]["completed"]
            ):
                raise ValueError("live_auth_checkpoint_receipt_progress")
            return
        if document["status"] == "succeeded" and (
            counts["social_profile_http_count"] != 1
            or counts["user_settings_http_count"] != 1
        ):
            raise ValueError("live_auth_final_profile_count")
        if document["status"] == "succeeded" and not all(
            document["credential_authority"].values()
        ):
            raise ValueError("live_auth_final_authority")
        if document["status"] == "succeeded" and not all(
            progress[name]["completed"]
            for name in (
                "precondition",
                "prepared_receipt",
                "refresh",
                "credential_replace",
                "parent_fsync",
                "reload",
                "authority_recheck",
                "rotation_checkpoint_receipt",
                "social_profile",
                "cached_identity",
                "user_settings",
            )
        ):
            raise ValueError("live_auth_final_progress")
        if document["status"] == "succeeded" and not (
            progress["final_receipt"]["entered"]
            and not progress["final_receipt"]["completed"]
        ):
            raise ValueError("live_auth_final_receipt_progress")
        if counts["user_settings_http_count"] > counts["social_profile_http_count"]:
            raise ValueError("live_auth_profile_order")

    def _persist_live_auth_refresh_receipt(
        self, destination: Path, document: Mapping[str, Any]
    ) -> None:
        """Validate and atomically persist redacted, observed auth evidence."""
        self._persist_live_acceptance_document(destination, document)

    def _run_verified_live_auth_refresh(
        self,
        *,
        token_path: Path,
        load_token_state: Any,
        refresh_di_token: Any,
        serialize_refreshed: Any,
        prepared_destination: Path,
        checkpoint_destination: Path,
        final_destination: Path,
        stop_destination: Path,
        observed_counts: Any,
        social_profile: Any,
        cache_identity: Any,
        user_settings: Any,
    ) -> dict[str, Any]:
        """Execute the non-retrying refresh/profile boundary from observed state.

        ``load_token_state`` is called before and after replacement by the
        driver that owns the pinned client.  It must derive the three local
        preconditions from a no-follow token load; the public API deliberately
        contains no caller-supplied auth booleans.
        """
        empty_counts = self._empty_auth_refresh_counts()
        no_authority = {
            "token_path_unchanged": False,
            "token_directory_unchanged": False,
            "owner_unchanged": False,
            "group_unchanged": False,
            "directory_mode_0700": False,
            "file_mode_0600": False,
            "structure_unchanged": False,
            "content_changed_exactly_once": False,
            "reloaded_nonexpiring": False,
        }
        progress = self._empty_auth_refresh_progress()
        destinations = (
            prepared_destination,
            checkpoint_destination,
            final_destination,
            stop_destination,
        )
        if len({str(destination.absolute()) for destination in destinations}) != len(
            destinations
        ):
            raise ValueError("live_auth_receipt_destinations_not_distinct")
        for destination in destinations:
            self._preflight_live_acceptance_destination(destination)

        def persist_stopped(
            stage: str,
            *,
            counts: Mapping[str, int],
            authority: Mapping[str, bool],
            previous_digest: str,
        ) -> None:
            stopped = self._make_live_auth_refresh_document(
                status="stopped",
                failure_stage=stage,
                counts=counts,
                authority=authority,
                progress=progress,
                previous_digest=previous_digest,
            )
            try:
                self._persist_live_auth_refresh_receipt(stop_destination, stopped)
            except Exception:
                raise RuntimeError("live_auth_stop_persist_failed") from None

        required = (
            "proactive_expiring",
            "has_di_refresh_credential",
            "has_di_client_identity",
        )
        before: Mapping[str, Any] | None = None
        authority: Mapping[str, bool] = no_authority
        self._auth_phase_entered(progress, "precondition")
        try:
            before = self._token_authority_snapshot(token_path)
            initial = load_token_state()
            if not isinstance(initial, Mapping) or any(
                initial.get(name) is not True for name in required
            ):
                raise ValueError("live_auth_refresh_precondition_failed")
            authority = {
                "token_path_unchanged": True,
                "token_directory_unchanged": True,
                "owner_unchanged": True,
                "group_unchanged": True,
                "directory_mode_0700": True,
                "file_mode_0600": True,
                "structure_unchanged": True,
                "content_changed_exactly_once": False,
                "reloaded_nonexpiring": False,
            }
            self._auth_phase_completed(progress, "precondition")
        except Exception:
            persist_stopped(
                "preflight",
                counts=empty_counts,
                authority=authority,
                previous_digest="0" * 64,
            )
            raise RuntimeError("live_auth_refresh_precondition_failed") from None

        self._auth_phase_entered(progress, "prepared_receipt")
        prepared = self._make_live_auth_refresh_document(
            status="prepared",
            failure_stage="none",
            counts=empty_counts,
            authority=authority,
            progress=progress,
            previous_digest="0" * 64,
        )
        try:
            self._persist_live_auth_refresh_receipt(prepared_destination, prepared)
            self._auth_phase_completed(progress, "prepared_receipt")
        except Exception:
            persist_stopped(
                "prepared_receipt_persist",
                counts=empty_counts,
                authority=authority,
                previous_digest="0" * 64,
            )
            raise RuntimeError("live_auth_prepared_receipt_failed") from None

        checkpoint: Mapping[str, Any] | None = None
        rotation_complete = False
        checkpoint_persisted = False
        rotation_stage = "refresh"
        try:
            self._auth_phase_entered(progress, "refresh")
            refresh_di_token()
            self._auth_phase_completed(progress, "refresh")
            if dict(observed_counts())["refresh_provider_entry_count"] != 1:
                raise ValueError("live_auth_refresh_entry_unobserved")
            rotation_stage = "rotation"
            serialized = serialize_refreshed()
            self._auth_phase_entered(progress, "credential_replace")

            def token_stage(event: str) -> None:
                if event == "parent_fsync_entered":
                    self._auth_phase_entered(progress, "parent_fsync")
                    return
                if event == "parent_fsync_completed":
                    self._auth_phase_completed(progress, "parent_fsync")
                    return
                raise ValueError("live_auth_atomic_stage")

            try:
                self._atomic_replace_existing_token(
                    token_path,
                    serialized,
                    expected_token_identity=(
                        before["token_device"],
                        before["token_inode"],
                        before["token_size"],
                        before["token_mode"],
                        before["token_uid"],
                        before["token_gid"],
                    ),
                    stage_callback=token_stage,
                )
            except _LiveAuthAtomicReplaceError as exc:
                if exc.replaced:
                    rotation_complete = True
                    self._auth_phase_completed(progress, "credential_replace")
                    rotation_stage = exc.stage
                    after = self._token_authority_snapshot(token_path)
                    authority = self._credential_authority_facts(
                        before, after, reloaded_nonexpiring=False
                    )
                else:
                    rotation_stage = exc.stage
                raise
            rotation_complete = True
            self._auth_phase_completed(progress, "credential_replace")
            rotation_stage = "reload"
            self._auth_phase_entered(progress, "reload")
            after = self._token_authority_snapshot(token_path)
            authority = self._credential_authority_facts(
                before, after, reloaded_nonexpiring=False
            )
            reloaded = load_token_state()
            if not isinstance(reloaded, Mapping) or (
                reloaded.get("proactive_expiring") is not False
                or reloaded.get("has_di_refresh_credential") is not True
                or reloaded.get("has_di_client_identity") is not True
            ):
                raise ValueError("live_auth_reload_expiry_failed")
            self._auth_phase_completed(progress, "reload")
            rotation_stage = "authority_recheck"
            self._auth_phase_entered(progress, "authority_recheck")
            authority = self._credential_authority_facts(
                before, after, reloaded_nonexpiring=True
            )
            if not all(authority.values()):
                raise ValueError("live_auth_authority_recheck_failed")
            self._auth_phase_completed(progress, "authority_recheck")
            rotation_stage = "checkpoint_persist"
            counts = dict(observed_counts())
            counts["credential_replace_count"] = 1
            self._auth_phase_entered(progress, "rotation_checkpoint_receipt")
            checkpoint = self._make_live_auth_refresh_document(
                status="rotation_checkpoint",
                failure_stage="none",
                counts=counts,
                authority=authority,
                progress=progress,
                previous_digest=prepared["auth_refresh_receipt_sha256"],
            )
            self._persist_live_auth_refresh_receipt(checkpoint_destination, checkpoint)
            checkpoint_persisted = True
            self._auth_phase_completed(progress, "rotation_checkpoint_receipt")
        except Exception:
            stopped_counts = dict(observed_counts())
            if rotation_complete:
                stopped_counts["credential_replace_count"] = 1
            persist_stopped(
                rotation_stage,
                counts=stopped_counts,
                authority=authority,
                previous_digest=(
                    checkpoint["auth_refresh_receipt_sha256"]
                    if checkpoint_persisted and checkpoint is not None
                    else prepared["auth_refresh_receipt_sha256"]
                ),
            )
            raise RuntimeError("live_auth_rotation_failed") from None
        try:
            self._auth_phase_entered(progress, "social_profile")
            social_payload = social_profile()
            self._auth_phase_completed(progress, "social_profile")
            counts = dict(observed_counts())
            counts["credential_replace_count"] = 1
        except Exception:
            persist_stopped(
                "social_profile",
                counts={**dict(observed_counts()), "credential_replace_count": 1},
                authority=authority,
                previous_digest=checkpoint["auth_refresh_receipt_sha256"],
            )
            raise RuntimeError("live_auth_social_profile_failed") from None
        try:
            self._auth_phase_entered(progress, "cached_identity")
            cache_identity(social_payload)
            if dict(observed_counts())["cached_identity_http_count"] != 0:
                raise ValueError("live_auth_cached_identity_http")
            self._auth_phase_completed(progress, "cached_identity")
        except Exception:
            persist_stopped(
                "cached_identity",
                counts={**dict(observed_counts()), "credential_replace_count": 1},
                authority=authority,
                previous_digest=checkpoint["auth_refresh_receipt_sha256"],
            )
            raise RuntimeError("live_auth_cached_identity_failed") from None
        try:
            self._auth_phase_entered(progress, "user_settings")
            user_settings()
            self._auth_phase_completed(progress, "user_settings")
            counts = dict(observed_counts())
            counts["credential_replace_count"] = 1
        except Exception:
            persist_stopped(
                "user_settings",
                counts={**dict(observed_counts()), "credential_replace_count": 1},
                authority=authority,
                previous_digest=checkpoint["auth_refresh_receipt_sha256"],
            )
            raise RuntimeError("live_auth_user_settings_failed") from None
        self._auth_phase_entered(progress, "final_receipt")
        final = self._make_live_auth_refresh_document(
            status="succeeded",
            failure_stage="none",
            counts=counts,
            authority=authority,
            progress=progress,
            previous_digest=checkpoint["auth_refresh_receipt_sha256"],
        )
        try:
            self._persist_live_auth_refresh_receipt(final_destination, final)
            self._auth_phase_completed(progress, "final_receipt")
        except Exception:
            persist_stopped(
                "final_receipt_persist",
                counts=counts,
                authority=authority,
                previous_digest=checkpoint["auth_refresh_receipt_sha256"],
            )
            raise RuntimeError("live_auth_final_receipt_failed") from None
        return {
            "prepared_receipt": prepared,
            "rotation_checkpoint": checkpoint,
            "final_receipt": final,
            "counts": counts,
            "authority": authority,
            "progress": progress,
        }

    _ACCOUNT_BASIC_RESOURCES = ("user_profile", "user_profile_settings", "devices")
    _ACCOUNT_B1_RESOURCES = (
        "primary_device",
        "device_settings",
        "device_last_used",
        "personal_records",
        "cycling_ftp",
        "pregnancy",
    )
    _PROFILE_SETTING_FIELDS = {
        "measurementSystem",
        "timeFormat",
        "weekStartDay",
        "heartRateMethod",
    }
