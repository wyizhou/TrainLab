from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_repository_quality.py"


@pytest.mark.parametrize(
    "check",
    ("frozen-contracts", "markdown-links", "email-template-sync", "all"),
)
def test_repository_quality_checks_are_reproducible_offline(check: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), check],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "passed"
    assert receipt["counts"]
