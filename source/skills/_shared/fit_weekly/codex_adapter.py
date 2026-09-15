"""Thin Codex adapter sharing the weekly intent/capture/recovery state machine.

Host-only internal API, not a public inference or authorization command. New
launches require retained public capability evidence; recovery requires only the
original prepared input and local result. Business validators remain mandatory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_facts,
    codex_capability,
    codex_output,
    codex_recovery,
    model_job,
    process_capture,
    storage,
)
from skills._shared.fit_weekly.codex_runtime import Runtime


def files(spec: dict[str, Any]) -> dict[str, bytes]:
    prefix = spec["prompt_prefix"]
    request = spec["request"]
    version = (
        request["response_schema"]
        .get("properties", {})
        .get("schema_version", {})
        .get("const")
    )
    if version in coaching_contract.VERSIONS.values():
        stage = request.get("stage")
        if (
            stage not in coaching_contract.VERSIONS
            or version != coaching_contract.VERSIONS[stage]
        ):
            raise ValueError("coaching_stage_invalid")
        coaching_contract.check(stage)
        if prefix != coaching_contract.prompt(stage) or request[
            "response_schema"
        ] != coaching_contract.schema(stage):
            raise ValueError("coaching_runtime_prompt_invalid")
        prefix += (
            "\nHOST_FACTS\n"
            + storage.canonical(coaching_facts.build(request["payload"]))
            + "\nSTAGE_PAYLOAD\n"
        )
    return {
        "prepared.json": storage.canonical(spec).encode(),
        "prompt.txt": (prefix + storage.canonical(spec["request"]["payload"])).encode(),
        "instructions.txt": spec["instructions"].encode(),
        "response.schema.json": storage.canonical(
            codex_output.wire_schema(spec["request"]["response_schema"])
        ).encode(),
    }


def check_spec(spec: Any) -> None:
    codex_output.keys(
        spec,
        {
            "schema_version",
            "request",
            "runtime",
            "capability",
            "instructions",
            "prompt_prefix",
        },
    )
    if spec["schema_version"] != "fit_codex_prepared_v1":
        raise ValueError("spec")
    identity = spec["runtime"]
    if (
        storage.digest(spec["instructions"].encode()) != identity["instructions_sha256"]
        or storage.digest(spec["prompt_prefix"].encode())
        != identity["prompt_prefix_sha256"]
        or spec["request"]["profile"] != profile(identity, spec["capability"])
    ):
        raise ValueError("binding")
    if "stage" in spec["request"] and identity.get("stage") != spec["request"]["stage"]:
        raise ValueError("binding")
    codex_capability.validate(spec["capability"], identity, spec["instructions"])
    process_capture.binding(files(spec)["prompt.txt"], model_job.sha(spec["request"]))


def profile(identity: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "model",
        "name": "codex",
        "configuration_sha256": model_job.sha(
            {
                "runtime": identity,
                "capability_sha256": model_job.sha(capability),
            }
        ),
    }


def verify_files(work: Path, spec: dict[str, Any]) -> None:
    storage.private_entry(work, directory=True)
    for name, raw in files(spec).items():
        path = work / name
        storage.private_entry(path, nonempty=True)
        if path.stat().st_size != len(raw) or path.read_bytes() != raw:
            raise ValueError("prepared")


class CodexAdapter:
    def __init__(self, root: Path, spec: dict[str, Any], runtime: Runtime | None):
        self.root, self._spec, self.runtime = root, model_job.clone(spec), runtime
        self.work = (
            model_job.capture_path(
                root,
                spec["request"]["period_end_utc"],
                stage=spec["request"].get("stage"),
            ).parent
            / "codex"
        )

    @property
    def profile(self) -> dict[str, Any]:
        return model_job.clone(self._spec["request"]["profile"])

    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("legacy_command_readonly")


def prepare(*args: Any, **kwargs: Any) -> Any:
    raise ValueError("legacy_command_readonly")


def recover(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    *,
    validate_input: model_job.InputValidator,
    validate_result: model_job.ResultValidator,
    stage: str | None = None,
) -> dict[str, Any]:
    work = model_job.capture_path(root, period_end, stage=stage).parent / "codex"
    try:
        spec = process_capture.read_json(work / "prepared.json", 64 * 1024 * 1024)
        check_spec(spec)
        verify_files(work, spec)
        if (
            spec["request"].get("stage") != stage
            or spec["request"]["period_end_utc"] != period_end
        ):
            raise ValueError("stage")
    except Exception:
        return model_job.outcome(None, 0)
    return codex_recovery.resume(
        root,
        period_end,
        scope_sha256,
        payload,
        response_schema,
        CodexAdapter(root, spec, None),
        prompt=files(spec)["prompt.txt"],
        validate_input=validate_input,
        validate_result=validate_result,
        startup_messages=tuple(spec["capability"]["startup_messages"]),
        stage=stage,
    )
