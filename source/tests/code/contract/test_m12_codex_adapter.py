from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
ledger = importlib.import_module("test_m12_model_job")
boundary_fixture = importlib.import_module("test_m12_codex_boundary")
output_fixture = importlib.import_module("test_m12_codex_output")


def module():
    return importlib.import_module("skills._shared.fit_weekly.command_adapter")


def public_proof(runtime):
    from skills._shared.fit_weekly import (
        codex_output,
        command_capability,
        model_process,
        process_capture,
    )

    body = boundary_fixture.packet()
    body["instructions"] = runtime.instructions
    body["model"] = runtime.settings.get("model", "public-default")
    body["reasoning"] = {"summary": "auto"}
    body["input"][-1]["content"][0]["text"] = command_capability.PROMPT
    body["text"] = {"format": codex_output.response_format(command_capability.SCHEMA)}
    result = model_process.ProcessResult(
        0, len(command_capability.PROMPT.encode()), b'{"ok":true}', b"", None
    )
    failed = replace(
        result, returncode=1, stdout=b"", error_code="process_exit_nonzero"
    )
    return {
        "schema_version": "fit_command_capability_v1",
        "runtime": runtime.identity(),
        "cwd": "/public/job",
        "initial_request": body,
        "process": process_capture.encode(
            result, command_capability.binding(runtime.identity())
        ),
        "handoffs": [],
        "refusals": {
            **command_capability.CODEX_REFUSALS,
            "outside_scope": '{"status":"unavailable","error_code":"detail_activity_outside_scope","provider_calls":0}',
            "over_range": '{"status":"unavailable","error_code":"detail_request_invalid","provider_calls":0}',
            "stage_scope": '{"status":"unavailable","error_code":"detail_stage_forbidden","provider_calls":0}',
            "over_budget": '{"status":"unavailable","error_code":"detail_budget_exceeded","provider_calls":0}',
        },
        "retry_processes": {
            mode: process_capture.encode(
                failed, command_capability.binding(runtime.identity())
            )
            for mode in ("http_error", "stream_error")
        },
        "retry_requests": {
            mode: [copy.deepcopy(body)] for mode in ("http_error", "stream_error")
        },
        "budget_scope_checks": {},
    }


def complete_probe(proof, tmp_path):
    from skills._shared.fit_weekly import (
        detail_transport,
        fit_detail,
        fit_parse,
        storage,
    )

    fixture = importlib.import_module("test_m12_fit_detail")
    time_factory = importlib.import_module("m12_fit_time_factory")
    factory = importlib.import_module("m12_fit_factory")
    probe_root = tmp_path / "probe-data"
    probe_root.mkdir(mode=0o700)
    data = factory.file_bytes(
        [
            time_factory.summary(elapsed_ms=1800417, timer_ms=1800417),
            *[factory.record(t, t * 3, 120) for t in range(1801)],
        ]
    )
    root, end, members = fixture.instance(probe_root, data)
    other_data = factory.file_bytes(
        [
            time_factory.summary(elapsed_ms=1800417, timer_ms=1800417, sport=2),
            *[factory.record(t, t * 3, 120) for t in range(1801)],
        ]
    )
    other = probe_root / "other.fit"
    storage.atomic_file(other, other_data)
    other_sha = storage.digest(other_data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "202", other, other_sha)
        fit_parse.parse_registered(db, root, "202", other_sha)
    members.append({"activity_ref": "202", "fit_sha256": other_sha})
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(
        root, end, scope["scope_sha256"], stage=proof["runtime"]["stage"]
    )
    requests = [fixture.request(end_offset_seconds=1200, resolution_seconds=1)] * 2 + [
        fixture.request(
            start_offset_seconds=1800, end_offset_seconds=1800.417, resolution_seconds=1
        )
    ]
    proof["handoffs"] = []
    for request in requests:
        value = host.read(request)
        proof["handoffs"].append(
            {
                "request": request,
                "host_result": value,
                "model_output": json.dumps(detail_transport.pack(value)),
                "charged_requests": host.usage()["requests"],
            }
        )

    def receipt(request, reader):
        value = reader.read(request)
        return {
            "request": request,
            "host_result": value,
            "model_output": json.dumps(detail_transport.pack(value)),
            "charged_requests": reader.usage()["requests"],
        }

    stage_handoff = None
    if proof["runtime"]["stage"] == "summary":
        stage_handoff = receipt(fixture.request(activity_ref="202"), host)
        proof["refusals"]["stage_scope"] = stage_handoff["model_output"]
    summary = fit_detail.DetailHost(root, end, scope["scope_sha256"], stage="summary")
    fill = [
        receipt(
            fixture.request(
                start_offset_seconds=n, end_offset_seconds=n + 1, resolution_seconds=1
            ),
            summary,
        )
        for n in range(1, 21 - host.usage()["requests"])
    ]
    proof["budget_scope_checks"] = {
        "stage_handoff": stage_handoff,
        "fill_handoffs": fill,
        "cache_handoff": receipt(requests[0], summary),
    }
    proof["requests"] = [copy.deepcopy(proof["initial_request"])]
    for index, output in enumerate(
        [x["model_output"] for x in proof["handoffs"]]
        + list(proof["refusals"].values())
    ):
        packet = copy.deepcopy(proof["initial_request"])
        packet["input"].append(
            {
                "type": "function_call_output",
                "call_id": f"call_{index}",
                "output": output,
            }
        )
        proof["requests"].append(packet)
    return proof


