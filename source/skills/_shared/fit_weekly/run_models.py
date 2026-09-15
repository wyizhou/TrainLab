from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching,
    coaching_contract,
    command_runtime,
    run_authorization,
    run_config,
)


def contracts(
    config: run_config.Config,
    end: str,
    grant: run_authorization.Grant | None,
    *,
    now: Callable[[], str],
) -> tuple:
    settings: dict[str, Any] = {}

    def runtime(stage: str) -> command_runtime.Runtime:
        if grant is None:
            raise ValueError("model_new_call_not_authorized")
        grant.check_frozen(config.root)
        grant.freeze(config.root, now=now())
        value = config.service("model")
        if (
            set(value) != {"command", "instructions", "stages"}
            or not isinstance(value["stages"], dict)
            or set(value["stages"]) != {"plan", "summary"}
        ):
            raise ValueError("model_config_invalid")
        for part in value["stages"].values():
            if not isinstance(part, dict) or set(part) != {"capability"}:
                raise ValueError("model_config_invalid")
        command = value["command"]
        if not isinstance(command, dict) or set(command) != {"adapter", "executable"}:
            raise ValueError("model_config_invalid")
        executable = Path(command["executable"])
        if not executable.is_absolute():
            executable = run_config.relative_path(config.root, command["executable"])
        spec = command_runtime.CommandSpec(command["adapter"], executable)
        permission = grant.command(end, stage, spec.key, now=now())
        settings[stage] = value["stages"][stage]
        return command_runtime.Runtime(
            command_spec=spec,
            source=run_config.SOURCE,
            instructions=value["instructions"],
            prompt_prefix=coaching_contract.prompt(stage),
            stage=stage,
            timeout_seconds=permission.timeout_seconds,
            authorization_expires_utc=grant.expires_utc,
            settings=command_runtime.environment_settings(
                spec.adapter, spec.executable
            ),
        )

    def capability(stage: str) -> Path:
        return run_config.private_path(config.root, settings[stage]["capability"])

    return coaching.command_contracts(
        config.root,
        end,
        runtimes={
            stage: lambda current=stage: runtime(current)
            for stage in ("plan", "summary")
        },
        capability_paths={
            stage: lambda current=stage: capability(current)
            for stage in ("plan", "summary")
        },
    )
