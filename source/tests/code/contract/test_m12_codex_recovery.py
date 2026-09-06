from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
ledger = importlib.import_module("test_m12_model_job")
output_fixture = importlib.import_module("test_m12_codex_output")
PROMPT = b"Public synthetic request."


def module():
    return importlib.import_module("skills._shared.fit_weekly.codex_recovery")


def setup(tmp_path, *, value=None, process_error=None):
    from skills._shared.fit_weekly import (
        fit_detail,
        fit_sync,
        model_job,
        process_capture,
        storage,
    )
    from skills._shared.fit_weekly.model_process import ProcessResult

    args = list(ledger.setup(tmp_path))
    args[-1].profile.update(kind="model", name="codex")
    paths = {}

    def stopped(*_):
        with storage.open_store(args[0]) as db:
            identity, request = fit_detail.get(db, "model-job:" + args[1] + ":intent")
        work = model_job.capture_path(*args[:2]).parent / "codex"
        fit_sync.private_directory(work)
        paths["work"] = work / "process"
        paths["request"] = request
        rows = output_fixture.events({"ok": True} if value is None else value)
        result = ProcessResult(
            0 if process_error is None else 23,
            len(PROMPT),
            output_fixture.stream(rows),
            b"",
            process_error,
        )
        process_capture.run(
            paths["work"], process_capture.binding(PROMPT, identity), lambda: result
        )
        raise model_job.AdapterInterrupted("public crash after durable process")

    args[-1].run = stopped
    with pytest.raises(model_job.AdapterInterrupted):
        ledger.run(args)

    def forbidden(*_):
        raise AssertionError("recovery must not invoke adapter")

    args[-1].run = forbidden
    return args, paths


def resume(args, **kwargs):
    return module().resume(
        *args,
        prompt=kwargs.pop("prompt", PROMPT),
        validate_input=kwargs.pop("validate_input", ledger.valid_input),
        validate_result=kwargs.pop("validate_result", ledger.valid_result),
        **kwargs,
    )


def test_complete_raw_result_recovers_without_starting_adapter(tmp_path):
    args, paths = setup(tmp_path)
    assert ledger.run(args)["status"] == "unknown"
    raw_before = (paths["work"] / "capture.json").read_bytes()
    result = resume(args)
    assert result["status"] == "succeeded"
    assert result["result"] == {"ok": True}
    assert result["invocation_adapter_calls"] == args[-1].calls == 0
    assert result["receipt"]["adapter_attempts"] == 1
    assert result["receipt"]["model_attempts"] == 1
    assert result["receipt"]["provider_calls"] == 0
    assert result["receipt"]["external_actions"] == 0
    assert (paths["work"] / "capture.json").read_bytes() == raw_before
    db = args[0] / "trainlab-fit.db"
    before = db.read_bytes()
    assert resume(args) == result
    assert ledger.run(args)["receipt"] == result["receipt"]
    assert db.read_bytes() == before


def test_no_original_intent_cannot_be_created_by_recovery(tmp_path):
    args = ledger.setup(tmp_path)
    before = (args[0] / "trainlab-fit.db").read_bytes()
    assert resume(args)["status"] == "unknown"
    assert not ledger.capture_path(args).parent.exists()
    assert (args[0] / "trainlab-fit.db").read_bytes() == before
    assert args[-1].calls == 0


