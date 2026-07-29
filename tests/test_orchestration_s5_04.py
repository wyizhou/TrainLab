from __future__ import annotations

import os
import sqlite3
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration import LeaseError, LeaseManager, Supervisor
import trainlab.orchestration.repository as repository_module


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakeProbe:
    def __init__(self, absent: bool = True, raises: bool = False) -> None:
        self.absent, self.raises, self.pids = absent, raises, []

    def is_absent(self, pid: int) -> bool:
        self.pids.append(pid)
        if self.raises:
            raise PermissionError("controlled")
        return self.absent


def foundation_root(tmp_path: Path) -> Path:
    root = tmp_path / "foundation"
    receipt = FoundationTool(FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock",
    )).execute(FoundationRequest("init", "s5-04", "2026-07-24T00:00:00Z"))
    assert receipt.status == "initialized"
    return root


def manager(root: Path, clock: FakeClock, instance: str, pid: int, probe: FakeProbe | None = None, ttl: int = 10, **kwargs) -> LeaseManager:
    return LeaseManager(root / "data.db", root / "state" / "locks" / f"{instance}.lock", instance, pid, clock, probe or FakeProbe(), ttl, **kwargs)


def lease_row(root: Path):
    with sqlite3.connect(root / "data.db") as conn:
        return conn.execute("SELECT owner_instance_id,owner_pid,heartbeat_at_utc,expires_at_utc FROM scheduler_leases WHERE lease_key='supervisor'").fetchone()


def test_s5_04_two_instance_competition_renewal_boundary_and_expired_takeover(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, 0, 0, tzinfo=UTC))
    first, second = manager(root, clock, "one", 101), manager(root, clock, "two", 202)
    assert first.acquire().state == "active"
    assert second.acquire().state == "passive"
    clock.advance(5)
    assert first.heartbeat().state == "active"
    clock.advance(10)  # exact expiry remains owned (safe boundary)
    assert second.acquire().state == "passive"
    clock.advance(1)
    assert second.acquire().state == "active"
    assert lease_row(root)[:2] == ("two", 202)
    assert first.heartbeat().state == "passive"


@pytest.mark.parametrize("probe", [FakeProbe(False), FakeProbe(raises=True)], ids=["old-pid-present-or-reused", "probe-permission-uncertain"])
def test_s5_04_expired_never_takes_over_without_positive_old_pid_absence(tmp_path: Path, probe: FakeProbe) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    assert manager(root, clock, "old", 10, ttl=2).acquire().state == "active"
    clock.advance(3)
    assert manager(root, clock, "new", 20, probe, ttl=2).acquire().state == "passive"
    assert lease_row(root)[:2] == ("old", 10)


