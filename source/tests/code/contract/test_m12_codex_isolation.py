"""Synthetic Host-only isolation checks; never load real user auth or Codex."""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import model_process


def module():
    return importlib.import_module("skills._shared.fit_weekly.codex_isolation")


def layout(tmp_path):
    tmp_path.chmod(0o700)
    home = tmp_path / "user"
    home.mkdir(mode=0o700)
    auth = home / ".codex"
    auth.mkdir(mode=0o700)
    (auth / "skills").mkdir(mode=0o700)
    (auth / "skills" / "SKILL.md").write_text("PUBLIC_SKILL_SENTINEL")
    (auth / "AGENTS.md").write_text("PUBLIC_INSTRUCTION_SENTINEL")
    (auth / "auth.json").write_text("PUBLIC_NOT_AN_AUTH_CREDENTIAL")
    work = tmp_path / "job"
    work.mkdir(mode=0o700)
    backend = tmp_path / "backend"
    backend.write_text("#!/bin/sh\nexit 91\n")
    backend.chmod(0o700)
    return home, auth, work, backend


def prepare(tmp_path, *, platform_name="Darwin"):
    home, auth, work, backend = layout(tmp_path)
    guard = module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name=platform_name,
        executable=backend,
        system_roots=(),
    )
    return guard, home, auth, work, backend


def test_darwin_only_child_policy_keeps_auth_location(tmp_path):
    guard, home, auth, work, backend = prepare(tmp_path)
    argv = guard.command([sys.executable, "-c", "pass"])
    assert argv[:2] == [str(backend), "-p"]
    assert argv[-3:] == [sys.executable, "-c", "pass"]
    assert "(allow default)" in argv[2]
    assert str(auth / "skills") in argv[2]
    assert str(auth / "AGENTS.md") in argv[2]
    assert str(home / ".agents" / "skills") in argv[2]
    assert "auth.json" not in argv[2]
    assert "file-write" not in argv[2]
    assert list(work.iterdir()) == []
    guard.validate_environment({"HOME": str(home), "CODEX_HOME": str(auth)})
    assert (auth / "auth.json").read_text() == "PUBLIC_NOT_AN_AUTH_CREDENTIAL"


def test_linux_masks_existing_targets_without_new_session(tmp_path):
    guard, home, auth, work, backend = prepare(tmp_path, platform_name="Linux")
    argv = guard.command([sys.executable, "-c", "pass"])
    assert argv[:4] == [str(backend), "--die-with-parent", "--bind", "/"]
    assert "--new-session" not in argv and "--unshare-pid" not in argv
    assert argv[-4:] == ["--", sys.executable, "-c", "pass"]
    mounts = [argv[n + 1 : n + 3] for n, x in enumerate(argv) if x == "--ro-bind"]
    assert len(mounts) == 2
    assert {x[1] for x in mounts} == {str(auth / "skills"), str(auth / "AGENTS.md")}
    for origin, target in mounts:
        assert Path(origin).is_relative_to(work)
        assert Path(target).exists()
        mode = 0o700 if Path(origin).is_dir() else 0o600
        assert stat.S_IMODE(Path(origin).stat().st_mode) == mode
    assert [x for x in mounts if x[1].endswith("AGENTS.md")][0][0].endswith("empty.txt")
    assert (work / "isolation" / "empty.txt").read_bytes() == b""
    assert (auth / "auth.json").read_text() == "PUBLIC_NOT_AN_AUTH_CREDENTIAL"
    assert not (home / ".agents").exists()


def test_linux_preserves_standard_device_access(tmp_path):
    guard, home, auth, work, backend = prepare(tmp_path, platform_name="Linux")
    argv = guard.command([sys.executable])
    # Plain recursive --bind applies nodev. The original /dev mount is needed
    # for ordinary /dev/null and entropy access, not additional model tools.
    n = argv.index("--dev-bind")
    assert argv[n + 1 : n + 3] == ["/dev", "/dev"]


