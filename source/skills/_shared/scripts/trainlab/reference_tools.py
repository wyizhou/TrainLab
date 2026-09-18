"""Restricted public reference reader for AI tool dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import (
    REFERENCE_CONTRACTS,
    ReferenceId,
    ToolAuthorization,
    validate_payload,
)


def read_reference(
    request: Mapping[str, Any],
    *,
    project_root: Path,
    authorization: ToolAuthorization,
) -> dict[str, Any]:
    payload = dict(request)
    try:
        validate_payload("ReadReferenceRequest", payload)
    except ValueError:
        return _failure(ErrorCode.INVALID_ARGUMENT, "request must contain exactly reference_id")
    reference_id = payload["reference_id"]
    if reference_id not in REFERENCE_CONTRACTS:
        return _failure(ErrorCode.INVALID_ARGUMENT, "reference is not registered")
    typed_id = cast(ReferenceId, reference_id)  # jsonschema has narrowed this to the ReferenceId literals.
    if not authorization.can_read_reference(typed_id):
        return _failure(ErrorCode.TOOL_NOT_ALLOWED, "reference is not authorized")
    contract = REFERENCE_CONTRACTS[typed_id]
    try:
        path = _inside_project(project_root, contract.relative_path)
        content = path.read_text(encoding="utf-8")
    except OSError:
        return _failure(ErrorCode.CONFIG_UNAVAILABLE, "reference is unavailable")
    result: dict[str, Any] = {
        "ok": True,
        "data": {
            "reference_id": typed_id,
            "title": _title(content, contract.purpose),
            "content": content,
        },
        "error": None,
    }
    validate_payload("ReadReferenceResult", result)
    return result


def _inside_project(project_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise OSError("reference path must be relative")
    root = project_root.resolve(strict=False)
    path = (root / relative_path).resolve(strict=False)
    path.relative_to(root)
    return path


def _title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _failure(code: ErrorCode, message: str) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "data": None, "error": {"code": code.value, "message": message, "details": {}}}
    validate_payload("ReadReferenceResult", result)
    return result
