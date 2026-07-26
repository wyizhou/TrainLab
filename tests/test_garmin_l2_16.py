from __future__ import annotations

import json
import socket
import threading
from types import SimpleNamespace

import pytest

from trainlab import cli
from trainlab.garmin import GarminConfig, SyncReceipt


def _args(mode: str, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "garmin_mode": mode,
        "garmin_sync_mode": None,
        "health_from": None,
        "through": None,
        "date": None,
        "resource": [],
        "activity_id": [],
        "strategy": None,
        "invocation_id": "l2-16",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _receipt(mode: str = "incremental", status: str = "succeeded") -> SyncReceipt:
    return SyncReceipt(
        mode=mode,
        status=status,
        requested_range={"from": None, "through": None},
        effective_range={"from": None, "through": None},
        completed_at_utc="2026-07-24T00:00:00Z",
    )


def test_garmin_help_has_only_one_shot_command_tree() -> None:
    parser = cli._parser()
    help_text = parser.format_help()
    assert "garmin" in help_text
    garmin = next(item for item in parser._subparsers._group_actions if item.dest == "command").choices["garmin"]
    garmin_help = garmin.format_help()
    for command in ("auth", "sync", "repair", "audit", "status"):
        assert command in garmin_help
    assert "--daemon" not in garmin_help
    assert "--schedule" not in garmin_help
    assert "--watch" not in garmin_help
    assert "--interval" not in garmin_help
    assert parser.parse_args(["garmin", "sync", "full", "--health-from", "2026-01-01"]).garmin_sync_mode == "full"
    assert parser.parse_args(["garmin", "repair", "--resource", "activities", "--strategy", "reparse"]).strategy == "reparse"


@pytest.mark.parametrize(
    "args",
    [
        _args("sync", garmin_sync_mode="full", through="2999-01-01"),
        _args("sync", garmin_sync_mode="snapshot", date="2999-01-02"),
        _args("repair"),
        _args("audit", health_from="2026-07-23", through="not-a-date"),
        _args("repair", resource=["activities", "activities"]),
        _args("repair", resource=["unreviewed_provider_resource"]),
    ],
)
def test_invalid_request_is_rejected_before_provider_or_configuration(monkeypatch: pytest.MonkeyPatch, args: SimpleNamespace) -> None:
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: (_ for _ in ()).throw(AssertionError("configuration")))
    result = cli.garmin_cli_execute(args, transport_factory=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("provider")))
    assert result.status == "failed"
    assert result.errors[0]["code"] == "invalid_request"


@pytest.mark.parametrize("status,code", [("succeeded", 0), ("partial", 10), ("deferred", 11), ("lock_busy", 12), ("auth_required", 20), ("failed", 21)])
def test_every_receipt_status_has_stable_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], status: str, code: int) -> None:
    parsed = SimpleNamespace(command="garmin", garmin_mode="sync", garmin_sync_mode="incremental")
    monkeypatch.setattr(cli, "_parser", lambda: SimpleNamespace(parse_args=lambda _argv: parsed))
    monkeypatch.setattr(cli, "garmin_cli_execute", lambda _args: _receipt(status=status))
    assert cli.main([]) == code
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == status


def test_valid_command_calls_unified_api_once_and_leaves_no_listener(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    foundation = SimpleNamespace(state_root=tmp_path / "state")
    config = GarminConfig(tmp_path / "data.db", tmp_path / "raw", tmp_path / "state", "2026-01-01")
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: foundation)
    monkeypatch.setattr(cli, "load_garmin_config", lambda *_: config)
    calls: list[object] = []

    class Tool:
        def __init__(self, *_args: object) -> None:
            pass

        def execute(self, request: object) -> SyncReceipt:
            calls.append(request)
            return _receipt("incremental")

    before_threads = {thread.ident for thread in threading.enumerate()}
    # The adapter must not leave a network listener or worker behind.  Its
    # provider is an inert fake, so any socket creation is a lifecycle breach.
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("socket")))
    monkeypatch.setattr(cli, "GarminCollectionTool", Tool)
    result = cli.garmin_cli_execute(
        _args("sync", garmin_sync_mode="incremental", through="2026-07-23"),
        transport_factory=lambda *_args, **_kwargs: object(),
    )
    assert result.status == "succeeded"
    assert len(calls) == 1
    assert {thread.ident for thread in threading.enumerate()} == before_threads


def test_status_constructs_no_transport_and_malformed_adapter_args_are_controlled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    foundation = SimpleNamespace(state_root=tmp_path / "state")
    config = GarminConfig(tmp_path / "data.db", tmp_path / "raw", tmp_path / "state", "2026-01-01")
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: foundation)
    monkeypatch.setattr(cli, "load_garmin_config", lambda *_: config)

    class Tool:
        def __init__(self, *_args: object) -> None:
            pass

        def execute(self, request: object) -> SyncReceipt:
            return _receipt("status")

    monkeypatch.setattr(cli, "GarminCollectionTool", Tool)
    status = cli.garmin_cli_execute(_args("status"), transport_factory=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("transport")))
    assert status.status == "succeeded"
    malformed = SimpleNamespace(garmin_mode="sync", garmin_sync_mode="nonsense")
    failed = cli.garmin_cli_execute(malformed)
    assert failed.status == "failed"
    assert failed.errors[0]["code"] == "invalid_request"
