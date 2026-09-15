from __future__ import annotations

import importlib
import json
import runpy
import shutil
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from skills._shared.fit_weekly import (
    coaching_contract,
    command_runtime,
    garmin_fit,
    garmin_publication,
    publication_ledger,
    run_authorization,
    run_config,
    storage,
    sync_calendar,
)

END = "2026-08-09T07:00:00Z"
NOW = "2026-08-09T07:00:01Z"
SOURCE = Path(__file__).resolve().parents[3]


class Provider:
    def __init__(self, activities):
        self.inventory = importlib.import_module("test_m12_weekly_evidence").FakeSDK(
            activities
        )
        self.calls = []
        self.starts = []
        self.closed = []
        self.workouts = {}
        self.calendar = []
        self.lost = None
        self.fail_inventory = False
        self.close_failure = False
        self.mode = None

    @asynccontextmanager
    async def factory(self, spec):
        self.mode = "upload_workout" in spec["environment"].get(
            "GARMIN_ENABLED_TOOLS", ""
        )
        self.starts.append(self.mode)
        try:
            yield self
        finally:
            self.closed.append(self.mode)
            if self.close_failure:
                raise OSError("public synthetic close failure")

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name=n)
                for n in (garmin_publication.TOOLS if self.mode else garmin_fit.TOOLS)
            ],
            nextCursor=None,
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name in garmin_fit.TOOLS:
            if self.fail_inventory:
                raise OSError("public synthetic inventory failure")
            result = await self.inventory.call_tool(name, arguments)
            if name == "get_activities_by_date":
                body = json.loads(result.content[0].text)
                for item in body["activities"]:
                    item["name"] = "公开合成运动"
                result.content[0].text = json.dumps(body)
            return result
        fixture = importlib.import_module("m12_publication_factory")
        if name == "upload_workout":
            ident = 100 + len(self.workouts)
            self.workouts[ident] = arguments["workout_data"]
            value = {"status": "success", "workout_id": ident}
        elif name == "get_workout_by_id":
            ident = int(arguments["workout_id"])
            value = fixture.curated(self.workouts[ident], ident)
        elif name == "schedule_workout":
            self.calendar.append(
                {
                    "workout_id": arguments["workout_id"],
                    "date": arguments["calendar_date"],
                    "scheduled_workout_id": 200 + len(self.calendar),
                }
            )
            value = {
                "status": "success",
                "workout_id": arguments["workout_id"],
                "scheduled_date": arguments["calendar_date"],
            }
        else:
            entries = [
                v
                for v in self.calendar
                if arguments["start_date"] <= v["date"] <= arguments["end_date"]
            ]
            value = {
                "count": len(entries),
                "date_range": {
                    "start": arguments["start_date"],
                    "end": arguments["end_date"],
                },
                "scheduled_workouts": entries,
            }
        if name == self.lost:
            raise OSError("public synthetic response lost")
        return SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps(value))],
        )


