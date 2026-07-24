from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from trainlab.orchestration import AtomicConfigStore, ControlledClock, OrchestrationConfigError, OrchestrationConfigLoader, SchedulingProjectionService


def payload(**overrides: object) -> dict:
    values: dict[str, object] = {
        "timezone": "Asia/Singapore", "morning_time": "07:00", "weekly_day": "sunday",
        "mail_poll_interval_seconds": 300, "health_check_interval_seconds": 60,
        "workflow_deadline_seconds": 3600, "max_parallel_read_checks": 4,
        "lease_ttl_seconds": 90, "heartbeat_interval_seconds": 30,
        "daily_misfire_window_hours": 12, "weekly_misfire_window_hours": 24,
        "state_lock_path": "state/locks/supervisor.lock", "temp_root": "state/tmp/orchestrator",
        "log_root": "logs", "operational_alerts_enabled": True,
    }
    values.update(overrides)
    return {"orchestrator": values}


def config_file(tmp_path: Path, content: dict | None = None) -> tuple[Path, Path]:
    root = tmp_path / "project"; directory = root / "config"; directory.mkdir(parents=True)
    root.chmod(0o700); directory.chmod(0o700)
    path = directory / "orchestrator.yaml"; path.write_text(yaml.safe_dump(content or payload())); path.chmod(0o600)
    return root, path


def load(tmp_path: Path, content: dict | None = None):
    root, path = config_file(tmp_path, content)
    return OrchestrationConfigLoader(root), path


def test_owner_only_static_config_hash_and_no_command_surface(tmp_path: Path) -> None:
    loader, path = load(tmp_path)
    first = loader.load(path); second = loader.load(path)
    assert first.config_sha256 == second.config_sha256 and len(first.config_sha256) == 64
    assert first.timezone == "Asia/Singapore" and first.morning_time == "07:00" and first.weekly_day == "sunday"
    for forbidden in ("command", "argv", "recipient", "model", "cron", "secret_token"):
        bad = payload(**{forbidden: "unsafe"})
        bad_root, bad_path = config_file(tmp_path / forbidden, bad)
        with pytest.raises(OrchestrationConfigError, match="schema_invalid"):
            OrchestrationConfigLoader(bad_root).load(bad_path)


@pytest.mark.parametrize("field,value", [("timezone", "UTC"), ("morning_time", "06:00"), ("weekly_day", "monday")])
def test_fixed_timezone_time_and_weekday_cannot_be_overridden(tmp_path: Path, field: str, value: str) -> None:
    with pytest.raises(OrchestrationConfigError, match="schema_invalid"):
        loader, path = load(tmp_path, payload(**{field: value})); loader.load(path)


def test_rejects_unsafe_permissions_symlink_and_path_escape(tmp_path: Path) -> None:
    loader, path = load(tmp_path)
    path.chmod(0o644)
    with pytest.raises(OrchestrationConfigError, match="not_owner_only"):
        loader.load(path)
    path.chmod(0o600); path.parent.chmod(0o755)
    with pytest.raises(OrchestrationConfigError, match="not_owner_only"):
        loader.load(path)
    path.parent.chmod(0o700)
    path.parents[1].chmod(0o755)
    with pytest.raises(OrchestrationConfigError, match="not_owner_only"):
        loader.load(path)
    path.parents[1].chmod(0o700)
    root, _ = config_file(tmp_path / "escape", payload(state_lock_path="../outside.lock"))
    with pytest.raises(OrchestrationConfigError, match="path_escape"):
        OrchestrationConfigLoader(root).load(root / "config/orchestrator.yaml")
    root, path = config_file(tmp_path / "link")
    target = root / "outside.yaml"; target.write_text(yaml.safe_dump(payload())); target.chmod(0o600)
    path.unlink(); path.symlink_to(target)
    with pytest.raises(OrchestrationConfigError, match="symlink_forbidden"):
        OrchestrationConfigLoader(root).load(path)


def test_rejects_all_existing_raw_config_components_before_resolve(tmp_path: Path) -> None:
    root, path = config_file(tmp_path / "inside")
    config_real = root / "config-real"; path.parent.rename(config_real)
    inside_link = root / "config-link"; inside_link.symlink_to(config_real, target_is_directory=True)
    with pytest.raises(OrchestrationConfigError, match="symlink_forbidden"):
        OrchestrationConfigLoader(root).load(inside_link / "orchestrator.yaml")

    root, _ = config_file(tmp_path / "outside")
    outside = tmp_path / "external-config"; outside.mkdir(); outside.chmod(0o700)
    target = outside / "orchestrator.yaml"; target.write_text(yaml.safe_dump(payload())); target.chmod(0o600)
    outside_link = root / "config-link"; outside_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OrchestrationConfigError, match="symlink_forbidden"):
        OrchestrationConfigLoader(root).load(outside_link / "orchestrator.yaml")


