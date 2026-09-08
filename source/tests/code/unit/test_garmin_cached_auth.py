"""Current cached Garmin authentication guard; migrated from M9 unchanged."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


def _module(name: str):
    path = (
        Path(__file__).resolve().parents[3]
        / "skills/garmin-sync/scripts"
        / (name + ".py")
    )
    spec = importlib.util.spec_from_file_location("current_" + name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_guard_disables_credentials_refresh_and_library_retry() -> None:
    guard = _module("mcp_server_guard")

    class AuthenticationError(RuntimeError):
        pass

    class Garmin:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.kwargs = kwargs

        def resume_login(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("unpatched")

        def get_training_status(self, *_args: object) -> dict[str, Any]:
            raise AssertionError("unpatched")

        def get_user_profile(self) -> dict[str, Any]:
            raise AssertionError("unpatched")

    class Client:
        def _refresh_session(self) -> None:
            raise AssertionError("unpatched")

        def _refresh_di_token(self) -> None:
            raise AssertionError("unpatched")

    garmin_module = type(
        "GarminModule",
        (),
        {"Garmin": Garmin, "GarminConnectAuthenticationError": AuthenticationError},
    )
    client_module = type("ClientModule", (), {"Client": Client})
    guard.install_guard(garmin_module, client_module)
    instance = Garmin(is_cn=True)
    assert instance.kwargs["retry_attempts"] == 0
    with pytest.raises(AuthenticationError, match="credential_login_disabled"):
        Garmin(email="forbidden", password="forbidden")
    with pytest.raises(AuthenticationError, match="cached_token_refresh_disabled"):
        Client()._refresh_session()
    with pytest.raises(AuthenticationError, match="cached_token_refresh_disabled"):
        Client()._refresh_di_token()
    with pytest.raises(AuthenticationError, match="interactive_auth_disabled"):
        instance.resume_login({}, "forbidden")
    assert instance.get_training_status("2026-08-16") == {}
    assert instance.get_user_profile() == {}


def test_mcp_guard_initialization_uses_one_profile_entry_without_settings() -> None:
    guard = _module("mcp_server_guard")

    class AuthenticationError(RuntimeError):
        pass

    class Garmin:
        client: Any
        display_name: str | None
        full_name: str
        unit_system: str | None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.username = "cached-user"
            self.garmin_connect_user_settings_url = "/settings"

        def _load_profile_and_settings(self) -> None:
            raise AssertionError("unpatched")

    class Client:
        def _refresh_session(self) -> None:
            raise AssertionError("unpatched")

        def _refresh_di_token(self) -> None:
            raise AssertionError("unpatched")

    garmin_module = type(
        "GarminModule",
        (),
        {"Garmin": Garmin, "GarminConnectAuthenticationError": AuthenticationError},
    )
    client_module = type("ClientModule", (), {"Client": Client})
    guard.install_guard(garmin_module, client_module)

    calls: list[str] = []

    class ProfileClient:
        def connectapi(self, path: str) -> dict[str, Any]:
            calls.append(path)
            if path != "/userprofile-service/socialProfile":
                raise AssertionError("settings or other initialization is forbidden")
            return {"displayName": "provider-user", "fullName": "Provider User"}

    instance = Garmin()
    instance.client = ProfileClient()
    instance._load_profile_and_settings()
    assert calls == ["/userprofile-service/socialProfile"]
    assert instance.display_name == "provider-user"
    assert instance.full_name == "Provider User"
    assert instance.unit_system is None

    failed_calls: list[str] = []

    class FailingClient:
        def connectapi(self, path: str) -> dict[str, Any]:
            failed_calls.append(path)
            raise RuntimeError("provider failure")

    failed = Garmin()
    failed.client = FailingClient()
    with pytest.raises(AuthenticationError, match="social profile"):
        failed._load_profile_and_settings()
    assert failed_calls == ["/userprofile-service/socialProfile"]
