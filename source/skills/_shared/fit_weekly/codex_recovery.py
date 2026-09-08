"""Recover a previously stopped Codex capture into its existing weekly ledger.

No executable, environment, credential or external result path is accepted. A
future launcher supplies its frozen prompt/startup diagnostics and same adapter
profile. Full capability binding is still a launcher responsibility; this module
never creates a model attempt, starts a process, or contacts a model/provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import codex_output, model_job, process_capture, storage


def resume(
    root: Path,
    period_end: str,
    scope_sha256: str,
    payload: dict[str, Any],
    response_schema: dict[str, Any],
    adapter: model_job.Adapter,
    *,
    prompt: bytes,
    validate_input: model_job.InputValidator,
    validate_result: model_job.ResultValidator,
    startup_messages: tuple[str, ...] = (),
    stage: str | None = None,
) -> dict[str, Any]:
    # Invalid caller configuration is rejected before reading any job evidence.
    codex_output.wire_schema(response_schema)
    process_capture.binding(prompt, "0" * 64)
    if (
        type(startup_messages) is not tuple
        or any(not isinstance(s, str) or not s for s in startup_messages)
        or len(set(startup_messages)) != len(startup_messages)
    ):
        raise ValueError("codex_recovery_configuration_invalid")

    def read_completed(request: dict[str, Any]) -> model_job.RecoveredOutput | None:
        if (
            request["profile"]["kind"] != "model"
            or request["profile"]["name"] != "codex"
        ):
            return None
        work = (
            model_job.capture_path(root, period_end, stage=stage).parent
            / "codex"
            / "process"
        )
        expected = process_capture.binding(prompt, model_job.sha(request))
        try:
            storage.private_entry(work.parent, directory=True)
            result = process_capture.read_terminal(work, expected)
        except Exception:
            return None
        # Only this confirmed-stop capture may produce a terminal model error.
        # A missing/partial/corrupt stream container above remains unknown.
        try:
            parsed = codex_output.parse_result(
                result,
                response_schema,
                prompt_bytes=len(prompt),
                startup_messages=startup_messages,
            )
        except ValueError:
            return model_job.RecoveredOutput(error_code="model_adapter_failed")
        return model_job.RecoveredOutput(parsed.value)

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
