from trainlab.db.base import Base


def test_every_activity_business_table_has_an_explicit_user_owner() -> None:
    business_tables = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name.startswith("activity_") or name == "activities"
    }

    assert set(business_tables) == {
        "activities",
        "activity_imports",
        "activity_sessions",
        "activity_records",
        "activity_laps",
        "activity_segments",
        "activity_devices",
        "activity_metric_definitions",
    }
    assert all("user_id" in table.columns for table in business_tables.values())


def test_activity_import_has_lifecycle_and_attempt_fencing_columns() -> None:
    columns = Base.metadata.tables["activity_imports"].columns
    assert {
        "title_override",
        "delete_requested_at",
        "last_delete_attempt_at",
        "delete_attempt_count",
        "delete_error_code",
        "processing_token",
    }.issubset(columns.keys())
