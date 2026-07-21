#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trainlab.config import load_settings
from trainlab.ingest import ingest_daemon


if __name__ == "__main__":
    ingest_daemon(load_settings(ROOT))
