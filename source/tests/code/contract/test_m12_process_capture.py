from __future__ import annotations

import base64
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))


def module():
    return importlib.import_module("skills._shared.fit_weekly.process_capture")


def binding():
    return module().binding(
        b"public prompt", "a" * 64, stdout_limit=4096, stderr_limit=256
    )


def result(**change):
    from skills._shared.fit_weekly.model_process import ProcessResult

    values = dict(
        returncode=0,
        input_bytes=13,
        stdout=b"public output\n",
        stderr=b"",
        error_code=None,
        process_stopped=True,
    )
    return ProcessResult(**(values | change))


def test_capture_is_durable_before_return_and_replay_does_not_launch(tmp_path):
    work = tmp_path / "capture"
    calls = []

    def launch():
        calls.append(1)
        assert json.loads((work / "intent.json").read_text())["binding"] == binding()
        return result(stdout=b"\x00\xffpublic output\n")

    first = module().run(work, binding(), launch)
    assert first.stdout == b"\x00\xffpublic output\n"
    raw = (work / "capture.json").read_bytes()
    capture = json.loads(raw)
    assert capture["process"]["stderr"]["byte_size"] == 0
    assert capture["process"]["stderr"]["base64"] == ""
    assert base64.b64decode(capture["process"]["stdout"]["base64"]) == first.stdout
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in work.iterdir())
    assert work.stat().st_mode & 0o777 == 0o700
    assert module().run(work, binding(), launch) == first
    assert calls == [1]
    assert (work / "capture.json").read_bytes() == raw
    assert str(tmp_path) not in raw.decode()


@pytest.mark.parametrize(
    "code",
    [
        "process_start_failed",
        "process_input_incomplete",
        "process_timeout",
        "process_exit_nonzero",
        "process_stdout_limit",
        "process_stderr_limit",
        "process_io_failed",
    ],
)
def test_stopped_process_failure_keeps_exact_bounded_evidence(tmp_path, code):
    failure = result(
        returncode=None if code == "process_start_failed" else -9,
        input_bytes=0,
        stdout=b"partial",
        stderr=b"private failure bytes",
        error_code=code,
    )
    first = module().run(tmp_path / "capture", binding(), lambda: failure)
    assert first == failure
    assert (
        module().run(tmp_path / "capture", binding(), lambda: pytest.fail("relaunch"))
        == failure
    )


@pytest.mark.parametrize(
    "part",
    [
        "request_sha256",
        "prompt_sha256",
        "prompt_bytes",
        "stdout_limit",
        "stderr_limit",
        "extra",
    ],
)
def test_binding_drift_never_restarts(tmp_path, part):
    work = tmp_path / "capture"
    module().run(work, binding(), result)
    changed = binding()
    if part.endswith("sha256"):
        changed[part] = "b" * 64
    else:
        changed[part] = 2
    with pytest.raises((ValueError, module().EvidenceUnavailable)):
        module().run(work, changed, lambda: pytest.fail("relaunch"))


@pytest.mark.parametrize(
    "when", ["mkdir_barrier", "intent", "capture", "capture_barrier"]
)
def test_finite_write_failures_preserve_nonterminal_and_never_restart(
    tmp_path, monkeypatch, when
):
    from skills._shared.fit_weekly import storage

    work = tmp_path / "capture"
    calls = []
    original = storage.atomic_file
    with monkeypatch.context() as patch:
        if when == "mkdir_barrier":
            patch.setattr(
                storage,
                "sync_dir",
                lambda _: (_ for _ in ()).throw(OSError("private path")),
            )
        else:

            def write(path, data):
                if path.name == ("intent.json" if when == "intent" else "capture.json"):
                    if when == "capture_barrier":
                        original(path, data)
                    raise OSError("private path")
                original(path, data)

            patch.setattr(storage, "atomic_file", write)

        def launch():
            calls.append(1)
            return result()

        with pytest.raises(module().EvidenceUnavailable) as caught:
            module().run(work, binding(), launch)
        assert "private path" not in str(caught.value)
    if when == "capture_barrier":
        assert (
            module().run(work, binding(), lambda: pytest.fail("relaunch")) == result()
        )
    else:
        with pytest.raises(module().EvidenceUnavailable):
            module().run(work, binding(), lambda: pytest.fail("relaunch"))
    assert len(calls) == int(when in {"capture", "capture_barrier"})


