"""FIT/original-activity acquisition, validation and projection."""
from __future__ import annotations

from .contracts import *  # noqa: F403
from .contracts import _FONT_GRADE_DISPLAY

# Raw FIT remains the lossless source of record.  SQLite keeps a deterministic
# activity-level sample sketch so normal analysis cannot grow without bound.
FIT_MAX_SQLITE_RECORDS = 2_000

class FitCollectionMixin:
    def _fit_temp_dir(self) -> Path:
        parent = self.config.raw_root.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink():
            raise GarminError("fit_zip_unsafe_member")
        return Path(tempfile.mkdtemp(prefix=".fit-download-", dir=parent))

    @staticmethod
    def _write_temp_file(path: Path, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(fd, view); view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _fit_timestamp(value: Any) -> str | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _fit_json_value(cls, value: Any) -> Any:
        """Serialize FIT values without losing array or timestamp structure."""
        if isinstance(value, datetime):
            return cls._fit_timestamp(value)
        if isinstance(value, (date, datetime_time)):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (tuple, list)):
            return [cls._fit_json_value(item) for item in value]
        raise TypeError(f"unsupported_fit_value:{type(value).__name__}")

    @classmethod
    def _fit_field_evidence(cls, field: Any) -> dict[str, Any]:
        is_developer = getattr(field, "field_type", None) == "devfield"
        definition = getattr(field, "field_def", None)
        return {
            "value": cls._fit_json_value(field.value),
            "unit": field.units,
            "field_definition_number": field.def_num,
            "developer_data_index": getattr(definition, "dev_data_index", None) if is_developer else None,
            "is_developer": is_developer,
        }

    @staticmethod
    def _fit_optional(primary: Any, fallback: Any) -> Any:
        return primary if primary is not None else fallback

    @staticmethod
    def _fit_unknown_timestamp(fields: Iterable[Any], fallback: str | None) -> str | None:
        for field in fields:
            if field.def_num == 253 and isinstance(field.value, int):
                return (datetime(1989, 12, 31, tzinfo=UTC) + timedelta(seconds=field.value)).isoformat().replace("+00:00", "Z")
        return fallback

    def _extract_original_candidates(self, blob: bytes, suffix: str) -> list[bytes]:
        """Extract one ORIGINAL format from an untrusted transient container."""
        if suffix not in {"fit", "tcx", "gpx"}:
            raise ValueError("unsupported_original_format")
        if len(blob) > self._FIT_MAX_BYTES:
            raise GarminError("fit_zip_limits_exceeded")
        directory = self._fit_temp_dir()
        try:
            zip_path = directory / "original.zip"
            if not blob.startswith(b"PK"):
                minimum = 12 if suffix == "fit" else 1
                return [blob] if len(blob) >= minimum else []
            self._write_temp_file(zip_path, blob)
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    infos = archive.infolist()
                    if len(infos) > self._FIT_MAX_MEMBERS or sum(item.file_size for item in infos) > self._FIT_MAX_TOTAL_BYTES:
                        raise GarminError("fit_zip_limits_exceeded")
                    if archive.testzip() is not None:
                        raise GarminError("fit_zip_invalid")
                    candidates: list[bytes] = []
                    for info in infos:
                        name = PurePosixPath(info.filename)
                        mode = info.external_attr >> 16
                        file_type = stat.S_IFMT(mode)
                        if file_type == stat.S_IFLNK or name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                            raise GarminError("fit_zip_unsafe_member")
                        if info.is_dir():
                            continue
                        # ZIPs produced on non-Unix platforms commonly have no
                        # file type bits.  Otherwise accept regular files only.
                        if file_type not in {0, stat.S_IFREG}:
                            raise GarminError("fit_zip_unsafe_member")
                        if info.file_size > self._FIT_MAX_BYTES:
                            raise GarminError("fit_zip_limits_exceeded")
                        if name.suffix.casefold() == f".{suffix}":
                            try:
                                candidates.append(archive.read(info))
                            except (RuntimeError, zipfile.BadZipFile) as exc:
                                raise GarminError("fit_zip_invalid") from exc
                    return candidates
            except GarminError:
                raise
            except (RuntimeError, zipfile.BadZipFile) as exc:
                raise GarminError("fit_zip_invalid") from exc
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _extract_fit_candidates(self, blob: bytes) -> list[bytes]:
        """Read ORIGINAL as an untrusted transient container; leave no ZIP behind."""
        return self._extract_original_candidates(blob, "fit")

    @staticmethod
    def _activity_declared_original_format(
        conn: sqlite3.Connection, activity: int,
    ) -> str | None:
        row = conn.execute(
            "SELECT extras_json FROM activities WHERE id=?", (activity,),
        ).fetchone()
        if row is None:
            return None
        value = json.loads(row["extras_json"] or "{}").get(
            "connect_original_format"
        )
        return value if value in {"fit", "tcx", "gpx"} else None

    @staticmethod
    def _has_archived_activity_original(
        conn: sqlite3.Connection, provider_id: str, original_format: str,
    ) -> bool:
        return conn.execute(
            """SELECT 1 FROM source_revisions
               WHERE provider='garmin' AND resource_kind=?
                 AND provider_object_id=? AND is_current=1
                 AND parsed_at_utc IS NOT NULL""",
            (f"activity_original_{original_format}", provider_id),
        ).fetchone() is not None

    def _collect_nonfit_activity_original(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        original_format: str,
        day: date,
        receipt: SyncReceipt,
    ) -> str:
        """Archive a declared TCX/GPX ORIGINAL without parsing it as FIT."""
        key = f"garmin:activity:{provider_id}"
        resource = f"activity_original_{original_format}"
        media_type = {
            "tcx": "application/vnd.garmin.tcx+xml",
            "gpx": "application/gpx+xml",
        }[original_format]
        try:
            if self._has_archived_activity_original(
                conn, provider_id, original_format,
            ):
                self.repo.item(
                    conn, run, resource, key, "project", "unchanged",
                    increment_attempt=False,
                )
                receipt.counts["unchanged"] += 1
            else:
                blob = self._call(
                    lambda: self._transport().activity_original(provider_id),
                    conn=conn, run=run, subject=subject, resource=resource,
                    key=key, allows_404=True,
                )
                self.repo.item(
                    conn, run, resource, key, "fetch", "fetched",
                    increment_attempt=False,
                )
                candidates = self._extract_original_candidates(
                    blob, original_format,
                )
                unique = {
                    digest(candidate): candidate for candidate in candidates
                }
                if not unique:
                    raise GarminError("activity_original_missing")
                if len(unique) != 1:
                    for candidate_hash, candidate in sorted(unique.items()):
                        candidate_key = self._identity_hmac(
                            f"{resource}-candidate:{provider_id}:{candidate_hash}"
                        )
                        self.repo.archive(
                            conn, f"{resource}_candidate", candidate_key,
                            candidate, original_format, media_type,
                        )
                    raise GarminError("activity_original_ambiguous")
                candidate = next(iter(unique.values()))
                _, revision, changed = self.repo.archive(
                    conn, resource, provider_id, candidate,
                    original_format, media_type,
                )
                self.repo.item(
                    conn, run, resource, key, "project",
                    "revised" if changed else "unchanged",
                    revision_id=revision, increment_attempt=False,
                )
                receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            outcome = self._classify(exc, allows_404=True)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            deferred = outcome.status == "deferred"
            terminal = (
                "not_available" if outcome.status == "not_available"
                else "forbidden" if outcome.status == "forbidden"
                else "deferred" if deferred else "failed"
            )
            retry = self._next_retry(exc, 0) if deferred else None
            self.repo.item(
                conn, run, resource, key, "project", terminal,
                error=exc, next_retry=retry, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, resource, key, day.isoformat(), "project",
                exc.code, deferred=deferred, next_retry=retry,
            )
            receipt.counts[
                "not_available" if terminal == "not_available"
                else "deferred" if deferred else "failed"
            ] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            return "invalid"
        except Exception:
            error = GarminError("activity_original_archive_failed")
            self.repo.item(
                conn, run, resource, key, "project", "failed",
                error=error, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, resource, key, day.isoformat(), "project",
                error.code,
            )
            receipt.counts["failed"] += 1
            return "invalid"

        # The provider metadata is authoritative: FIT is not applicable to
        # this activity.  Preserve and close any legacy fit_missing evidence.
        self.repo.resolve_gaps(
            conn, subject, "activity_fit", day.isoformat(),
            logical_object_key=key,
            stages=("fetch", "extract", "parse", "project"),
        )
        self.repo.item(
            conn, run, "activity_fit", key, "discover", "not_available",
            error=GarminError("fit_not_available_for_activity_format"),
            increment_attempt=False,
        )
        receipt.counts["not_available"] += 1
        return "fit" if self._has_active_fit(conn, activity) else "not_available"

    def _validate_fit_sessions(
        self,
        sessions: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        start_utc: str,
        sport: str,
    ) -> tuple[str, str]:
        if not sessions:
            raise GarminError("fit_no_session")
        identities: list[tuple[str, str, str, int]] = []
        for index, session in enumerate(sessions):
            stamp = self._fit_timestamp(session.get("start_time") or session.get("timestamp"))
            fit_sport = str(session.get("sport") or "").strip()
            fit_sub_sport = str(session.get("sub_sport") or "").strip()
            if not stamp or not fit_sport:
                raise GarminError("fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch")
            identities.append((stamp, fit_sport, fit_sub_sport, index))
        try:
            expected_start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            ordered = sorted(
                identities,
                key=lambda item: (
                    datetime.fromisoformat(item[0].replace("Z", "+00:00")),
                    item[3],
                ),
            )
            earliest_start = datetime.fromisoformat(ordered[0][0].replace("Z", "+00:00"))
        except ValueError as exc:
            raise GarminError("fit_identity_mismatch") from exc
        if abs((earliest_start - expected_start).total_seconds()) > 300:
            raise GarminError("fit_identity_mismatch")

        declared_counts = {
            int(activity["num_sessions"])
            for activity in activities
            if isinstance(activity.get("num_sessions"), int)
        }
        if declared_counts and declared_counts != {len(sessions)}:
            raise GarminError("fit_ambiguous_session")
        activity_types = {str(activity.get("type") or "").strip() for activity in activities}
        # Garmin Connect type keys and FIT sport vocabularies are not always
        # identical.  Keep this table explicit and closed: a time match alone
        # is never enough to accept an unrecognised Connect activity type.
        expected = {
            "badminton": ("racket", "badminton"),
            "breathwork": ("training", "breathing"),
            "indoor_cardio": ("training", "cardio_training"),
            "indoor_cycling": ("cycling", "indoor_cycling"),
            "indoor_running": ("running", "indoor_running"),
            "treadmill_running": ("running", "treadmill"),
            "strength_training": ("training", "strength_training"),
            "training": ("training", None),
            "bouldering": ("rock_climbing", "bouldering"),
            "indoor_climbing": ("rock_climbing", "indoor_climbing"),
            "rock_climbing": ("rock_climbing", None),
            "running": ("running", None),
            "cycling": ("cycling", None),
            "hiking": ("hiking", None),
        }.get(sport)
        multisport = (
            sport in {"multisport", "multi_sport", "triathlon"}
            or "auto_multi_sport" in activity_types
        )
        if not multisport:
            if expected is None:
                raise GarminError(
                    "fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch"
                )
            conflicts = [
                identity for identity in identities
                if identity[1] != expected[0]
                or (expected[1] is not None and identity[2] != expected[1])
            ]
            if conflicts:
                raise GarminError("fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch")
        return ordered[0][0], ordered[0][1]

    def _fit_session_identity(self, fit: bytes, start_utc: str, sport: str) -> tuple[str, str]:
        directory = self._fit_temp_dir()
        path = directory / "candidate.fit"
        try:
            self._write_temp_file(path, fit)
            sessions: list[dict[str, Any]] = []
            activities: list[dict[str, Any]] = []
            try:
                with fitdecode.FitReader(path, check_crc=True) as reader:
                    for frame in reader:
                        if isinstance(frame, fitdecode.FitDataMessage):
                            values = {field.name: field.value for field in frame.fields}
                            if frame.name == "session":
                                sessions.append(values)
                            elif frame.name == "activity":
                                activities.append(values)
            except Exception as exc:
                raise GarminError("fit_crc_invalid") from exc
            return self._validate_fit_sessions(sessions, activities, start_utc, sport)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _collect_activity_fit(self, conn: sqlite3.Connection, run: int, subject: int, provider_id: str, activity: int, start_utc: str, sport: str, day: date, receipt: SyncReceipt) -> str:
        key = f"garmin:activity:{provider_id}"
        original_format = self._activity_declared_original_format(
            conn, activity,
        )
        if original_format in {"tcx", "gpx"}:
            return self._collect_nonfit_activity_original(
                conn, run, subject, provider_id, activity,
                original_format, day, receipt,
            )
        try:
            blob = self._call(lambda: self._transport().activity_original(provider_id), conn=conn, run=run, subject=subject, resource="activity_fit", key=key, allows_404=True)
            self.repo.item(
                conn, run, "activity_fit", key, "fetch", "fetched",
                increment_attempt=False,
            )
            candidates = self._extract_fit_candidates(blob)
            valid: list[bytes] = []
            invalid_codes: list[str] = []
            # Hash/deduplicate before parsing.  Stable hash order makes both
            # validation and the selected failure independent of ZIP order.
            unique_candidates = {
                candidate_hash: candidate
                for candidate_hash, candidate in sorted(
                    ((digest(candidate), candidate) for candidate in candidates),
                    key=lambda item: item[0],
                )
            }
            # Every extracted FIT is immutable received evidence, irrespective
            # of whether later validation selects it for canonical projection.
            # Archive before parsing so corrupt, mismatched, or multi-session
            # candidates cannot disappear with an extract failure.  The HMAC
            # keeps the provider activity id and candidate digest out of
            # externally visible identifiers; archive is content-addressed so
            # a repeated ORIGINAL response is a no-op.
            for candidate_hash, candidate in unique_candidates.items():
                candidate_key = self._identity_hmac(
                    f"fit-candidate:{provider_id}:{candidate_hash}"
                )
                self.repo.archive(
                    conn, "activity_fit_candidate", candidate_key, candidate,
                    "fit", "application/octet-stream",
                )
            for candidate in unique_candidates.values():
                try:
                    self._fit_session_identity(candidate, start_utc, sport)
                    valid.append(candidate)
                except GarminError as exc:
                    invalid_codes.append(exc.code)
            if not valid:
                failure_priority = {
                    "fit_crc_invalid": 0,
                    "fit_no_session": 1,
                    "fit_identity_mismatch": 2,
                    "fit_ambiguous_session": 3,
                }
                code = min(invalid_codes, key=lambda item: (failure_priority.get(item, 99), item)) if invalid_codes else "fit_missing"
                raise GarminError(code)
            unique = {digest(candidate): candidate for candidate in valid}
            if len(unique) != 1:
                candidate_revisions: list[int] = []
                for candidate_hash in unique:
                    candidate_key = self._identity_hmac(
                        f"fit-candidate:{provider_id}:{candidate_hash}"
                    )
                    candidate_revision = conn.execute(
                        """SELECT id FROM source_revisions
                             WHERE provider='garmin'
                               AND resource_kind='activity_fit_candidate'
                               AND provider_object_id=? AND is_current=1""",
                        (candidate_key,),
                    ).fetchone()
                    if candidate_revision is None:
                        raise ValueError("fit_candidate_archive_missing")
                    candidate_revisions.append(int(candidate_revision["id"]))
                now = utc_now()
                validation_errors: dict[str, str | None] = {}
                for candidate_hash, candidate in unique_candidates.items():
                    if candidate_hash in unique:
                        validation_errors[candidate_hash] = None
                        continue
                    try:
                        self._fit_session_identity(candidate, start_utc, sport)
                    except GarminError as exc:
                        validation_errors[candidate_hash] = exc.code
                details = json.dumps({
                    "candidate_count": len(unique_candidates),
                    "valid_candidate_count": len(unique),
                    "candidates": [
                        {"hash": candidate_hash, "error_code": validation_errors.get(candidate_hash)}
                        for candidate_hash in sorted(unique_candidates)
                    ],
                }, sort_keys=True, allow_nan=False)
                issue = conn.execute("SELECT id FROM data_quality_issues WHERE entity_type='activity' AND entity_id=? AND issue_code='ambiguous_activity_fit' AND status='open'", (activity,)).fetchone()
                if issue:
                    conn.execute("UPDATE data_quality_issues SET last_seen_at_utc=?,details_json=? WHERE id=?", (now, details, int(issue[0])))
                else:
                    conn.execute("INSERT INTO data_quality_issues(entity_type,entity_id,issue_code,severity,details_json,status,first_seen_at_utc,last_seen_at_utc,source_revision_id) VALUES(?,?,?,?,?,'open',?,?,?)", ("activity", activity, "ambiguous_activity_fit", "warning", details, now, now, candidate_revisions[0]))
                raise GarminError("fit_ambiguous")
            fit = next(iter(unique.values()))
            def projector(revision: int) -> None:
                # Revision-bound projections are immutable historical evidence.
                # Only canonical FIT rows without a revision FK are replaced.
                row = conn.execute("SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,)).fetchone()
                extras = json.loads(row["extras_json"] or "{}")
                extras.pop("fit_session", None)
                extras["fit_sessions"] = []
                source_map = json.loads(row["source_map_json"] or "{}")
                source_map.pop("fit_session", None)
                source_map.pop("fit_sessions", None)
                conn.execute("UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?", (json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), activity))
                # These projections have no revision FK.  Replace only FIT-owned
                # rows inside the publish transaction; other source kinds remain.
                conn.execute("DELETE FROM activity_metric_sources WHERE activity_id=? AND source_kind IN ('standard_fit','developer_fit')", (activity,))
                conn.execute("DELETE FROM course_points WHERE activity_id=? AND course_identity='fit'", (activity,))
                self._project_fit(conn, activity, fit, revision)
                conn.execute("UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='activity_fit'", (activity,))
                conn.execute("INSERT OR IGNORE INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, revision, "activity_fit"))
                self._promote_fit_canonical(conn, activity, revision)
            _, revision, changed = self.repo.archive(conn, "activity_fit", provider_id, fit, "fit", "application/octet-stream", projector)
            conn.execute("UPDATE data_quality_issues SET status='resolved',resolved_at_utc=?,last_seen_at_utc=? WHERE entity_type='activity' AND entity_id=? AND issue_code='ambiguous_activity_fit' AND status='open'", (utc_now(), utc_now(), activity))
            self.repo.resolve_gaps(
                conn, subject, "activity_fit", day.isoformat(),
                logical_object_key=key,
                stages=("extract", "parse"),
            )
            self.repo.item(conn, run, "activity_fit", key, "parse", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
            receipt.counts["revised" if changed else "unchanged"] += 1
            return "fit"
        except GarminError as exc:
            outcome = self._classify(exc, allows_404=True)
            terminal = "not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if outcome.status == "deferred" else "failed"))
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            fetch = conn.execute(
                """SELECT status FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND resource_kind='activity_fit'
                     AND logical_object_key=? AND stage='fetch'""",
                (run, key),
            ).fetchone()
            failure_stage = (
                "fetch"
                if fetch is not None and fetch["status"] == "running"
                else "extract"
            )
            self.repo.item(
                conn, run, "activity_fit", key, failure_stage, terminal,
                error=exc, next_retry=retry, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, "activity_fit", key, day.isoformat(),
                failure_stage, exc.code, deferred=terminal == "deferred",
                next_retry=retry,
            )
            if terminal == "not_available":
                receipt.counts["not_available"] += 1
            else:
                receipt.counts["deferred" if terminal == "deferred" else "failed"] += 1
            if self._has_active_fit(conn, activity):
                return "fit"
            if exc.code == "not_supported":
                return "not_supported"
            if terminal == "not_available":
                return "not_available"
            if exc.code in {
                "fit_missing", "fit_crc_invalid", "fit_no_session",
                "fit_identity_mismatch", "fit_ambiguous_session",
            }:
                return "invalid"
            return terminal
        except Exception:
            # ``archive`` has already committed received raw evidence before
            # entering the projector; do not let a parser/DDL failure erase it
            # or replace a prior current FIT revision.
            error = GarminError("fit_parse_failed")
            self.repo.item(conn, run, "activity_fit", key, "parse", "failed", error=error, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_fit", key, day.isoformat(), "parse", error.code)
            receipt.counts["failed"] += 1
            return "fit" if self._has_active_fit(conn, activity) else "failed"

    def _store_fit_session_evidence(
        self,
        conn: sqlite3.Connection,
        activity: int,
        revision: int,
        fields: Iterable[Any],
    ) -> None:
        session_fields = {field.name: self._fit_field_evidence(field) for field in fields}
        row = conn.execute("SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,)).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        sessions = extras.setdefault("fit_sessions", [])
        session_entry = {
            "session_index": len(sessions),
            "source_revision_id": revision,
            "fields": session_fields,
        }
        sessions.append(session_entry)
        extras["fit_sessions"] = sessions
        extras["fit_session"] = sessions[0]
        source_map["fit_session"] = {"source_revision_id": revision, "source_kind": "fit_session"}
        source_map["fit_sessions"] = {
            "source_revision_id": revision,
            "source_kind": "fit_session",
            "ordered": True,
            "session_count": len(sessions),
        }
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), activity),
        )

    def _project_fit(self, conn: sqlite3.Connection, activity: int, fit: bytes, revision: int) -> None:
        directory = self._fit_temp_dir(); path = directory / "project.fit"
        try:
            self._write_temp_file(path, fit); indexes: dict[str, int] = {}; sport = ""; record_count = 0
            metric_ranges: dict[tuple[str, str, int | None, str], list[str | None]] = {}
            workout_steps: dict[int, dict[str, Any]] = {}
            exercise_titles: dict[tuple[str, int | None], str] = {}
            # Workout steps and exercise titles are metadata for set messages,
            # not a positional stream.  Cache the complete definitions before
            # assigning any set its semantic fields.
            with fitdecode.FitReader(path, check_crc=True) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    values = {field.name: field.value for field in frame.fields}
                    if frame.name == "workout_step" and isinstance(values.get("message_index"), int):
                        workout_steps[values["message_index"]] = values
                    elif frame.name == "exercise_title":
                        category = values.get("exercise_category")
                        title = values.get("wkt_step_name")
                        if category is not None and isinstance(title, str) and title:
                            exercise_titles[(str(category), values.get("exercise_name"))] = title
                    elif frame.name == "record":
                        record_count += 1
            sample_stride = max(1, math.ceil(record_count / FIT_MAX_SQLITE_RECORDS))
            with fitdecode.FitReader(path, check_crc=True) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage): continue
                    values = {field.name: field.value for field in frame.fields}; name = frame.name
                    stamp = self._fit_timestamp(values.get("timestamp"))
                    if name == "session":
                        sport = str(values.get("sport") or sport)
                        self._store_fit_session_evidence(conn, activity, revision, frame.fields)
                    if name == "record":
                        index = indexes.get("record", 0); indexes["record"] = index + 1
                        generic_fields = {"timestamp","position_lat","position_long","distance","speed","enhanced_speed","altitude","enhanced_altitude","heart_rate","cadence","power","temperature"}
                        extras: dict[str, Any] = {}
                        metadata: dict[str, Any] = {}
                        for field in frame.fields:
                            evidence = self._fit_field_evidence(field)
                            if field.name in generic_fields:
                                metadata[field.name] = evidence
                            else:
                                extras[field.name] = evidence
                            if field.name != "timestamp" and not field.name.startswith("unknown_") and field.value is not None:
                                is_developer = evidence["is_developer"]
                                source_kind = "developer_fit" if is_developer else "standard_fit"
                                developer_index = evidence["developer_data_index"] if is_developer else None
                                attribution = "explicit_developer" if is_developer else "unknown"
                                key = (field.name, source_kind, developer_index, attribution)
                                existing = metric_ranges.get(key)
                                if existing is None:
                                    metric_ranges[key] = [stamp, stamp]
                                else:
                                    existing[1] = stamp
                        extras["_field_metadata"] = metadata
                        extras["_sample_storage"] = "bounded_fit_sketch"
                        extras["_sample_stride"] = sample_stride
                        extras["_record_count"] = record_count
                        lat = values.get("position_lat"); lon = values.get("position_long")
                        if isinstance(lat, (int, float)): lat = lat * 180.0 / (2 ** 31)
                        if isinstance(lon, (int, float)): lon = lon * 180.0 / (2 ** 31)
                        if index % sample_stride == 0:
                            conn.execute("INSERT OR IGNORE INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,latitude,longitude,distance_m,speed_mps,altitude_m,heart_rate_bpm,cadence_rpm,power_w,temperature_c,extras_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (activity, revision, "fit_record", index, stamp, lat, lon, values.get("distance"), self._fit_optional(values.get("enhanced_speed"), values.get("speed")), self._fit_optional(values.get("enhanced_altitude"), values.get("altitude")), values.get("heart_rate"), values.get("cadence"), values.get("power"), values.get("temperature"), json.dumps(extras, sort_keys=True, allow_nan=False)))
                    elif name in {"lap", "split", "set", "workout_step", "length", "interval"}:
                        if name == "set":
                            kind = "strength_rest" if str(values.get("set_type") or "").endswith("rest") else "strength_active"
                        elif name == "split" and sport == "rock_climbing":
                            kind = "climb_rest" if str(values.get("split_type") or "").endswith("rest") else "climb_active"
                        else:
                            kind = name
                        index = indexes.get(kind, 0); indexes[kind] = index + 1
                        cursor = conn.execute("INSERT OR IGNORE INTO activity_segments(activity_id,segment_type,segment_index,start_time_utc,end_time_utc,duration_seconds,distance_m,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)", (activity, kind, index, self._fit_timestamp(values.get("start_time")), stamp, self._fit_optional(values.get("total_timer_time"), values.get("duration")), values.get("total_distance"), json.dumps({field.name: self._fit_json_value(field.value) for field in frame.fields}, sort_keys=True, allow_nan=False), revision))
                        row = conn.execute("SELECT id FROM activity_segments WHERE activity_id=? AND source_revision_id=? AND segment_type=? AND segment_index=?", (activity, revision, kind, index)).fetchone(); segment = int(row[0])
                        if kind == "strength_active":
                            step_index = values.get("wkt_step_index")
                            step = workout_steps.get(step_index, {}) if isinstance(step_index, int) else {}
                            raw_exercise_number = step.get("exercise_name")
                            step_category = step.get("exercise_category")
                            title = exercise_titles.get((str(step_category), raw_exercise_number)) if step_category is not None else None
                            intensity = step.get("intensity")
                            exercise_category = intensity if intensity in {"warmup", "cooldown"} else (step_category or (str(title) if title else None))
                            exercise_name = step.get("notes") or title or step.get("wkt_step_name") or exercise_category
                            conn.execute("INSERT OR IGNORE INTO strength_sets(segment_id,workout_step_index,set_type,exercise_category,raw_exercise_number,exercise_name,repetitions,weight_kg,duration_seconds) VALUES(?,?,?,?,?,?,?,?,?)", (segment, step_index, str(values.get("set_type") or "active"), exercise_category, raw_exercise_number, exercise_name, values.get("repetitions"), values.get("weight"), values.get("duration")))
                        elif kind == "climb_active":
                            grade = values.get("unknown_70")
                            if grade is None:
                                grade = values.get("grade")
                            explicit_completed = values.get("unknown_73")
                            if explicit_completed is not None:
                                completed = int(bool(explicit_completed))
                            else:
                                # In the bouldering sample, this outcome code
                                # is the only completion evidence: 3=completed,
                                # 2=not completed.  The untouched raw code
                                # remains in activity_segments.extras_json.
                                completed = {3: 1, 2: 0}.get(values.get("unknown_71"))
                            conn.execute("INSERT OR IGNORE INTO climbing_routes(segment_id,grade_raw,grade_system,grade_display,completed,falls,ascent_meters) VALUES(?,?,?,?,?,?,?)", (segment, str(grade) if grade is not None else None, "font" if grade is not None else None, _FONT_GRADE_DISPLAY.get(grade), completed, values.get("unknown_72") if values.get("unknown_72") is not None else values.get("falls"), values.get("total_ascent")))
                    elif name == "field_description": conn.execute("INSERT OR IGNORE INTO fit_metric_definitions(source_revision_id,developer_data_index,native_mesg_num,field_definition_number,field_name,base_type,raw_unit,canonical_metric_key) VALUES(?,?,?,?,?,?,?,?)", (revision, int(values.get("developer_data_index") or 0), values.get("native_mesg_num"), int(values.get("field_definition_number") or 0), values.get("field_name"), values.get("fit_base_type_id"), values.get("units"), None))
                    elif name == "developer_data_id":
                        developer_index = values.get("developer_data_index")
                        application_id = values.get("application_id")
                        if isinstance(developer_index, int) and application_id is not None:
                            uid = self._identity_hmac(f"garmin-developer:{developer_index}:{self._fit_json_value(application_id)}")
                            now = utc_now()
                            conn.execute("INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc", (uid, "garmin_developer", f"developer_data_index:{developer_index}", "developer_app", now, now))
                            device = conn.execute("SELECT id FROM devices WHERE device_uid_hash=?", (uid,)).fetchone()
                            conn.execute("INSERT OR IGNORE INTO activity_devices(activity_id,device_id,device_role,source_revision_id) VALUES(?,?,?,?)", (activity, int(device[0]), "developer_app", revision))
                    elif name == "device_info":
                        serial = values.get("serial_number")
                        if serial is not None:
                            uid = self._identity_hmac(f"garmin:{serial}"); now = utc_now(); conn.execute("INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc", (uid, str(values.get("manufacturer") or "garmin"), str(values.get("product") or ""), "fit_device", now, now)); device = conn.execute("SELECT id FROM devices WHERE device_uid_hash=?", (uid,)).fetchone(); conn.execute("INSERT OR IGNORE INTO activity_devices(activity_id,device_id,device_role,source_revision_id) VALUES(?,?,?,?)", (activity, int(device[0]), "unknown", revision))
                    elif name == "course_point":
                        index = indexes.get("course_point", 0); indexes["course_point"] = index + 1
                        lat = values.get("position_lat"); lon = values.get("position_long")
                        lat = lat * 180.0 / (2 ** 31) if isinstance(lat, (int, float)) else lat
                        lon = lon * 180.0 / (2 ** 31) if isinstance(lon, (int, float)) else lon
                        conn.execute("INSERT OR IGNORE INTO course_points(activity_id,course_identity,point_index,name,point_type,distance_m,latitude,longitude,route_time_utc) VALUES(?,?,?,?,?,?,?,?,?)", (activity, "fit", index, values.get("name"), values.get("type"), values.get("distance"), lat, lon, stamp))
                        conn.execute("INSERT OR IGNORE INTO activity_aux_messages(activity_id,source_revision_id,global_message_number,message_name,message_index,timestamp_utc,payload_json) VALUES(?,?,?,?,?,?,?)", (activity, revision, int(getattr(frame, "global_mesg_num", -1)), "course_point_evidence", index, stamp, json.dumps({field.name: self._fit_field_evidence(field) for field in frame.fields}, sort_keys=True, allow_nan=False)))
                    elif name.startswith("unknown_"):
                        number = int(name.split("_", 1)[1]); unknown_stamp = self._fit_unknown_timestamp(frame.fields, stamp)
                        signature = json.dumps(sorted(({"name": field.name, "field_definition_number": field.def_num, "unit": field.units, "developer_data_index": getattr(getattr(field, "field_def", None), "dev_data_index", None) if getattr(field, "field_type", None) == "devfield" else None, "is_developer": getattr(field, "field_type", None) == "devfield"} for field in frame.fields), key=lambda item: (item["name"], item["field_definition_number"])), sort_keys=True, allow_nan=False)
                        conn.execute("INSERT INTO fit_unknown_message_catalog(source_revision_id,global_message_number,message_count,field_signature_json,first_timestamp_utc,last_timestamp_utc) VALUES(?,?,1,?,?,?) ON CONFLICT(source_revision_id,global_message_number) DO UPDATE SET message_count=message_count+1,first_timestamp_utc=CASE WHEN excluded.first_timestamp_utc IS NOT NULL AND (fit_unknown_message_catalog.first_timestamp_utc IS NULL OR excluded.first_timestamp_utc<fit_unknown_message_catalog.first_timestamp_utc) THEN excluded.first_timestamp_utc ELSE fit_unknown_message_catalog.first_timestamp_utc END,last_timestamp_utc=CASE WHEN excluded.last_timestamp_utc IS NOT NULL AND (fit_unknown_message_catalog.last_timestamp_utc IS NULL OR excluded.last_timestamp_utc>fit_unknown_message_catalog.last_timestamp_utc) THEN excluded.last_timestamp_utc ELSE fit_unknown_message_catalog.last_timestamp_utc END", (revision, number, signature, unknown_stamp, unknown_stamp))
                    elif name not in {"session", "activity", "file_id", "file_creator", "sport", "event", "developer_data_id", "device_settings", "zones_target"}:
                        index = indexes.get(name, 0); indexes[name] = index + 1; conn.execute("INSERT OR IGNORE INTO activity_aux_messages(activity_id,source_revision_id,global_message_number,message_name,message_index,timestamp_utc,payload_json) VALUES(?,?,?,?,?,?,?)", (activity, revision, int(getattr(frame, "global_mesg_num", -1)), name, index, stamp, json.dumps({field.name: self._fit_field_evidence(field) for field in frame.fields}, sort_keys=True, allow_nan=False)))
            for (metric_key, source_kind, developer_index, attribution), (valid_from, valid_to) in metric_ranges.items():
                exists = conn.execute("SELECT 1 FROM activity_metric_sources WHERE activity_id=? AND metric_key=? AND valid_from_utc IS ? AND valid_to_utc IS ? AND source_kind=? AND device_id IS NULL AND developer_data_index IS ? AND attribution_method=?", (activity, metric_key, valid_from, valid_to, source_kind, developer_index, attribution)).fetchone()
                if exists is None:
                    conn.execute("INSERT INTO activity_metric_sources(activity_id,metric_key,valid_from_utc,valid_to_utc,source_kind,device_id,developer_data_index,attribution_method,confidence) VALUES(?,?,?,?,?,?,?,?,?)", (activity, metric_key, valid_from, valid_to, source_kind, None, developer_index, attribution, 1.0 if attribution == "explicit_developer" else None))
        finally:
            shutil.rmtree(directory, ignore_errors=True)
