from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.sync.conftest import block_external_connections, offline  # noqa: F401
from trainlab.local_web.auth_security import ORIGIN
from trainlab.local_web.server import WebAppSettings, create_app


@pytest.fixture
def client(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[TestClient]:
    request.getfixturevalue("offline")
    app = create_app(WebAppSettings(instance_root=tmp_path, project_root=Path(__file__).parents[3], auth_maintenance=False))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client
