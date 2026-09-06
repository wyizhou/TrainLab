"""Thin Codex adapter sharing the weekly intent/capture/recovery state machine.

Host-only internal API, not a public inference or authorization command. New
launches require retained public capability evidence; recovery requires only the
original prepared input and local result. Business validators remain mandatory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    codex_capability,
    codex_isolation,
    codex_output,
    codex_recovery,
    codex_runtime,
    fit_detail,
    fit_sync,
    model_job,
    model_process,
    process_capture,
    storage,
)
from skills._shared.fit_weekly.codex_runtime import Runtime


def files(spec: dict[str, Any]) -> dict[str, bytes]:
    return {
        "prepared.json": storage.canonical(spec).encode(),
        "prompt.txt": (
            spec["prompt_prefix"] + storage.canonical(spec["request"]["payload"])
        ).encode(),
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
            model_job.capture_path(root, spec["request"]["period_end_utc"]).parent
            / "codex"
        )

    @property
    def profile(self) -> dict[str, Any]:
        return model_job.clone(self._spec["request"]["profile"])

    def run(
        self,
        payload: dict[str, Any],
        detail: fit_detail.DetailHost,
        response_schema: dict[str, Any],
    ) -> Any:
        try:
            spec, request = self._spec, self._spec["request"]
            check_spec(spec)
            verify_files(self.work, spec)
            if (
                self.runtime is None
                or self.runtime.identity() != spec["runtime"]
                or payload != request["payload"]
                or response_schema != request["response_schema"]
                or detail.root != self.root
                or detail.scope_sha != request["scope_sha256"]
                or detail.key != fit_detail.period_key(request["period_end_utc"])[0]
            ):
                raise ValueError("binding")
            with storage.open_store(self.root) as db:
                if fit_detail.get(
                    db, "model-job:" + request["period_end_utc"] + ":intent"
                ) != (model_job.sha(request), request):
                    raise ValueError("intent")
            env = codex_runtime.environment(self.work)
            home = Path(env["HOME"])
            isolation = codex_isolation.prepare(
                work=self.work / "job",
                home=home,
                codex_home=Path(env.get("CODEX_HOME", str(home / ".codex"))),
            )
            isolation.validate_environment(env)
            argv = isolation.command(
                self.runtime.command(
                    self.root,
                    request["period_end_utc"],
                    request["scope_sha256"],
                    self.work,
                )
            )
        except Exception:
            raise ValueError("codex_launch_preflight_invalid") from None
        prompt = files(spec)["prompt.txt"]
        result = process_capture.run(
            self.work / "process",
            process_capture.binding(prompt, model_job.sha(request)),
            lambda: model_process.execute(
                argv, prompt=prompt, env=env, cwd=self.work / "job"
            ),
        )
        return codex_output.parse_result(
            result,
            response_schema,
            prompt_bytes=len(prompt),
            startup_messages=tuple(spec["capability"]["startup_messages"]),
        ).value


def prepare(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    *,
    runtime: Runtime,
    capability_path: Path,
    validate_input: model_job.InputValidator,
    validate_result: model_job.ResultValidator,
) -> CodexAdapter:
    try:
        root = codex_isolation.host_path(root).resolve()
        identity = runtime.identity()
        capability = codex_capability.read(
            capability_path, identity, runtime.instructions
        )
        request, _ = model_job.prepare_request(
            period_end,
            scope_sha256,
            payload,
            response_schema,
            profile(identity, capability),
            validate_input=validate_input,
            validate_result=validate_result,
        )
        spec = {
            "schema_version": "fit_codex_prepared_v1",
            "request": request,
            "runtime": identity,
            "capability": capability,
            "instructions": runtime.instructions,
            "prompt_prefix": runtime.prompt_prefix,
        }
        check_spec(spec)
        adapter = CodexAdapter(root, spec, runtime)
        # One instance writer publishes all preparation files. A concurrent
        # prepare must not replace a sibling file after another job starts.
        with storage.open_store(root) as db:
            fit_detail.DetailHost(root, period_end, scope_sha256).scope(db)
            for folder in (
                adapter.work.parent.parent,
                adapter.work.parent,
                adapter.work,
            ):
                fit_sync.private_directory(folder)
            for folder in ("job", "logs", "sqlite", "tmp"):
                fit_sync.private_directory(adapter.work / folder)
            env = codex_runtime.environment(adapter.work)
            home = Path(env["HOME"])
            isolation = codex_isolation.prepare(
                work=adapter.work / "job",
                home=home,
                codex_home=Path(env.get("CODEX_HOME", str(home / ".codex"))),
            )
            isolation.validate_environment(env)
            for name, raw in files(spec).items():
                storage.atomic_file(adapter.work / name, raw)
            verify_files(adapter.work, spec)
        return adapter
    except Exception:
        raise ValueError("codex_preparation_invalid") from None


def recover(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    *,
    validate_input: model_job.InputValidator,
    validate_result: model_job.ResultValidator,
) -> dict[str, Any]:
    work = model_job.capture_path(root, period_end).parent / "codex"
    try:
        spec = process_capture.read_json(work / "prepared.json", 64 * 1024 * 1024)
        check_spec(spec)
        verify_files(work, spec)
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
    )
