"""Public child programs only; no Codex, credentials or model service."""

from __future__ import annotations

import importlib
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skills._shared.fit_weekly import model_job


def module() -> Any:
    return importlib.import_module("skills._shared.fit_weekly.model_process")


def execute(tmp_path: Path, code: str, **changes: Any) -> Any:
    options = {
        "cwd": tmp_path,
        "env": {"PATH": os.defpath, "LANG": "C"},
        "prompt": b"public input",
        "timeout": 2.0,
        "stop_timeout": 2.0,
        "stdout_limit": 100_000,
        "stderr_limit": 10_000,
    }
    options.update(changes)
    return module().execute([sys.executable, "-c", code], **options)


def test_pipes_are_drained_while_stdin_is_sent(tmp_path: Path) -> None:
    result = execute(
        tmp_path,
        "import sys; sys.stdout.buffer.write(b'x'*200000); sys.stdout.flush(); "
        "sys.stderr.buffer.write(b'y'*200000); sys.stderr.flush(); "
        "p=sys.stdin.buffer.read(); sys.stdout.buffer.write(p)",
        prompt=b"p" * 200_000,
        stdout_limit=500_000,
        stderr_limit=300_000,
    )
    assert result.error_code is None and result.returncode == 0
    assert result.stdout == b"x" * 200_000 + b"p" * 200_000
    assert result.stderr == b"y" * 200_000
    assert result.input_bytes == 200_000 and result.process_stopped


def test_process_launch_time_is_included_in_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = module()
    real_popen = subprocess.Popen
    monotonic = time.monotonic
    offset = 0.0
    children = []

    def launch(argv, **kwargs):
        nonlocal offset
        child = real_popen(argv, **kwargs)
        if argv[0] == sys.executable:
            children.append(child)
            # The real child exists. Advance only the supervisor's private
            # clock to represent a finite slow launch, not a hung OS.
            offset += 31.0
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(
        supervisor,
        "time",
        SimpleNamespace(monotonic=lambda: monotonic() + offset, sleep=time.sleep),
    )
    result = execute(
        tmp_path,
        "import sys; sys.stdin.buffer.read(); print('finished')",
        timeout=30,
        stop_timeout=5,
    )
    assert len(children) == 1
    assert children[0].poll() is not None
    assert result.error_code == "process_timeout"
    assert result.process_stopped and result.input_bytes == 0
    assert result.stdout == b""


@pytest.mark.parametrize(
    "code,error",
    [
        ("import sys; sys.stdin.buffer.read(); sys.exit(7)", "process_exit_nonzero"),
        ("import time; time.sleep(10)", "process_timeout"),
        ("import os; os.close(0)", "process_input_incomplete"),
        ("import os; os.write(1,b'x'*200000)", "process_stdout_limit"),
        ("import os; os.write(2,b'x'*200000)", "process_stderr_limit"),
    ],
)
def test_terminal_failures_are_not_success(
    tmp_path: Path, code: str, error: str
) -> None:
    result = execute(tmp_path, code, prompt=b"p" * 200_000, timeout=0.5)
    assert result.error_code == error and result.process_stopped
    assert len(result.stdout) <= 100_000 and len(result.stderr) <= 10_000


def test_executable_start_error_has_fixed_code(tmp_path: Path) -> None:
    result = module().execute(
        [str(tmp_path / "missing-private-command")],
        cwd=tmp_path,
        env={},
        prompt=b"public",
        timeout=1,
    )
    assert result.error_code == "process_start_failed"
    assert result.returncode is None and result.input_bytes == 0
    assert result.stdout == result.stderr == b"" and result.process_stopped
    assert "missing-private-command" not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        {"prompt": b""},
        {"prompt": "not bytes"},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"stop_timeout": 0},
        {"stdout_limit": True},
        {"stderr_limit": -1},
        {"env": {"BAD": "a\x00b"}},
        {"cwd": Path("relative")},
    ],
)
def test_invalid_launch_options_do_not_create_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    launches = []
    monkeypatch.setattr(
        module().subprocess, "Popen", lambda *a, **k: launches.append(a)
    )
    with pytest.raises(ValueError, match="process_options_invalid"):
        execute(tmp_path, "pass", **change)
    assert launches == []


def test_argv_is_not_interpreted_by_shell(tmp_path: Path) -> None:
    code = "import sys; sys.stdin.buffer.read(); print(sys.argv[1])"
    result = module().execute(
        [sys.executable, "-c", code, "$(touch injected); *"],
        cwd=tmp_path,
        env={},
        prompt=b"public",
        timeout=2,
    )
    assert result.error_code is None
    assert result.stdout == b"$(touch injected); *\n"
    assert not (tmp_path / "injected").exists()


def test_child_cannot_inherit_unlisted_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAINLAB_TEST_PRIVATE", "private-value")
    result = execute(
        tmp_path,
        "import os,sys; sys.stdin.read(); print(os.getenv('TRAINLAB_TEST_PRIVATE'))",
    )
    assert result.stdout == b"None\n"


