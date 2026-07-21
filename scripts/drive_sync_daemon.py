#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trainlab.config import load_settings
from trainlab.sync import drive_sync_daemon


if __name__ == "__main__":
    drive_sync_daemon(load_settings(ROOT))
