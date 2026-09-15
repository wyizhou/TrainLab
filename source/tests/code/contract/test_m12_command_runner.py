from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from skills._shared.fit_weekly import command_output, command_runtime, model_process

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}


@pytest.mark.parametrize("adapter", ["codex", "claude"])
def test_real_replaceable_process_syntax_and_complete_input(tmp_path, adapter):
    executable = tmp_path / adapter
    executable.write_text(f"""#!{sys.executable}
import json,sys
args=sys.argv[1:]
assert {adapter!r}!='codex' or args[0]=='exec'
assert {adapter!r}!='claude' or args[0]=='-p'
assert '-m' not in args and '--model' not in args and '--effort' not in args
assert sys.stdin.buffer.read()==b'public complete input'
value={{'ok': True}}
if {adapter!r}=='claude':value={{'type':'result','subtype':'success','is_error':False,'result':json.dumps(value)}}
print(json.dumps(value))
""")
    executable.chmod(0o700)
    spec = command_runtime.CommandSpec(adapter, executable)
    runtime = command_runtime.Runtime(
        spec,
        Path(__file__).resolve().parents[3],
        "Public instruction",
        "Public input",
        settings={},
    )
    work = tmp_path / "work"
    work.mkdir()
    (work / "response.schema.json").write_text(json.dumps(SCHEMA))
    result = model_process.execute(
        runtime.command(tmp_path, "2026-08-09T07:00:00Z", "0" * 64, work),
        prompt=b"public complete input",
        env={"PATH": os.defpath},
        cwd=tmp_path,
        timeout=3,
    )
    assert command_output.parse_result(
        result, SCHEMA, prompt_bytes=21, adapter=adapter
    ) == {"ok": True}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"ok":true}{"ok":true}',
        b'{"ok":true,"ok":false}',
        b'{"ok":',
        b'{"ok":NaN}',
        b'{"ok":true} trailing',
        b'{"ok":false}',
        b"[]",
        b"",
    ],
)
def test_invalid_final_is_rejected(raw):
    result = model_process.ProcessResult(0, 1, raw, b"", None)
    with pytest.raises(ValueError):
        command_output.parse_result(result, SCHEMA, prompt_bytes=1, adapter="codex")


@pytest.mark.parametrize(
    "change", [{"returncode": 1}, {"error_code": "process_timeout"}, {"input_bytes": 0}]
)
def test_complete_stop_and_input_are_required(change):
    result = model_process.ProcessResult(0, 1, b'{"ok":true}', b"", None)
    with pytest.raises(ValueError):
        command_output.parse_result(
            dataclasses.replace(result, **change),
            SCHEMA,
            prompt_bytes=1,
            adapter="codex",
        )


def test_environment_selection_drops_instructions_and_tools(tmp_path, monkeypatch):
    home = tmp_path / "home"
    auth = home / ".codex"
    auth.mkdir(parents=True)
    (auth / "config.toml").write_text(
        'model="environment-model"\nmodel_reasoning_effort="high"\nmodel_provider="local"\ndeveloper_instructions="SENTINEL"\n[model_providers.local]\nname="Local"\nbase_url="http://127.0.0.1:5555/v1"\nwire_api="responses"\nenv_key="PUBLIC_TEST_KEY"\n[mcp_servers.forbidden]\ncommand="forbidden"\n'
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(auth))
    selected = command_runtime.environment_settings("codex")
    assert selected["model"] == "environment-model"
    assert selected["model_reasoning_effort"] == "high"
    assert "SENTINEL" not in json.dumps(selected) and "forbidden" not in json.dumps(
        selected
    )
    assert selected["model_providers.trainlab_environment.env_key"] == "PUBLIC_TEST_KEY"
    assert selected["model_providers.trainlab_environment.request_max_retries"] == 0
    assert selected["model_providers.trainlab_environment.stream_max_retries"] == 0


def test_unknown_adapter_is_rejected():
    with pytest.raises(ValueError):
        command_runtime.CommandSpec("unknown", Path(sys.executable)).identity()


