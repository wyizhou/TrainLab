from trainlab.db.database import create_database_engine


def test_database_engine_hides_sql_parameters_from_unexpected_errors() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    try:
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
