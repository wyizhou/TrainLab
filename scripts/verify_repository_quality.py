#!/usr/bin/env python3
"""Offline repository contract, documentation, and template checks."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
_SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "archive",
        "build",
        "dist",
        "logs",
        "node_modules",
        "state",
    }
)
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
_REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)", re.MULTILINE)
_TEMPLATE_PAIRS = (
    (
        "design/trainlab-daily-report-email.html",
        "src/trainlab/email_templates/templates/daily_report.html",
    ),
    (
        "design/trainlab-weekly-report-email.html",
        "src/trainlab/email_templates/templates/weekly_report.html",
    ),
    (
        "design/trainlab-mail-reply-email.html",
        "src/trainlab/email_templates/templates/mail_reply.html",
    ),
)


class QualityCheckError(RuntimeError):
    """A deterministic repository invariant is not satisfied."""


def _markdown_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in _SKIP_DIRECTORIES)
        base = Path(directory)
        for name in sorted(files):
            if name.lower().endswith(".md"):
                yield base / name


def _without_fenced_code(text: str) -> str:
    visible: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            visible.append(line)
    return "\n".join(visible)


def _link_targets(text: str) -> Iterable[str]:
    for pattern in (_INLINE_LINK, _REFERENCE_LINK):
        for match in pattern.finditer(text):
            yield match.group("target").strip().strip("<>")


def check_markdown_links(root: Path = ROOT) -> int:
    checked = 0
    failures: list[str] = []
    resolved_root = root.resolve()
    for source in _markdown_files(resolved_root):
        text = _without_fenced_code(source.read_text(encoding="utf-8"))
        for raw_target in _link_targets(text):
            parsed = urlsplit(raw_target)
            if (
                not parsed.path
                or parsed.scheme
                or parsed.netloc
                or raw_target.startswith(("#", "/"))
            ):
                continue
            target = (source.parent / unquote(parsed.path)).resolve()
            checked += 1
            try:
                target.relative_to(resolved_root)
            except ValueError:
                failures.append(
                    f"{source.relative_to(resolved_root)}: outside root: {raw_target}"
                )
                continue
            if not target.exists():
                failures.append(
                    f"{source.relative_to(resolved_root)}: missing: {raw_target}"
                )
    if failures:
        raise QualityCheckError("markdown_link_check_failed\n" + "\n".join(failures))
    return checked


def check_frozen_contracts(root: Path = ROOT) -> int:
    from trainlab.orchestration.contracts import (
        FROZEN_CONTRACT_HASHES,
        verify_frozen_contracts,
    )

    verify_frozen_contracts(root)
    return len(FROZEN_CONTRACT_HASHES)


def check_email_template_sync(root: Path = ROOT) -> int:
    failures: list[str] = []
    for design_name, runtime_name in _TEMPLATE_PAIRS:
        design = root / design_name
        runtime = root / runtime_name
        if not design.is_file() or not runtime.is_file():
            failures.append(f"template_missing:{design_name}:{runtime_name}")
        elif design.read_bytes() != runtime.read_bytes():
            failures.append(f"template_drift:{design_name}:{runtime_name}")
    if failures:
        raise QualityCheckError("email_template_sync_failed\n" + "\n".join(failures))
    return len(_TEMPLATE_PAIRS)


_CHECKS: dict[str, Callable[[Path], int]] = {
    "frozen-contracts": check_frozen_contracts,
    "markdown-links": check_markdown_links,
    "email-template-sync": check_email_template_sync,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_repository_quality")
    parser.add_argument("check", choices=("all", *_CHECKS))
    args = parser.parse_args(argv)
    selected = tuple(_CHECKS) if args.check == "all" else (args.check,)
    counts: dict[str, int] = {}
    try:
        for name in selected:
            counts[name] = _CHECKS[name](ROOT)
    except (OSError, UnicodeError, ValueError, QualityCheckError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "1",
                    "status": "failed",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {"schema_version": "1", "status": "passed", "counts": counts},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
