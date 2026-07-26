from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import importlib.util

import pytest

from trainlab.foundation_sample import generate_sample_database
from trainlab import garmin_smoke_runtime as runtime
from trainlab.garmin_smoke_runtime import SmokeRuntimeError, SmokeRuntimeRequest, _window, run_smoke

ROOT = Path(__file__).resolve().parents[1]


def receipt(mode: str, start: str | None, through: str | None, status: str = "succeeded", number: int = 1, counts: dict | None = None) -> dict:
    return {"schema_version":"1", "run_id":None if mode in {"auth","status"} else f"gr-00000000-0000-4000-8000-{number:012x}", "mode":mode, "status":status, "requested_range":{"from":start if mode == "full" else None,"through":through}, "effective_range":{"from":start,"through":through}, "coverage_state":"partial" if mode == "snapshot" else "complete", "counts":counts or {"fetched":0,"empty":0,"unchanged":0,"revised":0,"failed":0,"deferred":0,"not_available":0,"not_enabled":0}, "complete_through_by_resource":{}, "open_gap_count":0, "next_retry_at_utc":None, "errors":[], "started_at_utc":"2026-07-24T00:00:00Z", "completed_at_utc":"2026-07-24T00:00:01Z"}


def setup(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True); root = tmp_path / "project"; root.mkdir(mode=0o700)
    generate_sample_database(root / "foundation-shadow")
    tokens = tmp_path / "tokens"; tokens.mkdir(mode=0o700)
    (tokens / "token").write_text("x"); os.chmod(tokens / "token", 0o600)
    return root, tokens


def request(root: Path, tokens: Path, **changes: object) -> SmokeRuntimeRequest:
    values: dict[str, object] = dict(isolated_root=root, production_token_store=tokens, approved_from="2026-07-22", approved_through="2026-07-23", invocation_ids=tuple(f"inv-{i:032x}" for i in range(8)), production_garmin_config=ROOT / "config/garmin.yaml", authorization_id="authz-" + "a" * 32, approved_modes=("auth","incremental","snapshot","repair","audit","status"), bounded_activity_window_authorized=True, e04_backup_receipt_sha256="b" * 64, operator_registered=True, shadow_attested=True, canonical_owner_unchanged=True)
    values.update(changes); return SmokeRuntimeRequest(**values)  # type: ignore[arg-type]


def fake(calls: list[list[str]]):
    number = 0
    def run(command, **_kwargs):
        nonlocal number
        calls.append(command); payload = json.loads(Path(command[-1]).read_text()); mode = payload["mode"]; actual = payload["request"]
        start = None if mode in {"auth","status"} else (actual["health_from_local_date"] or actual["snapshot_local_date"] or payload["config"]["approved_from"])
        through = None if mode in {"auth","status"} else (actual["through_local_date"] or actual["snapshot_local_date"])
        number += 1
        return type("Result", (), {"stdout": json.dumps(receipt(mode, start, through, number=number)) + "\n", "returncode": 0})()
    return run


def test_clone_order_cleanup_and_safe_publish(tmp_path: Path):
    root, tokens = setup(tmp_path); calls: list[list[str]] = []
    shadow_before = (root / "foundation-shadow/data.db").read_bytes()
    config_before = (ROOT / "config/garmin.yaml").read_bytes()
    result = run_smoke(request(root, tokens), execute=fake(calls))
    published = root / "smoke-result"
    assert result["status"] == "succeeded" and len(calls) == 8
    assert published.is_dir() and not list(published.rglob("secrets/garmin"))
    assert (published / "receipts/01.json").stat().st_mode & 0o777 == 0o600
    assert not list(root.glob(".smoke-*"))
    assert (root / "foundation-shadow/data.db").read_bytes() == shadow_before
    assert (ROOT / "config/garmin.yaml").read_bytes() == config_before
    operations = json.loads((published / "operations.json").read_text())
    assert operations["repeat_no_op"] is True and operations["snapshot_cursor_unchanged"] is True
    assert operations["incremental_repeat_no_op"] is True and operations["snapshot_repeat_no_op"] is True
    assert operations["snapshot_cursor_before_sha256"] == operations["snapshot_cursor_after_sha256"]
    assert operations["operations"][1]["request_sha256"] == operations["operations"][2]["request_sha256"]
    assert operations["operations"][3]["request_sha256"] == operations["operations"][4]["request_sha256"]
    assert operations["operations"][2]["no_op"] is True
    assert operations["operations"][4]["no_op"] is True
    assert "errors" not in json.loads((published / "receipts/05.json").read_text())


def test_authz_missing_does_not_copy_token(tmp_path: Path):
    root, tokens = setup(tmp_path)
    with pytest.raises(SmokeRuntimeError, match="smoke_authorization_incomplete"):
        run_smoke(request(root, tokens, bounded_activity_window_authorized=False), execute=lambda *_a, **_k: None)
    assert not list(root.rglob("secrets/garmin"))


