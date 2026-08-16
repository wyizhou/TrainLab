#!/usr/bin/env python3
"""Check goal/module structure without printing private goal content."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def headings_and_labels(text: str) -> tuple[list[str], list[str]]:
    headings = [line.strip() for line in text.splitlines() if line.startswith("#")]
    labels = []
    for line in text.splitlines():
        if not line.startswith("-"):
            continue
        match = re.match(r"^-\s*(.+?)[：:]", line)
        if match:
            labels.append(match.group(1).strip())
    return headings, labels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    args = parser.parse_args()
    goal = args.goal.read_text(encoding="utf-8")
    module = args.module.read_text(encoding="utf-8")
    goal_headings, goal_labels = headings_and_labels(goal)
    module_headings, module_labels = headings_and_labels(module)
    mode = args.goal.stat().st_mode & 0o777
    errors: list[str] = []
    if mode != 0o600:
        errors.append("goal_mode_not_0600")
    if goal_headings != module_headings or goal_labels != module_labels:
        errors.append("goal_module_structure_mismatch")
    module_values = [
        line.split("：", 1)[1].strip()
        for line in module.splitlines()
        if line.startswith("-") and "：" in line
    ]
    if not module_values or any(
        "【" not in value or "】" not in value for value in module_values
    ):
        errors.append("private_value_in_module")
    print({"status": "passed" if not errors else "failed", "errors": errors})
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
