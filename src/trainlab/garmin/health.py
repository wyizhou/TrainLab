"""Account and health collection plus canonical health projections."""
from __future__ import annotations

from .contracts import *  # noqa: F403

class HealthCollectionMixin:
    def _account_basics(self, conn: sqlite3.Connection, run: int, subject: int, day: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Collect the reviewed account baseline without persisting PII payloads."""
        selected = set(request.resource_kinds)
        # The three device-reference resources are deliberately dependent on
        # this invocation's devices inventory.  No provider identifier is
        # cached across invocations.
        device_dependents = {"primary_device", "device_last_used", "device_settings"}
        resources = tuple(resource for resource in self._ACCOUNT_BASIC_RESOURCES if not selected or resource in selected or (resource == "devices" and bool(selected & device_dependents)))
        if not resources:
            return
        # Never reuse IDs discovered by a previous invocation.
        if "devices" in resources:
            self._account_device_ids = {}
            self._account_device_aliases = {}
            self._account_devices_ready = False
        from ..garmin_catalog import RESOURCE_CATALOG
        for resource in resources:
            spec = RESOURCE_CATALOG[resource]
            key = f"garmin:account:{resource}"
            try:
                payload = self._call(
                    lambda r=resource: self._transport().fetch_health(r, day.isoformat()),
                    conn=conn, run=run, subject=subject, resource=resource, key=key,
                    allows_404=spec.allows_404,
                )
                raw_payload = validate_provider_json_payload(payload)
                state = self._health_payload_state(payload, spec.empty_state)
                if state is not None:
                    if state != "empty":
                        self.repo.capability(conn, subject, resource, state, reason="provider_empty_or_capability", next_probe=self._account_next_probe(state), environment_key=self.config.region)
                    coverage_state = "partial" if request.mode == "snapshot" else state
                    if not self._promote_partial_coverage(
                        conn, subject, resource, day.isoformat(), request,
                        state, None,
                    ):
                        self.repo.coverage(conn, subject, resource, day.isoformat(), coverage_state, None, 0, snapshot=request.mode == "snapshot")
                    self.repo.item(conn, run, resource, key, "fetch", state, increment_attempt=False)
                    self._count_receipt_terminal(receipt, state)
                    self._resolve_successful_health_gaps(
                        conn, subject, resource, day.isoformat(), key, request, state,
                    )
                    continue
                self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                safe = self._safe_account_payload(resource, payload)
                if resource == "devices":
                    self._account_device_ids = self._device_id_map(payload)
                    self._account_device_aliases = self._device_alias_map(payload)
                provider_id = self._identity_hmac(f"account-resource:{resource}")

                def projector(revision: int, *, safe_payload: Any = safe, kind: str = resource) -> None:
                    if kind == "devices":
                        self._catalog_device_fields(conn, safe_payload)
                        count = self._project_devices(conn, safe_payload)
                    else:
                        self.repo.fields(conn, kind, safe_payload)
                        count = self._project_profile_settings(conn, subject, kind, safe_payload, revision)
                    self.repo.coverage(conn, subject, kind, day.isoformat(), "partial" if request.mode == "snapshot" else "fetched", revision, count, snapshot=request.mode == "snapshot")
                    self._resolve_successful_health_gaps(
                        conn, subject, kind, day.isoformat(), key, request, "fetched",
                    )

                semantic_payload = (
                    canonical_provider_json(safe)
                    if resource == "user_profile"
                    else None
                )
                _, revision, changed = self.repo.archive(
                    conn,
                    resource,
                    provider_id,
                    canonical_provider_json(raw_payload),
                    "json",
                    "application/json",
                    projector,
                    semantic_payload=semantic_payload,
                    profile_version=(
                        ACCOUNT_PROFILE_SEMANTIC_VERSION
                        if semantic_payload is not None
                        else None
                    ),
                )
                if resource == "devices":
                    self._account_devices_ready = True
                if not changed and request.mode == "snapshot":
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", revision, 0, snapshot=True)
                elif not changed:
                    self._promote_partial_coverage(
                        conn, subject, resource, day.isoformat(), request,
                        "fetched", revision,
                    )
                self._resolve_successful_health_gaps(
                    conn, subject, resource, day.isoformat(), key, request, "fetched",
                )
                self.repo.capability(conn, subject, resource, "supported", environment_key=self.config.region)
                self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                receipt.counts["revised" if changed else "unchanged"] += 1
            except GarminError as exc:
                outcome = self._classify(exc, allows_404=spec.allows_404)
                if outcome.status == "auth_required":
                    raise GarminError("auth_required", http_status=401) from None
                if outcome.status == "not_available" or exc.code == "not_supported":
                    state = "not_supported" if exc.code == "not_supported" else "not_available"
                    self.repo.capability(conn, subject, resource, state, reason=exc.code, next_probe=self._account_next_probe(state), environment_key=self.config.region)
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else state, None, 0, snapshot=request.mode == "snapshot")
                    terminal, retry = state, None
                elif outcome.status == "forbidden":
                    self.repo.capability(conn, subject, resource, "forbidden", reason=exc.code, next_probe=self._account_next_probe("forbidden"), environment_key=self.config.region)
                    terminal, retry = "forbidden", None
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else "forbidden", None, 0, snapshot=request.mode == "snapshot")
                else:
                    terminal = "deferred" if outcome.status == "deferred" else "failed"
                    retry = self._next_retry(exc, 0) if terminal == "deferred" else None
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                self._count_receipt_terminal(receipt, terminal)
                # Account-baseline absence prevents a complete account
                # snapshot.  It remains explicitly counted as unavailable
                # while correctly making this run partial.
                if terminal == "not_available":
                    receipt.counts["failed"] += 1
                self._resolve_successful_health_gaps(
                    conn, subject, resource, day.isoformat(), key, request, terminal,
                )
                receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            except Exception:
                error = GarminError("account_project_failed")
                if request.mode == "snapshot":
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                self.repo.item(conn, run, resource, key, "project", "failed", error=error)
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "project", error.code)
                receipt.counts["failed"] += 1

    def _account_b1(self, conn: sqlite3.Connection, run: int, subject: int, day: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Remaining reviewed account/device endpoints (L2-09B1 only)."""
        selected = set(request.resource_kinds)
        resources = tuple(resource for resource in self._ACCOUNT_B1_RESOURCES if not selected or resource in selected)
        if not resources:
            return
        from ..garmin_catalog import RESOURCE_CATALOG
        device_ids = dict(getattr(self, "_account_device_ids", {}))
        for resource in resources:
            spec = RESOURCE_CATALOG[resource]
            keys = list(device_ids.items()) if resource == "device_settings" else [(None, None)]
            # The final flag says whether this observation published a new
            # canonical revision.  It lets aggregate account coverage retain
            # the snapshot's proven record count on an unchanged promotion.
            outcomes: list[tuple[str, int | None, int, str | None, bool]] = []
            if resource in {"primary_device", "device_last_used"} and not getattr(self, "_account_devices_ready", False):
                key = f"garmin:account:{resource}:account"
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "discover", "not_available")
                self.repo.item(conn, run, resource, key, "discover", "not_available", increment_attempt=False)
                outcomes.append(("not_available", None, 0, "not_available", False))
                self._count_receipt_terminal(receipt, "not_available")
                self._resolve_successful_health_gaps(
                    conn, subject, resource, day.isoformat(), key, request, "not_available",
                )
                self._publish_b1_coverage(conn, subject, resource, day.isoformat(), request, outcomes)
                continue
            if resource == "device_settings" and not keys:
                self.repo.gap(conn, subject, resource, "garmin:account:device_settings", day.isoformat(), "discover", "not_available")
                self.repo.item(conn, run, resource, "garmin:account:device_settings", "discover", "not_available", increment_attempt=False)
                outcomes.append(("not_available", None, 0, "not_available", False))
                self._count_receipt_terminal(receipt, "not_available")
                self._resolve_successful_health_gaps(
                    conn, subject, resource, day.isoformat(), "garmin:account:device_settings", request, "not_available",
                )
            for device_hash, provider_id in keys:
                key = f"garmin:account:{resource}:{device_hash or 'account'}"
                try:
                    payload = self._call(
                        lambda r=resource, p=provider_id: self._fetch_account(r, p),
                        conn=conn, run=run, subject=subject, resource=resource,
                        key=key, allows_404=spec.allows_404,
                    )
                    raw_payload = validate_provider_json_payload(payload)
                    state = self._health_payload_state(payload, spec.empty_state)
                    if state is not None:
                        # Capability/empty responses are immutable, sanitized
                        # tombstones too.  They supersede an older account
                        # canonical projection instead of leaving it current.
                        provider_key = self._identity_hmac(f"account-b1:{resource}:{device_hash or 'account'}")
                        tombstone = {"availability_state": state}
                        coverage_state = "partial" if request.mode == "snapshot" else state
                        def tombstone_projector(revision: int, *, kind: str = resource) -> None:
                            self.repo.fields(conn, kind, tombstone)
                            self._supersede_b1_projection(conn, subject, kind)
                        _, revision, changed = self.repo.archive(conn, resource, provider_key, stable_json(tombstone), "json", "application/json", tombstone_projector)
                        self.repo.item(conn, run, resource, key, "fetch", state, revision_id=revision, increment_attempt=False)
                        outcomes.append((state, revision, 0, "provider_empty_or_capability" if state != "empty" else None, changed))
                        self._count_receipt_terminal(receipt, state)
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, day.isoformat(), key, request, state,
                        )
                        continue
                    # _call records running for every provider operation.
                    # A successful fetch must end before projection begins.
                    self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                    provider_key = self._identity_hmac(f"account-b1:{resource}:{device_hash or 'account'}")
                    def projector(
                        revision: int,
                        *,
                        kind: str = resource,
                        raw_payload: Any = payload,
                        hashed: str | None = device_hash,
                    ) -> None:
                        # Compute the redacted projection only after the raw
                        # object and received revision are durable.  A future
                        # wrapper drift therefore remains locally reparsable.
                        safe_payload = self._safe_b1_payload(
                            kind,
                            raw_payload,
                            device_hash=hashed,
                            device_ids=device_ids,
                            device_aliases=dict(
                                getattr(self, "_account_device_aliases", {})
                            ),
                        )
                        if kind in {"primary_device", "device_last_used", "device_settings"}:
                            count = self._project_device_b1(conn, subject, kind, safe_payload, hashed, revision)
                        else:
                            self._supersede_b1_projection(conn, subject, kind)
                            self.repo.fields(conn, kind, safe_payload)
                            count = self._project_b1_physiology(conn, subject, kind, safe_payload, revision)
                    reference_semantic = (
                        self._device_reference_semantic_payload(payload, resource)
                        if resource == "device_last_used"
                        else None
                    )
                    _, revision, changed = self.repo.archive(
                        conn,
                        resource,
                        provider_key,
                        canonical_provider_json(raw_payload),
                        "json",
                        "application/json",
                        projector,
                        semantic_payload=(
                            canonical_provider_json(reference_semantic)
                            if reference_semantic is not None
                            else None
                        ),
                        profile_version=(
                            DEVICE_REFERENCE_SEMANTIC_VERSION
                            if reference_semantic is not None
                            else None
                        ),
                    )
                    self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                    outcomes.append(("fetched", revision, 1, None, changed))
                    receipt.counts["revised" if changed else "unchanged"] += 1
                    self._resolve_successful_health_gaps(
                        conn, subject, resource, day.isoformat(), key, request, "fetched",
                    )
                except GarminError as exc:
                    outcome = self._classify(exc, allows_404=spec.allows_404)
                    if outcome.status == "auth_required": raise GarminError("auth_required", http_status=401) from None
                    if exc.code == "not_supported":
                        state, terminal, retry = "not_supported", "not_supported", None
                    elif outcome.status == "not_available":
                        state, terminal, retry = "not_available", "not_available", None
                    elif outcome.status == "forbidden":
                        state, terminal, retry = "forbidden", "forbidden", None
                    elif outcome.status == "deferred":
                        state, terminal, retry = "deferred", "deferred", self._next_retry(exc, 0)
                    else:
                        state, terminal, retry = "failed", "failed", None
                    if state in {"not_supported", "not_available", "forbidden"}:
                        pass
                    else:
                        self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                        if request.mode == "snapshot":
                            self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                    outcomes.append((terminal, None, 0, exc.code, False))
                    self._resolve_successful_health_gaps(
                        conn, subject, resource, day.isoformat(), key, request, terminal,
                    )
                    if terminal == "deferred":
                        self._count_receipt_terminal(receipt, terminal)
                        receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                    else:
                        self._count_receipt_terminal(receipt, terminal)
                except Exception as exc:
                    error = GarminError("unknown_device_reference" if str(exc) == "unknown_device_reference" else "account_project_failed")
                    self.repo.item(conn, run, resource, key, "project", "failed", error=error)
                    self.repo.gap(conn, subject, resource, key, day.isoformat(), "project", error.code)
                    outcomes.append(("failed", None, 0, error.code, False))
                    receipt.counts["failed"] += 1
            self._publish_b1_coverage(conn, subject, resource, day.isoformat(), request, outcomes)

    def _fetch_account(self, resource: str, provider_id: str | None) -> Any:
        method = getattr(self._transport(), "fetch_account", None)
        if not callable(method): raise GarminError("not_supported", http_status=404)
        return method(resource, provider_id)

    def _device_id_map(self, payload: Any) -> dict[str, str]:
        records = payload.get("devices", []) if isinstance(payload, dict) else payload
        result: dict[str, str] = {}
        if not isinstance(records, list): return result
        for entry in records:
            if not isinstance(entry, dict): continue
            provider_id = entry.get("deviceId") or entry.get("deviceUuid") or entry.get("unitId") or entry.get("serialNumber")
            if provider_id is not None: result[self._identity_hmac(f"device:{provider_id}")] = str(provider_id)
        return result

    def _device_alias_map(self, payload: Any) -> dict[str, str]:
        """Map every reviewed provider identifier to one canonical device hash."""
        records = payload.get("devices", []) if isinstance(payload, dict) else payload
        result: dict[str, str] = {}
        if not isinstance(records, list):
            return result
        for entry in records:
            if not isinstance(entry, dict):
                continue
            provider_id = (
                entry.get("deviceId")
                or entry.get("deviceUuid")
                or entry.get("unitId")
                or entry.get("serialNumber")
            )
            if provider_id is None:
                continue
            canonical = self._identity_hmac(f"device:{provider_id}")
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            ):
                alias = entry.get(field)
                if alias is not None:
                    result[self._identity_hmac(f"device:{alias}")] = canonical
        return result

    def _safe_b1_payload(
        self,
        resource: str,
        payload: Any,
        *,
        device_hash: str | None,
        device_ids: dict[str, str],
        device_aliases: dict[str, str] | None = None,
    ) -> Any:
        if resource in {"primary_device", "device_last_used"}:
            source = self._device_reference_object(payload, resource)
            aliases = device_aliases or {
                canonical: canonical for canonical in device_ids
            }
            canonical = None
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            ):
                provider_id = source.get(field)
                if provider_id is None:
                    continue
                canonical = aliases.get(
                    self._identity_hmac(f"device:{provider_id}")
                )
                if canonical is not None:
                    break
            if canonical is None or canonical not in device_ids:
                raise ValueError("unknown_device_reference")
            return {"device_uid_hash": canonical}
        if resource == "device_settings":
            if device_hash is None or device_hash not in device_ids: raise ValueError("unknown_device_reference")
            source = payload if isinstance(payload, dict) else {}
            safe = {"device_uid_hash": device_hash}
            for field in ("softwareVersion", "firmwareVersion", "batterySaveMode"):
                if isinstance(source.get(field), (str, int, float, bool)): safe[field] = source[field]
            return safe
        source = payload if isinstance(payload, dict) else {}
        allowed = {
            "personal_records": {"vo2Max", "maxHeartRate", "restingHeartRate"},
            "cycling_ftp": {"ftp", "ftpWatts"},
            "pregnancy": {"pregnancyWeek"},
        }[resource]
        return {key: source[key] for key in sorted(allowed) if isinstance(source.get(key), (int, float)) and not isinstance(source.get(key), bool)}

    @staticmethod
    def _device_reference_object(payload: Any, resource: str) -> dict[str, Any]:
        """Normalise the reviewed Connect wrappers without accepting guesses."""
        if isinstance(payload, list):
            if len(payload) != 1 or not isinstance(payload[0], dict):
                raise ValueError("unknown_device_reference")
            return payload[0]
        if not isinstance(payload, dict):
            raise ValueError("unknown_device_reference")
        wrappers = (
            (
                "primaryTrainingDevice",
                "PrimaryTrainingDevice",
                "primaryTrainingDeviceDTO",
                "primaryDevice",
                "deviceDTO",
                "device",
            )
            if resource == "primary_device"
            else (
                "lastUsedDevice",
                "lastUsedDeviceDTO",
                "deviceLastUsed",
                "deviceDTO",
                "device",
            )
        )
        for name in wrappers:
            value = payload.get(name)
            if isinstance(value, dict):
                return value
        return payload

    @classmethod
    def _device_reference_semantic_payload(
        cls,
        payload: Any,
        resource: str,
    ) -> dict[str, str] | None:
        """Select stable reference fields while retaining complete raw JSON."""
        try:
            source = cls._device_reference_object(payload, resource)
        except ValueError:
            return None
        reference = {
            field: str(source[field])
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            )
            if source.get(field) is not None
        }
        # Unknown wrapper drift falls back to full-response revisioning.  Its
        # complete raw object remains available for a later parser repair.
        return reference or None

    def _project_device_b1(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, device_hash: str | None, revision: int) -> int:
        hashed = payload.get("device_uid_hash") if isinstance(payload, dict) else device_hash
        if not hashed or conn.execute("SELECT 1 FROM devices WHERE device_uid_hash=?", (hashed,)).fetchone() is None:
            raise ValueError("unknown_device_reference")
        if resource == "device_settings":
            catalog = {key: value for key, value in payload.items() if key != "device_uid_hash"}
            self.repo.fields(conn, resource, catalog)
            for path in ("/softwareVersion", "/firmwareVersion", "/batterySaveMode"):
                self.repo.passthrough_field(conn, resource, path)
        # There is no device-role/settings table in the frozen Foundation DDL.
        # A revision-linked physiology record is the stable, de-identified
        # canonical relationship: provider IDs and serials never enter it.
        conn.execute(
            """DELETE FROM physiology_metrics WHERE physiology_record_id IN
               (SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND provider_record_id=?)""",
            (subject, resource, hashed),
        )
        conn.execute("DELETE FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND provider_record_id=?", (subject, resource, hashed))
        stamp = self._now_utc().isoformat().replace("+00:00", "Z")
        record = int(conn.execute(
            """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (subject, "garmin", resource, hashed, stamp, self._local_day(stamp), "provider_derived", stable_json({"device_uid_hash": hashed}), revision),
        ).lastrowid)
        values: dict[str, Any] = {}
        if resource == "primary_device": values["garmin.device.role.primary"] = True
        elif resource == "device_last_used": values["garmin.device.role.last_used"] = True
        else:
            values = {f"garmin.device.settings.{key}": value for key, value in payload.items() if key != "device_uid_hash"}
        for metric_key, value in values.items():
            conn.execute(
                """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_text,value_boolean,raw_unit,canonical_unit,value_origin,source_path)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (record, metric_key, float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                 value if isinstance(value, str) else None, int(value) if isinstance(value, bool) else None,
                 None, None, "provider_derived", "/" + metric_key.rsplit(".", 1)[-1]),
            )
        return 1

    def _publish_b1_coverage(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, request: SyncRequest, outcomes: list[tuple[str, int | None, int, str | None, bool]]) -> None:
        """One resource/day coverage row, after all per-device facts settle."""
        if not outcomes:
            return
        severity = {"fetched": 0, "empty": 1, "not_enabled": 2, "not_available": 3, "not_supported": 4, "forbidden": 5, "failed": 6, "deferred": 7}
        state, revision, _count, reason, _changed = max(outcomes, key=lambda outcome: severity.get(outcome[0], 6))
        total = sum(item[2] for item in outcomes) if state == "fetched" else 0
        coverage_state = "partial" if request.mode == "snapshot" else ({"failed": "error", "deferred": "partial"}.get(state, state))
        latest = conn.execute(
            """SELECT id,record_count,source_revision_id,availability_state
               FROM resource_coverage
               WHERE subject_id=? AND provider='garmin' AND resource_kind=?
                 AND local_date=?
               ORDER BY id DESC LIMIT 1""",
            (subject, resource, day),
        ).fetchone()
        terminal = {"fetched", "empty", "not_enabled", "not_available", "not_supported"}
        if (
            request.mode != "snapshot"
            and coverage_state in terminal
            and latest is not None
            and latest["availability_state"] == "partial"
            and all(not outcome[4] for outcome in outcomes)
        ):
            # A repeated account observation did not run a projector.  Keep
            # the already-proven aggregate count and only replace the
            # snapshot's partial state with the new terminal observation.
            conn.execute(
                "DELETE FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=? AND id<>?",
                (subject, resource, day, latest["id"]),
            )
            conn.execute(
                """UPDATE resource_coverage
                   SET availability_state=?,source_revision_id=?,observed_at_utc=?
                   WHERE id=?""",
                (
                    coverage_state,
                    revision if revision is not None else latest["source_revision_id"],
                    utc_now(),
                    latest["id"],
                ),
            )
            capability = "supported" if state in {"fetched", "empty"} else state
            if capability in {"supported", "not_enabled", "not_available", "not_supported", "forbidden"}:
                self.repo.capability(conn, subject, resource, capability, reason=reason, next_probe=self._account_next_probe(capability), environment_key=self.config.region)
            return
        # Source revisions preserve history.  Coverage is the one current
        # aggregate claim for this account resource/date, never one row per
        # device response.
        conn.execute("DELETE FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=?", (subject, resource, day))
        self.repo.coverage(conn, subject, resource, day, coverage_state, revision, total, snapshot=request.mode == "snapshot")
        capability = "supported" if state in {"fetched", "empty"} else state
        if capability in {"supported", "not_enabled", "not_available", "not_supported", "forbidden"}:
            self.repo.capability(conn, subject, resource, capability, reason=reason, next_probe=self._account_next_probe(capability), environment_key=self.config.region)

    @staticmethod
    def _count_receipt_terminal(receipt: SyncReceipt, terminal: str) -> None:
        """Map every durable terminal state to receipt-v1's fixed counters."""
        counter = {
            "not_supported": "not_available",
            "forbidden": "failed",
        }.get(terminal, terminal)
        if counter in receipt.counts:
            receipt.counts[counter] += 1

    @staticmethod
    def _supersede_b1_projection(conn: sqlite3.Connection, subject: int, resource: str) -> None:
        """Account snapshots have one current canonical view per resource."""
        if resource in {"personal_records", "cycling_ftp", "pregnancy"}:
            conn.execute(
                """DELETE FROM physiology_metrics WHERE physiology_record_id IN
                   (SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=?)""",
                (subject, resource),
            )
            conn.execute("DELETE FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=?", (subject, resource))

    def _project_b1_physiology(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, revision: int) -> int:
        if not payload: return 0
        stamp = self._now_utc().isoformat().replace("+00:00", "Z")
        cursor = conn.execute("INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)", (subject, "garmin", resource, stamp, self._local_day(stamp), "provider_derived", "{}", revision))
        record = int(cursor.lastrowid)
        for key, value in payload.items():
            metric_key, unit = self._b1_metric_definition(resource, key)
            conn.execute("INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path) VALUES(?,?,?,?,?,?,?)", (record, metric_key, float(value), unit, unit, "provider_derived", f"/{key}"))
            self.repo.map_field(conn, resource, f"/{key}", metric_key)
        return 1

    @staticmethod
    def _b1_metric_definition(resource: str, key: str) -> tuple[str, str | None]:
        """Reviewed scalar metrics; no provider container is treated as a metric."""
        units = {
            ("personal_records", "vo2Max"): "ml/kg/min",
            ("personal_records", "maxHeartRate"): "bpm",
            ("personal_records", "restingHeartRate"): "bpm",
            ("cycling_ftp", "ftp"): "W",
            ("cycling_ftp", "ftpWatts"): "W",
            ("pregnancy", "pregnancyWeek"): "week",
        }
        return f"garmin.{resource}.{key}", units.get((resource, key))

    def _account_next_probe(self, state: str) -> str | None:
        if state not in {"not_enabled", "not_available", "not_supported", "forbidden"}:
            return None
        return (self._now_utc() + timedelta(days=7)).isoformat().replace("+00:00", "Z")

    def _safe_account_payload(self, resource: str, payload: Any) -> Any:
        if resource in {"user_profile", "user_profile_settings"}:
            source = payload if isinstance(payload, dict) else {}
            safe: dict[str, str | int | float | bool] = {}
            for key in sorted(self._PROFILE_SETTING_FIELDS):
                value = source.get(key)
                if isinstance(value, (str, int, float, bool)):
                    safe[key] = value
            return safe
        if resource == "devices":
            source = payload.get("devices", []) if isinstance(payload, dict) else payload
            if not isinstance(source, list):
                raise ValueError("invalid_devices_payload")
            devices: list[dict[str, str]] = []
            for entry in source:
                if not isinstance(entry, dict):
                    raise ValueError("invalid_device_entry")
                uid = entry.get("deviceId") or entry.get("deviceUuid") or entry.get("unitId") or entry.get("serialNumber")
                if uid is None:
                    raise ValueError("missing_device_uid")
                safe = {"device_uid_hash": self._identity_hmac(f"device:{uid}")}
                for source_key, target_key in (("manufacturer", "manufacturer"), ("product", "product"), ("productName", "product"), ("deviceType", "deviceType"), ("type", "deviceType"), ("hardwareVersion", "hardwareVersion")):
                    value = entry.get(source_key)
                    if value is not None and target_key not in safe:
                        safe[target_key] = str(value)
                # Software is not hardware. The stable devices DDL has no
                # software column, so the reviewed raw source field is kept as
                # a known passthrough and never populates hardware_version.
                if entry.get("softwareVersion") is not None:
                    safe["softwareVersion"] = str(entry["softwareVersion"])
                devices.append(safe)
            return {"devices": sorted(devices, key=lambda device: device["device_uid_hash"])}
        raise ValueError("unknown_account_resource")

    def _catalog_device_fields(self, conn: sqlite3.Connection, payload: Any) -> None:
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        catalog_payload = {"devices": [{key: value for key, value in device.items() if key != "device_uid_hash"} for device in devices]}
        self.repo.fields(conn, "devices", catalog_payload)
        for path, key in (
            ("/devices/*/hardwareVersion", "garmin.device.hardware_version"),
        ):
            self.repo.map_field(conn, "devices", path, key)
        for path in ("/devices/*/softwareVersion", "/devices/*/manufacturer", "/devices/*/product", "/devices/*/deviceType"):
            self.repo.passthrough_field(conn, "devices", path)

    def _project_devices(self, conn: sqlite3.Connection, payload: Any) -> int:
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        for device in devices:
            conn.execute(
                """INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,hardware_version,first_seen_at_utc,last_seen_at_utc)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET
                   manufacturer=excluded.manufacturer,product=excluded.product,device_type=excluded.device_type,
                   hardware_version=excluded.hardware_version,last_seen_at_utc=excluded.last_seen_at_utc""",
                (device["device_uid_hash"], device.get("manufacturer"), device.get("product"), device.get("deviceType"), device.get("hardwareVersion"), now, now),
            )
        return len(devices)

    def _project_profile_settings(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, revision: int) -> int:
        if not isinstance(payload, dict):
            return 0
        allowed = {key: value for key, value in payload.items() if key in self._PROFILE_SETTING_FIELDS}
        if not allowed:
            return 0
        # Revisions make the view current; do not retain an unbounded complete
        # provider response in extras_json.
        cursor = conn.execute(
            """INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            (subject, "garmin", resource, self._now_utc().isoformat().replace("+00:00", "Z"), self._now_utc().astimezone(TZ).date().isoformat(), "profile_setting", "{}", revision),
        )
        record = int(cursor.lastrowid)
        for key, value in allowed.items():
            numeric = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            text = value if isinstance(value, str) else None
            boolean = int(value) if isinstance(value, bool) else None
            conn.execute(
                """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_text,value_boolean,raw_unit,canonical_unit,value_origin,source_path)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (record, f"garmin.profile.{key}", numeric, text, boolean, None, None, "profile_setting", f"/{key}"),
            )
            self.repo.map_field(conn, resource, f"/{key}", f"garmin.profile.{key}")
        return 1

    @staticmethod
    def _health_item_completed(
        conn: sqlite3.Connection,
        run: int,
        resource: str,
        logical_key: str,
    ) -> bool:
        """Return true only for a fully durable successful health work item."""
        stages = {
            str(row["stage"]): str(row["status"])
            for row in conn.execute(
                """SELECT stage,status FROM garmin_sync_items
                    WHERE garmin_sync_run_id=? AND resource_kind=?
                      AND logical_object_key=?""",
                (run, resource, logical_key),
            )
        }
        fetch = stages.get("fetch")
        if fetch in {
            "empty", "not_available", "not_enabled", "not_supported",
        }:
            return True
        return (
            fetch == "fetched"
            and stages.get("project") in {"revised", "unchanged", "succeeded"}
        )

    def _resolve_successful_health_gaps(
        self,
        conn: sqlite3.Connection,
        subject: int,
        resource: str,
        day: str,
        logical_key: str,
        request: SyncRequest,
        terminal: str,
    ) -> None:
        """Close only the exact completed health/account observation.

        A repeated raw response can legitimately leave ``archive`` unchanged,
        so projection is not invoked.  Gap resolution is an observation-level
        effect, rather than a projection-only effect.  Keep it fail-closed:
        snapshots, failures, deferrals and forbidden responses cannot resolve
        a historical full-day gap, and a same-day sibling key stays untouched.
        """
        if request.mode == "snapshot" or terminal not in {
            "fetched", "empty", "not_available", "not_enabled", "not_supported",
        }:
            return
        self.repo.resolve_gaps(
            conn, subject, resource, day, logical_object_key=logical_key,
        )

    def _promote_partial_coverage(
        self,
        conn: sqlite3.Connection,
        subject: int,
        resource: str,
        day: str,
        request: SyncRequest,
        state: str,
        revision: int | None,
    ) -> bool:
        """Promote a latest snapshot claim after a successful full observation.

        A snapshot deliberately stores ``partial`` even when its raw object is
        already current.  A later non-snapshot fetch may consequently be
        unchanged and skip the projector.  Promote that *same* coverage row
        rather than inventing a new projection count or a duplicate lineage
        claim.  This is deliberately unavailable to snapshots, failures,
        deferrals and forbidden responses.
        """
        if request.mode == "snapshot" or state not in {
            "fetched", "empty", "not_available", "not_enabled", "not_supported",
        }:
            return False
        row = conn.execute(
            """SELECT id,record_count,source_revision_id,availability_state
               FROM resource_coverage
               WHERE subject_id=? AND provider='garmin' AND resource_kind=?
                 AND local_date=?
               ORDER BY id DESC LIMIT 1""",
            (subject, resource, day),
        ).fetchone()
        if row is None or row["availability_state"] != "partial":
            return False
        # A snapshot preserves its projected count.  A later unchanged full
        # response must therefore not call a zero-record snapshot "fetched".
        if state == "fetched" and row["record_count"] == 0:
            state = "empty"
        conn.execute(
            """UPDATE resource_coverage
               SET availability_state=?,source_revision_id=?,observed_at_utc=?
               WHERE id=?""",
            (
                state,
                revision if revision is not None else row["source_revision_id"],
                utc_now(),
                row["id"],
            ),
        )
        return True

    def _health(self, conn: sqlite3.Connection, run: int, subject: int, start: date, through: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        selected = set(request.resource_kinds) or set(HEALTH_RESOURCES)
        from ..garmin_catalog import RESOURCE_CATALOG
        # Compatibility doubles used by pre-range tests expose only the old
        # one-day protocol. Real pinned transport always provides fetch_range.
        range_resources = ({resource for resource in selected if resource in RESOURCE_CATALOG and RESOURCE_CATALOG[resource].scope == "range"}
                           if callable(getattr(self._transport(), "fetch_range", None)) else set())
        for resource in sorted(range_resources):
            self._health_range(conn, run, subject, resource, start, through, request, receipt)
        selected -= range_resources
        for day in (start + timedelta(i) for i in range((through - start).days + 1)):
            for resource in HEALTH_RESOURCES:
                if resource not in selected: continue
                key = f"garmin:health:{resource}:{day}"
                if self._health_item_completed(conn, run, resource, key):
                    continue
                try:
                    spec = RESOURCE_CATALOG[resource]
                    payload = self._call(
                        lambda r=resource, d=day: self._transport().fetch_health(r, d.isoformat()),
                        conn=conn, run=run, subject=subject, resource=resource, key=key,
                        allows_404=spec.allows_404,
                    )
                    # Validate before recording a successful fetch stage: a
                    # credential-bearing response is quarantined with zero
                    # raw/revision/canonical writes.
                    stored_payload = validate_provider_json_payload(payload)
                    payload_state = self._health_payload_state(stored_payload, spec.empty_state)
                    if payload_state is not None:
                        capability = "supported" if payload_state == "empty" else payload_state
                        self.repo.capability(
                            conn, subject, resource, capability,
                            reason="provider_empty_or_capability" if capability != "supported" else None,
                            next_probe=self._account_next_probe(capability),
                            environment_key=self.config.region,
                        )
                        coverage_state = "partial" if request.mode == "snapshot" else payload_state
                        def tombstone_projector(revision: int) -> None:
                            self.repo.fields(conn, resource, stored_payload)
                            self._supersede_health_projection(conn, subject, resource, key, day.isoformat())
                            self.repo.coverage(conn, subject, resource, day.isoformat(), coverage_state, revision, 0, snapshot=request.mode == "snapshot")
                            self._resolve_successful_health_gaps(
                                conn, subject, resource, day.isoformat(), key, request, payload_state,
                            )
                        _, revision, changed = self.repo.archive(
                            conn, resource, key, canonical_provider_json(stored_payload), "json", "application/json", tombstone_projector
                        )
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, day.isoformat(), key, request, payload_state,
                        )
                        if not changed and not self._promote_partial_coverage(
                            conn, subject, resource, day.isoformat(), request,
                            payload_state, revision,
                        ):
                            # A stable tombstone remains an immutable current
                            # revision; record this observation with provenance.
                            self.repo.coverage(conn, subject, resource, day.isoformat(), coverage_state, revision, 0, snapshot=request.mode == "snapshot")
                            self._resolve_successful_health_gaps(
                                conn, subject, resource, day.isoformat(), key, request, payload_state,
                            )
                        self.repo.item(conn, run, resource, key, "fetch", payload_state, revision_id=revision, increment_attempt=False)
                        if payload_state in receipt.counts: receipt.counts[payload_state] += 1
                        continue
                    self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                    def projector(revision: int):
                        self.repo.fields(conn, resource, stored_payload)
                        self._supersede_health_projection(conn, subject, resource, key, day.isoformat())
                        projected = self._project_health(conn, subject, resource, day.isoformat(), stored_payload, revision)
                        completed_state = "fetched" if projected > 0 else "empty"
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else completed_state, revision, projected, snapshot=request.mode == "snapshot")
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, day.isoformat(), key, request, completed_state,
                        )
                    _, revision, changed = self.repo.archive(conn, resource, key, canonical_provider_json(stored_payload), "json", "application/json", projector)
                    if not changed:
                        self._promote_partial_coverage(
                            conn, subject, resource, day.isoformat(), request,
                            "fetched", revision,
                        )
                    self._resolve_successful_health_gaps(
                        conn, subject, resource, day.isoformat(), key, request, "fetched",
                    )
                    self.repo.capability(
                        conn, subject, resource, "supported",
                        environment_key=self.config.region,
                    )
                    self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision); receipt.counts["revised" if changed else "unchanged"] += 1
                except GarminError as exc:
                    outcome = self._classify(exc, allows_404=spec.allows_404)
                    if outcome.status == "auth_required":
                        raise GarminError("auth_required", http_status=401) from None
                    if outcome.status == "not_available" or exc.code == "not_supported":
                        state = "not_supported" if exc.code == "not_supported" else "not_available"
                        self.repo.capability(conn, subject, resource, state, reason=exc.code, next_probe=self._account_next_probe(state), environment_key=self.config.region)
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else state, None, 0, snapshot=request.mode == "snapshot")
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, day.isoformat(), key, request, state,
                        )
                        self.repo.item(conn, run, resource, key, "fetch", state, error=exc, increment_attempt=False)
                        if state in receipt.counts: receipt.counts[state] += 1
                        continue
                    if outcome.status == "forbidden":
                        self.repo.capability(conn, subject, resource, "forbidden", reason=exc.code, next_probe=self._account_next_probe("forbidden"), environment_key=self.config.region)
                        terminal, retry = "forbidden", None
                    elif outcome.status == "deferred":
                        terminal, retry = "deferred", self._next_retry(exc, 0)
                    else:
                        terminal, retry = "failed", None
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    elif outcome.status == "forbidden":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "forbidden", None, 0)
                    self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                    self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                    receipt.counts["deferred" if terminal == "deferred" else "failed"] += 1
                    receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                except Exception:
                    error = GarminError("parse_or_project_failed")
                    received_revision = self._unparsed_revision(conn, resource, key)
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    self.repo.item(conn, run, resource, key, "project", "failed", error=error, revision_id=received_revision)
                    self.repo.gap(
                        conn,
                        subject,
                        resource,
                        key,
                        day.isoformat(),
                        "project",
                        error.code,
                        revision=received_revision,
                    )
                    receipt.counts["failed"] += 1
                finally:
                    if resource in ADVANCED_RESOURCES:
                        self._consolidate_advanced_coverage(conn, subject, resource, day.isoformat())

    def _health_range(self, conn: sqlite3.Connection, run: int, subject: int, resource: str, start: date, through: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Fetch a bounded provider range once and fan it out with shared lineage."""
        from ..garmin_catalog import RESOURCE_CATALOG
        spec = RESOURCE_CATALOG[resource]
        maximum_days = spec.max_range_days
        if maximum_days is None or maximum_days < 1:
            raise ValueError("range_spec_missing_max_days")
        cursor = start
        while cursor <= through:
            end = min(through, cursor + timedelta(days=maximum_days - 1))
            logical_key = f"garmin:health:{resource}:{cursor}:{end}"
            if self._health_item_completed(conn, run, resource, logical_key):
                cursor = end + timedelta(days=1)
                continue
            try:
                payload = self._call(lambda s=cursor, e=end: self._transport().fetch_range(resource, s.isoformat(), e.isoformat()), conn=conn, run=run, subject=subject, resource=resource, key=logical_key, allows_404=spec.allows_404)
                stored = validate_provider_json_payload(payload)
                state = self._health_payload_state(stored, spec.empty_state)
                days = [cursor + timedelta(index) for index in range((end - cursor).days + 1)]
                if state is not None:
                    def tombstone(revision: int) -> None:
                        for current_day in days:
                            self._supersede_range_projection(conn, subject, resource, current_day.isoformat())
                            self.repo.coverage(conn, subject, resource, current_day.isoformat(), "partial" if request.mode == "snapshot" else state, revision, 0, snapshot=request.mode == "snapshot")
                    _, revision, changed = self.repo.archive(conn, resource, logical_key, canonical_provider_json(stored), "json", "application/json", tombstone)
                    if not changed:
                        for current_day in days:
                            self._promote_partial_coverage(
                                conn, subject, resource, current_day.isoformat(),
                                request, state, revision,
                            )
                    self.repo.item(conn, run, resource, logical_key, "fetch", state, revision_id=revision, increment_attempt=False)
                    self._count_receipt_terminal(receipt, state)
                    capability = "supported" if state == "empty" else state
                    self.repo.capability(conn, subject, resource, capability, reason="provider_empty_or_capability" if capability != "supported" else None, next_probe=self._account_next_probe(capability), environment_key=self.config.region)
                    for current_day in days:
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, current_day.isoformat(), logical_key, request, state,
                        )
                    cursor = end + timedelta(days=1); continue
                self.repo.item(conn, run, resource, logical_key, "fetch", "fetched", increment_attempt=False)
                def projector(revision: int) -> None:
                    # Validate every returned record before deleting or writing
                    # any canonical row.  The received revision already exists
                    # at this point, so a malformed range remains reparsable.
                    by_day = self._range_payload_by_day(stored, cursor, end, resource=resource)
                    lactate_envelope = resource == "lactate_threshold" and isinstance(stored, dict) and any(
                        isinstance(stored.get(family), list)
                        for family in ("heart_rate", "power", "speed")
                    )
                    if lactate_envelope:
                        self.repo.fields(conn, resource, stored)
                    for current_day in days:
                        day_payload = by_day[current_day.isoformat()]
                        self._supersede_range_projection(conn, subject, resource, current_day.isoformat())
                        # Lactate's range envelope identifies the metric family
                        # only at the top level.  Catalogue that source shape,
                        # rather than the internally grouped day payload below.
                        if not lactate_envelope:
                            self.repo.fields(conn, resource, day_payload)
                        count = self._project_health(conn, subject, resource, current_day.isoformat(), day_payload, revision) if day_payload else 0
                        # Sparse records are a per-day absence, not an account
                        # capability conclusion.  Only an explicitly empty
                        # *whole response* above uses spec.empty_state.
                        state_for_day = "partial" if request.mode == "snapshot" else ("fetched" if count > 0 else "empty")
                        self.repo.coverage(conn, subject, resource, current_day.isoformat(), state_for_day, revision, count, snapshot=request.mode == "snapshot")
                        self._resolve_successful_health_gaps(
                            conn, subject, resource, current_day.isoformat(), logical_key, request, "fetched",
                        )
                _, revision, changed = self.repo.archive(conn, resource, logical_key, canonical_provider_json(stored), "json", "application/json", projector)
                if not changed:
                    by_day = self._range_payload_by_day(
                        stored, cursor, end, resource=resource,
                    )
                    for current_day in days:
                        state_for_day = (
                            "fetched"
                            if by_day[current_day.isoformat()]
                            else "empty"
                        )
                        self._promote_partial_coverage(
                            conn, subject, resource, current_day.isoformat(),
                            request, state_for_day, revision,
                        )
                for current_day in days:
                    self._resolve_successful_health_gaps(
                        conn, subject, resource, current_day.isoformat(), logical_key, request, "fetched",
                    )
                # Sparse per-day absence is coverage only; a successful range
                # response still proves the resource is supported.
                self.repo.capability(conn, subject, resource, "supported", environment_key=self.config.region)
                self.repo.item(conn, run, resource, logical_key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                receipt.counts["revised" if changed else "unchanged"] += 1
            except GarminError as exc:
                outcome = self._classify(exc, allows_404=spec.allows_404)
                if outcome.status == "auth_required":
                    raise GarminError("auth_required", http_status=401) from None
                retry = self._next_retry(exc, 0) if outcome.status == "deferred" else None
                terminal = "not_supported" if exc.code == "not_supported" else ("not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if outcome.status == "deferred" else "failed")))
                self.repo.item(conn, run, resource, logical_key, "fetch", terminal, error=exc, increment_attempt=False)
                if terminal in {"not_available", "not_supported", "forbidden"}:
                    self.repo.capability(conn, subject, resource, terminal, reason=exc.code, next_probe=self._account_next_probe(terminal), environment_key=self.config.region)
                for current_day in [cursor + timedelta(index) for index in range((end - cursor).days + 1)]:
                    coverage_state = "partial" if request.mode == "snapshot" else (terminal if terminal in {"not_available", "not_supported", "forbidden"} else "error")
                    self.repo.coverage(conn, subject, resource, current_day.isoformat(), coverage_state, None, 0, snapshot=request.mode == "snapshot")
                if terminal in {"not_available", "not_supported"}:
                    # Preserve the observed recovery history without leaving a
                    # deterministic capability absence as a cursor blocker.
                    self.repo.gap(
                        conn, subject, resource, logical_key,
                        cursor.isoformat(), "fetch", exc.code,
                        end_day=end.isoformat(),
                    )
                    if request.mode != "snapshot":
                        for current_day in (
                            cursor + timedelta(index)
                            for index in range((end - cursor).days + 1)
                        ):
                            self.repo.resolve_gaps(
                                conn, subject, resource,
                                current_day.isoformat(),
                                logical_object_key=logical_key,
                                stages=("fetch",),
                            )
                else:
                    self.repo.gap(conn, subject, resource, logical_key, cursor.isoformat(), "fetch", exc.code, end_day=end.isoformat(), deferred=terminal == "deferred", next_retry=retry)
                receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                self._count_receipt_terminal(receipt, terminal)
                if terminal == "deferred":
                    # Do not turn a provider cooldown into a burst across
                    # later chunks.  The unscheduled remainder has no
                    # coverage claim and will be planned by the next run.
                    break
            except Exception:
                error = GarminError("parse_or_project_failed")
                received_revision = self._unparsed_revision(conn, resource, logical_key)
                self.repo.item(conn, run, resource, logical_key, "project", "failed", error=error, revision_id=received_revision)
                self.repo.gap(conn, subject, resource, logical_key, cursor.isoformat(), "project", error.code, end_day=end.isoformat(), revision=received_revision)
                receipt.counts["failed"] += 1
            cursor = end + timedelta(days=1)

    def _range_payload_by_day(self, payload: Any, start: date, end: date, *, resource: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Validate a whole provider response, then fan sparse records by day.

        A range response is permitted to contain no record for a legal day
        (weigh-ins and menstrual events are naturally sparse).  Missing or
        malformed dates on *returned* records are not sparse: they invalidate
        the whole chunk before any canonical projection occurs.
        """
        records = self._range_records(payload, resource=resource)
        selected: dict[str, list[dict[str, Any]]] = {
            (start + timedelta(index)).isoformat(): []
            for index in range((end - start).days + 1)
        }
        for record in records:
            date_keys = [
                "calendarDate",
                "timestamp",
                "timestampGMT",
                "measurementTimestampGMT",
                "gmtTimestamp",
                "startTimeGMT",
                "startTimestampGMT",
            ]
            if resource == "lactate_threshold":
                # Garmin's lactate range entries are dated by their update,
                # not by the enclosing response's from/until bounds.
                date_keys.insert(0, "updatedDate")
            if resource in {
                "body_battery",
                "body_composition",
                "weigh_ins",
                "blood_pressure",
            }:
                # These reviewed range envelopes use a local calendar `date`.
                # Do not accept that ambiguous key for unrelated resources.
                date_keys.insert(1, "date")
            stamp = next(
                (
                    record.get(key)
                    for key in date_keys
                    if record.get(key) is not None
                ),
                None,
            )
            if stamp is None:
                raise ValueError("range_record_missing_date")
            parsed = self._timestamp_utc(stamp, start.isoformat(), allow_day_boundary=True)
            local_day = self._local_day(parsed)
            if local_day not in selected and resource == "endurance_score":
                # The precise-day endpoint can return the latest available
                # score even when it predates the requested window.  Keep that
                # response as raw evidence without assigning it to this day.
                continue
            if local_day not in selected:
                raise ValueError("range_record_outside_window")
            if resource in ADVANCED_RESOURCES and resource != "lactate_threshold" and selected[local_day]:
                # Reviewed advanced range endpoints carry one daily summary;
                # duplicate calendar records are a shape drift, not a second
                # canonical prediction.  Measurement endpoints may validly
                # contain multiple same-day observations and remain allowed.
                raise ValueError("range_duplicate_day")
            selected[local_day].append(record)
        return selected

    def _range_payload_for_day(self, payload: Any, day: str, span: int) -> Any:
        # Compatibility helper retained for older callers/tests.
        start = date.fromisoformat(day)
        return self._range_payload_by_day(payload, start, start + timedelta(days=span - 1))[day]

    @staticmethod
    def _unparsed_revision(conn: sqlite3.Connection, resource: str, provider_id: str) -> int | None:
        row = conn.execute(
            """SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=?
               AND provider_object_id=? AND is_current=0 AND parsed_at_utc IS NULL
               ORDER BY revision_no DESC LIMIT 1""",
            (resource, provider_id),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _range_records(
        self, payload: Any, *, resource: str | None = None
    ) -> list[dict[str, Any]]:
        """Open only reviewed range envelopes; metadata is never a record."""
        if isinstance(payload, dict):
            if resource == "weigh_ins" and isinstance(payload.get("dailyWeightSummaries"), list):
                # Daily summaries are envelopes.  Only allWeightMetrics holds
                # measurements; latestWeight is a summary pointer and would
                # otherwise duplicate a canonical observation.
                return [
                    metric
                    for summary in payload["dailyWeightSummaries"]
                    if isinstance(summary, dict)
                    for metric in (
                        summary.get("allWeightMetrics")
                        if isinstance(summary.get("allWeightMetrics"), list)
                        else []
                    )
                    if isinstance(metric, dict)
                ]
            if resource == "lactate_threshold" and any(
                isinstance(payload.get(name), list)
                for name in ("heart_rate", "power", "speed")
            ):
                # Retain the provider family only as ephemeral projection
                # context.  It is never archived and never field-catalogued.
                return [
                    {**entry, "__trainlab_lactate_family": family}
                    for family in ("heart_rate", "power", "speed")
                    for entry in (payload.get(family) if isinstance(payload.get(family), list) else [])
                    if isinstance(entry, dict)
                ]
            wrappers: dict[str, tuple[str, ...]] = {
                "body_composition": ("dateWeightList",),
                "weigh_ins": ("dailyWeightSummaries",),
                "blood_pressure": ("measurementSummaries",),
                "lactate_threshold": ("speed", "heart_rate", "power"),
                "menstrual": (
                    "cycleSummaries",
                    "loggedNoteDays",
                    "loggedOvulationDays",
                    "loggedSymptomDays",
                ),
            }
            selected_wrappers = wrappers.get(resource or "")
            if selected_wrappers is not None and any(
                name in payload for name in selected_wrappers
            ):
                return [
                    item
                    for name in selected_wrappers
                    for item in (
                        payload.get(name)
                        if isinstance(payload.get(name), list)
                        else []
                    )
                    if isinstance(item, dict)
                ]
            if (
                resource == "endurance_score"
                and "enduranceScoreDTO" in payload
            ):
                value = payload.get("enduranceScoreDTO")
                if value in (None, {}):
                    return []
                if not isinstance(value, dict):
                    raise ValueError("range_envelope_invalid")
                return [value]
            if (
                resource == "endurance_score"
                and "calendarDate" in payload
                and payload.get("calendarDate") is None
            ):
                # A supported account without a score yet returns the DTO
                # shape with a null day.  It is a valid empty observation for
                # the requested window, not a timestampless score.
                return []
            if resource == "endurance_score" and "calendarDate" in payload:
                # `contributors` is nested metadata, not a list of dated
                # records.  Keep the DTO itself as the sole daily record.
                return [payload]
            if (
                resource == "hill_score"
                and payload.get("hillScoreDTOList") == []
                and payload.get("maxScore") is None
                and isinstance(payload.get("periodAvgScore"), dict)
                and all(value is None for value in payload["periodAvgScore"].values())
            ):
                # A supported account can have no hill-score observations in
                # the requested period.  It is an empty range, never score 0.
                return []
        records = self._advanced_records(payload) if isinstance(payload, (dict, list)) else []
        if isinstance(payload, dict) and records == [payload]:
            nested = [item for value in payload.values() if isinstance(value, list) for item in value if isinstance(item, dict)]
            if nested:
                return nested
        return records

    @staticmethod
    def _supersede_range_projection(conn: sqlite3.Connection, subject: int, resource: str, day: str) -> None:
        conn.execute(
            """DELETE FROM body_measurements
                 WHERE subject_id=? AND local_date=?
                   AND source_revision_id IN (
                       SELECT id FROM source_revisions
                        WHERE provider='garmin' AND resource_kind=?
                   )""",
            (subject, day, resource),
        )
        records = list(conn.execute("SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND local_date=?", (subject, resource, day)))
        if records:
            ids = tuple(row[0] for row in records)
            conn.execute("DELETE FROM physiology_metrics WHERE physiology_record_id IN (%s)" % ",".join("?" for _ in ids), ids)
            conn.execute("DELETE FROM physiology_records WHERE id IN (%s)" % ",".join("?" for _ in ids), ids)

    @staticmethod
    def _consolidate_advanced_coverage(conn: sqlite3.Connection, subject: int, resource: str, day: str) -> None:
        """Advanced lookback has one unambiguous final resource/day verdict."""
        rows = conn.execute(
            """SELECT id FROM resource_coverage WHERE subject_id=? AND provider='garmin'
               AND resource_kind=? AND local_date=? ORDER BY id DESC""",
            (subject, resource, day),
        ).fetchall()
        if len(rows) > 1:
            conn.execute(
                "DELETE FROM resource_coverage WHERE id IN (%s)" % ",".join("?" for _ in rows[1:]),
                tuple(row["id"] for row in rows[1:]),
            )

    @staticmethod
    def _health_payload_state(payload: Any, empty_state: str) -> str | None:
        """Recognise only explicit provider capability states; null never means zero."""
        if payload is None or payload == [] or payload == {}:
            return empty_state
        if isinstance(payload, dict):
            state = payload.get("availability_state") or payload.get("capability_state")
            if state in {"not_enabled", "not_available", "not_supported"}:
                return str(state)
        return None

    @staticmethod
    def _timestamp_utc(
        value: Any,
        fallback_day: str,
        *,
        allow_day_boundary: bool = False,
        assume_utc: bool = False,
    ) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Garmin epoch timestamps appear in seconds or milliseconds.
            seconds = float(value) / 1000 if abs(value) > 10_000_000_000 else float(value)
            try:
                return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                pass
        if isinstance(value, str) and value:
            # JSON object keys are strings.  Garmin's ``sleepLevelsMap`` and
            # hourly maps therefore expose epoch seconds/milliseconds as text,
            # even though the same endpoint uses numeric values in arrays.
            # Test this before ISO parsing: ``fromisoformat`` cannot identify
            # an epoch key and would otherwise silently fall back to midnight.
            candidate_number = value.strip()
            try:
                if candidate_number and candidate_number.lstrip("+-").replace(".", "", 1).isdigit():
                    seconds = float(candidate_number)
                    seconds = seconds / 1000 if abs(seconds) > 10_000_000_000 else seconds
                    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                pass
            # ``datetime.fromisoformat('YYYY-MM-DD')`` silently creates
            # midnight.  Date-only input is legal only for resource specs
            # which explicitly model a local-day aggregate.
            if len(value) == 10:
                try:
                    parsed_day = date.fromisoformat(value)
                except ValueError:
                    parsed_day = None
                if parsed_day is not None:
                    if not allow_day_boundary:
                        raise ValueError("date_only_timestamp_not_allowed")
                    return datetime.combine(parsed_day, datetime.min.time(), TZ).astimezone(UTC).isoformat().replace("+00:00", "Z")
            candidate = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC if assume_utc else TZ)
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
        if value is not None or not allow_day_boundary:
            raise ValueError("invalid_or_missing_timestamp")
        return datetime.combine(date.fromisoformat(fallback_day), datetime.min.time(), TZ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _local_day(timestamp_utc: str) -> str:
        return datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()

    @staticmethod
    def _numeric_fields(value: Any, path: str = "") -> Iterable[tuple[str, float]]:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"timestamp", "timestampgmt", "starttimestampgmt", "endtimestampgmt", "sleepstarttimestampgmt", "sleependtimestampgmt"}:
                    continue
                yield from HealthCollectionMixin._numeric_fields(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for child in value:
                yield from HealthCollectionMixin._numeric_fields(child, path)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            yield path or "value", float(value)

    def _upsert_daily_health(self, conn: sqlite3.Connection, subject: int, day: str, resource: str, payload: Any, revision: int) -> None:
        """Store only reviewed scalar daily facts, never an endpoint payload."""
        prior = conn.execute("SELECT values_json,extras_json,source_map_json FROM daily_health WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day)).fetchone()
        values = json.loads(prior["values_json"]) if prior else {}
        extras = json.loads(prior["extras_json"]) if prior else {}
        source_map = json.loads(prior["source_map_json"]) if prior else {}
        for metric in DAILY_SCALAR_METRICS.get(resource, {}).values():
            values.pop(metric[0], None)
            source_map.pop(metric[0], None)
        if isinstance(payload, dict):
            for source, metric in DAILY_SCALAR_METRICS.get(resource, {}).items():
                value = payload.get(source)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[metric[0]] = float(value)
                    source_map[metric[0]] = {
                        "source_revision_id": revision,
                        "source_path": metric[4],
                        "raw_unit": metric[1],
                        "canonical_unit": metric[2],
                        "value_origin": metric[3],
                    }
                    self.repo.map_field(conn, resource, metric[4], metric[0])
        conn.execute("UPDATE daily_health SET is_current=0 WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day))
        if values:
            conn.execute("INSERT INTO daily_health(subject_id,local_date,values_json,extras_json,source_map_json,source_revision_id,is_current) VALUES(?,?,?,?,?,?,1)", (subject, day, stable_json(values).decode("utf-8"), json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), revision))

    def _clear_daily_health_resource(self, conn: sqlite3.Connection, subject: int, day: str, resource: str) -> None:
        prior = conn.execute("SELECT values_json,extras_json,source_map_json,source_revision_id FROM daily_health WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day)).fetchone()
        if prior is None:
            return
        values, extras, source_map = (json.loads(prior[column]) for column in ("values_json", "extras_json", "source_map_json"))
        for metric in DAILY_SCALAR_METRICS.get(resource, {}).values():
            values.pop(metric[0], None)
            source_map.pop(metric[0], None)
        conn.execute("UPDATE daily_health SET is_current=0 WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day))
        if values:
            conn.execute("INSERT INTO daily_health(subject_id,local_date,values_json,extras_json,source_map_json,source_revision_id,is_current) VALUES(?,?,?,?,?,?,1)", (subject, day, json.dumps(values, sort_keys=True, allow_nan=False), json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), prior["source_revision_id"]))

    def _assert_sample_day(
        self,
        stamp: str,
        requested_day: str,
        *,
        allow_next_midnight: bool = False,
    ) -> None:
        observed = datetime.fromisoformat(
            stamp.replace("Z", "+00:00")
        ).astimezone(TZ)
        requested = date.fromisoformat(requested_day)
        if observed.date() == requested:
            return
        # Garmin's completed-day respiration stream is a closed interval: its
        # final observation is exactly 00:00 on the following local day.  Keep
        # that real timestamp, but do not relax the boundary for any other
        # resource or for a later time on the following day.
        if (
            allow_next_midnight
            and observed.date() == requested + timedelta(days=1)
            and observed.time() == datetime.min.time()
        ):
            return
        raise ValueError("timestamp_outside_requested_day")

    def _project_samples(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        """Project direct samples plus documented Garmin timestamp/value containers.

        The pinned client returns a mixture of record lists and nested arrays:
        for example ``bodyBatteryValuesArray`` is ``[[epoch_ms, level], ...]``.
        Treating the parent object as a single record loses every observed-at
        timestamp.  Recognised series are normalised first and excluded from the
        generic recursive pass; unknown fields remain in the archived raw JSON
        and source-field catalog rather than rejecting the whole resource.
        """
        series = CANONICAL_SERIES_METRICS.get(resource)
        direct_metrics = CANONICAL_SAMPLE_METRICS.get(resource, {})
        records = payload if isinstance(payload, list) else [payload]
        inserted = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            recognised: set[str] = set()
            if series is not None:
                field, canonical_key, raw_unit, origin, source_path = series
                values = record.get(field)
                if values is not None:
                    recognised.add(field)
                    if not isinstance(values, list):
                        raise ValueError("invalid_series_container")
                    for point_index, point in enumerate(values):
                        # The catalog declares timestamp/value tuples as exactly
                        # arity two. Extra tuple values are schema drift, not
                        # invented `*_2` canonical metrics.
                        if not isinstance(point, (list, tuple)) or len(point) != 2:
                            raise ValueError("invalid_series_tuple_arity")
                        stamp = self._timestamp_utc(point[0], day)
                        self._assert_sample_day(
                            stamp,
                            day,
                            allow_next_midnight=resource == "respiration",
                        )
                        if point[1] is None:
                            # Garmin uses null to represent a missing sensor
                            # interval.  The raw tuple remains immutable; no
                            # numeric sample is invented for this point.
                            continue
                        if not isinstance(point[1], (int, float)) or isinstance(point[1], bool):
                            raise ValueError("invalid_series_value")
                        conn.execute(
                            "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key,value_number,raw_value_json,raw_unit,canonical_unit,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)",
                            (subject, stamp, self._local_day(stamp), canonical_key, float(point[1]), json.dumps({"sample_index": index, "series_index": point_index}, sort_keys=True, allow_nan=False), raw_unit, raw_unit, revision),
                        )
                        self.repo.map_field(conn, resource, source_path, canonical_key)
                        inserted += 1
            # Do not recursively flatten recognised timestamp/value containers:
            # their timestamps were handled above.  Preserve any other provider
            # fields (including future drift) through the generic path.
            generic_record = {key: value for key, value in record.items() if key not in recognised}
            if direct_metrics:
                timestamp_fields = (
                    "timestamp",
                    "timestampGMT",
                    "startTimeGMT",
                    "startTimestampGMT",
                    "startGMT",
                )
                timestamp_key = next(
                    (
                        key
                        for key in timestamp_fields
                        if generic_record.get(key) is not None
                    ),
                    None,
                )
                timestamp = (
                    generic_record.get(timestamp_key)
                    if timestamp_key is not None
                    else None
                )
                if timestamp is None and resource == "rhr":
                    timestamp = generic_record.get("calendarDate")
                def direct_value(source: str) -> Any:
                    # Older Connect daily SpO₂ responses have a reviewed
                    # lowercase scalar spelling; the canonical key remains
                    # the same and the exact raw source path is catalogued.
                    if source == "spO2" and source not in generic_record:
                        return generic_record.get("spo2")
                    return generic_record.get(source)

                meaningful_direct = any(
                    isinstance(direct_value(source), (int, float))
                    and not isinstance(direct_value(source), bool)
                    for source in direct_metrics
                )
                if meaningful_direct and timestamp is not None:
                    stamp = self._timestamp_utc(
                        timestamp,
                        day,
                        allow_day_boundary=resource == "rhr",
                        assume_utc=bool(
                            timestamp_key
                            and (
                                "GMT" in timestamp_key
                                or timestamp_key.endswith("UTC")
                            )
                        ),
                    )
                    self._assert_sample_day(stamp, day)
                    for source, metric in direct_metrics.items():
                        value = direct_value(source)
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            continue
                        conn.execute(
                            "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key,value_number,raw_value_json,raw_unit,canonical_unit,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)",
                            (subject, stamp, self._local_day(stamp), metric[0], float(value), json.dumps({"sample_index": index}, sort_keys=True, allow_nan=False), metric[1], metric[2], revision),
                        )
                        source_path = "/spo2" if source == "spO2" and source not in generic_record else metric[4]
                        self.repo.map_field(conn, resource, source_path, metric[0])
                        inserted += 1
                elif meaningful_direct:
                    # A numeric sensor/measurement value cannot be represented
                    # as a fetched zero-record day.  Only explicitly reviewed
                    # daily aggregates are permitted to use day boundaries.
                    raise ValueError("missing_sample_timestamp")
        return inserted

    def _project_physiology(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> None:
        """Publish provider summary records without duplicating specialist streams.

        ``health_samples`` owns high-frequency timestamp/value arrays and
        ``body_measurements`` owns composition/BP observations.  This method
        stores one provenance record per meaningful provider record and only
        direct scalar summary fields as metrics.  It deliberately does not
        recursively flatten response containers: array indices are transport
        details, not stable physiological metric names.
        """
        excluded_containers = {
            "heartRateValues", "stressValuesArray", "respirationValuesArray",
            "spO2HourlyAverages", "bodyBatteryValuesArray",
            "dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries",
            "bloodPressureList", "bodyCompositionSummaries", "measurements",
        }
        measurement_wrappers = (
            "dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries",
            "bloodPressureList", "bodyCompositionSummaries", "measurements",
        )
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = [payload]
            # A BP response is a provider wrapper around individual readings.
            # Give each reading its own provenance timestamp instead of one
            # synthetic record for the enclosing range response.
            for wrapper in measurement_wrappers:
                if isinstance(payload.get(wrapper), list):
                    records = payload[wrapper]
                    break
        else:
            return
        timestamp_keys = {
            "timestamp", "timestampGMT", "startTimeGMT", "startTimestampGMT",
            "endTimeGMT", "endTimestampGMT", "calendarDate",
        }
        metric_specs = PHYSIOLOGY_SCALAR_METRICS.get(resource, {})
        for record in records:
            if not isinstance(record, dict):
                continue
            scalar_items = [
                (metric, value, metric_specs[metric])
                for metric, value in record.items()
                if metric not in timestamp_keys | excluded_containers
                and metric in metric_specs
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]
            # A record that consists solely of an already-projected stream has
            # no separate scalar summary fact to publish.
            if not scalar_items and (
                isinstance(payload, list)
                or resource in {"hrv"}
            ):
                continue
            daily_stamp = (
                record.get("calendarDate")
                or record.get("date")
                if resource in {
                    "body_battery",
                    "intensity_minutes",
                    "hrv",
                    "body_battery_events",
                }
                else None
            )
            timestamp_key = next(
                (
                    key
                    for key in (
                        "measurementTimestampGMT",
                        "timestamp",
                        "timestampGMT",
                        "startTimeGMT",
                        "startTimestampGMT",
                        "calendarDate",
                    )
                    if record.get(key) is not None
                ),
                None,
            )
            timestamp_value = daily_stamp or (
                record.get(timestamp_key) if timestamp_key else None
            )
            has_timestamp = timestamp_value is not None
            stamp = self._timestamp_utc(
                timestamp_value,
                day,
                allow_day_boundary=bool(daily_stamp) or resource in {
                    "intensity_minutes",
                    "all_day_events",
                    "lifestyle",
                    "body_battery_events",
                },
                assume_utc=bool(
                    not daily_stamp
                    and timestamp_key
                    and (
                        "GMT" in timestamp_key
                        or timestamp_key.endswith("UTC")
                    )
                ),
            )
            if has_timestamp:
                self._assert_sample_day(stamp, day)
            cursor = conn.execute(
                "INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)",
                (subject, "garmin", resource, stamp, self._local_day(stamp), "provider_derived", stable_json(record).decode("utf-8"), revision),
            )
            record_id = int(cursor.lastrowid)
            for metric, value, spec in scalar_items:
                conn.execute(
                    "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path) VALUES(?,?,?,?,?,?,?)",
                    (record_id, spec[0], float(value), spec[1], spec[2], spec[3], spec[4]),
                )
                self.repo.map_field(conn, resource, spec[4], spec[0])

    def _project_body_measurements(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> None:
        records = payload if isinstance(payload, list) else [payload]
        if isinstance(payload, dict):
            for key in ("dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries", "bloodPressureList", "bodyCompositionSummaries", "measurements"):
                if isinstance(payload.get(key), list):
                    records = payload[key]
                    break
        for item in records:
            if not isinstance(item, dict):
                continue
            timestamp_key = next(
                (
                    key
                    for key in (
                        "measurementTimestampGMT",
                        "timestamp",
                        "timestampGMT",
                        "gmtTimestamp",
                        "dateTimestamp",
                        "calendarDate",
                        "date",
                    )
                    if item.get(key) is not None
                ),
                None,
            )
            stamp = self._timestamp_utc(
                item.get(timestamp_key) if timestamp_key else None,
                day,
                allow_day_boundary=timestamp_key in {"calendarDate", "date"},
                assume_utc=bool(
                    timestamp_key
                    and (
                        "GMT" in timestamp_key
                        or timestamp_key == "gmtTimestamp"
                    )
                ),
            )
            self._assert_sample_day(stamp, day)
            conn.execute("INSERT INTO body_measurements(subject_id,observed_at_utc,local_date,values_json,extras_json,source_revision_id) VALUES(?,?,?,?,?,?)", (subject, stamp, self._local_day(stamp), stable_json(item).decode("utf-8"), "{}", revision))

    def _project_sleep(self, conn: sqlite3.Connection, subject: int, day: str, payload: Any, revision: int) -> int:
        if not isinstance(payload, dict):
            raise ValueError("sleep_payload_not_object")
        sessions = payload.get("sessions") or payload.get("sleepSessions") or []
        naps = payload.get("naps") or []
        if isinstance(naps, list):
            sessions = [*sessions, *[{**nap, "session_type": nap.get("session_type", "nap")} for nap in naps if isinstance(nap, dict)]]
        main = payload.get("dailySleepDTO")
        if isinstance(main, dict):
            main_start = (
                main.get("start_time_utc")
                or main.get("startTimeGMT")
                or main.get("sleepStartTimestampGMT")
            )
            main_end = (
                main.get("end_time_utc")
                or main.get("endTimeGMT")
                or main.get("sleepEndTimestampGMT")
            )
            # Connect returns a populated dailySleepDTO with both timestamps
            # null when no sleep session exists for that completed day.  This
            # is a valid fetched zero-record observation.  A one-sided session
            # remains invalid and is rejected below.
            if main_start is not None or main_end is not None:
                sessions = [main, *sessions]
        if not sessions and any(key in payload for key in ("sleepStartTimestampGMT", "startTimeGMT")):
            sessions = [payload]
        inserted = 0
        for session_index, item in enumerate(sessions):
            if not isinstance(item, dict):
                continue
            start = self._timestamp_utc(item.get("start_time_utc") or item.get("startTimeGMT") or item.get("sleepStartTimestampGMT"), day)
            end = self._timestamp_utc(item.get("end_time_utc") or item.get("endTimeGMT") or item.get("sleepEndTimestampGMT"), day)
            if end < start:
                raise ValueError("sleep_session_end_before_start")
            kind = item.get("session_type") or item.get("sleepType") or ("nap" if item.get("isNap") else "main_sleep")
            kind = kind if kind in {"main_sleep", "nap"} else "unknown"
            cursor = conn.execute("INSERT INTO sleep_sessions(subject_id,session_type,start_time_utc,end_time_utc,values_json,extras_json,source_map_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)", (subject, kind, start, end, stable_json(item).decode("utf-8"), "{}", json.dumps({"source_revision_id": revision}, allow_nan=False), revision))
            session_id = int(cursor.lastrowid)
            stages = item.get("stages") or item.get("sleepStages") or []
            # Garmin daily sleep payloads may expose stage changes as an epoch
            # map rather than an array.  Derive bounded intervals without
            # inventing values when the map is absent.
            if not stages and isinstance(item.get("sleepLevelsMap"), dict):
                points = sorted((self._timestamp_utc(mark, day), level) for mark, level in item["sleepLevelsMap"].items())
                stages = [
                    {"stage_type": str(level), "start_time_utc": begin, "end_time_utc": points[index + 1][0] if index + 1 < len(points) else end}
                    for index, (begin, level) in enumerate(points)
                ]
            for stage_index, stage in enumerate(stages):
                if not isinstance(stage, dict):
                    continue
                stage_start = self._timestamp_utc(stage.get("start_time_utc") or stage.get("startTimeGMT") or stage.get("startTimestampGMT"), day)
                stage_end = self._timestamp_utc(stage.get("end_time_utc") or stage.get("endTimeGMT") or stage.get("endTimestampGMT"), day)
                if stage_end < stage_start or stage_start < start or stage_end > end:
                    raise ValueError("sleep_stage_outside_session")
                duration = (datetime.fromisoformat(stage_end.replace("Z", "+00:00")) - datetime.fromisoformat(stage_start.replace("Z", "+00:00"))).total_seconds()
                conn.execute("INSERT INTO sleep_stages(sleep_session_id,stage_index,stage_type,start_time_utc,end_time_utc,duration_seconds,source_revision_id) VALUES(?,?,?,?,?,?,?)", (session_id, stage_index, str(stage.get("stage_type") or stage.get("stageType") or "unknown"), stage_start, stage_end, duration, revision))
            inserted += 1
        return inserted

    def _supersede_health_projection(self, conn: sqlite3.Connection, subject: int, resource: str, provider_id: str, day: str) -> None:
        """Remove only the old current projection inside the replacement transaction."""
        revisions = [
            int(row[0])
            for row in conn.execute(
                """SELECT id FROM source_revisions WHERE provider='garmin'
                   AND resource_kind=? AND provider_object_id=? AND is_current=1""",
                (resource, provider_id),
            )
        ]
        if revisions:
            placeholders = ",".join("?" for _ in revisions)
            conn.execute(
                f"DELETE FROM health_samples WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE subject_id=? AND source_revision_id IN ({placeholders}))",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM sleep_sessions WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM body_measurements WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"""DELETE FROM physiology_metrics WHERE physiology_record_id IN
                    (SELECT id FROM physiology_records WHERE subject_id=? AND source_revision_id IN ({placeholders}))""",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM physiology_records WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
        self._clear_daily_health_resource(conn, subject, day, resource)

    @staticmethod
    def _safe_advanced_payload(resource: str, payload: Any) -> Any:
        """Return the provider response byte-for-byte semantically intact.

        Raw objects are evidence, not a redacted derivative.  Credential-like
        fields are the sole exception: their presence is quarantined before any
        archive/write, because persisting a token would violate the secret
        boundary.  Canonical projection below remains allow-listed.
        """
        return validate_provider_json_payload(payload)

    @staticmethod
    def _advanced_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise ValueError("advanced_payload_not_object")
        for wrapper in ("trainingReadiness", "racePredictions", "calendarEntries", "foodLog", "meals", "items", "data"):
            value = payload.get(wrapper)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        return [payload]

    def _project_advanced(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        specs = ADVANCED_PHYSIOLOGY_METRICS[resource]
        if (
            resource == "lactate_threshold"
            and isinstance(payload, list)
            and any(
                isinstance(record, dict)
                and "__trainlab_lactate_family" in record
                for record in payload
            )
        ):
            inserted = 0
            lactate_specs = {
                "heart_rate": specs["lactateThresholdHeartRate"],
                "power": specs["lactateThresholdPower"],
                "speed": specs["lactateThresholdSpeed"],
            }
            for index, record in enumerate(payload):
                if not isinstance(record, dict):
                    continue
                family = record.get("__trainlab_lactate_family")
                spec = lactate_specs.get(family)
                value = record.get("value")
                if spec is None or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                stamp = self._timestamp_utc(
                    record.get("updatedDate"), day, allow_day_boundary=True,
                )
                self._assert_sample_day(stamp, day)
                cursor = conn.execute(
                    """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (subject, "garmin", resource, f"{family}:{index}", stamp,
                     self._local_day(stamp), "provider_derived", "{}", revision),
                )
                source_path = f"/{family}/*/value"
                conn.execute(
                    """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path)
                       VALUES(?,?,?,?,?,?,?)""",
                    (int(cursor.lastrowid), spec[0], float(value), spec[1], spec[2], spec[3], source_path),
                )
                self.repo.map_field(conn, resource, source_path, spec[0])
                inserted += 1
            return inserted
        records = self._advanced_records(payload)
        prefix = "/*/" if isinstance(payload, list) else "/"
        if isinstance(payload, dict):
            for wrapper in ("trainingReadiness", "racePredictions", "calendarEntries", "foodLog", "meals", "items", "data"):
                if isinstance(payload.get(wrapper), list):
                    prefix = f"/{wrapper}/*/"
                    break
                if isinstance(payload.get(wrapper), dict):
                    prefix = f"/{wrapper}/"
                    break
        inserted = 0
        for index, record in enumerate(records):
            scalars = [(field, value, specs[field]) for field, value in record.items() if field in specs and isinstance(value, (int, float)) and not isinstance(value, bool)]
            # These are provider daily/range summaries.  Their calendar date is
            # authoritative for the observation day; timestamps may describe
            # a contributing sleep/recovery interval crossing midnight.
            timestamp_value = next(
                (
                    record.get(field)
                    for field in (
                        "calendarDate",
                        "date",
                        "timestamp",
                        "timestampGMT",
                        "startTimeGMT",
                        "startTimestampGMT",
                    )
                    if record.get(field) is not None
                ),
                None,
            )
            # These endpoints are daily/range provider summaries. A missing
            # timestamp means the requested Singapore day boundary, never an
            # invented high-frequency sample time.
            stamp = self._timestamp_utc(timestamp_value, day, allow_day_boundary=True)
            self._assert_sample_day(stamp, day)
            cursor = conn.execute(
                """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (subject, "garmin", resource, str(index), stamp, self._local_day(stamp), "provider_predicted" if resource == "race_predictions" else "provider_derived", "{}", revision),
            )
            record_id = int(cursor.lastrowid)
            for field, value, spec in scalars:
                source_path = prefix + field
                conn.execute(
                    """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path)
                       VALUES(?,?,?,?,?,?,?)""",
                    (record_id, spec[0], float(value), spec[1], spec[2], spec[3], source_path),
                )
                self.repo.map_field(conn, resource, source_path, spec[0])
            inserted += 1
        known_empty_wrapper = isinstance(payload, dict) and any(
            wrapper in payload
            for wrapper in (
                "trainingReadiness",
                "racePredictions",
                "calendarEntries",
                "foodLog",
                "meals",
                "items",
                "data",
            )
        )
        if payload not in ({}, [], None) and not records and not known_empty_wrapper:
            raise ValueError("advanced_payload_shape")
        return inserted

    def _project_health(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        """Project one reviewed base resource inside the publisher transaction.

        Raw JSON and source-field discovery happen before this method.  A
        parse or projection exception therefore rolls back only this revision's
        canonical rows while retaining the raw object for repair.
        """
        if resource in ADVANCED_RESOURCES:
            return self._project_advanced(conn, subject, resource, day, payload, revision)
        daily_resources = {
            "user_summary", "steps", "floors", "heart_rates", "rhr", "hydration",
            "respiration", "spo2", "intensity_minutes", "stress",
        }
        sampled_resources = {
            "steps", "floors", "heart_rates", "rhr", "respiration", "spo2", "stress", "hrv", "body_battery",
        }
        physiology_resources = {
            "intensity_minutes", "all_day_events", "lifestyle", "hrv", "body_battery",
            "body_battery_events", "blood_pressure",
        }
        body_resources = {"body_composition", "weigh_ins", "blood_pressure"}
        projected = 0
        if resource in daily_resources:
            self._upsert_daily_health(conn, subject, day, resource, payload, revision)
            if any(
                isinstance(payload.get(source), (int, float)) and not isinstance(payload.get(source), bool)
                for source in DAILY_SCALAR_METRICS.get(resource, {})
            ) if isinstance(payload, dict) else False:
                projected += 1
        if resource in sampled_resources:
            projected += self._project_samples(conn, subject, resource, day, payload, revision)
        if resource == "sleep":
            projected += self._project_sleep(conn, subject, day, payload, revision)
        if resource in body_resources:
            self._project_body_measurements(conn, subject, resource, day, payload, revision)
            projected += 1
        if resource in physiology_resources or resource not in daily_resources | sampled_resources | body_resources | {"sleep"}:
            self._project_physiology(conn, subject, resource, day, payload, revision)
            projected += 1
        return projected
