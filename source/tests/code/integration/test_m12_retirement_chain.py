from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from skills._shared.fit_weekly import runtime_resources, storage

SOURCE = Path(__file__).resolve().parents[3]


def test_isolated_unified_import_sync_weekly_publication_reconcile_and_move(tmp_path):
    isolated = tmp_path / "isolated-source"
    isolated.mkdir(mode=0o700)
    runtime = set(
        runtime_resources.files(SOURCE, collection=True, entrypoint=True, history=True)
    )
    active_tests = {
        p
        for p in (SOURCE / "tests/code").rglob("*")
        if p.is_file() and p.suffix in (".py", ".json")
    }
    copied = []
    for source in sorted(runtime | active_tests):
        relative = source.relative_to(SOURCE)
        target = isolated / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(0o600)
        assert source.read_bytes() == target.read_bytes()
        copied.append(str(relative))
    manifest = json.loads((SOURCE / "docs/legacy-test-mapping.json").read_text())
    assert not any(
        (isolated / r["path"]).exists() for r in manifest["retired_resources"]
    )
    assert not (isolated / "skills/_shared/scripts/archive_legacy.py").exists()
    assert not (isolated / "data-backup").exists()
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    temporary = tmp_path / "child-tmp"
    temporary.mkdir(mode=0o700)
    basetemp = temporary / "pytest"
    command = [
        sys.executable,
        "-I",
        "-m",
        "pytest",
        "tests/code/fixtures/m12_retirement_chain_driver.py",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(basetemp),
    ]
    environment = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "en_US.UTF-8",
        "TRAINLAB_CHAIN_EVIDENCE": str(isolated / "chain-evidence.json"),
    }
    assert Path(environment["TMPDIR"]).resolve().is_relative_to(tmp_path.resolve())
    assert Path(command[-1]).resolve().is_relative_to(tmp_path.resolve())
    assert temporary.stat().st_mode & 0o777 == 0o700
    result = subprocess.run(
        command,
        cwd=isolated,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((isolated / "chain-evidence.json").read_text())
    assert evidence["model_processes"] == 2 and evidence["gmail_sends"] == 2
    assert evidence["gmail_label_creates"] == 1 and evidence["gmail_label_applies"] == 2
    assert (
        evidence["workouts"] == evidence["schedules"] == 3
        and evidence["move_repeat_calls"] == 0
    )
    destination = os.environ.get("TRAINLAB_RETIREMENT_EVIDENCE")
    if destination:
        out = Path(destination)
        out.write_text(
            json.dumps(
                {
                    "command": command,
                    "cwd": str(isolated),
                    "temporary_environment": {
                        "TMPDIR": environment["TMPDIR"],
                        "basetemp": str(basetemp),
                    },
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "copied_files": [
                        {
                            "path": p,
                            "sha256": storage.digest((isolated / p).read_bytes()),
                        }
                        for p in copied
                    ],
                    "chain": evidence,
                },
                indent=2,
            )
            + "\n"
        )