def test_symlink_and_malicious_receipt_fail_without_result(tmp_path: Path):
    root, tokens = setup(tmp_path); shutil.rmtree(root / "foundation-shadow/raw"); (root / "foundation-shadow/raw").symlink_to(tmp_path)
    with pytest.raises(SmokeRuntimeError): run_smoke(request(root, tokens), execute=lambda *_a, **_k: None)
    root, tokens = setup(tmp_path / "again")
    def bad(command, **_kwargs):
        payload = json.loads(Path(command[-1]).read_text()); return type("R", (), {"stdout": json.dumps(receipt(payload["mode"], None, None, "succeeded") | {"run_id":"raw-token"}) + "\n", "returncode": 0})()
    with pytest.raises(SmokeRuntimeError): run_smoke(request(root, tokens), execute=bad)
    assert not (root / "smoke-result").exists() and not list(root.glob(".smoke-*"))


def test_window_and_retry_after_failure(tmp_path: Path):
    assert _window("2026-07-22", "2026-08-04") == 14
    root, tokens = setup(tmp_path)
    with pytest.raises(SmokeRuntimeError): run_smoke(request(root, tokens, approved_through="2026-08-05"), execute=lambda *_a, **_k: None)
    root, tokens = setup(tmp_path / "retry")
    with pytest.raises(SmokeRuntimeError): run_smoke(request(root, tokens), execute=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("unknown")))
    assert not list(root.glob(".smoke-*")) and not (root / "smoke-result").exists()


def test_fixed_bounded_sequence_has_no_full_and_shares_approved_start(tmp_path: Path):
    root, tokens = setup(tmp_path); calls: list[list[str]] = []
    run_smoke(request(root, tokens, approved_from="2026-07-20", approved_through="2026-08-02"), execute=fake(calls))
    payloads = [json.loads(path.read_text()) for path in sorted((root / "smoke-result").glob("request-*.json"))]
    assert [payload["mode"] for payload in payloads] == ["auth", "incremental", "incremental", "snapshot", "snapshot", "repair", "audit", "status"]
    assert all(payload["mode"] != "full" for payload in payloads)
    incrementals = [payload for payload in payloads if payload["mode"] == "incremental"]
    assert all(payload["request"]["through_local_date"] == "2026-08-02" and payload["config"]["history_start_date"] == "2026-07-20" and payload["config"]["approved_from"] == "2026-07-20" for payload in incrementals)
    snapshots = [payload for payload in payloads if payload["mode"] == "snapshot"]
    assert all(payload["request"]["snapshot_local_date"] == "2026-08-02" for payload in snapshots)


def test_worker_refuses_tampered_full_payload(tmp_path: Path):
    payload = tmp_path / "full.json"; payload.write_text(json.dumps({"mode": "full"}))
    with pytest.raises(ValueError, match="smoke_mode_forbidden"):
        runtime._worker(payload)


def test_activity_transport_allows_only_bounded_list_calls():
    calls: list[tuple[str, str]] = []
    class Delegate:
        def list_activities(self, start: str, through: str) -> list[object]:
            calls.append((start, through)); return []
    transport = runtime._BoundedSmokeTransport(Delegate(), "2026-07-20", "2026-08-02")
    assert transport.list_activities("2026-07-20", "2026-08-02") == []
    assert calls == [("2026-07-20", "2026-08-02")]
    with pytest.raises(RuntimeError, match="unbounded_activity_inventory_forbidden"):
        transport.activity_count()
    with pytest.raises(RuntimeError, match="unbounded_activity_inventory_forbidden"):
        transport.activity_page(0, 100)
    with pytest.raises(RuntimeError, match="activity_window_outside_approval"):
        transport.list_activities(None, "2026-08-02")


def test_progress_reports_all_stages_durations_and_total_elapsed(tmp_path: Path):
    root, tokens = setup(tmp_path); events: list[dict[str, object]] = []; tick = -1
    def clock() -> float:
        nonlocal tick
        tick += 1; return float(tick)
    result = run_smoke(request(root, tokens), execute=fake([]), monotonic=clock, progress=events.append)
    assert [event["event"] for event in events] == [value for _ in range(8) for value in ("stage_started", "stage_completed")] + ["smoke_completed"]
    completed = [event for event in events if event["event"] == "stage_completed"]
    assert [event["stage_index"] for event in completed] == list(range(1, 9))
    assert all(event["duration_seconds"] == 1.0 and event["status"] == "succeeded" for event in completed)
    assert all(
        set(
            (
                "fetched_count",
                "unchanged_count",
                "revised_count",
                "failed_count",
                "deferred_count",
            )
        )
        <= set(event)
        for event in completed
    )
    assert result["total_elapsed_seconds"] == 17.0
    operations = json.loads((root / "smoke-result/operations.json").read_text())
    assert operations["total_elapsed_seconds"] == 17.0
    assert all(item["duration_seconds"] == 1.0 for item in operations["operations"])


