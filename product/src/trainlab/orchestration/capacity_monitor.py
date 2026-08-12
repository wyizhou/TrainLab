"""Bounded, metadata-only capacity observations.

This module deliberately uses only ``statvfs``, directory entry metadata, and
``stat``.  It never opens a FIT, JSON, SQLite, log, temporary, backup, or
credential file.  The returned observations contain fixed identifiers and
numeric sizes only, so they are suitable for data-free operational receipts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CapacityStatus = Literal["ready", "warning", "critical", "unavailable"]

_MEBIBYTE = 1024 * 1024
_GIBIBYTE = 1024 * _MEBIBYTE
_DIRECTORY_TARGETS = ("raw", "logs", "temp")


class CapacityMonitorError(ValueError):
    """Raised when a capacity configuration is not bounded or is invalid."""


@dataclass(frozen=True, slots=True)
class CapacityThresholds:
    """Fixed, reviewable thresholds for metadata-only observations."""

    disk_warning_percent: int = 80
    disk_critical_percent: int = 90
    sqlite_warning_bytes: int = 512 * _MEBIBYTE
    sqlite_critical_bytes: int = 2 * _GIBIBYTE
    wal_warning_bytes: int = 128 * _MEBIBYTE
    wal_critical_bytes: int = 512 * _MEBIBYTE
    directory_warning_bytes: int = 2 * _GIBIBYTE
    directory_critical_bytes: int = 8 * _GIBIBYTE
    max_directory_entries: int = 128

    def __post_init__(self) -> None:
        if not 0 < self.disk_warning_percent < self.disk_critical_percent <= 100:
            raise CapacityMonitorError("capacity_disk_thresholds_invalid")
        pairs = (
            (self.sqlite_warning_bytes, self.sqlite_critical_bytes),
            (self.wal_warning_bytes, self.wal_critical_bytes),
            (self.directory_warning_bytes, self.directory_critical_bytes),
        )
        if any(warning < 0 or warning >= critical for warning, critical in pairs):
            raise CapacityMonitorError("capacity_byte_thresholds_invalid")
        if not 1 <= self.max_directory_entries <= 1024:
            raise CapacityMonitorError("capacity_directory_scan_limit_invalid")


@dataclass(frozen=True, slots=True)
class CapacityPaths:
    """Local targets; paths are inputs only and never appear in observations."""

    filesystem_root: Path
    sqlite_database: Path
    raw_directory: Path
    log_directory: Path
    temp_directory: Path


@dataclass(frozen=True, slots=True)
class CapacityObservation:
    """A data-free result for one fixed capacity target."""

    target: str
    status: CapacityStatus
    code: str
    bytes_observed: int | None
    threshold_bytes: int | None
    utilization_percent: int | None = None
    entries_scanned: int | None = None
    scan_complete: bool | None = None

    def __post_init__(self) -> None:
        if self.target not in {"disk", "sqlite", "wal", *_DIRECTORY_TARGETS}:
            raise CapacityMonitorError("capacity_target_invalid")
        if self.status not in {"ready", "warning", "critical", "unavailable"}:
            raise CapacityMonitorError("capacity_status_invalid")
        if not self.code.startswith(f"capacity_{self.target}_"):
            raise CapacityMonitorError("capacity_code_invalid")
        if self.bytes_observed is not None and self.bytes_observed < 0:
            raise CapacityMonitorError("capacity_bytes_invalid")
        if self.threshold_bytes is not None and self.threshold_bytes < 0:
            raise CapacityMonitorError("capacity_threshold_invalid")
        if (
            self.utilization_percent is not None
            and not 0 <= self.utilization_percent <= 100
        ):
            raise CapacityMonitorError("capacity_utilization_invalid")
        if self.entries_scanned is not None and self.entries_scanned < 0:
            raise CapacityMonitorError("capacity_entries_invalid")


@dataclass(frozen=True, slots=True)
class CapacityReport:
    """A bounded collection of fixed, data-free target observations."""

    observations: tuple[CapacityObservation, ...]

    @property
    def status(self) -> CapacityStatus:
        statuses = {observation.status for observation in self.observations}
        if "critical" in statuses:
            return "critical"
        if "unavailable" in statuses:
            return "unavailable"
        if "warning" in statuses:
            return "warning"
        return "ready"


class CapacityMonitor:
    """Read a fixed set of filesystem metadata with a hard directory bound."""

    def __init__(self, thresholds: CapacityThresholds | None = None) -> None:
        self._thresholds = thresholds or CapacityThresholds()

    def observe(self, paths: CapacityPaths) -> CapacityReport:
        """Return fixed observations without opening, deleting, or rotating data."""
        database = paths.sqlite_database
        return CapacityReport(
            observations=(
                self._disk(paths.filesystem_root),
                self._file(
                    "sqlite",
                    database,
                    self._thresholds.sqlite_warning_bytes,
                    self._thresholds.sqlite_critical_bytes,
                ),
                self._file(
                    "wal",
                    database.with_name(f"{database.name}-wal"),
                    self._thresholds.wal_warning_bytes,
                    self._thresholds.wal_critical_bytes,
                ),
                self._directory("raw", paths.raw_directory),
                self._directory("logs", paths.log_directory),
                self._directory("temp", paths.temp_directory),
            )
        )

    def _disk(self, root: Path) -> CapacityObservation:
        try:
            stats = os.statvfs(root)
            capacity = stats.f_frsize * stats.f_blocks
            available = stats.f_frsize * stats.f_bavail
        except OSError:
            return CapacityObservation(
                "disk", "unavailable", "capacity_disk_metadata_unavailable", None, None
            )
        if capacity <= 0 or available < 0 or available > capacity:
            return CapacityObservation(
                "disk", "unavailable", "capacity_disk_metadata_unavailable", None, None
            )
        used = capacity - available
        used_percent = used * 100 // capacity
        status, code = _percent_status(
            "disk",
            used_percent,
            self._thresholds.disk_warning_percent,
            self._thresholds.disk_critical_percent,
        )
        return CapacityObservation(
            "disk", status, code, used, capacity, utilization_percent=used_percent
        )

    def _file(
        self, target: Literal["sqlite", "wal"], path: Path, warning: int, critical: int
    ) -> CapacityObservation:
        try:
            size = path.stat().st_size
        except OSError:
            return CapacityObservation(
                target,
                "unavailable",
                f"capacity_{target}_metadata_unavailable",
                None,
                None,
            )
        status, code = _byte_status(target, size, warning, critical)
        return CapacityObservation(target, status, code, size, warning)

    def _directory(
        self, target: Literal["raw", "logs", "temp"], path: Path
    ) -> CapacityObservation:
        try:
            with os.scandir(path) as entries:
                total = 0
                scanned = 0
                complete = True
                for entry in entries:
                    if scanned == self._thresholds.max_directory_entries:
                        complete = False
                        break
                    scanned += 1
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            return CapacityObservation(
                target,
                "unavailable",
                f"capacity_{target}_metadata_unavailable",
                None,
                None,
            )
        if not complete:
            return CapacityObservation(
                target,
                "warning",
                f"capacity_{target}_scan_limit_reached",
                total,
                self._thresholds.directory_warning_bytes,
                entries_scanned=scanned,
                scan_complete=False,
            )
        status, code = _byte_status(
            target,
            total,
            self._thresholds.directory_warning_bytes,
            self._thresholds.directory_critical_bytes,
        )
        return CapacityObservation(
            target,
            status,
            code,
            total,
            self._thresholds.directory_warning_bytes,
            entries_scanned=scanned,
            scan_complete=True,
        )


def _byte_status(
    target: str, value: int, warning: int, critical: int
) -> tuple[CapacityStatus, str]:
    if value >= critical:
        return "critical", f"capacity_{target}_critical"
    if value >= warning:
        return "warning", f"capacity_{target}_warning"
    return "ready", f"capacity_{target}_healthy"


def _percent_status(
    target: str, value: int, warning: int, critical: int
) -> tuple[CapacityStatus, str]:
    if value >= critical:
        return "critical", f"capacity_{target}_critical"
    if value >= warning:
        return "warning", f"capacity_{target}_warning"
    return "ready", f"capacity_{target}_healthy"
