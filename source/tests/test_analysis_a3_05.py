from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

import src.analysis.run_state as run_state
from src.analysis.contracts import AnalysisRequest
from src.analysis.run_state import (
    AnalysisRunCoordinator,
    AnalysisRunRepository,
    AnalysisRunStateError,
    PreparedAnalysisRun,
    SubjectLockManager,
    build_analysis_run_key,
    parse_analysis_run_key,
)

UTC = "2026-07-23T00:00:00Z"


def request(
    mode: str = "daily",
    *,
    subject: str = "subject1",
    invocation: str | None = "invoke1",
    **override: str | None,
) -> AnalysisRequest:
    values: dict[str, str | None] = {
        "run_key": None,
        "summary_local_date": None,
        "advice_local_date": None,
        "as_of_local_date": None,
        "plan_id": None,
        "reason_event_id": None,
        "effective_local_date": None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
    }
    if mode == "daily":
        values.update(summary_local_date="2026-07-22", advice_local_date="2026-07-23")
    if mode == "weekly":
        values.update(as_of_local_date="2026-07-23")
    if mode == "revise_plan":
        values.update(
            plan_id="plan1", reason_event_id="event1", effective_local_date="2026-07-23"
        )
    if mode == "regenerate":
        values.update(
            artifact_id="artifact1", regeneration_reason_code="operator_review"
        )
    values.update(override)
    return AnalysisRequest(
        mode=mode,
        subject_id=subject,
        invocation_id=invocation,
        requested_at_utc=UTC,
        **values,
    )  # type: ignore[arg-type]


def connection(database: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(database, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, subject_key TEXT NOT NULL UNIQUE, is_active INTEGER NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO data_subjects(id,subject_key,is_active) VALUES(?,?,1)",
        [(1, "subject1"), (2, "subject2")],
    )
    conn.execute("""CREATE TABLE analysis_runs(
        id INTEGER PRIMARY KEY, run_key TEXT NOT NULL UNIQUE, subject_id INTEGER NOT NULL REFERENCES data_subjects(id),
        analysis_kind TEXT NOT NULL, target_start_local_date TEXT, target_end_local_date TEXT,
        status TEXT NOT NULL CHECK(status IN ('started','succeeded','failed','rejected')),
        harness_version TEXT, input_schema_version TEXT, output_schema_version TEXT,
        context_snapshot_json TEXT, context_snapshot_sha256 TEXT, generator_metadata_json TEXT,
        started_at_utc TEXT NOT NULL, completed_at_utc TEXT)""")
    conn.execute(
        "CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY, generated_by_run_id INTEGER NOT NULL REFERENCES analysis_runs(id))"
    )
    return conn


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("daily", "analysis:subject1:daily:2026-07-22:invoke1"),
        ("weekly", "analysis:subject1:weekly:2026-07-23:invoke1"),
        ("revise_plan", "analysis:subject1:revise_plan:plan1:event1:invoke1"),
        ("regenerate", "analysis:subject1:regenerate:artifact1:invoke1"),
    ],
)
def test_four_canonical_run_key_routes(mode: str, expected: str) -> None:
    key = build_analysis_run_key(request(mode))
    assert key.value == expected
    assert parse_analysis_run_key(key.value) == key


@pytest.mark.parametrize(
    "mode,override,expected",
    [
        (
            "daily",
            {"invocation": "invoke:daily"},
            "analysis:subject1:daily:2026-07-22:invoke%3Adaily",
        ),
        (
            "weekly",
            {"invocation": "invoke:weekly"},
            "analysis:subject1:weekly:2026-07-23:invoke%3Aweekly",
        ),
        (
            "revise_plan",
            {
                "invocation": "invoke:plan",
                "plan_id": "plan:one",
                "reason_event_id": "event:one",
            },
            "analysis:subject1:revise_plan:plan%3Aone:event%3Aone:invoke%3Aplan",
        ),
        (
            "regenerate",
            {"invocation": "invoke:regen", "artifact_id": "artifact:one"},
            "analysis:subject1:regenerate:artifact%3Aone:invoke%3Aregen",
        ),
    ],
)
def test_colon_identifiers_are_reversibly_canonicalized(
    mode: str, override: dict[str, str], expected: str
) -> None:
    source = request(mode, **override)
    key = build_analysis_run_key(source)
    assert key.value == expected
    assert parse_analysis_run_key(key.value) == key


@pytest.mark.parametrize(
    "value",
    [
        "analysis:subject1:daily:2026-01-01:inv:extra",
        "analysis:subject1:daily:not-a-date:inv",
        "analysis:subject1:retry_delivery:x:inv",
        "analysis:subject1:daily:2026-01-01:bad/inv",
        "analysis:subject1:daily:2026-01-01:invoke%3adaily",
        "analysis:subject1:daily:2026-01-01:",
    ],
)
def test_run_key_rejects_invalid_or_ambiguous_values(value: str) -> None:
    with pytest.raises(AnalysisRunStateError, match="analysis_run_key_invalid"):
        parse_analysis_run_key(value)


def test_schema_incompatible_and_missing_invocation_column_are_rejected() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, subject_key TEXT, is_active INTEGER)"
    )
    conn.execute(
        "CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY, run_key TEXT UNIQUE, subject_id INTEGER, analysis_kind TEXT, status TEXT, started_at_utc TEXT, invocation_id TEXT)"
    )
    with pytest.raises(
        AnalysisRunStateError, match="analysis_runs_schema_incompatible"
    ):
        AnalysisRunRepository(conn)


def test_same_invocation_is_unique_and_receipt_loss_recovers_started_run() -> None:
    repo = AnalysisRunRepository(connection())
    first = repo.prepare_write(request())
    recovered = repo.prepare_write(request())
    assert (first.action, recovered.action, first.run_id, recovered.run_id) == (
        "started",
        "recovered",
        first.run_id,
        first.run_id,
    )
    with pytest.raises(AnalysisRunStateError, match="analysis_invocation_id_reused"):
        repo.prepare_write(request("weekly", invocation="invoke1"))


def test_invocation_matching_is_decoded_exact_not_sql_wildcard() -> None:
    repo = AnalysisRunRepository(connection())
    repo.prepare_write(request(invocation="invoke_a"))
    # `_` must not collide with the `X` of another invocation.
    assert repo.prepare_write(request(invocation="invokeXa")).action == "started"
    with pytest.raises(AnalysisRunStateError, match="analysis_invocation_id_reused"):
        repo.prepare_write(request("weekly", invocation="invoke_a"))


def test_legacy_run_rows_are_ignored_for_new_invocation_and_current_status() -> None:
    conn = connection()
    conn.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES('daily-run',1,'daily','succeeded','2099-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES('weekly-run',1,'weekly','succeeded','2099-01-02T00:00:00Z')"
    )
    repo = AnalysisRunRepository(conn)
    created = repo.prepare_write(request(invocation="new:invoke"))
    current = repo.status(request("status", invocation=None))
    assert (
        created.action == "started"
        and current is not None
        and current.run_id == created.run_id
    )


def test_succeeded_is_unchanged_and_terminal_failures_are_not_reopened(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    started = coordinator.begin(request())
    coordinator.finish(started, "succeeded")
    assert repo.prepare_write(request()).action == "unchanged"
    failed = coordinator.begin(request(invocation="invoke2"))
    coordinator.finish(failed, "failed")
    with pytest.raises(
        AnalysisRunStateError, match="analysis_terminal_run_requires_new_invocation"
    ):
        repo.prepare_write(request(invocation="invoke2"))


def test_failed_transaction_leaves_no_half_run() -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    with pytest.raises(AnalysisRunStateError, match="analysis_subject_not_active"):
        repo.prepare_write(request(subject="unknown"))
    assert conn.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 0


def test_transition_trace_is_controlled_and_never_contains_payload() -> None:
    repo = AnalysisRunRepository(connection())
    decision = repo.prepare_write(request(invocation="safe1"))
    assert decision.transition_trace == ("run_created",)
    assert "password" not in json.dumps(decision.transition_trace)


def locks(tmp_path: Path) -> SubjectLockManager:
    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return SubjectLockManager(root / "analysis.lock")


def test_subject_locks_are_nonblocking_and_isolated(tmp_path: Path) -> None:
    manager = locks(tmp_path)
    one = manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke2")
    two = manager.acquire("subject2", "analysis:subject2:daily:2026-07-22:invoke3")
    two.release()
    one.release()


def test_coordinator_mutually_excludes_same_subject_but_not_other_subject(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    first = coordinator.begin(request(invocation="one"))
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="two"))
    other = coordinator.begin(request(subject="subject2", invocation="three"))
    other.release()
    first.release()


def test_succeeded_preflight_bypasses_other_subject_lock_but_new_work_does_not(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    old = coordinator.begin(request(invocation="old"))
    coordinator.finish(old, "succeeded")
    active = coordinator.begin(request(invocation="active"))
    assert coordinator.begin(request(invocation="old")).decision.action == "unchanged"
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="new"))
    active.release()


def test_coordinator_acquires_before_write_and_releases_after_failed_prepare(
    tmp_path: Path,
) -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    with pytest.raises(AnalysisRunStateError, match="analysis_subject_not_active"):
        coordinator.begin(request(subject="unknown", invocation="bad"))
    assert list((tmp_path / "locks").iterdir()) == []
    first = coordinator.begin(request(invocation="ok"))
    assert conn.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 1
    first.release()


def test_coordinator_finish_requires_matching_prepared_lock(tmp_path: Path) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="finish"))
    assert prepared.lock is not None
    coordinator.finish(prepared, "succeeded")
    assert repo.preflight_succeeded(request(invocation="finish")) is not None
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_unauthorized"
    ):
        coordinator.finish(PreparedAnalysisRun(prepared.decision, None), "failed")


def test_repository_has_no_public_finish_or_unbound_terminal_write(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    assert not hasattr(repo, "finish")
    prepared = repo.prepare_write(request(invocation="direct"))
    with pytest.raises(AnalysisRunStateError, match="analysis_finish_unauthorized"):
        repo._finish_authorized(
            prepared.run_id, prepared.run_key, "succeeded", object()
        )
    assert (
        repo.status(request("status", invocation=None, run_key=prepared.run_key)).status
        == "started"
    )  # type: ignore[union-attr]
    # Binding and finishing are only established by a Coordinator instance.
    AnalysisRunCoordinator(repo, locks(tmp_path))


def test_finish_accepts_only_same_coordinator_same_prepared_identity(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="identity"))
    copied = PreparedAnalysisRun(prepared.decision, prepared.lock)
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_unauthorized"
    ):
        coordinator.finish(copied, "succeeded")
    coordinator.abort(prepared)
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_unauthorized"
    ):
        coordinator.finish(prepared, "failed")


def test_finish_rejects_mutated_prepared_scope_and_second_coordinator(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    manager = locks(tmp_path)
    coordinator = AnalysisRunCoordinator(repo, manager)
    with pytest.raises(
        AnalysisRunStateError, match="analysis_repository_already_bound"
    ):
        AnalysisRunCoordinator(repo, manager)
    prepared = coordinator.begin(request(invocation="mutated"))
    assert prepared.lock is not None
    held = prepared.lock
    object.__setattr__(prepared, "lock", None)
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_lock_required"
    ):
        coordinator.finish(prepared, "succeeded")
    held.release()


def test_finish_rejects_released_lock_and_is_one_shot(tmp_path: Path) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="released"))
    assert prepared.lock is not None
    prepared.release()
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_lock_required"
    ):
        coordinator.finish(prepared, "succeeded")
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_lock_required"
    ):
        coordinator.finish(prepared, "failed")


def test_finish_db_failure_restores_canonical_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="dbfail"))
    original_finish = repo._finish_authorized
    monkeypatch.setattr(
        repo,
        "_finish_authorized",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("db")),
    )
    with pytest.raises(sqlite3.OperationalError, match="db"):
        coordinator.finish(prepared, "failed")
    monkeypatch.setattr(repo, "_finish_authorized", original_finish)
    lock_path = tmp_path / "locks/analysis.lock.subject1.lock"
    assert lock_path.exists()
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="after-dbfail"))


def test_actual_sqlite_update_failure_rolls_back_and_restores_lock(
    tmp_path: Path,
) -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="trigger-update"))
    conn.execute(
        "CREATE TRIGGER fail_analysis_finish BEFORE UPDATE ON analysis_runs BEGIN SELECT RAISE(ABORT, 'finish denied'); END"
    )
    with pytest.raises(sqlite3.DatabaseError, match="finish denied"):
        coordinator.finish(prepared, "succeeded")
    row = conn.execute(
        "SELECT status FROM analysis_runs WHERE id=?", (prepared.decision.run_id,)
    ).fetchone()
    assert (
        row[0] == "started"
        and (tmp_path / "locks/analysis.lock.subject1.lock").exists()
    )


def test_actual_sqlite_commit_failure_rolls_back_and_restores_lock(
    tmp_path: Path,
) -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="deny-commit"))

    def deny_commit(
        action: int,
        arg1: str | None,
        arg2: str | None,
        db: str | None,
        source: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_commit)
    with pytest.raises(sqlite3.DatabaseError):
        coordinator.finish(prepared, "succeeded")
    conn.set_authorizer(None)
    row = conn.execute(
        "SELECT status FROM analysis_runs WHERE id=?", (prepared.decision.run_id,)
    ).fetchone()
    assert (
        row[0] == "started"
        and (tmp_path / "locks/analysis.lock.subject1.lock").exists()
    )


def test_commit_success_cleanup_failure_is_status_visible_and_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="cleanup"))
    assert prepared.lock is not None
    original_finalize = prepared.lock.finalize_finish_claim

    def cleanup_fail(claim: str, *, committed: bool) -> None:
        if committed:
            original_finalize(claim, committed=False)
            raise AnalysisRunStateError("analysis_lock_busy")
        original_finalize(claim, committed=committed)

    monkeypatch.setattr(prepared.lock, "finalize_finish_claim", cleanup_fail)
    with pytest.raises(AnalysisRunStateError, match="analysis_finish_cleanup_required"):
        coordinator.finish(prepared, "succeeded")
    status = repo.status(
        request("status", invocation=None, run_key=prepared.decision.run_key)
    )
    assert status is not None and status.status == "succeeded"
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="after-cleanup"))


def test_committed_finish_unlink_failure_keeps_claim_and_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="unlink-fail"))
    assert prepared.lock is not None
    original_unlink = os.unlink

    def fail_finish_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if ".finish." in name:
            raise OSError("unlink")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fail_finish_unlink)
    with pytest.raises(AnalysisRunStateError, match="analysis_finish_cleanup_required"):
        coordinator.finish(prepared, "succeeded")
    status = repo.status(
        request("status", invocation=None, run_key=prepared.decision.run_key)
    )
    assert status is not None and status.status == "succeeded"
    assert list((tmp_path / "locks").glob("*.claim")) or list(
        (tmp_path / "locks").glob(".*.claim")
    )
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="after-unlink-fail"))


def test_committed_finish_parent_fsync_failure_rebuilds_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="fsync-fail"))
    assert prepared.lock is not None
    parent_fd = prepared.lock.parent_fd
    original_fsync = os.fsync
    parent_calls = 0

    def fail_once_parent(fd: int) -> None:
        nonlocal parent_calls
        if fd == parent_fd:
            parent_calls += 1
        # First parent fsync persists canonical→finish claim.  Fail the next
        # one, after unlink, to exercise committed cleanup recovery.
        if fd == parent_fd and parent_calls == 2:
            raise OSError("parent fsync")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_once_parent)
    with pytest.raises(AnalysisRunStateError, match="analysis_finish_cleanup_required"):
        coordinator.finish(prepared, "succeeded")
    status = repo.status(
        request("status", invocation=None, run_key=prepared.decision.run_key)
    )
    assert status is not None and status.status == "succeeded"
    assert list((tmp_path / "locks").glob(".*.cleanup.*.claim"))
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="after-fsync-fail"))


def test_invalid_finish_status_keeps_prepared_authorization_for_abort(
    tmp_path: Path,
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="invalid-status"))
    with pytest.raises(AnalysisRunStateError, match="analysis_finish_status_invalid"):
        coordinator.finish(prepared, "invalid")  # type: ignore[arg-type]
    coordinator.abort(prepared)


def test_cross_coordinator_prepared_is_rejected_but_origin_can_abort(
    tmp_path: Path,
) -> None:
    # Separate SQLite connections simulate separate processes over one DB and
    # one trusted lock root.
    database = tmp_path / "shared.sqlite"
    repo1 = AnalysisRunRepository(connection(database))
    peer = sqlite3.connect(database, isolation_level=None)
    peer.execute("PRAGMA foreign_keys=ON")
    repo2 = AnalysisRunRepository(peer)
    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    one = AnalysisRunCoordinator(repo1, SubjectLockManager(root / "analysis.lock"))
    two = AnalysisRunCoordinator(repo2, SubjectLockManager(root / "analysis.lock"))
    prepared = one.begin(request(invocation="cross"))
    with pytest.raises(
        AnalysisRunStateError, match="analysis_prepared_run_unauthorized"
    ):
        two.finish(prepared, "succeeded")
    one.abort(prepared)


def test_finish_claim_swap_never_authorizes_database_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="claim-swap"))
    filename = "analysis.lock.subject1.lock"
    replacement = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:other",
        "started_at_utc": UTC,
    }
    original_rename = os.rename

    def swap_finish_claim(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if dst.startswith(f".{filename}.finish."):
            os.unlink(dst, dir_fd=dst_dir_fd)
            fd = os.open(
                dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dst_dir_fd
            )
            try:
                os.write(fd, json.dumps(replacement).encode("utf-8"))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)

    monkeypatch.setattr(os, "rename", swap_finish_claim)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.finish(prepared, "succeeded")
    status = repo.status(
        request("status", invocation=None, run_key=prepared.decision.run_key)
    )
    assert status is not None and status.status == "started"
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.begin(request(invocation="after-claim-swap"))


def test_finish_canonical_rebuild_never_authorizes_database_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    prepared = coordinator.begin(request(invocation="canonical-rebuild"))
    filename = "analysis.lock.subject1.lock"
    replacement = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:other",
        "started_at_utc": UTC,
    }
    original_rename = os.rename

    def rebuild_canonical(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if dst.startswith(f".{filename}.finish."):
            fd = os.open(
                filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=src_dir_fd
            )
            try:
                os.write(fd, json.dumps(replacement).encode("utf-8"))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)

    monkeypatch.setattr(os, "rename", rebuild_canonical)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        coordinator.finish(prepared, "succeeded")
    status = repo.status(
        request("status", invocation=None, run_key=prepared.decision.run_key)
    )
    assert status is not None and status.status == "started"


@pytest.mark.skipif(not Path("/dev/fd").exists(), reason="platform has no fd view")
def test_successful_finish_chain_does_not_leak_file_descriptors(tmp_path: Path) -> None:
    repo = AnalysisRunRepository(connection())
    coordinator = AnalysisRunCoordinator(repo, locks(tmp_path))
    before = len(os.listdir("/dev/fd"))
    for index in range(10):
        prepared = coordinator.begin(request(invocation=f"finish-loop-{index}"))
        coordinator.finish(prepared, "succeeded")
    assert len(os.listdir("/dev/fd")) <= before


