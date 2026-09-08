from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
fixture = importlib.import_module("test_m12_fit_detail")


def module():
    return importlib.import_module("skills._shared.fit_weekly.model_job")


def setup(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, members = fixture.instance(tmp_path)
    scope = fit_detail.freeze_scope(root, end, members)
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean", "const": True}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    adapter = module().FakeAdapter({"ok": True}, [fixture.request()])
    return root, end, scope["scope_sha256"], {"public": True}, schema, adapter


def valid_input(body):
    assert body == {"public": True}


def valid_result(body, context):
    valid_input(context)
    assert body == {"ok": True}


def run(args, **kwargs):
    return module().run(
        *args,
        stage=kwargs.pop("stage", "plan"),
        validate_input=kwargs.pop("validate_input", valid_input),
        validate_result=kwargs.pop("validate_result", valid_result),
        **kwargs,
    )


def capture_path(args):
    return module().capture_path(args[0], args[1], stage="plan")


def legacy_saved(
    root, end, scope, payload, schema, adapter, *, validate_input, validate_result
):
    """Manufacture public saved v1 evidence; not an executable legacy entrypoint.

    Only history-reading tests use this fixture. Execution/crash/concurrency
    regressions use the current parameterized ledger above.
    """
    from skills._shared.fit_weekly import fit_detail, fit_sync, storage

    assert isinstance(adapter, module().FakeAdapter)
    request, validator = module().prepare_request(
        end,
        scope,
        payload,
        schema,
        adapter.profile,
        validate_input=validate_input,
        validate_result=validate_result,
    )
    output = adapter.run(payload, fit_detail.DetailHost(root, end, scope), schema)
    capture = module().checked_result(request, output, None, validator, validate_result)
    path = module().capture_path(root, end)
    fit_sync.private_directory(path.parent.parent)
    fit_sync.private_directory(path.parent)
    storage.atomic_file(path, storage.canonical(capture).encode())
    with storage.open_store(root) as db:
        fit_detail.put(
            db, "model-job:" + end + ":intent", module().sha(request), request
        )
        fit_detail.put(
            db, "model-job:" + end + ":result", module().sha(request), capture
        )
    return module().outcome(capture, 1)


def test_success_same_interface_detail_no_long_store_lock_and_replay(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    args = setup(tmp_path)
    first = run(args)
    assert first["status"] == "succeeded"
    assert first["result"] == {"ok": True}
    assert first["receipt"]["adapter_kind"] == "fake"
    assert first["receipt"]["adapter_attempts"] == 1
    assert first["receipt"]["model_attempts"] == 0
    assert first["receipt"]["provider_calls"] == 0
    assert first["receipt"]["external_actions"] == 0
    assert first["invocation_adapter_calls"] == 1
    assert args[-1].calls == 1
    assert fit_detail.DetailHost(*args[:3]).usage()["requests"] == 1
    before = (args[0] / "trainlab-fit.db").read_bytes()
    second = run(args)
    assert second["receipt"] == first["receipt"]
    assert second["result"] == first["result"]
    assert second["invocation_adapter_calls"] == 0
    assert args[-1].calls == 1
    assert before == (args[0] / "trainlab-fit.db").read_bytes()


@pytest.mark.parametrize("change", ["payload", "schema", "profile", "scope"])
def test_same_week_changed_inputs_never_grant_second_attempt(tmp_path, change):
    args = list(setup(tmp_path))
    run(args)
    if change == "payload":
        args[3] = {"public": False}
    elif change == "schema":
        args[4] = {"type": "object"}
    elif change == "scope":
        args[2] = "f" * 64
    else:
        args[5] = module().FakeAdapter({"ok": False}, [])
    with pytest.raises(ValueError):
        run(args, validate_input=lambda _: None)
    assert args[5].calls == (0 if change == "profile" else 1)


@pytest.mark.parametrize("change", ["input", "schema", "scope", "profile"])
def test_preflight_failure_has_no_intent_or_adapter_call(tmp_path, change):
    from skills._shared.fit_weekly import storage

    args = list(setup(tmp_path))
    if change == "input":
        args[3] = {"gps": "synthetic forbidden"}
    elif change == "schema":
        args[4] = {"$ref": "https://example.invalid/no-network"}
    elif change == "scope":
        args[2] = "0" * 64
    else:
        args[-1].profile["unapproved"] = "value"
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        run(args)
    assert args[-1].calls == 0
    assert (args[0] / "trainlab-fit.db").read_bytes() == before
    assert not capture_path(args).exists()
    with storage.open_store(args[0]) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM documents WHERE logical_key LIKE 'model-job:%'"
            ).fetchone()[0]
            == 0
        )