@pytest.mark.parametrize("leader_waits", [True, False])
@pytest.mark.parametrize("closes_streams", [True, False])
def test_descendant_is_stopped_before_result(
    tmp_path: Path, leader_waits: bool, closes_streams: bool
) -> None:
    child = (
        "import os,time; "
        + ("os.close(0); os.close(1); os.close(2); " if closes_streams else "")
        + "time.sleep(0.8); open('late-write','w').write('late')"
    )
    code = (
        "import subprocess,sys,time; sys.stdin.read(); "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        + ("time.sleep(10)" if leader_waits else "print('done')")
    )
    result = execute(tmp_path, code, timeout=0.25 if leader_waits else 2)
    assert result.process_stopped
    assert result.error_code == ("process_timeout" if leader_waits else None)
    time.sleep(0.9)
    assert not (tmp_path / "late-write").exists()


def test_unknown_group_state_never_becomes_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module(), "session_groups", lambda *args: None)
    with pytest.raises(model_job.AdapterInterrupted) as failure:
        execute(
            tmp_path, "import sys; sys.stdin.read(); print('done')", stop_timeout=0.1
        )
    assert not failure.value.capture.process_stopped
    assert failure.value.capture.stdout == b"done\n"


def test_parent_exception_also_stops_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = []
    confirm = module().stop

    class Broken(selectors.DefaultSelector):
        def select(self, timeout: float | None = None) -> Any:
            raise KeyboardInterrupt

    def observe(*args: Any) -> Any:
        result = confirm(*args)
        stopped.append(result)
        return result

    monkeypatch.setattr(module().selectors, "DefaultSelector", Broken)
    monkeypatch.setattr(module(), "stop", observe)
    with pytest.raises(KeyboardInterrupt):
        execute(tmp_path, "import time; time.sleep(10)")
    assert stopped == [True]


def test_exact_output_limit_and_closed_streams(tmp_path: Path) -> None:
    result = execute(
        tmp_path,
        "import sys; sys.stdin.read(); sys.stdout.write('x'*17)",
        stdout_limit=17,
    )
    assert result.error_code is None and result.stdout == b"x" * 17


def test_group_probe_failure_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("private diagnostic")

    monkeypatch.setattr(module().subprocess, "run", fail)
    assert module().session_groups(12345, 1) is None


def test_zombies_are_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(
        module().subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, f"123 123 {os.geteuid()} Z\n124 124 {os.geteuid()} S\n".encode(), b""
        ),
    )
    monkeypatch.setattr(module().os, "getsid", lambda pid: pid)
    assert module().session_groups(123, 1) == set()
    assert module().session_groups(124, 1) == {124}


def test_result_can_be_used_by_single_attempt_ledger(tmp_path: Path) -> None:
    fixture = importlib.import_module("test_m12_model_job")
    args = fixture.setup(tmp_path)
    adapter = model_job.FakeAdapter({"ok": True}, [])
    calls = []

    def run(payload: dict[str, Any], host: Any, schema: dict[str, Any]) -> Any:
        calls.append(True)
        result = execute(
            tmp_path, "import sys; sys.stdin.read(); print('{\"ok\":true}')"
        )
        assert result.error_code is None
        return json.loads(result.stdout)

    adapter.run = run
    args = (*args[:5], adapter)
    a = fixture.run(args)
    b = fixture.run(args)
    assert a["status"] == b["status"] == "succeeded"
    assert calls == [True] and b["invocation_adapter_calls"] == 0


@pytest.mark.parametrize("operation", ["read", "write"])
def test_finite_pipe_io_failure_stops_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    m = module()
    original_start, original_io = m.subprocess.Popen, getattr(m.os, operation)
    watched = []

    def start(*args: Any, **kwargs: Any) -> Any:
        proc = original_start(*args, **kwargs)
        if args[0][0] == sys.executable:
            watched.append(
                (proc.stdout if operation == "read" else proc.stdin).fileno()
            )
        return proc

    def fail(fd: int, value: Any) -> Any:
        if fd in watched:
            watched.remove(fd)
            raise OSError("private content must not enter the fixed error")
        return original_io(fd, value)

    monkeypatch.setattr(m.subprocess, "Popen", start)
    monkeypatch.setattr(m.os, operation, fail)
    result = execute(
        tmp_path, "import sys,time; print('public',flush=True); time.sleep(10)"
    )
    assert result.process_stopped and result.error_code == "process_io_failed"
    assert "private content" not in repr(result)


@pytest.mark.parametrize("data", [b"123", b"not-a-group S\n", b"\xff\n"])
def test_malformed_process_observation_is_unknown(
    monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    import subprocess

    monkeypatch.setattr(
        module().subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, data, b""),
    )
    assert module().session_groups(123, 1) is None


def test_unknown_process_reentry_does_not_start_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = importlib.import_module("test_m12_model_job")
    args = fixture.setup(tmp_path)
    calls = []

    def run(*values: Any) -> Any:
        calls.append(True)
        return execute(tmp_path, "import sys; sys.stdin.read(); print('public')")

    args[-1].run = run
    monkeypatch.setattr(module(), "session_groups", lambda *a: None)
    with pytest.raises(model_job.AdapterInterrupted):
        fixture.run(args)
    replay = fixture.run(args)
    assert replay["status"] == "unknown" and replay["invocation_adapter_calls"] == 0
    assert calls == [True]


