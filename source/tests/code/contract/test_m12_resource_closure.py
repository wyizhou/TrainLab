"""Current resources form a closed dependency set, not a legacy directory scan."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import codex_runtime, runtime_resources
from skills._shared.scripts import schema_validation

SOURCE = Path(__file__).resolve().parents[3]


def write_schema(root: Path, name: str, body: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.schema.json").write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", **body})
    )


def test_unused_broken_schema_cannot_break_current_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "schemas"
    write_schema(root, "current", {"type": "integer"})
    (root / "old_daily.schema.json").write_text("not JSON")
    monkeypatch.setattr(schema_validation, "schema_root", lambda: root)
    assert schema_validation.validate_payload(7, "current") == []
    assert schema_validation.validate_payload("seven", "current") == ["$:type"]


@pytest.mark.parametrize("reference", ["#/$defs/value", "urn:trainlab:child"])
def test_wire_schema_without_dialect_uses_declared_draft202012(
    tmp_path: Path, reference: str
) -> None:
    # Structured Outputs projections omit $schema. The shared validator is
    # explicitly Draft 2020-12; this must not mutate the frozen wire bytes.
    wire = {"$ref": reference, "$defs": {"value": {"type": "integer"}}}
    path = tmp_path / "wire.schema.json"
    raw = json.dumps(wire).encode()
    path.write_bytes(raw)
    (tmp_path / "child.schema.json").write_text('{"type":"integer"}')
    assert schema_validation.validate_payload(7, "wire", root=tmp_path) == []
    assert schema_validation.validate_payload("seven", "wire", root=tmp_path) == [
        "$:type"
    ]
    assert path.read_bytes() == raw


def test_shared_gmail_schema_uses_same_declared_reference_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = SOURCE / "skills/gmail-sender/scripts/gmail_rest_common.py"
    spec = importlib.util.spec_from_file_location("current_gmail_schema", path)
    assert spec is not None and spec.loader is not None
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    root = tmp_path / "skills/_shared/schemas"
    write_schema(root, "current", {"$ref": "urn:trainlab:child"})
    write_schema(root, "child", {"type": "object", "additionalProperties": False})
    (root / "old_daily.schema.json").write_text("broken legacy")
    monkeypatch.setattr(common, "SOURCE_ROOT", tmp_path)
    common.validate_schema({}, "current")
    with pytest.raises(common.GmailRestError, match="gmail_rest_schema_invalid"):
        common.validate_schema({"unexpected": True}, "current")
    (root / "child.schema.json").unlink()
    with pytest.raises(common.GmailRestError, match="gmail_rest_schema_unavailable"):
        common.validate_schema({}, "current")


def test_transitive_schema_references_are_loaded_without_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_schema(tmp_path, "root", {"$ref": "urn:trainlab:child"})
    write_schema(tmp_path, "child", {"$ref": "urn:trainlab:leaf"})
    write_schema(tmp_path, "leaf", {"type": "integer", "minimum": 2})
    (tmp_path / "unused.schema.json").write_text("broken")
    monkeypatch.setattr(schema_validation, "schema_root", lambda: tmp_path)
    assert schema_validation.validate_payload(3, "root") == []
    assert schema_validation.validate_payload(1, "root") == ["$:minimum"]
    (tmp_path / "leaf.schema.json").unlink()
    with pytest.raises(ValueError, match="schema_dependency_invalid"):
        schema_validation.validate_payload(3, "root")


@pytest.mark.parametrize(
    "reference",
    ["https://example.invalid/x.json", "../secret", "file:///tmp/x", "/etc/passwd"],
)
def test_schema_dependency_never_loads_arbitrary_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    write_schema(tmp_path, "root", {"$ref": reference})
    monkeypatch.setattr(schema_validation, "schema_root", lambda: tmp_path)
    with pytest.raises(ValueError, match="schema_dependency_invalid"):
        schema_validation.validate_payload({}, "root")


def runtime_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    shutil.copytree(
        SOURCE / "skills/_shared/fit_weekly",
        source / "skills/_shared/fit_weekly",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        SOURCE / "skills/_shared/scripts",
        source / "skills/_shared/scripts",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        SOURCE / "skills/_shared/schemas", source / "skills/_shared/schemas"
    )
    shutil.copyfile(SOURCE / "requirements.txt", source / "requirements.txt")
    for name in ("skills/__init__.py", "skills/_shared/__init__.py"):
        shutil.copyfile(SOURCE / name, source / name)
    executable = tmp_path / "public-executable"
    executable.write_bytes(b"public fixture")
    executable.chmod(0o700)
    monkeypatch.setattr(
        codex_runtime,
        "__file__",
        str(source / "skills/_shared/fit_weekly/codex_runtime.py"),
    )
    return codex_runtime.Runtime(
        executable, source, "public-model", "file", "instructions", "prompt"
    )


def test_unrelated_legacy_resources_do_not_change_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = runtime_copy(tmp_path, monkeypatch)
    before = runtime.identity()
    (runtime.source / "skills/_shared/schemas/daily_summary_v1.schema.json").write_text(
        "broken legacy"
    )
    (runtime.source / "skills/_shared/fit_weekly/not_a_dependency.py").write_text(
        "raise RuntimeError('must not load')"
    )
    assert runtime.identity() == before
    (runtime.source / "skills/_shared/schemas/daily_summary_v1.schema.json").unlink()
    assert runtime.identity() == before


@pytest.mark.parametrize("name", ["schema_validation.py", "training_goal_v1.py"])
def test_actual_goal_validation_dependency_changes_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    runtime = runtime_copy(tmp_path, monkeypatch)
    before = runtime.identity()
    path = runtime.source / "skills/_shared/scripts" / name
    path.write_text(path.read_text() + "\n# dependency changed\n")
    assert runtime.identity() != before


def test_missing_actual_schema_prevents_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = runtime_copy(tmp_path, monkeypatch)
    (runtime.source / "skills/_shared/schemas/training_goal_v1.schema.json").unlink()
    with pytest.raises(ValueError, match="codex_runtime_unavailable"):
        runtime.identity()


def test_closed_copy_finishes_context_model_history_and_relocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = importlib.import_module("test_m12_weekly_context")
    instance, _, _ = fixture.setup(
        tmp_path, monkeypatch, parser_version="fit-summary-2"
    )
    source = tmp_path / "closed-source"
    for path in runtime_resources.files(SOURCE):
        target = source / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    assert not (source / "tests").exists()
    assert not (source / "skills/training-coach").exists()
    assert not (source / "skills/_shared/state.py").exists()
    assert not (source / "data-backup").exists()
    # Fixtures prepare real synthetic FIT outside the child. The isolated
    # product process reads no tests, retired modules or archived resources.
    program = """
