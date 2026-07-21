#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trainlab.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["watchdog", "--once"]))
