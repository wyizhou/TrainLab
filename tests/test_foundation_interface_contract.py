from __future__ import annotations

import json
import os
import threading
from multiprocessing import active_children
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import trainlab.foundation as foundation
from trainlab.cli import _parser, main as cli_main
from trainlab.foundation import FOUNDATION_SCHEMA_VERSION, FoundationConfig, FoundationRequest, FoundationTool


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def request(mode: str, target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode, "interface-contract", "2026-07-23T00:00:00Z", target)


def tree_snapshot(root: Path) -> dict[Path, tuple]:
    return {path.relative_to(root): (("directory", path.stat().st_mtime_ns) if path.is_dir() else ("file", path.read_bytes(), path.stat().st_mtime_ns)) for path in [root, *root.rglob("*")]}


def test_ready_init_is_lock_free_strict_noop(tmp_path: Path) -> None:
    root = tmp_path / "foundation"; instance = FoundationTool(config(root))
    assert instance.execute(request("init")).status == "initialized"
    before = tree_snapshot(root)

    def forbidden_lock(_: Path):
        raise AssertionError("ready init must not acquire writer lock")

    instance._lock = forbidden_lock  # type: ignore[method-assign]
    assert instance.execute(request("init")).status == "already_initialized"
    assert tree_snapshot(root) == before


def test_request_schema_conditions_and_api_reject_without_side_effects(tmp_path: Path) -> None:
    schema = json.loads((Path(__file__).resolve().parents[1] / "harness/schemas/foundation_request.schema.json").read_text())
    validator = Draft202012Validator(schema)
    valid_migrate = {"mode": "migrate", "invocation_id": "x", "requested_at_utc": "2026-01-01T00:00:00Z", "target_schema_version": 1}
    valid_init = {**valid_migrate, "mode": "init", "target_schema_version": None}
    assert not list(validator.iter_errors(valid_migrate)) and not list(validator.iter_errors(valid_init))
    assert list(validator.iter_errors({**valid_migrate, "target_schema_version": None}))
    assert list(validator.iter_errors({**valid_init, "target_schema_version": 1}))
    root = tmp_path / "untouched"; instance = FoundationTool(config(root))
    assert instance.execute(request("init", 1)).status == "failed"
    assert not root.exists()
    assert instance.execute(request("migrate")).status == "failed"
    assert not root.exists()


def test_cli_service_integration_isolated_owner_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "owner-root"; owner_config = config(root)
    monkeypatch.setattr(foundation.FoundationConfig, "load", classmethod(lambda cls, _: owner_config))
    schema = Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "harness/schemas/foundation_receipt.schema.json").read_text()))
    before_threads = {thread.ident for thread in threading.enumerate()}
    before_children = {child.pid for child in active_children()}

    def call(arguments: list[str], expected: int) -> dict:
        assert cli_main(arguments) == expected
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out.count("\n") == 1
        payload = json.loads(captured.out)
        assert not list(schema.iter_errors(payload))
        encoded = captured.out.lower()
        assert "access_token" not in encoded and "refresh_token" not in encoded and "raw/" not in encoded
        return payload

    assert call(["foundation", "init"], 0)["status"] == "initialized"
    assert call(["foundation", "status"], 0)["status"] == "ready"
    assert call(["foundation", "verify"], 0)["status"] == "ready"
    assert call(["foundation", "migrate", "--target-version", str(FOUNDATION_SCHEMA_VERSION)], 0)["status"] == "already_initialized"
    before = tree_snapshot(root)
    assert call(["foundation", "migrate", "--target-version", str(FOUNDATION_SCHEMA_VERSION + 1)], 10)["status"] == "incompatible"
    assert tree_snapshot(root) == before
    assert {thread.ident for thread in threading.enumerate()} == before_threads
    assert {child.pid for child in active_children()} == before_children
    for rejected in (["foundation", "--data-root", "/tmp", "init"], ["foundation", "init", "--daemon"]):
        with pytest.raises(SystemExit): _parser().parse_args(rejected)


def test_all_receipt_statuses_validate_schema(tmp_path: Path) -> None:
    root = tmp_path / "foundation"; instance = FoundationTool(config(root))
    schema = Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "harness/schemas/foundation_receipt.schema.json").read_text()))
    busy_root = tmp_path / "busy"; lock = busy_root / "state" / "locks" / "foundation.lock"; lock.parent.mkdir(parents=True); lock.write_text(json.dumps({"pid": os.getpid()})); lock.chmod(0o600)
    receipts = [instance.execute(request("init")), instance.execute(request("init")), instance.execute(request("status")), instance.execute(request("verify")), instance.execute(request("migrate", FOUNDATION_SCHEMA_VERSION + 1)), FoundationTool(config(tmp_path / "bad")).execute(request("migrate")), FoundationTool(config(busy_root)).execute(request("init"))]
    assert {item.status for item in receipts} >= {"initialized", "already_initialized", "ready", "incompatible", "failed", "lock_busy"}
    assert all(not list(schema.iter_errors(json.loads(item.json()))) for item in receipts)
