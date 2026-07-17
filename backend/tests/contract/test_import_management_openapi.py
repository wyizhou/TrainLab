from trainlab.main import create_app


def test_import_management_openapi_contract_is_frozen() -> None:
    paths = create_app().openapi()["paths"]
    assert paths["/api/v1/imports"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ImportListPage"}
    assert "delete" in paths["/api/v1/imports/{import_id}"]
    assert "delete" in paths["/api/v1/activities/{activity_id}"]
    assert "204" in paths["/api/v1/imports/{import_id}"]["delete"]["responses"]
    assert "204" in paths["/api/v1/activities/{activity_id}"]["delete"]["responses"]
