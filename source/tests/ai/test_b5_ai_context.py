from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from tests.fit.test_b1_regressions import valid
from trainlab.ai import AIConfig, AIProtocolError, ToolDispatcher, load_ai_config, run_tool_loop
from trainlab.context import ContextError, build_context
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.interfaces import (
    REFERENCE_CONTRACTS,
    TOOL_CONTRACTS,
    CapacityPolicy,
    ReferenceContract,
    ReferenceId,
    ToolAuthorization,
)
from trainlab.contracts.session import InMemoryConversationHistory
from trainlab.contracts.time import NO_ACTIVITY_WEEKLY_SUMMARY, format_utc
from trainlab.fit import import_activity, initialize_schema, open_database
from trainlab.report_service import ReportService
from trainlab.reports import (
    ReportStorageError,
    get_activity_report,
    get_weekly_report,
    save_activity_report,
)


class FakeAIClient:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("unexpected AI call")
        return self.responses.pop(0)


def response(message: dict[str, Any], finish_reason: str | None = "stop") -> dict[str, Any]:
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def auth(
    *activity_ids: str,
    references: tuple[ReferenceId, ...] = ("longdou", "garmin-fit-parsing"),
) -> ToolAuthorization:
    return ToolAuthorization(frozenset(activity_ids), frozenset(references))


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def add_activity(connection: sqlite3.Connection, activity_id: str = "a" * 64, *, start: datetime | None = datetime(2030, 1, 2, tzinfo=UTC)) -> str:
    parsed = valid()
    text = None if start is None else format_utc(start)
    parsed = replace(parsed, start_time_utc=start, basic={**parsed.basic, "start_time_utc": text})
    return import_activity(connection, activity_id=activity_id, fit_path=f"{activity_id[:8]}.fit", parsed=parsed)


def file_db(tmp_path: Path) -> tuple[sqlite3.Connection, Path, str]:
    db_path = tmp_path / "states/data.db"
    connection = open_database(db_path)
    initialize_schema(connection)
    activity_id = add_activity(connection)
    return connection, db_path, activity_id


def dispatcher(tmp_path: Path, activity_id: str = "a" * 64) -> ToolDispatcher:
    return ToolDispatcher(
        db_path=tmp_path / "states/data.db",
        authorization=auth(activity_id),
        project_root=project_root(),
        capacity=CapacityPolicy(storage_bytes_limit=None, model_payload_bytes_limit=100_000),
    )


def test_ai_tool_loop_handles_no_tool_single_and_multi_tool_rounds(tmp_path: Path) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        no_tool = run_tool_loop(
            FakeAIClient(response({"content": "直接总结"})),
            model="fake",
            messages=[{"role": "user", "content": "hi"}],
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
        )
        assert no_tool.content == "直接总结"

        client = FakeAIClient(
            response(
                {"content": None, "tool_calls": [tool_call("r1", "read_reference", {"reference_id": "longdou"})]},
                "tool_calls",
            ),
            response(
                {
                    "content": None,
                    "tool_calls": [tool_call("g1", "get_running_records", {"activity_id": activity_id})],
                },
                "tool_calls",
            ),
            response({"content": "最终全文"}),
        )
        completed = run_tool_loop(
            client,
            model="fake",
            messages=[{"role": "user", "content": "需要资料和采样"}],
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            max_tool_rounds=3,
        )
        assert completed.content == "最终全文"
        tool_messages = [m for m in completed.messages if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_messages] == ["r1", "g1"]
        assert "longdou" in tool_messages[0]["content"]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("client", "code"),
    [
        (FakeAIClient(response({"content": "cut"}, "length")), ErrorCode.RESOURCE_LIMIT),
        (FakeAIClient({"broken": []}), ErrorCode.DATA_INVALID),
        (
            FakeAIClient(response({"content": None, "tool_calls": [tool_call("u", "unknown", {})]}, "tool_calls")),
            ErrorCode.TOOL_NOT_ALLOWED,
        ),
        (
            FakeAIClient(
                response(
                    {"content": None, "tool_calls": [tool_call("r", "read_reference", {"reference_id": "longdou", "path": "x"})]},
                    "tool_calls",
                )
            ),
            ErrorCode.INVALID_ARGUMENT,
        ),
    ],
)
def test_ai_tool_loop_fails_explicitly(client: FakeAIClient, code: ErrorCode, tmp_path: Path) -> None:
    _, db_path, activity_id = file_db(tmp_path)
    with pytest.raises(AIProtocolError) as error:
        run_tool_loop(
            client,
            model="fake",
            messages=[{"role": "user", "content": "hi"}],
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            max_tool_rounds=1,
        )
    assert error.value.code == code


