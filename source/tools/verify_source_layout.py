"""Check the source-only layout and private-data boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def main() -> int:
    forbidden = ("src", "tests", "config", "state", "logs", "pyproject.toml")
    failures = [name for name in forbidden if (REPO_ROOT / name).exists()]
    if (ROOT / "src" / "orchestration").exists():
        failures.append("source/src/orchestration")
    if (ROOT / "source").exists():
        failures.append("source/source")
    for private_path in (
        "data-backup",
        "source/state/data.db",
        "source/logs/runtime.log",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", private_path],
            cwd=REPO_ROOT,
            check=False,
        )
        if ignored.returncode != 0:
            failures.append(f"private-data-ignore:{private_path}")
    if failures:
        raise SystemExit("source_layout_failed:" + ",".join(failures))
    print("source-layout=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
