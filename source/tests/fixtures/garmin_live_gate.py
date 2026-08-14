"""Deterministic, data-free safety gate for offline Garmin acceptance tests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_REVIEWED_RESOURCES = frozenset({"heart_rates", "spo2", "steps"})
_MAX_PROVIDER_ENTRIES = 8
_MAX_WALL_SECONDS = 30.0


class LiveGateError(RuntimeError):
    """A closed gate with a stable, non-sensitive failure code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LiveGateBudget:
    """All externally relevant bounds required before provider entry."""

    from_local_date: str | None
    through_local_date: str | None
    resource_kinds: tuple[str, ...]
    max_provider_entries: int
    max_wall_seconds: float
    max_activity_count: int
    max_fit_download_count: int
    max_raw_object_count: int
    minimum_provider_interval_seconds: float = 0.0

    def validate(self) -> None:
        start = _local_date(self.from_local_date, "start_date_missing")
        through = _local_date(self.through_local_date, "through_date_missing")
        if start > through:
            raise LiveGateError("date_range_reversed")
        if (through - start).days > 0:
            raise LiveGateError("date_window_exceeded")
        if (
            not self.resource_kinds
            or tuple(sorted(set(self.resource_kinds))) != self.resource_kinds
            or not set(self.resource_kinds).issubset(_REVIEWED_RESOURCES)
        ):
            raise LiveGateError("resource_allowlist_invalid")
        if not _bounded_int(
            self.max_provider_entries, minimum=1, maximum=_MAX_PROVIDER_ENTRIES
        ):
            raise LiveGateError("provider_budget_invalid")
        if not _bounded_number(
            self.max_wall_seconds, minimum=0.001, maximum=_MAX_WALL_SECONDS
        ):
            raise LiveGateError("wall_budget_invalid")
        if self.max_activity_count != 0 or self.max_fit_download_count != 0:
            raise LiveGateError("download_budget_invalid")
        if not _bounded_int(
            self.max_raw_object_count,
            minimum=0,
            maximum=self.max_provider_entries,
        ):
            raise LiveGateError("raw_budget_invalid")
        if not _bounded_number(
            self.minimum_provider_interval_seconds,
            minimum=0.0,
            maximum=5.0,
        ):
            raise LiveGateError("interval_budget_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "from_local_date": self.from_local_date,
            "through_local_date": self.through_local_date,
            "resource_kinds": list(self.resource_kinds),
            "max_provider_entries": self.max_provider_entries,
            "max_wall_seconds": self.max_wall_seconds,
            "max_activity_count": self.max_activity_count,
            "max_fit_download_count": self.max_fit_download_count,
            "max_raw_object_count": self.max_raw_object_count,
            "minimum_provider_interval_seconds": (
                self.minimum_provider_interval_seconds
            ),
        }


