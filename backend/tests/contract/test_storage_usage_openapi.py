from trainlab.main import create_app


def test_storage_usage_openapi_contract_is_frozen() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/storage/usage"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/StorageUsageResponse"
    }
    assert {"401", "500"}.issubset(operation["responses"])
