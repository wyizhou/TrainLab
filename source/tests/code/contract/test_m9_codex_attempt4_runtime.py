from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts import canary_evidence

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolated_canary_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(canary_evidence, "PUBLIC_ROOT_PARENT", tmp_path)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _helpers() -> Any:
    return _load(
        Path(__file__).with_name("test_m9_codex_daily_runner.py"),
        "m9_attempt4_legacy_helpers",
    )


def _runtime() -> Any:
    return _load(
        ROOT / "skills/training-coach/scripts/codex_attempt_runtime.py",
        "m9_attempt4_runtime",
    )


def _canary() -> Any:
    return _load(
        ROOT / "skills/training-coach/scripts/run_schema_canary.py",
        "m9_schema_canary",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failed_attempt3(tmp_path: Path) -> tuple[Any, Any, Path, Path, Path]:
    helpers = _helpers()
    runtime = _runtime()
    run_root, context, prompt = helpers._inputs(tmp_path)
    failing = helpers._fake_codex(
        tmp_path,
        events=[
            {
                "type": "error",
                "error": {
                    "code": "invalid_json_schema",
                    "message": "Invalid schema",
                    "status": 400,
                },
            }
        ],
        returncode=1,
    )
    receipt = runtime.run_codex_daily(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_PATH),
        codex_executable=failing,
        environment_check=lambda: "0" * 64,
    )
    assert receipt["status"] == "failed"
    return helpers, runtime, run_root, context, prompt


def test_public_canary_then_attempt4_succeeds_and_replays_without_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    historical = {
        path: path.read_bytes()
        for directory in (run_root / "ai-attempt-2", run_root / "ai-attempt-3")
        for path in directory.iterdir()
    }
    wire_v1 = runtime.SCHEMA_PATH.read_bytes()
    canary = _canary()
    canary_root = tmp_path / "trainlab-m9-schema-canary-r07.test"
    canary_root.mkdir(mode=0o700)
    canary_fake = helpers._fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result=helpers._daily_payload(),
    )
    canary_receipt = canary.run_schema_canary(
        root=canary_root,
        codex_executable=canary_fake,
        version_reader=lambda _path: "codex-cli synthetic",
    )
    assert canary_receipt["status"] == "succeeded"
    assert "candidate" not in canary.PUBLIC_PROMPT.decode().lower()
    canary_receipt_path = canary_root / "schema-canary-v2/canary-receipt.json"

    attempt4_fake = canary_fake
    first = runtime.run_codex_daily_v4(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
        codex_executable=attempt4_fake,
        canary_receipt_path=canary_receipt_path,
        environment_check=lambda: "0" * 64,
    )
    assert first["status"] == "succeeded"
    assert first["attempt"] == 4
    assert (run_root / "ai-attempt-4/ai-result.json").is_file()
    assert not (run_root / "ai-attempt-4.pending").exists()
    assert not (run_root / "ai-attempt-5").exists()
    assert runtime.SCHEMA_PATH.read_bytes() == wire_v1
    assert all(path.read_bytes() == raw for path, raw in historical.items())

    monkeypatch.setattr(
        runtime,
        "_run_process",
        lambda *_args, **_kwargs: pytest.fail("replay started Codex"),
    )
    replay = runtime.run_codex_daily_v4(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
        codex_executable=attempt4_fake,
        canary_receipt_path=canary_receipt_path,
        environment_check=lambda: "0" * 64,
    )
    assert replay == first


def test_failed_canary_prevents_attempt4(tmp_path: Path) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    canary = _canary()
    canary_root = tmp_path / "trainlab-m9-schema-canary-r07.test"
    canary_root.mkdir(mode=0o700)
    failing = helpers._fake_codex(
        tmp_path,
        events=[{"type": "error", "message": "synthetic failure"}],
        returncode=1,
    )
    receipt = canary.run_schema_canary(
        root=canary_root,
        codex_executable=failing,
        version_reader=lambda _path: "codex-cli synthetic",
    )
    assert receipt["status"] == "failed"
    with pytest.raises(runtime.RunnerBlocked, match="schema_canary_invalid"):
        runtime.run_codex_daily_v4(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
            codex_executable=failing,
            canary_receipt_path=(canary_root / "schema-canary-v2/canary-receipt.json"),
            environment_check=lambda: "0" * 64,
        )
    assert not (run_root / "ai-attempt-4.pending").exists()
    assert not (run_root / "ai-attempt-4").exists()


