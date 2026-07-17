from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRAINLAB_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://trainlab:trainlab@localhost:5432/trainlab"
    public_origin: str = "http://localhost:8000"
    trusted_origins: list[str] = ["http://localhost:8000", "http://localhost:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    session_cookie_name: str = "trainlab_session"
    csrf_cookie_name: Literal["trainlab_csrf"] = "trainlab_csrf"
    session_cookie_secure: bool = False
    session_ttl_days: int = 30
    login_failure_limit: int = 5
    login_lock_minutes: int = 15
    frontend_dist: Path = Path("../frontend/dist")
    private_storage_root: Path = Path("./data/private")
    fit_upload_max_bytes: int = 50 * 1024 * 1024
    import_processing_stale_minutes: int = 15
    log_level: str = "INFO"

    @field_validator("public_origin", mode="after")
    @classmethod
    def strip_origin_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("trusted_origins", mode="after")
    @classmethod
    def normalize_origins(cls, values: list[str]) -> list[str]:
        return [value.rstrip("/") for value in values]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment == "production" and not self.session_cookie_secure:
            raise ValueError("production requires TRAINLAB_SESSION_COOKIE_SECURE=true")
        if self.public_origin not in self.trusted_origins:
            raise ValueError("public_origin must be included in trusted_origins")
        if self.session_ttl_days < 1:
            raise ValueError("session_ttl_days must be positive")
        if self.login_failure_limit < 1 or self.login_lock_minutes < 1:
            raise ValueError("login throttle settings must be positive")
        if self.fit_upload_max_bytes < 1:
            raise ValueError("fit_upload_max_bytes must be positive")
        if self.import_processing_stale_minutes < 1:
            raise ValueError("import_processing_stale_minutes must be positive")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