@pytest.mark.parametrize("failure", ["unconfirmed", "exception", "interrupt"])
def test_uncertain_termination_never_becomes_an_ordinary_failed_result(
    tmp_path, failure
):
    from skills._shared.fit_weekly.model_process import ProcessInterrupted

    work = tmp_path / "capture"

    def launch():
        if failure == "unconfirmed":
            raise ProcessInterrupted(
                result(
                    returncode=None,
                    error_code="process_stop_unconfirmed",
                    process_stopped=False,
                )
            )
        if failure == "interrupt":
            raise KeyboardInterrupt()
        raise OSError("private error must not escape")

    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), launch)
    assert not (work / "capture.json").exists()
    if failure == "unconfirmed":
        assert (
            json.loads((work / "interrupted.json").read_text())["process"][
                "process_stopped"
            ]
            is False
        )
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: pytest.fail("relaunch"))


@pytest.mark.parametrize(
    "change",
    [
        dict(stdout=b"x" * 4097),
        dict(stderr=b"x" * 257),
        dict(input_bytes=14),
        dict(input_bytes=True),
        dict(returncode=True),
        dict(input_bytes=12),
        dict(error_code="private-secret"),
        dict(process_stopped=False),
        dict(stdout="not bytes"),
    ],
)
def test_invalid_process_result_never_publishes_terminal(tmp_path, change):
    work = tmp_path / "capture"
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: result(**change))
    assert not (work / "capture.json").exists()
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: pytest.fail("relaunch"))


@pytest.mark.parametrize(
    "damage",
    [
        "empty",
        "json",
        "duplicate",
        "extra",
        "sha",
        "length",
        "base64",
        "binding",
        "permission",
        "symlink",
        "hardlink",
        "interrupted",
        "intent_missing",
        "extra_file",
    ],
)
def test_recovery_refuses_incomplete_or_damaged_private_evidence(tmp_path, damage):
    from skills._shared.fit_weekly import storage

    work = tmp_path / "capture"
    module().run(work, binding(), result)
    path = work / "capture.json"
    if damage == "empty":
        path.write_bytes(b"")
    elif damage == "json":
        path.write_bytes(b"{")
    elif damage == "duplicate":
        path.write_text('{"schema_version":"duplicate",' + path.read_text()[1:])
    elif damage == "permission":
        path.chmod(0o644)
    elif damage in {"symlink", "hardlink"}:
        saved = tmp_path / "saved"
        path.rename(saved)
        if damage == "symlink":
            path.symlink_to(saved)
        else:
            os.link(saved, path)
    elif damage == "interrupted":
        (work / "interrupted.json").write_bytes(path.read_bytes())
    elif damage == "intent_missing":
        (work / "intent.json").rename(tmp_path / "saved-intent")
    elif damage == "extra_file":
        (work / "extra").write_bytes(b"unexpected")
    else:
        value = json.loads(path.read_text())
        if damage == "extra":
            value["extra"] = True
        elif damage == "binding":
            value["binding"]["request_sha256"] = "f" * 64
        elif damage == "sha":
            value["process"]["stdout"]["sha256"] = "0" * 64
        elif damage == "length":
            value["process"]["stdout"]["byte_size"] += 1
        else:
            value["process"]["stdout"]["base64"] = "!not-base64!"
        path.write_text(storage.canonical(value))
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: pytest.fail("relaunch"))


