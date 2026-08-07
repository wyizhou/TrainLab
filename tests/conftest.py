from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from tests.support.isolation import IsolatedTestSubject, create_isolated_test_subject


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
