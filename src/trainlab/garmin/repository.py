"""Durable Garmin repository and raw-object storage boundary."""
from __future__ import annotations

from .contracts import *  # noqa: F403
class GarminRepository:
    """All mutable Garmin state, with short transactions only."""
    def __init__(self, config: GarminConfig) -> None:
        self.config = config

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.config.database_path}?mode=ro" if readonly else self.config.database_path, isolation_level=None, uri=readonly)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def subject(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT id FROM data_subjects WHERE subject_key=?", (self.config.subject_key,)).fetchone()
        if row:
            return int(row[0])
        conn.execute("INSERT INTO data_subjects(subject_key,timezone,created_at_utc) VALUES(?,?,?)", (self.config.subject_key, "Asia/Singapore", utc_now()))
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def start_run(self, conn: sqlite3.Connection, request: SyncRequest, subject_id: int, receipt: SyncReceipt) -> int:
        if request.invocation_id is None:
            raise ValueError("invocation_id_required")
        invocation = request.invocation_id
        existing = conn.execute("SELECT id,run_id,status FROM garmin_sync_runs WHERE invocation_id=?", (invocation,)).fetchone()
        if existing:
            full = conn.execute("SELECT * FROM garmin_sync_runs WHERE id=?", (existing["id"],)).fetchone()
            receipt.run_id, receipt.status = full["run_id"], full["status"]
            receipt.started_at_utc = full["started_at_utc"]
            receipt.requested_range = {"from": full["requested_from_local_date"], "through": full["requested_through_local_date"]}
            receipt.effective_range = {"from": full["actual_from_local_date"], "through": full["actual_through_local_date"]}
            receipt.counts.update({"fetched":full["fetched_count"],"empty":full["empty_count"],"unchanged":full["unchanged_count"],"revised":full["revised_count"],"failed":full["failed_count"],"deferred":full["deferred_count"]})
            for item_status, count in conn.execute(
                """SELECT status,count(*) AS count
                   FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND status IN ('not_available','not_supported','not_enabled')
                   GROUP BY status""",
                (existing["id"],),
            ):
                # Receipt v1 has no separate not_supported counter.  It is a
                # completed unavailable outcome, deterministically folded
                # into not_available both live and during replay.
                counter = "not_available" if item_status == "not_supported" else item_status
                receipt.counts[counter] += int(count)
            fallback_used = conn.execute(
                """SELECT 1 FROM garmin_sync_items
                   WHERE garmin_sync_run_id=?
                     AND resource_kind='activity_details_fallback'
                     AND stage='project'
                     AND (
                         status IN ('revised','unchanged','succeeded')
                         OR (
                             status='failed'
                             AND error_code IN (
                                 'activity_chart_empty','activity_chart_invalid'
                             )
                         )
                     )
                   LIMIT 1""",
                (existing["id"],),
            ).fetchone()
            receipt.coverage_state = (
                "partial"
                if (
                    full["mode"] == "snapshot"
                    or fallback_used is not None
                    or full["status"] in {"partial", "deferred", "failed"}
                )
                else "complete" if full["status"] == "succeeded" else None
            )
            receipt.complete_through_by_resource = {
                row["resource_kind"]: row["complete_through_local_date"]
                for row in conn.execute(
                    """SELECT resource_kind,complete_through_local_date
                       FROM garmin_sync_cursors WHERE subject_id=?""",
                    (subject_id,),
                )
            }
            receipt.open_gap_count = int(
                conn.execute(
                    """SELECT count(*) FROM garmin_sync_gaps
                       WHERE subject_id=? AND status IN ('open','deferred')""",
                    (subject_id,),
                ).fetchone()[0]
            )
            receipt.next_retry_at_utc, receipt.completed_at_utc = full["next_retry_at_utc"], full["completed_at_utc"]
            if full["error_summary"]: receipt.errors.append({"code":full["error_summary"],"resource":"garmin","logical_object_key":"garmin:run","summary":full["error_summary"]})
            if full["status"] == "started":
                conn.execute(
                    """UPDATE garmin_sync_items
                       SET status='pending',completed_at_utc=NULL,next_retry_at_utc=NULL
                       WHERE garmin_sync_run_id=? AND status='running'""",
                    (existing["id"],),
                )
                # An interrupted run has not reached ``finish_run``, so its
                # aggregate columns still contain their initial zeros. Rebuild
                # only completed-success counters before skipping durable work.
                # Failed/deferred items are retried below; carrying their old
                # counts forward would incorrectly make a successful resume
                # finish partial/deferred.
                receipt.counts.update({key: 0 for key in receipt.counts})
                for item_status, count in conn.execute(
                    """SELECT status,count(*) AS count
                         FROM garmin_sync_items
                        WHERE garmin_sync_run_id=?
                          AND status IN (
                              'fetched','empty','unchanged','revised',
                              'not_available','not_supported',
                              'not_enabled'
                          )
                        GROUP BY status""",
                    (existing["id"],),
                ):
                    counter = (
                        "not_available"
                        if item_status == "not_supported"
                        else item_status
                    )
                    receipt.counts[counter] += int(count)
            return int(existing["id"])
        run_id = f"gr-{uuid.uuid4()}"
        receipt.run_id, receipt.status = run_id, "started"
        conn.execute("""INSERT INTO garmin_sync_runs(run_id,invocation_id,subject_id,mode,requested_from_local_date,requested_through_local_date,resource_catalog_version,collector_version,garminconnect_version,parser_version,status,started_at_utc)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, invocation, subject_id, request.mode if request.mode != "auth" and request.mode != "status" else "audit", request.health_from_local_date, request.through_local_date or request.snapshot_local_date, CATALOG_VERSION, COLLECTOR_VERSION, GARMINCONNECT_VERSION, PARSER_VERSION, "started", receipt.started_at_utc))
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def finish_run(self, conn: sqlite3.Connection, run_id: int, receipt: SyncReceipt, actual_from: str | None, actual_through: str | None) -> None:
        receipt.completed_at_utc = utc_now()
        # A later successful stage proves that its provider fetch completed.
        # Close any such predecessor defensively so a future adapter omission
        # cannot publish a succeeded run with a lingering `running` item.
        conn.execute(
            """UPDATE garmin_sync_items AS fetch
               SET status='fetched',completed_at_utc=?,error_code=NULL,
                   error_summary=NULL,next_retry_at_utc=NULL
               WHERE fetch.garmin_sync_run_id=? AND fetch.stage='fetch'
                 AND fetch.status='running'
                 AND EXISTS(
                     SELECT 1 FROM garmin_sync_items AS later
                     WHERE later.garmin_sync_run_id=fetch.garmin_sync_run_id
                       AND later.resource_kind=fetch.resource_kind
                       AND later.logical_object_key=fetch.logical_object_key
                       AND later.stage IN ('extract','parse','project','reconcile','validate')
                       AND later.status IN ('fetched','empty','unchanged','revised','succeeded',
                                            'not_available','not_enabled','not_supported')
                 )""",
            (receipt.completed_at_utc, run_id),
        )
        remaining = int(
            conn.execute(
                """SELECT count(*) FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND status='running'""",
                (run_id,),
            ).fetchone()[0]
        )
        if remaining:
            conn.execute(
                """UPDATE garmin_sync_items
                   SET status='failed',error_code='interrupted',
                       error_summary='interrupted',completed_at_utc=?
                   WHERE garmin_sync_run_id=? AND status='running'""",
                (receipt.completed_at_utc, run_id),
            )
            receipt.counts["failed"] += remaining
            if receipt.status == "succeeded":
                receipt.status = "partial"
        conn.execute("""UPDATE garmin_sync_runs SET status=?,actual_from_local_date=?,actual_through_local_date=?,fetched_count=?,empty_count=?,unchanged_count=?,revised_count=?,failed_count=?,deferred_count=?,next_retry_at_utc=?,error_summary=?,completed_at_utc=? WHERE id=?""", (receipt.status, actual_from, actual_through, receipt.counts["fetched"], receipt.counts["empty"], receipt.counts["unchanged"], receipt.counts["revised"], receipt.counts["failed"], receipt.counts["deferred"], receipt.next_retry_at_utc, safe_provider_error_code(receipt.errors[0]["code"]) if receipt.errors else None, receipt.completed_at_utc, run_id))

    def item(self, conn: sqlite3.Connection, run_id: int, resource: str, key: str, stage: str, status: str, *, revision_id: int | None = None, error: GarminError | None = None, next_retry: str | None = None, increment_attempt: bool = True) -> None:
        allowed={"pending":{"running","failed","deferred"},"running":{"fetched","empty","unchanged","revised","succeeded","failed","deferred","not_available","not_enabled","not_supported","forbidden"},"deferred":{"running","failed"},"failed":{"running"}}
        row=conn.execute("SELECT status FROM garmin_sync_items WHERE garmin_sync_run_id=? AND resource_kind=? AND logical_object_key=? AND stage=?",(run_id,resource,key,stage)).fetchone()
        terminal = {
            "fetched", "empty", "unchanged", "revised", "succeeded", "failed",
            "deferred", "not_available", "not_enabled", "not_supported",
            "forbidden",
        }
        replay_allowed = (
            row is not None
            and row["status"] in terminal
            and status in terminal | {"running"}
        )
        if row and row["status"]!=status and status not in allowed.get(row["status"],set()) and not replay_allowed: raise ValueError("invalid_item_transition")
        now = utc_now(); completed = now if status in {"fetched","empty","unchanged","revised","succeeded","failed","deferred","not_available","not_enabled","not_supported","forbidden"} else None
        error_code = self._safe_error_code(error.code) if error else None
        conn.execute("""INSERT INTO garmin_sync_items(garmin_sync_run_id,resource_kind,logical_object_key,stage,status,attempt_count,http_status,error_code,error_summary,next_retry_at_utc,source_revision_id,started_at_utc,completed_at_utc)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(garmin_sync_run_id,resource_kind,logical_object_key,stage) DO UPDATE SET status=excluded.status,attempt_count=garmin_sync_items.attempt_count+?,http_status=excluded.http_status,error_code=excluded.error_code,error_summary=excluded.error_summary,next_retry_at_utc=excluded.next_retry_at_utc,source_revision_id=excluded.source_revision_id,completed_at_utc=excluded.completed_at_utc""", (run_id, resource, key, stage, status, 1 if increment_attempt else 0, error.http_status if error else None, error_code, error_code if error else None, next_retry, revision_id, now, completed, 1 if increment_attempt else 0))

    @staticmethod
    def _safe_error_code(code: str) -> str:
        return safe_provider_error_code(code)

    def gap(self, conn: sqlite3.Connection, subject: int, resource: str, key: str, day: str, stage: str, reason: str, *, end_day: str | None = None, deferred: bool = False, next_retry: str | None = None, revision: int | None = None) -> None:
        now = utc_now(); status = "deferred" if deferred else "open"; reason = safe_provider_error_code(reason)
        conn.execute("""INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,next_retry_at_utc,first_seen_at_utc,last_attempt_at_utc,source_revision_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred') DO UPDATE SET reason_code=excluded.reason_code,status=excluded.status,next_retry_at_utc=excluded.next_retry_at_utc,last_attempt_at_utc=excluded.last_attempt_at_utc,attempt_count=garmin_sync_gaps.attempt_count+1""", (subject, resource, key, day, end_day or day, stage, reason, status, next_retry, now, now, revision))

    def resolve_gaps(
        self,
        conn: sqlite3.Connection,
        subject: int,
        resource: str,
        day: str,
        *,
        logical_object_key: str | None = None,
        stages: Iterable[str] | None = None,
    ) -> None:
        """Resolve a day-level gap scope, optionally narrowed to one object.

        Health resources intentionally use the original resource/day scope.
        Object resources such as activity FIT must also pass their logical key
        so one successful object cannot hide another object's unresolved gap.
        """
        now = utc_now()
        filters = [
            "subject_id=?",
            "resource_kind=?",
            "window_start_local_date<=?",
            "window_end_local_date>=?",
            "status IN ('open','deferred')",
        ]
        parameters: list[Any] = [subject, resource, day, day]
        if logical_object_key is not None:
            filters.append("logical_object_key=?")
            parameters.append(logical_object_key)
        if stages is not None:
            stage_values = tuple(dict.fromkeys(stages))
            if not stage_values:
                return
            filters.append(f"stage IN ({','.join('?' for _ in stage_values)})")
            parameters.extend(stage_values)
        conn.execute(
            f"""UPDATE garmin_sync_gaps
                SET status='resolved',resolved_at_utc=?,last_attempt_at_utc=?
                WHERE {' AND '.join(filters)}""",
            (now, now, *parameters),
        )

    def capability(self, conn: sqlite3.Connection, subject: int, resource: str, state: str, *, reason: str | None = None, next_probe: str | None = None, environment_key: str = "default") -> None:
        if state not in {"supported","not_enabled","not_available","not_supported","forbidden","unknown"}: raise ValueError("invalid_capability_state")
        reason = safe_provider_error_code(reason) if reason else None
        now=utc_now(); conn.execute("INSERT INTO garmin_resource_capabilities(subject_id,environment_key,resource_kind,capability_state,reason_code,first_checked_at_utc,last_checked_at_utc,next_probe_at_utc) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(subject_id,environment_key,resource_kind) DO UPDATE SET capability_state=excluded.capability_state,reason_code=excluded.reason_code,last_checked_at_utc=excluded.last_checked_at_utc,next_probe_at_utc=excluded.next_probe_at_utc",(subject,environment_key,resource,state,reason,now,now,next_probe))

    def reconcile_legacy_capability_environment(
        self, conn: sqlite3.Connection, subject: int, environment_key: str,
    ) -> None:
        """Reconcile legacy capability metadata and zero-record coverage.

        Earlier health paths omitted ``environment_key`` and consequently
        created ``default`` rows alongside the configured Garmin region.  This
        merges only that capability metadata into the configured region.  It
        also corrects legacy Garmin ``fetched`` coverage with zero canonical
        records to ``empty``; it never changes counts, revisions, raw data,
        evidence or observation timestamps.  It then restores missing
        capability index rows from the subject's latest completed
        coverage observations.  When a regional row already exists, the newer
        observation defines the capability semantics while the observation
        envelope is retained.
        """
        conn.execute("BEGIN IMMEDIATE")
        try:
            # A successful provider response that produced no reviewed
            # canonical rows represents a completed empty day.  Repair only
            # that legacy coverage label in place: raw data, revision links,
            # counts and observation timestamps are deliberately untouched.
            # This is scoped to Garmin and is naturally idempotent.
            conn.execute(
                """UPDATE resource_coverage
                   SET availability_state='empty'
                   WHERE subject_id=? AND provider='garmin'
                     AND availability_state='fetched' AND record_count=0""",
                (subject,),
            )
            # Coverage semantics are independent of the configured region;
            # only migration of legacy capability rows is region-specific.
            if environment_key == "default":
                conn.execute("COMMIT")
                return
            legacy_rows = conn.execute(
                """SELECT * FROM garmin_resource_capabilities
                   WHERE subject_id=? AND environment_key='default'
                   ORDER BY resource_kind,id""",
                (subject,),
            ).fetchall()
            for legacy in legacy_rows:
                current = conn.execute(
                    """SELECT * FROM garmin_resource_capabilities
                       WHERE subject_id=? AND environment_key=? AND resource_kind=?""",
                    (subject, environment_key, legacy["resource_kind"]),
                ).fetchone()
                if current is None:
                    conn.execute(
                        "UPDATE garmin_resource_capabilities SET environment_key=? WHERE id=?",
                        (environment_key, legacy["id"]),
                    )
                    continue
                newest = max((legacy, current), key=lambda row: (row["last_checked_at_utc"], row["id"]))
                first_checked = min(legacy["first_checked_at_utc"], current["first_checked_at_utc"])
                last_checked = max(legacy["last_checked_at_utc"], current["last_checked_at_utc"])
                conn.execute(
                    """UPDATE garmin_resource_capabilities
                       SET capability_state=?,reason_code=?,reason_summary=?,
                           first_checked_at_utc=?,last_checked_at_utc=?,
                           next_probe_at_utc=?,source_revision_id=?
                       WHERE id=?""",
                    (
                        newest["capability_state"], newest["reason_code"], newest["reason_summary"],
                        first_checked, last_checked, newest["next_probe_at_utc"],
                        newest["source_revision_id"], current["id"],
                    ),
                )
                conn.execute("DELETE FROM garmin_resource_capabilities WHERE id=?", (legacy["id"],))
            completed = {
                "fetched": "supported", "empty": "supported",
                "not_enabled": "not_enabled", "not_available": "not_available",
                "not_supported": "not_supported", "forbidden": "forbidden",
            }
            latest_coverage: dict[str, sqlite3.Row] = {}
            for coverage in conn.execute(
                """SELECT id,resource_kind,availability_state,observed_at_utc
                   FROM resource_coverage
                   WHERE subject_id=? AND provider='garmin'
                   ORDER BY resource_kind,observed_at_utc DESC,id DESC""",
                (subject,),
            ):
                if (
                    coverage["resource_kind"] not in latest_coverage
                    and coverage["availability_state"] in completed
                ):
                    latest_coverage[coverage["resource_kind"]] = coverage
            for resource, coverage in latest_coverage.items():
                current = conn.execute(
                    """SELECT * FROM garmin_resource_capabilities
                       WHERE subject_id=? AND environment_key=? AND resource_kind=?""",
                    (subject, environment_key, resource),
                ).fetchone()
                if current is not None and current["last_checked_at_utc"] >= coverage["observed_at_utc"]:
                    continue
                state = completed[coverage["availability_state"]]
                if current is None:
                    conn.execute(
                        """INSERT INTO garmin_resource_capabilities(
                               subject_id,environment_key,resource_kind,capability_state,
                               first_checked_at_utc,last_checked_at_utc)
                           VALUES(?,?,?,?,?,?)""",
                        (subject, environment_key, resource, state,
                         coverage["observed_at_utc"], coverage["observed_at_utc"]),
                    )
                else:
                    conn.execute(
                        """UPDATE garmin_resource_capabilities
                           SET capability_state=?,reason_code=NULL,reason_summary=NULL,
                               last_checked_at_utc=?,next_probe_at_utc=NULL
                           WHERE id=?""",
                        (state, coverage["observed_at_utc"], current["id"]),
                    )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _verify_dirfd(fd: int) -> None:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("unsafe_raw_path")

    @staticmethod
    def _verify_filefd(fd: int, payload: bytes, *, expected_size: int | None = None) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != (len(payload) if expected_size is None else expected_size):
            raise ValueError("raw_object_corrupt")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if digest(b"".join(chunks)) != digest(payload):
            raise ValueError("raw_object_corrupt")

    def _open_raw_rootfd(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            before = os.lstat(self.config.raw_root)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o700:
            raise ValueError("unsafe_raw_path")
        try:
            fd = os.open(self.config.raw_root, flags)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        try:
            self._verify_dirfd(fd)
            after = os.lstat(self.config.raw_root)
            current = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("unsafe_raw_path")
        except Exception:
            os.close(fd)
            raise
        return fd

    def _open_child_dirfd(self, parent_fd: int, name: str, *, create: bool) -> int:
        if not name or name in {".", ".."} or "/" in name:
            raise ValueError("unsafe_raw_path")
        created = False
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise ValueError("raw_object_corrupt") from None
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                raise ValueError("unsafe_raw_path") from exc
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                raise ValueError("unsafe_raw_path") from exc
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise ValueError("unsafe_raw_path")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        try:
            self._verify_dirfd(child_fd)
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            current = os.fstat(child_fd)
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("unsafe_raw_path")
            # A newly named directory cannot be used as a durable raw path
            # until its parent directory entry is durable.  This intentionally
            # fails closed before any raw_objects transaction is opened.
            if created:
                os.fsync(parent_fd)
        except Exception:
            os.close(child_fd)
            raise
        return child_fd

    def _cleanup_owned_temp(
        self,
        directory_fd: int,
        temporary_name: str,
        *,
        device: int,
        inode: int,
        payload: bytes,
    ) -> None:
        """Remove only an inode we still own, without temp-name stat/unlink.

        The first operation moves the random temporary entry to an independent
        cleanup claim.  A hostile replacement of the old temp name is never
        inspected or unlinked.  A replacement of the claim is detected by the
        descriptor-backed identity sequence and intentionally retained.
        """
        claim = f".cleanup-{uuid.uuid4()}"
        try:
            # Claim names are random and private to this invocation.  Check
            # before rename so a pre-existing unexpected claim is never
            # overwritten; a later replacement is caught below and preserved.
            try:
                os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("raw_cleanup_claim_exists")
            os.rename(temporary_name, claim, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except FileNotFoundError as exc:
            raise ValueError("raw_cleanup_interrupted") from exc

        try:
            before = os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or (before.st_dev, before.st_ino) != (device, inode):
                raise ValueError("raw_cleanup_claim_replaced")
            fd = os.open(claim, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                opened = os.fstat(fd)
                self._verify_filefd(fd, payload)
                after = os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    (opened.st_dev, opened.st_ino) != (device, inode)
                    or (after.st_dev, after.st_ino) != (device, inode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                ):
                    raise ValueError("raw_cleanup_claim_replaced")
            finally:
                os.close(fd)
            # The only unlink follows a successful full descriptor-backed
            # verification of the random claim, never a stat(temp)/unlink.
            os.unlink(claim, dir_fd=directory_fd)
            os.fsync(directory_fd)
            # A rename removes the old temporary name.  If it has reappeared
            # while cleaning, it is somebody else's replacement: preserve it
            # and fail before any database publication.
            try:
                os.stat(temporary_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("raw_cleanup_temp_replaced")
        except FileNotFoundError as exc:
            raise ValueError("raw_cleanup_claim_replaced") from exc

    def _open_relative_rawfd(self, relative_path: str) -> int:
        parts = Path(relative_path).parts
        if not parts or parts[0] != "raw" or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("raw_object_corrupt")
        root_fd = self._open_raw_rootfd()
        current = root_fd
        try:
            for part in parts[1:-1]:
                child = self._open_child_dirfd(current, part, create=False)
                os.close(current)
                current = child
            before = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise ValueError("raw_object_corrupt")
            fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
            after = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            opened = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                os.close(fd)
                raise ValueError("raw_object_corrupt")
            return fd
        except OSError as exc:
            raise ValueError("raw_object_corrupt") from exc
        finally:
            os.close(current)

    def store_raw(self, resource: str, payload: bytes, suffix: str, media_type: str) -> tuple[int, str]:
        """Append immutable provider evidence to the permanent raw archive.

        Final JSON and FIT objects are content-addressed and never removed or
        overwritten by collection, repair, audit, or replay.  The only cleanup
        in this write path is for a private temporary inode after the durable
        content-addressed file has been verified.
        """
        allowed_types = {
            "json": "application/json",
            "fit": "application/octet-stream",
            "tcx": "application/vnd.garmin.tcx+xml",
            "gpx": "application/gpx+xml",
        }
        if allowed_types.get(suffix) != media_type:
            raise ValueError("raw_type_not_allowed")
        if suffix == "json":
            # Validate at the lowest public raw boundary, but preserve the
            # provider's exact bytes as required by the raw evidence contract.
            parse_provider_json_bytes(payload)
        sha = digest(payload)
        now = utc_now()
        existing_connection = self.connect()
        try:
            existing = existing_connection.execute(
                """SELECT id,relative_path,size_bytes,media_type
                   FROM raw_objects WHERE sha256=?""",
                (sha,),
            ).fetchone()
        finally:
            existing_connection.close()
        if existing is not None:
            try:
                stored_fd = self._open_relative_rawfd(str(existing["relative_path"]))
                try:
                    self._verify_filefd(stored_fd, payload, expected_size=int(existing["size_bytes"]))
                finally:
                    os.close(stored_fd)
            except ValueError as exc:
                raise ValueError("raw_object_corrupt") from exc
            if existing["size_bytes"] != len(payload) or existing["media_type"] != media_type:
                raise ValueError("raw_object_corrupt")
            return int(existing["id"]), sha

        date_path = datetime.now(UTC).strftime("%Y/%m")
        root_fd = self._open_raw_rootfd()
        dir_fds = [root_fd]
        final_name = f"{sha}.{suffix}"
        try:
            storage_kind = suffix if suffix in {"fit", "tcx", "gpx"} else "json"
            for part in ("garmin", storage_kind, *date_path.split("/")):
                child_fd = self._open_child_dirfd(dir_fds[-1], part, create=True)
                dir_fds.append(child_fd)
            directory_fd = dir_fds[-1]
            try:
                before_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                before_final = None
            if before_final is not None:
                if stat.S_ISLNK(before_final.st_mode):
                    raise ValueError("raw_object_corrupt")
                try:
                    final_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                except OSError as exc:
                    raise ValueError("raw_object_corrupt") from exc
                try:
                    opened_final = os.fstat(final_fd)
                    self._verify_filefd(final_fd, payload)
                    after_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                    if (before_final.st_dev, before_final.st_ino) != (opened_final.st_dev, opened_final.st_ino) or (after_final.st_dev, after_final.st_ino) != (opened_final.st_dev, opened_final.st_ino):
                        raise ValueError("raw_object_corrupt")
                finally:
                    os.close(final_fd)
            else:
                temporary_name = f".tmp-{uuid.uuid4()}"
                tmp_fd = os.open(temporary_name, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
                # Capture the owned temporary inode before any potentially
                # failing write.  Cleanup may only unlink this exact inode.
                tmp_inode: int | None = None
                tmp_device: int | None = None
                written = 0
                try:
                    tmp_info = os.fstat(tmp_fd)
                    if not stat.S_ISREG(tmp_info.st_mode) or tmp_info.st_uid != os.getuid():
                        raise ValueError("unsafe_raw_path")
                    tmp_inode, tmp_device = tmp_info.st_ino, tmp_info.st_dev
                    os.fchmod(tmp_fd, 0o600)
                    while written < len(payload):
                        count = os.write(tmp_fd, payload[written:])
                        if count <= 0:
                            raise OSError("raw_short_write")
                        written += count
                    os.fsync(tmp_fd)
                    self._verify_filefd(tmp_fd, payload)
                    tmp_inode = os.fstat(tmp_fd).st_ino
                    won = False
                    try:
                        os.link(temporary_name, final_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                        won = True
                    except FileExistsError:
                        pass
                    os.fsync(directory_fd)
                    before_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(before_final.st_mode):
                        raise ValueError("raw_object_corrupt")
                    final_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                    try:
                        self._verify_filefd(final_fd, payload)
                        final_stat = os.fstat(final_fd)
                        after_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                        if (before_final.st_dev, before_final.st_ino) != (final_stat.st_dev, final_stat.st_ino) or (after_final.st_dev, after_final.st_ino) != (final_stat.st_dev, final_stat.st_ino):
                            raise ValueError("raw_object_corrupt")
                        if won and (final_stat.st_dev, final_stat.st_ino) != (tmp_device, tmp_inode):
                            raise ValueError("raw_object_corrupt")
                    finally:
                        os.close(final_fd)
                finally:
                    os.close(tmp_fd)
                    if tmp_inode is not None and tmp_device is not None:
                        self._cleanup_owned_temp(
                            directory_fd,
                            temporary_name,
                            device=tmp_device,
                            inode=tmp_inode,
                            payload=payload[:written],
                        )
            rel = str(Path("raw") / "garmin" / storage_kind / date_path / final_name)
        finally:
            for fd in reversed(dir_fds):
                os.close(fd)
        conn = self.connect()
        try:
            # Do not leave a raw_objects row behind if the second trusted
            # descriptor verification detects a concurrent name swap.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,original_name,fetched_at_utc) VALUES(?,?,?,?,?,?,?,?)", (sha, rel, media_type, len(payload), "garmin", resource, None, now))
            row = conn.execute(
                """SELECT id,relative_path,size_bytes,media_type
                   FROM raw_objects WHERE sha256=?""",
                (sha,),
            ).fetchone()
            raw_id = int(row["id"])
            stored_fd = self._open_relative_rawfd(str(row["relative_path"]))
            try:
                self._verify_filefd(stored_fd, payload, expected_size=int(row["size_bytes"]))
            finally:
                os.close(stored_fd)
            if (
                row["size_bytes"] != len(payload)
                or row["media_type"] != media_type
            ):
                raise ValueError("raw_object_corrupt")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return raw_id, sha

    def publish_revision(
        self,
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        raw_id: int,
        raw_sha: str,
        projector: Callable[[int], None] | None = None,
        *,
        payload_hash: str | None = None,
        profile_version: str | None = None,
    ) -> tuple[int, bool]:
        if conn.in_transaction:
            raise ValueError("publisher_requires_clean_connection")
        raw = conn.execute(
            "SELECT sha256 FROM raw_objects WHERE id=?",
            (raw_id,),
        ).fetchone()
        if raw is None or raw["sha256"] != raw_sha:
            raise ValueError("raw_revision_mismatch")
        semantic_hash = payload_hash or raw_sha
        current = conn.execute("SELECT id,payload_hash,profile_version,revision_no FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
        if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
            return int(current["id"]), False
        # Receiving provider evidence and accepting it as canonical are two
        # different durability boundaries.  A parser failure must leave an
        # immutable, non-current revision available for offline reparse.
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("SELECT id,payload_hash,profile_version FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
            if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
                conn.execute("COMMIT")
                return int(current["id"]), False
            # Only a previously *unparsed* received revision may be reused.
            # Returning from a tombstone to an old payload is a provider
            # correction and needs a new revision/current transition.
            received = conn.execute("SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND payload_hash=? AND profile_version IS ? AND parsed_at_utc IS NULL ORDER BY revision_no DESC LIMIT 1", (resource, provider_id, semantic_hash, profile_version)).fetchone()
            if received is None:
                rev = int(conn.execute("SELECT coalesce(max(revision_no),0)+1 FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=?", (resource, provider_id)).fetchone()[0])
                conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,parser_name,parser_version,profile_version,is_current,parsed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,0,NULL)", ("garmin", resource, provider_id, rev, raw_id, semantic_hash, "garmin", PARSER_VERSION, profile_version))
                revision = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                revision = int(received["id"])
            # Commit the received revision before canonical parsing.  The
            # following transaction is deliberately separate and may roll
            # back without erasing raw provenance.
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("SELECT id,payload_hash,profile_version FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
            if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
                conn.execute("COMMIT")
                return int(current["id"]), False
            if projector:
                projector(revision)
            if current:
                conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=?", (current["id"],))
            conn.execute("UPDATE source_revisions SET is_current=1,parsed_at_utc=? WHERE id=?", (utc_now(), revision))
            conn.execute("COMMIT")
            return revision, True
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def archive(
        self,
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        payload: bytes,
        suffix: str,
        media_type: str,
        projector: Callable[[int], None] | None = None,
        *,
        semantic_payload: bytes | None = None,
        profile_version: str | None = None,
    ) -> tuple[int, int, bool]:
        semantic_hash: str | None = None
        if suffix == "json":
            _, canonical = parse_provider_json_bytes(
                semantic_payload if semantic_payload is not None else payload
            )
            semantic_hash = digest(canonical)
        raw_id, raw_sha = self.store_raw(resource, payload, suffix, media_type)
        revision, changed = self.publish_revision(
            conn, resource, provider_id, raw_id, raw_sha, projector,
            payload_hash=semantic_hash,
            profile_version=profile_version,
        )
        return raw_id, revision, changed

    def coverage(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, state: str, revision: int | None, count: int, *, snapshot: bool = False) -> None:
        """Record coverage without turning a snapshot observation into history.

        Foundation coverage intentionally retains completed-day history.  A
        snapshot is different: its only date-level claim is ``partial``, so a
        repeat must update that one observation rather than append duplicate
        partial rows.
        """
        if snapshot:
            row = conn.execute(
                """SELECT id FROM resource_coverage WHERE subject_id=? AND provider='garmin'
                   AND resource_kind=? AND local_date=? AND availability_state='partial'
                   ORDER BY id DESC LIMIT 1""",
                (subject, resource, day),
            ).fetchone()
            if row is not None:
                conn.execute(
                    """UPDATE resource_coverage SET record_count=?,source_revision_id=?,observed_at_utc=?
                       WHERE id=?""",
                    (count, revision, utc_now(), row["id"]),
                )
                return
        conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,record_count,source_revision_id,observed_at_utc) VALUES(?,?,?,?,?,?,?,?)", (subject, "garmin", resource, day, state, count, revision, utc_now()))

    def fields(self, conn: sqlite3.Connection, resource: str, payload: Any) -> None:
        """Catalog source leaf paths without treating discovery as a failure.

        Garmin responses occasionally use numeric dictionary keys for device
        identifiers or epoch buckets.  Those values describe a collection
        member, rather than a distinct field, so catalog them as ``*`` just as
        list members are catalogued.  Named keys remain exact: reviewed
        mappings must continue to match their precise source path.
        """
        def segment(key: Any) -> str:
            if isinstance(key, int) and not isinstance(key, bool):
                return "*"
            if isinstance(key, str) and re.fullmatch(r"[0-9]+", key):
                return "*"
            return str(key)

        def walk(value: Any, path: str = ""):
            if isinstance(value, dict):
                for key, child in value.items(): yield from walk(child, f"{path}/{segment(key)}")
            elif isinstance(value, list):
                for child in value: yield from walk(child, f"{path}/*")
            else: yield path or "/", type(value).__name__
        now=utc_now()
        for path, kind in walk(payload):
            conn.execute("INSERT INTO source_field_catalog(provider,resource_kind,field_path,observed_type,first_seen_at_utc,last_seen_at_utc,mapping_state) VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider,resource_kind,field_path) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc,observed_type=excluded.observed_type", ("garmin",resource,path,kind,now,now,"unknown"))

    def map_field(self, conn: sqlite3.Connection, resource: str, field_path: str, canonical_metric_key: str) -> None:
        """Mark only reviewed source paths as mapped; drift remains unknown."""
        conn.execute(
            """UPDATE source_field_catalog
               SET mapping_state='mapped',canonical_metric_key=?
               WHERE provider='garmin' AND resource_kind=? AND field_path=?""",
            (canonical_metric_key, resource, field_path),
        )

    def passthrough_field(self, conn: sqlite3.Connection, resource: str, field_path: str) -> None:
        conn.execute(
            """UPDATE source_field_catalog SET mapping_state='known_passthrough',canonical_metric_key=NULL
               WHERE provider='garmin' AND resource_kind=? AND field_path=?""",
            (resource, field_path),
        )

    def advance_cursor(self, conn: sqlite3.Connection, subject: int, resource: str, through: str, run_id: int, *, partial: bool = False) -> None:
        if partial: return
        current=conn.execute("SELECT complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=? AND resource_kind=? AND cursor_grain='local_date'",(subject,resource)).fetchone()
        if current and current[0]: candidate=date.fromisoformat(current[0])+timedelta(days=1)
        else:
            first=conn.execute("SELECT min(local_date) FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date<=?",(subject,resource,through)).fetchone()[0]
            candidate=date.fromisoformat(first) if first else None
        latest=None
        while candidate and candidate.isoformat()<=through:
            day=candidate.isoformat(); coverage=conn.execute("SELECT availability_state FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=? ORDER BY id DESC LIMIT 1",(subject,resource,day)).fetchone(); gap=conn.execute("SELECT 1 FROM garmin_sync_gaps WHERE subject_id=? AND resource_kind=? AND window_start_local_date<=? AND window_end_local_date>=? AND status IN ('open','deferred')",(subject,resource,day,day)).fetchone()
            if not coverage or coverage[0] not in {"fetched","empty","not_enabled","not_available","not_supported"} or gap: break
            latest=day; candidate+=timedelta(days=1)
        if latest: conn.execute("INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,complete_through_local_date,last_success_at_utc,last_run_id,catalog_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(subject_id,resource_kind,cursor_grain) DO UPDATE SET complete_through_local_date=excluded.complete_through_local_date,last_success_at_utc=excluded.last_success_at_utc,last_run_id=excluded.last_run_id,catalog_version=excluded.catalog_version",(subject,resource,"local_date",latest,utc_now(),run_id,CATALOG_VERSION))
