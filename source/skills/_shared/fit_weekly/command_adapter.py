from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_facts,
    codex_isolation,
    codex_output,
    command_capability,
    command_output,
    fit_detail,
    fit_sync,
    model_job,
    model_process,
    process_capture,
    publication_ledger,
    stage_policy,
    storage,
    sync_calendar,
)
from skills._shared.fit_weekly.command_runtime import Runtime


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
    if spec["schema_version"] != "fit_command_prepared_v1":
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
    command_capability.validate(spec["capability"], identity, spec["instructions"])
    process_capture.binding(files(spec)["prompt.txt"], model_job.sha(spec["request"]))


def profile(identity: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "model",
        "name": "command",
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


class CommandAdapter:
    def __init__(self, root: Path, spec: dict[str, Any], runtime: Runtime | None):
        self.root, self._spec, self.runtime = root, model_job.clone(spec), runtime
        self.work = (
            model_job.capture_path(
                root,
                spec["request"]["period_end_utc"],
                stage=spec["request"].get("stage"),
            ).parent
            / "command"
        )

    @property
    def profile(self) -> dict[str, Any]:
        return model_job.clone(self._spec["request"]["profile"])

    def launch_materials(
        self, request: dict[str, Any]
    ) -> tuple[dict[str, str], list[str]]:
        try:
            check_spec(self._spec)
            verify_files(self.work, self._spec)
            if (
                self.runtime is None
                or self.runtime.identity() != self._spec["runtime"]
                or request != self._spec["request"]
            ):
                raise ValueError("binding")
            for folder in (
                self.work.parent.parent,
                self.work.parent,
                *(self.work / name for name in ("job", "logs", "sqlite", "tmp")),
            ):
                storage.private_entry(folder, directory=True)
            env = self.runtime.environment(self.work)
            mask = isolation(
                adapter=self.runtime.command_spec.adapter,
                work=self.work / "job",
                env=env,
            )
            mask.validate_environment({**env, "CODEX_HOME": str(mask.codex_home)})
            argv = mask.command(
                self.runtime.command(
                    self.root,
                    request["period_end_utc"],
                    request["scope_sha256"],
                    self.work,
                )
            )
            return env, argv
        except Exception:
            raise ValueError("command_launch_preflight_invalid") from None

    def validate_new_attempt(self, request: dict[str, Any]) -> dict[str, str]:
        env, _ = self.launch_materials(request)
        return env

    def run(
        self,
        payload: dict[str, Any],
        detail: fit_detail.DetailHost,
        response_schema: dict[str, Any],
    ) -> Any:
        try:
            spec, request = self._spec, self._spec["request"]
            env, argv = self.launch_materials(request)
            if (
                self.runtime is None
                or payload != request["payload"]
                or response_schema != request["response_schema"]
                or detail.root != self.root
                or detail.scope_sha != request["scope_sha256"]
                or detail.key != fit_detail.period_key(request["period_end_utc"])[0]
                or detail.stage != request.get("stage")
            ):
                raise ValueError("binding")
            with storage.open_store(self.root) as db:
                if fit_detail.get(
                    db,
                    stage_policy.job_key(
                        request["period_end_utc"], request.get("stage")
                    )
                    + ":intent",
                ) != (model_job.sha(request), request):
                    raise ValueError("intent")
            runtime = self.runtime
        except Exception:
            raise ValueError("command_launch_preflight_invalid") from None
        prompt = files(spec)["prompt.txt"]

        def execute() -> model_process.ProcessResult:
            timeout = runtime.timeout_seconds
            if runtime.authorization_expires_utc is not None:
                timeout = min(
                    timeout,
                    (
                        sync_calendar.utc_time(runtime.authorization_expires_utc)
                        - sync_calendar.utc_time(publication_ledger.utc_now())
                    ).total_seconds(),
                )
                if timeout <= 0:
                    return model_process.ProcessResult(
                        None, 0, b"", b"", "process_authorization_expired"
                    )
            return model_process.execute(
                argv, prompt=prompt, env=env, cwd=self.work / "job", timeout=timeout
            )

        result = process_capture.run(
            self.work / "process",
            process_capture.binding(prompt, model_job.sha(request)),
            execute,
        )
        return command_output.parse_result(
            result,
            response_schema,
            prompt_bytes=len(prompt),
            adapter=runtime.command_spec.adapter,
        )


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
    stage: str | None = None,
) -> CommandAdapter:
    try:
        stage_policy.require(stage)
        if runtime.stage != stage:
            raise ValueError("stage")
        root = codex_isolation.host_path(root).resolve()
        identity = runtime.identity()
        capability = command_capability.read(
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
            stage=stage,
        )
        spec = {
            "schema_version": "fit_command_prepared_v1",
            "request": request,
            "runtime": identity,
            "capability": capability,
            "instructions": runtime.instructions,
            "prompt_prefix": runtime.prompt_prefix,
        }
        check_spec(spec)
        adapter = CommandAdapter(root, spec, runtime)
        # One instance writer publishes all preparation files. A concurrent
        # prepare must not replace a sibling file after another job starts.
        with storage.open_store(root) as db:
            fit_detail.DetailHost(root, period_end, scope_sha256, stage=stage).scope(db)
            existing = fit_detail.get(
                db, stage_policy.job_key(period_end, stage) + ":intent"
            )
            if existing is not None and existing != (model_job.sha(request), request):
                raise ValueError("intent")
            for folder in (
                adapter.work.parent.parent,
                adapter.work.parent,
                adapter.work,
            ):
                fit_sync.private_directory(folder)
            for folder in ("job", "logs", "sqlite", "tmp"):
                fit_sync.private_directory(adapter.work / folder)
            env = runtime.environment(adapter.work)
            mask = isolation(
                adapter=runtime.command_spec.adapter,
                work=adapter.work / "job",
                env=env,
            )
            mask.validate_environment({**env, "CODEX_HOME": str(mask.codex_home)})
            for name, raw in files(spec).items():
                storage.atomic_file(adapter.work / name, raw)
            verify_files(adapter.work, spec)
        return adapter
    except Exception:
        raise ValueError("command_preparation_invalid") from None


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
    work = model_job.capture_path(root, period_end, stage=stage).parent / "command"
    if not work.exists() and not work.is_symlink():
        from skills._shared.fit_weekly import codex_adapter

        return codex_adapter.recover(
            root,
            period_end,
            scope_sha256,
            payload,
            response_schema,
            validate_input=validate_input,
            validate_result=validate_result,
            stage=stage,
        )
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
    adapter = CommandAdapter(root, spec, None)
    prompt = files(spec)["prompt.txt"]

    def read_completed(request: dict[str, Any]) -> model_job.RecoveredOutput | None:
        if request["profile"] != adapter.profile:
            return None
        try:
            result = process_capture.read_terminal(
                work / "process",
                process_capture.binding(prompt, model_job.sha(request)),
            )
        except Exception:
            return None
        try:
            value = command_output.parse_result(
                result,
                response_schema,
                prompt_bytes=len(prompt),
                adapter=spec["runtime"]["command"]["adapter"],
            )
        except ValueError:
            return model_job.RecoveredOutput(error_code="model_adapter_failed")
        return model_job.RecoveredOutput(value)

    return model_job.recover(
        root,
        period_end,
        scope_sha256,
        payload,
        response_schema,
        adapter,
        validate_input=validate_input,
        validate_result=validate_result,
        read_completed=read_completed,
        stage=stage,
    )


def isolation(
    *, adapter: str, work: Path, env: dict[str, str]
) -> codex_isolation.Isolation:
    home = Path(env["HOME"])
    auth = Path(env.get("CODEX_HOME", str(home / ".codex")))
    if adapter == "claude":
        auth = Path(env.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
        masks = [
            home / ".claude" / name
            for name in (
                "CLAUDE.md",
                "skills",
                "plugins",
                "agents",
                "commands",
                "projects",
            )
        ]
        masks += [parent / "CLAUDE.md" for parent in (work, *work.parents)]
        masks += [
            Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
            Path("/etc/claude-code/managed-settings.json"),
        ]
        return codex_isolation.prepare(
            work=work, home=home, codex_home=auth, extra_masks=tuple(masks)
        )
    return codex_isolation.prepare(work=work, home=home, codex_home=auth)
