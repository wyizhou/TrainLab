import json
from pathlib import Path

from fastapi.testclient import TestClient

from trainlab.main import create_app


def test_openapi_exposes_auth_and_the_user_owned_fit_activity_contract(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths) == {
        "/healthz",
        "/readyz",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
        "/api/v1/imports/fit",
        "/api/v1/imports",
        "/api/v1/imports/{import_id}",
        "/api/v1/imports/{import_id}/retry",
        "/api/v1/activities",
        "/api/v1/activities/{activity_id}",
        "/api/v1/activities/{activity_id}/source",
        "/api/v1/storage/usage",
    }
    assert "/api/v1/auth/register" not in paths

    upload = paths["/api/v1/imports/fit"]["post"]["responses"]
    for status in ("200", "201"):
        assert upload[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/FitImportResponse"
        }
    fit_response = response.json()["components"]["schemas"]["FitImportResponse"]
    assert fit_response["properties"]["activity"] == {
        "$ref": "#/components/schemas/ActivityListItem"
    }
    assert "activity" in fit_response["required"]

    source = paths["/api/v1/activities/{activity_id}/source"]["get"]["responses"]
    assert source["200"]["content"] == {
        "application/vnd.ant.fit": {"schema": {"type": "string", "format": "binary"}}
    }
    for status in ("401", "403", "404", "410"):
        assert source[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    for path, method in (
        ("/api/v1/imports/fit", "post"),
        ("/api/v1/imports/{import_id}/retry", "post"),
        ("/api/v1/activities", "get"),
        ("/api/v1/activities/{activity_id}", "get"),
        ("/api/v1/activities/{activity_id}/source", "get"),
    ):
        responses = paths[path][method]["responses"]
        for status in ("500", "503"):
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }


def test_checked_in_openapi_contract_matches_runtime() -> None:
    contract_path = Path(__file__).parents[3] / "docs" / "api" / "openapi.json"
    checked_in = json.loads(contract_path.read_text(encoding="utf-8"))
    assert checked_in == create_app().openapi()