def test_relocated_capture_recovers_without_changing_files(tmp_path):
    first = tmp_path / "first"
    module().run(first, binding(), result)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    before = {p.name: p.read_bytes() for p in second.iterdir()}
    assert module().run(second, binding(), lambda: pytest.fail("relaunch")) == result()
    assert before == {p.name: p.read_bytes() for p in second.iterdir()}


def test_capture_recovery_barrier_failure_does_not_return_result(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import storage

    work = tmp_path / "capture"
    module().run(work, binding(), result)
    monkeypatch.setattr(
        storage, "atomic_file", lambda *_: (_ for _ in ()).throw(OSError("fsync"))
    )
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: pytest.fail("relaunch"))


def test_reentrant_caller_cannot_launch_before_first_result(tmp_path):
    work = tmp_path / "capture"

    def launch():
        with pytest.raises(module().EvidenceUnavailable):
            module().run(work, binding(), lambda: pytest.fail("second launch"))
        return result()

    assert module().run(work, binding(), launch) == result()


def test_real_subprocess_output_passes_to_codex_parser_and_model_job(tmp_path):
    from skills._shared.fit_weekly import codex_output, model_process

    jobs = importlib.import_module("test_m12_model_job")
    protocol = importlib.import_module("test_m12_codex_output")
    args = list(jobs.setup(tmp_path))
    raw = protocol.stream(protocol.events({"ok": True}))
    calls = []
    work = args[0] / "process-test"

    def adapter_run(payload, host, schema):
        def launch():
            calls.append(1)
            return model_process.execute(
                [
                    sys.executable,
                    "-c",
                    "import sys;sys.stdin.buffer.read();sys.stdout.buffer.write("
                    + repr(raw)
                    + ")",
                ],
                cwd=tmp_path,
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
                prompt=b"public prompt",
                timeout=10,
            )

        capture = module().run(work, binding(), launch)
        return codex_output.parse_result(capture, schema, prompt_bytes=13).value

    args[-1].run = adapter_run
    outcome = jobs.run(args)
    assert (
        outcome["status"] == "succeeded" and outcome["receipt"]["model_attempts"] == 0
    )
    assert calls == [1]
    assert jobs.run(args)["invocation_adapter_calls"] == 0


def test_raw_persistence_failure_leaves_outer_model_ledger_unknown(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import storage

    jobs = importlib.import_module("test_m12_model_job")
    args = list(jobs.setup(tmp_path))
    args[-1].run = lambda *_: module().run(args[0] / "process-test", binding(), result)
    original = storage.atomic_file

    def fail(path, data):
        if path.name == "capture.json" and path.parent.name == "process-test":
            raise OSError("local disk failure")
        original(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "atomic_file", fail)
        with pytest.raises(module().EvidenceUnavailable):
            jobs.run(args)
    assert not jobs.capture_path(args).exists()
    assert jobs.run(args)["status"] == "unknown"


@pytest.mark.parametrize("prompt", [b"", b"x" * 16_777_217, "not bytes", None])
def test_invalid_prompt_binding_is_rejected_without_files(tmp_path, prompt):
    with pytest.raises(ValueError, match="process_capture_binding_invalid"):
        module().binding(prompt, "a" * 64)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_sha256", "A" * 64),
        ("prompt_bytes", True),
        ("prompt_bytes", 0),
        ("stderr_limit", 0),
        ("stdout_limit", 67_108_865),
        ("stdout_limit", 1.5),
    ],
)
def test_invalid_binding_never_creates_work(tmp_path, field, value):
    changed = binding()
    changed[field] = value
    with pytest.raises(ValueError, match="process_capture_binding_invalid"):
        module().run(tmp_path / "capture", changed, lambda: pytest.fail("launch"))
    assert list(tmp_path.iterdir()) == []


def test_intent_type_drift_is_not_hidden_by_python_boolean_equality(tmp_path):
    from skills._shared.fit_weekly import storage

    work = tmp_path / "capture"
    one = module().binding(b"x", "a" * 64)
    module().run(work, one, lambda: result(input_bytes=1))
    intent = json.loads((work / "intent.json").read_text())
    intent["binding"]["prompt_bytes"] = True
    (work / "intent.json").write_text(storage.canonical(intent))
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, one, lambda: pytest.fail("launch"))