class LiveProviderGate:
    """Allow only the frozen offline call sequence and enforce every budget."""

    def __init__(
        self,
        budget: LiveGateBudget,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._budget = budget
        self._monotonic = monotonic
        self._sleep = sleep
        self._started = monotonic()
        self._active = False
        self._last_entry: float | None = None
        self.ledger: list[dict[str, int | str]] = []
        self.counts = {
            "refresh_provider_entry_count": 0,
            "social_profile_http_count": 0,
            "user_settings_http_count": 0,
            "data_provider_entry_count": 0,
            "blocked_provider_attempt_count": 0,
        }

    def invoke(self, operation: str, callback: Callable[[], Any]) -> Any:
        if not self._active:
            self._blocked("provider_gate_inactive")
        if not callable(callback):
            self._blocked("provider_callback_invalid")
        count_key = self._authorize(operation)
        now = self._monotonic()
        if now - self._started > self._budget.max_wall_seconds:
            self._blocked("wall_budget_exceeded")
        if len(self.ledger) >= self._budget.max_provider_entries:
            self._blocked("provider_budget_exceeded")
        if self._last_entry is not None:
            minimum = self._budget.minimum_provider_interval_seconds
            while now - self._last_entry < minimum:
                self._sleep(minimum - (now - self._last_entry))
                now = self._monotonic()
                if now - self._started > self._budget.max_wall_seconds:
                    self._blocked("wall_budget_exceeded")
        self._last_entry = now
        self.counts[count_key] += 1
        self.ledger.append(
            {
                "ordinal": len(self.ledger) + 1,
                "operation": operation,
                "monotonic_ns": int(now * 1_000_000_000),
            }
        )
        return callback()

    def _authorize(self, operation: str) -> str:
        if operation == "auth_refresh":
            if self.counts["refresh_provider_entry_count"]:
                self._blocked("auth_refresh_repeated")
            return "refresh_provider_entry_count"
        if operation == "social_profile":
            if self.counts["refresh_provider_entry_count"] != 1:
                self._blocked("social_profile_before_refresh")
            if self.counts["social_profile_http_count"]:
                self._blocked("social_profile_repeated")
            return "social_profile_http_count"
        if operation == "user_settings":
            if self.counts["social_profile_http_count"] != 1:
                self._blocked("user_settings_before_profile")
            if self.counts["user_settings_http_count"]:
                self._blocked("user_settings_repeated")
            return "user_settings_http_count"
        prefix = "resource:"
        if not operation.startswith(prefix):
            self._blocked("provider_operation_unreviewed")
        resource = operation.removeprefix(prefix)
        if resource not in self._budget.resource_kinds:
            self._blocked("provider_resource_unreviewed")
        if self.counts["user_settings_http_count"] != 1:
            self._blocked("data_before_auth_gate")
        return "data_provider_entry_count"

    def _blocked(self, code: str) -> None:
        self.counts["blocked_provider_attempt_count"] += 1
        raise LiveGateError(code)


class GarminLiveGate:
    """One-shot offline harness that persists only bounded redacted evidence."""

    def __init__(
        self,
        marker_root: Path,
        budget: LiveGateBudget,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.marker_root = marker_root
        self.budget = budget
        self.monotonic = monotonic
        self.sleep = sleep
        self.receipt_path = marker_root / "receipt.json"
        self.lock_path = marker_root / "execution.lock"
        self._verify_root()

    def execute_once(
        self, operation: Callable[[LiveProviderGate], Mapping[str, Any]]
    ) -> dict[str, Any]:
        lock = self._acquire_lock()
        provider = LiveProviderGate(
            self.budget, monotonic=self.monotonic, sleep=self.sleep
        )
        try:
            try:
                self.budget.validate()
            except LiveGateError as exc:
                receipt = self._receipt(
                    status="stopped",
                    failure_code=f"preflight_{exc.code}",
                    provider=provider,
                    run_result=None,
                )
                self._persist_or_close(receipt)
                raise
            provider._active = True
            try:
                raw_result = operation(provider)
                if provider.counts["blocked_provider_attempt_count"]:
                    raise LiveGateError("provider_gate_violation")
                run_result = _normalize_run_result(raw_result)
            except LiveGateError as exc:
                receipt = self._receipt(
                    status="stopped",
                    failure_code=exc.code,
                    provider=provider,
                    run_result=None,
                )
                self._persist_or_close(receipt)
                raise
            except Exception as exc:
                receipt = self._receipt(
                    status="stopped",
                    failure_code="execution_failed",
                    provider=provider,
                    run_result=None,
                )
                self._persist_or_close(receipt)
                raise LiveGateError("execution_failed") from exc
            finally:
                provider._active = False
            receipt = self._receipt(
                status="succeeded",
                failure_code=None,
                provider=provider,
                run_result=run_result,
            )
            self._persist_or_close(receipt)
            return receipt
        finally:
            os.close(lock)

    def _verify_root(self) -> None:
        facts = os.lstat(self.marker_root)
        if stat.S_ISLNK(facts.st_mode) or not stat.S_ISDIR(facts.st_mode):
            raise LiveGateError("marker_root_invalid")
        if stat.S_IMODE(facts.st_mode) != 0o700:
            raise LiveGateError("marker_root_mode_invalid")

    def _acquire_lock(self) -> int:
        directory = os.open(
            self.marker_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            return os.open(
                self.lock_path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
        except FileExistsError as exc:
            raise LiveGateError("execution_lock_busy") from exc
        finally:
            os.close(directory)

    def _receipt(
        self,
        *,
        status: str,
        failure_code: str | None,
        provider: LiveProviderGate,
        run_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": "1",
            "document_kind": "garmin_live_gate_receipt",
            "timezone": "Asia/Hong_Kong",
            "status": status,
            "failure_code": failure_code,
            "budget": self.budget.as_dict(),
            "observed": {
                "provider_entry_count": len(provider.ledger),
                "credential_content_read_count": 0,
                "credential_write_count": 0,
                "production_authority_write_count": 0,
            },
            "operation_counts": dict(provider.counts),
            "provider_entry_ledger": list(provider.ledger),
            "run_result": run_result,
            "receipt_sha256": "0" * 64,
        }
        receipt["receipt_sha256"] = receipt_sha256(receipt)
        return receipt

    def _persist_or_close(self, receipt: Mapping[str, Any]) -> None:
        try:
            self._persist(receipt)
        except Exception as exc:
            raise LiveGateError("receipt_persist_failed") from exc

    def _persist(self, receipt: Mapping[str, Any]) -> None:
        validate_receipt(receipt)
        if self.receipt_path.exists() or self.receipt_path.is_symlink():
            raise LiveGateError("receipt_destination_exists")
        payload = (
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        directory = os.open(
            self.marker_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        temporary = f".{self.receipt_path.name}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("receipt_short_write")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary,
                self.receipt_path.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            os.fsync(directory)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)


def require_sync_receipt(tool: Any, receipt: Any) -> Any:
    """Use the product's current receipt validator before gate checkpointing."""
    validator = getattr(tool, "_validated_receipt", None)
    if not callable(validator):
        raise LiveGateError("sync_receipt_validator_missing")
    try:
        validated = validator(receipt)
    except Exception as exc:
        raise LiveGateError("sync_receipt_invalid") from exc
    if validated is not receipt:
        raise LiveGateError("sync_receipt_identity")
    return receipt


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "document_kind",
        "timezone",
        "status",
        "failure_code",
        "budget",
        "observed",
        "operation_counts",
        "provider_entry_ledger",
        "run_result",
        "receipt_sha256",
    }
    if set(receipt) != required:
        raise LiveGateError("receipt_shape_invalid")
    if (
        receipt["schema_version"] != "1"
        or receipt["document_kind"] != "garmin_live_gate_receipt"
        or receipt["timezone"] != "Asia/Hong_Kong"
        or receipt["status"] not in {"succeeded", "stopped"}
    ):
        raise LiveGateError("receipt_header_invalid")
    budget = _budget_from_mapping(receipt["budget"])
    preflight_stop = (
        receipt["status"] == "stopped"
        and isinstance(receipt["failure_code"], str)
        and receipt["failure_code"].startswith("preflight_")
    )
    if not preflight_stop:
        budget.validate()
    observed = receipt["observed"]
    if not isinstance(observed, Mapping) or set(observed) != {
        "provider_entry_count",
        "credential_content_read_count",
        "credential_write_count",
        "production_authority_write_count",
    }:
        raise LiveGateError("receipt_observed_invalid")
    if any(
        observed[name] != 0
        for name in (
            "credential_content_read_count",
            "credential_write_count",
            "production_authority_write_count",
        )
    ):
        raise LiveGateError("receipt_private_boundary_invalid")
    ledger = receipt["provider_entry_ledger"]
    counts = receipt["operation_counts"]
    if not isinstance(ledger, list) or not isinstance(counts, Mapping):
        raise LiveGateError("receipt_provider_evidence_invalid")
    if set(counts) != {
        "refresh_provider_entry_count",
        "social_profile_http_count",
        "user_settings_http_count",
        "data_provider_entry_count",
        "blocked_provider_attempt_count",
    }:
        raise LiveGateError("receipt_provider_counts_invalid")
    if any(
        not _bounded_int(value, minimum=0, maximum=_MAX_PROVIDER_ENTRIES)
        for value in counts.values()
    ):
        raise LiveGateError("receipt_provider_counts_invalid")
    if any(
        not isinstance(entry, Mapping)
        or set(entry) != {"ordinal", "operation", "monotonic_ns"}
        or not isinstance(entry["operation"], str)
        or not _bounded_int(entry["monotonic_ns"], minimum=0, maximum=10**18)
        for entry in ledger
    ):
        raise LiveGateError("receipt_provider_ledger_invalid")
    entered = sum(
        counts[name] for name in counts if name != "blocked_provider_attempt_count"
    )
    if (
        observed["provider_entry_count"] != len(ledger)
        or entered != len(ledger)
        or len(ledger) > budget.max_provider_entries
        or [entry.get("ordinal") for entry in ledger] != list(range(1, len(ledger) + 1))
    ):
        raise LiveGateError("receipt_provider_count_invalid")
    intervals = [
        (ledger[index]["monotonic_ns"] - ledger[index - 1]["monotonic_ns"])
        / 1_000_000_000
        for index in range(1, len(ledger))
    ]
    if any(value < budget.minimum_provider_interval_seconds for value in intervals):
        raise LiveGateError("receipt_provider_interval_invalid")
    status = receipt["status"]
    if (status == "succeeded") != (receipt["failure_code"] is None):
        raise LiveGateError("receipt_outcome_invalid")
    if status == "succeeded":
        _normalize_run_result(receipt["run_result"])
    elif receipt["run_result"] is not None:
        raise LiveGateError("receipt_stop_result_invalid")
    if receipt["receipt_sha256"] != receipt_sha256(receipt):
        raise LiveGateError("receipt_digest_invalid")


def _budget_from_mapping(value: Any) -> LiveGateBudget:
    if not isinstance(value, Mapping):
        raise LiveGateError("receipt_budget_invalid")
    expected = {
        "from_local_date",
        "through_local_date",
        "resource_kinds",
        "max_provider_entries",
        "max_wall_seconds",
        "max_activity_count",
        "max_fit_download_count",
        "max_raw_object_count",
        "minimum_provider_interval_seconds",
    }
    if set(value) != expected or not isinstance(value["resource_kinds"], list):
        raise LiveGateError("receipt_budget_invalid")
    return LiveGateBudget(
        from_local_date=value["from_local_date"],
        through_local_date=value["through_local_date"],
        resource_kinds=tuple(value["resource_kinds"]),
        max_provider_entries=value["max_provider_entries"],
        max_wall_seconds=value["max_wall_seconds"],
        max_activity_count=value["max_activity_count"],
        max_fit_download_count=value["max_fit_download_count"],
        max_raw_object_count=value["max_raw_object_count"],
        minimum_provider_interval_seconds=value["minimum_provider_interval_seconds"],
    )


def _normalize_run_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"status", "counts"}:
        raise LiveGateError("run_result_invalid")
    if value["status"] not in {"succeeded", "unchanged"}:
        raise LiveGateError("run_result_status_invalid")
    counts = value["counts"]
    if (
        not isinstance(counts, Mapping)
        or not counts
        or any(
            not _bounded_int(count, minimum=0, maximum=1_000_000)
            for count in counts.values()
        )
    ):
        raise LiveGateError("run_result_counts_invalid")
    return {"status": value["status"], "counts": dict(sorted(counts.items()))}


def _local_date(value: str | None, missing_code: str) -> date:
    if value is None:
        raise LiveGateError(missing_code)
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LiveGateError("local_date_invalid") from exc


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _bounded_number(value: Any, *, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )
