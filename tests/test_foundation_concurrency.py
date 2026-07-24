from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def request() -> FoundationRequest:
    return FoundationRequest(mode="init", invocation_id="concurrency-test", requested_at_utc="2026-07-23T00:00:00Z")


def test_simultaneous_init_has_one_writer_and_one_lock_busy(tmp_path: Path) -> None:
    root = tmp_path / "same-root"
    entered, release = Event(), Event()

    def pause_at_phase(phase: str) -> None:
        if phase == "before_schema":
            entered.set()
            assert release.wait(timeout=5)

    first = FoundationTool(config(root), failpoint=pause_at_phase)
    result: list[str] = []
    worker = Thread(target=lambda: result.append(first.execute(request()).status))
    worker.start()
    assert entered.wait(timeout=5)
    second = FoundationTool(config(root)).execute(request())
    assert second.status == "lock_busy"
    release.set(); worker.join(timeout=5)
    assert result == ["initialized"]
    assert FoundationTool(config(root)).execute(request()).status == "already_initialized"


def test_init_rechecks_database_after_lock_acquisition(tmp_path: Path) -> None:
    root = tmp_path / "recheck"
    contender = FoundationTool(config(root))

    @contextmanager
    def lock_with_prior_writer(_root: Path):
        # This controlled seam models the first writer committing while the
        # contender is waiting to enter its already-acquired lock body.
        assert FoundationTool(config(root)).execute(request()).status == "initialized"
        yield

    contender._lock = lock_with_prior_writer  # type: ignore[method-assign]
    receipt = contender.execute(request())
    assert receipt.status == "already_initialized"


def test_initializing_recovery_competes_under_the_same_writer_lock(tmp_path: Path) -> None:
    root = tmp_path / "recovery"

    def crash_after_schema(phase: str) -> None:
        if phase == "after_schema":
            raise RuntimeError("simulated crash")

    assert FoundationTool(config(root), failpoint=crash_after_schema).execute(request()).status == "failed"
    holder = FoundationTool(config(root))
    acquired, release = Event(), Event()

    def hold_lock() -> None:
        with holder._lock(root):
            acquired.set()
            assert release.wait(timeout=5)

    thread = Thread(target=hold_lock); thread.start()
    assert acquired.wait(timeout=5)
    competitor = FoundationTool(config(root)).execute(request())
    assert competitor.status == "lock_busy"
    release.set(); thread.join(timeout=5)
    recovered = FoundationTool(config(root)).execute(request())
    assert recovered.status == "initialized" and recovered.ready
