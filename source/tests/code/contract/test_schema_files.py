from __future__ import annotations

from jsonschema import Draft202012Validator

from skills._shared.fit_weekly import runtime_resources
from skills._shared.scripts.schema_validation import schema_documents


def test_current_declared_schemas_and_references_are_valid() -> None:
    schemas = schema_documents(
        runtime_resources.SCHEMAS + ("gmail_rest_auth_receipt_v1",)
    )
    assert schemas
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