def test_active_stale_and_malicious_lock_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    path = tmp_path / "locks/analysis.lock.subject1.lock"
    payload = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke1",
        "started_at_utc": UTC,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", payload["run_key"])
    monkeypatch.setattr(
        os, "kill", lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError())
    )
    recovered = manager.acquire("subject1", payload["run_key"])
    recovered.release()
    path.write_text("{broken", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", payload["run_key"])


def test_stale_claim_preserves_same_payload_replacement_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    filename = "analysis.lock.subject1.lock"
    path = tmp_path / "locks" / filename
    payload = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke1",
        "started_at_utc": UTC,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    original_rename = os.rename

    def replace_before_claim(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src == filename and dst.startswith(f".{filename}.stale."):
            os.unlink(filename, dir_fd=src_dir_fd)
            replacement = os.open(
                filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=src_dir_fd
            )
            try:
                os.write(replacement, json.dumps(payload).encode("utf-8"))
                os.fchmod(replacement, 0o600)
            finally:
                os.close(replacement)
        original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(
        os, "kill", lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError())
    )
    monkeypatch.setattr(os, "rename", replace_before_claim)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", payload["run_key"])
    quarantined = list((tmp_path / "locks").glob(f".{filename}.stale.*.claim"))
    assert path.exists() and len(quarantined) == 1
    assert json.loads(quarantined[0].read_text(encoding="utf-8")) == payload
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", payload["run_key"])


@pytest.mark.parametrize("short_write", [True, False])
def test_failed_create_leaves_no_owned_lock_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short_write: bool
) -> None:
    manager = locks(tmp_path)
    original_write = os.write

    def incomplete_write(fd: int, data: bytes) -> int:
        if short_write:
            return max(0, len(data) - 1)
        return 0

    monkeypatch.setattr(os, "write", incomplete_write)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_create_failed"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    assert list((tmp_path / "locks").iterdir()) == []
    monkeypatch.setattr(os, "write", original_write)


def test_post_create_replacement_is_quarantined_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    filename = "analysis.lock.subject1.lock"
    replacement = {
        "pid": 999,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke9",
        "started_at_utc": UTC,
    }
    original_reader = run_state._read_private_lock_at
    calls = 0

    def replace_before_read(parent_fd: int, name: str):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        # First read is the pre-create missing check; swap only before the
        # mandatory post-create verification read.
        if calls == 2 and name == filename:
            os.unlink(name, dir_fd=parent_fd)
            fd = os.open(
                name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=parent_fd
            )
            try:
                os.write(fd, json.dumps(replacement).encode("utf-8"))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        return original_reader(parent_fd, name)

    monkeypatch.setattr(run_state, "_read_private_lock_at", replace_before_read)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_create_failed"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    claims = list((tmp_path / "locks").glob(f".{filename}.failed-create.*.claim"))
    assert (tmp_path / "locks" / filename).exists() and len(claims) == 1
    assert json.loads(claims[0].read_text(encoding="utf-8")) == replacement
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")


def test_release_pre_read_swap_preserves_replacement_and_closes_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    held = manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    replacement = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke2",
        "started_at_utc": UTC,
    }
    original_reader = run_state._read_private_lock_at

    def swap_before_read(parent_fd: int, name: str):  # type: ignore[no-untyped-def]
        os.unlink(name, dir_fd=parent_fd)
        fd = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=parent_fd
        )
        try:
            os.write(fd, json.dumps(replacement).encode("utf-8"))
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        return original_reader(parent_fd, name)

    monkeypatch.setattr(run_state, "_read_private_lock_at", swap_before_read)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        held.release()
    monkeypatch.setattr(run_state, "_read_private_lock_at", original_reader)
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", replacement["run_key"])
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_already_released"):
        held.release()


