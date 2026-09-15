from __future__ import annotations

import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills._shared.fit_weekly import (
    model_job,
    report_artifacts,
    run_state,
    schedule_state,
    storage,
)

SOURCE = Path(__file__).resolve().parents[3]
HOST = SOURCE / "tests/code/fixtures/m12_daemon_host.py"
END = "2026-08-09T07:00:00Z"
DAY = "daily:2026-09-09"


def until(check, *, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("bounded process observation timed out")


def launch(area, mode, now):
    (area / "clock").write_text(now)
    (area / "ready").unlink(missing_ok=True)
    log = (area / f"host-{len(list(area.glob('host-*.log')))}.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, str(HOST), str(area), mode],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=log,
        stderr=log,
    )
    log.close()
    try:
        until(lambda: (area / "ready").exists() or proc.poll() is not None, timeout=90)
        assert proc.poll() is None, [p.read_text() for p in area.glob("host-*.log")]
        return proc, Path((area / "ready").read_text())
    except BaseException:
        proc.kill()
        proc.wait(timeout=5)
        raise


def outcome(root, slot):
    return schedule_state.read(root)["outcomes"].get(slot)


def terminate(proc, sig=signal.SIGTERM):
    if proc.poll() is None:
        proc.send_signal(sig)
    return proc.wait(timeout=15)


def alive(pid):
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True
    )
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def cli(root, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "skills._shared.fit_weekly",
            "--instance",
            str(root),
            *args,
        ],
        cwd=SOURCE,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_model_pid_marker_is_published_only_when_complete(tmp_path):
    marker = tmp_path / "model-pids.json"
    children = []
    opened = []
    observed = []

    def spawn(*args, **kwargs):
        assert not marker.exists(), "model PID marker published before child is ready"
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        observed.append("spawn")
        return child

    def track_open(*args, **kwargs):
        stream = open(*args, **kwargs)
        opened.append(stream)
        return stream

    def publish(source, destination):
        assert Path(source).parent == marker.parent
        assert Path(source) != marker
        assert Path(destination) == marker
        assert not marker.exists()
        assert opened and all(stream.closed for stream in opened)
        assert json.loads(Path(source).read_text()) == [os.getpid(), children[0].pid]
        os.replace(source, destination)
        assert json.loads(marker.read_text()) == [os.getpid(), children[0].pid]
        observed.append("publish")

    def wait(seconds):
        assert seconds == 120
        assert json.loads(marker.read_text()) == [os.getpid(), children[0].pid]
        assert all(child.poll() is None for child in children)
        observed.append("wait")

    namespace = {
        "json": json,
        "os": SimpleNamespace(getpid=os.getpid, replace=publish),
        "subprocess": SimpleNamespace(Popen=spawn),
        "sys": sys,
        "time": SimpleNamespace(sleep=wait),
        "open": track_open,
    }
    try:
        code = runpy.run_path(str(HOST))["model_wait_code"](marker)
        exec(code, namespace)
        assert observed == ["spawn", "publish", "wait"]
    finally:
        for stream in opened:
            stream.close()
        for child in children:
            terminate(child)


def test_daemon_real_daily_cutoff_status_busy_stop_restart_and_move(tmp_path):
    proc, root = launch(tmp_path, "daily", "2026-09-09T13:59:59Z")
    try:
        until(lambda: run_state.status(root)["lifecycle"] == "running")
        until(
            lambda: schedule_state.read(root)["last_seen_utc"] == "2026-09-09T13:59:59Z"
        )
        before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        result = cli(root, "status")
        assert result.returncode == 0
        assert json.loads(result.stdout)["last_run"]["command"] == "daemon"
        assert {
            str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()
        } == before
        assert not schedule_state.read(root)["claims"]
        assert cli(root, "reconcile").returncode == 2
        (tmp_path / "clock").write_text("2026-09-09T14:00:00Z")
        assert until(lambda: outcome(root, DAY))["status"] == "complete"
        claim = schedule_state.read(root)["claims"][DAY]
        assert claim["late"] is False
        assert claim["dates"] == ["2026-09-08", "2026-09-09"]
        calls = json.loads((tmp_path / "http.json").read_text())["calls"]
        assert sum(url.endswith("/send") for _, url in calls) == 1
        assert terminate(proc) == 143
        state = run_state.status(root)
        assert state["last_run"]["outcome"] == "stopped"
        assert state["lifecycle"] == "not_running"
        moved = tmp_path / "moved-instance"
        root.rename(moved)
        (tmp_path / "resume-instance").write_text(str(moved))
        restarted, moved = launch(tmp_path, "daily", "2026-09-09T14:00:01Z")
        try:
            until(lambda: run_state.status(moved)["lifecycle"] == "running")
            time.sleep(0.5)
            assert schedule_state.read(moved)["attempts"][DAY] == 1
            assert json.loads((tmp_path / "http.json").read_text())["calls"] == calls
        finally:
            terminate(restarted)
    finally:
        terminate(proc)


