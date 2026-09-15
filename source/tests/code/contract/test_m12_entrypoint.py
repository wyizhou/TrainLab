from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import run_authorization, run_config, storage

SOURCE = Path(__file__).resolve().parents[3]

NOW = "2026-09-09T00:00:00Z"
END = "2026-09-13T07:00:00Z"


def private_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def configuration() -> dict:
    return {
        "schema_version": "fit_run_config_v1",
        "goal": "private/goal.json",
        "services": {
            "garmin": "private/garmin.json",
            "gmail": "private/gmail.json",
            "model": "private/model.json",
        },
    }


def authorization() -> dict:
    return {
        "schema_version": "fit_run_authorization_v1",
        "key": "approved-batch-1",
        "starts_utc": "2026-09-08T00:00:00Z",
        "expires_utc": "2026-09-15T00:00:00Z",
        "sync": {
            "dates": ["2026-09-07", "2026-09-09"],
            "as_of_utc": NOW,
            "tools": [
                "garmin.session",
                "get_activities_by_date",
                "download_activity_file",
            ],
            "page_size": 20,
            "max_pages": 4,
            "max_activities": 50,
            "max_download_calls": 50,
            "max_session_starts": 2,
            "timeout_seconds": 30,
            "total_timeout_seconds": 120,
        },
        "models": [
            {
                "period_end_utc": END,
                "stage": stage,
                "model": "test-model",
                "timeout_seconds": 60,
            }
            for stage in ("plan", "summary")
        ],
        "publication": {
            "action_keys": ["weekly:2026-09-13:mail"],
            "start_date": "2026-09-09",
            "end_date": "2026-09-20",
            "max_calls": {"gmail.send": 1, "gmail.get": 1},
        },
    }


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "skills._shared.fit_weekly",
            "--instance",
            str(root),
            *args,
        ],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_private_config_is_lazy_and_relocatable(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    private_json(root / "config.json", configuration())
    config = run_config.load(root)
    assert config.service_path("gmail") == root / "private/gmail.json"
    moved = tmp_path / "moved"
    root.rename(moved)
    config = run_config.load(moved)
    assert config.goal_path == moved / "private/goal.json"
    with pytest.raises(ValueError, match="config_service_unavailable"):
        config.service("gmail")


@pytest.mark.parametrize(
    "case",
    [
        "wide",
        "symlink",
        "hardlink",
        "owner",
        "parent_link",
        "escape",
        "absolute_escape",
        "duplicate",
        "unknown",
        "secret",
        "oversize",
    ],
)
def test_bad_configuration_fails_without_echo_or_service_reads(
    tmp_path: Path, monkeypatch, case: str
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    payload = configuration()
    secret = "PRIVATE-SYNTHETIC-SENTINEL"
    path = private_json(root / "config.json", payload)
    if case == "wide":
        path.chmod(0o644)
    elif case == "symlink":
        path.rename(root / "target")
        path.symlink_to(root / "target")
    elif case == "hardlink":
        os.link(path, root / "link")
    elif case == "owner":
        monkeypatch.setattr(storage.os, "getuid", lambda: -1)
    elif case == "parent_link":
        link = tmp_path / "linked"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif case in ("escape", "absolute_escape"):
        payload["goal"] = (
            "../outside.json" if case == "escape" else "/tmp/../outside.json"
        )
        private_json(path, payload)
    elif case == "duplicate":
        path.write_text(
            '{"schema_version":"fit_run_config_v1","schema_version":"fit_run_config_v1"}'
        )
    elif case == "unknown":
        payload["enabled"] = True
        private_json(path, payload)
    elif case == "secret":
        path.write_text(secret)
    else:
        path.write_bytes(b" " * 131073)
    with pytest.raises(ValueError) as error:
        run_config.load(root)
    assert secret not in str(error.value)


def test_service_paths_checked_only_when_selected(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    private_json(root / "config.json", configuration())
    config = run_config.load(root)
    (root / "private").mkdir(mode=0o700)
    private_json(root / "private/gmail.json", {"token": "token.json"})
    assert config.service("gmail") == {"token": "token.json"}
    (root / "private").chmod(0o755)
    with pytest.raises(ValueError, match="config_service_unavailable"):
        config.service("gmail")


def test_authorization_has_stable_scope_and_existing_contracts() -> None:
    grant = run_authorization.parse(authorization(), now=NOW)
    sync = grant.sync_spec(["2026-09-07"], is_cn=False, now=NOW)
    assert sync.inventory.start_date == sync.inventory.end_date == "2026-09-07"
    assert sync.total_timeout_seconds == 120
    assert (
        sync.inventory.key
        == grant.sync_spec(["2026-09-07"], is_cn=False, now=NOW).inventory.key
    )
    with pytest.raises(ValueError):
        grant.sync_spec(["2026-09-07", "2026-09-09"], is_cn=False, now=NOW)
    with pytest.raises(ValueError):
        grant.sync_spec(["2026-09-08"], is_cn=False, now=NOW)
    assert grant.model(END, "plan", "test-model", now=NOW).timeout_seconds == 60
    for end, stage, model in [
        (END, "plan", "different"),
        ("2026-09-20T07:00:00Z", "plan", "test-model"),
    ]:
        with pytest.raises(ValueError):
            grant.model(end, stage, model, now=NOW)
    pub = grant.publication(now=NOW)
    pub.validate()
    assert pub.key == grant.key
    assert pub.max_calls == {"gmail.send": 1, "gmail.get": 1}
    with pytest.raises(ValueError):
        grant.publication(now="2026-09-16T00:00:00Z")


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "unknown",
        "empty",
        "reversed",
        "expired",
        "future",
        "duplicate_days",
        "unsorted_days",
        "future_day",
        "tool",
        "bool",
        "nan",
        "zero",
        "activities",
        "downloads",
        "model_stage",
        "model_week",
        "model_duplicate",
        "pub_dates",
        "pub_tool",
        "pub_actions",
        "pub_bool",
    ],
)
def test_invalid_authorization_fails_before_adapter_creation(case: str) -> None:
    value = copy.deepcopy(authorization())
    now = NOW
    if case == "missing":
        del value["sync"]["max_activities"]
    elif case == "unknown":
        value["enabled"] = True
    elif case == "empty":
        value.update(sync=None, models=[], publication=None)
    elif case == "reversed":
        value["starts_utc"], value["expires_utc"] = (
            value["expires_utc"],
            value["starts_utc"],
        )
    elif case == "expired":
        now = "2026-09-16T00:00:00Z"
    elif case == "future":
        now = "2026-09-07T00:00:00Z"
    elif case == "duplicate_days":
        value["sync"]["dates"] *= 2
    elif case == "unsorted_days":
        value["sync"]["dates"].reverse()
    elif case == "future_day":
        value["sync"]["dates"] = ["2026-09-10"]
    elif case == "tool":
        value["sync"]["tools"].append("get_health")
    elif case == "bool":
        value["sync"]["max_pages"] = True
    elif case == "nan":
        value["sync"]["timeout_seconds"] = float("nan")
    elif case == "zero":
        value["sync"]["total_timeout_seconds"] = 0
    elif case == "activities":
        value["sync"]["max_activities"] = 81
    elif case == "downloads":
        value["sync"]["max_download_calls"] = -1
    elif case == "model_stage":
        value["models"][0]["stage"] = "daily"
    elif case == "model_week":
        value["models"][0]["period_end_utc"] = NOW
    elif case == "model_duplicate":
        value["models"] *= 2
    elif case == "pub_dates":
        value["publication"]["start_date"] = "2026-09-30"
    elif case == "pub_tool":
        value["publication"]["max_calls"]["gmail.delete"] = 1
    elif case == "pub_actions":
        value["publication"]["action_keys"] *= 2
    else:
        value["publication"]["max_calls"]["gmail.send"] = True
    with pytest.raises(ValueError, match="run_authorization_invalid"):
        run_authorization.parse(value, now=now)


def test_cli_status_is_readonly_and_bad_arguments_do_not_create(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = cli(missing, "status")
    assert result.returncode == 0
    assert json.loads(result.stdout)["instance"] == "uninitialized"
    assert not missing.exists()
    result = cli(missing, "sync", "--unexpected", "PRIVATE-SYNTHETIC-SENTINEL")
    assert result.returncode != 0
    assert "PRIVATE-SYNTHETIC-SENTINEL" not in result.stdout + result.stderr
    assert not missing.exists()


def test_frozen_authorization_cannot_change_or_reset_on_relocation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    grant = run_authorization.parse(authorization(), now=NOW)
    first = grant.freeze(root, now=NOW)
    moved = tmp_path / "moved"
    root.rename(moved)
    assert grant.freeze(moved, now=NOW) == first
    altered = authorization()
    altered["sync"]["max_pages"] += 1
    with pytest.raises(ValueError, match="store_file_conflict"):
        run_authorization.parse(altered, now=NOW).freeze(moved, now=NOW)
    assert grant.freeze(moved, now=NOW) == first
    assert len(list((moved / "authorizations").iterdir())) == 1


def test_authorization_file_uses_the_same_private_boundary(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    path = private_json(root / "authorization.json", authorization())
    assert (
        run_authorization.load(root, "authorization.json", now=NOW).key
        == "approved-batch-1"
    )
    path.chmod(0o644)
    with pytest.raises(ValueError, match="run_authorization_invalid"):
        run_authorization.load(root, "authorization.json", now=NOW)
    path.chmod(0o600)
    path.write_text("PRIVATE-SYNTHETIC-SENTINEL")
    with pytest.raises(ValueError, match="run_authorization_invalid") as error:
        run_authorization.load(root, "authorization.json", now=NOW)
    assert "PRIVATE-SYNTHETIC-SENTINEL" not in str(error.value)


@pytest.mark.parametrize(
    "command,args",
    [
        ("weekly", ["--period-end", END]),
        ("daemon", []),
        ("reconcile", []),
        (
            "edit",
            [
                "--period-end",
                END,
                "--base-id",
                "base",
                "--base-sha",
                "a" * 64,
                "--revision-id",
                "new",
                "--part",
                "summary",
                "--content",
                "edit.json",
            ],
        ),
    ],
)
def test_commands_keep_explicit_implementation_and_material_boundaries(
    tmp_path: Path, command: str, args: list[str]
) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    private_json(root / "config.json", configuration())
    result = cli(root, command, *args)
    if command == "reconcile" and not args:
        assert result.returncode == 0
        assert json.loads(result.stdout) == {
            "status": "complete",
            "mode": "local",
            "weeks": {},
        }
    else:
        assert result.returncode != 0
        assert "command_arguments_or_instance_invalid" in result.stderr
        if command == "daemon":
            assert result.returncode == 2
            assert not (root / "runtime/schedule").exists()
    assert cli(root, "status").returncode == 0
