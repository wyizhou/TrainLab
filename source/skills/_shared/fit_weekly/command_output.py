from __future__ import annotations

from typing import Any

from skills._shared.fit_weekly import codex_output, model_job, model_process


def parse_result(
    process: model_process.ProcessResult,
    business_schema: dict[str, Any],
    *,
    prompt_bytes: int,
    adapter: str,
) -> dict[str, Any]:
    if process.process_stopped is not True:
        raise model_process.ProcessInterrupted(process)
    if (
        type(prompt_bytes) is not int
        or not 0 < prompt_bytes <= 16_777_216
        or type(process.returncode) is not int
        or process.returncode != 0
        or process.error_code is not None
        or type(process.input_bytes) is not int
        or process.input_bytes != prompt_bytes
        or type(process.stdout) is not bytes
        or not 0 < len(process.stdout) <= 67_108_864
    ):
        raise ValueError("command_process_invalid")
    try:
        value = codex_output.strict_json(process.stdout.decode("utf-8"))
        if adapter == "claude":
            if (
                not isinstance(value, dict)
                or value.get("type") != "result"
                or value.get("subtype") != "success"
                or value.get("is_error") is not False
                or not isinstance(value.get("result"), str)
            ):
                raise ValueError("terminal")
            value = codex_output.strict_json(value["result"])
        elif adapter != "codex":
            raise ValueError("adapter")
        if not isinstance(value, dict):
            raise ValueError("object")
        model_job.schema_validator(business_schema).validate(value)
        return value
    except Exception:
        raise ValueError("command_result_invalid") from None
