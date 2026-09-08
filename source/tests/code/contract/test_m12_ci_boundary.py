"""Exercise the actual CI archive check without private or pre-existing data."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def archive_command() -> list[str]:
    lines = (ROOT / ".github/workflows/ci.yml").read_text().splitlines()
    commands = [
        shlex.split(line.strip())
        for line in lines
        if line.strip().startswith("git check-ignore") and "data-backup" in line
    ]
    assert len(commands) == 1
    command = commands[0]
    assert len(command) == 4 and command[:3] == ["git", "check-ignore", "-q"]
    return command


def checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
    )
    repo = tmp_path / "checkout"
    source = repo / "source"
    source.mkdir(parents=True)
    templates = tmp_path / "empty-templates"
    templates.mkdir()
    subprocess.run(
        ["git", "init", "-q", f"--template={templates}", str(repo)],
        env=env,
        capture_output=True,
        check=True,
    )
    (repo / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    return source, env


@pytest.mark.parametrize("state", ["missing", "empty", "populated"])
def test_ci_archive_check_does_not_require_the_archive(
    tmp_path: Path, state: str
) -> None:
    source, env = checkout(tmp_path)
    archive = source.parent / "data-backup"
    if state != "missing":
        archive.mkdir()
    if state == "populated":
        (archive / "public-synthetic.txt").write_text("synthetic archive fixture")
    result = subprocess.run(archive_command(), cwd=source, env=env, capture_output=True)
    assert result.returncode == 0
    assert archive.exists() is (state != "missing")
    for path, expected in (
        ("../data-backup/example.txt", 0),
        ("../data-backup/nested/example.txt", 0),
        ("public-note.txt", 1),
    ):
        probe = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=source,
            env=env,
            capture_output=True,
        )
        assert probe.returncode == expected


def test_ci_archive_check_still_rejects_a_missing_ignore_rule(tmp_path: Path) -> None:
    source, env = checkout(tmp_path)
    ignore = source.parent / ".gitignore"
    original = ignore.read_text()
    assert "/data-backup/\n" in original
    ignore.write_text(original.replace("/data-backup/\n", ""))
    result = subprocess.run(archive_command(), cwd=source, env=env, capture_output=True)
    assert result.returncode == 1
    assert not (source.parent / "data-backup").exists()


def test_ci_runs_full_active_tests_on_macos_and_linux() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "os: [ubuntu-latest, macos-latest]" in text
    assert "runs-on: ${{ matrix.os }}" in text
    assert "python -m pytest tests/code -q" in text
    assert "test_m12_*.py" not in text
    assert "continue-on-error" not in text


def test_ci_compile_is_read_only_and_schema_roots_are_declared() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "compileall" not in text
    assert 'compile(path.read_bytes(), str(path), "exec")' in text
    assert "schema_documents" in text
    assert "runtime_resources.SCHEMAS" in text
