"""Collection lifecycle, locking, retries and provider-call control."""
from __future__ import annotations

from .contracts import *  # noqa: F403
from .repository import GarminRepository

class GarminCollectionBase:
    def __init__(self, config: GarminConfig, transport: GarminTransport | None = None, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] = lambda: datetime.now(TZ), monotonic: Callable[[], float] = time.monotonic, rng: Callable[[], float] | None = None) -> None:
        self.config, self.transport, self.repo, self.sleep, self.clock, self.monotonic = config, transport, GarminRepository(config), sleep, clock, monotonic
        self.rng = rng or random.Random().random
        self._last_request: float | None = None

    def execute(self, request: SyncRequest) -> SyncReceipt:
        if request.invocation_id is None: request=replace(request,invocation_id=f"garmin-{uuid.uuid4()}")
        receipt = SyncReceipt(mode=request.mode, requested_range={"from": request.health_from_local_date, "through": request.through_local_date or request.snapshot_local_date}, effective_range={"from": None, "through": None})
        self._validate(request)
        if request.mode == "status": return self._validated_receipt(self._status(receipt))
        if request.mode == "auth": return self._validated_receipt(self._auth(receipt))
        lock = self.config.state_root / "locks" / "garmin.lock"; lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not self._recover_stale_lock(lock, request.invocation_id):
                receipt.status, receipt.completed_at_utc = "lock_busy", utc_now(); return self._validated_receipt(receipt)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, stable_json({"pid": os.getpid(), "invocation_id": request.invocation_id, "started_at_utc": receipt.started_at_utc}))
            os.fsync(fd)
            return self._validated_receipt(self._execute_locked(request, receipt))
        finally:
            os.close(fd); lock.unlink(missing_ok=True)

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
            payload=json.loads(lock.read_text()); pid=int(payload["pid"]); invocation_id=payload.get("invocation_id")
            os.kill(pid, 0); return False
        except ProcessLookupError:
            pass
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return False
        conn=self.repo.connect()
        try:
            active=conn.execute("SELECT 1 FROM garmin_sync_runs WHERE invocation_id=? AND status='started'",(invocation_id,)).fetchone() if invocation_id else None
            if active and requested_invocation_id != invocation_id:
                return False
        finally: conn.close()
        lock.unlink(missing_ok=True); return True

    def _execute_locked(self, request: SyncRequest, receipt: SyncReceipt) -> SyncReceipt:
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
                conn, subject, self.config.region,
            )
            run = self.repo.start_run(conn, request, subject, receipt)
            if receipt.status != "started": return receipt
            # Reparse and reconcile are deliberately offline operations.  In
            # particular they must remain usable while a token is expired or
            # Garmin is unavailable; the immutable raw object is the input.
            repair_strategy = self._repair_strategy(conn, subject, request, receipt)
            offline_repair = request.mode == "repair" and repair_strategy in {"reparse", "reconcile"}
            if request.mode == "repair" and repair_strategy == "deferred":
                receipt.status = "deferred"
                self.repo.finish_run(conn, run, receipt, None, None)
                return receipt
            if not offline_repair:
                identity = conn.execute("SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND is_verified=1", (subject,)).fetchone()
                if identity is None:
                    receipt.status = "auth_required"; receipt.errors.append({"code":"verified_identity_required","resource":"auth","logical_object_key":"garmin:account:identity","summary":"authenticate before sync"}); self.repo.finish_run(conn, run, receipt, None, None); return receipt
                try:
                    self._transport().login()
                    actual = self._identity_hmac(self._transport().identity())
                    verified = conn.execute("SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND identity_hmac=? AND is_verified=1", (subject, actual)).fetchone()
                    if verified is None:
                        receipt.status="failed"; receipt.errors.append({"code":"identity_mismatch","resource":"auth","logical_object_key":"garmin:account:identity","summary":"identity mismatch"}); self.repo.finish_run(conn,run,receipt,None,None); return receipt
                except GarminError as exc:
                    receipt.status="auth_required" if exc.http_status==401 else "failed"; receipt.errors.append({"code":exc.code,"resource":"auth","logical_object_key":"garmin:account:identity","summary":"provider authentication failed"}); self.repo.finish_run(conn,run,receipt,None,None); return receipt
            today = self._today_local()
            yesterday = today - timedelta(days=1)
            if request.mode == "repair" and offline_repair:
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else yesterday
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._offline_repair(conn, run, subject, replace(request, repair_strategy=repair_strategy), receipt)
                self._advance_repair_health_cursors(
                    conn, run, subject, request, actual_through,
                )
            elif request.mode in {"full", "incremental", "snapshot"}:
                plan = self._build_mode_plan(conn, subject, request, today)
                prior_gap_ceiling = (
                    int(conn.execute(
                        "SELECT coalesce(max(id),0) FROM garmin_sync_gaps"
                    ).fetchone()[0])
                    if request.mode == "incremental"
                    else 0
                )
                actual_start, actual_through = plan.effective_start, plan.effective_through
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                if plan.snapshot:
                    receipt.coverage_state = "partial"
                self._account_basics(conn, run, subject, plan.effective_through, request, receipt)
                self._account_b1(conn, run, subject, plan.effective_through, request, receipt)
                selected = set(request.resource_kinds)
                for window in plan.health_windows:
                    scoped = replace(request, resource_kinds=(window.resource_kind,))
                    self._health(
                        conn, run, subject, window.start, window.through,
                        scoped, receipt,
                    )
                # Explicit account-only repair is a closed provider scope: it
                # must not enumerate activities merely because activities are
                # normally part of a full collection invocation.
                activity_scope = {
                    "activity_inventory", "activity_summary", "activity_fit",
                    "activity_details_fallback", "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if request.activity_ids or not selected or selected.intersection(activity_scope):
                    self._activities(
                        conn, run, subject, plan.activity_start,
                        plan.activity_through, request, receipt,
                        not selected or "activity_fit" in selected,
                    )
                if request.mode == "incremental":
                    self._process_due_gaps(
                        conn, run, subject, request, receipt,
                        plan.activity_start, plan.activity_through,
                        prior_gap_ceiling,
                    )
                if not plan.snapshot:
                    for window in plan.health_windows:
                        self.repo.advance_cursor(
                            conn, subject, window.resource_kind,
                            window.through.isoformat(), run,
                        )
                    if receipt.coverage_state != "partial":
                        receipt.coverage_state = (
                            "complete"
                            if self._health_windows_complete(conn, subject, plan.health_windows)
                            else "partial"
                        )
            elif request.mode == "audit":
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else today
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._audit(conn, subject, receipt, actual_start, actual_through)
            elif request.mode == "repair":
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else yesterday
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._account_basics(conn, run, subject, actual_through, request, receipt)
                self._account_b1(conn, run, subject, actual_through, request, receipt)
                selected = set(request.resource_kinds)
                if not selected or selected.intersection(COLLECTED_HEALTH_RESOURCES):
                    self._health(conn, run, subject, actual_start, actual_through, request, receipt)
                activity_scope = {
                    "activity_inventory", "activity_summary", "activity_fit",
                    "activity_details_fallback", "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if request.activity_ids or not selected or selected.intersection(activity_scope):
                    self._activities(
                        conn, run, subject, actual_start, actual_through,
                        request, receipt, not selected or "activity_fit" in selected,
                    )
                self._advance_repair_health_cursors(
                    conn, run, subject, request, actual_through,
                )
            receipt.status = "deferred" if receipt.counts["deferred"] else (
                "partial"
                if receipt.counts["failed"] or (
                    request.mode != "snapshot" and receipt.coverage_state == "partial"
                )
                else "succeeded"
            )
            receipt.open_gap_count = int(conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred')", (subject,)).fetchone()[0])
            receipt.complete_through_by_resource = {r["resource_kind"]: r["complete_through_local_date"] for r in conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?", (subject,))}
            if receipt.next_retry_at_utc is None:
                pending_retry = conn.execute(
                    """SELECT min(next_retry_at_utc) FROM garmin_sync_gaps
                       WHERE subject_id=? AND status='deferred'
                         AND next_retry_at_utc IS NOT NULL""",
                    (subject,),
                ).fetchone()[0]
                receipt.next_retry_at_utc = pending_retry
            self.repo.finish_run(
                conn, run, receipt,
                actual_start.isoformat() if actual_start else None,
                actual_through.isoformat() if actual_through else None,
            )
            return receipt
        except GarminError as exc:
            receipt.status = "auth_required" if exc.http_status == 401 else "failed"; receipt.errors.append({"code": exc.code, "resource": "garmin", "logical_object_key":"garmin:run","summary": exc.code})
            try: self.repo.finish_run(conn, run, receipt, actual_start.isoformat() if actual_start else None, actual_through.isoformat() if actual_through else None)
            except Exception: receipt.completed_at_utc = utc_now()
            return receipt
        finally: conn.close()

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
            resource for resource in COLLECTED_HEALTH_RESOURCES
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
            resource for resource in COLLECTED_HEALTH_RESOURCES
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
                conn, subject, resource, actual_through.isoformat(), run,
            )

    @staticmethod
    def _health_windows_complete(
        conn: sqlite3.Connection,
        subject: int,
        windows: Iterable[ResourceDateWindow],
    ) -> bool:
        closed_states = {
            "fetched", "empty", "not_enabled", "not_available", "not_supported",
        }
        for window in windows:
            rows = conn.execute(
                """SELECT local_date,availability_state
                   FROM resource_coverage
                   WHERE subject_id=? AND provider='garmin'
                     AND resource_kind=? AND local_date>=? AND local_date<=?
                   ORDER BY id""",
                (
                    subject, window.resource_kind,
                    window.start.isoformat(), window.through.isoformat(),
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
                    subject, window.resource_kind,
                    window.through.isoformat(), window.start.isoformat(),
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
        gaps = list(conn.execute(
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
        ))
        activity_resources = {
            "activity_inventory", "activity_summary", "activity_fit",
            "activity_details_fallback", "activities",
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
                    conn, run, subject, start, through, scoped, receipt,
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
                conn, run, subject,
                start if activity_id else activity_start,
                through if activity_id else activity_through,
                scoped, receipt,
                selected_resource == "activity_fit",
            )

    @staticmethod
    def _activity_id_from_key(logical_key: str) -> str | None:
        prefix = "garmin:activity:"
        if not logical_key.startswith(prefix):
            return None
        value = logical_key[len(prefix):].strip()
        return value if value and ":" not in value else None

    def _now_utc(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.astimezone(UTC)

    def _classify(self, error: GarminError, *, allows_404: bool = False) -> RetryClassification:
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
                self.config.rate_limit_fallback_seconds * (2 ** attempt),
            )
        return (self._now_utc() + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    def _cooldown_error(self, conn: sqlite3.Connection | None, subject: int | None, resource: str | None, key: str | None) -> GarminError | None:
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
            due = datetime.fromisoformat(row["next_retry_at_utc"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return GarminError("cooldown_corrupt")
        remaining = (due - self._now_utc()).total_seconds()
        return GarminError("cooldown_active", http_status=429, retry_after=max(1, int(remaining))) if remaining > 0 else None

    def _call(self, fn: Callable[[], Any], *, conn: sqlite3.Connection | None = None, run: int | None = None, subject: int | None = None, resource: str | None = None, key: str | None = None, stage: str = "fetch", allows_404: bool = False) -> Any:
        """Execute one provider call with controlled retry and durable attempts."""
        cooldown = self._cooldown_error(conn, subject, resource, key)
        if cooldown is not None:
            raise cooldown
        last: GarminError | None = None
        refreshed = False
        for attempt in range(self.config.max_attempts):
            try:
                now = self.monotonic()
                interval = 0.0
                if self._last_request is not None:
                    target_interval = (
                        self.config.request_min_interval_ms
                        + self.config.request_interval_jitter_ms * self.rng()
                    ) / 1000
                    interval = target_interval - (now - self._last_request)
                    if interval > 0:
                        self.sleep(interval)
                # Record the time before invoking so failed requests also
                # participate in the global pseudo-random interval.
                self._last_request = now + max(0.0, interval)
                if conn is not None and run is not None and resource and key:
                    self.repo.item(conn, run, resource, key, stage, "running")
                return fn()
            except GarminError as exc:
                last = exc
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
                if classification.status != "retry" or attempt + 1 == self.config.max_attempts:
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
                    delay = min(self.config.retry_max_seconds, self.config.retry_base_seconds * (2 ** attempt) + self.rng())
                    self.sleep(delay)
        raise last or GarminError("unknown")

    _ACCOUNT_BASIC_RESOURCES = ("user_profile", "user_profile_settings", "devices")
    _ACCOUNT_B1_RESOURCES = ("primary_device", "device_settings", "device_last_used", "personal_records", "cycling_ftp", "pregnancy")
    _PROFILE_SETTING_FIELDS = {
        "measurementSystem", "timeFormat", "weekStartDay", "heartRateMethod",
    }
