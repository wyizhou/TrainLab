from trainlab.main import create_app


def test_activity_rename_openapi_contract_is_frozen() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/activities/{activity_id}"]["patch"]
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ActivityNameUpdate"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ActivityListItem"
    }
    assert {"401", "403", "404", "422", "500"}.issubset(operation["responses"])
