from __future__ import annotations

import json
import os
import threading
from multiprocessing import active_children
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import trainlab.foundation as foundation
from trainlab.cli import main as cli_main
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


UTC = "2026-07-24T12:34:56Z"


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
    if not root.exists():
        return ()
    return tuple(sorted((str(p.relative_to(root)), p.stat().st_size if p.is_file() else -1, p.stat().st_mtime_ns) for p in [root, *root.rglob("*")]))


def test_fnd01_request_schema_is_exact_and_api_rejects_before_io(tmp_path: Path) -> None:
    schema = json.loads((Path(__file__).parents[1] / "harness/schemas/foundation_request.schema.json").read_text())
    validator = Draft202012Validator(schema)
    valid = {"mode": "init", "invocation_id": "request-1", "requested_at_utc": UTC, "target_schema_version": None}
    assert not list(validator.iter_errors(valid))
    invalid = [
        {**valid, "unknown": True},
        {**valid, "invocation_id": "含中文"},
        {**valid, "invocation_id": "x" * 129},
        {**valid, "requested_at_utc": "2026-07-24"},
        {**valid, "requested_at_utc": "2026-07-24T12:34:56+00:00"},
        {**valid, "requested_at_utc": "2026-07-24T12:34:56.1Z"},
        {**valid, "mode": "migrate", "target_schema_version": None},
        {**valid, "mode": "migrate", "target_schema_version": True},
        {**valid, "target_schema_version": 1},
    ]
    root = tmp_path / "never-created"; tool = FoundationTool(config(root))
    for payload in invalid:
        assert list(validator.iter_errors(payload))
        # JSON-only unknown keys cannot be represented by the fixed dataclass;
        # all other invalid combinations must be rejected by the API too.
        if "unknown" not in payload and payload["mode"] in {"init", "status", "verify", "migrate"}:
            receipt = tool.execute(FoundationRequest(payload["mode"], payload["invocation_id"], payload["requested_at_utc"], payload["target_schema_version"]))
            assert receipt.status == "failed" and receipt.invocation_id in {"", payload["invocation_id"]}
        assert snapshot(root) == ()
    assert tool.execute(object()).status == "failed"  # type: ignore[arg-type]
    assert snapshot(root) == ()


def _write_owner_project(root: Path) -> None:
    (root / "config").mkdir(parents=True, mode=0o700)
    (root / "harness" / "schemas").mkdir(parents=True, mode=0o700)
    (root / "config" / "foundation.yaml").write_text("foundation:\n  data_root: state/foundation\n  database_path: data.db\n  raw_root: raw\n  state_root: state\n  ready_marker: state/foundation-ready.json\n  lock_path: state/locks/foundation.lock\n")
    (root / "harness" / "schemas" / "foundation.schema.json").write_text((Path(__file__).parents[1] / "harness/schemas/foundation.schema.json").read_text())
    for p in (root, root / "config", root / "harness", root / "harness" / "schemas"):
        p.chmod(0o700)
    for p in (root / "config" / "foundation.yaml", root / "harness" / "schemas" / "foundation.schema.json"):
        p.chmod(0o600)


@pytest.mark.parametrize("attack", ["absolute", "escape", "root_alias", "db_raw_overlap", "middle_symlink", "config_symlink", "writable_ancestor"])
def test_fnd01_owner_config_and_path_rejection_has_no_foundation_write(tmp_path: Path, attack: str) -> None:
    project = tmp_path / "project"; _write_owner_project(project)
    yaml_path = project / "config" / "foundation.yaml"
    if attack == "absolute": yaml_path.write_text(yaml_path.read_text().replace("state/foundation", "/tmp/foundation"))
    elif attack == "escape": yaml_path.write_text(yaml_path.read_text().replace("database_path: data.db", "database_path: ../escape.db"))
    elif attack == "root_alias": yaml_path.write_text(yaml_path.read_text().replace("data_root: state/foundation", "data_root: ."))
    elif attack == "db_raw_overlap": yaml_path.write_text(yaml_path.read_text().replace("raw_root: raw", "raw_root: data.db"))
    elif attack == "middle_symlink":
        (project / "state").symlink_to(tmp_path / "outside", target_is_directory=True)
    elif attack == "config_symlink":
        target = project / "config" / "other.yaml"; target.write_text(yaml_path.read_text()); yaml_path.unlink(); yaml_path.symlink_to(target)
    else:
        (project / "config").chmod(0o777)
    before = snapshot(project / "state")
    with pytest.raises(ValueError): FoundationConfig.load(project)
    assert snapshot(project / "state") == before


def test_fnd01_cli_and_api_share_equivalent_receipt_and_no_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "foundation"; owner = config(root); api_owner=config(tmp_path / "api-foundation")
    monkeypatch.setattr(foundation.FoundationConfig, "load", classmethod(lambda cls, _: owner))
    monkeypatch.setattr(foundation, "_utc", lambda: UTC)
    before_threads = {item.ident for item in threading.enumerate()}; before_children = {item.pid for item in active_children()}
    api_receipt = json.loads(FoundationTool(api_owner).execute(FoundationRequest("init", "same-request", UTC)).json())
    assert cli_main(["foundation", "--invocation-id", "same-request", "init"]) == 0
    output = capsys.readouterr(); assert output.err == "" and output.out.count("\n") == 1
    cli_receipt = json.loads(output.out)
    assert cli_receipt == api_receipt
    assert {item.ident for item in threading.enumerate()} == before_threads
    assert {item.pid for item in active_children()} == before_children


def test_fnd01_cli_configuration_failure_is_one_redacted_receipt(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def reject(cls, root):
        raise ValueError("token=must-not-appear")
    monkeypatch.setattr(foundation.FoundationConfig, "load", classmethod(reject))
    assert cli_main(["foundation", "--invocation-id", "config-failure", "status"]) == 20
    output=capsys.readouterr()
    assert output.err == "" and output.out.count("\n") == 1 and "token=" not in output.out
    payload=json.loads(output.out)
    assert payload["status"] == "failed" and payload["errors"] == [{"code":"invalid_configuration","summary":"foundation_configuration_rejected"}]