import json, sys
from pathlib import Path
from skills._shared.fit_weekly import weekly_context, weekly_history, model_job, storage
root, end = Path(sys.argv[1]), sys.argv[2]
def valid_result(body, payload):
    assert body == {"ok": True}
    assert payload["schema_version"] == "fit_weekly_context_v2"
context = weekly_context.freeze(root, end, validate_report=valid_result)
schema = {"type": "object", "required": ["ok"], "additionalProperties": False,
          "properties": {"ok": {"type": "boolean", "const": True}}}
adapter = model_job.FakeAdapter({"ok": True}, [])
def run(root):
    return model_job.run(root, end, context["scope_sha256"], context, schema, adapter,
        validate_input=weekly_context.validator(root, end, validate_report=valid_result),
        validate_result=valid_result)
first = run(root)
assert first["status"] == "succeeded"
history = weekly_history.archive(root, end, validate_report=valid_result)
before = (root / "trainlab-fit.db").read_bytes()
assert run(root)["invocation_adapter_calls"] == 0
assert (root / "trainlab-fit.db").read_bytes() == before
moved = root.with_name("moved-instance")
root.rename(moved)
assert run(moved)["invocation_adapter_calls"] == 0
assert weekly_history.archive(moved, end, validate_report=valid_result) == history
assert (moved / "trainlab-fit.db").read_bytes() == before
assert adapter.calls == 1
assert first["receipt"]["provider_calls"] == first["receipt"]["external_actions"] == 0
with storage.open_store(moved) as db:
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert storage.verify_fit_closure(db, moved) == 2
for name, module in tuple(sys.modules.items()):
    if name.startswith("skills.") and getattr(module, "__file__", None):
        assert Path(module.__file__).is_relative_to(Path.cwd())
print(json.dumps({"activities": len(context["current_week"]["activities"]),
                  "calls": adapter.calls, "replay_calls": 0}))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(instance), fixture.fixture.END],
        cwd=source,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"activities": 2, "calls": 1, "replay_calls": 0}