def test_intent_visible_before_adapter_and_concurrent_caller_does_not_restart(tmp_path):
    from skills._shared.fit_weekly import storage

    args = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = args[-1].run

    def waiting(*values):
        with storage.open_store(args[0]) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM documents WHERE logical_key LIKE 'model-job:%:intent'"
                ).fetchone()[0]
                == 1
            )
        entered.set()
        assert release.wait(5)
        return original(*values)

    args[-1].run = waiting
    outputs = []
    worker = threading.Thread(target=lambda: outputs.append(run(args)))
    worker.start()
    try:
        assert entered.wait(5)
        pending = run(args)
        assert pending["status"] == "unknown"
        assert pending["invocation_adapter_calls"] == 0
    finally:
        release.set()
        worker.join(5)
    assert len(outputs) == 1 and outputs[0]["status"] == "succeeded"
    assert args[-1].calls == 1


@pytest.mark.parametrize("when", ["intent", "capture"])
def test_real_process_exit_then_recovery_never_runs_adapter_twice(tmp_path, when):
    import subprocess

    args = setup(tmp_path)
    child = """
import os,sys
from pathlib import Path
from skills._shared.fit_weekly import model_job, storage
root,end,scope,when=sys.argv[1:]
adapter=model_job.FakeAdapter({'ok':True},[])
if when=='intent':
    adapter.run=lambda *args: os._exit(23)
else:
    old=storage.atomic_file
    def crash(path,data):
        old(path,data)
        os._exit(23)
    storage.atomic_file=crash
model_job.run(Path(root),end,scope,{'public':True},
 {'type':'object','properties':{'ok':{'type':'boolean','const':True}},'required':['ok'],'additionalProperties':False},
 adapter,stage="plan",validate_input=lambda _:None,validate_result=lambda *_:None)
"""
    # Use the same adapter profile in both processes.
    args[-1].requests = []
    args[-1].profile = module().FakeAdapter({"ok": True}, []).profile
    done = subprocess.run(
        [sys.executable, "-c", child, str(args[0]), args[1], args[2], when],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SOURCE)},
        timeout=15,
        capture_output=True,
    )
    assert done.returncode == 23, done.stderr.decode()
    result = run(args)
    assert result["status"] == ("unknown" if when == "intent" else "succeeded")
    assert result["invocation_adapter_calls"] == args[-1].calls == 0


@pytest.mark.parametrize("failure", ["adapter", "schema", "business"])
def test_failure_is_durable_redacted_and_not_retried(tmp_path, failure):
    args = setup(tmp_path)
    opts = {}
    if failure == "adapter":

        def fail(*_):
            raise RuntimeError("synthetic-private-address@example.invalid")

        args[-1].run = fail
    elif failure == "schema":
        args[-1].output = {"ok": False}
    else:

        def reject(*_):
            raise ValueError("synthetic-private-secret")

        opts["validate_result"] = reject
    first = run(args, **opts)
    assert first["status"] == "failed" and first["result"] is None
    second = run(args, **opts)
    assert first["receipt"] == second["receipt"]
    assert second["invocation_adapter_calls"] == 0
    text = capture_path(args).read_text()
    assert "synthetic-private" not in text
    assert json.loads(text)["output"] == (
        {"ok": False}
        if failure == "schema"
        else {"ok": True}
        if failure == "business"
        else None
    )


@pytest.mark.parametrize("failure", ["capture_write", "directory_fsync", "sqlite"])
def test_finite_persistence_failure_retains_intent_and_only_local_recovery(
    tmp_path, monkeypatch, failure
):
    from skills._shared.fit_weekly import fit_detail, storage

    args = setup(tmp_path)
    original_atomic, original_put = storage.atomic_file, fit_detail.put
    with monkeypatch.context() as patch:
        if failure == "sqlite":

            def fail_result(db, key, *rest):
                if key.endswith(":result") and key.startswith("model-job:"):
                    raise sqlite3.OperationalError("synthetic disk failure")
                return original_put(db, key, *rest)

            patch.setattr(fit_detail, "put", fail_result)
        else:

            def fail_capture(path, data):
                if failure == "directory_fsync":
                    original_atomic(path, data)
                raise OSError("synthetic disk failure")

            patch.setattr(storage, "atomic_file", fail_capture)
        with pytest.raises(ValueError, match="model_job_persistence_unavailable"):
            run(args)
    assert args[-1].calls == 1
    result = run(args)
    assert result["status"] == (
        "unknown" if failure == "capture_write" else "succeeded"
    )
    assert result["invocation_adapter_calls"] == 0 and args[-1].calls == 1