def test_parent_and_symlinked_skill_locations_are_covered(tmp_path):
    home, auth, work, backend = layout(tmp_path)
    target = tmp_path / "shared-skills"
    target.mkdir()
    link = home / ".agents"
    link.mkdir()
    (link / "skills").symlink_to(target, target_is_directory=True)
    (tmp_path / "AGENTS.override.md").write_text("PUBLIC_PARENT")
    guard = module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name="Darwin",
        executable=backend,
        system_roots=(),
    )
    assert target in guard.blocked
    assert link / "skills" in guard.blocked
    assert tmp_path / "AGENTS.override.md" in guard.blocked
    assert work / "AGENTS.md" in guard.blocked


@pytest.mark.parametrize("field", ["home", "codex_home", "work"])
@pytest.mark.parametrize("value", ["relative", "/", "bad\nname"])
def test_unsafe_host_paths_rejected_before_artifacts(tmp_path, field, value):
    home, auth, work, backend = layout(tmp_path)
    kwargs = dict(work=work, home=home, codex_home=auth)
    kwargs[field] = Path(value)
    with pytest.raises(ValueError, match="codex_isolation"):
        module().prepare(
            **kwargs, platform_name="Linux", executable=backend, system_roots=()
        )
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("platform_name", ["Windows", "darwin", "", "FreeBSD"])
def test_unknown_platform_does_not_fall_back(tmp_path, platform_name):
    home, auth, work, backend = layout(tmp_path)
    with pytest.raises(ValueError, match="codex_isolation_unavailable"):
        module().prepare(
            work=work,
            home=home,
            codex_home=auth,
            platform_name=platform_name,
            executable=backend,
            system_roots=(),
        )
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "not_executable", "directory"])
def test_backend_unavailable_never_creates_work_artifacts(tmp_path, kind):
    home, auth, work, backend = layout(tmp_path)
    if kind == "missing":
        backend = tmp_path / "not-installed"
    elif kind == "not_executable":
        backend.chmod(0o600)
    else:
        backend = tmp_path
    with pytest.raises(ValueError, match="codex_isolation_unavailable"):
        module().prepare(
            work=work,
            home=home,
            codex_home=auth,
            platform_name="Linux",
            executable=backend,
            system_roots=(),
        )
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("bad_target", ["auth", "work", "home"])
def test_skill_alias_cannot_mask_required_host_roots(tmp_path, bad_target):
    home, auth, work, backend = layout(tmp_path)
    aliases = home / ".agents"
    aliases.mkdir()
    (aliases / "skills").symlink_to(
        {"auth": auth, "work": work, "home": home}[bad_target]
    )
    with pytest.raises(ValueError, match="codex_isolation_conflict"):
        module().prepare(
            work=work,
            home=home,
            codex_home=auth,
            platform_name="Linux",
            executable=backend,
            system_roots=(),
        )
    assert list(work.iterdir()) == []


def test_linux_does_not_create_missing_codex_skill_root_on_host(tmp_path):
    home, auth, work, backend = layout(tmp_path)
    other_auth = home / "custom-auth"
    other_auth.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="codex_isolation_unavailable"):
        module().prepare(
            work=work,
            home=home,
            codex_home=other_auth,
            platform_name="Linux",
            executable=backend,
            system_roots=(),
        )
    assert not (other_auth / "skills").exists()
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("change", ["home", "codex_home", "relative"])
def test_environment_must_keep_original_auth_location(tmp_path, change):
    guard, home, auth, work, backend = prepare(tmp_path)
    env = {"HOME": str(home), "CODEX_HOME": str(auth)}
    env[
        {"home": "HOME", "codex_home": "CODEX_HOME", "relative": "CODEX_HOME"}[change]
    ] = "relative" if change == "relative" else str(work)
    with pytest.raises(ValueError, match="codex_isolation_environment_invalid"):
        guard.validate_environment(env)


