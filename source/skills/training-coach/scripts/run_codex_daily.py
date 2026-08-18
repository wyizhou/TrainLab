#!/usr/bin/env python3
"""Thin CLI for the single approved M9 Codex daily attempt."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from codex_attempt_runtime import main  # noqa: E402, I001


if __name__ == "__main__":
    raise SystemExit(main())