@pytest.mark.parametrize("kind", ["process", "wire", "business", "events"])
def test_confirmed_failure_is_closed_and_never_retried(tmp_path, kind):
    from skills._shared.fit_weekly import storage

    args, paths = setup(
        tmp_path,
        value={"ok": False} if kind == "wire" else None,
        process_error="process_exit_nonzero" if kind == "process" else None,
    )
    options: dict[str, Any] = {}
    if kind == "business":

        def invalid(*_):
            raise ValueError("public synthetic rejected business result")

        options["validate_result"] = invalid
    elif kind == "events":
        from skills._shared.fit_weekly import process_capture

        target = paths["work"] / "capture.json"
        value = json.loads(target.read_text())
        value["process"]["stdout"] = process_capture.encode_stream(b"bad events\n")
        target.write_text(storage.canonical(value))
    result = resume(args, **options)
    assert result["status"] == "failed" and result["result"] is None
    expected = "model_result_invalid" if kind == "business" else "model_adapter_failed"
    assert result["receipt"]["error_code"] == expected
    assert result["invocation_adapter_calls"] == 0
    assert resume(args, **options) == result


@pytest.mark.parametrize(
    "change",
    [
        "absent",
        "empty",
        "corrupt",
        "wide",
        "symlink",
        "hardlink",
        "intent",
        "binding",
        "sha",
        "unconfirmed",
        "extra",
    ],
)
def test_incomplete_or_invalid_capture_remains_unknown(tmp_path, change):
    from skills._shared.fit_weekly import storage

    args, paths = setup(tmp_path)
    target = paths["work"] / "capture.json"
    value = json.loads(target.read_text())
    if change == "absent":
        target.unlink()
    elif change == "empty":
        target.write_bytes(b"")
    elif change == "corrupt":
        target.write_bytes(b"{")
    elif change == "wide":
        target.chmod(0o644)
    elif change == "symlink":
        saved = target.with_name("saved")
        target.rename(saved)
        target.symlink_to(saved)
    elif change == "hardlink":
        os.link(target, target.with_name("linked"))
    elif change == "intent":
        (paths["work"] / "intent.json").unlink()
    elif change == "extra":
        (paths["work"] / "unexpected").touch(mode=0o600)
    else:
        if change == "binding":
            value["binding"]["request_sha256"] = "0" * 64
        elif change == "sha":
            value["process"]["stdout"]["sha256"] = "0" * 64
        else:
            value["process"]["process_stopped"] = False
            value["process"]["error_code"] = "process_stop_unconfirmed"
        target.write_text(storage.canonical(value))
    for _ in range(2):
        assert resume(args)["status"] == "unknown"
        assert not ledger.capture_path(args).exists()
        assert args[-1].calls == 0


@pytest.mark.parametrize("change", ["prompt", "payload", "schema", "scope", "profile"])
def test_input_drift_never_recovers_wrong_task(tmp_path, change):
    args, _ = setup(tmp_path)
    options: dict[str, Any] = {}
    if change == "prompt":
        options["prompt"] = PROMPT + b" changed"
        assert resume(args, **options)["status"] == "unknown"
    else:
        if change == "payload":
            args[3] = {"public": False}
            options["validate_input"] = lambda _: None
        elif change == "schema":
            args[4] = copy.deepcopy(args[4])
            args[4]["description"] = "changed"
        elif change == "scope":
            args[2] = "0" * 64
        else:
            args[-1].profile["configuration_sha256"] = "0" * 64
        with pytest.raises(ValueError):
            resume(args, **options)
    assert not ledger.capture_path(args).exists()
    assert args[-1].calls == 0


@pytest.mark.parametrize("stage", ["raw_barrier", "outer_before", "outer_after", "sql"])
def test_finite_persistence_failure_can_recover_without_second_model(
    tmp_path, monkeypatch, stage
):
    from skills._shared.fit_weekly import fit_detail, storage

    args, paths = setup(tmp_path)
    original = storage.atomic_file
    put = fit_detail.put
    outer = ledger.capture_path(args)

    def failing(path, data):
        if stage == "raw_barrier" and path == paths["work"] / "capture.json":
            raise OSError("public IO failure")
        if stage == "outer_before" and path == outer:
            raise OSError("public IO failure")
        original(path, data)
        if stage == "outer_after" and path == outer:
            raise OSError("public IO failure")

    def sql(db, key, *values):
        if key.endswith(":result"):
            raise OSError("public SQL failure")
        return put(db, key, *values)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "atomic_file", failing)
        if stage == "sql":
            patch.setattr(fit_detail, "put", sql)
        if stage == "raw_barrier":
            assert resume(args)["status"] == "unknown"
        else:
            with pytest.raises(ValueError, match="model_job_persistence_unavailable"):
                resume(args)
    result = resume(args)
    assert result["status"] == "succeeded"
    assert result["invocation_adapter_calls"] == args[-1].calls == 0