def test_default_auth_location_and_safe_quoting(tmp_path):
    nested = tmp_path / '中文 "quoted" \\ names'
    nested.mkdir(mode=0o700)
    guard, home, auth, work, backend = prepare(nested)
    guard.validate_environment({"HOME": str(home)})
    assert (
        json.dumps(str(auth / "skills"), ensure_ascii=False)
        in guard.command([sys.executable])[2]
    )


def test_real_current_platform_child_isolated_with_same_session(tmp_path):
    home, auth, work, backend = layout(tmp_path)
    current = "Darwin" if sys.platform == "darwin" else "Linux"
    # Missing Linux Bubblewrap must fail closed; do not install a dependency or
    # call that availability check an actual Linux sandbox pass.
    import shutil

    actual = shutil.which("sandbox-exec" if current == "Darwin" else "bwrap")
    if actual is None:
        with pytest.raises(ValueError, match="codex_isolation_unavailable"):
            module().prepare(
                work=work,
                home=home,
                codex_home=auth,
                platform_name=current,
                system_roots=(),
            )
        return
    guard = module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name=current,
        executable=Path(actual),
        system_roots=(),
    )
    code = """
import json,os,sys
from pathlib import Path
with open('/dev/null','wb') as sink: sink.write(b'public')
with open('/dev/urandom','rb') as entropy: assert len(entropy.read(1)) == 1
blocked=[]
for name in sys.argv[1:3]:
 try:
  text=Path(name).read_text()
  blocked.append(not text)
 except (PermissionError,FileNotFoundError): blocked.append(True)
print(json.dumps({'blocked':blocked,'auth':Path(sys.argv[3]).read_text(),
 'same_session':os.getsid(0)==int(sys.argv[4]) if len(sys.argv)>4 else True}))
"""
    # The supervisor creates the session. A wrapper receives its SID before the
    # isolation program and executes that program without creating another SID.
    wrapped = [
        sys.executable,
        "-c",
        "import os,sys; os.execv(sys.argv[1],sys.argv[1:]+[str(os.getsid(0))])",
        *guard.command(
            [
                sys.executable,
                "-c",
                code,
                str(auth / "AGENTS.md"),
                str(auth / "skills" / "SKILL.md"),
                str(auth / "auth.json"),
            ]
        ),
    ]
    result = model_process.execute(
        wrapped,
        prompt=b"public",
        env={"PATH": os.environ["PATH"]},
        cwd=work,
        timeout=10,
    )
    assert result.process_stopped and result.error_code is None
    assert json.loads(result.stdout) == {
        "blocked": [True, True],
        "auth": "PUBLIC_NOT_AN_AUTH_CREDENTIAL",
        "same_session": True,
    }
    assert (auth / "AGENTS.md").read_text() == "PUBLIC_INSTRUCTION_SENTINEL"


def test_preflight_never_reads_instruction_or_auth_bytes(tmp_path, monkeypatch):
    home, auth, work, backend = layout(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("global bytes read")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name="Darwin",
        executable=backend,
        system_roots=(),
    )


@pytest.mark.parametrize("field", ["home", "codex_home"])
def test_resolved_root_alias_rejected(tmp_path, field):
    home, auth, work, backend = layout(tmp_path)
    alias = tmp_path / "root-alias"
    alias.symlink_to("/", target_is_directory=True)
    kwargs = dict(work=work, home=home, codex_home=auth)
    kwargs[field] = alias
    with pytest.raises(ValueError, match="codex_isolation_path_invalid"):
        module().prepare(
            **kwargs, platform_name="Darwin", executable=backend, system_roots=()
        )


