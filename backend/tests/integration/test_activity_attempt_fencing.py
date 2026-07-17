import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.db.models.user import User
from trainlab.importers.fit import FitDecodeFailure, parse_fit_file
from trainlab.services.auth import LoginRateLimiter

FIT_FIXTURE = (
    Path(__file__).parents[3] / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
)


def _login(client: TestClient, user: User) -> dict[str, str]:
    client.app.state.login_rate_limiter = LoginRateLimiter()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "correct-password"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get("trainlab_csrf")
    assert csrf
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


@pytest.mark.parametrize("replacement_status", ["deleting", "processing"])
def test_old_parse_cannot_write_after_delete_or_new_attempt_takes_ownership(
    client: TestClient,
    user: User,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    replacement_status: str,
) -> None:  # type: ignore[no-untyped-def]
    parsed = parse_fit_file(FIT_FIXTURE, "run.fit")

    def replace_attempt(_source, _name):  # type: ignore[no-untyped-def]
        with Session(engine) as other:
            imported = other.scalar(
                select(ActivityImport).where(
                    ActivityImport.user_id == user.id,
                    ActivityImport.status == "processing",
                )
            )
            assert imported is not None
            imported.status = replacement_status
            imported.processing_token = None if replacement_status == "deleting" else uuid.uuid4()
            other.commit()
        return parsed

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", replace_attempt)
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": ("run.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=_login(client, user),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "import_attempt_superseded"
    with Session(engine) as db:
        imported = db.scalar(select(ActivityImport).where(ActivityImport.user_id == user.id))
        assert imported is not None
        assert imported.status == replacement_status
        assert db.scalar(select(func.count(Activity.id))) == 0


def test_old_parse_failure_cannot_overwrite_delete_intent(
    client: TestClient, user: User, engine, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    def replace_then_fail(_source, _name):  # type: ignore[no-untyped-def]
        with Session(engine) as other:
            imported = other.scalar(
                select(ActivityImport).where(
                    ActivityImport.user_id == user.id,
                    ActivityImport.status == "processing",
                )
            )
            assert imported is not None
            imported.status = "deleting"
            imported.processing_token = None
            other.commit()
        raise FitDecodeFailure("fit_decode_failed", "FIT 文件无法解析")

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", replace_then_fail)
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": ("run.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=_login(client, user),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "import_attempt_superseded"
    with Session(engine) as db:
        imported = db.scalar(select(ActivityImport).where(ActivityImport.user_id == user.id))
        assert imported is not None
        assert imported.status == "deleting"
        assert imported.processing_token is None
        assert db.scalar(select(func.count(Activity.id))) == 0
