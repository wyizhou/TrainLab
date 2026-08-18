#!/usr/bin/env python3
"""Start the pinned Garmin MCP with refresh and retry paths disabled."""

from __future__ import annotations

import importlib
import os
from typing import Any


def install_guard(garminconnect_module: Any, client_module: Any) -> None:
    """Force cached-token-only, single-attempt behavior before MCP imports it."""

    garmin_class = garminconnect_module.Garmin
    original_init = garmin_class.__init__
    authentication_error = garminconnect_module.GarminConnectAuthenticationError

    def guarded_init(self: Any, *args: Any, **kwargs: Any) -> None:
        email = kwargs.get("email", args[0] if args else None)
        password = kwargs.get("password", args[1] if len(args) > 1 else None)
        if email or password:
            raise authentication_error("credential_login_disabled")
        kwargs["retry_attempts"] = 0
        original_init(self, *args, **kwargs)

    def refresh_disabled(*_args: Any, **_kwargs: Any) -> None:
        raise authentication_error("cached_token_refresh_disabled")

    def interactive_auth_disabled(*_args: Any, **_kwargs: Any) -> None:
        raise authentication_error("interactive_auth_disabled")

    def provider_fallback_disabled(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def load_profile_and_settings_once(self: Any) -> None:
        try:
            profile = self.client.connectapi("/userprofile-service/socialProfile")
        except Exception as exc:
            raise authentication_error("Failed to retrieve social profile") from exc
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("displayName"), str)
            or not profile["displayName"]
        ):
            raise authentication_error("Invalid profile data found")
        self.display_name = profile["displayName"]
        self.full_name = str(profile.get("fullName", ""))
        self.unit_system = None

    garmin_class.__init__ = guarded_init
    garmin_class._load_profile_and_settings = load_profile_and_settings_once
    garmin_class.resume_login = interactive_auth_disabled
    garmin_class.get_training_status = provider_fallback_disabled
    garmin_class.get_user_profile = provider_fallback_disabled
    client_module.Client._refresh_session = refresh_disabled
    client_module.Client._refresh_di_token = refresh_disabled


def main() -> int:
    garminconnect_module = importlib.import_module("garminconnect")
    client_module = importlib.import_module("garminconnect.client")
    install_guard(garminconnect_module, client_module)
    if os.environ.get("TRAINLAB_M9_GUARD_SELF_TEST") == "1":
        return 0
    garmin_mcp = importlib.import_module("garmin_mcp")
    garmin_mcp.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