def test_rejects_non_owner_root_or_middle_directory_and_safe_child_symlink(tmp_path: Path) -> None:
    root, path = config_file(tmp_path / "permissions")
    root.chmod(0o755)
    with pytest.raises(OrchestrationConfigError, match="not_owner_only"):
        OrchestrationConfigLoader(root).load(path)
    root.chmod(0o700); path.parent.chmod(0o755)
    with pytest.raises(OrchestrationConfigError, match="not_owner_only"):
        OrchestrationConfigLoader(root).load(path)
    path.parent.chmod(0o700)

    root, path = config_file(tmp_path / "safe-child", payload(state_lock_path="state-link/supervisor.lock"))
    state = root / "state"; state.mkdir(); state.chmod(0o700)
    (root / "state-link").symlink_to(state, target_is_directory=True)
    with pytest.raises(OrchestrationConfigError, match="symlink_forbidden"):
        OrchestrationConfigLoader(root).load(path)


def test_atomic_reload_keeps_last_valid_snapshot_and_returns_incident(tmp_path: Path) -> None:
    loader, path = load(tmp_path); store = AtomicConfigStore(loader, path)
    first = store.reload(); assert first.applied and first.incident is None and first.snapshot is not None
    original = first.snapshot
    path.write_text(yaml.safe_dump(payload(timezone="UTC"))); path.chmod(0o600)
    failed = store.reload()
    assert not failed.applied and failed.snapshot == original and store.active == original
    assert failed.incident is not None and failed.incident.category == "orchestrator_configuration_invalid"
    assert failed.incident.previous_config_sha256 == original.config_sha256


def test_singapore_projection_handles_utc_boundary_sunday_and_repeat_0700(tmp_path: Path) -> None:
    loader, path = load(tmp_path); snapshot = loader.load(path); service = SchedulingProjectionService()
    before = datetime(2026, 7, 18, 22, 59, tzinfo=UTC)  # Sunday 06:59 Singapore.
    jobs = {job.job_key: job for job in service.project(snapshot, before)}
    assert jobs["morning"].next_due_at_utc == datetime(2026, 7, 18, 23, 0, tzinfo=UTC)
    assert jobs["weekly"].next_due_at_utc == jobs["morning"].next_due_at_utc
    assert jobs["weekly"].depends_on_job_key == "morning" and jobs["weekly"].logical_local_date == "2026-07-19"
    assert jobs["morning"].collection_strategy == "own_incremental"
    assert jobs["weekly"].collection_strategy == "reuse_morning_collection"
    exact = datetime(2026, 7, 18, 23, 0, tzinfo=UTC)
    repeat = service.project(snapshot, exact)
    assert {job.job_key: job.next_due_at_utc for job in repeat}["morning"] == exact
    assert service.logical_local_date(datetime(2026, 7, 18, 16, 0, tzinfo=UTC)) == "2026-07-19"


def test_projection_is_utc_deterministic_across_wall_clock_jumps_and_has_intervals(tmp_path: Path) -> None:
    loader, path = load(tmp_path); snapshot = loader.load(path); service = SchedulingProjectionService()
    forward = service.project(snapshot, datetime(2026, 3, 29, 0, 0, tzinfo=UTC))
    backward = service.project(snapshot, datetime(2026, 3, 28, 23, 0, tzinfo=UTC))
    assert {job.job_key: job.next_due_at_utc for job in forward}["morning"] == datetime(2026, 3, 29, 23, 0, tzinfo=UTC)
    assert {job.job_key: job.next_due_at_utc for job in backward}["morning"] == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    jobs = {job.job_key: job for job in forward}
    assert jobs["mail_poll"].next_due_at_utc == datetime(2026, 3, 29, 0, 5, tzinfo=UTC)
    assert jobs["health_check"].next_due_at_utc == datetime(2026, 3, 29, 0, 1, tzinfo=UTC)
    assert jobs["morning"].misfire_window.total_seconds() == 12 * 3600
    assert jobs["weekly"].misfire_window.total_seconds() == 24 * 3600
    assert all(not hasattr(job, "write") for job in jobs.values())
    clock = ControlledClock(datetime(2026, 3, 29, 0, 0, tzinfo=UTC))
    assert service.project_from_clock(snapshot, clock) == forward
