"""Direct TrainLab entry point for the source-only development layout.

The wrapper deliberately bootstraps the source directory before importing the
product package.  This keeps direct execution independent of the current
working directory while still allowing an explicit instance root override.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("TRAINLAB_INSTANCE_ROOT", str(SOURCE_ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import src  # noqa: E402

_EXPECTED_PACKAGE_ROOT = (SOURCE_ROOT / "src").resolve()
_ACTUAL_PACKAGE_ROOT = Path(src.__file__).resolve().parent
if _ACTUAL_PACKAGE_ROOT != _EXPECTED_PACKAGE_ROOT:
    raise RuntimeError("trainlab_source_package_mismatch")

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "__garmin-smoke-worker":
        from src.garmin_smoke_runtime import _worker

        raise SystemExit(_worker(Path(sys.argv[2])))
    raise SystemExit(main(sys.argv[1:]))