@pytest.mark.parametrize(
    "damage",
    [
        "empty",
        "json",
        "request",
        "output",
        "duplicate",
        "permission",
        "symlink",
        "hardlink",
    ],
)
def test_capture_damage_never_restarts_or_returns_success(tmp_path, damage):
    args = setup(tmp_path)
    run(args)
    path = capture_path(args)
    if damage == "empty":
        path.write_bytes(b"")
    elif damage == "json":
        path.write_text("{")
    elif damage == "permission":
        path.chmod(0o644)
    elif damage in ("symlink", "hardlink"):
        saved = path.with_suffix(".saved")
        path.rename(saved)
        if damage == "symlink":
            path.symlink_to(saved)
        else:
            os.link(saved, path)
    elif damage == "duplicate":
        text = path.read_text()
        path.write_text('{"output":{},' + text[1:])
    else:
        body = json.loads(path.read_text())
        if damage == "request":
            body["receipt"]["request_sha256"] = "f" * 64
        else:
            body["output"] = {"ok": False}
        path.write_text(json.dumps(body))
    with pytest.raises(ValueError):
        run(args)
    assert args[-1].calls == 1


def test_moved_instance_has_identical_receipt_and_no_database_increment(tmp_path):
    args = list(setup(tmp_path))
    first = run(args)
    relocated = tmp_path / "relocated"
    shutil.copytree(args[0], relocated)
    args[0] = relocated
    before = (relocated / "trainlab-fit.db").read_bytes()
    result = run(args)
    assert result["receipt"] == first["receipt"]
    assert result["invocation_adapter_calls"] == 0
    assert (relocated / "trainlab-fit.db").read_bytes() == before
    assert str(tmp_path) not in capture_path(args).read_text()


def test_unconfirmed_adapter_interruption_keeps_unknown_not_false_failure(tmp_path):
    args = setup(tmp_path)

    def interrupted(*_):
        raise module().AdapterInterrupted()

    args[-1].run = interrupted
    with pytest.raises(module().AdapterInterrupted):
        run(args)
    assert not capture_path(args).exists()
    assert run(args)["status"] == "unknown"


def test_adapter_cannot_mutate_frozen_request_and_receipt_payload(tmp_path):
    args = setup(tmp_path)
    original_payload, original_schema = copy.deepcopy(args[3]), copy.deepcopy(args[4])
    original = args[-1].run

    def changed(payload, host, schema):
        payload.clear()
        schema.clear()
        return original(payload, host, schema)

    args[-1].run = changed
    result = run(args)
    assert result["status"] == "succeeded"
    assert args[3] == original_payload and args[4] == original_schema


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "$ref": "#/$defs/missing"},
        {"type": "object", "properties": {"ok": {"$ref": "#/$defs/missing"}}},
        {"type": "object", "$defs": {"unused": {"$ref": "https://example.invalid/no"}}},
        False,
    ],
)
def test_invalid_schema_references_are_rejected_before_reservation(tmp_path, schema):
    args = list(setup(tmp_path))
    args[4] = schema
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="model_job_input_invalid"):
        run(args)
    assert args[-1].calls == 0
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_intent_write_failure_does_not_start_adapter_or_leak_error(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import fit_detail

    args = setup(tmp_path)
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with monkeypatch.context() as patch:

        def fail(*_):
            raise sqlite3.OperationalError("synthetic-private-path")

        patch.setattr(fit_detail, "put", fail)
        with pytest.raises(ValueError, match="^model_job_preflight_unavailable$"):
            run(args)
    assert args[-1].calls == 0
    assert (args[0] / "trainlab-fit.db").read_bytes() == before
    assert run(args)["status"] == "succeeded"


def test_recovered_capture_barrier_failure_does_not_publish_terminal(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import fit_detail, storage

    args = setup(tmp_path)
    original_put = fit_detail.put
    with monkeypatch.context() as patch:

        def fail_result(db, key, *rest):
            if key.startswith("model-job:") and key.endswith(":result"):
                raise sqlite3.OperationalError("synthetic fail")
            return original_put(db, key, *rest)

        patch.setattr(fit_detail, "put", fail_result)
        with pytest.raises(ValueError, match="model_job_persistence_unavailable"):
            run(args)
    with monkeypatch.context() as patch:

        def fail_barrier(*_):
            raise OSError("synthetic fail")

        patch.setattr(storage, "atomic_file", fail_barrier)
        with pytest.raises(ValueError, match="model_job_persistence_unavailable"):
            run(args)
    with storage.open_store(args[0]) as db:
        assert fit_detail.get(db, "model-job:" + args[1] + ":plan:result") is None
    assert args[-1].calls == 1
    assert run(args)["status"] == "succeeded"


def test_missing_capture_after_terminal_never_uses_database_only_success(tmp_path):
    args = setup(tmp_path)
    run(args)
    path = capture_path(args)
    path.rename(path.with_suffix(".saved"))
    with pytest.raises(ValueError, match="model_capture_invalid"):
        run(args)
    assert args[-1].calls == 1


def test_mandatory_validators_cannot_be_omitted(tmp_path):
    args = setup(tmp_path)
    with pytest.raises(TypeError):
        module().run(*args)
    with pytest.raises(ValueError, match="model_job_input_invalid"):
        run(args, validate_result=None)
    assert args[-1].calls == 0