def test_relocated_instance_uses_same_business_binding(tmp_path):
    args, _ = setup(tmp_path)
    moved = tmp_path / "moved"
    shutil.copytree(args[0], moved)
    args[0] = moved
    assert resume(args)["status"] == "succeeded"
    assert args[-1].calls == 0


def test_existing_outer_failure_is_not_replaced_by_success_raw(tmp_path):
    args, _ = setup(tmp_path)

    def rejected(*_):
        raise ValueError("public business rejection")

    first = resume(args, validate_result=rejected)
    assert first["status"] == "failed"
    assert resume(args) == first


@pytest.mark.parametrize("stage", ["raw", "outer", "sql"])
def test_real_process_exit_during_recovery_then_local_resume(tmp_path, stage):
    import subprocess

    args, _ = setup(tmp_path)
    program = """
import os,sys,json
from pathlib import Path
from skills._shared.fit_weekly import codex_recovery,model_job,storage,fit_detail
root,end,scope,profile,stage=sys.argv[1:]
root=Path(root)
adapter=model_job.FakeAdapter({'ok':True},[])
adapter.profile=json.loads(profile)
adapter.run=lambda *args: os._exit(99)
original=storage.atomic_file
outer=model_job.capture_path(root,end)
def atomic(path,data):
    original(path,data)
    if stage=='raw' and path.name=='capture.json' and path.parent.name=='process':
        os._exit(37)
    if stage=='outer' and path==outer:
        os._exit(37)
storage.atomic_file=atomic
put=fit_detail.put
def save(db,key,*args):
    put(db,key,*args)
    if stage=='sql' and key.endswith(':result'):
        os._exit(37)
fit_detail.put=save
codex_recovery.resume(root,end,scope,{'public':True},
 {'type':'object','properties':{'ok':{'type':'boolean','const':True}},
  'required':['ok'],'additionalProperties':False},adapter,
 prompt=b'Public synthetic request.',validate_input=lambda _:None,
 validate_result=lambda *_:None)
"""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(args[0]),
            args[1],
            args[2],
            json.dumps(args[-1].profile),
            stage,
        ],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SOURCE)},
        capture_output=True,
        timeout=15,
    )
    assert done.returncode == 37, done.stderr.decode()
    result = resume(args)
    assert result["status"] == "succeeded"
    assert result["invocation_adapter_calls"] == args[-1].calls == 0
    assert resume(args) == result


