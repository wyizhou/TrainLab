import json
from pathlib import Path

from fastapi.testclient import TestClient

from trainlab.main import create_app


def test_openapi_exposes_only_the_foundation_contract(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths) == {
        "/healthz",
        "/readyz",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
    }
    assert "/api/v1/auth/register" not in paths


def test_checked_in_openapi_contract_matches_runtime() -> None:
    contract_path = Path(__file__).parents[3] / "docs" / "api" / "openapi.json"
    checked_in = json.loads(contract_path.read_text(encoding="utf-8"))
    assert checked_in == create_app().openapi()
