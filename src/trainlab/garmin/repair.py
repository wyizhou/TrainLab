"""Repair, audit, status and authentication operations."""
from __future__ import annotations

from .contracts import *  # noqa: F403

class RepairAuditMixin:
    def _repair_strategy(
        self, conn: sqlite3.Connection, subject: int, request: SyncRequest,
        receipt: SyncReceipt,
    ) -> Literal["refetch", "reparse", "reconcile", "deferred"]:
        """Choose auto repair from durable evidence, never from a guess.

        A caller can explicitly choose a strategy.  ``auto`` only examines
        unresolved gaps in the requested scope; capability cooldown is kept as
        a deferred receipt rather than turning into an avoidable provider call.
        """
        if request.mode != "repair":
            return "refetch"
        if request.repair_strategy in {"refetch", "reparse", "reconcile"}:
            return request.repair_strategy
        resources = set(request.resource_kinds)
        if "activities" in resources:
            resources.remove("activities")
            resources.update(ACTIVITY_RESOURCE_KINDS)
        activity_ids = set(request.activity_ids)
        clauses = ["subject_id=?", "status IN ('open','deferred')"]
        values: list[Any] = [subject]
        if resources:
            clauses.append("resource_kind IN (%s)" % ",".join("?" for _ in resources))
            values.extend(sorted(resources))
        if request.health_from_local_date:
            clauses.append("window_end_local_date>=?")
            values.append(request.health_from_local_date)
        if request.through_local_date:
            clauses.append("window_start_local_date<=?")
            values.append(request.through_local_date)
        rows = list(conn.execute(
            "SELECT resource_kind,logical_object_key,reason_code,status,next_retry_at_utc "
            "FROM garmin_sync_gaps WHERE " + " AND ".join(clauses), values
        ))
        if activity_ids:
            rows = [row for row in rows if any(
                self._activity_id_matches(str(row["logical_object_key"]), activity_id)
                for activity_id in activity_ids
            )]
        if rows and all(
            row["status"] == "deferred" and row["next_retry_at_utc"]
            and row["next_retry_at_utc"] > utc_now()
            for row in rows
        ):
            receipt.counts["deferred"] += len(rows)
            receipt.next_retry_at_utc = min(str(row["next_retry_at_utc"]) for row in rows)
            receipt.errors.append({"code": "capability_cooldown", "resource": "garmin", "logical_object_key": "garmin:repair", "summary": "repair deferred until next retry"})
            return "deferred"
        reasons = {str(row["reason_code"]) for row in rows}
        # FIT extraction/identity failures have no locally repairable
        # canonical source.  They require a fresh ORIGINAL response, not an
        # offline reconcile of whatever source happens to be current.
        fit_refetch_reasons = {
            "fit_identity_mismatch", "fit_crc_invalid", "fit_no_session",
            "fit_ambiguous_session", "fit_missing", "fit_ambiguous",
            "fit_zip_invalid", "fit_zip_limits_exceeded", "fit_zip_unsafe_member",
        }
        if any(
            str(row["resource_kind"]) == "activity_fit"
            and str(row["reason_code"]) in fit_refetch_reasons
            for row in rows
        ):
            return "refetch"
        # Missing, corrupt, and transport evidence requires a new provider
        # response.  It has priority when a mixed scope is requested.
        if not rows or any(
            token in reason for reason in reasons
            for token in ("network", "timeout", "rate", "raw_integrity", "missing_raw", "fetch")
        ):
            return "refetch"
        if any("reconcile" in reason or "canonical" in reason for reason in reasons):
            return "reconcile"
        if any(token in reason for reason in reasons for token in ("parse", "project", "field")):
            return "reparse"
        return "refetch"

    def _audit(
        self, conn: sqlite3.Connection, subject: int, receipt: SyncReceipt,
        start: date, through: date,
    ) -> None:
        """Build local, repeatable evidence; never overwrite provider facts."""
        now = utc_now()
        # Audit-owned gaps are refreshed for this bounded window.  They remain
        # durable history, but a later clean scan closes stale evidence before
        # recreating any issue that is still present.
        conn.execute(
            """UPDATE garmin_sync_gaps
                  SET status='resolved',resolved_at_utc=?,last_attempt_at_utc=?
                WHERE subject_id=? AND status IN ('open','deferred')
                  AND reason_code IN ('coverage_error','cursor_crosses_gap',
                                      'activity_summary_missing')
                  AND (window_end_local_date='' OR window_end_local_date>=?)
                  AND (window_start_local_date='' OR window_start_local_date<=?)""",
            (now, now, subject, start.isoformat(), through.isoformat()),
        )
        conn.execute(
            """UPDATE garmin_sync_gaps
                  SET status='ignored_with_reason',resolved_at_utc=?,last_attempt_at_utc=?,
                      next_retry_at_utc=NULL
                WHERE subject_id=? AND status IN ('open','deferred')
                  AND reason_code='unmapped_field_signature'""",
            (now, now, subject),
        )
        for row in conn.execute(
            "SELECT resource_kind,local_date FROM resource_coverage "
            """WHERE subject_id=? AND provider='garmin'
                 AND availability_state='error'
                 AND local_date BETWEEN ? AND ?""",
            (subject, start.isoformat(), through.isoformat()),
        ):
            self.repo.gap(conn, subject, row["resource_kind"], f"coverage:{row['resource_kind']}:{row['local_date']}", row["local_date"] or "", "validate", "coverage_error")
        # A completed cursor must never leap an unresolved date-level gap.
        for cursor in conn.execute(
            "SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?",
            (subject,),
        ):
            ceiling = cursor["complete_through_local_date"]
            if not ceiling:
                continue
            gap = conn.execute(
                """SELECT logical_object_key,window_start_local_date,window_end_local_date,stage
                   FROM garmin_sync_gaps WHERE subject_id=? AND resource_kind=?
                     AND status IN ('open','deferred')
                     AND stage!='cursor_audit'
                     AND window_start_local_date!=''
                     AND (window_end_local_date='' OR window_end_local_date>=?)
                     AND (window_start_local_date='' OR window_start_local_date<=?)
                     AND (window_start_local_date='' OR window_start_local_date<=?)
                   ORDER BY id LIMIT 1""",
                (
                    subject, cursor["resource_kind"], start.isoformat(),
                    through.isoformat(), ceiling,
                ),
            ).fetchone()
            if gap is not None:
                self.repo.gap(conn, subject, cursor["resource_kind"], str(gap["logical_object_key"]), str(gap["window_start_local_date"]), "cursor_audit", "cursor_crosses_gap", end_day=str(gap["window_end_local_date"]))
                receipt.counts["failed"] += 1
        # Validate every current revision's raw lineage.  ``raw_objects`` is
        # authoritative for byte hash; source payload hash can be semantic JSON.
        global_resources = tuple(sorted({*ACCOUNT_RESOURCE_KINDS, "activity_inventory"}))
        placeholders = ",".join("?" for _ in global_resources)
        raw_rows = conn.execute(
            f"""WITH candidate_revisions(id) AS (
                       SELECT id FROM source_revisions
                        WHERE provider='garmin' AND is_current=1
                          AND resource_kind IN ({placeholders})
                       UNION
                       SELECT coverage.source_revision_id
                         FROM resource_coverage coverage
                        WHERE coverage.subject_id=?
                          AND coverage.source_revision_id IS NOT NULL
                          AND coverage.local_date BETWEEN ? AND ?
                       UNION
                       SELECT relation.source_revision_id
                         FROM activity_source_revisions relation
                         JOIN activities activity ON activity.id=relation.activity_id
                        WHERE activity.subject_id=?
                          AND activity.local_date BETWEEN ? AND ?
                   )
                   SELECT r.id,r.resource_kind,r.provider_object_id,r.payload_hash,
                       r.profile_version,
                       o.relative_path,o.sha256,o.size_bytes,o.media_type
                  FROM candidate_revisions candidate
                  JOIN source_revisions r ON r.id=candidate.id
                  JOIN raw_objects o ON o.id=r.raw_object_id
                 WHERE r.provider='garmin' AND r.is_current=1""",
            (
                *global_resources,
                subject, start.isoformat(), through.isoformat(),
                subject, start.isoformat(), through.isoformat(),
            ),
        )
        for row in raw_rows:
            try:
                raw = self._repair_raw_bytes(row)
                if digest(raw) != row["sha256"]:
                    raise ValueError("raw_object_corrupt")
                if str(row["media_type"]) == "application/json":
                    payload, canonical = parse_provider_json_bytes(raw)
                    if row["profile_version"] == ACCOUNT_PROFILE_SEMANTIC_VERSION:
                        canonical = canonical_provider_json(
                            self._safe_account_payload(
                                str(row["resource_kind"]),
                                payload,
                            )
                        )
                    elif row["profile_version"] == DEVICE_REFERENCE_SEMANTIC_VERSION:
                        reference = self._device_reference_semantic_payload(
                            payload,
                            str(row["resource_kind"]),
                        )
                        if reference is None:
                            raise ValueError("raw_object_corrupt")
                        canonical = canonical_provider_json(reference)
                    elif row["profile_version"] is not None:
                        raise ValueError("raw_object_corrupt")
                    if digest(canonical) != row["payload_hash"]:
                        raise ValueError("raw_object_corrupt")
            except (OSError, ValueError, json.JSONDecodeError):
                self.repo.gap(conn, subject, row["resource_kind"], row["provider_object_id"], "", "validate", "raw_integrity", revision=int(row["id"]))
                receipt.counts["failed"] += 1
            else:
                conn.execute(
                    """UPDATE garmin_sync_gaps
                          SET status='resolved',resolved_at_utc=?,
                              last_attempt_at_utc=?
                        WHERE subject_id=? AND resource_kind=?
                          AND logical_object_key=?
                          AND stage='validate' AND reason_code='raw_integrity'
                          AND status IN ('open','deferred')""",
                    (
                        now, now, subject, row["resource_kind"],
                        row["provider_object_id"],
                    ),
                )
        # Field catalog drift remains discoverable in ``source_field_catalog``.
        # An unknown leaf is preserved verbatim in raw evidence and may be
        # reviewed later, but discovery alone is not a failed fetch or an
        # unresolved data gap.  In particular, do not recreate legacy
        # ``unmapped_field_signature`` gaps here: those would block unrelated
        # analysis despite there being no lost or invalid source data.
        # An activity has a durable summary and, where FIT has been requested,
        # an active parsed FIT revision.  This check never declares a FIT
        # mandatory: an existing FIT-stage gap is the evidence of intent.
        for row in conn.execute(
            """SELECT a.id,a.provider_activity_id,a.local_date
                 FROM activities a WHERE a.subject_id=? AND a.provider='garmin'
                   AND a.local_date BETWEEN ? AND ? AND a.provider_state='active'
                   AND NOT EXISTS (SELECT 1 FROM activity_source_revisions ar
                                   WHERE ar.activity_id=a.id AND ar.source_role='summary_json'
                                     AND ar.is_active=1)""",
            (subject, start.isoformat(), through.isoformat()),
        ):
            self.repo.gap(conn, subject, "activity_summary", f"garmin:activity:{row['provider_activity_id']}", row["local_date"], "audit", "activity_summary_missing")
        receipt.counts["fetched"] += 1

    def _repair_raw_bytes(self, row: sqlite3.Row) -> bytes:
        root = self.config.raw_root.parent.resolve()
        path = (root / str(row["relative_path"])).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("raw_object_corrupt")
        raw = path.read_bytes()
        if "size_bytes" in row.keys() and len(raw) != int(row["size_bytes"]):
            raise ValueError("raw_object_corrupt")
        return raw

    @staticmethod
    def _repair_day(provider_object_id: str, request: SyncRequest) -> str | None:
        matches = re.findall(r"\d{4}-\d{2}-\d{2}", provider_object_id)
        if matches:
            return matches[-1]
        return request.through_local_date or request.health_from_local_date

    @staticmethod
    def _activity_id_matches(provider_object_id: str, activity_id: str) -> bool:
        """Match activity ids as complete colon-delimited key segments."""
        return (
            provider_object_id == activity_id
            or provider_object_id.endswith(f":{activity_id}")
            or f":{activity_id}:" in provider_object_id
        )

    @staticmethod
    def _repair_range_dates(
        resource: str, provider_object_id: str, request: SyncRequest,
    ) -> tuple[date, date]:
        """Recover a bounded range key without guessing an endpoint day."""
        match = re.fullmatch(
            rf"garmin:health:{re.escape(resource)}:(\d{{4}}-\d{{2}}-\d{{2}}):(\d{{4}}-\d{{2}}-\d{{2}})",
            provider_object_id,
        )
        if match is None:
            raise ValueError("repair_range_key_invalid")
        start, end = (date.fromisoformat(value) for value in match.groups())
        if start > end:
            raise ValueError("repair_range_invalid_bounds")
        if request.health_from_local_date and start < date.fromisoformat(request.health_from_local_date):
            raise ValueError("repair_range_before_request")
        if request.through_local_date and end > date.fromisoformat(request.through_local_date):
            raise ValueError("repair_range_after_request")
        return start, end

    def _offline_repair(self, conn: sqlite3.Connection, run: int, subject: int, request: SyncRequest, receipt: SyncReceipt) -> None:
        resources = set(request.resource_kinds)
        if "activities" in resources:
            resources.remove("activities")
            resources.update(ACTIVITY_RESOURCE_KINDS)
        activity_ids = set(request.activity_ids)
        rows = list(conn.execute(
            """SELECT r.id,r.resource_kind,r.provider_object_id,r.is_current,r.parsed_at_utc,
                      r.payload_hash,o.relative_path,o.sha256,o.size_bytes
                 FROM source_revisions r JOIN raw_objects o ON o.id=r.raw_object_id
                WHERE r.provider='garmin'
                ORDER BY r.resource_kind,r.provider_object_id,r.revision_no DESC"""
        ))
        gap_filters = [
            "subject_id=?", "status IN ('open','deferred')",
            "source_revision_id IS NOT NULL",
        ]
        gap_parameters: list[Any] = [subject]
        if request.health_from_local_date:
            gap_filters.append("window_end_local_date>=?")
            gap_parameters.append(request.health_from_local_date)
        if request.through_local_date:
            gap_filters.append("window_start_local_date<=?")
            gap_parameters.append(request.through_local_date)
        gap_revision_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT source_revision_id FROM garmin_sync_gaps "
                f"WHERE {' AND '.join(gap_filters)}",
                gap_parameters,
            )
        }
        scoped_activity_revision_ids: set[int] | None = None
        if request.health_from_local_date or request.through_local_date:
            lower = request.health_from_local_date or "0001-01-01"
            upper = request.through_local_date or "9999-12-31"
            scoped_activity_revision_ids = {
                int(row[0])
                for row in conn.execute(
                    "SELECT ar.source_revision_id FROM activity_source_revisions ar "
                    "JOIN activities a ON a.id=ar.activity_id "
                    "WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ?",
                    (subject, lower, upper),
                )
            }
        eligible_rows = [
            row for row in rows
            if (not resources or str(row["resource_kind"]) in resources)
            and (
                scoped_activity_revision_ids is None
                or str(row["resource_kind"]) not in ACTIVITY_RESOURCE_KINDS
                or int(row["id"]) in scoped_activity_revision_ids
            )
            and (
                not activity_ids
                or any(
                    self._activity_id_matches(
                        str(row["provider_object_id"]), activity_id,
                    )
                    for activity_id in activity_ids
                )
            )
        ]
        # A revision-linked unresolved gap is precise recovery evidence.  Do
        # not rebuild adjacent/current revisions from the same resource while
        # such evidence exists in the requested window.
        gap_rows = [row for row in eligible_rows if int(row["id"]) in gap_revision_ids]
        if gap_rows:
            selected = {
                int(row["id"]): row
                for row in gap_rows
            }
        else:
            # Without an unresolved revision-linked gap, explicit reparse is a
            # safe rebuild of the newest revision for each logical object.
            selected = {}
            for row in eligible_rows:
                selected.setdefault(
                    (str(row["resource_kind"]), str(row["provider_object_id"])), row,
                )
        for row in selected.values():
            resource, key, revision = str(row["resource_kind"]), str(row["provider_object_id"]), int(row["id"])
            day = self._repair_day(key, request) or ""
            resolved_range_days: list[str] = []
            try:
                raw = self._repair_raw_bytes(row)
                if digest(raw) != row["sha256"]:
                    raise ValueError("raw_object_corrupt")
                conn.execute("BEGIN IMMEDIATE")
                if request.repair_strategy == "reconcile":
                    if resource == "activity_fit" or resource == "activity_summary":
                        activity_id = key.removeprefix("garmin:activity:")
                        activity = conn.execute("SELECT id,local_date FROM activities WHERE provider='garmin' AND provider_activity_id=?", (activity_id,)).fetchone()
                        if activity is None:
                            raise ValueError("activity_missing")
                        self._reconcile_activity(conn, run, subject, activity_id, int(activity["id"]), date.fromisoformat(activity["local_date"]), receipt)
                    else:
                        # Non-activity source selection has one current raw
                        # source.  Persist a deterministic check, not a fake
                        # canonical rewrite.
                        conn.execute("INSERT INTO reconciliation_results(entity_type,entity_id,field_key,left_source_revision_id,right_source_revision_id,result,checked_at_utc) VALUES(?,?,?,?,?,?,?)", ("source_revision", revision, "canonical_source", revision, revision, "match", utc_now()))
                    conn.execute("COMMIT")
                    receipt.counts["unchanged"] += 1
                    continue
                if resource == "activity_fit":
                    activity_id = key.removeprefix("garmin:activity:")
                    activity = conn.execute("SELECT id,local_date FROM activities WHERE provider='garmin' AND provider_activity_id=?", (activity_id,)).fetchone()
                    if activity is None:
                        raise ValueError("activity_missing")
                    local_activity_id = int(activity["id"])
                    # Rebuild the revision-bound FIT projection inside this
                    # transaction.  A parser failure rolls the deletes back,
                    # so the prior canonical/current projection remains
                    # available rather than becoming half-reparsed.
                    segment_ids = [
                        int(item[0]) for item in conn.execute(
                            """SELECT id FROM activity_segments
                               WHERE activity_id=? AND source_revision_id=?""",
                            (local_activity_id, revision),
                        )
                    ]
                    if segment_ids:
                        placeholders = ",".join("?" for _ in segment_ids)
                        conn.execute(
                            f"DELETE FROM climbing_routes WHERE segment_id IN ({placeholders})",
                            segment_ids,
                        )
                        conn.execute(
                            f"DELETE FROM strength_sets WHERE segment_id IN ({placeholders})",
                            segment_ids,
                        )
                    for table in (
                        "activity_samples", "activity_aux_messages",
                        "fit_metric_definitions", "activity_devices",
                        "fit_unknown_message_catalog",
                    ):
                        conn.execute(
                            f"DELETE FROM {table} WHERE source_revision_id=?",
                            (revision,),
                        )
                    conn.execute(
                        "DELETE FROM activity_segments WHERE activity_id=? AND source_revision_id=?",
                        (local_activity_id, revision),
                    )
                    conn.execute(
                        """DELETE FROM activity_metric_sources
                           WHERE activity_id=?
                             AND source_kind IN ('standard_fit','developer_fit')""",
                        (local_activity_id,),
                    )
                    conn.execute(
                        "DELETE FROM course_points WHERE activity_id=? AND course_identity='fit'",
                        (local_activity_id,),
                    )
                    activity_state = conn.execute(
                        "SELECT extras_json,source_map_json FROM activities WHERE id=?",
                        (local_activity_id,),
                    ).fetchone()
                    extras = json.loads(activity_state["extras_json"] or "{}")
                    source_map = json.loads(activity_state["source_map_json"] or "{}")
                    extras.pop("fit_session", None)
                    extras["fit_sessions"] = []
                    source_map.pop("fit_session", None)
                    source_map.pop("fit_sessions", None)
                    conn.execute(
                        "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
                        (
                            json.dumps(extras, sort_keys=True, allow_nan=False),
                            json.dumps(source_map, sort_keys=True, allow_nan=False),
                            local_activity_id,
                        ),
                    )
                    self._project_fit(conn, local_activity_id, raw, revision)
                    conn.execute(
                        """UPDATE activity_source_revisions SET is_active=0
                           WHERE activity_id=? AND source_role='activity_fit'""",
                        (local_activity_id,),
                    )
                    conn.execute(
                        """INSERT INTO activity_source_revisions(
                               activity_id,source_revision_id,source_role,is_active
                           ) VALUES(?,?,?,1)
                           ON CONFLICT(activity_id,source_revision_id,source_role)
                           DO UPDATE SET is_active=1""",
                        (local_activity_id, revision, "activity_fit"),
                    )
                    self._promote_fit_canonical(conn, local_activity_id, revision)
                    day = str(activity["local_date"])
                elif resource == "activity_summary":
                    payload, _canonical = parse_provider_json_bytes(raw)
                    validated = self._validate_activity_summary(payload, key)
                    local_activity_id = self._project_activity(
                        conn, subject, key, validated["normalized_summary"], validated, revision
                    )
                    conn.execute(
                        """UPDATE activity_source_revisions SET is_active=1
                           WHERE activity_id=? AND source_revision_id=?
                             AND source_role='summary_json'""",
                        (local_activity_id, revision),
                    )
                    day = str(validated["local_date"])
                # Repairs follow the active health whitelist as well as the
                # normal collection planner.  Historical gaps for excluded
                # endpoints remain auditable but cannot silently re-enable
                # those provider calls.
                elif resource in COLLECTED_HEALTH_RESOURCES:
                    payload, _canonical = parse_provider_json_bytes(raw)
                    spec = RESOURCE_CATALOG[resource]
                    if spec.scope == "range":
                        range_start, range_end = self._repair_range_dates(resource, key, request)
                        # Validate the entire immutable response before
                        # replacing a single day's canonical projection.
                        by_day = self._range_payload_by_day(
                            payload, range_start, range_end, resource=resource,
                        )
                        lactate_envelope = resource == "lactate_threshold" and isinstance(payload, dict) and any(
                            isinstance(payload.get(family), list)
                            for family in ("heart_rate", "power", "speed")
                        )
                        if lactate_envelope:
                            self.repo.fields(conn, resource, payload)
                        for current_day in (
                            range_start + timedelta(index)
                            for index in range((range_end - range_start).days + 1)
                        ):
                            current_day_text = current_day.isoformat()
                            day_payload = by_day[current_day_text]
                            self._supersede_range_projection(
                                conn, subject, resource, current_day_text,
                            )
                            if not lactate_envelope:
                                self.repo.fields(conn, resource, day_payload)
                            count = (
                                self._project_health(
                                    conn, subject, resource, current_day_text,
                                    day_payload, revision,
                                )
                                if day_payload else 0
                            )
                            self.repo.coverage(
                                conn, subject, resource, current_day_text,
                                "fetched" if count > 0 else "empty", revision, count,
                            )
                            resolved_range_days.append(current_day_text)
                    else:
                        if not day:
                            raise ValueError("repair_date_unknown")
                        self.repo.fields(conn, resource, payload)
                        self._supersede_health_projection(conn, subject, resource, key, day)
                        count = self._project_health(conn, subject, resource, day, payload, revision)
                        self.repo.coverage(
                            conn, subject, resource, day,
                            "fetched" if count > 0 else "empty", revision, count,
                        )
                else:
                    # Archive-only resources still get their raw syntax and
                    # field signature verified; their existing projection is
                    # intentionally left untouched until a typed projector is
                    # available rather than guessed here.
                    payload, _canonical = parse_provider_json_bytes(raw)
                    self.repo.fields(conn, resource, payload)
                current = conn.execute("SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, key)).fetchone()
                if current is not None and int(current["id"]) != revision:
                    conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=?", (int(current["id"]),))
                conn.execute("UPDATE source_revisions SET is_current=1,parsed_at_utc=?,parser_version=? WHERE id=?", (utc_now(), PARSER_VERSION, revision))
                conn.execute("COMMIT")
                if resolved_range_days:
                    for resolved_day in resolved_range_days:
                        self.repo.resolve_gaps(
                            conn, subject, resource, resolved_day,
                            logical_object_key=key,
                        )
                elif day:
                    self.repo.resolve_gaps(conn, subject, resource, day)
                receipt.counts["revised"] += 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                self.repo.gap(conn, subject, resource, key, day, "reparse" if request.repair_strategy == "reparse" else "reconcile", "offline_repair_failed", revision=revision)
                receipt.counts["failed"] += 1

    def _status(self, receipt: SyncReceipt) -> SyncReceipt:
        conn = self.repo.connect(readonly=True)
        try:
            row = conn.execute("SELECT id FROM data_subjects WHERE subject_key=?", (self.config.subject_key,)).fetchone()
            if row is None:
                receipt.status = "succeeded"; receipt.completed_at_utc = utc_now(); return receipt
            subject = int(row["id"]); receipt.status = "succeeded"; receipt.open_gap_count = int(conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred')", (subject,)).fetchone()[0]); receipt.complete_through_by_resource = {row["resource_kind"]: row["complete_through_local_date"] for row in conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?", (subject,))}; receipt.completed_at_utc = utc_now(); return receipt
        finally: conn.close()

    def _auth(self, receipt: SyncReceipt) -> SyncReceipt:
        if self.transport is None:
            receipt.status = "auth_required"; receipt.errors.append({"code":"interactive_provider_required","resource":"auth","logical_object_key":"garmin:account:identity","summary":"no credential provider"})
        else:
            self.transport.login()
            identity = self._identity_hmac(self.transport.identity())
            conn = self.repo.connect()
            try:
                subject = self.repo.subject(conn)
                existing = conn.execute("SELECT subject_id FROM subject_identities WHERE provider='garmin' AND identity_kind='account' AND identity_hmac=?", (identity,)).fetchone()
                if existing and int(existing["subject_id"]) != subject:
                    receipt.status = "failed"; receipt.errors.append({"code":"identity_mismatch","resource":"auth","logical_object_key":"garmin:account:identity","summary":"identity mismatch"})
                else:
                    now = utc_now()
                    conn.execute("INSERT OR IGNORE INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,1,?,?)", (subject, "garmin", "account", identity, now, now))
                    conn.execute("UPDATE subject_identities SET last_seen_at_utc=?,is_verified=1 WHERE provider='garmin' AND identity_kind='account' AND identity_hmac=?", (now, identity))
                    receipt.status = "succeeded"
            finally: conn.close()
        receipt.completed_at_utc = utc_now(); return receipt

    def _identity_hmac(self, identity: str) -> str:
        key_path = self.config.state_root / "secrets" / "garmin-identity.key"; key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not key_path.exists():
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try: os.write(fd, os.urandom(32))
            finally: os.close(fd)
        key = key_path.read_bytes(); os.chmod(key_path, 0o600)
        return hmac.new(key, identity.encode(), hashlib.sha256).hexdigest()

    def _transport(self) -> GarminTransport:
        if self.transport is None: raise GarminError("transport_not_configured")
        return self.transport

    def _validate(self, request: SyncRequest) -> None:
        if not 1 <= self.config.max_attempts <= 5: raise ValueError("max_attempts_out_of_range")
        if self.config.request_min_interval_ms < 0 or self.config.request_interval_jitter_ms < 0 or self.config.request_timeout_seconds <= 0 or self.config.retry_base_seconds <= 0 or self.config.retry_max_seconds <= 0 or self.config.inline_retry_after_max_seconds < 0 or self.config.rate_limit_fallback_seconds <= 0: raise ValueError("invalid_retry_configuration")
        if self.config.lookback_days < 1: raise ValueError("lookback_days_out_of_range")
        if self.config.max_repair_items_per_incremental < 0: raise ValueError("invalid_repair_item_limit")
        if request.mode not in {"auth","full","incremental","snapshot","repair","audit","status"}: raise ValueError("invalid_mode")
        if request.mode == "full" and not (request.health_from_local_date or self.config.history_start_date): raise ValueError("history_start_date_required")
        if request.mode == "incremental" and not self.config.history_start_date: raise ValueError("history_start_date_required")
        if request.mode == "repair" and not (request.health_from_local_date or request.through_local_date or request.resource_kinds or request.activity_ids): raise ValueError("repair_requires_scope")
        if request.mode == "snapshot" and request.through_local_date: raise ValueError("snapshot_uses_snapshot_date")
        if request.mode in {"auth", "status"} and any((request.health_from_local_date, request.through_local_date, request.snapshot_local_date, request.resource_kinds, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_requires_empty_scope")
        if request.mode in {"full", "incremental", "audit"} and any((request.snapshot_local_date, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_has_incompatible_parameters")
        if request.mode == "snapshot" and any((request.health_from_local_date, request.resource_kinds, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_has_incompatible_parameters")
        if request.mode == "repair" and request.snapshot_local_date:
            raise ValueError("mode_has_incompatible_parameters")
        if any(resource not in REQUEST_RESOURCE_KINDS for resource in request.resource_kinds):
            raise ValueError("resource_kind_invalid")
        excluded_health = set(HEALTH_RESOURCES) - set(COLLECTED_HEALTH_RESOURCES)
        if any(resource in excluded_health for resource in request.resource_kinds):
            raise ValueError("resource_kind_not_allowlisted")
        for value in (request.health_from_local_date, request.through_local_date, request.snapshot_local_date):
            if value: date.fromisoformat(value)
        if self.config.history_start_date:
            date.fromisoformat(self.config.history_start_date)
        today = self._today_local()
        if request.mode in {"full", "incremental"}:
            through = (
                date.fromisoformat(request.through_local_date)
                if request.through_local_date
                else today - timedelta(days=1)
            )
            if through >= today:
                raise ValueError("completed_mode_through_must_be_before_today")
            if request.mode == "full":
                start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or ""
                )
                if start > through:
                    raise ValueError("sync_range_start_after_through")
            elif date.fromisoformat(self.config.history_start_date or "") > through:
                raise ValueError("sync_range_start_after_through")
        if request.mode == "snapshot":
            snapshot_day = date.fromisoformat(
                request.snapshot_local_date or today.isoformat()
            )
            if snapshot_day > today:
                raise ValueError("snapshot_date_in_future")
        if request.mode in {"repair", "audit"}:
            through = date.fromisoformat(request.through_local_date) if request.through_local_date else today
            if through > today:
                raise ValueError("repair_or_audit_through_must_not_be_after_today")
            if request.health_from_local_date and date.fromisoformat(request.health_from_local_date) > through:
                raise ValueError("sync_range_start_after_through")
        schema_path = Path(__file__).resolve().parents[3] / "harness" / "schemas" / "garmin_sync_request.schema.json"
        payload = asdict(request); payload["resource_kinds"] = list(request.resource_kinds); payload["activity_ids"] = list(request.activity_ids)
        if list(Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).iter_errors(payload)): raise ValueError("invalid_sync_request_schema")

    @staticmethod
    def _validated_receipt(receipt: SyncReceipt) -> SyncReceipt:
        for error in receipt.errors:
            original = str(error.get("code") or "provider_error")
            safe = safe_provider_error_code(original)
            error["code"] = safe
            if safe != original:
                error["summary"] = "provider request failed"
        schema_path = Path(__file__).resolve().parents[3] / "harness" / "schemas" / "garmin_sync_receipt.schema.json"
        if list(Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).iter_errors(asdict(receipt))):
            raise RuntimeError("invalid_sync_receipt_schema")
        return receipt