def test_wire_linter_blocks_before_canary_pending_or_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    invalid = tmp_path / "wire-v2-invalid.json"
    schema = json.loads(runtime.SCHEMA_V2_PATH.read_text())
    del schema["properties"]["schema_version"]["type"]
    invalid.write_text(json.dumps(schema, sort_keys=True) + "\n")
    invalid.chmod(0o600)
    monkeypatch.setattr(
        runtime,
        "ATTEMPT4_POLICY",
        runtime.ATTEMPT4_POLICY._replace(wire_schema_path=invalid),
    )
    monkeypatch.setattr(
        runtime,
        "_run_process",
        lambda *_args, **_kwargs: pytest.fail("invalid wire started Codex"),
    )
    fake = helpers._fake_codex(tmp_path, result=helpers._daily_payload())
    with pytest.raises(runtime.RunnerBlocked, match="frozen_schema_invalid"):
        runtime.run_codex_daily_v4(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(invalid),
            codex_executable=fake,
            canary_receipt_path=tmp_path / "missing-canary.json",
            environment_check=lambda: "0" * 64,
        )
    assert not (run_root / "ai-attempt-4.pending").exists()


def test_pending_unknown_attempt_and_attempt5_block_before_codex(
    tmp_path: Path,
) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    fake = helpers._fake_codex(tmp_path, result=helpers._daily_payload())
    pending = run_root / "ai-attempt-4.pending"
    pending.mkdir(mode=0o700)
    with pytest.raises(runtime.RunnerBlocked, match="ai_attempt_incomplete"):
        runtime.run_codex_daily_v4(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
            codex_executable=fake,
            canary_receipt_path=tmp_path / "missing-canary.json",
            environment_check=lambda: "0" * 64,
        )
    pending.rmdir()
    attempt5 = run_root / "ai-attempt-5"
    attempt5.mkdir(mode=0o700)
    with pytest.raises(runtime.RunnerBlocked, match="ai_attempt_history_invalid"):
        runtime.run_codex_daily_v4(
            run_root=run_root,
            expected_context_sha256=_sha(context),
            expected_prompt_sha256=_sha(prompt),
            expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
            codex_executable=fake,
            canary_receipt_path=tmp_path / "missing-canary.json",
            environment_check=lambda: "0" * 64,
        )


def test_failed_attempt4_is_terminal_and_cannot_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    canary = _canary()
    canary_root = tmp_path / "trainlab-m9-schema-canary-r07.test"
    canary_root.mkdir(mode=0o700)
    fake = helpers._fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result=helpers._daily_payload(),
    )
    canary.run_schema_canary(
        root=canary_root,
        codex_executable=fake,
        version_reader=lambda _path: "codex-cli synthetic",
    )
    receipt_path = canary_root / "schema-canary-v2/canary-receipt.json"
    failing = helpers._fake_codex(
        tmp_path,
        events=[{"type": "error", "message": "synthetic model failure"}],
        returncode=1,
    )
    # The same executable identity is part of the authorization. Preserve that
    # identity while changing only the fake process outcome for this test.
    failing.write_bytes(
        fake.read_bytes().replace(b"raise SystemExit(0)", b"raise SystemExit(1)")
    )
    failing.chmod(0o700)
    canary_receipt = json.loads(receipt_path.read_text())
    canary_receipt["codex_executable_sha256"] = _sha(failing)
    receipt_path.write_text(json.dumps(canary_receipt, sort_keys=True, indent=2) + "\n")
    receipt_path.chmod(0o600)
    first = runtime.run_codex_daily_v4(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
        codex_executable=failing,
        canary_receipt_path=receipt_path,
        environment_check=lambda: "0" * 64,
    )
    assert first["status"] == "failed"
    monkeypatch.setattr(
        runtime,
        "_run_process",
        lambda *_args, **_kwargs: pytest.fail("failed attempt 4 retried Codex"),
    )
    replay = runtime.run_codex_daily_v4(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
        codex_executable=failing,
        canary_receipt_path=receipt_path,
        environment_check=lambda: "0" * 64,
    )
    assert replay == first