def test_progress_failure_is_safe_and_cli_keeps_stdout_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root, tokens = setup(tmp_path); events: list[dict[str, object]] = []
    with pytest.raises(SmokeRuntimeError):
        run_smoke(request(root, tokens), execute=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret /private/path")), progress=events.append)
    assert [event["event"] for event in events] == ["stage_started", "stage_failed"]
    assert "secret" not in json.dumps(events) and "path" not in json.dumps(events)

    spec = importlib.util.spec_from_file_location("run_garmin_smoke_test", ROOT / "scripts/run_garmin_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    args = ["run_garmin_smoke", "--isolated-root", str(root), "--production-token-store", str(tokens), "--production-garmin-config", str(ROOT / "config/garmin.yaml"), "--from-date", "2026-07-22", "--through-date", "2026-07-23", "--authorization-id", "authz-" + "a" * 32, "--e04-backup-receipt-sha256", "b" * 64, "--operator-registered", "--shadow-attested", "--canonical-owner-unchanged", "--bounded-activity-window-authorized"]
    for index in range(8): args.extend(["--invocation-id", f"inv-{index:032x}"])
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(module, "run_smoke", lambda _request, progress: (progress({"event": "smoke_completed", "total_elapsed_seconds": 1.0}) or {"status": "succeeded", "total_elapsed_seconds": 1.0}))
    assert module.main() == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ['{"status": "succeeded", "total_elapsed_seconds": 1.0}']
    assert captured.err.splitlines() == ['{"event":"smoke_completed","total_elapsed_seconds":1.0}']
    monkeypatch.setattr(module, "run_smoke", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret /private/path")))
    assert module.main() == 2
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ['{"code": "smoke_runtime_failed", "status": "failed"}']
    assert len(captured.err.splitlines()) == 1 and "secret" not in captured.err and "path" not in captured.err
    monkeypatch.setattr(
        module,
        "run_smoke",
        lambda *_a, **_k: (_ for _ in ()).throw(
            SmokeRuntimeError("safe_but_not_whitelisted")
        ),
    )
    assert module.main() == 2
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        '{"code": "smoke_runtime_failed", "status": "failed"}'
    ]
    assert '"code":"smoke_runtime_failed"' in captured.err


def test_non_success_receipt_emits_failed_not_completed(tmp_path: Path):
    root, tokens = setup(tmp_path); events: list[dict[str, object]] = []
    def partial(command, **_kwargs):
        payload = json.loads(Path(command[-1]).read_text())
        mode = payload["mode"]
        return type("R", (), {
            "stdout": json.dumps(receipt(mode, None, None, status="partial")) + "\n",
            "returncode": 10,
        })()
    with pytest.raises(SmokeRuntimeError, match="operation_not_succeeded"):
        run_smoke(request(root, tokens), execute=partial, progress=events.append)
    assert [event["event"] for event in events] == ["stage_started", "stage_failed"]
    assert events[-1]["status"] == "partial"
    assert events[-1]["failed_count"] == 0
    assert events[-1]["deferred_count"] == 0
    assert events[-1]["error_codes"] == []
    assert all(set(item) == {"resource", "code", "count", "status"} for item in events[-1]["gap_breakdown"])
    assert all(set(item) == {"resource", "code", "count"} for item in events[-1]["failed_item_breakdown"])
    assert events[-1]["breakdown_truncated"] is False
    assert "errors" not in events[-1]


def test_duplicate_run_id_and_repeat_mutation_are_rejected(tmp_path: Path):
    root, tokens = setup(tmp_path)
    def duplicate(command, **_kwargs):
        payload = json.loads(Path(command[-1]).read_text()); mode = payload["mode"]
        actual = payload["request"]; start = None if mode in {"auth", "status"} else (actual["health_from_local_date"] or actual["snapshot_local_date"] or payload["config"]["approved_from"]); through = None if mode in {"auth", "status"} else (actual["through_local_date"] or actual["snapshot_local_date"])
        return type("R", (), {"stdout": json.dumps(receipt(mode, start, through, number=1)) + "\n", "returncode": 0})()
    with pytest.raises(SmokeRuntimeError, match="receipt_run_id_duplicate"):
        run_smoke(request(root, tokens), execute=duplicate)
    root, tokens = setup(tmp_path / "repeat")
    calls: list[list[str]] = []; ordinary = fake(calls)
    def changed_repeat(command, **kwargs):
        result = ordinary(command, **kwargs)
        if len(calls) == 3:
            value = json.loads(result.stdout); value["counts"]["fetched"] = 1; result.stdout = json.dumps(value) + "\n"
        return result
    with pytest.raises(SmokeRuntimeError, match="repeat_not_no_op"):
        events: list[dict[str, object]] = []
        run_smoke(
            request(root, tokens),
            execute=changed_repeat,
            progress=events.append,
        )
    assert events[-1]["event"] == "validation_failed"
    assert events[-1]["gate"] == "repeat_no_op"
    assert events[-1]["incremental_no_op"] is False
    assert events[-1]["snapshot_no_op"] is True
    assert not (root / "smoke-result").exists()


def test_real_timeout_kills_and_reaps_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    killed: list[int] = []; original = runtime.os.killpg
    def observe(pid: int, sig: int) -> None:
        killed.append(pid); original(pid, sig)
    monkeypatch.setattr(runtime.os, "killpg", observe)
    with pytest.raises(SmokeRuntimeError, match="child_timeout"):
        runtime._run_child([sys.executable, "-c", "import time; time.sleep(3)"], tmp_path, 1)
    assert killed


def test_child_exception_also_kills_and_reaps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    events: list[str] = []
    class BrokenProcess:
        pid = 12345; returncode = None
        def poll(self): return None
        def communicate(self, timeout=None):
            events.append("communicate")
            if len(events) == 1: raise OSError("pipe failure")
            return "", ""
        def wait(self): events.append("wait"); return -9
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_a, **_k: BrokenProcess())
    monkeypatch.setattr(runtime.os, "killpg", lambda *_a: events.append("kill"))
    with pytest.raises(SmokeRuntimeError, match="child_execution_failed"):
        runtime._run_child(["irrelevant"], tmp_path, 1)
    assert events == ["communicate", "kill", "communicate", "wait"]


def test_actual_request_is_validated_before_worker_and_publish_scans_token_hashes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root, tokens = setup(tmp_path); calls: list[object] = []
    original_request = runtime._request
    monkeypatch.setattr(runtime, "_request", lambda *_args: {"mode": "auth"})
    with pytest.raises(SmokeRuntimeError, match="request_schema_invalid"):
        run_smoke(request(root, tokens), execute=lambda *_a, **_k: calls.append(1))
    assert not calls
    monkeypatch.setattr(runtime, "_request", original_request)
    root, tokens = setup(tmp_path / "scan"); calls2: list[list[str]] = []; ordinary = fake(calls2)
    def copied_token(command, **kwargs):
        result = ordinary(command, **kwargs)
        if len(calls2) == 1:
            (Path(kwargs["cwd"]) / "leak.bin").write_text("x")
        return result
    with pytest.raises(SmokeRuntimeError, match="published_token_copy"):
        run_smoke(request(root, tokens), execute=copied_token)

    root, tokens = setup(tmp_path / "benign-name")
    calls3: list[list[str]] = []
    ordinary_benign = fake(calls3)
    def benign_tokenized_filename(command, **kwargs):
        result = ordinary_benign(command, **kwargs)
        if len(calls3) == 1:
            (Path(kwargs["cwd"]) / "tokenization-metadata.json").write_text(
                "provider metadata only"
            )
        return result
    succeeded = run_smoke(
        request(root, tokens),
        execute=benign_tokenized_filename,
    )
    assert succeeded["status"] == "succeeded"
    assert (
        root / "smoke-result/tokenization-metadata.json"
    ).read_text() == "provider metadata only"

    root, tokens = setup(tmp_path / "symlink")
    calls4: list[list[str]] = []
    ordinary_symlink = fake(calls4)
    def linked_token_directory(command, **kwargs):
        result = ordinary_symlink(command, **kwargs)
        if len(calls4) == 1:
            (Path(kwargs["cwd"]) / "innocent-alias").symlink_to(
                tokens,
                target_is_directory=True,
            )
        return result
    with pytest.raises(SmokeRuntimeError, match="published_sensitive_path"):
        run_smoke(
            request(root, tokens),
            execute=linked_token_directory,
        )
    assert not (root / "smoke-result").exists()

    root, tokens = setup(tmp_path / "similar-path")
    calls5: list[list[str]] = []
    ordinary_similar = fake(calls5)
    def similar_but_not_credential_path(command, **kwargs):
        result = ordinary_similar(command, **kwargs)
        if len(calls5) == 1:
            directory = (
                Path(kwargs["cwd"])
                / "foundation/state/secrets/garmin-metadata"
            )
            directory.mkdir()
            (directory / "marker.json").write_text("metadata")
        return result
    succeeded = run_smoke(
        request(root, tokens),
        execute=similar_but_not_credential_path,
    )
    assert succeeded["status"] == "succeeded"
    assert (
        root
        / "smoke-result/foundation/state/secrets/garmin-metadata/marker.json"
    ).read_text() == "metadata"