def setup(tmp_path, monkeypatch, *, fail_stage=None, timeout_stage=None, timeout=30):
    import requests

    sync_fixture = importlib.import_module("test_m12_sync_command")
    entry = importlib.import_module("test_m12_entrypoint")
    proof_fixture = importlib.import_module("test_m12_codex_adapter")
    outputs = importlib.import_module("m12_coaching_factory")
    fit_fixture = importlib.import_module("test_m12_weekly_evidence")
    original_which = shutil.which
    root, _, _, _ = sync_fixture.setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/synthetic/uvx" if name == "uvx" else original_which(name),
    )
    home = tmp_path / "public-home"
    home.mkdir(mode=0o700)
    (home / ".codex").mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: NOW)
    plan = outputs.plan()
    plan["days"][0]["workout"]["steps"][0]["repeat"] = 2
    plan["days"][0]["workout"]["steps"][0]["steps"][0]["value"] = 600
    summary = outputs.summary({"current_week": {"activities": []}})
    executable = tmp_path / "synthetic-model"
    script = f"""#!{sys.executable}
import json,sys,time
prompt=sys.stdin.read()
payload=json.loads(prompt.split("\\nSTAGE_PAYLOAD\\n",1)[1])
stage=payload["stage"]
if stage == {timeout_stage!r}:
    time.sleep(60)
if stage == {fail_stage!r}:
    print(json.dumps({{"type":"turn.failed","error":{{"message":"public synthetic failure"}}}}))
    sys.exit(1)
value=json.loads({json.dumps(plan, ensure_ascii=False)!r}) if stage=="plan" else json.loads({json.dumps(summary, ensure_ascii=False)!r})
if stage=="summary":
    value["other_sports"]=[{{"activity_ref":a["activity_ref"],"session_ordinal":s["session_ordinal"],"explanation":json.loads({json.dumps(outputs.claim(), ensure_ascii=False)!r})}} for a in payload["current_week"]["activities"] for s in a["sessions"] if s["sport"]!="running"]
print(json.dumps(value,ensure_ascii=False),flush=True)
"""
    executable.write_text(script)
    executable.chmod(0o700)
    config_value = json.loads((root / "config.json").read_text())
    config_value["goal"] = "weekly-goal.md"
    config_value["services"]["model"] = "model.json"
    (root / "weekly-goal.md").write_text(
        importlib.import_module("test_m12_weekly_context").goal_text()
    )
    (root / "weekly-goal.md").chmod(0o600)
    stages = {s: {"capability": f"{s}-capability.json"} for s in ("plan", "summary")}
    entry.private_json(root / "config.json", config_value)
    entry.private_json(
        root / "model.json",
        {
            "command": {"adapter": "codex", "executable": str(executable)},
            "instructions": "Only the explicit public FIT tools and supplied stage input are available.",
            "stages": stages,
        },
    )
    actions = [
        *sync_fixture.mail_actions(f"weekly:{END}:gmail"),
        *(
            f"weekly:{END}:{operation}:{date}"
            for date in ("2026-08-10", "2026-08-13", "2026-08-16")
            for operation in ("create", "schedule")
        ),
    ]
    grant_value = {
        "schema_version": "fit_run_authorization_v2",
        "key": "public-week",
        "starts_utc": "2026-08-09T07:00:00Z",
        "expires_utc": "2026-08-20T00:00:00Z",
        "sync": {
            "dates": sync_calendar.days_between(
                sync_calendar.day_value("2026-08-02"),
                sync_calendar.day_value("2026-08-09"),
            ),
            "as_of_utc": NOW,
            "tools": sorted(run_authorization.SYNC_TOOLS),
            "page_size": 20,
            "max_pages": 2,
            "max_activities": 40,
            "max_download_calls": 8,
            "max_session_starts": 2,
            "timeout_seconds": 30,
            "total_timeout_seconds": 300,
        },
        "models": [
            {
                "period_end_utc": END,
                "stage": s,
                "command_sha256": command_runtime.CommandSpec("codex", executable).key,
                "timeout_seconds": timeout,
            }
            for s in stages
        ],
        "publication": {
            "action_keys": actions,
            "start_date": "2026-08-09",
            "end_date": "2026-08-16",
            "max_calls": {k: 30 for k in publication_ledger.TOOLS},
        },
    }
    entry.private_json(root / "authorization.json", grant_value)
    config = run_config.load(root)
    grant = run_authorization.parse(grant_value, now=NOW)
    for stage in stages:
        runtime = command_runtime.Runtime(
            command_runtime.CommandSpec("codex", executable),
            SOURCE,
            "Only the explicit public FIT tools and supplied stage input are available.",
            coaching_contract.prompt(stage),
            stage,
            timeout,
            grant.expires_utc,
            settings=command_runtime.environment_settings("codex"),
        )
        probe = tmp_path / (stage + "-probe")
        probe.mkdir(mode=0o700)
        proof = proof_fixture.complete_probe(proof_fixture.public_proof(runtime), probe)
        storage.atomic_file(
            root / f"{stage}-capability.json", storage.canonical(proof).encode()
        )
    epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(
        fit_fixture.factory,
        "BASE",
        int((datetime.fromisoformat("2026-08-02T07:00:00Z") - epoch).total_seconds()),
    )
    provider = Provider(
        [
            ("101", 3600, fit_fixture.data()),
            ("102", 7200, fit_fixture.data(7200, sport=31)),
        ]
    )
    monkeypatch.setattr(garmin_fit, "sdk_session", provider.factory)
    http = importlib.import_module("m12_publication_factory").Gmail()
    monkeypatch.setattr(requests, "Session", lambda: http)
    return root, config, grant, provider, http


def cli(root, monkeypatch, *arguments):
    monkeypatch.setattr(
        sys, "argv", ["fit_weekly", "--instance", str(root), *arguments]
    )
    try:
        runpy.run_module("skills._shared.fit_weekly", run_name="__main__")
    except SystemExit as exc:
        return exc.code
    raise AssertionError("entrypoint must exit")
