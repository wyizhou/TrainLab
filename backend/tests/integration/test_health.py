import os
from pathlib import Path

from fastapi.testclient import TestClient

from trainlab.db.database import get_db
from trainlab.db.migrations import migration_head
from trainlab.main import create_app


def test_private_storage_probe_is_removed_on_success(settings) -> None:  # type: ignore[no-untyped-def]
    from trainlab.api.routes.health import _private_storage_ready

    before = set(settings.private_storage_root.iterdir())
    assert _private_storage_ready(settings.private_storage_root) is True
    assert set(settings.private_storage_root.iterdir()) == before


def test_readiness_rejects_missing_private_storage_without_leaking_path(
    client: TestClient, tmp_path: Path
) -> None:
    missing = tmp_path / "private-storage-must-not-leak"
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"private_storage_root": missing}
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["code"] == "private_storage_not_ready"
    assert str(missing) not in response.text


def test_private_storage_probe_rejects_symlinked_root(settings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from trainlab.api.routes.health import _private_storage_ready

    link = tmp_path / "storage-link"
    link.symlink_to(settings.private_storage_root, target_is_directory=True)

    before = set(settings.private_storage_root.iterdir())
    assert _private_storage_ready(link) is False
    assert set(settings.private_storage_root.iterdir()) == before


def test_private_storage_probe_failure_still_removes_probe(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trainlab.api.routes import health

    real_fsync = os.fsync

    def fail_probe_fsync(file_descriptor: int) -> None:
        if file_descriptor >= 0:
            raise OSError("synthetic write failure")
        real_fsync(file_descriptor)

    monkeypatch.setattr(health.os, "fsync", fail_probe_fsync)

    before = set(settings.private_storage_root.iterdir())
    assert health._private_storage_ready(settings.private_storage_root) is False
    assert set(settings.private_storage_root.iterdir()) == before


def test_private_storage_probe_rejects_unwritable_root(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trainlab.api.routes import health

    real_open = os.open

    def reject_probe(path, flags, mode=0o777, *, dir_fd=None):  # type: ignore[no-untyped-def]
        if dir_fd is not None:
            raise PermissionError("synthetic read-only storage")
        return real_open(path, flags, mode)

    monkeypatch.setattr(health.os, "open", reject_probe)

    before = set(settings.private_storage_root.iterdir())
    assert health._private_storage_ready(settings.private_storage_root) is False
    assert set(settings.private_storage_root.iterdir()) == before


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