@pytest.mark.parametrize("adapter", ["codex", "claude"])
@pytest.mark.parametrize(
    "raw",
    [
        b'{"ok":true}' * 2,
        b'{"ok":NaN}',
        b'{"ok":true,"ok":false}',
        b'{"ok":true}x',
        b"{}",
    ],
)
def test_terminal_output_does_not_search_backwards(adapter, raw):
    if adapter == "claude":
        raw = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": raw.decode(),
            }
        ).encode()
    result = model_process.ProcessResult(0, 1, raw, b"", None)
    with pytest.raises(ValueError):
        command_output.parse_result(result, SCHEMA, prompt_bytes=1, adapter=adapter)


@pytest.mark.parametrize(
    "value",
    [
        {
            "type": "result",
            "subtype": "error",
            "is_error": False,
            "result": '{"ok":true}',
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": '{"ok":true}',
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": '{"ok":true}',
            "x": float("nan"),
        },
    ],
)
def test_claude_error_or_nonfinite_metadata_cannot_be_success(value):
    result = model_process.ProcessResult(0, 1, json.dumps(value).encode(), b"", None)
    with pytest.raises(ValueError):
        command_output.parse_result(result, SCHEMA, prompt_bytes=1, adapter="claude")


def test_command_grant_binds_identity_and_old_grant_cannot_launch():
    from skills._shared.fit_weekly import run_authorization

    value: dict[str, Any] = {
        "schema_version": "fit_run_authorization_v2",
        "key": "public",
        "starts_utc": "2026-08-09T07:00:00Z",
        "expires_utc": "2026-08-10T07:00:00Z",
        "sync": None,
        "models": [
            {
                "period_end_utc": "2026-08-09T07:00:00Z",
                "stage": "plan",
                "command_sha256": "1" * 64,
                "timeout_seconds": 20,
            }
        ],
        "publication": None,
    }
    grant = run_authorization.parse(value, now="2026-08-09T07:00:01Z")
    assert (
        grant.command(
            "2026-08-09T07:00:00Z", "plan", "1" * 64, now="2026-08-09T07:00:01Z"
        ).timeout_seconds
        == 20
    )
    with pytest.raises(ValueError):
        grant.command(
            "2026-08-09T07:00:00Z", "plan", "2" * 64, now="2026-08-09T07:00:01Z"
        )
    value["schema_version"] = "fit_run_authorization_v1"
    value["models"][0].pop("command_sha256")
    value["models"][0]["model"] = "historical"
    old = run_authorization.parse(value, now="2026-08-09T07:00:01Z")
    with pytest.raises(ValueError):
        old.command(
            "2026-08-09T07:00:00Z", "plan", "1" * 64, now="2026-08-09T07:00:01Z"
        )


