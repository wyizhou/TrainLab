"""Host-only launch settings. No configuration/authentication reads or writes."""

from __future__ import annotations

import math
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
    sync_calendar,
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
    timeout_seconds: float = 600
    authorization_expires_utc: str | None = None

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
                or isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0
            ):
                raise ValueError("settings")
            if self.authorization_expires_utc is not None:
                sync_calendar.utc_time(self.authorization_expires_utc)
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
                "version": "fit-codex-runtime-4",
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
                "timeout_seconds": self.timeout_seconds,
                "authorization_expires_utc": self.authorization_expires_utc,
                "instructions_sha256": storage.digest(self.instructions.encode()),
                "prompt_prefix_sha256": storage.digest(self.prompt_prefix.encode()),
                "tool_surface_sha256": codex_boundary.TOOL_SURFACE_SHA256,
            }
        except Exception:
            raise ValueError("codex_runtime_unavailable") from None

    def command(self, *args: Any, **kwargs: Any) -> list[str]:
        raise ValueError("legacy_command_readonly")
