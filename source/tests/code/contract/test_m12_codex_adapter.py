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
    return importlib.import_module("skills._shared.fit_weekly.codex_adapter")


def public_proof(runtime):
    from skills._shared.fit_weekly import (
        codex_capability,
        codex_output,
        process_capture,
    )
    from skills._shared.fit_weekly.model_process import ProcessResult

    body = boundary_fixture.packet()
    body["instructions"] = runtime.instructions
    body["model"] = runtime.model
    body["input"][-1]["content"][0]["text"] = codex_capability.PROMPT
    body["text"] = {"format": codex_output.response_format(codex_capability.SCHEMA)}
    events = output_fixture.stream(output_fixture.events({"ok": True}))
    result = ProcessResult(0, len(codex_capability.PROMPT.encode()), events, b"", None)
    return {
        "schema_version": "fit_codex_capability_v1",
        "runtime": runtime.identity(),
        "cwd": "/public/job",
        "initial_request": body,
        "process": process_capture.encode(
            result, codex_capability.binding(runtime.identity())
        ),
        "startup_messages": [],
        "refusals": dict(codex_capability.REFUSALS),
        "handoffs": [],
    }


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
    runtime = module().Runtime(
        executable=executable,
        source=SOURCE,
        model="public-model",
        credential_store="file",
        instructions="Public Host instructions.",
        prompt_prefix="Public weekly input:\n",
    )
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
            output_fixture.stream(output_fixture.events({"ok": True})),
            b"",
            None,
        )

    monkeypatch.setattr(model_process, "execute", execute)
    return args, runtime, proof_path, calls


def complete_probe(proof, tmp_path):
    from skills._shared.fit_weekly import (
        codex_capability,
        detail_transport,
        fit_detail,
        model_job,
        process_capture,
    )
    from skills._shared.fit_weekly.model_process import ProcessResult

    fixture = importlib.import_module("test_m12_fit_detail")
    probe_root = tmp_path / "probe-data"
    probe_root.mkdir(mode=0o700)
    root, end, members = fixture.instance(probe_root)
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    proof["handoffs"] = []
    for resolution in (1, 1, 5, 5):
        request = fixture.request(
            end_offset_seconds=1200, resolution_seconds=resolution
        )
        value = host.read(request)
        proof["handoffs"].append(
            {
                "request": request,
                "host_result": value,
                "model_output": json.dumps(
                    detail_transport.pack(value), separators=(",", ":")
                ),
                "charged_requests": host.usage()["requests"],
            }
        )
    assert model_job.sha(proof["handoffs"][0]["host_result"]) == model_job.sha(
        proof["handoffs"][1]["host_result"]
    )
    rows = output_fixture.events({"ok": True})
    tool_events = []
    for i, item in enumerate(proof["handoffs"]):
        pair = output_fixture.call(item_id=f"detail-{i}")
        for event in pair:
            event["item"]["arguments"] = item["request"]
        tool_events.extend(pair)
    for i, server in enumerate(("fit", "unconfigured")):
        pair = output_fixture.call(
            item_id=f"refusal-{i}", tool="read_mcp_resource", server=server, failed=True
        )
        for event in pair:
            event["item"]["arguments"] = {
                "server": server,
                "uri": "file:///public-sentinel",
            }
        pair[-1]["item"]["error"]["message"] = list(codex_capability.REFUSALS.values())[
            i + 1
        ]
        tool_events.extend(pair)
    rows[2:2] = tool_events
    result = ProcessResult(
        0, len(codex_capability.PROMPT.encode()), output_fixture.stream(rows), b"", None
    )
    proof["process"] = process_capture.encode(
        result, codex_capability.binding(proof["runtime"])
    )
    proof["requests"] = [copy.deepcopy(proof["initial_request"])]
    for i, output in enumerate(
        [
            *(x["model_output"] for x in proof["handoffs"]),
            *codex_capability.REFUSALS.values(),
        ]
    ):
        request = copy.deepcopy(proof["initial_request"])
        request["input"].append(
            {"type": "function_call_output", "call_id": f"call_{i}", "output": output}
        )
        proof["requests"].append(request)
    return proof


