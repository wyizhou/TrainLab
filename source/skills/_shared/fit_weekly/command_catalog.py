from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import codex_output, storage


def component(executable: Path) -> dict[str, Any] | None:
    path = executable.resolve().with_name("codex-code-mode-host")
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("command_native_host_invalid")
    return {
        "path": str(path),
        "sha256": storage.digest(path.read_bytes()),
        "bytes": path.stat().st_size,
    }


def derive(raw: str) -> tuple[bytes, list[dict[str, Any]]]:
    value = codex_output.strict_json(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"models"}
        or not isinstance(value["models"], list)
        or not value["models"]
    ):
        raise ValueError("command_catalog_invalid")
    changes = []
    for index, model in enumerate(value["models"]):
        if not isinstance(model, dict) or not isinstance(model.get("slug"), str):
            raise ValueError("command_catalog_invalid")
        changes.append(
            {
                "index": index,
                "slug": model["slug"],
                "field": "apply_patch_tool_type",
                "before_present": "apply_patch_tool_type" in model,
                "before": model.get("apply_patch_tool_type"),
                "after": None,
            }
        )
        model["apply_patch_tool_type"] = None
    return storage.canonical(value).encode(), changes


def resolve(
    executable: Path, explicit: str | None, *, bundled_available: bool = False
) -> dict[str, Any]:
    home = Path(os.environ.get("CODEX_HOME", str(Path(os.environ["HOME"]) / ".codex")))
    cache = home / "models_cache.json"
    if explicit is not None:
        path = Path(explicit)
        if not path.is_absolute():
            raise ValueError("command_catalog_relative_source_unproven")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_194_304:
            raise ValueError("command_catalog_source_invalid")
        raw = path.read_text()
        kind, source = "configured", str(path)
    else:
        if cache.exists() or cache.is_symlink():
            raise ValueError("command_catalog_cache_unproven")
        if not bundled_available:
            raise ValueError("command_catalog_effective_source_unproven")
        if platform.system() != "Darwin":
            raise ValueError("command_catalog_offline_platform_unavailable")
        policy = "(version 1)(allow default)(deny network*)(deny file-write*)"
        args = [
            "/usr/bin/sandbox-exec",
            "-p",
            policy,
            str(executable),
            "debug",
            "models",
            "--bundled",
        ]
        result = subprocess.run(args, capture_output=True, timeout=20, check=False)
        if result.returncode != 0 or len(result.stdout) > 4_194_304:
            raise ValueError("command_catalog_offline_export_failed")
        raw = result.stdout.decode()
        kind, source = "bundled", str(executable.resolve())
    derived, changes = derive(raw)
    return {
        "source_kind": kind,
        "source": source,
        "original_sha256": storage.digest(raw.encode()),
        "derived_sha256": storage.digest(derived),
        "changes": changes,
        "original": raw,
    }


def validate(value: dict[str, Any]) -> bytes:
    derived, changes = derive(value["original"])
    if (
        storage.digest(value["original"].encode()) != value["original_sha256"]
        or storage.digest(derived) != value["derived_sha256"]
        or changes != value["changes"]
        or value["source_kind"] not in {"configured", "effective_cache", "bundled"}
    ):
        raise ValueError("command_catalog_binding_invalid")
    return derived
