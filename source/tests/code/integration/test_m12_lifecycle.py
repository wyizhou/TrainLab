from __future__ import annotations

import json
import os
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import lifecycle, run_state, runtime_resources, storage

SOURCE = Path(__file__).resolve().parents[3]

CHILD = """
import sys, signal
from pathlib import Path
from skills._shared.fit_weekly import lifecycle, storage
root = Path(sys.argv[1])
with lifecycle.run(root, 'sync'):
    with storage.open_store(root) as db:
        print('READY', flush=True)
        signal.pause()
"""


def child(root: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(root)],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 10)
    if not ready or process.stdout.readline().strip() != "READY":
        process.kill()
        out, err = process.communicate(timeout=5)
        pytest.fail(f"child did not start: {out!r} {err!r}")
    return process


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])
def test_real_signal_lock_status_and_restart(tmp_path: Path, sig: int) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    process = child(root)
    try:
        before = snapshot(root)
        state = run_state.status(root)
        assert state["lifecycle"] == "running"
        assert state["database"] == "readable"
        assert state["last_run"]["command"] == "sync"
        assert snapshot(root) == before
        with pytest.raises(ValueError, match="lifecycle_busy"):
            with lifecycle.run(root, "weekly"):
                pytest.fail("second writer admitted")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skills._shared.fit_weekly",
                "--instance",
                str(root),
                "status",
            ],
            cwd=SOURCE,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["lifecycle"] == "running"
        os.kill(process.pid, sig)
        process.communicate(timeout=10)
        assert process.returncode == (-sig if sig == signal.SIGKILL else 128 + sig)
        state = run_state.status(root)
        assert state["lifecycle"] == (
            "interrupted" if sig == signal.SIGKILL else "not_running"
        )
        if sig != signal.SIGKILL:
            assert state["last_run"]["outcome"] == "stopped"
            assert state["last_run"]["signal"] == sig
        with lifecycle.run(root, "edit"):
            with storage.open_store(root):
                assert run_state.status(root)["lifecycle"] == "running"
        assert run_state.status(root)["last_run"]["outcome"] == "completed"
        moved = tmp_path / "moved"
        root.rename(moved)
        assert run_state.status(moved)["lifecycle"] == "not_running"
        assert len(list((moved / "runtime/runs").iterdir())) == 2
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_status_does_not_read_tokens_or_modify_old_database(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    (root / "config.json").write_text("unreadable private configuration")
    before = snapshot(root)
    original = Path.read_bytes

    def guarded(path):
        if path.name in ("config.json", "token.json"):
            pytest.fail("status read service configuration")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with storage.open_store(root):
        assert run_state.status(root)["lifecycle"] == "not_running"
    monkeypatch.undo()
    assert snapshot(root) == before


@pytest.mark.parametrize(
    "case", ["bad_db", "bad_mode", "link", "bad_state", "missing_lock", "exclusive"]
)
def test_status_failures_are_unreadable_and_do_not_repair(
    tmp_path: Path, case: str
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    with lifecycle.run(root, "sync"):
        pass
    connection = None
    if case == "bad_db":
        (root / "trainlab-fit.db").write_bytes(b"not SQLite")
    elif case == "bad_mode":
        (root / "trainlab-fit.db").chmod(0o644)
    elif case == "link":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif case == "bad_state":
        next((root / "runtime/runs").glob("*/start.json")).write_text("broken")
    elif case == "missing_lock":
        (root / "lifecycle.lock").unlink()
    else:
        connection = sqlite3.connect(root / "trainlab-fit.db")
        connection.execute("BEGIN EXCLUSIVE")
    before = snapshot(root)
    try:
        result = run_state.status(root)
        assert (
            result["instance"] == "unreadable"
            or result["database"] == "unreadable"
            or result["lifecycle"] == "unreadable"
        )
        assert snapshot(root) == before
    finally:
        if connection is not None:
            connection.close()


def test_business_pending_unknown_and_corruption(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)

    def put(key, value):
        with storage.open_store(root) as db:
            storage.put_document(
                db,
                "delivery_receipt",
                key,
                storage.digest(storage.canonical(value).encode()),
                value,
            )

    request = {"schema_version": "fit_delivery_request_v1", "action_key": "mail-1"}
    put("pub:one:request", request)
    assert run_state.status(root)["business"]["pending"] == 1
    put("pub:one:intent", {"schema_version": "fit_delivery_intent_v1"})
    assert run_state.status(root)["business"]["unknown"] == 1
    with sqlite3.connect(root / "trainlab-fit.db") as db:
        db.execute("DROP TRIGGER documents_update")
        db.execute("UPDATE documents SET content_sha256=?", ("0" * 64,))
    assert run_state.status(root)["database"] == "unreadable"


def test_exception_records_failure_without_secret(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    with pytest.raises(RuntimeError):
        with lifecycle.run(root, "weekly"):
            raise RuntimeError("PRIVATE-SYNTHETIC-SENTINEL")
    result = run_state.status(root)
    assert result["last_run"]["outcome"] == "failed"
    assert "PRIVATE-SYNTHETIC-SENTINEL" not in json.dumps(result)
    assert all(
        b"PRIVATE-SYNTHETIC-SENTINEL" not in content
        for content in snapshot(root).values()
    )


def test_live_pid_without_os_lock_is_interrupted(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    with lifecycle.run(root, "sync"):
        pass
    run_state.begin(root, "weekly", "2026-09-09T00:00:00Z")
    result = run_state.status(root)
    assert result["last_run"]["pid"] == os.getpid()
    assert result["lifecycle"] == "interrupted"


def test_lock_durability_failure_closes_descriptor_and_restarts(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    closed = []
    original_close = lifecycle.os.close

    def track(fd):
        closed.append(fd)
        original_close(fd)

    def fail(path):
        raise OSError("synthetic barrier failure")

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle.os, "close", track)
        patch.setattr(lifecycle.storage, "sync_dir", fail)
        with pytest.raises(OSError):
            with lifecycle.run(root, "sync"):
                pytest.fail("barrier failure admitted business")
    assert closed
    with lifecycle.run(root, "sync"):
        assert run_state.status(root)["lifecycle"] == "running"


def test_interrupted_start_record_preserves_attempt_and_allows_restart(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)

    def fail(*args):
        raise OSError("synthetic interruption before start record")

    with monkeypatch.context() as patch:
        patch.setattr(run_state.storage, "atomic_file", fail)
        with pytest.raises(OSError):
            with lifecycle.run(root, "sync"):
                pytest.fail("business started without durable record")
    assert run_state.status(root)["lifecycle"] == "interrupted"
    with lifecycle.run(root, "sync"):
        pass
    assert run_state.status(root)["last_run"]["sequence"] == 2
    assert len(list((root / "runtime/runs").iterdir())) == 2


def test_explicit_resource_copy_runs_real_status_without_tests_or_archive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    root = tmp_path / "instance"
    storage.initialize(root)
    database = (root / "trainlab-fit.db").read_bytes()
    with lifecycle.run(root, "sync"):
        pass
    for path in runtime_resources.files(SOURCE, entrypoint=True):
        target = source / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    assert not (source / "tests").exists()
    assert not (source / "data-backup").exists()
    assert not (source / "skills/_shared/fit_weekly/legacy_import.py").exists()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills._shared.fit_weekly",
            "--instance",
            str(root),
            "status",
        ],
        cwd=source,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["lifecycle"] == "not_running"
    assert (root / "trainlab-fit.db").read_bytes() == database