def test_selected_settings_and_credentials_are_separate(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import command_environment

    home = tmp_path / "home"
    directory = home / ".claude"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(
        json.dumps(
            {
                "model": "claude-sonnet-4-6",
                "effortLevel": "high",
                "env": {
                    "ANTHROPIC_API_KEY": "synthetic-public-secret",
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
                },
                "hooks": {"SessionStart": "forbidden"},
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(directory))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    selected = command_environment.settings("claude")
    assert "synthetic-public-secret" not in json.dumps(selected)
    assert "forbidden" not in json.dumps(selected)
    env = command_environment.environment(tmp_path, "claude", selected)
    assert env["ANTHROPIC_API_KEY"] == "synthetic-public-secret"
    assert (
        env["CLAUDE_CODE_MAX_RETRIES"] == "0"
        and env["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"] == "1"
    )
    assert env["MAX_MCP_OUTPUT_TOKENS"] == "1000000"


def test_current_identity_excludes_retired_launchers(tmp_path, monkeypatch):
    import importlib

    fixture = importlib.import_module("test_m12_resource_closure")
    runtime = fixture.runtime_copy(tmp_path, monkeypatch)
    before = runtime.identity()
    for name in (
        "codex_runtime",
        "codex_adapter",
        "codex_recovery",
        "codex_capability",
    ):
        (runtime.source / "skills/_shared/fit_weekly" / f"{name}.py").write_text(
            "retired reader only"
        )
    assert runtime.identity() == before


@pytest.mark.parametrize("environment_override", [False, True])
def test_builtin_provider_keeps_configured_endpoint(
    tmp_path, monkeypatch, environment_override
):
    from skills._shared.fit_weekly import command_environment

    auth = tmp_path / ".codex"
    auth.mkdir()
    (auth / "config.toml").write_text(
        'model="public-model"\nmodel_reasoning_effort="high"\n'
        'openai_base_url="http://127.0.0.1:5101/config/v1"\n'
        'cli_auth_credentials_store="file"\n'
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(auth))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    if environment_override:
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:5102/env/v1")
    selected = command_environment.settings("codex")
    assert (
        selected["model_providers.trainlab_environment.base_url"]
        == "http://127.0.0.1:5101/config/v1"
    )
    assert selected["model_providers.trainlab_environment.requires_openai_auth"] is True
    assert "model_providers.trainlab_environment.env_key" not in selected
    assert selected["cli_auth_credentials_store"] == "file"
    assert selected["model"] == "public-model"
    assert selected["model_reasoning_effort"] == "high"


def test_environment_url_does_not_invent_builtin_override(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import command_environment

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:5102/env/v1")
    selected = command_environment.settings("codex")
    assert "model_providers.trainlab_environment.base_url" not in selected
    assert (
        selected["inherited_environment"]["OPENAI_BASE_URL"]
        == "http://127.0.0.1:5102/env/v1"
    )


def test_custom_endpoint_and_environment_headers_preserve_toml(tmp_path, monkeypatch):
    import tomllib

    from skills._shared.fit_weekly import command_environment

    auth = tmp_path / ".codex"
    auth.mkdir()
    (auth / "config.toml").write_text(
        'model_provider="local"\nopenai_base_url="http://127.0.0.1:5101/ignored"\n'
        '[model_providers.local]\nname="Public"\nbase_url="http://127.0.0.1:5103/custom"\n'
        'wire_api="responses"\nenv_key="PUBLIC_KEY"\n'
        'env_http_headers={ "X.Public-Header"="PUBLIC_HEADER" }\n'
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(auth))
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:5102/ignored")
    monkeypatch.setenv("PUBLIC_KEY", "synthetic-auth-marker")
    monkeypatch.setenv("PUBLIC_HEADER", "synthetic-header-marker")
    selected = command_environment.settings("codex")
    runtime = command_runtime.Runtime(
        command_runtime.CommandSpec("codex", Path(sys.executable)),
        Path(__file__).resolve().parents[3],
        "Public",
        "Public",
        settings=selected,
    )
    argv = runtime.command(tmp_path, "2026-08-09T07:00:00Z", "0" * 64, tmp_path)
    definitions = {}
    for index, arg in enumerate(argv):
        if arg == "-c" and argv[index + 1].startswith("model_providers."):
            definitions.update(
                tomllib.loads(argv[index + 1])["model_providers"][
                    "trainlab_environment"
                ]
            )
    assert definitions["env_http_headers"] == {"X.Public-Header": "PUBLIC_HEADER"}
    assert definitions["base_url"] == "http://127.0.0.1:5103/custom"
    assert definitions["env_key"] == "PUBLIC_KEY"
    assert definitions["request_max_retries"] == definitions["stream_max_retries"] == 0
    env = runtime.environment(tmp_path)
    assert env["PUBLIC_KEY"] == "synthetic-auth-marker"
    assert env["PUBLIC_HEADER"] == "synthetic-header-marker"
    assert "synthetic-auth-marker" not in json.dumps(selected)
    assert "synthetic-header-marker" not in json.dumps(selected)


@pytest.mark.parametrize(
    "definition",
    [
        'name="Missing endpoint"',
        'name="Unsupported protocol"\nbase_url="http://127.0.0.1:5101"\nwire_api="chat"',
        'name="Embedded auth"\nbase_url="http://127.0.0.1:5101"\nhttp_headers={ Authorization="public" }',
        'name="Query auth"\nbase_url="http://127.0.0.1:5101?key=public"',
    ],
)
def test_unsupported_provider_routing_is_rejected(tmp_path, monkeypatch, definition):
    auth = tmp_path / ".codex"
    auth.mkdir()
    (auth / "config.toml").write_text(
        'model_provider="local"\n[model_providers.local]\n' + definition
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(auth))
    with pytest.raises(ValueError, match="command_environment_unavailable"):
        command_runtime.environment_settings("codex")