def test_ai_tool_loop_rejects_excessive_tool_rounds(tmp_path: Path) -> None:
    _, db_path, activity_id = file_db(tmp_path)
    client = FakeAIClient(
        response({"content": None, "tool_calls": [tool_call("r1", "read_reference", {"reference_id": "longdou"})]}, "tool_calls"),
        response({"content": None, "tool_calls": [tool_call("r2", "read_reference", {"reference_id": "longdou"})]}, "tool_calls"),
    )
    with pytest.raises(AIProtocolError) as error:
        run_tool_loop(
            client,
            model="fake",
            messages=[{"role": "user", "content": "loop"}],
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            max_tool_rounds=1,
        )
    assert error.value.code == ErrorCode.TIMEOUT


def test_dispatcher_and_reference_reader_allow_only_registered_tools_and_ids(tmp_path: Path) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        active_dispatcher = ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root())
        records = active_dispatcher.dispatch("get_running_records", {"activity_id": activity_id})
        assert records["ok"] is True
        reference = active_dispatcher.dispatch("read_reference", {"reference_id": "longdou"})
        assert reference["ok"] is True
        assert "龙豆" in reference["data"]["content"]
        assert active_dispatcher.dispatch("read_reference", {"reference_id": "longdou", "url": "https://x"})["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value
        assert ToolDispatcher(db_path=db_path, authorization=auth(activity_id, references=()), project_root=project_root()).dispatch("read_reference", {"reference_id": "longdou"})["error"]["code"] == ErrorCode.TOOL_NOT_ALLOWED.value
        assert active_dispatcher.dispatch("shell", {})["error"]["code"] == ErrorCode.TOOL_NOT_ALLOWED.value
    finally:
        connection.close()


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink"])
def test_reference_reader_rejects_escape_without_path_or_content_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    project = tmp_path / "project"
    references = project / "references"
    references.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("外部资料-不得读取", encoding="utf-8")
    if kind == "traversal":
        relative_path = Path("../outside.md")
    elif kind == "absolute":
        relative_path = outside
    else:
        (references / "longdou.md").symlink_to(outside)
        relative_path = Path("references/longdou.md")
    monkeypatch.setitem(
        REFERENCE_CONTRACTS,
        "longdou",
        ReferenceContract("longdou", relative_path, "Public sensor reference."),
    )
    try:
        result = ToolDispatcher(
            db_path=db_path,
            authorization=auth(activity_id),
            project_root=project,
        ).dispatch("read_reference", {"reference_id": "longdou"})
    finally:
        connection.close()

    rendered = json.dumps(result, ensure_ascii=False)
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.CONFIG_UNAVAILABLE.value
    assert "外部资料-不得读取" not in rendered
    assert str(tmp_path) not in rendered
    assert outside.as_posix() not in rendered


def test_context_missing_material_fails_with_public_error(tmp_path: Path) -> None:
    (tmp_path / "source/tools").mkdir(parents=True)
    (tmp_path / "source/tools/README.md").write_text("工具索引", encoding="utf-8")
    with pytest.raises(ContextError) as error:
        build_context(mode="daily", current_user_message="日报", project_root=tmp_path)

    assert error.value.code == ErrorCode.CONFIG_UNAVAILABLE
    assert error.value.message == "context material is unavailable"
    assert str(tmp_path) not in str(error.value)


def test_context_activity_daily_weekly_history_and_policy_boundaries(tmp_path: Path) -> None:
    connection, _db_path, activity_id = file_db(tmp_path)
    try:
        history = InMemoryConversationHistory()
        history.append("user", "上一轮", datetime(2030, 1, 1, tzinfo=UTC))
        activity = build_context(
            mode="activity",
            current_user_message="总结这场",
            project_root=project_root(),
            history=history,
            connection=connection,
            activity_id=activity_id,
        )
        assert activity.metadata["mode"]["activity_facts"]["activity_id"] == activity_id
        assert "工具索引" in activity.messages[0]["content"]
        assert "longdou" in activity.messages[0]["content"]
        assert "上一轮" in activity.messages[0]["content"]

        daily = build_context(mode="daily", current_user_message="日报", project_root=project_root(), history=history)
        assert "不读取健康数据" in daily.messages[1]["content"]
        assert connection.execute("SELECT count(*) FROM weekly_report").fetchone() == (0,)

        save_activity_report(connection, activity_id=activity_id, summary="活动全文")
        weekly = build_context(
            mode="weekly",
            current_user_message="周总结",
            project_root=project_root(),
            connection=connection,
            run_time_utc=datetime(2030, 1, 3, tzinfo=UTC),
        )
        assert weekly.metadata["mode"]["activity_summaries"][0]["summary"] == "活动全文"

        missing_id = add_activity(connection, "b" * 64, start=datetime(2030, 1, 2, 12, tzinfo=UTC))
        with pytest.raises(ContextError) as missing:
            build_context(
                mode="weekly",
                current_user_message="周总结",
                project_root=project_root(),
                connection=connection,
                run_time_utc=datetime(2030, 1, 3, tzinfo=UTC),
            )
        assert missing.value.code == ErrorCode.POLICY_UNCONFIGURED

        empty = build_context(
            mode="weekly",
            current_user_message="空周",
            project_root=project_root(),
            connection=connection,
            run_time_utc=datetime(2031, 1, 3, tzinfo=UTC),
        )
        assert empty.metadata["mode"]["empty_week_summary"] == NO_ACTIVITY_WEEKLY_SUMMARY
        assert connection.execute("SELECT count(*) FROM activties_report WHERE activity_id=?", (missing_id,)).fetchone() == (0,)
    finally:
        connection.close()


def test_report_service_saves_only_after_success_and_preserves_full_text(tmp_path: Path) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "活动报告全文\nSELECT 1"})),
            ai_config=AIConfig("https://invalid.local", "secret-key", "fake", max_tool_rounds=2),
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            history=InMemoryConversationHistory(),
        )
        result = service.generate_activity_report(
            activity_id=activity_id,
            current_user_message="生成活动报告",
            now_utc=datetime(2030, 1, 4, tzinfo=UTC),
        )
        assert result.summary == "活动报告全文\nSELECT 1"
        assert get_activity_report(connection, activity_id)["summary"] == result.summary
        assert service.history.persistence_target is None
        assert "secret-key" not in json.dumps(result.ai_messages, ensure_ascii=False)

        failing_service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "截断"}, "length")),
            ai_config=AIConfig("https://invalid.local", "secret-key", "fake"),
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            history=InMemoryConversationHistory(),
        )
        before = get_activity_report(connection, activity_id)
        with pytest.raises(AIProtocolError):
            failing_service.generate_activity_report(
                activity_id=activity_id,
                current_user_message="失败不覆盖",
                now_utc=datetime(2030, 1, 4, tzinfo=UTC),
            )
        assert get_activity_report(connection, activity_id) == before
    finally:
        connection.close()


