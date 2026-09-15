from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from skills._shared.fit_weekly import codex_output, command_catalog, storage

BASE_ENV = (
    "HOME",
    "PATH",
    "LANG",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "NO_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
CLAUDE_SELECTION = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "AWS_REGION",
    "AWS_PROFILE",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLOUD_ML_REGION",
    "ANTHROPIC_FOUNDRY_RESOURCE",
)
CLAUDE_AUTH = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_FOUNDRY_API_KEY",
)
CODEX_SELECTION = ("OPENAI_BASE_URL", "CHATGPT_CODEX_BASE_URL")


def document(path: Path, *, toml: bool = False) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_048_576:
        raise ValueError("command_environment_invalid")
    raw = path.read_bytes()
    value = (
        tomllib.loads(raw.decode()) if toml else codex_output.strict_json(raw.decode())
    )
    if not isinstance(value, dict):
        raise ValueError("command_environment_invalid")
    return value


def scalar(value: Any) -> Any:
    if (
        not isinstance(value, (str, bool, int))
        or isinstance(value, str)
        and (not value or len(value) > 8192 or any(ord(c) < 32 for c in value))
    ):
        raise ValueError("command_environment_invalid")
    return value


def endpoint(value: Any) -> str:
    scalar(value)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("command_environment_invalid")
    return value


def settings(adapter: str, executable: Path | None = None) -> dict[str, Any]:
    try:
        home = Path(os.environ["HOME"])
        result: dict[str, Any] = {}
        if adapter == "codex":
            auth = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
            value = document(auth / "config.toml", toml=True)
            selected = dict(value)
            if value.get("profile"):
                selected.update(value.get("profiles", {})[value["profile"]])
            for name in (
                "model",
                "model_reasoning_effort",
                "model_reasoning_summary",
                "model_verbosity",
                "model_catalog_json",
                "cli_auth_credentials_store",
                "openai_base_url",
                "chatgpt_base_url",
            ):
                if name in selected:
                    result[name] = (
                        endpoint(selected[name])
                        if name.endswith("base_url")
                        else scalar(selected[name])
                    )
            provider = selected.get("model_provider", "openai")
            if provider == "openai":
                definition = {"name": "OpenAI", "requires_openai_auth": True}
                if "openai_base_url" in result:
                    definition["base_url"] = result["openai_base_url"]
            else:
                definition = selected.get("model_providers", {}).get(provider)
                if not isinstance(definition, dict):
                    raise ValueError("provider")
                if (
                    "base_url" not in definition
                    or definition.get("wire_api", "responses") != "responses"
                ):
                    raise ValueError("provider_configuration_unsupported")
                if set(definition) - {
                    "name",
                    "base_url",
                    "wire_api",
                    "env_key",
                    "env_key_instructions",
                    "requires_openai_auth",
                    "request_max_retries",
                    "stream_max_retries",
                    "stream_idle_timeout_ms",
                    "supports_websockets",
                    "env_http_headers",
                }:
                    raise ValueError("provider_configuration_unsupported")
            result["model_provider"] = "trainlab_environment"
            for name, item in definition.items():
                if name in (
                    "request_max_retries",
                    "stream_max_retries",
                    "supports_websockets",
                    "env_key_instructions",
                ):
                    continue
                if name == "env_http_headers":
                    if not isinstance(item, dict) or any(
                        not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(v))
                        for v in item.values()
                    ):
                        raise ValueError("headers")
                elif name == "base_url":
                    item = endpoint(item)
                else:
                    item = scalar(item)
                result["model_providers.trainlab_environment." + name] = item
            result.update(
                {
                    "model_providers.trainlab_environment.request_max_retries": 0,
                    "model_providers.trainlab_environment.stream_max_retries": 0,
                    "model_providers.trainlab_environment.supports_websockets": False,
                }
            )
            result["inherited_environment"] = {
                k: endpoint(os.environ[k]) for k in CODEX_SELECTION if k in os.environ
            }
            if executable is not None and command_catalog.component(executable):
                result["native_catalog"] = command_catalog.resolve(
                    executable,
                    result.get("model_catalog_json"),
                    bundled_available=(
                        definition.get("requires_openai_auth") is False
                        and not definition.get("env_key")
                        and not os.environ.get("OPENAI_API_KEY")
                        and not (auth / "auth.json").exists()
                        and not selected.get("features")
                    ),
                )
        elif adapter == "claude":
            directory = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
            value = document(directory / "settings.json")
            for name in ("model", "effortLevel"):
                if name in value:
                    result[name] = scalar(value[name])
            configured = value.get("env", {})
            if not isinstance(configured, dict):
                raise ValueError("environment")
            result["inherited_environment"] = {
                k: scalar(os.environ.get(k, configured[k] if k in configured else ""))
                for k in CLAUDE_SELECTION
                if k in os.environ or k in configured
            }
            for name in ("ANTHROPIC_BASE_URL",):
                if name in result["inherited_environment"]:
                    endpoint(result["inherited_environment"][name])
            if value.get("apiKeyHelper"):
                raise ValueError("command_auth_helper_unsupported")
        else:
            raise ValueError("adapter")
        storage.canonical(result)
        return result
    except Exception:
        raise ValueError("command_environment_unavailable") from None


def environment(work: Path, adapter: str, selected: dict[str, Any]) -> dict[str, str]:
    env = {k: os.environ[k] for k in BASE_ENV if k in os.environ}
    env.update(selected.get("inherited_environment", {}))
    auth_names = list(CLAUDE_AUTH) if adapter == "claude" else ["OPENAI_API_KEY"]
    configured_auth: dict[str, str] = {}
    if adapter == "claude":
        home = Path(os.environ["HOME"])
        directory = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
        configured = document(directory / "settings.json").get("env", {})
        configured_auth = {
            k: configured[k]
            for k in CLAUDE_AUTH
            if k in configured and isinstance(configured[k], str)
        }
    if adapter == "codex":
        key = selected.get("model_providers.trainlab_environment.env_key")
        if key:
            auth_names.append(key)
        auth_names.extend(
            selected.get(
                "model_providers.trainlab_environment.env_http_headers", {}
            ).values()
        )
    env.update(configured_auth)
    env.update({k: os.environ[k] for k in auth_names if k in os.environ})
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(work / "tmp"))
    if adapter == "claude":
        env.update(
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            CLAUDE_CODE_DISABLE_CLAUDE_MDS="1",
            CLAUDE_CODE_MAX_RETRIES="0",
            CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK="1",
            MAX_STRUCTURED_OUTPUT_RETRIES="0",
            MAX_MCP_OUTPUT_TOKENS="1000000",
            ENABLE_TOOL_SEARCH="false",
            CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        )
    return env