def test_attempt4_intent_binds_attempt3_canary_and_v2_schema(tmp_path: Path) -> None:
    helpers, runtime, run_root, context, prompt = _failed_attempt3(tmp_path)
    canary = _canary()
    canary_root = tmp_path / "trainlab-m9-schema-canary-r07.test"
    canary_root.mkdir(mode=0o700)
    fake = helpers._fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result=helpers._daily_payload(),
    )
    canary.run_schema_canary(
        root=canary_root,
        codex_executable=fake,
        version_reader=lambda _path: "codex-cli synthetic",
    )
    receipt_path = canary_root / "schema-canary-v2/canary-receipt.json"
    runtime.run_codex_daily_v4(
        run_root=run_root,
        expected_context_sha256=_sha(context),
        expected_prompt_sha256=_sha(prompt),
        expected_schema_sha256=_sha(runtime.SCHEMA_V2_PATH),
        codex_executable=fake,
        canary_receipt_path=receipt_path,
        environment_check=lambda: "0" * 64,
    )
    intent = json.loads((run_root / "ai-attempt-4/attempt-intent.json").read_text())
    assert intent["attempt"] == 4
    assert intent["wire_schema_sha256"] == _sha(runtime.SCHEMA_V2_PATH)
    assert intent["canary_receipt_sha256"] == _sha(receipt_path)
    assert intent["prior_attempt_receipt_sha256"] == _sha(
        run_root / "ai-attempt-3/attempt-receipt.json"
    )
    assert intent["provider_calls"] == 0
    assert intent["external_actions"] == 0


def test_canary_cli_accepts_no_candidate_or_private_input() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/training-coach/scripts/run_schema_canary.py"),
            "--help",
        ],
        cwd=ROOT.parent,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    help_text = result.stdout.lower()
    assert "--root" in help_text
    for forbidden in (
        "candidate",
        "--prompt",
        "--context",
        "--goal",
        "--token",
        "--date",
        "--mode",
        "--request-id",
    ):
        assert forbidden not in help_text


def test_canary_root_rejects_candidate_state_and_untrusted_entries(
    tmp_path: Path,
) -> None:
    canary = _canary()
    candidate = tmp_path / "trainlab-m9-candidate-synthetic"
    candidate.mkdir(mode=0o700)
    state = candidate / "source/state"
    state.mkdir(parents=True, mode=0o700)
    database = state / "trainlab.db"
    database.write_bytes(b"synthetic")
    database.chmod(0o600)
    nested = candidate / "trainlab-m9-schema-canary-r07.nested"
    nested.mkdir(mode=0o700)

    for path in (candidate, state, nested):
        with pytest.raises(canary.CanaryBlocked, match="schema_canary_root_invalid"):
            canary._require_root(path)

    for name in ("state", "tokens", "private-context"):
        nested_private = tmp_path / name / "trainlab-m9-schema-canary-r07.nested"
        nested_private.mkdir(parents=True, mode=0o700)
        with pytest.raises(canary.CanaryBlocked, match="schema_canary_root_invalid"):
            canary._require_root(nested_private)

    public = tmp_path / "trainlab-m9-schema-canary-r07.untrusted"
    public.mkdir(mode=0o700)
    extra = public / "private-context.json"
    extra.write_text("{}\n")
    extra.chmod(0o600)
    with pytest.raises(canary.CanaryBlocked, match="schema_canary_root_invalid"):
        canary._require_root(public)


def test_canary_consumer_rejects_bundle_copied_into_candidate(
    tmp_path: Path,
) -> None:
    helpers = _helpers()
    runtime = _runtime()
    canary = _canary()
    public = tmp_path / "trainlab-m9-schema-canary-r07.consumer"
    public.mkdir(mode=0o700)
    fake = helpers._fake_codex(
        tmp_path,
        events=[{"type": "turn.completed"}],
        result=helpers._daily_payload(),
    )
    canary.run_schema_canary(
        root=public,
        codex_executable=fake,
        version_reader=lambda _path: "codex-cli synthetic",
    )

    candidate = tmp_path / "trainlab-m9-candidate-synthetic"
    candidate.mkdir(mode=0o700)
    copied = candidate / "schema-canary-v2"
    shutil.copytree(public / "schema-canary-v2", copied)
    with pytest.raises(runtime.RunnerBlocked, match="schema_canary_invalid"):
        runtime._read_canary_receipt(
            copied / "canary-receipt.json", runtime.SCHEMA_V2_PATH.read_bytes()
        )