def test_report_service_activity_storage_capacity_failure_does_not_insert_or_overwrite(
    tmp_path: Path,
) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        limited_dispatcher = ToolDispatcher(
            db_path=db_path,
            authorization=auth(activity_id),
            project_root=project_root(),
            capacity=CapacityPolicy(storage_bytes_limit=5, model_payload_bytes_limit=None),
        )
        service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "0123456789 long"})),
            ai_config=AIConfig("https://invalid.local", "secret", "fake"),
            dispatcher=limited_dispatcher,
            history=InMemoryConversationHistory(),
        )

        with pytest.raises(ReportStorageError) as insert_error:
            service.generate_activity_report(
                activity_id=activity_id,
                current_user_message="超限活动报告",
                now_utc=datetime(2030, 1, 4, tzinfo=UTC),
            )

        assert insert_error.value.code == ErrorCode.RESOURCE_LIMIT
        assert connection.execute("SELECT count(*) FROM activties_report").fetchone() == (0,)
        assert service.history.snapshot() == ()

        save_activity_report(connection, activity_id=activity_id, summary="旧报告")
        before = get_activity_report(connection, activity_id)
        overwrite_service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "0123456789 long"})),
            ai_config=AIConfig("https://invalid.local", "secret", "fake"),
            dispatcher=limited_dispatcher,
            history=InMemoryConversationHistory(),
        )
        with pytest.raises(ReportStorageError) as overwrite_error:
            overwrite_service.generate_activity_report(
                activity_id=activity_id,
                current_user_message="超限不覆盖",
                now_utc=datetime(2030, 1, 4, tzinfo=UTC),
            )

        assert overwrite_error.value.code == ErrorCode.RESOURCE_LIMIT
        assert get_activity_report(connection, activity_id) == before
        assert overwrite_service.history.snapshot() == ()
    finally:
        connection.close()