def test_s5_04_clock_backwards_and_future_expiry_fail_closed(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    owner = manager(root, clock, "one", 10, ttl=10)
    assert owner.acquire().state == "active"
    clock.advance(-1)
    with pytest.raises(LeaseError, match="clock_anomaly"):
        owner.heartbeat()
    clock.advance(1)
    with sqlite3.connect(root / "data.db") as conn:
        conn.execute("UPDATE scheduler_leases SET expires_at_utc=?", ("2026-07-24T01:00:00Z",))
    with pytest.raises(LeaseError, match="clock_anomaly"):
        owner.acquire()


def test_s5_04_missed_heartbeat_loses_ownership_without_renewal(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    owner = manager(root, clock, "one", 10, ttl=2)
    assert owner.acquire().state == "active"
    clock.advance(3)
    assert owner.heartbeat().state == "passive"
    assert lease_row(root)[:2] == ("one", 10)


def test_s5_04_database_busy_rolls_back_and_never_claims(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    blocker = sqlite3.connect(root / "data.db", timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(LeaseError, match="database_unavailable"):
            manager(root, clock, "one", 1).acquire()
    finally:
        blocker.rollback(); blocker.close()
    assert lease_row(root) is None


def test_s5_04_heartbeat_retries_only_transient_sqlite_contention(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    blocker = sqlite3.connect(root / "data.db", timeout=0)
    lease = manager(root, clock, "one", 1, heartbeat_retry_seconds=0.1)
    assert lease.acquire().state == "active"
    blocker.execute("BEGIN EXCLUSIVE")
    elapsed = [0.0]

    def monotonic() -> float:
        return elapsed[0]

    def release_after_first_backoff(delay: float) -> None:
        elapsed[0] += delay
        blocker.rollback()

    lease._monotonic = monotonic
    lease._sleep = release_after_first_backoff
    try:
        assert lease.heartbeat().state == "active"
    finally:
        blocker.close()


def test_s5_04_heartbeat_busy_beyond_budget_still_fails_closed(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    blocker = sqlite3.connect(root / "data.db", timeout=0)
    lease = manager(root, clock, "one", 1, heartbeat_retry_seconds=0.1)
    assert lease.acquire().state == "active"
    blocker.execute("BEGIN EXCLUSIVE")
    elapsed = [0.0]
    lease._monotonic = lambda: elapsed[0]
    lease._sleep = lambda delay: elapsed.__setitem__(0, elapsed[0] + delay)
    try:
        with pytest.raises(LeaseError, match="database_unavailable"):
            lease.heartbeat()
    finally:
        blocker.rollback()
        blocker.close()


def test_s5_04_heartbeat_does_not_retry_non_busy_sqlite_errors(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    lease = manager(root, clock, "one", 1, heartbeat_retry_seconds=0.1)
    assert lease.acquire().state == "active"

    class BrokenTransaction:
        def __enter__(self):
            raise sqlite3.OperationalError("disk I/O error")

        def __exit__(self, *_args):
            return False

    retries: list[float] = []
    lease._tx = lambda: BrokenTransaction()
    lease._sleep = retries.append

    with pytest.raises(LeaseError, match="database_unavailable"):
        lease.heartbeat()
    assert retries == []


def test_s5_04_local_lock_is_only_evidence_and_unknown_not_deleted(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    unknown = root / "state" / "locks" / "foreign.lock"
    unknown.write_text("foreign"); unknown.chmod(0o600)
    lease = LeaseManager(root / "data.db", unknown, "one", 1, clock, FakeProbe())
    assert lease.acquire().state == "active"
    assert unknown.exists()
    assert lease.release().state == "stopped"
    assert unknown.exists()


@pytest.mark.parametrize("replacement", ["regular", "symlink"], ids=["foreign-regular-swap", "foreign-symlink-swap"])
def test_s5_04_release_never_deletes_replaced_evidence_lock(tmp_path: Path, replacement: str) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    lease = manager(root, clock, "one", 1)
    assert lease.acquire().state == "active"
    lock = root / "state" / "locks" / "one.lock"
    lock.unlink()
    if replacement == "regular":
        lock.write_bytes(b"FOREIGN REPLACEMENT")
    else:
        target = root / "state" / "locks" / "foreign-target"
        target.write_bytes(b"FOREIGN REPLACEMENT")
        lock.symlink_to(target)
    result = lease.release()
    assert result.cleanup_status == "retained"
    assert lock.exists() or lock.is_symlink()
    if replacement == "regular":
        assert lock.read_bytes() == b"FOREIGN REPLACEMENT"


def test_s5_04_final_unlink_race_is_safe_by_never_unlinking_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    lease = manager(root, clock, "one", 1)
    assert lease.acquire().state == "active"
    lock = root / "state" / "locks" / "one.lock"
    actual_unlink = os.unlink
    def replace_at_attempt(name, *args, **kwargs):
        if name == lock.name:
            actual_unlink(lock)
            lock.write_bytes(b"FOREIGN_AFTER_CHECK")
        raise AssertionError("release must not unlink by path")
    monkeypatch.setattr(os, "unlink", replace_at_attempt)
    assert lease.release().cleanup_status == "retained"
    assert lock.exists()


def test_s5_04_counterfeit_database_is_rejected_before_any_write(tmp_path: Path) -> None:
    root = tmp_path / "counterfeit"
    root.mkdir(mode=0o700)
    locks = root / "locks"; locks.mkdir(mode=0o700)
    database = root / "counterfeit.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE scheduler_leases (id INTEGER PRIMARY KEY, lease_key TEXT, owner_instance_id TEXT, owner_pid INTEGER, acquired_at_utc TEXT, heartbeat_at_utc TEXT, expires_at_utc TEXT)")
    with pytest.raises(LeaseError, match="database_unavailable"):
        LeaseManager(database, locks / "lease.lock", "one", 1, FakeClock(datetime(2026, 7, 24, tzinfo=UTC)), FakeProbe()).acquire()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM scheduler_leases").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["symlink", "group_writable"], ids=["database-symlink", "database-mode"])
def test_s5_04_database_path_identity_gate_rejects_before_lease_write(tmp_path: Path, mutation: str) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    database = root / "data.db"
    if mutation == "symlink":
        linked = root / "linked.db"
        linked.symlink_to(database)
        input_path = linked
    else:
        database.chmod(0o660)
        input_path = database
    try:
        with pytest.raises(LeaseError, match="database_unavailable"):
            LeaseManager(input_path, root / "state" / "locks" / "bad.lock", "one", 1, clock, FakeProbe()).acquire()
    finally:
        if mutation == "group_writable":
            database.chmod(0o600)
    assert lease_row(root) is None


def test_s5_04_connect_time_database_swap_is_rejected_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = foundation_root(tmp_path)
    database, replacement, original = root / "data.db", root / "replacement.db", root / "original.db"
    shutil.copy2(database, replacement); replacement.chmod(0o600)
    real_connect = repository_module.sqlite3.connect
    swapped = False
    def connect_with_swap(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            database.rename(original)
            replacement.rename(database)
        return real_connect(*args, **kwargs)
    monkeypatch.setattr(repository_module.sqlite3, "connect", connect_with_swap)
    with pytest.raises(LeaseError, match="database_unavailable"):
        manager(root, FakeClock(datetime(2026, 7, 24, tzinfo=UTC)), "one", 1).acquire()
    with sqlite3.connect(original) as conn:
        assert conn.execute("SELECT count(*) FROM scheduler_leases").fetchone()[0] == 0
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM scheduler_leases").fetchone()[0] == 0


def test_s5_04_connect_redirect_to_other_valid_foundation_db_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, other = foundation_root(tmp_path / "one"), foundation_root(tmp_path / "two")
    real_connect = repository_module.sqlite3.connect
    configured = root / "data.db"
    def redirected_connect(target, *args, **kwargs):
        if str(configured) in str(target):
            target = f"file:{other / 'data.db'}?mode=rw"
        return real_connect(target, *args, **kwargs)
    monkeypatch.setattr(repository_module.sqlite3, "connect", redirected_connect)
    with pytest.raises(LeaseError, match="database_unavailable"):
        manager(root, FakeClock(datetime(2026, 7, 24, tzinfo=UTC)), "one", 1).acquire()
    monkeypatch.undo()
    assert lease_row(root) is None
    assert lease_row(other) is None


def test_s5_04_stale_same_identity_generation_cannot_heartbeat_or_release_new_lease(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    old = manager(root, clock, "same", 222, ttl=2)
    assert old.acquire().state == "active"
    clock.advance(3)
    replacement = manager(root, clock, "same", 222, FakeProbe(True), ttl=2)
    assert replacement.acquire().state == "active"
    before = lease_row(root)
    assert old.heartbeat().state == "passive"
    with pytest.raises(LeaseError, match="ownership_lost"):
        old.release()
    assert lease_row(root) == before
    assert replacement.heartbeat().state == "active"


def test_s5_04_takeover_audit_is_atomic_and_only_for_real_takeover(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    assert manager(root, clock, "old", 1, ttl=2).acquire().state == "active"
    with sqlite3.connect(root / "data.db") as conn:
        assert conn.execute("SELECT count(*) FROM service_health_checks WHERE check_kind='lease_takeover'").fetchone()[0] == 0
    clock.advance(3)
    second = manager(root, clock, "new", 2, FakeProbe(True), ttl=2)
    assert second.acquire().state == "active"
    clock.advance(3)
    assert manager(root, clock, "third", 3, FakeProbe(True), ttl=2).acquire().state == "active"
    with sqlite3.connect(root / "data.db") as conn:
        rows = conn.execute("SELECT check_kind,target_kind,status,metrics_json FROM service_health_checks WHERE check_kind='lease_takeover' ORDER BY id").fetchall()
    assert len(rows) == 2
    assert all(row[:3] == ("lease_takeover", "supervisor", "succeeded") for row in rows)
    assert all('previous_claim_sha256' in row[3] for row in rows)
    assert rows[0][3] != rows[1][3]
    assert second.heartbeat().state == "passive"  # stale claimant creates no audit
    with sqlite3.connect(root / "data.db") as conn:
        assert conn.execute("SELECT count(*) FROM service_health_checks WHERE check_kind='lease_takeover'").fetchone()[0] == 2


@pytest.mark.parametrize("kind", ["mode", "directory", "fifo", "oversize"], ids=["world-writable", "directory", "fifo", "oversize"])
def test_s5_04_unsafe_existing_marker_blocks_before_database_claim(tmp_path: Path, kind: str) -> None:
    root = foundation_root(tmp_path)
    lock = root / "state" / "locks" / "supervisor.lock"
    if kind == "mode":
        lock.write_bytes(b"x"); lock.chmod(0o666)
    elif kind == "directory":
        lock.mkdir()
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.write_bytes(b"x" * 4097); lock.chmod(0o600)
    with pytest.raises(LeaseError, match="existing_marker_unsafe"):
        LeaseManager(root / "data.db", lock, "one", 1, FakeClock(datetime(2026, 7, 24, tzinfo=UTC)), FakeProbe()).acquire()
    assert lease_row(root) is None


def test_s5_04_passive_and_database_failure_remove_only_own_evidence(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    first = manager(root, clock, "first", 1)
    second = manager(root, clock, "second", 2)
    assert first.acquire().state == "active"
    assert second.acquire().state == "passive"
    assert not (root / "state" / "locks" / "second.lock").exists()
    blocker = sqlite3.connect(root / "data.db", timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")
    failed = manager(root, clock, "third", 3)
    try:
        with pytest.raises(LeaseError, match="database_unavailable"):
            failed.acquire()
    finally:
        blocker.rollback(); blocker.close()
    assert not (root / "state" / "locks" / "third.lock").exists()


def test_s5_04_lock_parent_symlink_and_outside_root_are_rejected(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = root / "state" / "linked-locks"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LeaseError, match="lock_path_unsafe"):
        LeaseManager(root / "data.db", linked / "x.lock", "one", 1, clock, FakeProbe()).acquire()
    with pytest.raises(LeaseError, match="lock_path_unsafe"):
        LeaseManager(root / "data.db", outside / "x.lock", "two", 2, clock, FakeProbe()).acquire()


@pytest.mark.parametrize("signal_number", [2, 15], ids=["INT", "TERM"])
def test_s5_04_supervisor_signals_stop_without_workflow_and_cleanup(tmp_path: Path, signal_number: int) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    calls: list[str] = []
    supervisor = Supervisor(manager(root, clock, "one", 1), lambda: calls.append("executor-stop"))
    assert supervisor.start().state == "active"
    supervisor.request_stop(signal_number)
    assert supervisor.heartbeat().state == "passive"
    assert supervisor.stop().state == "stopped"
    assert calls == ["executor-stop"]
    assert lease_row(root) is None
    assert supervisor.stop().state == "stopped"
    with pytest.raises(LeaseError, match="start_invalid"):
        supervisor.start()


def test_s5_04_cleanup_exception_releases_lease_and_no_background_state(tmp_path: Path) -> None:
    root = foundation_root(tmp_path)
    clock = FakeClock(datetime(2026, 7, 24, tzinfo=UTC))
    supervisor = Supervisor(manager(root, clock, "one", 1), lambda: (_ for _ in ()).throw(RuntimeError("controlled")))
    assert supervisor.start().state == "active"
    with pytest.raises(LeaseError, match="executor_cleanup_failed"):
        supervisor.stop()
    assert supervisor.state == "stopped"
    assert lease_row(root) is None


@pytest.mark.parametrize("instance,pid", [("bad space", 1), ("ok", 0), ("ok", True)])
def test_s5_04_identity_validation(tmp_path: Path, instance: str, pid: int) -> None:
    root = foundation_root(tmp_path)
    with pytest.raises(LeaseError):
        manager(root, FakeClock(datetime(2026, 7, 24, tzinfo=UTC)), instance, pid)