def prepare(args, runtime, proof):
    return module().prepare(
        *args[:5],
        runtime=runtime,
        capability_path=proof,
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
    work = model_job.capture_path(*args[:2]).parent / "codex"
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
    before = (args[0] / "trainlab-fit.db").read_bytes()
    assert execute(args, adapter)["invocation_adapter_calls"] == 0
    assert len(calls) == 1
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_environment_does_not_inherit_provider_or_python_injection(
    tmp_path, monkeypatch
):
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "PYTHONPATH",
        "BASH_ENV",
        "CODEX_SQLITE_HOME",
    ):
        monkeypatch.setenv(key, "PUBLIC_POISON")
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    execute(args, adapter)
    env = calls[0][1]["env"]
    assert "PUBLIC_POISON" not in env.values()
    assert env["HOME"] == str(tmp_path / "public-home")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "OPENAI_API_KEY" not in env


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
        from skills._shared.fit_weekly import codex_runtime

        monkeypatch.setattr(
            codex_runtime, "version", lambda _: "public-different-version"
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
    "kind", ["binary", "instructions", "schema_file", "prompt_file", "prepared"]
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
    targets[kind].write_bytes(b"public changed bytes")
    result = execute(args, adapter)
    assert result["status"] == "failed"
    assert calls == []
    assert not (adapter.work / "process").exists()


def test_interrupted_after_process_recovers_from_original_materials(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import codex_output, model_job

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    parse = codex_output.parse_result

    def crash(*a, **kw):
        from skills._shared.fit_weekly import codex_capability

        if kw["prompt_bytes"] == len(codex_capability.PROMPT.encode()):
            return parse(*a, **kw)
        raise model_job.AdapterInterrupted("public crash after raw persistence")

    monkeypatch.setattr(codex_output, "parse_result", crash)
    with pytest.raises(model_job.AdapterInterrupted):
        execute(args, adapter)
    monkeypatch.setattr(codex_output, "parse_result", parse)
    # Recovery must not need a current executable, proof, global HOME or login.
    runtime.executable.unlink()
    proof.unlink()
    monkeypatch.setenv("HOME", "/public/now-unavailable")
    result = module().recover(
        *args[:5],
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    assert result["invocation_adapter_calls"] == 0
    assert (
        module().recover(
            *args[:5],
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
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "unknown" and len(calls) == 1


def test_capability_without_observed_tool_lifecycle_is_not_proof(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import codex_capability, process_capture, storage
    from skills._shared.fit_weekly.model_process import ProcessResult

    args, runtime, path, calls = setup(tmp_path, monkeypatch)
    proof = json.loads(path.read_text())
    result = ProcessResult(
        0,
        len(codex_capability.PROMPT.encode()),
        output_fixture.stream(output_fixture.events({"ok": True})),
        b"",
        None,
    )
    proof["process"] = process_capture.encode(
        result, codex_capability.binding(runtime.identity())
    )
    path.write_text(storage.canonical(proof))
    with pytest.raises(ValueError):
        prepare(args, runtime, path)
    assert calls == []


def test_command_uses_supported_named_openai_provider_without_auth_copy(
    tmp_path, monkeypatch
):
    args, runtime, _, _ = setup(tmp_path, monkeypatch)
    argv = runtime.command(*args[:3], tmp_path / "work")
    config = dict(
        x.split("=", 1) for i, x in enumerate(argv) if i and argv[i - 1] == "-c"
    )
    assert not any(k.startswith("model_providers.openai.") for k in config)
    assert json.loads(config["model_provider"]) == "trainlab_openai"
    assert (
        json.loads(config["model_providers.trainlab_openai.requires_openai_auth"])
        is True
    )
    assert (
        json.loads(config["model_providers.trainlab_openai.request_max_retries"]) == 0
    )
    assert json.loads(config["model_providers.trainlab_openai.stream_max_retries"]) == 0
    assert not any(
        k.endswith((".env_key", ".experimental_bearer_token", ".base_url"))
        for k in config
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
        "startup",
        "unconfirmed",
        "failed_turn",
        "wrong_host_request",
        "short_host_result",
    ],
)
def test_capability_checks_retained_evidence_not_flags(tmp_path, monkeypatch, kind):
    from skills._shared.fit_weekly import codex_capability, process_capture, storage

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
    elif kind == "startup":
        proof["startup_messages"] = ["a", "a"]
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
            proof["process"], codex_capability.binding(runtime.identity())
        )
        from dataclasses import replace

        bad = (
            result.stdout
            + b'{"type":"turn.failed","error":{"message":"public failure"}}\n'
        )
        proof["process"] = process_capture.encode(
            replace(result, stdout=bad), codex_capability.binding(runtime.identity())
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
    from skills._shared.fit_weekly import codex_capability, process_capture, storage

    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    second_runtime = (
        replace(runtime, prompt_prefix="Another public input:\n")
        if changed_prompt
        else runtime
    )
    second_proof = json.loads(proof.read_text())
    process = process_capture.decode(
        second_proof["process"], codex_capability.binding(runtime.identity())
    )
    second_proof["runtime"] = second_runtime.identity()
    second_proof["process"] = process_capture.encode(
        process, codex_capability.binding(second_runtime.identity())
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
            assert str(exc) == "codex_preparation_invalid"
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
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    assert (args[0] / "trainlab-fit.db").read_bytes() == before


def test_legacy_tool_capability_recovers_stopped_capture_but_cannot_start_new_runtime(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import (
        codex_boundary,
        codex_output,
        fit_parse,
        model_job,
    )

    packet = boundary_fixture.packet
    current_sha = codex_boundary.TOOL_SURFACE_SHA256
    legacy_tools = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_cli_tools.json").read_text()
    )

    def old_packet():
        return {**packet(), "tools": legacy_tools}

    monkeypatch.setattr(
        codex_boundary, "TOOL_SURFACE_SHA256", codex_boundary.LEGACY_TOOL_SURFACE_SHA256
    )
    monkeypatch.setattr(boundary_fixture, "packet", old_packet)
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-1")
    args, runtime, proof, calls = setup(tmp_path, monkeypatch)
    adapter = prepare(args, runtime, proof)
    parse = codex_output.parse_result

    def stopped_before_receipt(*a, **kw):
        from skills._shared.fit_weekly import codex_capability

        if kw["prompt_bytes"] == len(codex_capability.PROMPT.encode()):
            return parse(*a, **kw)
        raise model_job.AdapterInterrupted("synthetic stopped before receipt")

    monkeypatch.setattr(codex_output, "parse_result", stopped_before_receipt)
    with pytest.raises(model_job.AdapterInterrupted):
        execute(args, adapter)
    assert len(calls) == 1
    monkeypatch.setattr(codex_output, "parse_result", parse)
    monkeypatch.setattr(codex_boundary, "TOOL_SURFACE_SHA256", current_sha)
    monkeypatch.setattr(boundary_fixture, "packet", packet)
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-2")
    with pytest.raises(ValueError):
        prepare(args, runtime, proof)
    result = module().recover(
        *args[:5],
        validate_input=ledger.valid_input,
        validate_result=ledger.valid_result,
    )
    assert result["status"] == "succeeded" and len(calls) == 1
    before = (args[0] / "trainlab-fit.db").read_bytes()
    assert (
        module().recover(
            *args[:5],
            validate_input=ledger.valid_input,
            validate_result=ledger.valid_result,
        )
        == result
    )
    assert (args[0] / "trainlab-fit.db").read_bytes() == before and len(calls) == 1
