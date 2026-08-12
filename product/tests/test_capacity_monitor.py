from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from trainlab.orchestration.capacity_monitor import (
    CapacityMonitor,
    CapacityMonitorError,
    CapacityPaths,
    CapacityThresholds,
)


def _paths(tmp_path: Path) -> CapacityPaths:
    sqlite = tmp_path / "data.db"
    sqlite.write_bytes(b"db")
    raw = tmp_path / "raw"
    logs = tmp_path / "logs"
    temp = tmp_path / "temp"
    for directory in (raw, logs, temp):
        directory.mkdir()
    return CapacityPaths(tmp_path, sqlite, raw, logs, temp)


def _monitor() -> CapacityMonitor:
    return CapacityMonitor(
        CapacityThresholds(
            disk_warning_percent=80,
            disk_critical_percent=90,
            sqlite_warning_bytes=10,
            sqlite_critical_bytes=20,
            wal_warning_bytes=10,
            wal_critical_bytes=20,
            directory_warning_bytes=10,
            directory_critical_bytes=20,
            max_directory_entries=2,
        )
    )


def _by_target(paths: CapacityPaths, target: str):
    return next(
        item for item in _monitor().observe(paths).observations if item.target == target
    )


def test_well_below_threshold_is_healthy(tmp_path: Path) -> None:
    observation = _by_target(_paths(tmp_path), "sqlite")
    assert (observation.status, observation.code) == (
        "ready",
        "capacity_sqlite_healthy",
    )


def test_just_below_threshold_is_healthy(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.sqlite_database.write_bytes(b"x" * 9)
    observation = _by_target(paths, "sqlite")
    assert observation.status == "ready"


def test_exact_threshold_is_warning(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.sqlite_database.write_bytes(b"x" * 10)
    observation = _by_target(paths, "sqlite")
    assert (observation.status, observation.code) == (
        "warning",
        "capacity_sqlite_warning",
    )


def test_disk_exact_threshold_is_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        "trainlab.orchestration.capacity_monitor.os.statvfs",
        lambda _root: SimpleNamespace(f_frsize=1, f_blocks=100, f_bavail=20),
    )
    observation = _by_target(paths, "disk")
    assert (observation.status, observation.code, observation.utilization_percent) == (
        "warning",
        "capacity_disk_warning",
        80,
    )


def test_just_above_warning_threshold_is_warning(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.sqlite_database.write_bytes(b"x" * 11)
    observation = _by_target(paths, "sqlite")
    assert observation.status == "warning"


def test_unavailable_metadata_is_not_success(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.sqlite_database.unlink()
    observation = _by_target(paths, "sqlite")
    assert (observation.status, observation.code, observation.bytes_observed) == (
        "unavailable",
        "capacity_sqlite_metadata_unavailable",
        None,
    )


def test_unavailable_disk_metadata_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        "trainlab.orchestration.capacity_monitor.os.statvfs",
        lambda _root: (_ for _ in ()).throw(OSError("unavailable")),
    )
    observation = _by_target(paths, "disk")
    assert (observation.status, observation.code) == (
        "unavailable",
        "capacity_disk_metadata_unavailable",
    )


def test_wal_growth_is_thresholded_without_reading_database(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.sqlite_database.with_name("data.db-wal").write_bytes(b"x" * 20)
    observation = _by_target(paths, "wal")
    assert (observation.status, observation.code, observation.bytes_observed) == (
        "critical",
        "capacity_wal_critical",
        20,
    )


def test_log_and_temp_growth_are_thresholded(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (paths.log_directory / "one.log").write_bytes(b"x" * 10)
    (paths.temp_directory / "one.tmp").write_bytes(b"x" * 20)
    log = _by_target(paths, "logs")
    temp = _by_target(paths, "temp")
    assert (log.status, log.code, log.scan_complete) == (
        "warning",
        "capacity_logs_warning",
        True,
    )
    assert (temp.status, temp.code, temp.scan_complete) == (
        "critical",
        "capacity_temp_critical",
        True,
    )


def test_directory_scan_is_bounded_and_never_lists_names(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    for index in range(3):
        (paths.raw_directory / f"private-{index}.fit").write_bytes(b"x")
    observation = _by_target(paths, "raw")
    assert (
        observation.status,
        observation.code,
        observation.entries_scanned,
        observation.scan_complete,
    ) == (
        "warning",
        "capacity_raw_scan_limit_reached",
        2,
        False,
    )
    assert "private" not in repr(observation)


def test_observations_never_contain_configured_paths_or_file_content(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    secret_name = "private-athlete-data.fit"
    (paths.raw_directory / secret_name).write_bytes(b"not-an-observation-payload")
    report = _monitor().observe(paths)
    serialized = repr(report)
    assert str(paths.raw_directory) not in serialized
    assert secret_name not in serialized
    assert "not-an-observation-payload" not in serialized


def test_invalid_thresholds_are_rejected() -> None:
    with pytest.raises(CapacityMonitorError, match="capacity_disk_thresholds_invalid"):
        CapacityThresholds(disk_warning_percent=90, disk_critical_percent=90)
