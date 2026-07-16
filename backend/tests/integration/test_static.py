from fastapi.testclient import TestClient

from trainlab.main import create_app


def test_spa_home_deep_route_and_assets(settings, frontend_dist) -> None:  # type: ignore[no-untyped-def]
    app_settings = settings.model_copy(update={"frontend_dist": frontend_dist})
    with TestClient(create_app(app_settings)) as client:
        assert "TrainLab SPA" in client.get("/").text
        assert "TrainLab SPA" in client.get("/activities/1").text
        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "trainlab" in asset.text
        assert client.get("/assets/missing.js").status_code == 404


def test_missing_frontend_reports_a_json_error(settings) -> None:  # type: ignore[no-untyped-def]
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert response.status_code == 404
    assert response.json()["code"] == "frontend_not_built"