def setup(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import codex_isolation, model_process, storage

    args = ledger.setup(tmp_path)
    home = tmp_path / "public-home"
    home.mkdir(mode=0o700)
    (home / ".codex").mkdir(mode=0o700)
    executable = tmp_path / "public-codex"
    executable.write_bytes(b"public executable fixture")
    executable.chmod(0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    from skills._shared.fit_weekly import command_runtime

    runtime = module().Runtime(
        command_spec=command_runtime.CommandSpec("codex", executable),
        source=SOURCE,
        instructions="Public Host instructions.",
        prompt_prefix="Public weekly input:\n",
        settings=command_runtime.environment_settings("codex"),
    )
    from skills._shared.fit_weekly import command_runtime

    proof = public_proof(runtime)
    # Complete transfer/refusal evidence is supplied by the focused fixture below.
    proof = complete_probe(proof, tmp_path)
    proof_path = tmp_path / "public-capability.json"
    storage.atomic_file(proof_path, storage.canonical(proof).encode())
    calls = []

    def isolate(**kw):
        return codex_isolation.Isolation(
            "Darwin", home, home / ".codex", kw["work"], (), ("/public/isolate",)
        )

    monkeypatch.setattr(codex_isolation, "prepare", isolate)

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return model_process.ProcessResult(
            0,
            len(kwargs["prompt"]),
            b'{"ok":true}',
            b"",
            None,
        )

    monkeypatch.setattr(model_process, "execute", execute)
    return args, runtime, proof_path, calls


def prepare(args, runtime, proof):
    return module().prepare(
        *args[:5],
        runtime=runtime,
        capability_path=proof,
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )


def execute(args, adapter):
    return ledger.run((*args[:5], adapter))


def test_prepare_launch_capture_and_replay_one_interface(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import model_job, storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    assert calls == []
    with storage.open_store(args[0]) as db:
        assert not db.execute(
            "SELECT 1 FROM documents WHERE logical_key LIKE 'model-job:%'"
        ).fetchall()
    result = execute(args, adapter)
    assert result["status"] == "succeeded"
    assert result["result"] == {"ok": True}
    assert len(calls) == 1
    assert result["receipt"]["model_attempts"] == 1
    assert result["receipt"]["provider_calls"] == 0
    work = model_job.capture_path(*args[:2], stage="plan").parent / "command"
    assert (work / "prepared.json").stat().st_mode & 0o777 == 0o600
    assert (work / "process/capture.json").is_file()
    argv, options = calls[0]
    assert argv[:3] == ["/public/isolate", str(runtime.executable), "exec"]
    for flag in (
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
    ):
        assert flag in argv
    assert "resume" not in argv and argv[-1] == "-"
    assert "read-only" in argv
    assert options["prompt"] == b'Public weekly input:\n{"public":true}'
    assert options["cwd"] == work / "job"
    assert options["timeout"] == runtime.timeout_seconds
    assert adapter._spec["runtime"]["timeout_seconds"] == runtime.timeout_seconds
    before = (args[0] / "trainlab-fit.db").read_bytes()
    assert execute(args, adapter)["invocation_adapter_calls"] == 0
    assert len(calls) == 1
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_expiration_during_capture_preparation_stops_before_model_process(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import process_capture, publication_ledger, storage

    args, initial, path, calls = setup(tmp_path, monkeypatch)
    runtime = replace(initial, authorization_expires_utc="2026-08-09T07:00:01Z")
    probe = tmp_path / "expiry-proof"
    probe.mkdir(mode=0o700)
    proof = complete_probe(public_proof(runtime), probe)
    path.write_text(storage.canonical(proof))
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: "2026-08-09T07:00:00Z")
    adapter = prepare(args, runtime, path)
    capture = process_capture.run

    def crossed_deadline(*a, **kw):
        monkeypatch.setattr(
            publication_ledger, "utc_now", lambda: "2026-08-09T07:00:01Z"
        )
        return capture(*a, **kw)

    monkeypatch.setattr(process_capture, "run", crossed_deadline)
    result = execute(args, adapter)
    assert result["status"] == "failed"
    assert calls == []
    captured = json.loads((adapter.work / "process/capture.json").read_text())
    assert captured["process"]["error_code"] == "process_authorization_expired"


def test_environment_inherits_auth_but_not_python_or_shell_injection(
    tmp_path, monkeypatch
):
    for key in ("PYTHONPATH", "BASH_ENV", "CODEX_SQLITE_HOME"):
        monkeypatch.setenv(key, "PUBLIC_POISON")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-public-key")
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    execute(args, adapter)
    env = calls[0][1]["env"]
    assert "PUBLIC_POISON" not in env.values()
    assert env["OPENAI_API_KEY"] == "synthetic-public-key"
    assert "synthetic-public-key" not in json.dumps(adapter._spec)


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "wide",
        "symlink",
        "changed_binary",
        "schema",
        "input",
        "proof",
        "tools",
        "packages",
    ],
)
def test_bad_preflight_no_intent_or_process(tmp_path, monkeypatch, kind):
    from skills._shared.fit_weekly import storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    args = list(args)
    if kind == "missing":
        proof.unlink()
    elif kind == "wide":
        proof.chmod(0o644)
    elif kind == "symlink":
        moved = proof.with_suffix(".original")
        proof.rename(moved)
        proof.symlink_to(moved)
    elif kind == "changed_binary":
        runtime.executable.write_bytes(b"changed public binary")
    elif kind == "packages":
        from skills._shared.fit_weekly import command_runtime

        monkeypatch.setattr(
            command_runtime, "version", lambda _: "public-different-version"
        )
    elif kind == "schema":
        args[4] = {"$ref": "https://example.invalid/forbidden"}
    elif kind == "input":
        args[3] = {"gps": "public forbidden field"}
    else:
        value = json.loads(proof.read_text())
        if kind == "proof":
            value["refusals"]["shell"] = "executed"
        else:
            value["initial_request"]["tools"].append({"name": "shell"})
        proof.write_text(storage.canonical(value))
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        prepare(args, runtime, proof)
    assert calls == []
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize(
    "kind",
    ["binary", "instructions", "schema_file", "prompt_file", "prepared", "effort"],
)
def test_launch_refuses_prepared_drift(tmp_path, monkeypatch, kind):
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    targets = {
        "binary": runtime.executable,
        "instructions": adapter.work / "instructions.txt",
        "schema_file": adapter.work / "response.schema.json",
        "prompt_file": adapter.work / "prompt.txt",
        "prepared": adapter.work / "prepared.json",
    }
    if kind == "effort":
        (Path(os.environ["HOME"]) / ".codex/config.toml").write_text(
            'model_reasoning_effort="low"\n'
        )
    else:
        targets[kind].write_bytes(b"public changed bytes")
    with pytest.raises(ValueError, match="model_job_preflight_unavailable"):
        execute(args, adapter)
    from skills._shared.fit_weekly import fit_detail, stage_policy, storage

    with storage.open_store(args[0]) as db:
        assert (
            fit_detail.get(db, stage_policy.job_key(args[1], "plan") + ":intent")
            is None
        )
        assert (
            fit_detail.get(db, stage_policy.job_key(args[1], "plan") + ":result")
            is None
        )
    assert calls == []
    assert not (adapter.work / "process").exists()


def test_interrupted_after_process_recovers_from_original_materials(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import command_output, model_job

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    parse = command_output.parse_result

    def crash(*a, **kw):
        from skills._shared.fit_weekly import command_capability

        if kw["prompt_bytes"] == len(command_capability.PROMPT.encode()):
            return parse(*a, **kw)
        raise model_job.AdapterInterrupted("public crash after raw persistence")

    monkeypatch.setattr(command_output, "parse_result", crash)
    with pytest.raises(model_job.AdapterInterrupted):
        execute(args, adapter)
    monkeypatch.setattr(command_output, "parse_result", parse)
    # Recovery must not need a current executable, proof, global HOME or login.
    runtime.executable.unlink()
    proof.unlink()
    monkeypatch.setenv("HOME", "/public/now-unavailable")
    result = module().recover(
        *args[:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    assert result["invocation_adapter_calls"] == 0
    assert (
        module().recover(
            *args[:5],
            stage="plan",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )
        == result
    )


def test_relocation_recovery_and_schema_drift(tmp_path, monkeypatch):
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    execute(args, adapter)
    moved = tmp_path / "moved-instance"
    shutil.copytree(args[0], moved)
    result = module().recover(
        moved,
        *args[1:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    wrong = copy.deepcopy(args[4])
    wrong["properties"]["ok"]["const"] = False
    with pytest.raises(ValueError):
        module().recover(
            moved,
            *args[1:4],
            wrong,
            stage="plan",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )
    assert len(calls) == 1


def test_incomplete_prepared_never_restarts(tmp_path, monkeypatch):
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    execute(args, adapter)
    (adapter.work / "prepared.json").unlink()
    result = module().recover(
        *args[:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "unknown" and len(calls) == 1


def test_capability_without_observed_tool_lifecycle_is_not_proof(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import command_capability, process_capture, storage
    from skills._shared.fit_weekly.model_process import ProcessResult

    args, runtime, path, calls = setup(tmp_path, monkeypatch)
    proof = json.loads(path.read_text())
    result = ProcessResult(
        0,
        len(command_capability.PROMPT.encode()),
        output_fixture.stream(output_fixture.events({"ok": True})),
        b"",
        None,
    )
    proof["process"] = process_capture.encode(
        result, command_capability.binding(runtime.identity())
    )
    path.write_text(storage.canonical(proof))
    with pytest.raises(ValueError):
        prepare(args, runtime, path)
    assert calls == []


def test_command_inherits_default_without_product_model_override(tmp_path, monkeypatch):
    args, runtime, _, _ = setup(tmp_path, monkeypatch)
    argv = runtime.command(*args[:3], tmp_path / "work")
    config = dict(
        x.split("=", 1) for i, x in enumerate(argv) if i and argv[i - 1] == "-c"
    )
    assert "-m" not in argv and "model" not in config
    assert json.loads(config["model_provider"]) == "trainlab_environment"
    assert (
        json.loads(config["model_providers.trainlab_environment.request_max_retries"])
        == 0
    )
    assert (
        json.loads(config["model_providers.trainlab_environment.stream_max_retries"])
        == 0
    )


@pytest.mark.parametrize(
    "kind",
    [
        "short_transcript",
        "missing_refusal",
        "different_tool",
        "lossy_handoff",
        "cache_charge",
        "wrong_resolution",
        "retry",
        "unconfirmed",
        "failed_turn",
        "wrong_host_request",
        "short_host_result",
        "budget_missing_receipt",
        "budget_wrong_charge",
        "native_tool_expansion",
    ],
)
def test_capability_checks_retained_evidence_not_flags(tmp_path, monkeypatch, kind):
    from skills._shared.fit_weekly import command_capability, process_capture, storage

    args, runtime, path, calls = setup(tmp_path, monkeypatch)
    proof = json.loads(path.read_text())
    if kind == "short_transcript":
        proof["requests"].pop()
    elif kind == "missing_refusal":
        proof["requests"][5]["input"][-1]["output"] = "success"
    elif kind == "different_tool":
        proof["requests"][1]["tools"][0]["name"] = "exec_command"
    elif kind == "lossy_handoff":
        proof["handoffs"][0]["model_output"] = "{}"
    elif kind == "cache_charge":
        proof["handoffs"][1]["charged_requests"] = 2
    elif kind == "wrong_resolution":
        proof["handoffs"][0]["request"]["resolution_seconds"] = 5
    elif kind == "native_tool_expansion":
        proof["initial_request"]["input"].insert(
            0,
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {
                        "type": "namespace",
                        "name": "functions",
                        "tools": [{"type": "custom", "name": "apply_patch"}],
                    }
                ],
            },
        )
    elif kind == "budget_missing_receipt":
        proof["budget_scope_checks"]["fill_handoffs"].pop()
    elif kind == "budget_wrong_charge":
        proof["budget_scope_checks"]["fill_handoffs"][0]["charged_requests"] = 1
    elif kind == "retry":
        proof["retry_requests"]["http_error"].append(proof["initial_request"])
    elif kind == "unconfirmed":
        proof["process"]["process"]["process_stopped"] = False
        proof["process"]["process"]["error_code"] = "process_stop_unconfirmed"
    elif kind in ("wrong_host_request", "short_host_result"):
        from skills._shared.fit_weekly import detail_transport

        for i in (0, 1):
            value = proof["handoffs"][i]["host_result"]
            if kind == "wrong_host_request":
                value["activity_ref"] = "202"
            else:
                value["blocks"] = value["blocks"][:60]
            text = json.dumps(detail_transport.pack(value), separators=(",", ":"))
            proof["handoffs"][i]["model_output"] = text
            proof["requests"][i + 1]["input"][-1]["output"] = text
    else:
        result = process_capture.decode(
            proof["process"], command_capability.binding(runtime.identity())
        )
        from dataclasses import replace

        bad = (
            result.stdout
            + b'{"type":"turn.failed","error":{"message":"public failure"}}\n'
        )
        proof["process"] = process_capture.encode(
            replace(result, stdout=bad), command_capability.binding(runtime.identity())
        )
    path.write_text(storage.canonical(proof))
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        prepare(args, runtime, path)
    assert calls == [] and before == (args[0] / "trainlab-fit.db").read_bytes()


@pytest.mark.parametrize("point", ["prepared", "intent", "capture", "outer"])
def test_finite_write_failure_never_repeats_child(tmp_path, monkeypatch, point):
    from skills._shared.fit_weekly import model_job, storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    original = storage.atomic_file

    def fail(path, raw):
        selected = {
            "prepared": path.name == "prepared.json",
            "intent": path.name == "intent.json" and path.parent.name == "process",
            "capture": path.name == "capture.json" and path.parent.name == "process",
            "outer": path.name == "capture.json" and path.parent.name != "process",
        }
        if selected[point]:
            raise OSError("public finite write failure")
        return original(path, raw)

    if point == "prepared":
        monkeypatch.setattr(storage, "atomic_file", fail)
        with pytest.raises(ValueError):
            prepare(args, runtime, proof)
        assert calls == []
        return
    adapter = prepare(args, runtime, proof)
    monkeypatch.setattr(storage, "atomic_file", fail)
    with pytest.raises((ValueError, model_job.AdapterInterrupted)):
        execute(args, adapter)
    monkeypatch.setattr(storage, "atomic_file", original)
    result = module().recover(
        *args[:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == ("succeeded" if point == "outer" else "unknown")
    assert len(calls) == (0 if point == "intent" else 1)
    execute(args, adapter)
    assert len(calls) == (0 if point == "intent" else 1)


def test_supervised_child_uses_private_umask_without_changing_parent(tmp_path):
    from skills._shared.fit_weekly import model_process

    script = "import sys; from pathlib import Path; sys.stdin.buffer.read(); Path('new').mkdir(); Path('new/log').write_text('public')"
    previous = os.umask(0o022)
    try:
        result = model_process.execute(
            [sys.executable, "-c", script],
            prompt=b"public",
            env={"PATH": os.environ["PATH"]},
            cwd=tmp_path,
        )
        assert result.error_code is None
        assert (tmp_path / "new").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "new/log").stat().st_mode & 0o777 == 0o600
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(previous)


@pytest.mark.parametrize("changed_prompt", [False, True])
def test_concurrent_prepare_cannot_mix_frozen_materials(
    tmp_path, monkeypatch, changed_prompt
):
    from skills._shared.fit_weekly import command_capability, process_capture, storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    second_runtime = (
        replace(runtime, prompt_prefix="Another public input:\n")
        if changed_prompt
        else runtime
    )
    second_proof = json.loads(proof.read_text())
    process = process_capture.decode(
        second_proof["process"], command_capability.binding(runtime.identity())
    )
    for mode, raw in second_proof["retry_processes"].items():
        captured = process_capture.decode(
            raw, command_capability.binding(runtime.identity())
        )
        second_proof["retry_processes"][mode] = process_capture.encode(
            captured, command_capability.binding(second_runtime.identity())
        )
    second_proof["runtime"] = second_runtime.identity()
    second_proof["process"] = process_capture.encode(
        process, command_capability.binding(second_runtime.identity())
    )
    second_path = tmp_path / "other-public-proof.json"
    storage.atomic_file(second_path, storage.canonical(second_proof).encode())
    waiting, release = threading.Event(), threading.Event()
    original = os.rename
    outcome = {}

    def pause(src, dst, *a, **kw):
        if (
            threading.current_thread().name == "first-prepare"
            and Path(dst).name == "prepared.json"
        ):
            waiting.set()
            assert release.wait(60)
        return original(src, dst, *a, **kw)

    def first():
        try:
            outcome["adapter"] = prepare(args, runtime, proof)
        except BaseException as exc:
            outcome["error"] = exc

    monkeypatch.setattr(os, "rename", pause)
    worker = threading.Thread(target=first, name="first-prepare")
    worker.start()
    rejected = False
    try:
        assert waiting.wait(60)
        try:
            prepare(args, second_runtime, second_path)
        except ValueError as exc:
            assert str(exc) == "command_preparation_invalid"
            rejected = True
    finally:
        release.set()
        worker.join(60)
    assert not worker.is_alive()
    assert rejected and "error" not in outcome
    adapter = outcome["adapter"]
    module().verify_files(adapter.work, adapter._spec)
    assert calls == []
    assert execute(args, adapter)["status"] == "succeeded"
    before = (args[0] / "trainlab-fit.db").read_bytes()
    result = module().recover(
        *args[:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_stage_identity_prepare_and_recovery_cannot_cross_stage(tmp_path, monkeypatch):
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    assert execute(args, adapter)["status"] == "succeeded"
    summary_runtime = replace(runtime, stage="summary")
    assert summary_runtime.identity() != runtime.identity()
    with pytest.raises(ValueError, match="command_preparation_invalid"):
        module().prepare(
            *args[:5],
            runtime=summary_runtime,
            capability_path=proof,
            stage="summary",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )
    from skills._shared.fit_weekly import model_job

    wrong = model_job.capture_path(*args[:2], stage="summary").parent / "command"
    wrong.parent.mkdir(mode=0o700)
    shutil.copytree(adapter.work, wrong)
    assert (
        module().recover(
            *args[:5],
            stage="summary",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )["status"]
        == "unknown"
    )
    assert len(calls) == 1
    assert execute(args, adapter)["status"] == "succeeded" and len(calls) == 1


def test_legacy_tool_capability_recovers_stopped_capture_but_cannot_start_new_runtime(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import (
        codex_adapter,
        codex_boundary,
        codex_runtime,
        fit_parse,
        fit_sync,
        model_job,
        model_process,
        process_capture,
        storage,
    )

    old = importlib.import_module("m12_legacy_command_factory")
    current_packet = boundary_fixture.packet
    tools = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_cli_tools.json").read_text()
    )
    monkeypatch.setattr(
        codex_boundary, "TOOL_SURFACE_SHA256", codex_boundary.LEGACY_TOOL_SURFACE_SHA256
    )
    monkeypatch.setattr(
        boundary_fixture, "packet", lambda: {**current_packet(), "tools": tools}
    )
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-1")
    args = ledger.setup(tmp_path)
    executable = tmp_path / "retired-executable"
    executable.write_bytes(b"retired-public-binary")
    executable.chmod(0o700)
    runtime = codex_runtime.Runtime(
        executable,
        SOURCE,
        "historical-model",
        "file",
        "Public Host instructions.",
        "Public weekly input:\n",
    )
    proof = old.complete_probe(old.public_proof(runtime), tmp_path)
    request, _ = model_job.prepare_request(
        *args[1:5],
        codex_adapter.profile(runtime.identity(), proof),
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
        stage="plan",
    )
    spec = {
        "schema_version": "fit_codex_prepared_v1",
        "request": request,
        "runtime": runtime.identity(),
        "capability": proof,
        "instructions": runtime.instructions,
        "prompt_prefix": runtime.prompt_prefix,
    }
    adapter = codex_adapter.CodexAdapter(args[0], spec, None)
    for folder in (adapter.work.parent.parent, adapter.work.parent, adapter.work):
        fit_sync.private_directory(folder)
    for name, raw in codex_adapter.files(spec).items():
        storage.atomic_file(adapter.work / name, raw)
    prompt = codex_adapter.files(spec)["prompt.txt"]

    def historical_stopped(*_):
        result = model_process.ProcessResult(
            0,
            len(prompt),
            output_fixture.stream(output_fixture.events({"ok": True})),
            b"",
            None,
        )
        process_capture.run(
            adapter.work / "process",
            process_capture.binding(prompt, model_job.sha(request)),
            lambda: result,
        )
        raise model_job.AdapterInterrupted("synthetic historical stopped capture")

    monkeypatch.setattr(adapter, "run", historical_stopped)
    with pytest.raises(model_job.AdapterInterrupted):
        execute(args, adapter)
    monkeypatch.undo()
    before = {
        p: storage.digest(p.read_bytes())
        for p in adapter.work.rglob("*")
        if p.is_file()
    }
    with pytest.raises(ValueError, match="legacy_command_readonly"):
        codex_adapter.prepare()
    with pytest.raises(ValueError, match="legacy_command_readonly"):
        runtime.command()
    result = module().recover(
        *args[:5],
        stage="plan",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and result["invocation_adapter_calls"] == 0
    assert all(storage.digest(p.read_bytes()) == sha for p, sha in before.items())
    assert (
        module().recover(
            *args[:5],
            stage="plan",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )
        == result
    )


def test_replacing_command_preserves_success_and_shared_detail_budget(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import (
        command_runtime,
        fit_detail,
        model_job,
        storage,
    )

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    host = fit_detail.DetailHost(*args[:3], stage="plan")
    first = host.read(
        ledger.fixture.request(
            start_offset_seconds=0, end_offset_seconds=1, resolution_seconds=1
        )
    )
    assert execute(args, adapter)["status"] == "succeeded"
    saved = model_job.capture_path(*args[:2], stage="plan").read_bytes()
    executable = tmp_path / "replacement-command"
    executable.write_bytes(b"second public command")
    executable.chmod(0o700)
    replacement = replace(
        runtime,
        command_spec=command_runtime.CommandSpec("codex", executable),
        stage="summary",
    )
    area = tmp_path / "replacement-proof"
    area.mkdir(mode=0o700)
    new_proof = area / "proof.json"
    storage.atomic_file(
        new_proof,
        storage.canonical(complete_probe(public_proof(replacement), area)).encode(),
    )
    summary = module().prepare(
        *args[:5],
        runtime=replacement,
        capability_path=new_proof,
        stage="summary",
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert ledger.run((*args[:5], summary), stage="summary")["status"] == "succeeded"
    assert model_job.capture_path(*args[:2], stage="plan").read_bytes() == saved
    assert execute(args, adapter)["invocation_adapter_calls"] == 0
    second_host = fit_detail.DetailHost(*args[:3], stage="summary")
    assert (
        second_host.read(
            ledger.fixture.request(
                start_offset_seconds=0, end_offset_seconds=1, resolution_seconds=1
            )
        )
        == first
    )
    assert second_host.usage()["requests"] == 1
    second_host.read(
        ledger.fixture.request(
            start_offset_seconds=1, end_offset_seconds=2, resolution_seconds=1
        )
    )
    assert host.usage()["requests"] == 2
    assert len(calls) == 2
    assert runtime.command_spec.key != replacement.command_spec.key


def test_native_default_selection_is_audited_without_product_override(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import command_capability

    _, runtime, path, _ = setup(tmp_path, monkeypatch)
    proof = json.loads(path.read_text())
    for packet in [proof["initial_request"], *proof["requests"]]:
        packet["reasoning"] = {"effort": "low", "context": "all_turns"}
        packet["text"]["verbosity"] = "low"
    command_capability.validate(proof, runtime.identity(), runtime.instructions)
    proof["initial_request"]["reasoning"]["context"] = "arbitrary ambient content"
    with pytest.raises(ValueError, match="command_capability_invalid"):
        command_capability.validate(proof, runtime.identity(), runtime.instructions)


@pytest.mark.parametrize("status", ["succeeded", "unknown"])
def test_existing_attempt_ignores_current_environment_drift(
    tmp_path, monkeypatch, status
):
    from skills._shared.fit_weekly import model_job, model_process

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    if status == "unknown":

        def interrupted(*args, **kwargs):
            calls.append((args, kwargs))
            raise model_job.AdapterInterrupted("Public uncertain process")

        monkeypatch.setattr(model_process, "execute", interrupted)
        with pytest.raises(model_job.AdapterInterrupted):
            execute(args, adapter)
    else:
        assert execute(args, adapter)["status"] == status
    before = (args[0] / "trainlab-fit.db").read_bytes()
    (Path(os.environ["HOME"]) / ".codex/config.toml").write_text(
        'model_reasoning_effort="low"\n'
    )
    for result in (
        execute(args, adapter),
        module().recover(
            *args[:5],
            stage="plan",
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        ),
    ):
        assert result["status"] == status
        assert result["invocation_adapter_calls"] == 0
    assert len(calls) == 1
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_drift_after_intent_keeps_claim_and_stops_launch(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import fit_detail, stage_policy, storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    original = fit_detail.put
    key = stage_policy.job_key(args[1], "plan") + ":intent"

    def change_after_claim(db, logical_key, *rest):
        original(db, logical_key, *rest)
        if logical_key == key:
            (Path(os.environ["HOME"]) / ".codex/config.toml").write_text(
                'model_reasoning_effort="low"\n'
            )

    monkeypatch.setattr(fit_detail, "put", change_after_claim)
    result = execute(args, adapter)
    assert result["status"] == "failed"
    assert result["receipt"]["model_attempts"] == 1
    with storage.open_store(args[0]) as db:
        assert fit_detail.get(db, key) is not None
    assert calls == []
    assert not (adapter.work / "process").exists()


@pytest.mark.parametrize("target", ["job", "logs", "sqlite", "tmp"])
@pytest.mark.parametrize("mutation", ["mode", "symlink", "missing"])
def test_real_launch_dependencies_rejected_before_intent(
    tmp_path, monkeypatch, target, mutation
):
    from skills._shared.fit_weekly import codex_isolation

    real_isolation = codex_isolation.prepare
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(codex_isolation, "prepare", real_isolation)
    adapter = prepare(args, runtime, proof)
    path = adapter.work / target
    if mutation == "mode":
        path.chmod(0o755)
    elif mutation == "symlink":
        moved = adapter.work / (target + "-original")
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
    else:
        path.rmdir()
    before = (args[0] / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="model_job_preflight_unavailable"):
        execute(args, adapter)
    assert (args[0] / "trainlab-fit.db").read_bytes() == before
    assert calls == []
    assert not (adapter.work / "process").exists()
