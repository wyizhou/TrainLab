#!/usr/bin/env python3
"""Build a data-free TrainLab wheel and runtime source bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "product"
DIST = ROOT / "dist"

ALLOWED_FILES = frozenset({"pyproject.toml", "requirements.lock", "README.md"})
ALLOWED_ROOTS = frozenset(
    {"config", "deploy", "design", "docs", "harness", "references", "scripts", "src"}
)
DEVELOPMENT_ROOTS = frozenset({"archive", "tests"})
SKELETON_ROOTS = frozenset({"logs", "state", "test_data"})
PUBLIC_CONFIG = frozenset(
    {
        "README.md",
        "analysis.yaml",
        "gmail_mcp.example.yaml",
        "orchestration.example.yaml",
        "trainlab.example.json",
    }
)
FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".orchestration",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "exec-plans",
        "logs",
        "state",
        "test_data",
    }
)
FORBIDDEN_SUFFIXES = frozenset({".db", ".fit", ".lock", ".log", ".sqlite", ".sqlite3"})
FORBIDDEN_NAMES = frozenset(
    {
        ".env",
        "PLANS.md",
        "credentials.json",
        "foundation.yaml",
        "garmin.yaml",
        "gmail_mcp.yaml",
        "orchestration.yaml",
        "rclone.conf",
        "token.json",
        "trainlab.json",
        "trainlab.production.yaml",
        "memory.md",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_visible_product_files() -> tuple[Path, ...]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "product",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    product_root = PRODUCT.resolve(strict=True)
    for value in result.stdout.splitlines():
        candidate = (ROOT / value).resolve(strict=True)
        relative = candidate.relative_to(product_root)
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError(f"product_build_unsafe_file:{relative}")
        if relative.parts[0] in DEVELOPMENT_ROOTS:
            continue
        if relative.parts[0] in SKELETON_ROOTS:
            if relative.name != ".gitkeep":
                raise RuntimeError(f"product_build_tracked_private_path:{relative}")
            continue
        paths.append(relative)
    return tuple(sorted(set(paths), key=lambda value: value.as_posix()))


def _validate(relative: Path) -> None:
    if set(relative.parts) & FORBIDDEN_PARTS:
        raise RuntimeError(f"product_build_forbidden_path:{relative}")
    if len(relative.parts) == 1 and relative.name in ALLOWED_FILES:
        return
    if (
        relative.name in FORBIDDEN_NAMES
        or relative.suffix.lower() in FORBIDDEN_SUFFIXES
    ):
        raise RuntimeError(f"product_build_forbidden_file:{relative}")
    if len(relative.parts) == 1:
        raise RuntimeError(f"product_build_root_not_allowlisted:{relative}")
    if relative.parts[0] not in ALLOWED_ROOTS:
        raise RuntimeError(f"product_build_root_not_allowlisted:{relative}")
    if relative.parts[0] == "config" and relative.name not in PUBLIC_CONFIG:
        raise RuntimeError(f"product_build_private_config:{relative}")


def _write_bundle(files: tuple[Path, ...], destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            source = PRODUCT / relative
            info = zipfile.ZipInfo(f"trainlab-runtime/{relative.as_posix()}")
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.external_attr = (source.stat().st_mode & 0o777) << 16
            archive.writestr(info, source.read_bytes())


def build(*, python: str) -> dict[str, object]:
    files = _git_visible_product_files()
    if not files:
        raise RuntimeError("product_build_empty")
    for relative in files:
        _validate(relative)

    DIST.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trainlab-build-") as temporary:
        wheel_root = Path(temporary) / "wheel"
        wheel_root.mkdir()
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheel_root),
                str(PRODUCT),
            ],
            check=True,
        )
        wheels = tuple(wheel_root.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("product_build_wheel_count_invalid")
        wheel = DIST / wheels[0].name
        shutil.copy2(wheels[0], wheel)

    bundle = DIST / "trainlab-runtime.zip"
    _write_bundle(files, bundle)
    outputs = (wheel, bundle)
    manifest = {
        "schema_version": "1",
        "source_root": "product",
        "source_file_count": len(files),
        "outputs": [
            {"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}
            for path in outputs
        ],
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        result = build(python=args.python)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "passed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
