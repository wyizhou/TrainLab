"""Activity inventory, summaries, enrichment and reconciliation."""

from __future__ import annotations

from .contracts import *  # noqa: F403
from .lifecycle import ActivityInventoryObservation, next_activity_state


class ActivityCollectionMixin(GarminCollectionHost):
    def _activities(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        start: date,
        through: date,
        request: SyncRequest,
        receipt: SyncReceipt,
        collect_fit: bool = False,
    ) -> None:
        """L2-10 inventory and summary pipeline; FIT/enrichments are later units."""
        inventory_key = self._activity_inventory_key(request, start, through)
        if request.activity_ids:
            entries = [
                {"activityId": activity_id} for activity_id in request.activity_ids
            ]
            inventory_complete = False
        else:
            entries, inventory_complete = self._collect_activity_inventory(
                conn, run, subject, start, through, request, receipt, inventory_key
            )
        if not entries and not inventory_complete:
            return

        unique_entries: dict[str, dict[str, Any]] = {}
        duplicate = False
        for entry in entries:
            try:
                activity_id = self._activity_inventory_id(entry)
            except ValueError:
                inventory_complete = False
                duplicate = False
                break
            if activity_id in unique_entries:
                duplicate = True
                continue
            unique_entries[activity_id] = entry
        if duplicate:
            inventory_complete = False
            error = GarminError("activity_inventory_duplicate_ids")
            self.repo.item(
                conn,
                run,
                "activity_inventory",
                inventory_key,
                "validate",
                "failed",
                error=error,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activity_inventory",
                inventory_key,
                start.isoformat(),
                "validate",
                error.code,
                end_day=through.isoformat(),
            )
            receipt.counts["failed"] += 1

        applicable_ids: set[str] = set()
        for activity_id, entry in unique_entries.items():
            # Presence in a provider inventory is sufficient to protect or
            # reactivate an existing local activity even if summary refresh
            # later fails. Date bounds are applied by the state query itself.
            applicable_ids.add(activity_id)
            entry_day = self._activity_inventory_local_date(entry)
            if entry_day is not None and not self._activity_date_in_scope(
                entry_day, start, through, request.mode
            ):
                continue
            if self.budget_guard is not None:
                self.budget_guard.before_activity(activity_id)
            self._collect_activity_summary(
                conn,
                run,
                subject,
                activity_id,
                start,
                through,
                request,
                receipt,
                applicable_ids,
            )
            activity = conn.execute(
                "SELECT id,start_time_utc,sport,local_date FROM activities WHERE subject_id=? AND provider='garmin' AND provider_activity_id=?",
                (subject, activity_id),
            ).fetchone()
            if activity is not None:
                if collect_fit:
                    self._collect_activity_fit(
                        conn,
                        run,
                        subject,
                        activity_id,
                        int(activity["id"]),
                        str(activity["start_time_utc"]),
                        str(activity["sport"]),
                        date.fromisoformat(str(activity["local_date"])),
                        receipt,
                    )
                selected = set(request.resource_kinds)
                # Normal production collection keeps the activity surface
                # bounded: ORIGINAL FIT is the canonical activity source and
                # weather is the only automatic enrichment.  Other endpoint
                # roles remain available only when explicitly requested for a
                # repair or investigation.
                if not selected and collect_fit:
                    enrichments: tuple[tuple[str, str], ...] = (
                        DEFAULT_ACTIVITY_ENRICHMENTS
                    )
                else:
                    enrichments = tuple(
                        (resource, role)
                        for resource, role in ACTIVITY_ENRICHMENTS
                        if resource in selected
                    )
                for resource, role in enrichments:
                    self._collect_activity_enrichment(
                        conn,
                        run,
                        subject,
                        activity_id,
                        int(activity["id"]),
                        str(activity["sport"]),
                        date.fromisoformat(str(activity["local_date"])),
                        resource,
                        role,
                        receipt,
                    )
                # The chart/details endpoint is deliberately not a normal
                # fallback.  It may be fetched only by an explicit request.
                fallback_requested = "activity_details_fallback" in selected
                if fallback_requested and not self._has_active_fit(
                    conn, int(activity["id"])
                ):
                    self._collect_activity_chart_fallback(
                        conn,
                        run,
                        subject,
                        activity_id,
                        int(activity["id"]),
                        date.fromisoformat(str(activity["local_date"])),
                        receipt,
                    )
                self._reconcile_activity(
                    conn,
                    run,
                    subject,
                    activity_id,
                    int(activity["id"]),
                    date.fromisoformat(str(activity["local_date"])),
                    receipt,
                )

        absence_proven = self._inventory_absence_proven(request, inventory_complete)
        self._apply_activity_inventory_state(
            conn,
            subject,
            applicable_ids,
            start,
            through,
            request.mode,
            complete=inventory_complete,
            absence_proven=absence_proven,
            observation_id=inventory_key,
        )
        if inventory_complete:
            self.repo.capability(
                conn,
                subject,
                "activity_inventory",
                "supported",
                environment_key=self.config.region,
            )
            self._publish_activity_inventory_coverage(
                conn, subject, applicable_ids, start, through, request
            )

    @staticmethod
    def _activity_inventory_key(
        request: SyncRequest, start: date, through: date
    ) -> str:
        if request.mode == "full":
            return f"garmin:inventory:activities:full:through:{through.isoformat()}"
        return f"garmin:inventory:activities:{request.mode}:{start.isoformat()}:{through.isoformat()}"

    def _inventory_absence_proven(
        self, request: SyncRequest, inventory_complete: bool
    ) -> bool:
        """Only a bounded complete result or verified full paging proves absence."""

        if not inventory_complete or request.mode == "snapshot":
            return False
        if request.mode == "repair":
            return True
        if request.mode != "full" or self.budget_guard is not None:
            return False
        return callable(
            getattr(self._transport(), "activity_count", None)
        ) and callable(getattr(self._transport(), "activity_page", None))

    def _collect_activity_inventory(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        start: date,
        through: date,
        request: SyncRequest,
        receipt: SyncReceipt,
        inventory_key: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        transport = self._transport()
        entries: list[dict[str, Any]] = []
        signatures: set[str] = set()
        current_key = inventory_key
        current_stage = "discover"
        try:
            has_paging = (
                request.mode == "full"
                and self.budget_guard is None
                and callable(getattr(transport, "activity_count", None))
                and callable(getattr(transport, "activity_page", None))
            )
            if has_paging:
                count_key = f"{inventory_key}:count"
                current_key, current_stage = count_key, "discover"
                count = self._call(
                    lambda: transport.activity_count(),
                    conn=conn,
                    run=run,
                    subject=subject,
                    resource="activity_inventory",
                    key=count_key,
                    stage="discover",
                )
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise GarminError("activity_inventory_count_invalid")
                self.repo.item(
                    conn,
                    run,
                    "activity_inventory",
                    count_key,
                    "discover",
                    "fetched",
                    increment_attempt=False,
                )
                for page_no, offset in enumerate(range(0, count, 100)):
                    limit = min(100, count - offset)
                    page_key = f"{inventory_key}:page:{page_no:06d}"
                    current_key, current_stage = page_key, "fetch"
                    payload = self._call(
                        lambda o=offset, size=limit: transport.activity_page(o, size),
                        conn=conn,
                        run=run,
                        subject=subject,
                        resource="activity_inventory",
                        key=page_key,
                    )
                    current_stage = "validate"
                    page_entries, signature, _changed = (
                        self._archive_activity_inventory_page(
                            conn,
                            run,
                            receipt,
                            page_key,
                            payload,
                            expected_size=limit,
                        )
                    )
                    if signature in signatures:
                        raise GarminError("activity_inventory_paging_loop")
                    signatures.add(signature)
                    entries.extend(page_entries)
                # Preserve the successful empty page as raw inventory
                # evidence.  The full run itself is the observation identity.
                if count == 0:
                    page_key = f"{inventory_key}:page:000000"
                    current_key, current_stage = page_key, "validate"
                    page_entries, signature, _changed = (
                        self._archive_activity_inventory_page(
                            conn,
                            run,
                            receipt,
                            page_key,
                            [],
                            expected_size=0,
                        )
                    )
                    entries.extend(page_entries)
                    signatures.add(signature)
                final_key = f"{inventory_key}:count-final"
                current_key, current_stage = final_key, "discover"
                final_count = self._call(
                    lambda: transport.activity_count(),
                    conn=conn,
                    run=run,
                    subject=subject,
                    resource="activity_inventory",
                    key=final_key,
                    stage="discover",
                )
                if (
                    isinstance(final_count, bool)
                    or not isinstance(final_count, int)
                    or final_count != count
                ):
                    raise GarminError("activity_inventory_count_drift")
                self.repo.item(
                    conn,
                    run,
                    "activity_inventory",
                    final_key,
                    "discover",
                    "fetched",
                    increment_attempt=False,
                )
            else:
                page_key = f"{inventory_key}:page:000000"
                current_key, current_stage = page_key, "fetch"
                bounded_start = (
                    start.isoformat()
                    if self.budget_guard is not None
                    else (None if request.mode == "full" else start.isoformat())
                )
                payload = self._call(
                    lambda: list(
                        transport.list_activities(bounded_start, through.isoformat())
                    ),
                    conn=conn,
                    run=run,
                    subject=subject,
                    resource="activity_inventory",
                    key=page_key,
                )
                current_stage = "validate"
                entries, _signature, _changed = self._archive_activity_inventory_page(
                    conn,
                    run,
                    receipt,
                    page_key,
                    payload,
                    expected_size=None,
                )
            self.repo.item(
                conn,
                run,
                "activity_inventory",
                inventory_key,
                "discover",
                "fetched",
                increment_attempt=False,
            )
            return entries, True
        except GarminError as exc:
            if exc.http_status == 401:
                raise GarminError("auth_required", http_status=401) from None
            outcome = self._classify(exc)
            deferred = outcome.status == "deferred"
            retry = self._next_retry(exc, 0) if deferred else None
            terminal = (
                "forbidden"
                if outcome.status == "forbidden"
                else ("deferred" if deferred else "failed")
            )
            self.repo.item(
                conn,
                run,
                "activity_inventory",
                current_key,
                current_stage,
                terminal,
                error=exc,
                next_retry=retry,
                increment_attempt=False,
            )
            self.repo.item(
                conn,
                run,
                "activity_inventory",
                inventory_key,
                "discover",
                terminal,
                error=exc,
                next_retry=retry,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activity_inventory",
                current_key,
                start.isoformat(),
                current_stage,
                exc.code,
                end_day=through.isoformat(),
                deferred=deferred,
                next_retry=retry,
            )
            receipt.counts["deferred" if deferred else "failed"] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            return entries, False

    def _archive_activity_inventory_page(
        self,
        conn: sqlite3.Connection,
        run: int,
        receipt: SyncReceipt,
        page_key: str,
        payload: Any,
        *,
        expected_size: int | None,
    ) -> tuple[list[dict[str, Any]], str, bool]:
        page_box: dict[str, list[dict[str, Any]]] = {}

        def projector(_revision: int) -> None:
            page_box["entries"] = self._validate_activity_inventory_page(
                payload, expected_size
            )
            self.repo.fields(conn, "activity_inventory", payload)

        try:
            _, revision, changed = self.repo.archive(
                conn,
                "activity_inventory",
                page_key,
                canonical_provider_json(payload),
                "json",
                "application/json",
                projector,
            )
        except GarminError:
            raise
        except ValueError as exc:
            code = str(exc)
            if code not in {
                "activity_inventory_page_invalid",
                "activity_inventory_page_size_mismatch",
                "activity_inventory_id_invalid",
            }:
                code = "activity_inventory_page_invalid"
            raise GarminError(code) from None
        if not changed:
            page_box["entries"] = self._validate_activity_inventory_page(
                payload, expected_size
            )
        self.repo.item(
            conn,
            run,
            "activity_inventory",
            page_key,
            "fetch",
            "revised" if changed else "unchanged",
            revision_id=revision,
            increment_attempt=False,
        )
        receipt.counts["revised" if changed else "unchanged"] += 1
        return page_box["entries"], digest(canonical_provider_json(payload)), changed

    @staticmethod
    def _validate_activity_inventory_page(
        payload: Any, expected_size: int | None
    ) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict) and isinstance(payload.get("activities"), list):
            entries = payload["activities"]
        else:
            raise ValueError("activity_inventory_page_invalid")
        if expected_size is not None and len(entries) != expected_size:
            raise ValueError("activity_inventory_page_size_mismatch")
        result: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("activity_inventory_page_invalid")
            ActivityCollectionMixin._activity_inventory_id(entry)
            result.append(entry)
        return result

    @staticmethod
    def _activity_inventory_id(entry: dict[str, Any]) -> str:
        value = entry.get("activityId")
        if value is None:
            value = entry.get("id")
        if (
            isinstance(value, bool)
            or not isinstance(value, (str, int))
            or not str(value).strip()
        ):
            raise ValueError("activity_inventory_id_invalid")
        return str(value).strip()

    def _activity_inventory_local_date(self, entry: dict[str, Any]) -> str | None:
        for key in ("startTimeGMT", "startTimeUTC", "start_time_utc"):
            if entry.get(key) is not None:
                try:
                    return self._activity_time_utc(entry[key], local=False)[1]
                except GarminError:
                    return None
        for key in ("startTimeLocal", "calendarDate"):
            if entry.get(key) is not None:
                try:
                    return self._activity_time_utc(entry[key], local=True)[1]
                except GarminError:
                    return None
        return None

    @staticmethod
    def _activity_date_in_scope(
        local_date: str, start: date, through: date, mode: str
    ) -> bool:
        current = date.fromisoformat(local_date)
        return current <= through and (mode == "full" or current >= start)

    @staticmethod
    def _activity_time_utc(value: Any, *, local: bool) -> tuple[str, str]:
        if not isinstance(value, str) or not value.strip():
            raise GarminError("activity_summary_time_invalid")
        text = value.strip().replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            if len(text) != 10:
                raise GarminError("activity_summary_time_invalid") from None
            try:
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
            except ValueError:
                raise GarminError("activity_summary_time_invalid") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ if local else UTC)
        utc = parsed.astimezone(UTC)
        return utc.isoformat().replace("+00:00", "Z"), utc.astimezone(
            TZ
        ).date().isoformat()

    def _validate_activity_summary(
        self, summary: Any, activity_id: str
    ) -> dict[str, Any]:
        if not isinstance(summary, dict):
            raise GarminError("activity_summary_invalid")
        normalized = dict(summary)
        nested = summary.get("summaryDTO")
        if nested is not None:
            if not isinstance(nested, dict):
                raise GarminError("activity_summary_invalid")
            for key, value in nested.items():
                normalized.setdefault(key, value)
        if normalized.get("activityType") is None and isinstance(
            summary.get("activityTypeDTO"), dict
        ):
            normalized["activityType"] = summary["activityTypeDTO"]
        summary_id = normalized.get("activityId")
        if summary_id is None:
            summary_id = normalized.get("id")
        if isinstance(summary_id, bool) or str(summary_id).strip() != activity_id:
            raise GarminError("activity_summary_identity_mismatch")
        start_value = (
            normalized.get("startTimeGMT")
            or normalized.get("startTimeUTC")
            or normalized.get("start_time_utc")
        )
        start_utc, local_date = self._activity_time_utc(start_value, local=False)
        activity_type = normalized.get("activityType")
        if isinstance(activity_type, dict):
            sport = activity_type.get("typeKey")
            sub_sport = activity_type.get("subTypeKey")
        else:
            sport = activity_type
            sub_sport = normalized.get("activitySubType")
        if not isinstance(sport, str) or not sport.strip():
            raise GarminError("activity_summary_type_invalid")
        end_value = (
            normalized.get("endTimeGMT")
            or normalized.get("endTimeUTC")
            or normalized.get("end_time_utc")
        )
        end_utc = None
        if end_value is not None:
            end_utc, _ = self._activity_time_utc(end_value, local=False)
            if end_utc < start_utc:
                raise GarminError("activity_summary_time_invalid")
        return {
            "start_time_utc": start_utc,
            "end_time_utc": end_utc,
            "local_date": local_date,
            "sport": sport.strip(),
            "sub_sport": sub_sport.strip()
            if isinstance(sub_sport, str) and sub_sport.strip()
            else None,
            "normalized_summary": normalized,
        }

    @staticmethod
    def _summary_original_format(summary: Mapping[str, Any]) -> str | None:
        """Return only Garmin's declared ORIGINAL container format."""
        metadata = summary.get("metadataDTO")
        if not isinstance(metadata, Mapping):
            return None
        file_format = metadata.get("fileFormat")
        if not isinstance(file_format, Mapping):
            return None
        value = file_format.get("formatKey")
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip().casefold()

    def _record_activity_original_format(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        summary: Mapping[str, Any],
        revision: int,
    ) -> None:
        """Keep the small reviewed format fact in activity extras.

        The complete provider summary remains in its immutable raw revision.
        This avoids copying metadata payloads into the canonical activity while
        allowing the FIT stage to distinguish FIT from TCX/GPX deterministically.
        """
        original_format = self._summary_original_format(summary)
        if original_format is None:
            return
        row = conn.execute(
            """SELECT id,extras_json,source_map_json FROM activities
               WHERE subject_id=? AND provider='garmin'
                 AND provider_activity_id=?""",
            (subject, provider_id),
        ).fetchone()
        if row is None:
            return
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        extras["connect_original_format"] = original_format
        source_map["connect_original_format"] = {
            "source_revision_id": revision,
            "source_role": "summary_json",
            "source_path": "/metadataDTO/fileFormat/formatKey",
        }
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                row["id"],
            ),
        )

    def _collect_activity_summary(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        activity_id: str,
        start: date,
        through: date,
        request: SyncRequest,
        receipt: SyncReceipt,
        applicable_ids: set[str],
    ) -> None:
        key = f"garmin:activity:{activity_id}"
        try:
            summary = self._call(
                lambda: self._transport().activity_summary(activity_id),
                conn=conn,
                run=run,
                subject=subject,
                resource="activity_summary",
                key=key,
            )
            validate_provider_json_payload(summary)
            self.repo.item(
                conn,
                run,
                "activity_summary",
                key,
                "fetch",
                "fetched",
                increment_attempt=False,
            )
            try:
                validated = self._validate_activity_summary(summary, activity_id)
            except GarminError as validation_error:

                def rejected_summary(
                    _revision: int, error: GarminError = validation_error
                ) -> None:
                    raise error

                try:
                    self.repo.archive(
                        conn,
                        "activity_summary",
                        activity_id,
                        canonical_provider_json(summary),
                        "json",
                        "application/json",
                        rejected_summary,
                    )
                except GarminError:
                    pass
                raise validation_error
            if not self._activity_date_in_scope(
                validated["local_date"], start, through, request.mode
            ):
                return
            applicable_ids.add(activity_id)

            def summary_projector(revision: int) -> None:
                self._project_activity(
                    conn,
                    subject,
                    activity_id,
                    validated["normalized_summary"],
                    validated,
                    revision,
                )

            _, revision, changed = self.repo.archive(
                conn,
                "activity_summary",
                activity_id,
                canonical_provider_json(summary),
                "json",
                "application/json",
                summary_projector,
            )
            self._record_activity_original_format(
                conn,
                subject,
                activity_id,
                summary,
                revision,
            )
            if not changed:
                self._set_activity_active(conn, subject, activity_id)
            self.repo.item(
                conn,
                run,
                "activity_summary",
                key,
                "project",
                "revised" if changed else "unchanged",
                revision_id=revision,
            )
            self.repo.resolve_gaps(
                conn,
                subject,
                "activity_summary",
                date.fromisoformat(validated["local_date"]).isoformat(),
                logical_object_key=key,
                stages=("fetch", "project"),
            )
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            if exc.http_status == 401:
                raise GarminError("auth_required", http_status=401) from None
            outcome = self._classify(exc)
            deferred = outcome.status == "deferred"
            retry = self._next_retry(exc, 0) if deferred else None
            terminal = (
                "forbidden"
                if outcome.status == "forbidden"
                else ("deferred" if deferred else "failed")
            )
            stage = "project" if exc.code.startswith("activity_summary_") else "fetch"
            self.repo.item(
                conn,
                run,
                "activity_summary",
                key,
                stage,
                terminal,
                error=exc,
                next_retry=retry,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activity_summary",
                key,
                start.isoformat(),
                stage,
                exc.code,
                end_day=through.isoformat(),
                deferred=deferred,
                next_retry=retry,
            )
            receipt.counts["deferred" if deferred else "failed"] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_summary_project_failed")
            self.repo.item(
                conn,
                run,
                "activity_summary",
                key,
                "project",
                "failed",
                error=error,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activity_summary",
                key,
                start.isoformat(),
                "project",
                error.code,
                end_day=through.isoformat(),
            )
            receipt.counts["failed"] += 1

    def _project_activity(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        summary: dict[str, Any],
        validated: dict[str, Any],
        revision: int,
    ) -> int:
        existing = conn.execute(
            """SELECT extras_json,source_map_json FROM activities
               WHERE provider='garmin' AND provider_activity_id=?""",
            (provider_id,),
        ).fetchone()
        extras = json.loads(existing["extras_json"] or "{}") if existing else {}
        source_map = json.loads(existing["source_map_json"] or "{}") if existing else {}
        reviewed_summary_keys = (
            "activityId",
            "id",
            "activityName",
            "activityType",
            "activitySubType",
            "startTimeGMT",
            "startTimeUTC",
            "start_time_utc",
            "endTimeGMT",
            "endTimeUTC",
            "end_time_utc",
            "duration",
            "elapsedDuration",
            "movingDuration",
            "timerTime",
            "distance",
            "calories",
            "aerobicTrainingEffect",
            "anaerobicTrainingEffect",
            "trainingEffect",
            "uploadDate",
            "eventType",
            "privacy",
        )
        extras["connect_summary"] = {
            key: summary[key] for key in reviewed_summary_keys if key in summary
        }
        extras["connect_summary_revision_id"] = revision
        source_map["summary"] = revision
        for field_key in (
            "provider_activity_id",
            "name",
            "sport",
            "sub_sport",
            "start_time_utc",
            "local_date",
            "elapsed_seconds",
            "timer_seconds",
            "distance_m",
            "provider_state",
        ):
            source_map[field_key] = {
                "source_revision_id": revision,
                "source_role": "summary_json",
            }
        if validated["end_time_utc"] is not None:
            source_map["end_time_utc"] = {
                "source_revision_id": revision,
                "source_role": "summary_json",
                "method": "provider_explicit",
                "confidence": 1.0,
            }
            extras.pop("end_time_inference", None)
        else:
            source_map.pop("end_time_utc", None)
        conn.execute(
            """INSERT INTO activities(
                   subject_id,provider,provider_activity_id,name,sport,sub_sport,
                   start_time_utc,end_time_utc,local_date,elapsed_seconds,timer_seconds,
                   distance_m,extras_json,source_map_json,primary_revision_id,provider_state,
                   first_missing_at_utc,last_missing_at_utc,provider_deleted_at_utc
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',NULL,NULL,NULL)
               ON CONFLICT(provider,provider_activity_id) DO UPDATE SET
                   subject_id=excluded.subject_id,name=excluded.name,sport=excluded.sport,
                   sub_sport=excluded.sub_sport,start_time_utc=excluded.start_time_utc,
                   end_time_utc=excluded.end_time_utc,local_date=excluded.local_date,
                   elapsed_seconds=excluded.elapsed_seconds,timer_seconds=excluded.timer_seconds,
                   distance_m=excluded.distance_m,extras_json=excluded.extras_json,
                   source_map_json=excluded.source_map_json,
                   primary_revision_id=excluded.primary_revision_id,provider_state='active',
                   first_missing_at_utc=NULL,last_missing_at_utc=NULL,provider_deleted_at_utc=NULL""",
            (
                subject,
                "garmin",
                provider_id,
                summary.get("activityName"),
                validated["sport"],
                validated["sub_sport"],
                validated["start_time_utc"],
                validated["end_time_utc"],
                validated["local_date"],
                summary.get("elapsedDuration", summary.get("duration")),
                summary.get("timerTime", summary.get("duration")),
                summary.get("distance"),
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                revision,
            ),
        )
        activity = int(
            conn.execute(
                "SELECT id FROM activities WHERE provider='garmin' AND provider_activity_id=?",
                (provider_id,),
            ).fetchone()[0]
        )
        conn.execute(
            "UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='summary_json'",
            (activity,),
        )
        conn.execute(
            """INSERT INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?,?,1)
               ON CONFLICT(activity_id,source_revision_id,source_role)
               DO UPDATE SET is_active=1""",
            (activity, revision, "summary_json"),
        )
        return activity

    @staticmethod
    def _set_activity_active(
        conn: sqlite3.Connection, subject: int, provider_id: str
    ) -> None:
        conn.execute(
            """UPDATE activities SET provider_state='active',first_missing_at_utc=NULL,
                      last_missing_at_utc=NULL,provider_deleted_at_utc=NULL
               WHERE subject_id=? AND provider='garmin' AND provider_activity_id=?""",
            (subject, provider_id),
        )

    @staticmethod
    def _has_active_fit(conn: sqlite3.Connection, activity: int) -> bool:
        return (
            conn.execute(
                """SELECT 1 FROM activity_source_revisions ar
               JOIN source_revisions sr ON sr.id=ar.source_revision_id
               WHERE ar.activity_id=? AND ar.source_role='activity_fit'
                 AND ar.is_active=1 AND sr.is_current=1
                 AND sr.parsed_at_utc IS NOT NULL""",
                (activity,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _activity_enrichment_applicable(resource: str, sport: str) -> bool:
        normalized = sport.casefold()
        if resource == "activity_exercise_sets":
            return "strength" in normalized
        if resource == "activity_power_zones":
            return any(
                token in normalized
                for token in (
                    "cycling",
                    "running",
                    "rowing",
                    "ski",
                    "multisport",
                    "triathlon",
                )
            )
        if resource == "activity_weather":
            # Keep a weather observation attempt for every activity. Indoor,
            # pool and strength activities may legitimately produce a null or
            # not-available result, but skipping the provider call would make
            # the all-activity weather policy impossible to audit.
            return True
        return True

    @staticmethod
    def _validate_activity_enrichment_binding(
        conn: sqlite3.Connection,
        subject: int,
        activity: int,
        provider_id: str,
        payload: Any,
    ) -> None:
        row = conn.execute(
            """SELECT subject_id,provider,provider_activity_id
               FROM activities WHERE id=?""",
            (activity,),
        ).fetchone()
        if (
            row is None
            or int(row["subject_id"]) != subject
            or row["provider"] != "garmin"
            or str(row["provider_activity_id"]) != provider_id
        ):
            raise GarminError("activity_enrichment_binding_mismatch")
        if payload is not None and not isinstance(payload, (dict, list)):
            raise GarminError("activity_enrichment_invalid")
        if isinstance(payload, dict):
            for key in ("activityId", "activityID", "activity_id"):
                if key not in payload:
                    continue
                value = payload[key]
                if isinstance(value, bool) or str(value).strip() != provider_id:
                    raise GarminError("activity_enrichment_identity_mismatch")

    @staticmethod
    def _enrichment_state(payload: Any) -> str:
        if payload is None:
            return "null"
        if payload == {}:
            return "empty_object"
        if payload == []:
            return "empty_array"
        return "value"

    @staticmethod
    def _reviewed_enrichment_payload(role: str, payload: Any) -> Any:
        keys = {
            "hr_zones_json": {
                "zoneNumber",
                "zone",
                "secsInZone",
                "seconds",
                "zoneLowBoundary",
                "zoneHighBoundary",
                "lowBoundary",
                "highBoundary",
            },
            "power_zones_json": {
                "zoneNumber",
                "zone",
                "secsInZone",
                "seconds",
                "zoneLowBoundary",
                "zoneHighBoundary",
                "lowBoundary",
                "highBoundary",
            },
            "weather_json": {
                "temp",
                "temperature",
                "apparentTemperature",
                "dewPoint",
                "relativeHumidity",
                "humidity",
                "windSpeed",
                "windDirection",
                "weatherType",
                "issueDate",
                "observationTime",
            },
            "gear_json": {
                "gearPk",
                "uuid",
                "displayName",
                "gearTypeName",
                "modelName",
                "brandName",
                "customMakeModel",
            },
        }.get(role)
        if keys is None:
            return None

        def reviewed(value: Any) -> Any:
            if isinstance(value, list):
                return [
                    reviewed(item) for item in value if isinstance(item, (dict, list))
                ]
            if isinstance(value, dict):
                return {
                    key: value[key]
                    for key in keys
                    if key in value and not isinstance(value[key], (dict, list))
                }
            return None

        if isinstance(payload, dict):
            for container_key in (
                "zones",
                "timeInZones",
                "weather",
                "gear",
                "activityGear",
            ):
                if container_key in payload and isinstance(
                    payload[container_key], (dict, list)
                ):
                    return reviewed(payload[container_key])
        return reviewed(payload)

    @staticmethod
    def _payload_rows(payload: Any, keys: tuple[str, ...]) -> tuple[list[Any], bool]:
        """Return source-index-preserving rows plus an invalid-container flag."""
        if isinstance(payload, list):
            return payload, False
        if not isinstance(payload, dict):
            return [], False
        for key in keys:
            if key not in payload:
                continue
            value = payload[key]
            return (value, False) if isinstance(value, list) else ([], True)
        return [], False

    @staticmethod
    def _json_number(value: Any) -> float | int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value if math.isfinite(float(value)) else None

    def _json_timestamp(self, value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            seconds = (
                float(value) / 1000.0
                if abs(float(value)) >= 10_000_000_000
                else float(value)
            )
            try:
                return (
                    datetime.fromtimestamp(seconds, UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str) and value.strip():
            try:
                return self._activity_time_utc(value, local=False)[0]
            except GarminError:
                return None
        return None

    @staticmethod
    def _row_value(
        row: dict[str, Any],
        keys: tuple[str, ...],
    ) -> tuple[bool, Any]:
        for key in keys:
            if key in row:
                return True, row[key]
        return False, None

    def _prepare_typed_split_row(
        self,
        item: Any,
        source_index: int,
        sport: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(item, dict):
            return None, "row_not_object"
        invalid = False
        semantic = False
        route_semantic = False

        split_type_present, split_type_value = self._row_value(
            item, ("splitType", "type")
        )
        split_type: str | None = None
        if split_type_present and split_type_value is not None:
            if not isinstance(split_type_value, str) or not split_type_value.strip():
                invalid = True
            else:
                split_type = split_type_value.strip()
                semantic = True

        route_name_present, route_name_value = self._row_value(item, ("routeName",))
        route_name: str | None = None
        if route_name_present and route_name_value is not None:
            if not isinstance(route_name_value, str) or not route_name_value.strip():
                invalid = True
            else:
                route_name = route_name_value.strip()
                semantic = True

        start_present, start_value = self._row_value(
            item,
            ("startTimeGMT", "startTime", "startTimestamp"),
        )
        end_present, end_value = self._row_value(
            item,
            ("endTimeGMT", "endTime", "endTimestamp"),
        )
        start = (
            self._json_timestamp(start_value)
            if start_present and start_value is not None
            else None
        )
        end = (
            self._json_timestamp(end_value)
            if end_present and end_value is not None
            else None
        )
        if start_present and start_value is not None:
            if start is None:
                invalid = True
            else:
                semantic = True
        if end_present and end_value is not None:
            if end is None:
                invalid = True
            else:
                semantic = True
        if start is not None and end is not None and end < start:
            invalid = True

        def number(
            keys: tuple[str, ...],
            *,
            integer: bool = False,
            route: bool = False,
        ) -> float | int | None:
            nonlocal invalid, semantic, route_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                or (integer and not isinstance(value, int))
            ):
                invalid = True
                return None
            semantic = True
            route_semantic = route_semantic or route
            return value

        duration = number(("duration", "durationSeconds"))
        distance = number(("distance", "distanceMeters"))
        falls = number(("falls",), integer=True, route=True)
        ascent = number(("ascentMeters", "elevationGain"), route=True)

        completed_present, completed_value = self._row_value(item, ("completed",))
        completed: int | None = None
        if completed_present and completed_value is not None:
            if isinstance(completed_value, bool):
                completed = int(completed_value)
            elif (
                isinstance(completed_value, int)
                and not isinstance(completed_value, bool)
                and completed_value in {0, 1}
            ):
                completed = completed_value
            else:
                invalid = True
            if completed is not None:
                semantic = True
                route_semantic = True

        grade_present, grade = self._row_value(
            item, ("gradeRaw", "grade", "gradeValue")
        )
        if grade_present and grade is not None:
            if (
                isinstance(grade, bool)
                or not isinstance(grade, (str, int, float))
                or (isinstance(grade, str) and not grade.strip())
                or (isinstance(grade, float) and not math.isfinite(grade))
            ):
                invalid = True
            else:
                semantic = True
                route_semantic = True
        grade_system_present, grade_system_value = self._row_value(
            item, ("gradeSystem",)
        )
        grade_system: str | None = None
        if grade_system_present and grade_system_value is not None:
            if (
                not isinstance(grade_system_value, str)
                or not grade_system_value.strip()
            ):
                invalid = True
            else:
                grade_system = grade_system_value.strip()
                semantic = True
                route_semantic = True
        grade_display_present, grade_display_value = self._row_value(
            item, ("gradeDisplay",)
        )
        grade_display: str | None = None
        if grade_display_present and grade_display_value is not None:
            if (
                not isinstance(grade_display_value, str)
                or not grade_display_value.strip()
            ):
                invalid = True
            else:
                grade_display = grade_display_value.strip()
                semantic = True
                route_semantic = True

        if invalid:
            return None, "reviewed_field_invalid"
        if not semantic:
            return None, "unknown_only"
        climbing = any(token in sport.casefold() for token in ("climb", "boulder"))
        is_rest = split_type is not None and "rest" in split_type.casefold()
        kind = (
            ("climb_rest" if is_rest else "climb_active")
            if climbing or route_semantic
            else "split"
        )
        return {
            "source_index": source_index,
            "segment_type": kind,
            "start": start,
            "end": end,
            "duration": duration,
            "distance": distance,
            "split_type": split_type,
            "route_name": route_name,
            "route_semantic": route_semantic,
            "grade": grade if grade_present else None,
            "grade_system": grade_system,
            "grade_display": grade_display,
            "completed": completed,
            "falls": falls,
            "ascent": ascent,
        }, None

    def _project_typed_splits(
        self,
        conn: sqlite3.Connection,
        activity: int,
        sport: str,
        payload: Any,
        revision: int,
    ) -> dict[str, Any]:
        items, container_invalid = self._payload_rows(
            payload,
            ("typedSplits", "activityTypedSplits", "activitySplits", "splits"),
        )
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, item in enumerate(items):
            row, reason = self._prepare_typed_split_row(item, source_index, sport)
            if row is None:
                reasons[reason or "invalid"] = reasons.get(reason or "invalid", 0) + 1
            else:
                prepared.append(row)
        for item in prepared:
            extras = {
                "source_role": "typed_splits_json",
                "source_revision_id": revision,
                "source_index": item["source_index"],
            }
            if item["split_type"] is not None:
                extras["splitType"] = item["split_type"]
            if item["route_name"] is not None:
                extras["routeName"] = item["route_name"]
            conn.execute(
                """INSERT OR IGNORE INTO activity_segments(
                       activity_id,segment_type,segment_index,start_time_utc,
                       end_time_utc,duration_seconds,distance_m,extras_json,
                       source_revision_id
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    activity,
                    item["segment_type"],
                    item["source_index"],
                    item["start"],
                    item["end"],
                    item["duration"],
                    item["distance"],
                    json.dumps(extras, sort_keys=True, allow_nan=False),
                    revision,
                ),
            )
            if item["segment_type"] != "climb_active" or not item["route_semantic"]:
                continue
            segment = conn.execute(
                """SELECT id FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                     AND segment_type=? AND segment_index=?""",
                (activity, revision, item["segment_type"], item["source_index"]),
            ).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO climbing_routes(
                       segment_id,grade_raw,grade_system,grade_display,
                       completed,falls,ascent_meters
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    int(segment["id"]),
                    str(item["grade"]) if item["grade"] is not None else None,
                    item["grade_system"],
                    item["grade_display"]
                    if item["grade_display"] is not None
                    else (str(item["grade"]) if item["grade"] is not None else None),
                    item["completed"],
                    item["falls"],
                    item["ascent"],
                ),
            )
        return {
            "received_row_count": len(items),
            "valid_row_count": len(prepared),
            "dropped_row_count": len(items) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }

    def _prepare_exercise_set_row(
        self,
        item: Any,
        source_index: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(item, dict):
            return None, "row_not_object"
        invalid = False
        semantic = False
        detail_semantic = False

        def text(keys: tuple[str, ...], *, detail: bool = False) -> str | None:
            nonlocal invalid, semantic, detail_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                invalid = True
                return None
            semantic = True
            detail_semantic = detail_semantic or detail
            return value.strip()

        def number(
            keys: tuple[str, ...],
            *,
            integer: bool = False,
            detail: bool = False,
        ) -> float | int | None:
            nonlocal invalid, semantic, detail_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                or (integer and not isinstance(value, int))
            ):
                invalid = True
                return None
            semantic = True
            detail_semantic = detail_semantic or detail
            return value

        set_type = text(("setType", "type"), detail=True)
        category = text(("exerciseCategory",), detail=True)
        exercise_name = text(("exerciseName",), detail=True)
        duration = number(("duration", "durationSeconds"), detail=True)
        repetitions = number(("repetitions", "reps"), integer=True, detail=True)
        weight = number(("weightKg", "weight"), detail=True)
        step = number(("workoutStepIndex",), integer=True, detail=True)
        raw_exercise = number(("exerciseNumber",), integer=True, detail=True)
        start_present, start_value = self._row_value(
            item,
            ("startTimeGMT", "startTime", "startTimestamp"),
        )
        end_present, end_value = self._row_value(
            item,
            ("endTimeGMT", "endTime", "endTimestamp"),
        )
        start = (
            self._json_timestamp(start_value)
            if start_present and start_value is not None
            else None
        )
        end = (
            self._json_timestamp(end_value)
            if end_present and end_value is not None
            else None
        )
        if start_present and start_value is not None:
            if start is None:
                invalid = True
            else:
                semantic = True
        if end_present and end_value is not None:
            if end is None:
                invalid = True
            else:
                semantic = True
        if start is not None and end is not None and end < start:
            invalid = True
        if invalid:
            return None, "reviewed_field_invalid"
        if not semantic:
            return None, "unknown_only"
        return {
            "source_index": source_index,
            "segment_type": (
                "strength_rest"
                if set_type is not None and "rest" in set_type.casefold()
                else "strength_active"
            ),
            "set_type": set_type,
            "category": category,
            "exercise_name": exercise_name,
            "duration": duration,
            "repetitions": repetitions,
            "weight": weight,
            "step": step,
            "raw_exercise": raw_exercise,
            "start": start,
            "end": end,
            "detail_semantic": detail_semantic,
        }, None

    def _project_exercise_sets(
        self,
        conn: sqlite3.Connection,
        activity: int,
        payload: Any,
        revision: int,
    ) -> dict[str, Any]:
        items, container_invalid = self._payload_rows(
            payload,
            ("exerciseSets", "activityExerciseSets", "sets"),
        )
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, item in enumerate(items):
            row, reason = self._prepare_exercise_set_row(item, source_index)
            if row is None:
                reasons[reason or "invalid"] = reasons.get(reason or "invalid", 0) + 1
            else:
                prepared.append(row)
        for item in prepared:
            conn.execute(
                """INSERT OR IGNORE INTO activity_segments(
                       activity_id,segment_type,segment_index,start_time_utc,
                       end_time_utc,duration_seconds,extras_json,source_revision_id
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    activity,
                    item["segment_type"],
                    item["source_index"],
                    item["start"],
                    item["end"],
                    item["duration"],
                    json.dumps(
                        {
                            "source_role": "exercise_sets_json",
                            "source_revision_id": revision,
                            "source_index": item["source_index"],
                        },
                        sort_keys=True,
                        allow_nan=False,
                    ),
                    revision,
                ),
            )
            if not item["detail_semantic"]:
                continue
            segment = conn.execute(
                """SELECT id FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                     AND segment_type=? AND segment_index=?""",
                (
                    activity,
                    revision,
                    item["segment_type"],
                    item["source_index"],
                ),
            ).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO strength_sets(
                       segment_id,workout_step_index,set_type,exercise_category,
                       raw_exercise_number,exercise_name,repetitions,weight_kg,
                       duration_seconds
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    int(segment["id"]),
                    item["step"],
                    item["set_type"],
                    item["category"],
                    item["raw_exercise"],
                    item["exercise_name"],
                    item["repetitions"],
                    item["weight"],
                    item["duration"],
                ),
            )
        return {
            "received_row_count": len(items),
            "valid_row_count": len(prepared),
            "dropped_row_count": len(items) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }

    def _project_activity_enrichment(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        activity: int,
        sport: str,
        resource: str,
        role: str,
        payload: Any,
        revision: int,
    ) -> None:
        self._validate_activity_enrichment_binding(
            conn,
            subject,
            activity,
            provider_id,
            payload,
        )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?",
            (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        reviewed = self._reviewed_enrichment_payload(role, payload)
        enrichments = extras.setdefault("connect_enrichments", {})
        enrichment_entry: dict[str, Any] = {
            "source_revision_id": revision,
            "state": self._enrichment_state(payload),
        }
        if reviewed is not None:
            enrichment_entry["reviewed"] = reviewed
        enrichments[role] = enrichment_entry
        extras["connect_enrichments"] = enrichments
        source_map[role] = {
            "source_revision_id": revision,
            "source_role": role,
            "state": self._enrichment_state(payload),
        }
        projection: dict[str, Any] | None = None
        if role == "typed_splits_json":
            projection = self._project_typed_splits(
                conn,
                activity,
                sport,
                payload,
                revision,
            )
        elif role == "exercise_sets_json":
            projection = self._project_exercise_sets(
                conn,
                activity,
                payload,
                revision,
            )
        if projection is not None:
            enrichment_entry["projection"] = projection
            issue_code = (
                "activity_typed_splits_drift"
                if role == "typed_splits_json"
                else "activity_exercise_sets_drift"
            )
            if projection["dropped_row_count"] > 0:
                self._set_activity_issue(
                    conn,
                    activity,
                    issue_code,
                    "warning",
                    {
                        "source_revision_id": revision,
                        **projection,
                    },
                    revision,
                )
            else:
                self._resolve_activity_issue(conn, activity, issue_code)
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            "UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role=?",
            (activity, role),
        )
        conn.execute(
            """INSERT OR IGNORE INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?,?,1)""",
            (activity, revision, role),
        )

    def _collect_activity_enrichment(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        sport: str,
        day: date,
        resource: str,
        role: str,
        receipt: SyncReceipt,
    ) -> None:
        key = f"garmin:activity:{provider_id}"
        if not self._activity_enrichment_applicable(resource, sport):
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "discover",
                "not_supported",
                error=GarminError("not_supported"),
                increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        method = getattr(self._transport(), "activity_extra", None)
        if not callable(method):
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "fetch",
                "not_supported",
                error=GarminError("not_supported"),
                increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        try:
            payload = self._call(
                lambda: method(provider_id, role),
                conn=conn,
                run=run,
                subject=subject,
                resource=resource,
                key=key,
                allows_404=True,
            )
            validate_provider_json_payload(payload)
            # Field-shape discovery belongs to the received response, even
            # when binding/project validation later leaves its revision
            # non-current.  Autocommit here survives projector rollback.
            self.repo.fields(conn, resource, payload)
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "fetch",
                "fetched",
                increment_attempt=False,
            )

            def projector(revision: int) -> None:
                self._project_activity_enrichment(
                    conn,
                    subject,
                    provider_id,
                    activity,
                    sport,
                    resource,
                    role,
                    payload,
                    revision,
                )

            _, revision, changed = self.repo.archive(
                conn,
                resource,
                provider_id,
                canonical_provider_json(payload),
                "json",
                "application/json",
                projector,
            )
            self.repo.resolve_gaps(
                conn,
                subject,
                resource,
                day.isoformat(),
                logical_object_key=key,
                stages=("fetch", "project"),
            )
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "project",
                "revised" if changed else "unchanged",
                revision_id=revision,
                increment_attempt=False,
            )
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            outcome = self._classify(exc, allows_404=True)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            terminal = (
                "not_supported"
                if exc.code == "not_supported"
                else "not_available"
                if outcome.status == "not_available"
                else "forbidden"
                if outcome.status == "forbidden"
                else "deferred"
                if outcome.status == "deferred"
                else "failed"
            )
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            stage = (
                "project" if exc.code.startswith("activity_enrichment_") else "fetch"
            )
            self.repo.item(
                conn,
                run,
                resource,
                key,
                stage,
                terminal,
                error=exc,
                next_retry=retry,
                increment_attempt=False,
            )
            if terminal not in {"not_available", "not_supported"}:
                self.repo.gap(
                    conn,
                    subject,
                    resource,
                    key,
                    day.isoformat(),
                    stage,
                    exc.code,
                    deferred=terminal == "deferred",
                    next_retry=retry,
                )
            self._count_receipt_terminal(receipt, terminal)
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_extra_project_failed")
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "project",
                "failed",
                error=error,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                resource,
                key,
                day.isoformat(),
                "project",
                error.code,
            )
            receipt.counts["failed"] += 1

    @staticmethod
    def _set_activity_issue(
        conn: sqlite3.Connection,
        activity: int,
        issue_code: str,
        severity: str,
        details: dict[str, Any],
        revision: int | None,
    ) -> None:
        now = utc_now()
        payload = json.dumps(details, sort_keys=True, allow_nan=False)
        row = conn.execute(
            """SELECT id FROM data_quality_issues
               WHERE entity_type='activity' AND entity_id=? AND issue_code=?
                 AND status='open' ORDER BY id DESC LIMIT 1""",
            (activity, issue_code),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO data_quality_issues(
                       entity_type,entity_id,issue_code,severity,details_json,
                       status,first_seen_at_utc,last_seen_at_utc,source_revision_id
                   ) VALUES('activity',?,?,?,?,'open',?,?,?)""",
                (activity, issue_code, severity, payload, now, now, revision),
            )
        else:
            conn.execute(
                """UPDATE data_quality_issues
                   SET severity=?,details_json=?,last_seen_at_utc=?,
                       source_revision_id=?
                   WHERE id=?""",
                (severity, payload, now, revision, int(row["id"])),
            )

    @staticmethod
    def _resolve_activity_issue(
        conn: sqlite3.Connection,
        activity: int,
        issue_code: str,
    ) -> None:
        now = utc_now()
        conn.execute(
            """UPDATE data_quality_issues
               SET status='resolved',resolved_at_utc=?,last_seen_at_utc=?
               WHERE entity_type='activity' AND entity_id=? AND issue_code=?
                 AND status='open'""",
            (now, now, activity, issue_code),
        )

    @staticmethod
    def _chart_rows(payload: Any) -> tuple[list[Any], bool]:
        if isinstance(payload, list):
            return payload, False
        if not isinstance(payload, dict):
            return [], False
        for key in ("chartData", "points", "samples"):
            if key in payload:
                value = payload[key]
                return (value, False) if isinstance(value, list) else ([], True)
        descriptors = payload.get("metricDescriptors")
        metrics = payload.get("activityDetailMetrics")
        if descriptors is None and metrics is None:
            return [], False
        if not isinstance(descriptors, list) or not isinstance(metrics, list):
            return [], True
        index_to_key: dict[int, str] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                continue
            index = descriptor.get("metricsIndex")
            metric_key = descriptor.get("key")
            if (
                isinstance(index, int)
                and not isinstance(index, bool)
                and isinstance(metric_key, str)
            ):
                index_to_key[index] = metric_key
        rows: list[Any] = []
        for entry in metrics:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("metrics"), list
            ):
                rows.append(entry)
                continue
            row = {
                key: entry["metrics"][index]
                for index, key in index_to_key.items()
                if index < len(entry["metrics"])
            }
            rows.append(row)
        return rows, False

    def _prepare_activity_chart(
        self,
        payload: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows, container_invalid = self._chart_rows(payload)
        aliases = {
            "timestamp_utc": (
                "directTimestamp",
                "timestamp",
                "time",
                "startGMT",
                "startTimeGMT",
            ),
            "latitude": ("directLatitude", "latitude", "lat"),
            "longitude": ("directLongitude", "longitude", "lon", "lng"),
            "distance_m": ("directDistance", "distance", "distanceMeters"),
            "speed_mps": ("directSpeed", "speed", "speedMetersPerSecond"),
            "altitude_m": ("directElevation", "elevation", "altitude"),
            "heart_rate_bpm": ("directHeartRate", "heartRate", "heartRateBpm"),
            "cadence_rpm": ("directDoubleCadence", "directCadence", "cadence"),
            "power_w": ("directPower", "power", "watts"),
            "temperature_c": ("directAirTemperature", "temperature", "temperatureC"),
        }
        nonnegative = {
            "distance_m",
            "speed_mps",
            "heart_rate_bpm",
            "cadence_rpm",
            "power_w",
        }
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, row in enumerate(rows):
            if not isinstance(row, dict):
                reasons["row_not_object"] = reasons.get("row_not_object", 0) + 1
                continue
            invalid = False
            semantic = False
            timestamp_present, timestamp_value = self._row_value(
                row,
                aliases["timestamp_utc"],
            )
            stamp = (
                self._json_timestamp(timestamp_value)
                if timestamp_present and timestamp_value is not None
                else None
            )
            if timestamp_present and timestamp_value is not None:
                if stamp is None:
                    invalid = True
                else:
                    semantic = True
            values: dict[str, float | int | None] = {}
            for field, field_aliases in aliases.items():
                if field == "timestamp_utc":
                    continue
                present, value = self._row_value(row, field_aliases)
                if not present or value is None:
                    values[field] = None
                    continue
                numeric = self._json_number(value)
                if numeric is None:
                    invalid = True
                    values[field] = None
                    continue
                if field in nonnegative and numeric < 0:
                    invalid = True
                elif field == "latitude" and not -90 <= numeric <= 90:
                    invalid = True
                elif field == "longitude" and not -180 <= numeric <= 180:
                    invalid = True
                else:
                    semantic = True
                values[field] = numeric
            if invalid:
                reason = "reviewed_field_invalid"
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            if not semantic:
                reason = "unknown_only"
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            prepared.append(
                {
                    "source_index": source_index,
                    "timestamp_utc": stamp,
                    "values": values,
                }
            )
        evidence = {
            "stream_kind": "connect_chart",
            "coverage": "partial",
            "requested_max_points": ACTIVITY_CHART_MAX_POINTS,
            "requested_max_polyline_points": ACTIVITY_CHART_MAX_POLYLINE_POINTS,
            "received_point_count": len(rows),
            "valid_point_count": len(prepared),
            "dropped_point_count": len(rows) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }
        return prepared, evidence

    def _project_activity_chart(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        payload: Any,
        revision: int,
        prepared: list[dict[str, Any]],
        evidence: dict[str, Any],
    ) -> int:
        self._validate_activity_enrichment_binding(
            conn,
            subject,
            activity,
            provider_id,
            payload,
        )
        if evidence["received_point_count"] == 0:
            raise GarminError("activity_chart_empty")
        if evidence["valid_point_count"] == 0:
            raise GarminError("activity_chart_invalid")
        if len(prepared) <= ACTIVITY_CHART_MAX_POINTS:
            selected = prepared
            sampling_method = "none"
        elif ACTIVITY_CHART_MAX_POINTS == 1:
            selected = [prepared[0]]
            sampling_method = "even_stride"
        else:
            indices = [
                round(index * (len(prepared) - 1) / (ACTIVITY_CHART_MAX_POINTS - 1))
                for index in range(ACTIVITY_CHART_MAX_POINTS)
            ]
            selected = [prepared[index] for index in indices]
            sampling_method = "even_stride"
        for sample_index, prepared_row in enumerate(selected):
            values = prepared_row["values"]
            conn.execute(
                """INSERT OR IGNORE INTO activity_samples(
                       activity_id,source_revision_id,stream_kind,sample_index,
                       timestamp_utc,latitude,longitude,distance_m,speed_mps,
                       altitude_m,heart_rate_bpm,cadence_rpm,power_w,
                       temperature_c,extras_json
                   ) VALUES(?,?, 'connect_chart',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    activity,
                    revision,
                    sample_index,
                    prepared_row["timestamp_utc"],
                    values["latitude"],
                    values["longitude"],
                    values["distance_m"],
                    values["speed_mps"],
                    values["altitude_m"],
                    values["heart_rate_bpm"],
                    values["cadence_rpm"],
                    values["power_w"],
                    values["temperature_c"],
                    json.dumps(
                        {
                            "source_index": prepared_row["source_index"],
                            "source_role": "details_json_fallback",
                        },
                        sort_keys=True,
                        allow_nan=False,
                    ),
                ),
            )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?",
            (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        evidence = {
            **evidence,
            "source_revision_id": revision,
            "persisted_point_count": len(selected),
            "sampling_method": sampling_method,
        }
        extras["connect_chart"] = evidence
        source_map["sensor_stream"] = {
            "source_revision_id": revision,
            "source_role": "details_json_fallback",
            "stream_kind": "connect_chart",
            "coverage": "partial",
        }
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?, 'details_json_fallback',1)""",
            (activity, revision),
        )
        self.repo.coverage(
            conn,
            subject,
            "activity_details_fallback",
            day.isoformat(),
            "partial",
            revision,
            len(selected),
        )
        self._set_activity_issue(
            conn,
            activity,
            "activity_sensor_fallback",
            "warning",
            evidence,
            revision,
        )
        if sampling_method != "none":
            self._set_activity_issue(
                conn,
                activity,
                "activity_chart_sampled",
                "info",
                evidence,
                revision,
            )
        else:
            self._resolve_activity_issue(conn, activity, "activity_chart_sampled")
        if evidence["dropped_point_count"] > 0:
            self._set_activity_issue(
                conn,
                activity,
                "activity_chart_invalid_rows",
                "warning",
                evidence,
                revision,
            )
        else:
            self._resolve_activity_issue(
                conn,
                activity,
                "activity_chart_invalid_rows",
            )
        self._resolve_activity_issue(conn, activity, "activity_chart_empty")
        self._resolve_activity_issue(conn, activity, "activity_chart_invalid")
        return len(selected)

    @staticmethod
    def _received_activity_revision(
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        payload_hash: str | None,
    ) -> int | None:
        if payload_hash is None:
            return None
        row = conn.execute(
            """SELECT id FROM source_revisions
               WHERE provider='garmin' AND resource_kind=?
                 AND provider_object_id=? AND payload_hash=?
                 AND parsed_at_utc IS NULL
               ORDER BY revision_no DESC LIMIT 1""",
            (resource, provider_id, payload_hash),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _clear_invalid_chart_canonical(
        self,
        conn: sqlite3.Connection,
        subject: int,
        activity: int,
        day: date,
        issue_code: str,
        evidence: dict[str, Any],
        revision: int | None,
    ) -> None:
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?",
            (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        current_stream = source_map.get("sensor_stream")
        if (
            isinstance(current_stream, dict)
            and current_stream.get("source_role") == "details_json_fallback"
        ):
            source_map.pop("sensor_stream", None)
        prior_chart = extras.get("connect_chart")
        if isinstance(prior_chart, dict):
            prior_chart["canonical"] = False
            prior_chart["invalidated_by_revision_id"] = revision
            extras["connect_chart"] = prior_chart
        invalid_evidence = {
            **evidence,
            "source_revision_id": revision,
            "persisted_point_count": 0,
            "sampling_method": "none",
            "canonical_published": False,
        }
        extras["connect_chart_attempt"] = invalid_evidence
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        self.repo.coverage(
            conn,
            subject,
            "activity_details_fallback",
            day.isoformat(),
            "error",
            revision,
            0,
        )
        self._set_activity_issue(
            conn,
            activity,
            issue_code,
            "warning",
            invalid_evidence,
            revision,
        )
        other = (
            "activity_chart_invalid"
            if issue_code == "activity_chart_empty"
            else "activity_chart_empty"
        )
        self._resolve_activity_issue(conn, activity, other)
        self._resolve_activity_issue(
            conn,
            activity,
            "activity_chart_invalid_rows",
        )

    def _collect_activity_chart_fallback(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        receipt: SyncReceipt,
    ) -> None:
        resource = "activity_details_fallback"
        role = "details_json_fallback"
        key = f"garmin:activity:{provider_id}"
        chart_evidence: dict[str, Any] | None = None
        payload_hash: str | None = None
        method = getattr(self._transport(), "activity_extra", None)
        if not callable(method):
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "fetch",
                "not_supported",
                error=GarminError("not_supported"),
                increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        try:
            payload = self._call(
                lambda: method(provider_id, role),
                conn=conn,
                run=run,
                subject=subject,
                resource=resource,
                key=key,
                allows_404=True,
            )
            validate_provider_json_payload(payload)
            canonical = canonical_provider_json(payload)
            payload_hash = digest(canonical)
            self.repo.fields(conn, resource, payload)
            prepared, chart_evidence = self._prepare_activity_chart(payload)
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "fetch",
                "fetched",
                increment_attempt=False,
            )
            count_box: dict[str, int] = {}

            def projector(revision: int) -> None:
                count_box["count"] = self._project_activity_chart(
                    conn,
                    subject,
                    provider_id,
                    activity,
                    day,
                    payload,
                    revision,
                    prepared,
                    chart_evidence or {},
                )

            _, revision, changed = self.repo.archive(
                conn,
                resource,
                provider_id,
                canonical,
                "json",
                "application/json",
                projector,
            )
            self.repo.resolve_gaps(
                conn,
                subject,
                resource,
                day.isoformat(),
                logical_object_key=key,
                stages=("fetch", "project"),
            )
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "project",
                "revised" if changed else "unchanged",
                revision_id=revision,
                increment_attempt=False,
            )
            receipt.coverage_state = "partial"
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            if exc.code in {"activity_chart_empty", "activity_chart_invalid"}:
                received_revision = self._received_activity_revision(
                    conn,
                    resource,
                    provider_id,
                    payload_hash,
                )
                self._clear_invalid_chart_canonical(
                    conn,
                    subject,
                    activity,
                    day,
                    exc.code,
                    chart_evidence
                    or {
                        "stream_kind": "connect_chart",
                        "coverage": "partial",
                        "received_point_count": 0,
                        "valid_point_count": 0,
                        "dropped_point_count": 0,
                        "persisted_point_count": 0,
                        "sampling_method": "none",
                    },
                    received_revision,
                )
                receipt.coverage_state = "partial"
            outcome = self._classify(exc, allows_404=True)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            terminal = (
                "not_supported"
                if exc.code == "not_supported"
                else "not_available"
                if outcome.status == "not_available"
                else "forbidden"
                if outcome.status == "forbidden"
                else "deferred"
                if outcome.status == "deferred"
                else "failed"
            )
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            stage = (
                "project"
                if exc.code.startswith(("activity_chart_", "activity_enrichment_"))
                else "fetch"
            )
            self.repo.item(
                conn,
                run,
                resource,
                key,
                stage,
                terminal,
                error=exc,
                next_retry=retry,
                increment_attempt=False,
            )
            if terminal not in {"not_available", "not_supported"}:
                self.repo.gap(
                    conn,
                    subject,
                    resource,
                    key,
                    day.isoformat(),
                    stage,
                    exc.code,
                    deferred=terminal == "deferred",
                    next_retry=retry,
                )
            self._count_receipt_terminal(receipt, terminal)
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_extra_project_failed")
            self.repo.item(
                conn,
                run,
                resource,
                key,
                "project",
                "failed",
                error=error,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                resource,
                key,
                day.isoformat(),
                "project",
                error.code,
            )
            receipt.counts["failed"] += 1

    def _promote_fit_canonical(
        self,
        conn: sqlite3.Connection,
        activity: int,
        revision: int,
    ) -> None:
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?",
            (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        source_map["sensor_stream"] = {
            "source_revision_id": revision,
            "source_role": "activity_fit",
            "stream_kind": "fit_record",
            "coverage": "canonical",
        }
        source_map["segments"] = {
            "source_revision_id": revision,
            "source_role": "activity_fit",
        }
        if "connect_chart" in extras:
            extras["connect_chart"]["canonical"] = False
            extras["connect_chart"]["superseded_by_fit_revision_id"] = revision
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        self._resolve_activity_issue(conn, activity, "activity_sensor_fallback")
        self._resolve_activity_issue(conn, activity, "activity_chart_sampled")

    @staticmethod
    def _tri_value(values: dict[str, Any], key: str) -> dict[str, Any]:
        if key not in values:
            return {"state": "missing"}
        if values[key] is None:
            return {"state": "null", "value": None}
        return {"state": "value", "value": values[key]}

    @staticmethod
    def _fit_session_values(
        extras: dict[str, Any],
    ) -> tuple[dict[str, Any], int | None]:
        sessions = extras.get("fit_sessions")
        if not isinstance(sessions, list) or not sessions:
            return {}, None
        session = sessions[0]
        if not isinstance(session, dict) or not isinstance(session.get("fields"), dict):
            return {}, None
        values = {
            key: evidence.get("value")
            for key, evidence in session["fields"].items()
            if isinstance(evidence, dict) and "value" in evidence
        }
        revision = session.get("source_revision_id")
        return values, revision if isinstance(revision, int) else None

    @staticmethod
    def _reconciliation_result(
        left: dict[str, Any],
        right: dict[str, Any],
        tolerance: float,
    ) -> tuple[str, float | None, float | None]:
        if left["state"] != "value" or right["state"] != "value":
            return (
                ("match", None, None)
                if left == right
                else ("not_comparable", None, None)
            )
        left_value, right_value = left["value"], right["value"]
        if isinstance(left_value, bool) or isinstance(right_value, bool):
            return (
                ("match", None, None)
                if left_value == right_value
                else ("mismatch", None, None)
            )
        if not isinstance(left_value, (int, float)) or not isinstance(
            right_value, (int, float)
        ):
            return (
                ("match", None, None)
                if left_value == right_value
                else ("mismatch", None, None)
            )
        difference = abs(float(left_value) - float(right_value))
        denominator = max(abs(float(left_value)), abs(float(right_value)))
        relative = (
            difference / denominator
            if denominator
            else (0.0 if difference == 0 else None)
        )
        if difference == 0:
            return "match", difference, relative
        return (
            "within_tolerance" if difference <= tolerance else "mismatch",
            difference,
            relative,
        )

    def _store_reconciliation(
        self,
        conn: sqlite3.Connection,
        activity: int,
        field_key: str,
        left_revision: int,
        right_revision: int,
        left: dict[str, Any],
        right: dict[str, Any],
        tolerance: float,
    ) -> str:
        result, absolute, relative = self._reconciliation_result(left, right, tolerance)
        left_json = json.dumps(left, sort_keys=True, allow_nan=False)
        right_json = json.dumps(right, sort_keys=True, allow_nan=False)
        exists = conn.execute(
            """SELECT 1 FROM reconciliation_results
               WHERE entity_type='activity' AND entity_id=? AND field_key=?
                 AND left_source_revision_id=? AND right_source_revision_id=?
                 AND left_value_json=? AND right_value_json=? AND result=?""",
            (
                activity,
                field_key,
                left_revision,
                right_revision,
                left_json,
                right_json,
                result,
            ),
        ).fetchone()
        if exists is None:
            conn.execute(
                """INSERT INTO reconciliation_results(
                       entity_type,entity_id,field_key,left_source_revision_id,
                       right_source_revision_id,left_value_json,right_value_json,
                       absolute_difference,relative_difference,tolerance,result,
                       checked_at_utc
                   ) VALUES('activity',?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    activity,
                    field_key,
                    left_revision,
                    right_revision,
                    left_json,
                    right_json,
                    absolute,
                    relative,
                    tolerance,
                    result,
                    utc_now(),
                ),
            )
        return result

    def _end_time_candidates(
        self,
        conn: sqlite3.Connection,
        activity: int,
        start_utc: str,
        summary: dict[str, Any],
        summary_revision: int,
        fit_values: dict[str, Any],
        fit_revision: int | None,
    ) -> list[dict[str, Any]]:
        start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        candidates: list[dict[str, Any]] = []

        def duration_candidate(
            method: str,
            value: Any,
            revision: int | None,
            *,
            lower_bound: bool = False,
        ) -> None:
            seconds = self._json_number(value)
            if seconds is None or seconds < 0:
                return
            candidates.append(
                {
                    "method": method,
                    "timestamp_utc": (start + timedelta(seconds=float(seconds)))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "source_revision_id": revision,
                    "lower_bound": lower_bound,
                }
            )

        duration_candidate(
            "summary_elapsed",
            summary.get("elapsedDuration", summary.get("duration")),
            summary_revision,
        )
        duration_candidate(
            "summary_timer",
            summary.get("timerTime", summary.get("duration")),
            summary_revision,
            lower_bound=True,
        )
        duration_candidate(
            "fit_elapsed",
            fit_values.get("total_elapsed_time"),
            fit_revision,
        )
        duration_candidate(
            "fit_timer",
            fit_values.get("total_timer_time"),
            fit_revision,
            lower_bound=True,
        )
        active_fit_clause = (
            """AND source_revision_id=?"""
            if fit_revision is not None
            else """AND stream_kind='connect_chart'
               AND source_revision_id IN (
                   SELECT source_revision_id FROM activity_source_revisions
                   WHERE activity_id=? AND source_role='details_json_fallback'
                     AND is_active=1
               )"""
        )
        sample_parameters: tuple[Any, ...] = (
            (activity, fit_revision)
            if fit_revision is not None
            else (activity, activity)
        )
        sample = conn.execute(
            f"""SELECT timestamp_utc,source_revision_id FROM activity_samples
                WHERE activity_id=? AND timestamp_utc IS NOT NULL
                  {active_fit_clause}
                ORDER BY timestamp_utc DESC LIMIT 1""",
            sample_parameters,
        ).fetchone()
        if sample is not None:
            candidates.append(
                {
                    "method": "last_sample",
                    "timestamp_utc": sample["timestamp_utc"],
                    "source_revision_id": int(sample["source_revision_id"]),
                    "lower_bound": False,
                }
            )
        if fit_revision is not None:
            segment = conn.execute(
                """SELECT end_time_utc,start_time_utc,duration_seconds,source_revision_id
                   FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                   ORDER BY coalesce(end_time_utc,start_time_utc) DESC LIMIT 1""",
                (activity, fit_revision),
            ).fetchone()
            if segment is not None:
                end = segment["end_time_utc"]
                if (
                    end is None
                    and segment["start_time_utc"] is not None
                    and segment["duration_seconds"] is not None
                ):
                    segment_start = datetime.fromisoformat(
                        str(segment["start_time_utc"]).replace("Z", "+00:00")
                    )
                    end = (
                        (
                            segment_start
                            + timedelta(seconds=float(segment["duration_seconds"]))
                        )
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                if end is not None:
                    candidates.append(
                        {
                            "method": "last_segment",
                            "timestamp_utc": end,
                            "source_revision_id": int(segment["source_revision_id"]),
                            "lower_bound": False,
                        }
                    )
        return candidates

    def _infer_activity_end_time(
        self,
        conn: sqlite3.Connection,
        activity: int,
        summary: dict[str, Any],
        summary_revision: int,
        fit_values: dict[str, Any],
        fit_revision: int | None,
    ) -> None:
        row = conn.execute(
            """SELECT start_time_utc,end_time_utc,extras_json,source_map_json
               FROM activities WHERE id=?""",
            (activity,),
        ).fetchone()
        candidates = self._end_time_candidates(
            conn,
            activity,
            str(row["start_time_utc"]),
            summary,
            summary_revision,
            fit_values,
            fit_revision,
        )
        primary = [
            candidate for candidate in candidates if not candidate["lower_bound"]
        ]
        times = [
            datetime.fromisoformat(candidate["timestamp_utc"].replace("Z", "+00:00"))
            for candidate in primary
        ]
        conflict = len(times) > 1 and (max(times) - min(times)).total_seconds() > 60
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        if (
            row["end_time_utc"] is not None
            and source_map.get("end_time_utc", {}).get("method") == "provider_explicit"
        ):
            explicit = datetime.fromisoformat(
                str(row["end_time_utc"]).replace("Z", "+00:00")
            )
            conflict = conflict or any(
                abs((candidate - explicit).total_seconds()) > 60 for candidate in times
            )
            if conflict:
                self._set_activity_issue(
                    conn,
                    activity,
                    "activity_end_time_conflict",
                    "warning",
                    {
                        "explicit_end_time_utc": row["end_time_utc"],
                        "candidates": candidates,
                        "decision": "provider_explicit_retained",
                    },
                    fit_revision or summary_revision,
                )
            else:
                self._resolve_activity_issue(
                    conn, activity, "activity_end_time_conflict"
                )
            return
        if conflict:
            extras["end_time_inference"] = {
                "method": "conflict",
                "confidence": 0.0,
                "candidates": candidates,
                "decision": "fail_closed",
            }
            source_map.pop("end_time_utc", None)
            conn.execute(
                "UPDATE activities SET end_time_utc=NULL,extras_json=?,source_map_json=? WHERE id=?",
                (
                    json.dumps(extras, sort_keys=True, allow_nan=False),
                    json.dumps(source_map, sort_keys=True, allow_nan=False),
                    activity,
                ),
            )
            self._set_activity_issue(
                conn,
                activity,
                "activity_end_time_conflict",
                "warning",
                extras["end_time_inference"],
                fit_revision or summary_revision,
            )
            return
        usable = primary or candidates
        if not usable:
            return
        chosen = max(
            usable,
            key=lambda candidate: datetime.fromisoformat(
                candidate["timestamp_utc"].replace("Z", "+00:00")
            ),
        )
        confidence = 0.9 if len(primary) >= 2 else (0.7 if primary else 0.4)
        evidence = {
            "method": "cross_source" if len(usable) > 1 else chosen["method"],
            "confidence": confidence,
            "end_time_utc": chosen["timestamp_utc"],
            "evidence": candidates,
        }
        extras["end_time_inference"] = evidence
        source_map["end_time_utc"] = {
            "source_revision_id": chosen["source_revision_id"],
            "source_role": (
                "activity_fit"
                if chosen["source_revision_id"] == fit_revision
                else "summary_json"
            ),
            "method": evidence["method"],
            "confidence": confidence,
            "evidence_revision_ids": sorted(
                {
                    candidate["source_revision_id"]
                    for candidate in candidates
                    if isinstance(candidate["source_revision_id"], int)
                }
            ),
        }
        conn.execute(
            "UPDATE activities SET end_time_utc=?,extras_json=?,source_map_json=? WHERE id=?",
            (
                chosen["timestamp_utc"],
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        self._resolve_activity_issue(conn, activity, "activity_end_time_conflict")

    def _reconcile_activity(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        receipt: SyncReceipt,
    ) -> None:
        key = f"garmin:activity:{provider_id}"
        try:
            row = conn.execute(
                """SELECT a.extras_json,a.source_map_json,
                          summary.source_revision_id AS summary_revision
                   FROM activities a
                   JOIN activity_source_revisions summary
                     ON summary.activity_id=a.id
                    AND summary.source_role='summary_json'
                    AND summary.is_active=1
                   WHERE a.id=? AND a.subject_id=? AND a.provider='garmin'
                     AND a.provider_activity_id=?""",
                (activity, subject, provider_id),
            ).fetchone()
            if row is None:
                raise GarminError("activity_enrichment_binding_mismatch")
            extras = json.loads(row["extras_json"] or "{}")
            source_map = json.loads(row["source_map_json"] or "{}")
            summary = extras.get("connect_summary")
            if not isinstance(summary, dict):
                summary = {}
            summary_revision = int(row["summary_revision"])
            fit_values, fit_revision = self._fit_session_values(extras)
            mismatches: list[dict[str, Any]] = []
            connect_metrics: dict[str, Any] = {}
            fit_metrics: dict[str, Any] = {}
            if fit_revision is not None:
                for field_key, (
                    summary_key,
                    fit_key,
                    tolerance,
                ) in ACTIVITY_RECONCILIATION_FIELDS.items():
                    left = self._tri_value(summary, summary_key)
                    right = self._tri_value(fit_values, fit_key)
                    connect_metrics[field_key] = left
                    fit_metrics[field_key] = right
                    result = self._store_reconciliation(
                        conn,
                        activity,
                        field_key,
                        summary_revision,
                        fit_revision,
                        left,
                        right,
                        tolerance,
                    )
                    if result == "mismatch":
                        mismatches.append(
                            {
                                "field_key": field_key,
                                "left": left,
                                "right": right,
                                "tolerance": tolerance,
                            }
                        )
                extras["postprocessed_metrics"] = {
                    "connect": {
                        "source_revision_id": summary_revision,
                        "values": connect_metrics,
                    },
                    "fit": {
                        "source_revision_id": fit_revision,
                        "values": fit_metrics,
                    },
                }
                source_map["postprocessed_metrics"] = {
                    field_key: {
                        "canonical_source_revision_id": summary_revision,
                        "canonical_source_role": "summary_json",
                        "alternate_source_revision_id": fit_revision,
                        "alternate_source_role": "activity_fit",
                    }
                    for field_key in ACTIVITY_RECONCILIATION_FIELDS
                }
                fit_routes = conn.execute(
                    """SELECT 1 FROM activity_segments s JOIN climbing_routes r
                         ON r.segment_id=s.id
                       WHERE s.activity_id=? AND s.source_revision_id=? LIMIT 1""",
                    (activity, fit_revision),
                ).fetchone()
                fit_sets = conn.execute(
                    """SELECT 1 FROM activity_segments s JOIN strength_sets x
                         ON x.segment_id=s.id
                       WHERE s.activity_id=? AND s.source_revision_id=? LIMIT 1""",
                    (activity, fit_revision),
                ).fetchone()
                if fit_routes:
                    source_map["climbing_routes"] = {
                        "source_revision_id": fit_revision,
                        "source_role": "activity_fit",
                    }
                if fit_sets:
                    source_map["strength_sets"] = {
                        "source_revision_id": fit_revision,
                        "source_role": "activity_fit",
                    }
            for role, canonical_key, detail_table in (
                ("typed_splits_json", "climbing_routes", "climbing_routes"),
                ("exercise_sets_json", "strength_sets", "strength_sets"),
            ):
                current_source = source_map.get(canonical_key)
                if (
                    isinstance(current_source, dict)
                    and current_source.get("source_role") == "activity_fit"
                ):
                    continue
                relation = conn.execute(
                    f"""SELECT ar.source_revision_id
                        FROM activity_source_revisions ar
                        WHERE ar.activity_id=? AND ar.source_role=? AND ar.is_active=1
                          AND EXISTS(
                              SELECT 1 FROM activity_segments s
                              JOIN {detail_table} detail ON detail.segment_id=s.id
                              WHERE s.activity_id=ar.activity_id
                                AND s.source_revision_id=ar.source_revision_id
                          )""",
                    (activity, role),
                ).fetchone()
                if relation is not None:
                    source_map[canonical_key] = {
                        "source_revision_id": int(relation["source_revision_id"]),
                        "source_role": role,
                    }
                elif (
                    isinstance(current_source, dict)
                    and current_source.get("source_role") == role
                ):
                    source_map.pop(canonical_key, None)
            conn.execute(
                "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
                (
                    json.dumps(extras, sort_keys=True, allow_nan=False),
                    json.dumps(source_map, sort_keys=True, allow_nan=False),
                    activity,
                ),
            )
            if mismatches:
                self._set_activity_issue(
                    conn,
                    activity,
                    "activity_reconciliation_mismatch",
                    "warning",
                    {
                        "summary_revision_id": summary_revision,
                        "fit_revision_id": fit_revision,
                        "mismatches": mismatches,
                    },
                    fit_revision,
                )
            else:
                self._resolve_activity_issue(
                    conn,
                    activity,
                    "activity_reconciliation_mismatch",
                )
            self._infer_activity_end_time(
                conn,
                activity,
                summary,
                summary_revision,
                fit_values,
                fit_revision,
            )
            self.repo.resolve_gaps(
                conn,
                subject,
                "activities",
                day.isoformat(),
                logical_object_key=key,
                stages=("reconcile",),
            )
            self.repo.item(
                conn,
                run,
                "activities",
                key,
                "reconcile",
                "succeeded",
                increment_attempt=False,
            )
        except GarminError as exc:
            self.repo.item(
                conn,
                run,
                "activities",
                key,
                "reconcile",
                "failed",
                error=exc,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activities",
                key,
                day.isoformat(),
                "reconcile",
                exc.code,
            )
            receipt.counts["failed"] += 1
        except Exception:
            error = GarminError("activity_reconcile_failed")
            self.repo.item(
                conn,
                run,
                "activities",
                key,
                "reconcile",
                "failed",
                error=error,
                increment_attempt=False,
            )
            self.repo.gap(
                conn,
                subject,
                "activities",
                key,
                day.isoformat(),
                "reconcile",
                error.code,
            )
            receipt.counts["failed"] += 1

    def _apply_activity_inventory_state(
        self,
        conn: sqlite3.Connection,
        subject: int,
        seen_ids: set[str],
        start: date,
        through: date,
        mode: str,
        *,
        complete: bool,
        absence_proven: bool,
        observation_id: str,
    ) -> None:
        query = """SELECT id,provider_activity_id,local_date,provider_state,
                          provider_deleted_at_utc
                   FROM activities
                   WHERE subject_id=? AND provider='garmin' AND local_date<=?"""
        parameters: list[Any] = [subject, through.isoformat()]
        if mode != "full":
            query += " AND local_date>=?"
            parameters.append(start.isoformat())
        rows = list(conn.execute(query, parameters))
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        observation = ActivityInventoryObservation(
            observation_id=observation_id,
            mode=mode,
            start_local_date=None if mode == "full" else start,
            through_local_date=through,
            seen_ids=frozenset(seen_ids),
            complete=complete,
            absence_proven=absence_proven,
            observed_at_utc=now,
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                provider_id = str(row["provider_activity_id"])
                current_state = str(row["provider_state"])
                next_state = next_activity_state(
                    current_state,
                    provider_id,
                    date.fromisoformat(str(row["local_date"])),
                    observation,
                    last_transition_at_utc=(
                        str(row["provider_deleted_at_utc"])
                        if row["provider_deleted_at_utc"]
                        else None
                    ),
                )
                if next_state == "active":
                    self._set_activity_active(conn, subject, provider_id)
                elif next_state == "suspected_missing" and current_state == "active":
                    conn.execute(
                        """UPDATE activities SET provider_state='suspected_missing',
                                  first_missing_at_utc=?,last_missing_at_utc=? WHERE id=?""",
                        (now, now, row["id"]),
                    )
                elif (
                    next_state == "provider_deleted"
                    and current_state == "suspected_missing"
                ):
                    conn.execute(
                        """UPDATE activities SET provider_state='provider_deleted',
                                  last_missing_at_utc=?,provider_deleted_at_utc=? WHERE id=?""",
                        (now, now, row["id"]),
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _publish_activity_inventory_coverage(
        self,
        conn: sqlite3.Connection,
        subject: int,
        seen_ids: set[str],
        start: date,
        through: date,
        request: SyncRequest,
    ) -> None:
        if request.mode == "full":
            return
        counts: dict[str, int] = {}
        if seen_ids:
            placeholders = ",".join("?" for _ in seen_ids)
            counts = {
                row["local_date"]: int(row["record_count"])
                for row in conn.execute(
                    f"""SELECT local_date,count(*) AS record_count FROM activities
                        WHERE subject_id=? AND provider='garmin'
                          AND provider_activity_id IN ({placeholders})
                          AND local_date>=? AND local_date<=?
                        GROUP BY local_date""",
                    (
                        subject,
                        *sorted(seen_ids),
                        start.isoformat(),
                        through.isoformat(),
                    ),
                )
            }
        for offset in range((through - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            state = (
                "partial"
                if request.mode == "snapshot"
                else ("fetched" if counts.get(day, 0) else "empty")
            )
            self.repo.coverage(
                conn,
                subject,
                "activity_inventory",
                day,
                state,
                None,
                counts.get(day, 0),
                snapshot=request.mode == "snapshot",
            )

    _FIT_MAX_BYTES = 200 * 1024 * 1024
    _FIT_MAX_MEMBERS = 16
    _FIT_MAX_TOTAL_BYTES = 300 * 1024 * 1024
