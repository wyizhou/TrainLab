"""A3-11 runner isolation tests; all subprocesses are local test fakes."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import stat
import sys
import time

import pytest

from trainlab.analysis.config import AnalysisConfig
from trainlab.analysis.harness import HarnessBundle, HarnessFileEvidence, SchemaEvidence
from trainlab.analysis.runner import (
    AnalysisCodexRunner,
    AnalysisRunnerError,
    RUNNER_ADAPTER_VERSION,
    _codex_compatible_output_schema,
    _command,
    _supports_strict_structured_output,
)
import trainlab.analysis.runner as runner_module


def _config(tmp_path: Path, *, maximum: int = 1024, timeout: int = 2) -> AnalysisConfig:
    temp_root = tmp_path / "state" / "tmp" / "analysis"
    temp_root.mkdir(parents=True)
    temp_root.chmod(0o700)
    lock_parent = tmp_path / "state" / "locks"
    lock_parent.mkdir(parents=True)
    lock_parent.chmod(0o700)
    output_schema = tmp_path / "output.json"
    output_schema.write_bytes(b'{"type":"object"}')
    output_schema.chmod(0o600)
    return AnalysisConfig(
        schema_version="1",
        project_root=tmp_path,
        timezone="Asia/Singapore",
        harness_root=tmp_path / "harness",
        input_schema=tmp_path / "input.json",
        output_schema=output_schema,
        max_context_bytes=maximum,
        daily_baseline_days=7,
        weekly_baseline_days=28,
        max_recent_daily_artifacts=7,
        codex_timeout_seconds=timeout,
        delivery_timeout_seconds=30,
        lock_path=lock_parent / "analysis.lock",
        temp_root=temp_root,
    )


def _bundle(root: Path) -> HarnessBundle:
    harness = root / "harness" / "analysis.md"
    harness.parent.mkdir(parents=True)
    payload = b"trusted analysis harness\n"
    harness.write_bytes(payload)
    harness.chmod(0o600)
    output_schema = root / "output.json"
    return HarnessBundle(
        route="daily",
        harness_version="a" * 64,
        files=(HarnessFileEvidence("harness/analysis.md", sha256(payload).hexdigest()),),
        schema_evidence=SchemaEvidence(
            "1", "b" * 64, "1", sha256(output_schema.read_bytes()).hexdigest()
        ),
    )


@pytest.fixture
def accepted_context(monkeypatch):
    # A3-10 owns exhaustive context-schema coverage.  The runner receives its
    # already canonical bytes, so tests isolate process lifecycle behavior.
    monkeypatch.setattr(runner_module, "_canonical_context", lambda value, maximum: value)
    return b'{"canonical":"context"}'


def _fake_command(monkeypatch, program: str) -> None:
    monkeypatch.setattr(
        runner_module,
        "_command",
        lambda executable, *args, **kwargs: (sys.executable, "-c", program),
    )


def test_launch_profile_has_no_model_and_explicitly_disables_tools():
    command = _command(("codex",))
    assert command[:3] == ("codex", "exec", "--ephemeral")
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--skip-git-repo-check" in command
    output_index = command.index("--output-schema")
    assert command[output_index + 1] == "output.schema.json"
    assert not Path(command[output_index + 1]).is_absolute()
    assert not any("model" in argument.lower() for argument in command)
    assert "--sandbox" in command and "read-only" in command
    assert "mcp_servers={}" in command
    assert "tools.shell=false" in command
    assert "tools.file_write=false" in command
    assert "tools.network=false" in command


def test_generation_schema_adapts_only_codex_unsupported_constraints():
    source = {
        "type": "object",
        "properties": {
            "schema_version": {"const": "1"},
            "payload": {
                "type": "object",
                "maxProperties": 2,
                "propertyNames": {"maxLength": 10},
                "additionalProperties": {"type": "string"},
            },
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
    }

    adapted = json.loads(
        _codex_compatible_output_schema(
            json.dumps(source, separators=(",", ":")).encode()
        )
    )
    assert adapted["properties"]["schema_version"] == {
        "const": "1",
        "type": "string",
    }
    assert adapted["properties"]["payload"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert adapted["properties"]["items"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert "propertyNames" in source["properties"]["payload"]
    assert "maxProperties" in source["properties"]["payload"]
    assert source["properties"]["items"]["uniqueItems"] is True


def test_dynamic_extension_objects_fall_back_to_prompt_schema_validation():
    dynamic = b'{"type":"object","additionalProperties":{"type":"string"}}'
    closed = b'{"type":"object","additionalProperties":false,"properties":{},"required":[]}'
    assert _supports_strict_structured_output(dynamic) is False
    assert _supports_strict_structured_output(closed) is True
    assert "--output-schema" not in _command(
        ("codex",), structured_output=False
    )
    assert "--output-schema" in _command(
        ("codex",), structured_output=True
    )


def test_correction_entry_accepts_only_sanitized_validation_codes(tmp_path):
    runner = AnalysisCodexRunner(_config(tmp_path))
    with pytest.raises(
        AnalysisRunnerError, match="analysis_runner_correction_code_invalid"
    ):
        runner.execute_correction(
            _bundle(tmp_path), b"{}", "raw model output with sensitive detail"
        )


def test_success_is_one_generation_in_private_workspace_and_cleans_it(tmp_path, monkeypatch, accepted_context):
    config = _config(tmp_path)
    bundle = _bundle(tmp_path)
    calls = []
    original = runner_module.subprocess.Popen

    def factory(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        schema_copy = workspace / "output.schema.json"
        calls.append(
            (
                args,
                kwargs,
                stat.S_IMODE(workspace.stat().st_mode),
                schema_copy.is_file(),
                stat.S_IMODE(schema_copy.stat().st_mode),
            )
        )
        return original(*args, **kwargs)

    monkeypatch.setenv("CODEX_HOME", "/trusted/codex-home")
    _fake_command(monkeypatch, "import sys; sys.stdout.buffer.write(b'{\\\"ok\\\":true}')")
    result = AnalysisCodexRunner(config, process_factory=factory).execute(bundle, accepted_context)

    assert result.output_bytes == b'{"ok":true}'
    assert result.audit["runner_adapter_version"] == RUNNER_ADAPTER_VERSION
    assert result.audit["process_group_cleaned"] is True
    assert len(calls) == 1
    _, kwargs, workspace_mode, schema_exists, schema_mode = calls[0]
    assert kwargs["start_new_session"] is True
    assert Path(kwargs["cwd"]).parent == config.temp_root
    assert workspace_mode == 0o700
    assert schema_exists is True
    assert schema_mode == 0o600
    assert kwargs["env"]["HOME"] == str(kwargs["cwd"])
    assert kwargs["env"]["CODEX_HOME"] == "/trusted/codex-home"
    assert "CODEX_HOME" not in result.audit
    assert "/trusted/codex-home" not in repr(result.audit)
    assert list(config.temp_root.iterdir()) == []


def test_stdin_contains_complete_verified_harness_and_context(tmp_path, monkeypatch, accepted_context):
    config = _config(tmp_path)
    bundle = _bundle(tmp_path)
    received = tmp_path / "received-stdin"
    program = (
        "import pathlib,sys; "
        f"pathlib.Path({str(received)!r}).write_bytes(sys.stdin.buffer.read()); "
        "sys.stdout.buffer.write(b'{}')"
    )
    _fake_command(monkeypatch, program)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", "/parent-home")
    result = AnalysisCodexRunner(config).execute(bundle, accepted_context)
    payload = received.read_bytes()
    assert b"trusted analysis harness" in payload
    assert accepted_context in payload
    assert b"BEGIN TRUSTED HARNESS harness/analysis.md" in payload
    assert result.output_bytes == b"{}"


def test_codex_home_falls_back_to_parent_home_without_audit_leak(tmp_path, monkeypatch, accepted_context):
    config = _config(tmp_path)
    seen = []
    original = runner_module.subprocess.Popen

    def factory(*args, **kwargs):
        seen.append(kwargs["env"])
        return original(*args, **kwargs)

    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", "/parent-home")
    _fake_command(monkeypatch, "import sys; sys.stdout.buffer.write(b'{}')")
    result = AnalysisCodexRunner(config, process_factory=factory).execute(_bundle(tmp_path), accepted_context)
    assert seen[0]["CODEX_HOME"] == "/parent-home/.codex"
    assert "/parent-home/.codex" not in repr(result.audit)


def test_nonzero_is_stable_and_never_exposes_stderr(tmp_path, monkeypatch, accepted_context):
    _fake_command(monkeypatch, "import sys; sys.stderr.write('sensitive error'); raise SystemExit(7)")
    with pytest.raises(AnalysisRunnerError, match="^analysis_runner_process_nonzero$"):
        AnalysisCodexRunner(_config(tmp_path), process_factory=runner_module.subprocess.Popen).execute(
            _bundle(tmp_path), accepted_context
        )


def test_output_limit_terminates_group_and_cleans_workspace(tmp_path, monkeypatch, accepted_context):
    config = _config(tmp_path, maximum=8)
    _fake_command(monkeypatch, "import sys; sys.stdout.buffer.write(b'x' * 64)")
    with pytest.raises(AnalysisRunnerError, match="^analysis_runner_output_limit_exceeded$"):
        AnalysisCodexRunner(config).execute(_bundle(tmp_path), accepted_context)
    assert list(config.temp_root.iterdir()) == []


def test_timeout_kills_descendant_process_group_and_cleans_workspace(tmp_path, monkeypatch, accepted_context):
    config = _config(tmp_path, timeout=1)
    marker = tmp_path / "descendant-marker"
    child = f"import pathlib,time; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('orphan')"
    program = f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
    _fake_command(monkeypatch, program)
    with pytest.raises(AnalysisRunnerError, match="^analysis_runner_process_timeout$"):
        AnalysisCodexRunner(config).execute(_bundle(tmp_path), accepted_context)
    time.sleep(2.3)
    assert not marker.exists()
    assert list(config.temp_root.iterdir()) == []


def test_invalid_context_fails_before_process_start(tmp_path):
    with pytest.raises(AnalysisRunnerError, match="^analysis_runner_context_invalid$"):
        AnalysisCodexRunner(_config(tmp_path)).execute(_bundle(tmp_path), b"not-json")


def test_output_schema_hash_mismatch_fails_before_process_start(tmp_path, accepted_context):
    config = _config(tmp_path)
    bundle = _bundle(tmp_path)
    config.output_schema.write_bytes(b'{"type":"array"}')
    with pytest.raises(AnalysisRunnerError, match="^analysis_runner_output_schema_invalid$"):
        AnalysisCodexRunner(config).execute(bundle, accepted_context)