def test_concurrent_recovery_does_not_duplicate_result(tmp_path):
    import concurrent.futures
    import threading

    from skills._shared.fit_weekly import storage

    args, _ = setup(tmp_path)
    ready = threading.Barrier(3)

    def recovering():
        ready.wait(timeout=5)
        try:
            return resume(args)
        except ValueError as exc:
            assert str(exc) in (
                "model_job_preflight_unavailable",
                "model_job_persistence_unavailable",
            )
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: recovering(), range(3)))
    result = resume(args)
    assert result["status"] == "succeeded"
    assert all(x is None or x["status"] in ("unknown", "succeeded") for x in results)
    assert args[-1].calls == 0
    with storage.open_store(args[0]) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM documents WHERE logical_key LIKE 'model-job:%:result'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "kind",
    ["schema", "prompt", "startup_list", "startup_duplicate", "startup_empty", "input"],
)
def test_invalid_configuration_never_reads_recovery_or_creates_intent(
    tmp_path, monkeypatch, kind
):
    from skills._shared.fit_weekly import process_capture

    args = list(ledger.setup(tmp_path))
    options: dict[str, Any] = {}
    if kind == "schema":
        args[4] = {"type": "object"}
    elif kind == "prompt":
        options["prompt"] = b""
    elif kind == "startup_list":
        options["startup_messages"] = ["public diagnostic"]
    elif kind == "startup_duplicate":
        options["startup_messages"] = ("public diagnostic", "public diagnostic")
    elif kind == "startup_empty":
        options["startup_messages"] = ("",)
    else:
        args[3] = {"public": False}
    reads = []

    def forbidden(*_):
        reads.append(True)
        raise AssertionError("no evidence read before preflight")

    monkeypatch.setattr(process_capture, "read_terminal", forbidden)
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        resume(args, **options)
    assert reads == [] and args[-1].calls == 0
    assert not ledger.capture_path(args).parent.exists()
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("change", ["empty", "corrupt", "wide", "symlink", "result"])
def test_invalid_outer_capture_never_falls_back_to_raw(tmp_path, monkeypatch, change):
    from skills._shared.fit_weekly import process_capture, storage

    args, _ = setup(tmp_path)
    assert resume(args)["status"] == "succeeded"
    target = ledger.capture_path(args)
    if change == "empty":
        target.write_bytes(b"")
    elif change == "corrupt":
        target.write_bytes(b"{")
    elif change == "wide":
        target.chmod(0o644)
    elif change == "symlink":
        prior = target.with_name("prior.json")
        target.rename(prior)
        target.symlink_to(prior)
    else:
        value = json.loads(target.read_text())
        value["output"] = {"ok": False}
        target.write_text(storage.canonical(value))
    reads = []
    monkeypatch.setattr(process_capture, "read_terminal", lambda *_: reads.append(True))
    with pytest.raises(ValueError, match="model_capture_invalid"):
        resume(args)
    assert reads == [] and args[-1].calls == 0


@pytest.mark.parametrize("value", [None, {}, "public error", 1])
def test_invalid_generic_reader_result_does_not_publish(tmp_path, value):
    from skills._shared.fit_weekly import model_job

    args, _ = setup(tmp_path)
    result = model_job.recover(
        *args,
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
        read_completed=lambda _: value,
    )
    assert result["status"] == "unknown"
    assert not ledger.capture_path(args).exists()


def test_shared_request_constructor_is_exact_old_ledger_binding(tmp_path):
    from skills._shared.fit_weekly import model_job

    args, paths = setup(tmp_path)
    request, _ = model_job.prepare_request(
        *args[1:5],
        args[-1].profile,
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert request == paths["request"]
    request["payload"]["public"] = False
    assert args[3]["public"] is True


@pytest.mark.parametrize("recovering", [False, True])
def test_profile_property_error_is_redacted_before_io(tmp_path, recovering):
    from skills._shared.fit_weekly import model_job

    args = list(ledger.setup(tmp_path))

    class Bad:
        @property
        def profile(self):
            raise RuntimeError("synthetic-private-profile@example.invalid")

        def run(self, *_):
            raise AssertionError("unreachable")

    args[-1] = Bad()
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="^model_job_input_invalid$"):
        if recovering:
            model_job.recover(
                *args,
                validate_input=ledger.valid_input,
                validate_result=ledger.valid_result,
                read_completed=lambda _: None,
            )
        else:
            ledger.run(args)
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "wide"])
def test_codex_parent_directory_is_private_and_not_a_redirect(tmp_path, kind):
    args, paths = setup(tmp_path)
    parent = paths["work"].parent
    if kind == "symlink":
        outside = tmp_path / "outside-codex"
        parent.rename(outside)
        parent.symlink_to(outside, target_is_directory=True)
    else:
        parent.chmod(0o755)
    assert resume(args)["status"] == "unknown"
    assert not ledger.capture_path(args).exists()
