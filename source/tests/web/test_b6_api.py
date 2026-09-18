from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from tests.fit.test_b1_regressions import valid
from trainlab.ai import AIConfig
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


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def make_client(tmp_path: Path, *, ai_client: FakeAIClient | None = None) -> TestClient:
    settings = WebAppSettings(
        instance_root=tmp_path,
        project_root=project_root(),
        ai_client=ai_client,
        ai_config=None
        if ai_client is None
        else AIConfig(base_url="https://example.invalid/v1", api_key="fake", model="fake"),
    )
    return TestClient(create_app(settings))


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


def test_api_routes_status_and_spa_404_separation(tmp_path: Path) -> None:
    init_db(tmp_path).close()
    client = make_client(tmp_path)

    health = envelope(client.get("/api/health"))
    assert health["ok"] is True
    assert health["data"]["starts_background_jobs"] is False
    assert health["data"]["ai_generation_configured"] is False
    assert all(route["path"].startswith("/api/") for route in health["data"]["routes"])

    api_missing = envelope(client.get("/api/not-present"))
    assert api_missing["ok"] is False
    assert api_missing["error"]["code"] == "ACTIVITY_NOT_FOUND"
    assert "<!doctype" not in client.get("/api/not-present").text.lower()

    spa_missing = client.get("/not-a-real-spa-route")
    assert spa_missing.status_code == 200
    assert "TrainLab" in spa_missing.text


def test_api_validation_errors_use_common_envelope(tmp_path: Path) -> None:
    client = make_client(tmp_path)

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


def test_activity_search_pagination_and_existing_reports(tmp_path: Path) -> None:
    connection = init_db(tmp_path)
    first = "a" * 64
    second = "b" * 64
    add_activity(connection, first, sport="running", start=datetime(2030, 1, 2, tzinfo=UTC))
    add_activity(connection, second, sport="cycling", start=datetime(2030, 1, 3, tzinfo=UTC))
    save_activity_report(connection, activity_id=first, summary="安全文本 <strong>不会当 HTML</strong>")
    save_weekly_report(connection, run_time_utc=datetime(2030, 1, 8, tzinfo=UTC), summary="周总结全文")
    connection.close()

    client = make_client(tmp_path)
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


def test_report_generation_requires_explicit_fake_ai_and_never_reads_states_ai(tmp_path: Path) -> None:
    (tmp_path / "states").mkdir()
    (tmp_path / "states/ai.json").write_text("not json and must not be read", encoding="utf-8")
    connection = init_db(tmp_path)
    activity_id = "c" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()

    disabled = make_client(tmp_path)
    disabled_result = envelope(disabled.post(f"/api/reports/activity/{activity_id}/generate"))
    assert disabled_result["ok"] is False
    assert disabled_result["error"]["code"] == "CONFIG_UNAVAILABLE"

    fake = FakeAIClient("生成完成")
    enabled = make_client(tmp_path, ai_client=fake)
    generated = envelope(enabled.post(f"/api/reports/activity/{activity_id}/generate", json={"message": "生成"}))
    assert generated["ok"] is True
    assert generated["data"]["summary"] == "生成完成"
    assert fake.requests
    stored = envelope(enabled.get(f"/api/reports/activity/{activity_id}"))
    assert stored["data"]["summary"] == "生成完成"


def test_weekly_generation_keeps_missing_report_policy_and_supports_empty_week(tmp_path: Path) -> None:
    connection = init_db(tmp_path)
    activity_id = "d" * 64
    add_activity(connection, activity_id, start=datetime(2030, 1, 2, tzinfo=UTC))
    connection.close()
    client = make_client(tmp_path, ai_client=FakeAIClient("不应调用"))

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
