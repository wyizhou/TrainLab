"""One durable adapter attempt per week; recovery never restarts inference.

This internal Host component has no model launcher or CLI. Mandatory business
validators belong to the eventual weekly input/result modules. An adapter must
confirm its child has stopped before returning or raising an ordinary Exception;
uncertain termination uses AdapterInterrupted and leaves a nonterminal intent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from skills._shared.fit_weekly import fit_detail, fit_sync, storage

InputValidator = Callable[[dict[str, Any]], None]
ResultValidator = Callable[[Any, dict[str, Any]], None]
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_model_receipt_v1.schema.json"
)


class AdapterInterrupted(BaseException):
    """No confirmed terminal model state; never turn this into a failed receipt."""


class Adapter(Protocol):
    profile: dict[str, Any]

    def run(
        self,
        payload: dict[str, Any],
        detail: fit_detail.DetailHost,
        response_schema: dict[str, Any],
    ) -> Any: ...


def clone(value: Any) -> Any:
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("model_json_invalid")
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    if value is None or type(value) in (bool, int, float, str):
        return json.loads(storage.canonical(value))
    raise ValueError("model_json_invalid")


def sha(value: Any) -> str:
    return storage.digest(storage.canonical(value).encode())


class FakeAdapter:
    """Explicitly synthetic adapter, not an AI-generated report fallback."""

    def __init__(self, output: Any, requests: list[dict[str, Any]]):
        self.output, self.requests = clone(output), clone(requests)
        self.calls = 0
        self.profile = {
            "kind": "fake",
            "name": "synthetic",
            "configuration_sha256": sha({"output": output, "requests": requests}),
        }

    def run(
        self,
        payload: dict[str, Any],
        detail: fit_detail.DetailHost,
        response_schema: dict[str, Any],
    ) -> Any:
        self.calls += 1
        for request in self.requests:
            detail.read(request)
        return clone(self.output)


def capture_path(root: Path, end: str) -> Path:
    fit_detail.period_key(end)
    return root / "model-results" / storage.digest(end.encode()) / "capture.json"


def schema_validator(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    if not isinstance(schema, dict):
        raise ValueError("model_schema_invalid")
    jsonschema.Draft202012Validator.check_schema(schema)
    registry = Registry().with_resource(
        "urn:trainlab:model-response",
        Resource.from_contents(schema, default_specification=DRAFT202012),
    )
    resolver = registry.resolver("urn:trainlab:model-response")
    pending: list[Any] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node is not schema and "$id" in node:
                raise ValueError("model_schema_nested_resource")
            for ref in ("$ref", "$dynamicRef"):
                if ref in node:
                    if not node[ref].startswith("#"):
                        raise ValueError("model_schema_external_reference")
                    if not isinstance(
                        resolver.lookup(node[ref]).contents, (dict, bool)
                    ):
                        raise ValueError("model_schema_reference_invalid")
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return jsonschema.Draft202012Validator(
        schema, registry=Registry(), format_checker=jsonschema.FormatChecker()
    )


def receipt(request: dict[str, Any], output: Any, error: str | None) -> dict[str, Any]:
    return {
        "schema_version": "fit_model_receipt_v1",
        "period_end_utc": request["period_end_utc"],
        "request_sha256": sha(request),
        "scope_sha256": request["scope_sha256"],
        "adapter_kind": request["profile"]["kind"],
        "adapter_attempts": 1,
        "model_attempts": int(request["profile"]["kind"] == "model"),
        "status": "succeeded" if error is None else "failed",
        "error_code": error,
        "output_sha256": sha(output),
        "provider_calls": 0,
        "external_actions": 0,
    }


def check_capture(
    value: Any,
    request: dict[str, Any],
    validator: jsonschema.Draft202012Validator,
    validate_result: ResultValidator,
) -> dict[str, Any]:
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "receipt", "output"}
            or value["schema_version"] != "fit_model_capture_v1"
        ):
            raise ValueError("shape")
        observed = value["receipt"]
        jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(
            observed
        )
        if observed != receipt(request, value["output"], observed["error_code"]):
            raise ValueError("binding")
        if observed["status"] == "succeeded":
            validator.validate(value["output"])
            validate_result(clone(value["output"]), clone(request["payload"]))
        return value
    except Exception:
        raise ValueError("model_capture_invalid") from None


def outcome(capture: dict[str, Any] | None, calls: int) -> dict[str, Any]:
    result = capture["receipt"] if capture else None
    return {
        "status": result["status"] if result else "unknown",
        "receipt": clone(result),
        "result": clone(capture["output"])
        if capture and result and result["status"] == "succeeded"
        else None,
        "invocation_adapter_calls": calls,
    }


def run(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    adapter: Adapter,
    *,
    validate_input: InputValidator,
    validate_result: ResultValidator,
) -> dict[str, Any]:
    try:
        fit_detail.period_key(period_end)
        storage.require_sha(scope_sha256)
        profile = clone(adapter.profile)
        if (
            set(profile) != {"kind", "name", "configuration_sha256"}
            or profile["kind"] not in ("fake", "model")
            or not isinstance(profile["name"], str)
            or not re.fullmatch("[a-z][a-z0-9_-]{0,63}", profile["name"])
        ):
            raise ValueError("profile")
        storage.require_sha(profile["configuration_sha256"])
        request = {
            "schema_version": "fit_model_request_v1",
            "period_end_utc": period_end,
            "scope_sha256": scope_sha256,
            "payload": clone(payload),
            "response_schema": clone(response_schema),
            "profile": profile,
        }
        if not isinstance(request["payload"], dict) or not callable(validate_result):
            raise ValueError("input")
        validate_input(clone(request["payload"]))
        validator = schema_validator(request["response_schema"])
        binding = sha(request)
    except Exception:
        raise ValueError("model_job_input_invalid") from None
    host = fit_detail.DetailHost(root, period_end, scope_sha256)
    path = capture_path(root, period_end)
    key = "model-job:" + period_end
    # The only winner is the invocation that commits a previously absent intent.
    # Merely seeing an old intent can never authorize another adapter invocation.
    try:
        with storage.open_store(root) as db:
            host.scope(db)
            previous = fit_detail.get(db, key + ":intent")
            saved = fit_detail.get(db, key + ":result")
            if previous is not None and previous != (binding, request):
                raise ValueError("model_job_input_conflict")
            if previous is None and (
                saved is not None or path.exists() or path.is_symlink()
            ):
                raise ValueError("model_job_orphan_capture")
            fit_sync.private_directory(path.parent.parent)
            fit_sync.private_directory(path.parent)
            if previous is None:
                fit_detail.put(db, key + ":intent", binding, request)
    except Exception as exc:
        code = str(exc)
        if code not in {
            "model_job_input_conflict",
            "model_job_orphan_capture",
            "detail_scope_binding_invalid",
        }:
            code = "model_job_preflight_unavailable"
        raise ValueError(code) from None
    calls = 0
    if previous is None:
        calls = 1
        error = None
        output = None
        try:
            output = adapter.run(
                clone(request["payload"]), host, clone(request["response_schema"])
            )
        except Exception:
            error = "model_adapter_failed"
        else:
            try:
                output = clone(output)
                validator.validate(output)
                validate_result(clone(output), clone(request["payload"]))
            except Exception:
                error = "model_result_invalid"
                try:
                    output = clone(output)
                except Exception:
                    output = None
        captured = {
            "schema_version": "fit_model_capture_v1",
            "receipt": receipt(request, output, error),
            "output": output,
        }
        try:
            storage.atomic_file(path, storage.canonical(captured).encode())
        except Exception:
            raise ValueError("model_job_persistence_unavailable") from None
    if not path.exists() and not path.is_symlink():
        if saved is not None:
            raise ValueError("model_capture_invalid")
        return outcome(None, calls)
    try:
        storage.private_entry(path, nonempty=True)
        raw = path.read_bytes()
        captured = json.loads(raw)
        if storage.canonical(captured).encode() != raw:
            raise ValueError("canonical")
        check_capture(captured, request, validator, validate_result)
        if saved is not None and saved != (binding, captured):
            raise ValueError("saved")
    except Exception:
        raise ValueError("model_capture_invalid") from None
    try:
        # Replay repeats durability barriers, not the adapter. A previous rename
        # may be visible although its directory fsync or final SQL commit failed.
        storage.atomic_file(path, raw)
        with storage.open_store(root) as db:
            if fit_detail.get(db, key + ":intent") != (binding, request):
                raise ValueError("intent")
            fit_detail.put(db, key + ":result", binding, captured)
    except Exception:
        raise ValueError("model_job_persistence_unavailable") from None
    return outcome(captured, calls)
