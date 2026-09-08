"""Host-only launch settings. No configuration/authentication reads or writes."""

from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    codex_boundary,
    codex_isolation,
    model_job,
    runtime_resources,
    stage_policy,
    storage,
)


@dataclass(frozen=True)
class Runtime:
    executable: Path
    source: Path
    model: str
    credential_store: str
    instructions: str = field(repr=False)
    prompt_prefix: str = field(repr=False)
    stage: str = "plan"

    def identity(self) -> dict[str, Any]:
        try:
            stage_policy.require(self.stage)
            for path in (self.executable, self.source):
                codex_isolation.host_path(path)
            if (
                not self.executable.is_file()
                or not os.access(self.executable, os.X_OK)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", self.model)
                or self.credential_store not in ("file", "keyring", "auto")
                or any(
                    not isinstance(s, str) or not s.strip() or "\0" in s
                    for s in (self.instructions, self.prompt_prefix)
                )
                or len(self.instructions.encode()) > 131072
                or len(self.prompt_prefix.encode()) > 131072
            ):
                raise ValueError("settings")
            # Bind only actual current code/contract dependencies. Archives,
            # tests and retired daily resources never influence this identity.
            folder = self.source / "skills/_shared/fit_weekly"
            paths = runtime_resources.files(self.source)
            if folder.resolve() != Path(__file__).resolve().parent:
                raise ValueError("source")
            source_hash = model_job.sha(
                {
                    str(p.relative_to(self.source)): storage.digest(p.read_bytes())
                    for p in paths
                }
            )
            return {
                "version": "fit-codex-runtime-3",
                "stage": self.stage,
                "platform": platform.system(),
                "isolation": codex_isolation.VERSION,
                "executable_sha256": storage.digest(self.executable.read_bytes()),
                "python_sha256": storage.digest(Path(sys.executable).read_bytes()),
                "packages": {
                    name: version(name)
                    for name in ("fitdecode", "jsonschema", "referencing", "mcp")
                },
                "source_sha256": source_hash,
                "model": self.model,
                "credential_store": self.credential_store,
                "instructions_sha256": storage.digest(self.instructions.encode()),
                "prompt_prefix_sha256": storage.digest(self.prompt_prefix.encode()),
                "tool_surface_sha256": codex_boundary.TOOL_SURFACE_SHA256,
            }
        except Exception:
            raise ValueError("codex_runtime_unavailable") from None

    def command(self, instance: Path, end: str, scope: str, work: Path) -> list[str]:
        args = [
            str(self.executable),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--color",
            "never",
            "-C",
            str(work / "job"),
            "-m",
            self.model,
        ]
        args += codex_boundary.configuration_arguments(
            source=self.source,
            instance=instance,
            work=work,
            python=Path(sys.executable),
            period_end=end,
            scope_sha256=scope,
            stage=self.stage,
        )
        for key, value in {
            "model_provider": "trainlab_openai",
            "cli_auth_credentials_store": self.credential_store,
            # Reserved builtin IDs cannot be overridden. This named provider
            # retains Codex's OpenAI login/default endpoints, without supplying
            # a bearer token, proxy URL, environment key or auth command.
            "model_providers.trainlab_openai.name": "OpenAI",
            "model_providers.trainlab_openai.requires_openai_auth": True,
            "model_providers.trainlab_openai.request_max_retries": 0,
            "model_providers.trainlab_openai.stream_max_retries": 0,
            "model_providers.trainlab_openai.supports_websockets": False,
        }.items():
            args += ["-c", key + "=" + storage.canonical(value)]
        return [*args, "--output-schema", str(work / "response.schema.json"), "-"]


def environment(work: Path) -> dict[str, str]:
    # Preserve the chosen existing credential location, not arbitrary ambient
    # provider URLs, API keys, config overrides, shell startup or Python paths.
    env = {
        k: os.environ[k]
        for k in ("HOME", "CODEX_HOME", "PATH", "LANG")
        if k in os.environ
    }
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(work / "tmp"))
    return env