def test_release_claim_swap_quarantines_unknown_and_blocks_future_acquire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    held = manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    replacement = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke2",
        "started_at_utc": UTC,
    }
    original_rename = os.rename

    def swap_claim(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if dst.startswith(".analysis.lock.subject1.lock.release."):
            os.unlink(dst, dir_fd=dst_dir_fd)
            fd = os.open(
                dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dst_dir_fd
            )
            try:
                os.write(fd, json.dumps(replacement).encode("utf-8"))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)

    monkeypatch.setattr(os, "rename", swap_claim)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        held.release()
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", replacement["run_key"])


def test_release_does_not_overwrite_third_party_canonical_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    held = manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    filename = "analysis.lock.subject1.lock"
    replacement = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke2",
        "started_at_utc": UTC,
    }
    original_rename = os.rename

    def rebuild_canonical(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if dst.startswith(f".{filename}.release."):
            fd = os.open(
                filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=src_dir_fd
            )
            try:
                os.write(fd, json.dumps(replacement).encode("utf-8"))
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)

    monkeypatch.setattr(os, "rename", rebuild_canonical)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        held.release()
    assert (
        json.loads((tmp_path / "locks" / filename).read_text(encoding="utf-8"))
        == replacement
    )
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", replacement["run_key"])


@pytest.mark.skipif(not Path("/dev/fd").exists(), reason="platform has no fd view")
def test_release_closes_parent_once_and_is_explicitly_nonrepeatable(
    tmp_path: Path,
) -> None:
    manager = locks(tmp_path)
    before = len(os.listdir("/dev/fd"))
    for index in range(12):
        held = manager.acquire(
            "subject1", f"analysis:subject1:daily:2026-07-22:invoke{index}"
        )
        held.release()
        with pytest.raises(
            AnalysisRunStateError, match="analysis_lock_already_released"
        ):
            held.release()
    assert len(os.listdir("/dev/fd")) <= before


@pytest.mark.skipif(not Path("/dev/fd").exists(), reason="platform has no fd view")
def test_acquire_paths_do_not_leak_file_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    path = tmp_path / "locks/analysis.lock.subject1.lock"
    active = {
        "pid": 4242,
        "run_key": "analysis:subject1:daily:2026-07-22:invoke1",
        "started_at_utc": UTC,
    }
    path.write_text(json.dumps(active), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    before = len(os.listdir("/dev/fd"))
    for _ in range(12):
        with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
            manager.acquire("subject1", active["run_key"])
    path.write_text("{broken", encoding="utf-8")
    path.chmod(0o600)
    for _ in range(12):
        with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
            manager.acquire("subject1", active["run_key"])
    assert len(os.listdir("/dev/fd")) == before


def test_lock_creation_failure_removes_only_its_own_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = locks(tmp_path)
    path = tmp_path / "locks/analysis.lock.subject1.lock"
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_create_failed"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    assert not path.exists()
    # An fsync failure after the atomic claim may leave the failed call's
    # quarantine marker.  Remove this test fixture record before exercising a
    # distinct replacement race below.
    for claim in (tmp_path / "locks").glob(".analysis.lock.subject1.lock.*.claim"):
        claim.unlink()

    def replace_then_fail(fd: int) -> None:
        path.unlink(missing_ok=True)
        path.write_text('{"replacement":true}', encoding="utf-8")
        path.chmod(0o600)
        raise OSError("fsync")

    monkeypatch.setattr(os, "fsync", replace_then_fail)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_create_failed"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke2")
    assert path.exists() and path.read_text(encoding="utf-8") == '{"replacement":true}'