@pytest.mark.parametrize("position", ["before_launch", "after_capture"])
def test_real_process_exit_does_not_grant_new_launch(tmp_path, position):
    import subprocess

    work = tmp_path / "capture"
    child = """
import os,sys
from pathlib import Path
from skills._shared.fit_weekly import process_capture, storage
from skills._shared.fit_weekly.model_process import ProcessResult
work,position=sys.argv[1:]
def launch():
    if position=='before_launch': os._exit(23)
    return ProcessResult(0,13,b'public output\\n',b'',None)
old=storage.atomic_file
def save(path,data):
    old(path,data)
    if path.name=='capture.json': os._exit(23)
storage.atomic_file=save
process_capture.run(Path(work),process_capture.binding(b'public prompt','a'*64,stdout_limit=4096,stderr_limit=256),launch)
"""
    done = subprocess.run(
        [sys.executable, "-c", child, str(work), position],
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(SOURCE),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        timeout=10,
    )
    assert done.returncode == 23, done.stderr.decode()
    if position == "before_launch":
        with pytest.raises(module().EvidenceUnavailable):
            module().run(work, binding(), lambda: pytest.fail("relaunch"))
    else:
        assert (
            module().run(work, binding(), lambda: pytest.fail("relaunch")) == result()
        )


def test_six_processes_share_exactly_one_launch_reservation(tmp_path):
    import subprocess

    work, counter = tmp_path / "capture", tmp_path / "count"
    child = """
import os,sys,time
from pathlib import Path
from skills._shared.fit_weekly import process_capture
from skills._shared.fit_weekly.model_process import ProcessResult
work,counter=sys.argv[1:]
def launch():
    fd=os.open(counter,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    os.write(fd,b'call\\n');os.close(fd)
    time.sleep(0.1)
    return ProcessResult(0,13,b'public output\\n',b'',None)
sys.stdin.buffer.read(1)
try:
    process_capture.run(Path(work),process_capture.binding(b'public prompt','a'*64,stdout_limit=4096,stderr_limit=256),launch)
    print('complete')
except process_capture.EvidenceUnavailable:
    print('incomplete')
"""
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(work), str(counter)],
            env={
                "PATH": os.defpath,
                "PYTHONPATH": str(SOURCE),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(6)
    ]
    try:
        for proc in procs:
            assert proc.stdin is not None
            proc.stdin.write(b"x")
            proc.stdin.flush()
        for proc in procs:
            out, err = proc.communicate(timeout=15)
            assert proc.returncode == 0, err.decode()
            assert out.strip() in (b"complete", b"incomplete")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
    assert counter.read_bytes() == b"call\n"
    assert module().run(work, binding(), lambda: pytest.fail("relaunch")) == result()


def test_launch_mutation_cannot_change_persisted_binding(tmp_path):
    work = tmp_path / "capture"
    value = binding()

    def launch():
        value["request_sha256"] = "b" * 64
        return result()

    module().run(work, value, launch)
    assert json.loads((work / "capture.json").read_text())["binding"] == binding()


@pytest.mark.parametrize("unsafe", ["directory_mode", "directory_link", "parent_mode"])
def test_unsafe_work_path_is_not_adopted(tmp_path, unsafe):
    work = tmp_path / "capture"
    if unsafe == "directory_mode":
        work.mkdir(mode=0o755)
    elif unsafe == "directory_link":
        other = tmp_path / "other"
        other.mkdir(mode=0o700)
        work.symlink_to(other, target_is_directory=True)
    else:
        tmp_path.chmod(0o755)
    with pytest.raises(module().EvidenceUnavailable):
        module().run(work, binding(), lambda: pytest.fail("launch"))
    assert not (work / "intent.json").exists()
