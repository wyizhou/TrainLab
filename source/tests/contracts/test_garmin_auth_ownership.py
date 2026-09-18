from __future__ import annotations

import ast
from pathlib import Path


def test_auth_sdk_and_persistence_have_one_owner() -> None:
    package = Path(__file__).resolve().parents[2] / "skills/_shared/scripts/trainlab"
    paths = [package / name for name in ("garmin_sync.py", "garmin_auth_cli.py", "garmin_auth_maintenance.py")]
    paths += list((Path(__file__).resolve().parents[2] / "skills/local-web/scripts").glob("*.py"))
    for path in paths:
        text = path.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith(("garth", "garminconnect")) for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("garth", "garminconnect", "trainlab.garmin_auth_sdk", "trainlab.garmin_auth_store"))
        assert all(fragment not in text for fragment in ("updated_config", "refresh_auth", "GARMIN_CONFIG_PATH", "oauth1_token", "oauth2_token", "garmin.json"))
    for name in ("garmin_auth.py", "garmin_auth_sdk.py", "garmin_auth_store.py", "garmin_auth_maintenance.py"):
        text = (package / name).read_text()
        assert "input(" not in text and "getpass" not in text
