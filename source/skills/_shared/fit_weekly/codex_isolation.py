"""Host-only child masks for ambient Codex instructions and skill catalogs.

Not a model-tool sandbox or an authorization grant. Use together with the fixed
capability configuration, a current public CLI probe, and process supervision.
No configuration or authentication bytes are read, copied or rewritten here.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from skills._shared.fit_weekly import fit_sync, storage

VERSION = "fit-codex-isolation-1"
SYSTEM_ROOTS = (Path("/etc/codex/skills"),)
DOCUMENTS = ("AGENTS.md", "AGENTS.override.md")


def host_path(value: Path) -> Path:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or value == Path("/")
        or ".." in value.parts
        or any(ord(c) < 32 or ord(c) == 127 for c in str(value))
    ):
        raise ValueError("codex_isolation_path_invalid")
    return value


def locations(
    home: Path, auth: Path, work: Path, systems: Sequence[Path]
) -> tuple[Path, ...]:
    proposed: dict[Path, bool] = {}
    for parent in {auth, home / ".codex"}:
        proposed.update({parent / name: False for name in DOCUMENTS})
        proposed.update(
            {parent / name: True for name in ("skills", "plugins", "memories")}
        )
    proposed[home / ".agents" / "skills"] = True
    proposed.update({host_path(p): True for p in systems})
    for parent in (work, *work.parents):
        proposed.update({parent / name: False for name in DOCUMENTS})
        proposed[parent / ".agents" / "skills"] = True
        proposed[parent / ".codex" / "skills"] = True
    found: set[Path] = set()
    for path, directory in proposed.items():
        host_path(path)
        resolved = host_path(path.resolve())
        # Both lexical names and resolved targets matter to Seatbelt. Linux
        # mounts only canonical targets; aliases then see the same empty mask.
        found.update((path, resolved))
        try:
            mode = resolved.stat().st_mode
        except FileNotFoundError:
            continue
        if (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)) is not True:
            raise ValueError("codex_isolation_path_invalid")
    ordered = tuple(sorted(found, key=str))
    required = (home, auth, work, auth / "auth.json", auth / "installation_id")
    if any(p.is_relative_to(target) for p in required for target in ordered):
        raise ValueError("codex_isolation_conflict")
    return ordered


def empty_masks(work: Path) -> tuple[Path, Path]:
    folder = work / "isolation"
    fit_sync.private_directory(folder)
    blank_dir, blank_file = folder / "empty", folder / "empty.txt"
    fit_sync.private_directory(blank_dir)
    if list(blank_dir.iterdir()):
        raise ValueError("codex_isolation_scaffold_invalid")
    # Empty by design: this is a configuration mask, never a process result.
    # It is created only inside the private job, not in the user's global tree.
    try:
        fd = os.open(blank_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        storage.private_entry(blank_file)
        if blank_file.stat().st_size != 0:
            raise ValueError("codex_isolation_scaffold_invalid")
        fd = os.open(blank_file, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    storage.private_entry(blank_file)
    if set(folder.iterdir()) != {blank_dir, blank_file}:
        raise ValueError("codex_isolation_scaffold_invalid")
    storage.sync_dir(folder)
    return blank_dir, blank_file


@dataclass(frozen=True)
class Isolation:
    platform_name: str
    home: Path
    codex_home: Path
    work: Path
    blocked: tuple[Path, ...]
    prefix: tuple[str, ...]

    def validate_environment(self, env: Mapping[str, str]) -> None:
        try:
            actual_home = host_path(Path(env["HOME"]))
            actual_auth = host_path(
                Path(env.get("CODEX_HOME", str(actual_home / ".codex")))
            )
            if (
                actual_home.resolve() != self.home
                or actual_auth.resolve() != self.codex_home
            ):
                raise ValueError("mismatch")
        except (KeyError, TypeError, ValueError, OSError, RuntimeError):
            raise ValueError("codex_isolation_environment_invalid") from None

    def command(self, argv: Sequence[str]) -> list[str]:
        if (
            isinstance(argv, (str, bytes))
            or not argv
            or any(not isinstance(x, str) or "\0" in x for x in argv)
            or not Path(argv[0]).is_absolute()
        ):
            raise ValueError("codex_isolation_command_invalid")
        return [*self.prefix, *argv]


def prepare(
    *,
    work: Path,
    home: Path,
    codex_home: Path,
    platform_name: str | None = None,
    executable: Path | None = None,
    system_roots: Sequence[Path] = SYSTEM_ROOTS,
) -> Isolation:
    """Prepare only; caller validates unchanged child env before executing.

    Parameters are trusted Host deployment facts, not AI tool arguments. No
    executable is started here. Explicit backend/system paths enable synthetic
    checks; production selects the host platform and an already installed tool.
    """
    try:
        work, home, auth = (
            host_path(host_path(p).resolve()) for p in (work, home, codex_home)
        )
        storage.private_entry(work, directory=True)
        if not home.is_dir() or not auth.is_dir():
            raise ValueError("codex_isolation_path_invalid")
        selected = platform.system() if platform_name is None else platform_name
        tool = {"Darwin": "sandbox-exec", "Linux": "bwrap"}.get(selected)
        if tool is None:
            raise ValueError("codex_isolation_unavailable")
        installed = str(executable) if executable is not None else shutil.which(tool)
        if not installed:
            raise ValueError("codex_isolation_unavailable")
        program = host_path(Path(installed)).resolve()
        if not program.is_file() or not os.access(program, os.X_OK):
            raise ValueError("codex_isolation_unavailable")
        blocked = locations(home, auth, work, system_roots)
        if any(program.is_relative_to(path) for path in blocked):
            raise ValueError("codex_isolation_conflict")
        prefix: tuple[str, ...]
        if selected == "Darwin":
            profile = "(version 1)(allow default)" + "".join(
                "(deny file-read* (subpath "
                + json.dumps(str(p), ensure_ascii=False)
                + "))"
                for p in blocked
            )
            prefix = (str(program), "-p", profile)
        else:
            # Codex bootstraps bundled skills under this directory. If absent,
            # do not create a global mount destination or silently leave it open.
            if not (auth / "skills").is_dir():
                raise ValueError("codex_isolation_unavailable")
            existing = sorted({p.resolve() for p in blocked if p.exists()}, key=str)
            # Remove nested mounts covered by a parent mask. Never ask bwrap to
            # create a missing destination on a host-backed writable filesystem.
            targets = [
                p
                for p in existing
                if not any(p != q and p.is_relative_to(q) for q in existing)
            ]
            blank_dir, blank_file = empty_masks(work)
            args = [
                str(program),
                "--die-with-parent",
                "--bind",
                "/",
                "/",
                "--dev-bind",
                "/dev",
                "/dev",
                "--cap-drop",
                "ALL",
            ]
            for target in targets:
                args.extend(
                    (
                        "--ro-bind",
                        str(blank_dir if target.is_dir() else blank_file),
                        str(target),
                    )
                )
            prefix = (*args, "--")
        # No new session/PID namespace: model_process must observe and stop the
        # same session containing the wrapper, Codex and its FIT MCP process.
        return Isolation(selected, home, auth, work, blocked, prefix)
    except ValueError as exc:
        if str(exc).startswith("codex_isolation_"):
            raise
        raise ValueError("codex_isolation_path_invalid") from None
    except (OSError, RuntimeError, TypeError):
        raise ValueError("codex_isolation_unavailable") from None
