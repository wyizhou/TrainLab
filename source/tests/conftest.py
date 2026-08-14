from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from src.garmin import base as garmin_base
from src.garmin import health as garmin_health
from src.garmin import repair as garmin_repair
from src.garmin_catalog import HEALTH_RESOURCES
from tests.support.isolation import IsolatedTestSubject, create_isolated_test_subject

_LEGACY_FULL_CATALOG_MODULES = frozenset(
    {
        "test_garmin_l2_01_04.py",
        "test_garmin_l2_04.py",
        "test_garmin_l2_05.py",
        "test_garmin_l2_08.py",
        "test_garmin_l2_09b2.py",
        "test_garmin_l2_13.py",
        "test_garmin_l2_14.py",
    }
)


@pytest.fixture(autouse=True)
def legacy_full_catalog_compatibility(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep explicit legacy catalog coverage separate from production defaults."""
    if request.node.path.name not in _LEGACY_FULL_CATALOG_MODULES:
        return
    # These legacy L2 modules validate the complete catalog pipeline.  This
    # test-only patch never changes the narrow production collection default.
    full_catalog = tuple(HEALTH_RESOURCES)
    for module in (garmin_base, garmin_health, garmin_repair):
        monkeypatch.setattr(module, "COLLECTED_HEALTH_RESOURCES", full_catalog)


@pytest.fixture
def isolated_test_subject(
    request: pytest.FixtureRequest,
) -> Iterator[IsolatedTestSubject]:
    """A disposable test boundary rooted below ``state/test-tmp``.

    Future integration and live-acceptance tests must use this fixture instead
    of a project/state/raw path or a real recipient.
    """

    subject = create_isolated_test_subject(test_name=request.node.name)
    try:
        yield subject
    finally:
        shutil.rmtree(subject.root)
