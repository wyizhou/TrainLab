from fastapi.testclient import TestClient

from trainlab.db.database import get_db
from trainlab.db.migrations import migration_head
from trainlab.main import create_app


def test_health_and_ready_are_independent_checks(client: TestClient) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["X-Request-ID"]

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_readiness_uses_the_single_alembic_head() -> None:
    assert migration_head() == "0003_activity_data_lifecycle"


def test_unknown_api_route_uses_json_error(client: TestClient) -> None:
    response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "not_found"
    assert response.json()["requestId"] == response.headers["X-Request-ID"]


def test_registration_is_not_exposed(client: TestClient, origin_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/auth/register", json={}, headers=origin_headers)
    assert response.status_code == 404


def test_unexpected_api_failure_keeps_json_error_and_request_id(
    settings, origin_headers: dict[str, str]
) -> None:  # type: ignore[no-untyped-def]
    app = create_app(settings)

    def broken_database():  # type: ignore[no-untyped-def]
        raise RuntimeError("database details must stay private")
        yield

    app.dependency_overrides[get_db] = broken_database
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "owner-user", "password": "correct-password"},
            headers=origin_headers,
        )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "internal_error"
    assert response.json()["requestId"] == response.headers["X-Request-ID"]
    assert "database details" not in response.text


def test_validation_error_does_not_echo_password(
    client: TestClient, origin_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner-user", "password": "secret"},
        headers=origin_headers,
    )
    assert response.status_code == 422
    assert "secret" not in response.text
