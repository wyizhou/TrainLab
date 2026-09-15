from __future__ import annotations

import math
import os
import platform
import sys
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    codex_boundary,
    codex_isolation,
    command_catalog,
    command_environment,
    model_job,
    runtime_resources,
    stage_policy,
    storage,
    sync_calendar,
)

ADAPTERS = ("codex", "claude")
environment_settings = command_environment.settings


@dataclass(frozen=True)
class CommandSpec:
    adapter: str
    executable: Path

    def identity(self) -> dict[str, Any]:
        codex_isolation.host_path(self.executable)
        if (
            self.adapter not in ADAPTERS
            or not self.executable.is_file()
            or not os.access(self.executable, os.X_OK)
        ):
            raise ValueError("command_spec_invalid")
        return {
            "adapter": self.adapter,
            "protocol": "fit-command-1",
            "executable": str(self.executable.resolve()),
            "executable_sha256": storage.digest(self.executable.read_bytes()),
        }

    @property
    def key(self) -> str:
        return model_job.sha(self.identity())


@dataclass(frozen=True)
class Runtime:
    command_spec: CommandSpec
    source: Path
    instructions: str = field(repr=False)
    prompt_prefix: str = field(repr=False)
    stage: str = "plan"
    timeout_seconds: float = 600
    authorization_expires_utc: str | None = None
    settings: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def executable(self) -> Path:
        return self.command_spec.executable

    def identity(self) -> dict[str, Any]:
        try:
            stage_policy.require(self.stage)
            command = self.command_spec.identity()
            if (
                self.source.resolve() / "skills/_shared/fit_weekly"
                != Path(__file__).resolve().parent
                or any(
                    not isinstance(s, str)
                    or not s.strip()
                    or "\0" in s
                    or len(s.encode()) > 131072
                    for s in (self.instructions, self.prompt_prefix)
                )
                or isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (float, int))
                or not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0
            ):
                raise ValueError("settings")
            if self.authorization_expires_utc is not None:
                sync_calendar.utc_time(self.authorization_expires_utc)
            dependencies = runtime_resources.files(
                self.source, entrypoint=True, legacy_reader=False
            )
            identity = {
                "version": "fit-command-runtime-1",
                "command": command,
                "environment_settings": model_job.clone(self.settings),
                "stage": self.stage,
                "platform": platform.system(),
                "isolation": codex_isolation.VERSION,
                "python_sha256": storage.digest(Path(sys.executable).read_bytes()),
                "packages": {
                    name: version(name)
                    for name in ("fitdecode", "jsonschema", "referencing", "mcp")
                },
                "source_sha256": model_job.sha(
                    {
                        str(p.relative_to(self.source)): storage.digest(p.read_bytes())
                        for p in dependencies
                    }
                ),
                "timeout_seconds": self.timeout_seconds,
                "authorization_expires_utc": self.authorization_expires_utc,
                "instructions_sha256": storage.digest(self.instructions.encode()),
                "prompt_prefix_sha256": storage.digest(self.prompt_prefix.encode()),
            }
            if "native_catalog" in self.settings:
                command_catalog.validate(self.settings["native_catalog"])
                identity["native_host"] = command_catalog.component(self.executable)
                if identity["native_host"] is None:
                    raise ValueError("native_host_missing")
            return identity
        except Exception:
            raise ValueError("command_runtime_unavailable") from None

    def environment(self, work: Path) -> dict[str, str]:
        if (
            environment_settings(
                self.command_spec.adapter,
                self.executable if "native_catalog" in self.settings else None,
            )
            != self.settings
        ):
            raise ValueError("command_environment_drift")
        return command_environment.environment(
            work, self.command_spec.adapter, self.settings
        )

    def command(self, instance: Path, end: str, scope: str, work: Path) -> list[str]:
        adapter = self.command_spec.adapter
        if adapter == "codex":
            args = [
                str(self.command_spec.executable),
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--strict-config",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-C",
                str(work / "job"),
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
            for key, value in self.settings.items():
                if key not in {"inherited_environment", "native_catalog"} and not (
                    key == "model_catalog_json" and "native_catalog" in self.settings
                ):
                    encoded = (
                        "{"
                        + ",".join(
                            storage.canonical(k) + "=" + storage.canonical(v)
                            for k, v in value.items()
                        )
                        + "}"
                        if isinstance(value, dict)
                        else storage.canonical(value)
                    )
                    args += ["-c", key + "=" + encoded]
            if "native_catalog" in self.settings:
                catalog = self.settings["native_catalog"]
                storage.atomic_file(
                    work / "models.original.json", catalog["original"].encode()
                )
                storage.atomic_file(
                    work / "models.json", command_catalog.validate(catalog)
                )
                args += [
                    "-c",
                    "features.code_mode_host=true",
                    "-c",
                    "features.code_mode=true",
                    "-c",
                    "agents.enabled=false",
                    "-c",
                    "features.tool_search=false",
                    "-c",
                    "model_catalog_json="
                    + storage.canonical(str(work / "models.json")),
                ]
            return [*args, "--output-schema", str(work / "response.schema.json"), "-"]
        if adapter == "claude":
            mcp = {
                "mcpServers": {
                    "fit": {
                        "command": str(sys.executable),
                        "args": [
                            "-m",
                            "skills._shared.fit_weekly.detail_server",
                            "--instance-root",
                            str(instance),
                            "--period-end",
                            end,
                            "--scope-sha256",
                            scope,
                            "--stage",
                            self.stage,
                            "--compact",
                            "--text-only",
                        ],
                        "env": {
                            "PYTHONPATH": str(self.source),
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                    }
                }
            }
            settings = {
                k: v for k, v in self.settings.items() if k != "inherited_environment"
            }
            settings.update(disableAllHooks=True, autoMemoryEnabled=False)
            system = (
                self.instructions
                + "\nReturn exactly one JSON object matching this response schema:\n"
                + (work / "response.schema.json").read_text()
            )
            return [
                str(self.command_spec.executable),
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                "--setting-sources",
                "",
                "--disable-slash-commands",
                "--strict-mcp-config",
                "--mcp-config",
                storage.canonical(mcp),
                "--allowedTools",
                "mcp__fit__read_fit_detail",
                "--permission-mode",
                "dontAsk",
                "--no-session-persistence",
                "--no-chrome",
                "--system-prompt",
                system,
                "--settings",
                storage.canonical(settings),
            ]
        raise ValueError("command_adapter_unknown")
