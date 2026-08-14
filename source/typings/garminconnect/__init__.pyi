from collections.abc import Callable
from typing import Any


class Garmin:
    ActivityDownloadFormat: Any
    client: Any

    def __init__(
        self,
        email: str | None = ...,
        password: str | None = ...,
        *,
        is_cn: bool = ...,
        prompt_mfa: Callable[[], str] | None = ...,
        retry_attempts: int = ...,
    ) -> None: ...

    def login(self, tokenstore: str | None = ...) -> tuple[str | None, str | None]: ...
    def __getattr__(self, name: str) -> Any: ...