def test_empty_closed_collection_copy_syncs_all_sports_and_replays_after_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    fixture = importlib.import_module("test_m12_weekly_evidence")
    epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(
        fixture.factory, "BASE", int((fixture.stamp(0) - epoch).total_seconds())
    )
    source = tmp_path / "closed-source"
    for path in runtime_resources.files(SOURCE, collection=True):
        target = source / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    root = tmp_path / "empty-instance"
    assert not root.exists()
    assert not (source / "tests").exists()
    assert not (source / "data-backup").exists()
    assert not (source / "skills/_shared/state.py").exists()
    assert not (source / "skills/_shared/fit_weekly/legacy_import.py").exists()
    # The parent supplies only public synthetic bytes and an in-memory Fake MCP.
    # No prepared database, fixtures directory, archive, or original source path
    # is available to the isolated child.
    prefix = """
import asyncio, json, sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from skills._shared.fit_weekly import fit_sync, garmin_fit, storage, sync_calendar, weekly_evidence, fit_detail
def stamp(offset):
    return datetime.fromisoformat('2026-08-02T07:00:00Z') + timedelta(seconds=offset)
"""
    program = (
        prefix
        + inspect.getsource(fixture.FakeSDK)
        + """
root = Path(sys.argv[1])
storage.initialize(root)
tokens = root.with_name('synthetic-tokens')
tokens.mkdir(mode=0o700)
(tokens / 'synthetic.json').write_text('{"synthetic":true}')
(tokens / 'synthetic.json').chmod(0o600)
garmin_fit.shutil.which = lambda _: '/synthetic/uvx'
sdk = FakeSDK([('101', 3600, bytes.fromhex(sys.argv[2])),
               ('102', 7200, bytes.fromhex(sys.argv[3]))])
spec = fit_sync.SyncSpec(sync_calendar.InventoryRequest('closed:week', '2026-08-02',
    '2026-08-09', '2026-08-09T07:00:10Z', 20, 2), 2, 1, 2, True, 30)
def sync(root):
    return asyncio.run(fit_sync.synchronize(root, spec, token_root=tokens, session_factory=sdk.session))
receipt = sync(root)
assert receipt['fit_count'] == 2 and receipt['provider_calls']['total'] == 4
end = '2026-08-09T07:00:00Z'
evidence = weekly_evidence.freeze(root, end, spec.inventory.key)
assert {s['sport'] for a in evidence['activities'] for s in a['sessions']} == {'running', 'rock_climbing'}
members = [{'activity_ref': a['activity_ref'], 'fit_sha256': a['fit_sha256']} for a in evidence['activities']]
scope = fit_detail.freeze_scope(root, end, members)
request = {'activity_ref':'101', 'view':'series', 'start_offset_seconds':0,
           'end_offset_seconds':60, 'resolution_seconds':5}
detail = fit_detail.DetailHost(root, end, scope['scope_sha256']).read(request)
assert detail['status'] == 'available'
calls = list(sdk.calls)
moved = root.with_name('moved-instance')
root.rename(moved)
before = (moved / 'trainlab-fit.db').read_bytes()
assert sync(moved) == receipt
assert weekly_evidence.freeze(moved, end, spec.inventory.key) == evidence
assert fit_detail.DetailHost(moved, end, scope['scope_sha256']).read(request) == detail
assert sdk.calls == calls and (moved / 'trainlab-fit.db').read_bytes() == before
for name, module in tuple(sys.modules.items()):
    if name.startswith('skills.') and getattr(module, '__file__', None):
        assert Path(module.__file__).is_relative_to(Path.cwd())
print(json.dumps({'activities': 2, 'replay_calls': 0, 'detail': 'available'}))
"""
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(root),
            fixture.data().hex(),
            fixture.data(7200, sport=31).hex(),
        ],
        cwd=source,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "activities": 2,
        "replay_calls": 0,
        "detail": "available",
    }


@pytest.mark.parametrize("relative", runtime_resources.COLLECTION)
def test_missing_collection_resource_fails_without_original_source_fallback(
    tmp_path: Path, relative: str
) -> None:
    source = tmp_path / "closed-source"
    for path in runtime_resources.files(SOURCE, collection=True):
        target = source / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (source / relative).unlink()
    with pytest.raises(ValueError, match="runtime_dependency_missing"):
        runtime_resources.files(source, collection=True)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from pathlib import Path
from skills._shared.fit_weekly import garmin_fit
garmin_fit.shutil.which = lambda _: '/synthetic/uvx'
root = Path('private')
root.mkdir(mode=0o700)
tokens, work = root / 'tokens', root / 'work'
tokens.mkdir(mode=0o700)
work.mkdir(mode=0o700)
(tokens / 'synthetic.json').write_text('{"synthetic":true}')
(tokens / 'synthetic.json').chmod(0o600)
try:
    garmin_fit.launch_spec(tokens, work, is_cn=True)
except (ValueError, OSError):
    pass
else:
    raise AssertionError('missing runtime resource accepted')
""",
        ],
        cwd=source,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