@pytest.mark.parametrize(
    "damage", ["extra", "not_empty", "wide", "symlink", "hardlink", "populated_dir"]
)
def test_linux_mask_recovery_rejects_damaged_scaffolding(tmp_path, damage):
    guard, home, auth, work, backend = prepare(tmp_path, platform_name="Linux")
    file = work / "isolation" / "empty.txt"
    if damage == "extra":
        (file.parent / "extra").write_text("not allowed")
    elif damage == "not_empty":
        file.write_text("PUBLIC_BAD_INSTRUCTION")
    elif damage == "wide":
        file.chmod(0o644)
    elif damage == "symlink":
        file.unlink()
        file.symlink_to(auth / "AGENTS.md")
    elif damage == "hardlink":
        os.link(file, work / "other")
    else:
        (file.parent / "empty" / "SKILL.md").write_text("PUBLIC_BAD_SKILL")
    with pytest.raises(ValueError, match="codex_isolation"):
        module().prepare(
            work=work,
            home=home,
            codex_home=auth,
            platform_name="Linux",
            executable=backend,
            system_roots=(),
        )


def test_mask_reuse_is_exact_and_does_not_modify_global_files(tmp_path):
    guard, home, auth, work, backend = prepare(tmp_path, platform_name="Linux")
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
        for p in auth.rglob("*")
        if p.is_file()
    }
    again = module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name="Linux",
        executable=backend,
        system_roots=(),
    )
    assert again == guard
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in before
    }


@pytest.mark.parametrize("position", [1, 2, 3, 4, 5])
def test_finite_fsync_failure_does_not_return_a_launcher(
    tmp_path, monkeypatch, position
):
    home, auth, work, backend = layout(tmp_path)
    real = os.fsync
    calls = []

    def fail(fd):
        calls.append(fd)
        if len(calls) == position:
            raise OSError("synthetic fsync")
        real(fd)

    # Use the underlying Linux config path; no Linux process or provider starts.
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        try:
            module().prepare(
                work=work,
                home=home,
                codex_home=auth,
                platform_name="Linux",
                executable=backend,
                system_roots=(),
            )
        except ValueError as exc:
            assert str(exc) == "codex_isolation_unavailable"
        else:
            assert len(calls) < position
    recovered = module().prepare(
        work=work,
        home=home,
        codex_home=auth,
        platform_name="Linux",
        executable=backend,
        system_roots=(),
    )
    assert recovered.platform_name == "Linux"
    assert (auth / "AGENTS.md").read_text() == "PUBLIC_INSTRUCTION_SENTINEL"


@pytest.mark.parametrize(
    "argv", [[], "string", ["relative"], ["/bin/echo", "bad\0arg"], [42]]
)
def test_only_explicit_host_argv_is_accepted(tmp_path, argv):
    guard, home, auth, work, backend = prepare(tmp_path)
    with pytest.raises(ValueError, match="codex_isolation_command_invalid"):
        guard.command(argv)


@pytest.mark.parametrize("kind", ["file_skill", "dir_instruction", "loop"])
def test_unexpected_discovery_types_stop(tmp_path, kind):
    home, auth, work, backend = layout(tmp_path)
    other = tmp_path / "system-skills"
    if kind == "file_skill":
        other.write_text("not a directory")
    elif kind == "dir_instruction":
        other.mkdir()
        (work / "AGENTS.md").mkdir()
    else:
        other.symlink_to(other)
    with pytest.raises(ValueError, match="codex_isolation"):
        module().prepare(
            work=work,
            home=home,
            codex_home=auth,
            platform_name="Darwin",
            executable=backend,
            system_roots=(other,),
        )


def test_all_sources_in_custom_auth_location_are_blocked(tmp_path):
    home, auth, work, backend = layout(tmp_path)
    custom = tmp_path / "custom-auth"
    custom.mkdir()
    guard = module().prepare(
        work=work,
        home=home,
        codex_home=custom,
        platform_name="Darwin",
        executable=backend,
        system_roots=(),
    )
    for base in (auth, custom):
        for name in (
            "skills",
            "plugins",
            "memories",
            "AGENTS.md",
            "AGENTS.override.md",
        ):
            assert base / name in guard.blocked
    guard.validate_environment({"HOME": str(home), "CODEX_HOME": str(custom)})