def test_weekly_report_service_uses_ai_for_summaries_and_fixed_empty_week(tmp_path: Path) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        save_activity_report(connection, activity_id=activity_id, summary="活动总结全文")
        service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "周报告全文"})),
            ai_config=AIConfig("https://invalid.local", "secret", "fake"),
            dispatcher=ToolDispatcher(db_path=db_path, authorization=auth(activity_id), project_root=project_root()),
            history=InMemoryConversationHistory(),
        )
        weekly = service.generate_weekly_report(
            run_time_utc=datetime(2030, 1, 3, tzinfo=UTC), current_user_message="周报"
        )
        assert get_weekly_report(connection, cast(int, weekly.saved["id"]))["summary"] == "周报告全文"

        empty = service.generate_weekly_report(
            run_time_utc=datetime(2031, 1, 3, tzinfo=UTC), current_user_message="空周"
        )
        assert empty.summary == NO_ACTIVITY_WEEKLY_SUMMARY
        assert get_weekly_report(connection, cast(int, empty.saved["id"]))["summary"] == NO_ACTIVITY_WEEKLY_SUMMARY
    finally:
        connection.close()


def test_weekly_report_service_storage_capacity_blocks_ai_and_empty_week_saves(
    tmp_path: Path,
) -> None:
    connection, db_path, activity_id = file_db(tmp_path)
    try:
        save_activity_report(connection, activity_id=activity_id, summary="活动总结全文")
        limited_dispatcher = ToolDispatcher(
            db_path=db_path,
            authorization=auth(activity_id),
            project_root=project_root(),
            capacity=CapacityPolicy(storage_bytes_limit=5, model_payload_bytes_limit=None),
        )
        ai_service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(response({"content": "0123456789 long"})),
            ai_config=AIConfig("https://invalid.local", "secret", "fake"),
            dispatcher=limited_dispatcher,
            history=InMemoryConversationHistory(),
        )

        with pytest.raises(ReportStorageError) as ai_error:
            ai_service.generate_weekly_report(
                run_time_utc=datetime(2030, 1, 3, tzinfo=UTC),
                current_user_message="超限周报",
            )

        assert ai_error.value.code == ErrorCode.RESOURCE_LIMIT
        assert connection.execute("SELECT count(*) FROM weekly_report").fetchone() == (0,)

        empty_service = ReportService(
            connection=connection,
            project_root=project_root(),
            ai_client=FakeAIClient(),
            ai_config=AIConfig("https://invalid.local", "secret", "fake"),
            dispatcher=limited_dispatcher,
            history=InMemoryConversationHistory(),
        )
        with pytest.raises(ReportStorageError) as empty_error:
            empty_service.generate_weekly_report(
                run_time_utc=datetime(2031, 1, 3, tzinfo=UTC),
                current_user_message="空周也受容量限制",
            )

        assert empty_error.value.code == ErrorCode.RESOURCE_LIMIT
        assert connection.execute("SELECT count(*) FROM weekly_report").fetchone() == (0,)
    finally:
        connection.close()


def test_private_ai_config_loader_uses_only_explicit_tmp_instance(tmp_path: Path) -> None:
    config_path = tmp_path / "states/ai.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"base_url": "https://example.invalid/v1", "api_key": "private", "model": "fake"}),
        encoding="utf-8",
    )
    config = load_ai_config(tmp_path)
    assert config.base_url == "https://example.invalid/v1"
    assert config.api_key == "private"
    assert set(TOOL_CONTRACTS) == {"get_running_records", "read_reference"}
    sampling_tools = [name for name in TOOL_CONTRACTS if name == "get_running_records"]
    assert sampling_tools == ["get_running_records"]