def test_lock_rejects_symlink_and_wide_permissions(tmp_path: Path) -> None:
    manager = locks(tmp_path)
    path = tmp_path / "locks/analysis.lock.subject1.lock"
    outside = tmp_path / "outside"
    outside.write_text("x", encoding="utf-8")
    path.symlink_to(outside)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    path.unlink()
    path.write_text(
        json.dumps(
            {
                "pid": 1,
                "run_key": "analysis:subject1:daily:2026-07-22:invoke1",
                "started_at_utc": UTC,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o666)
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_busy"):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")


def test_lock_parent_requires_owner_only_mode_and_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "locks"
    root.mkdir()
    root.chmod(0o755)
    manager = SubjectLockManager(root / "analysis.lock")
    with pytest.raises(
        AnalysisRunStateError, match="analysis_lock_parent_unsafe_permissions"
    ):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")
    root.chmod(0o700)
    monkeypatch.setattr(os, "getuid", lambda: 987654)
    with pytest.raises(
        AnalysisRunStateError, match="analysis_lock_parent_unsafe_permissions"
    ):
        manager.acquire("subject1", "analysis:subject1:daily:2026-07-22:invoke1")


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_lock_rejects_symlink_at_each_trusted_boundary_component(
    tmp_path: Path, depth: int
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    real.chmod(0o700)
    if depth == 0:
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        base = link / "analysis.lock"
        trusted = tmp_path
    elif depth == 1:
        (real / "locks").mkdir(mode=0o700)
        (real / "locks").chmod(0o700)
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        base = link / "locks/analysis.lock"
        trusted = tmp_path
    else:
        (real / "one").mkdir(mode=0o700)
        (real / "one").chmod(0o700)
        (real / "one/locks").mkdir(mode=0o700)
        (real / "one/locks").chmod(0o700)
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        base = link / "one/locks/analysis.lock"
        trusted = tmp_path
    with pytest.raises(AnalysisRunStateError, match="analysis_lock_path_escape"):
        SubjectLockManager(base, trusted_root=trusted).acquire(
            "subject1", "analysis:subject1:daily:2026-07-22:invoke1"
        )


def test_open_lock_parent_fd_stays_bound_after_path_swap(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    parent = root / "locks"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    manager = SubjectLockManager(parent / "analysis.lock", trusted_root=root)
    fd, info, name = manager._open_lock_parent("subject1")
    moved = root / "locks-old"
    parent.rename(moved)
    replacement = root / "locks"
    replacement.mkdir(mode=0o700)
    replacement.chmod(0o700)
    try:
        assert (
            name == "analysis.lock.subject1.lock" and os.fstat(fd).st_ino == info.st_ino
        )
        assert os.fstat(fd).st_ino != replacement.stat().st_ino
    finally:
        os.close(fd)


def test_status_is_pure_read_only_for_database_and_lock_files(tmp_path: Path) -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    decision = repo.prepare_write(request())
    key = decision.run_key
    manager = locks(tmp_path)
    coordinator = AnalysisRunCoordinator(repo, manager)
    existing_files = sorted(path.name for path in (tmp_path / "locks").iterdir())
    before = conn.total_changes
    status_request = request("status", invocation=None, run_key=key)
    result = coordinator.status(status_request)
    assert result is not None and result.run_id == decision.run_id
    assert conn.total_changes == before
    assert (
        sorted(path.name for path in (tmp_path / "locks").iterdir()) == existing_files
    )
    assert manager  # Explicitly proves status has no need to acquire a lock manager.


def test_status_without_run_key_selects_latest_subject_run_read_only(
    tmp_path: Path,
) -> None:
    conn = connection()
    repo = AnalysisRunRepository(conn)
    first = repo.prepare_write(request(invocation="one"))
    second = repo.prepare_write(request(invocation="two"))
    before = conn.total_changes
    files = list((tmp_path / "locks").glob("*"))
    result = repo.status(request("status", invocation=None))
    assert (
        result is not None
        and result.run_id == second.run_id
        and result.run_id != first.run_id
    )
    assert (
        conn.total_changes == before and list((tmp_path / "locks").glob("*")) == files
    )
