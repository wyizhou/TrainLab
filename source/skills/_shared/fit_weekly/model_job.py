"""One durable adapter attempt per weekly stage; recovery never restarts inference.

This internal Host component has no model launcher or CLI. Mandatory business
validators belong to the eventual weekly input/result modules. An adapter must
confirm its child has stopped before returning or raising an ordinary Exception;
uncertain termination uses AdapterInterrupted and leaves a nonterminal intent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from skills._shared.fit_weekly import fit_detail, fit_sync, stage_policy, storage

InputValidator = Callable[[dict[str, Any]], None]
ResultValidator = Callable[[Any, dict[str, Any]], None]
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_model_receipt_v1.schema.json"
)


class AdapterInterrupted(BaseException):
    """No confirmed terminal model state; never turn this into a failed receipt."""


@dataclass(frozen=True)
class RecoveredOutput:
    """Host-only proof reader result; not a model-provided recovery instruction."""

    output: Any = field(default=None, repr=False)
    error_code: str | None = None


RecoveryReader = Callable[[dict[str, Any]], RecoveredOutput | None]


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


def capture_path(root: Path, end: str, *, stage: str | None = None) -> Path:
    fit_detail.period_key(end)
    stage_policy.require(stage, legacy=True)
    identity = end + (":" + stage if stage else "")
    return root / "model-results" / storage.digest(identity.encode()) / "capture.json"


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
        "schema_version": "fit_model_receipt_v2"
        if "stage" in request
        else "fit_model_receipt_v1",
        **({"stage": request["stage"]} if "stage" in request else {}),
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
        path = (
            SCHEMA_PATH.with_name("fit_model_receipt_v2.schema.json")
            if "stage" in request
            else SCHEMA_PATH
        )
        jsonschema.Draft202012Validator(json.loads(path.read_text())).validate(observed)
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


def prepare_request(
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    profile: dict[str, Any],
    *,
    validate_input: InputValidator,
    validate_result: ResultValidator,
    stage: str | None = None,
) -> tuple[dict[str, Any], jsonschema.Draft202012Validator]:
    try:
        fit_detail.period_key(period_end)
        storage.require_sha(scope_sha256)
        stage_policy.require(stage, legacy=True)
        profile = clone(profile)
        if (
            set(profile) != {"kind", "name", "configuration_sha256"}
            or profile["kind"] not in ("fake", "model")
            or not isinstance(profile["name"], str)
            or not re.fullmatch("[a-z][a-z0-9_-]{0,63}", profile["name"])
        ):
            raise ValueError("profile")
        storage.require_sha(profile["configuration_sha256"])
        request = {
            "schema_version": "fit_model_request_v2"
            if stage
            else "fit_model_request_v1",
            **({"stage": stage} if stage else {}),
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
        return request, validator
    except Exception:
        raise ValueError("model_job_input_invalid") from None


def checked_result(
    request: dict[str, Any],
    output: Any,
    error: str | None,
    validator: jsonschema.Draft202012Validator,
    validate_result: ResultValidator,
) -> dict[str, Any]:
    if error is None:
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
    return {
        "schema_version": "fit_model_capture_v1",
        "receipt": receipt(request, output, error),
        "output": output,
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
    stage: str | None = None,
) -> dict[str, Any]:
    return _execute(
        root,
        period_end,
        scope_sha256,
        payload,
        response_schema,
        adapter,
        validate_input=validate_input,
        validate_result=validate_result,
        recovery=None,
        stage=stage,
    )


def recover(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    adapter: Adapter,
    *,
    validate_input: InputValidator,
    validate_result: ResultValidator,
    read_completed: RecoveryReader,
    stage: str | None = None,
) -> dict[str, Any]:
    """No new intent or adapter invocation; only Host-local evidence recovery.

    read_completed must read an already durable, confirmed-stop capture. None
    means there is no recoverable terminal. It must not launch or contact a model.
    This is a Host interface, never an AI tool or arbitrary result-file CLI.
    """
    if not callable(read_completed):
        raise ValueError("model_recovery_reader_invalid")
    return _execute(
        root,
        period_end,
        scope_sha256,
        payload,
        response_schema,
        adapter,
        validate_input=validate_input,
        validate_result=validate_result,
        recovery=read_completed,
        stage=stage,
    )


def _execute(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    adapter: Adapter,
    *,
    validate_input: InputValidator,
    validate_result: ResultValidator,
    recovery: RecoveryReader | None,
    stage: str | None,
) -> dict[str, Any]:
    stage_policy.require(stage, legacy=True)
    try:
        request, validator = prepare_request(
            period_end,
            scope_sha256,
            payload,
            response_schema,
            adapter.profile,
            validate_input=validate_input,
            validate_result=validate_result,
            stage=stage,
        )
    except Exception:
        raise ValueError("model_job_input_invalid") from None
    binding = sha(request)
    host = fit_detail.DetailHost(root, period_end, scope_sha256, stage=stage)
    path = capture_path(root, period_end, stage=stage)
    key = stage_policy.job_key(period_end, stage)
    # The only winner is the invocation that commits a previously absent intent.
    # Merely seeing an old intent can never authorize another adapter invocation.
    try:
        with storage.open_store(root) as db:
            host.scope(db)
            previous = fit_detail.get(db, key + ":intent")
            saved = fit_detail.get(db, key + ":result")
            if previous is None and stage is None:
                if recovery is not None:
                    return outcome(None, 0)
                raise ValueError("model_stage_required")
            if (
                stage is not None
                and fit_detail.get(db, stage_policy.job_key(period_end) + ":intent")
                is not None
            ):
                raise ValueError("model_legacy_week_occupied")
            if previous is None and stage == "summary" and recovery is None:
                plan = fit_detail.get(
                    db, stage_policy.job_key(period_end, "plan") + ":result"
                )
                if plan is None or plan[1]["receipt"]["status"] != "succeeded":
                    raise ValueError("model_plan_not_succeeded")
            if previous is not None and previous != (binding, request):
                raise ValueError("model_job_input_conflict")
            if previous is None and (
                saved is not None or path.exists() or path.is_symlink()
            ):
                raise ValueError("model_job_orphan_capture")
            if previous is None and recovery is not None:
                return outcome(None, 0)
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
            "model_stage_required",
            "model_legacy_week_occupied",
            "model_plan_not_succeeded",
        }:
            code = "model_job_preflight_unavailable"
        raise ValueError(code) from None
    calls = 0
    recovered: RecoveredOutput | None = None
    if (
        recovery is not None
        and saved is None
        and not path.exists()
        and not path.is_symlink()
    ):
        try:
            recovered = recovery(clone(request))
            if recovered is not None and (
                type(recovered) is not RecoveredOutput
                or recovered.error_code not in (None, "model_adapter_failed")
                or recovered.error_code is not None
                and recovered.output is not None
            ):
                raise ValueError("recovery_shape")
        except Exception:
            return outcome(None, 0)
        if recovered is None:
            return outcome(None, 0)
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
    elif recovered is not None:
        output, error = recovered.output, recovered.error_code
    if previous is None or recovered is not None:
        captured = checked_result(request, output, error, validator, validate_result)
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
