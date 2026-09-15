"""VC-005 retires commands, while mapped migration functions remain testable."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = json.loads((ROOT / "docs/entrypoint-inventory.json").read_text())
ENTRIES = INVENTORY["entries"]
RETIRED = [entry["path"] for entry in ENTRIES if entry["status"] == "retired"]


def _dispatchers(path: Path) -> list[ast.If]:
    return [
        node
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "__name__ == '__main__'"
    ]


def test_entrypoint_inventory_covers_actual_commands_not_name_prefixes() -> None:
    assert INVENTORY["contract_version"] == "VC-005"
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "skills").rglob("*.py")
        if _dispatchers(path)
    }
    assert actual == {entry["path"] for entry in ENTRIES}
    assert len(actual) == len(ENTRIES)
    for entry in ENTRIES:
        assert entry["status"] in {"current", "maintenance", "retired"}
        assert entry["purpose"] and entry["exit_task"]


@pytest.mark.parametrize("relative", RETIRED)
def test_retired_commands_never_dispatch_business_main(relative: str) -> None:
    dispatchers = _dispatchers(ROOT / relative)
    assert len(dispatchers) == 1
    body = dispatchers[0].body
    assert len(body) == 1
    assert ast.unparse(body[0]) == "raise SystemExit('legacy_runtime_retired')"
    # Retained functions support the explicitly mapped migration regressions only.
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in ast.parse((ROOT / relative).read_text()).body
    )


@pytest.mark.parametrize("relative", RETIRED)
@pytest.mark.parametrize("argument", ["--help", "--retired-probe"])
def test_retired_commands_fail_closed_in_real_subprocess(
    relative: str, argument: str, tmp_path: Path
) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / relative), argument],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "legacy_runtime_retired"
    assert list(tmp_path.iterdir()) == []


def test_current_and_explicit_maintenance_commands_remain_available() -> None:
    active = {entry["path"] for entry in ENTRIES if entry["status"] != "retired"}
    assert "skills/_shared/fit_weekly/detail_server.py" in active
    assert "skills/garmin-sync/scripts/mcp_server_guard.py" in active
    assert "skills/gmail-sender/scripts/gmail_rest_auth.py" in active
    for relative in active:
        body = _dispatchers(ROOT / relative)[0].body
        assert ast.unparse(body[0]) == "raise SystemExit(main())"
