from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def create_database_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, hide_parameters=True)


def get_db(request: Request) -> Generator[Session, None, None]:
    with Session(request.app.state.engine) as session:
        yield session
