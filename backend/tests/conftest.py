from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from trainlab.core.config import Settings
from trainlab.core.security import hash_password, normalize_username
from trainlab.db.database import create_database_engine
from trainlab.db.models.session import LoginSession
from trainlab.db.models.user import User
from trainlab.main import create_app


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    from trainlab.core.config import get_settings

    base = get_settings()
    if base.environment != "test":
        pytest.exit("Integration tests require TRAINLAB_ENVIRONMENT=test")
    database_name = make_url(base.database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.exit("Integration tests require a database whose name ends with _test")
    return base.model_copy(
        update={
            "environment": "test",
            "public_origin": "http://testserver",
            "trusted_origins": ["http://testserver"],
            "allowed_hosts": ["testserver", "localhost"],
            "session_cookie_secure": False,
            "frontend_dist": tmp_path_factory.mktemp("frontend-missing"),
        }
    )


@pytest.fixture(scope="session")
def engine(settings: Settings):  # type: ignore[no-untyped-def]
    database_engine = create_database_engine(settings.database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(engine) -> Generator[None, None, None]:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        db.execute(delete(LoginSession))
        db.execute(delete(User))
        db.commit()
    yield


@pytest.fixture
def client(settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def origin_headers() -> dict[str, str]:
    return {"Origin": "http://testserver"}


def create_test_user(
    engine,
    username: str,
    password: str = "correct-password",
    *,
    owner: bool = False,
) -> User:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        user = User(
            username=username,
            username_normalized=normalize_username(username),
            display_name=username,
            password_hash=hash_password(password),
            is_owner=owner,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


@pytest.fixture
def user(engine) -> User:  # type: ignore[no-untyped-def]
    return create_test_user(engine, "owner-user", owner=True)


@pytest.fixture
def frontend_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>TrainLab SPA</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('trainlab')", encoding="utf-8")
    return dist
