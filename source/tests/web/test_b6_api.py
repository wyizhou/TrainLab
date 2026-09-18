from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.fit.test_b1_regressions import valid
from trainlab.ai import AIConfig
from trainlab.contracts.interfaces import REFERENCE_CONTRACTS, ReferenceContract
from trainlab.contracts.time import format_utc
from trainlab.fit import import_activity, initialize_schema, open_database
from trainlab.local_web.server import WebAppSettings, create_app
from trainlab.reports import save_activity_report, save_weekly_report


class FakeAIClient:
    def __init__(self, content: str = "AI 生成全文") -> None:
        self.content = content
        self.requests: list[dict[str, Any]] = []

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        return {"choices": [{"message": {"content": self.content}, "finish_reason": "stop"}]}


class ReferenceToolAIClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        if len(self.requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "read-longdou",
                                    "type": "function",
                                    "function": {
                                        "name": "read_reference",
                                        "arguments": '{"reference_id":"longdou"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        return {"choices": [{"message": {"content": "不应读取外部资料"}, "finish_reason": "stop"}]}


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def make_client(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    *,
    ai_client: Any | None = None,
    project_root_path: Path | None = None,
) -> TestClient:
    settings = WebAppSettings(
        instance_root=tmp_path,
        project_root=project_root() if project_root_path is None else project_root_path,
        ai_client=ai_client,
        ai_config=None
        if ai_client is None
        else AIConfig(base_url="https://example.invalid/v1", api_key="fake", model="fake"),
    )
    client = TestClient(create_app(settings), base_url="http://127.0.0.1:8080")
    client.__enter__()
    request.addfinalizer(lambda: client.__exit__(None, None, None))
    return client


def init_db(tmp_path: Path) -> sqlite3.Connection:
    connection = open_database(tmp_path / "states/data.db")
    initialize_schema(connection)
    return connection


def add_activity(
    connection: sqlite3.Connection,
    activity_id: str,
    *,
    sport: str = "running",
    start: datetime | None,
) -> str:
    parsed = valid()
    start_text = None if start is None else format_utc(start)
    end = None if start is None else start + timedelta(hours=1)
    end_text = None if end is None else format_utc(end)
    parsed = replace(
        parsed,
        sport=sport,
        start_time_utc=start,
        end_time_utc=end,
        basic={**parsed.basic, "sport": sport, "start_time_utc": start_text, "end_time_utc": end_text},
    )
    return import_activity(
        connection,
        activity_id=activity_id,
        fit_path=f"states/activities/{activity_id}.fit",
        parsed=parsed,
        parsed_at_utc=datetime(2030, 1, 1, tzinfo=UTC),
    )


def envelope(response: Any) -> dict[str, Any]:
    data = response.json()
    assert set(data) == {"ok", "data", "error"}
    return cast(dict[str, Any], data)


def test_api_routes_status_and_spa_404_separation(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    init_db(tmp_path).close()
    client = make_client(tmp_path, request)

    health = envelope(client.get("/api/health"))
    assert health["ok"] is True
    assert health["data"]["starts_background_jobs"] is True
    assert health["data"]["ai_background_jobs"] is False
    assert health["data"]["sync_background_jobs"] is False
    assert health["data"]["ai_generation_configured"] is False
    assert all(route["path"].startswith("/api/") for route in health["data"]["routes"])

    api_missing = envelope(client.get("/api/not-present"))
    assert api_missing["ok"] is False
    assert api_missing["error"]["code"] == "ACTIVITY_NOT_FOUND"
    assert "<!doctype" not in client.get("/api/not-present").text.lower()

    spa_missing = client.get("/not-a-real-spa-route")
    assert spa_missing.status_code == 200
    assert "TrainLab" in spa_missing.text


def test_api_validation_errors_use_common_envelope(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    client = make_client(tmp_path, request)

    bad_limit_response = client.get("/api/activities", params={"limit": "abc"})
    bad_limit = envelope(bad_limit_response)
    assert bad_limit_response.status_code == 400
    assert bad_limit["ok"] is False
    assert bad_limit["error"]["code"] == "INVALID_ARGUMENT"
    assert "detail" not in bad_limit_response.json()

    bad_report_id_response = client.get("/api/reports/weekly/not-int")
    bad_report_id = envelope(bad_report_id_response)
    assert bad_report_id_response.status_code == 400
    assert bad_report_id["ok"] is False
    assert bad_report_id["error"]["code"] == "INVALID_ARGUMENT"
    assert "detail" not in bad_report_id_response.json()

    bad_body_response = client.post("/api/reports/weekly/generate", json=["not", "an", "object"])
    bad_body = envelope(bad_body_response)
    assert bad_body_response.status_code == 400
    assert bad_body["ok"] is False
    assert bad_body["error"]["code"] == "INVALID_ARGUMENT"
    assert "detail" not in bad_body_response.json()


def test_activity_search_pagination_and_existing_reports(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    connection = init_db(tmp_path)
    first = "a" * 64
    second = "b" * 64
    add_activity(connection, first, sport="running", start=datetime(2030, 1, 2, tzinfo=UTC))
    add_activity(connection, second, sport="cycling", start=datetime(2030, 1, 3, tzinfo=UTC))
    save_activity_report(connection, activity_id=first, summary="安全文本 <strong>不会当 HTML</strong>")
    save_weekly_report(connection, run_time_utc=datetime(2030, 1, 8, tzinfo=UTC), summary="周总结全文")
    connection.close()

    client = make_client(tmp_path, request)
    listed = envelope(client.get("/api/activities", params={"limit": 1, "offset": 0}))
    assert listed["ok"] is True
    assert listed["data"]["total"] == 2
    assert [item["activity_id"] for item in listed["data"]["items"]] == [second]

    running = envelope(client.get("/api/activities", params={"sport": "running", "has_report": True}))
    assert running["ok"] is True
    assert [item["activity_id"] for item in running["data"]["items"]] == [first]
    assert running["data"]["items"][0]["report_summary"] == "安全文本 <strong>不会当 HTML</strong>"

    detail = envelope(client.get(f"/api/activities/{first}"))
    assert detail["ok"] is True
    assert detail["data"]["summary"]["messages"]

    report = envelope(client.get(f"/api/reports/activity/{first}"))
    assert report["data"]["summary"] == "安全文本 <strong>不会当 HTML</strong>"
    weekly = envelope(client.get("/api/reports/weekly"))
    assert weekly["data"]["items"] == [{"id": 1, "run_time_utc": "2030-01-08T00:00:00.000000Z", "summary": "周总结全文"}]

    bad = envelope(client.get("/api/activities", params={"limit": 0}))
    assert bad["ok"] is False
    assert bad["error"]["code"] == "INVALID_ARGUMENT"


def test_report_generation_requires_explicit_fake_ai_and_never_reads_states_ai(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    (tmp_path / "states").mkdir()
    (tmp_path / "states/ai.json").write_text("not json and must not be read", encoding="utf-8")
    connection = init_db(tmp_path)
    activity_id = "c" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()

    disabled = make_client(tmp_path, request)
    disabled_result = envelope(disabled.post(f"/api/reports/activity/{activity_id}/generate"))
    assert disabled_result["ok"] is False
    assert disabled_result["error"]["code"] == "CONFIG_UNAVAILABLE"

    fake = FakeAIClient("生成完成")
    enabled = make_client(tmp_path, request, ai_client=fake)
    generated = envelope(enabled.post(f"/api/reports/activity/{activity_id}/generate", json={"message": "生成"}))
    assert generated["ok"] is True
    assert generated["data"]["summary"] == "生成完成"
    assert fake.requests
    stored = envelope(enabled.get(f"/api/reports/activity/{activity_id}"))
    assert stored["data"]["summary"] == "生成完成"


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink"])
def test_report_generation_reference_escape_uses_public_json_error_without_reading_external_content(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    project = tmp_path / "project"
    (project / "source/tools").mkdir(parents=True)
    (project / "source/tools/README.md").write_text("工具索引", encoding="utf-8")
    (project / "source/skills/local-web/web").mkdir(parents=True)
    (project / "source/skills/local-web/web/index.html").write_text("TrainLab", encoding="utf-8")
    (project / "references").mkdir()
    (project / "references/README.md").write_text("资料索引", encoding="utf-8")
    outside = tmp_path / "outside-secret.md"
    outside.write_text("外部资料-不得读取", encoding="utf-8")
    if kind == "traversal":
        reference_path = Path("../outside-secret.md")
    elif kind == "absolute":
        reference_path = outside
    else:
        (project / "references/longdou.md").symlink_to(outside)
        reference_path = Path("references/longdou.md")
    monkeypatch.setitem(
        REFERENCE_CONTRACTS,
        "longdou",
        ReferenceContract("longdou", reference_path, "Public sensor reference."),
    )
    connection = init_db(tmp_path)
    activity_id = "e" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()
    fake = ReferenceToolAIClient()
    client = make_client(tmp_path, request, ai_client=fake, project_root_path=project)

    response = client.post(f"/api/reports/activity/{activity_id}/generate", json={"message": "读资料"})
    result = envelope(response)
    rendered = response.text

    assert response.status_code == 503
    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "CONFIG_UNAVAILABLE"
    assert "外部资料-不得读取" not in rendered
    assert str(tmp_path) not in rendered
    assert outside.as_posix() not in rendered


def test_report_generation_missing_context_index_uses_json_error_envelope(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    project = tmp_path / "project"
    (project / "source/tools").mkdir(parents=True)
    (project / "source/tools/README.md").write_text("工具索引", encoding="utf-8")
    (project / "source/skills/local-web/web").mkdir(parents=True)
    (project / "source/skills/local-web/web/index.html").write_text("TrainLab", encoding="utf-8")
    connection = init_db(tmp_path)
    activity_id = "f" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()
    fake = FakeAIClient("不应调用")
    client = make_client(tmp_path, request, ai_client=fake, project_root_path=project)

    response = client.post(f"/api/reports/activity/{activity_id}/generate")
    result = envelope(response)

    assert response.status_code == 503
    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "CONFIG_UNAVAILABLE"
    assert result["error"]["message"] == "context material is unavailable"
    assert "traceback" not in response.text.lower()
    assert str(tmp_path) not in response.text
    assert fake.requests == []


def test_weekly_generation_keeps_missing_report_policy_and_supports_empty_week(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    connection = init_db(tmp_path)
    activity_id = "d" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()
    client = make_client(tmp_path, request, ai_client=FakeAIClient("不应调用"))

    missing = envelope(
        client.post(
            "/api/reports/weekly/generate",
            json={"run_time_utc": "2030-01-08T00:00:00.000000Z", "message": "周报"},
        )
    )
    assert missing["ok"] is False
    assert missing["error"]["code"] == "POLICY_UNCONFIGURED"

    empty = envelope(
        client.post(
            "/api/reports/weekly/generate",
            json={"run_time_utc": "2040-01-08T00:00:00.000000Z"},
        )
    )
    assert empty["ok"] is True
    assert empty["data"]["summary"] == "本周无任何运动记录"