def test_command_cannot_receive_unlisted_open_file(tmp_path: Path) -> None:
    target = tmp_path / "private-sentinel"
    target.write_text("public fixture representing a private descriptor")
    with target.open("rb") as opened:
        os.set_inheritable(opened.fileno(), True)
        code = f"import os,sys; sys.stdin.read();\ntry: os.fstat({opened.fileno()}); print('leaked')\nexcept OSError: print('closed')"
        result = execute(tmp_path, code)
    assert result.error_code is None and result.stdout == b"closed\n"


@pytest.mark.parametrize("leader_waits", [True, False])
def test_normal_tool_in_another_process_group_is_also_stopped(
    tmp_path: Path, leader_waits: bool
) -> None:
    child = "import os,time; os.close(0); os.close(1); os.close(2); time.sleep(0.8); open('late-tool','w').write('late')"
    code = (
        "import subprocess,sys,time; sys.stdin.read(); "
        f"subprocess.Popen([sys.executable,'-c',{child!r}],process_group=0); "
        + ("time.sleep(10)" if leader_waits else "print('done')")
    )
    result = execute(tmp_path, code, timeout=0.25)
    assert result.process_stopped
    time.sleep(0.9)
    assert not (tmp_path / "late-tool").exists()


def test_other_independent_session_is_not_stopped(tmp_path: Path) -> None:
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True
    )
    try:
        result = execute(tmp_path, "import sys; sys.stdin.read(); print('done')")
        assert result.process_stopped and result.error_code is None
        assert other.poll() is None
    finally:
        other.kill()
        other.wait(timeout=2)


@pytest.mark.parametrize("disappeared", [True, False])
def test_session_lookup_disappearance_vs_error(
    monkeypatch: pytest.MonkeyPatch, disappeared: bool
) -> None:
    m = module()
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, f"123 123 {os.geteuid()} S\n".encode(), b""
        ),
    )

    def lookup(pid: int) -> int:
        raise ProcessLookupError if disappeared else PermissionError

    monkeypatch.setattr(m.os, "getsid", lookup)
    assert m.session_groups(123, 1) == (set() if disappeared else None)


@pytest.mark.parametrize("live", [False, True])
def test_signal_permission_is_not_a_liveness_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    m = module()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)" if live else "pass"],
        start_new_session=True,
    )
    original_kill = m.os.killpg
    if not live:
        proc.wait(timeout=2)

    def refused(pgid: int, sig: int) -> None:
        if pgid == proc.pid:
            raise PermissionError("public synthetic EPERM")
        original_kill(pgid, sig)

    monkeypatch.setattr(m.os, "killpg", refused)
    try:
        assert m.stop(proc, 0.15) is (not live)
    finally:
        if proc.poll() is None:
            original_kill(proc.pid, 9)
            proc.wait(timeout=2)


def test_signal_refusal_and_failed_observation_stays_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = module()
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    proc.wait(timeout=2)

    def refused(*args: Any) -> None:
        raise PermissionError("public synthetic EPERM")

    monkeypatch.setattr(m.os, "killpg", refused)
    monkeypatch.setattr(m, "session_groups", lambda *args: None)
    assert m.stop(proc, 0.1) is False


def test_real_unreaped_zombie_leader_can_be_confirmed_stopped(tmp_path: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    try:
        deadline = time.monotonic() + 2
        while True:
            state = (
                subprocess.check_output(["/bin/ps", "-p", str(proc.pid), "-o", "stat="])
                .decode()
                .strip()
            )
            if state.startswith("Z"):
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert module().stop(proc, 2) is True
        assert proc.returncode == 0
    finally:
        proc.wait(timeout=2)


def test_disappearance_between_observation_and_signal_is_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = module()
    real_start, real_groups, real_signal = (
        m.subprocess.Popen,
        m.session_groups,
        m.os.killpg,
    )
    owned = []
    observations = []
    refusals: list[int] = []

    def start(*args: Any, **kwargs: Any) -> Any:
        p = real_start(*args, **kwargs)
        if args[0][0] == sys.executable:
            owned.append(p.pid)
        return p

    def snapshot(sid: int, timeout: float) -> Any:
        observations.append(sid)
        if len(observations) == 1:
            return {sid}
        return real_groups(sid, timeout)

    def signal(pgid: int, sig: int) -> None:
        if pgid in owned and not refusals:
            refusals.append(pgid)
            raise PermissionError("public lifecycle race")
        real_signal(pgid, sig)

    monkeypatch.setattr(m.subprocess, "Popen", start)
    monkeypatch.setattr(m, "session_groups", snapshot)
    monkeypatch.setattr(m.os, "killpg", signal)
    result = execute(tmp_path, "import sys; sys.stdin.read(); print('done')")
    assert result.process_stopped and result.error_code is None
    assert len(refusals) == 1 and len(observations) >= 2