@pytest.mark.parametrize("late", [False, True])
def test_daemon_real_complete_week_original_chain_and_late_dates(tmp_path, late):
    now = "2026-08-11T04:00:00Z" if late else "2026-08-09T06:59:59Z"
    proc, root = launch(tmp_path, "late" if late else "weekly", now)
    try:
        if not late:
            until(lambda: run_state.status(root)["lifecycle"] == "running")
            assert f"weekly:{END}" not in schedule_state.read(root)["claims"]
            (tmp_path / "clock").write_text("2026-08-09T07:00:01Z")
        result = until(lambda: outcome(root, f"weekly:{END}"), timeout=120)
        assert result["status"] == "complete", (
            result,
            [p.read_text() for p in tmp_path.glob("host-*.log")],
        )
        state = schedule_state.read(root)
        assert list(state["claims"]) == [f"weekly:{END}"]
        assert state["claims"][f"weekly:{END}"]["late"] is late
        bundle = report_artifacts.read_sealed(root, END)
        assert bundle.pdf.startswith(b"%PDF")
        provider = json.loads((tmp_path / "provider.json").read_text())
        assert [v["date"] for v in provider["calendar"]] == (
            ["2026-08-13", "2026-08-16"]
            if late
            else ["2026-08-10", "2026-08-13", "2026-08-16"]
        )
        for stage in ("plan", "summary"):
            assert (
                model_job.capture_path(root, END, stage=stage).parent
                / "command/process/capture.json"
            ).is_file()
        assert (
            sum(
                url.endswith("/send")
                for _, url in json.loads((tmp_path / "http.json").read_text())["calls"]
            )
            == 1
        )
    finally:
        terminate(proc)


@pytest.mark.parametrize("mode", ["claim", "provider", "model"])
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])
def test_real_interrupt_descendants_locks_and_original_claim_recovery(
    tmp_path, mode, sig
):
    now = "2026-08-09T07:00:01Z" if mode == "model" else "2026-09-09T14:00:00Z"
    proc, root = launch(tmp_path, mode, now)
    try:
        marker = tmp_path / (
            "claimed"
            if mode == "claim"
            else "provider-pids.json.waiting"
            if mode == "provider"
            else "model-pids.json"
        )
        until(lambda: marker.exists() or proc.poll() is not None, timeout=100)
        assert proc.poll() is None, [p.read_text() for p in tmp_path.glob("host-*.log")]
        pids = (
            []
            if mode == "claim"
            else json.loads(
                (
                    tmp_path
                    / (
                        "provider-pids.json"
                        if mode == "provider"
                        else "model-pids.json"
                    )
                ).read_text()
            )
        )
        assert all(alive(pid) for pid in pids)
        code = terminate(proc, sig)
        assert code == (-sig if sig == signal.SIGKILL else 128 + sig)
        until(lambda: all(not alive(pid) for pid in pids), timeout=12)
        state = run_state.status(root)
        assert state["lifecycle"] == (
            "interrupted" if sig == signal.SIGKILL else "not_running"
        ), state
        assert not run_state.lock_held(root)
        if sig != signal.SIGKILL:
            assert state["last_run"]["outcome"] == "stopped"
        saved = schedule_state.read(root)
        slot = f"weekly:{END}" if mode == "model" else DAY
        claim = saved["claims"][slot]
        assert (
            claim["authorization_key"]
            == json.loads((root / "authorization.json").read_text())["key"]
        )
        if mode == "claim":
            (tmp_path / "resume-instance").write_text(str(root))
            restarted, _ = launch(tmp_path, "daily", now)
            try:
                assert until(lambda: outcome(root, slot))["status"] == "complete"
                assert schedule_state.read(root)["claims"][slot] == claim
            finally:
                terminate(restarted)
        elif mode == "model":
            before = len(list((root / "models").rglob("process/intent.json")))
            assert cli(root, "reconcile").returncode == 5
            assert len(list((root / "models").rglob("process/intent.json"))) == before
            (tmp_path / "resume-instance").write_text(str(root))
            restarted, _ = launch(tmp_path, "daily", now)
            try:
                assert until(lambda: outcome(root, slot))["status"] == "unknown"
                assert (
                    len(list((root / "models").rglob("process/intent.json"))) == before
                )
                assert schedule_state.read(root)["claims"][slot] == claim
            finally:
                terminate(restarted)
        elif mode == "provider":
            (tmp_path / "resume-instance").write_text(str(root))
            restarted, _ = launch(tmp_path, "daily", now)
            try:
                assert until(lambda: outcome(root, slot))["status"] == "complete"
                assert schedule_state.read(root)["claims"][slot] == claim
                with storage.open_store(root) as db:
                    events = [
                        json.loads(row[0])
                        for row in db.execute(
                            "SELECT content_json FROM documents WHERE kind='sync_receipt'"
                        )
                    ]
                calls = [
                    event
                    for event in events
                    if event.get("schema_version") == "fit_sync_budget_call_v1"
                ]
                assert sum(event["kind"] == "initialize" for event in calls) == 2
                assert sum(event["kind"] == "inventory" for event in calls) == 2
                assert len({event["job_key"] for event in calls}) == 1
            finally:
                terminate(restarted)
        with storage.open_store(root):
            pass
    finally:
        terminate(proc)
