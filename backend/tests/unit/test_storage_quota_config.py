import pytest
from pydantic import ValidationError

from trainlab.core.config import Settings


def test_storage_quota_defaults_match_the_frozen_contract() -> None:
    settings = Settings()
    assert settings.user_storage_max_bytes == 5 * 1024 * 1024 * 1024
    assert settings.user_storage_max_files == 10_000
    assert settings.storage_staging_grace_minutes == 60


@pytest.mark.parametrize(
    "field",
    [
        "user_storage_max_bytes",
        "user_storage_max_files",
        "storage_staging_grace_minutes",
    ],
)
def test_storage_quota_settings_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
