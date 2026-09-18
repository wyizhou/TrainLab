"""OpenAI-compatible chat loop and trusted tool dispatch for ADHOC-0031 B5."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import CapacityPolicy, ToolAuthorization
from trainlab.contracts.paths import AI_CONFIG_PATH
from trainlab.reference_tools import read_reference
from trainlab.running_records import handle_get_running_records

JsonObject = dict[str, Any]


class CompatibleAIClient(Protocol):
    def create_chat_completion(self, payload: JsonObject) -> JsonObject: ...


@dataclass(frozen=True)
class AIConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    max_tool_rounds: int = 8


@dataclass(frozen=True)
class AICompletion:
    content: str
    messages: tuple[JsonObject, ...]


class AIProtocolError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code
        self.message = message


def load_ai_config(instance_root: Path, relative_path: Path = AI_CONFIG_PATH) -> AIConfig:
    path = _inside_instance(instance_root, relative_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AIProtocolError(ErrorCode.CONFIG_UNAVAILABLE, "AI config is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI config is invalid JSON") from exc
    if not isinstance(data, dict):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI config must be a JSON object")
    try:
        base_url = _required_str(data, "base_url").rstrip("/")
        api_key = _required_str(data, "api_key")
        model = _required_str(data, "model")
    except KeyError as exc:
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI config is incomplete") from exc
    timeout = data.get("timeout_seconds", 60.0)
    max_rounds = data.get("max_tool_rounds", 8)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI timeout must be positive")
    if not isinstance(max_rounds, int) or max_rounds <= 0:
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI max_tool_rounds must be positive")
    return AIConfig(base_url=base_url, api_key=api_key, model=model, timeout_seconds=float(timeout), max_tool_rounds=max_rounds)


class HttpCompatibleAIClient:
    def __init__(self, config: AIConfig) -> None:
        self._config = config

    def create_chat_completion(self, payload: JsonObject) -> JsonObject:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            self._config.base_url + "/chat/completions",
            data=body,
            headers={
                "Authorization": "Bearer " + self._config.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AIProtocolError(ErrorCode.EXTERNAL_SERVICE_FAILED, "AI HTTP error") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AIProtocolError(ErrorCode.EXTERNAL_SERVICE_FAILED, "AI response unavailable") from exc
        if not isinstance(decoded, dict):
            raise AIProtocolError(ErrorCode.DATA_INVALID, "AI response must be an object")
        return decoded


@dataclass(frozen=True)
class ToolDispatcher:
    db_path: Path
    authorization: ToolAuthorization
    project_root: Path
    capacity: CapacityPolicy | None = None

    def dispatch(self, name: str, arguments: Mapping[str, Any]) -> JsonObject:
        if name == "get_running_records":
            return handle_get_running_records(
                arguments,
                db_path=self.db_path,
                authorization=self.authorization,
                capacity=self.capacity,
            )
        if name == "read_reference":
            return read_reference(arguments, project_root=self.project_root, authorization=self.authorization)
        return _failure(ErrorCode.TOOL_NOT_ALLOWED, "tool is not registered")


def compatible_tools() -> list[JsonObject]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_running_records",
                "description": "Return all records for one host-authorized running activity.",
                "parameters": _schema("GetRunningRecordsRequest"),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_reference",
                "description": "Read one approved public reference by id.",
                "parameters": _schema("ReadReferenceRequest"),
            },
        },
    ]


def run_tool_loop(
    client: CompatibleAIClient,
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    dispatcher: ToolDispatcher,
    max_tool_rounds: int = 8,
) -> AICompletion:
    conversation: list[JsonObject] = [dict(message) for message in messages]
    for _round in range(max_tool_rounds + 1):
        response = client.create_chat_completion(
            {"model": model, "messages": conversation, "tools": compatible_tools()}
        )
        message, finish_reason = _choice_message(response)
        if finish_reason in {"length", "content_filter"}:
            raise AIProtocolError(ErrorCode.RESOURCE_LIMIT, "AI response was truncated or filtered")
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            content = message.get("content")
            if not isinstance(content, str):
                raise AIProtocolError(ErrorCode.DATA_INVALID, "AI final content is missing")
            conversation.append({"role": "assistant", "content": content})
            return AICompletion(content=content, messages=tuple(conversation))
        if _round >= max_tool_rounds:
            raise AIProtocolError(ErrorCode.TIMEOUT, "AI tool loop exceeded max rounds")
        if not isinstance(tool_calls, list):
            raise AIProtocolError(ErrorCode.DATA_INVALID, "AI tool_calls must be a list")
        assistant_message = {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls}
        conversation.append(assistant_message)
        for call in tool_calls:
            tool_message = _execute_tool_call(call, dispatcher)
            conversation.append(tool_message)
    raise AIProtocolError(ErrorCode.TIMEOUT, "AI tool loop exceeded max rounds")


def _execute_tool_call(call: object, dispatcher: ToolDispatcher) -> JsonObject:
    if not isinstance(call, dict):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI tool call must be an object")
    call_id = call.get("id")
    function = call.get("function")
    if not isinstance(call_id, str) or not isinstance(function, dict):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI tool call id/function is missing")
    name = function.get("name")
    raw_arguments = function.get("arguments", "{}")
    if not isinstance(name, str) or not isinstance(raw_arguments, str):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI tool call name/arguments are invalid")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise AIProtocolError(ErrorCode.INVALID_ARGUMENT, "AI tool arguments are invalid JSON") from exc
    if not isinstance(arguments, dict):
        raise AIProtocolError(ErrorCode.INVALID_ARGUMENT, "AI tool arguments must be an object")
    result = dispatcher.dispatch(name, arguments)
    if result.get("ok") is not True:
        raise AIProtocolError(_error_code(result), "AI tool call failed")
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, sort_keys=True)}


def _choice_message(response: Mapping[str, Any]) -> tuple[JsonObject, str | None]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI response choices are missing")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI response message is missing")
    finish = choice.get("finish_reason")
    if finish is not None and not isinstance(finish, str):
        raise AIProtocolError(ErrorCode.DATA_INVALID, "AI finish_reason is invalid")
    return dict(choice["message"]), finish


def _error_code(result: Mapping[str, Any]) -> ErrorCode:
    error = result.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        try:
            return ErrorCode(error["code"])
        except ValueError:
            return ErrorCode.EXTERNAL_SERVICE_FAILED
    return ErrorCode.EXTERNAL_SERVICE_FAILED


def _failure(code: ErrorCode, message: str) -> JsonObject:
    return {"ok": False, "data": None, "error": {"code": code.value, "message": message, "details": {}}}


def _schema(name: str) -> JsonObject:
    from trainlab.contracts.json_validation import schema_for

    return schema_for(name)


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or value == "":
        raise KeyError(key)
    return value


def _inside_instance(instance_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise AIProtocolError(ErrorCode.INVALID_ARGUMENT, "path must be instance-relative")
    root = instance_root.resolve(strict=False)
    path = (root / relative_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AIProtocolError(ErrorCode.INVALID_ARGUMENT, "path escapes instance root") from exc
    return path
