from __future__ import annotations

import importlib
import json
import os
import runpy
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "tests/code/contract"))
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))


def model_wait_code(marker):
    code = (
        "pids = [os.getpid(), "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],"
        "process_group=0).pid]\n"
        f"temporary = {str(marker)!r} + f'.{{os.getpid()}}.tmp'\n"
        "with open(temporary, 'w') as ready:\n"
        "    json.dump(pids, ready)\n"
        f"os.replace(temporary, {str(marker)!r})\n"
        "time.sleep(120)\n"
    )
    return f"exec({code!r})"


def main():
    import requests

    from skills._shared.fit_weekly import (
        garmin_fit,
        publication_ledger,
        schedule_state,
    )

    area, mode = Path(sys.argv[1]), sys.argv[2]
    patch = pytest.MonkeyPatch()
    fixture_root = area / f"fixture-{os.getpid()}"
    fixture_root.mkdir(mode=0o700)
    daily = importlib.import_module("test_m12_daemon")
    if mode in ("weekly", "model", "late"):
        fixture = importlib.import_module("m12_weekly_factory")
        root, _, _, provider, http = fixture.setup(
            fixture_root,
            patch,
            timeout_stage="plan" if mode == "model" else None,
            timeout=120 if mode == "model" else 30,
        )
        if mode == "model":
            executable = fixture_root / "synthetic-model"
            text = executable.read_text()
            text = text.replace(
                "time.sleep(60)",
                model_wait_code(area / "model-pids.json"),
            )
            text = text.replace(
                "import json,sys,time", "import json,sys,time,os,subprocess"
            )
            executable.write_text(text)
            from skills._shared.fit_weekly import (
                coaching_contract,
                command_runtime,
                storage,
            )

            grant_path = root / "authorization.json"
            grant_value = json.loads(grant_path.read_text())
            for permission in grant_value["models"]:
                permission["command_sha256"] = command_runtime.CommandSpec(
                    "codex", executable
                ).key
            grant_path.write_text(json.dumps(grant_value))
            proof_fixture = importlib.import_module("test_m12_codex_adapter")
            for stage in ("plan", "summary"):
                runtime = command_runtime.Runtime(
                    command_runtime.CommandSpec("codex", executable),
                    SOURCE,
                    "Only the explicit public FIT tools and supplied stage input are available.",
                    coaching_contract.prompt(stage),
                    stage,
                    120,
                    "2026-08-20T00:00:00Z",
                    settings=command_runtime.environment_settings("codex"),
                )
                probe = area / (stage + "-new-probe")
                probe.mkdir(mode=0o700)
                proof = proof_fixture.complete_probe(
                    proof_fixture.public_proof(runtime), probe
                )
                path = root / f"{stage}-capability.json"
                path.write_bytes(storage.canonical(proof).encode())
        daily.config(
            root,
            first="2026-07-01" if mode == "late" else "2026-08-01",
            grants={f"weekly:{fixture.END}": "authorization.json"},
        )
        original_factory = provider.factory

        @asynccontextmanager
        async def record_factory(spec):
            async with original_factory(spec) as client:
                try:
                    yield client
                finally:
                    (area / "provider.json").write_text(
                        json.dumps(
                            {
                                "calls": provider.calls,
                                "workouts": provider.workouts,
                                "calendar": provider.calendar,
                            }
                        )
                    )

        patch.setattr(garmin_fit, "sdk_session", record_factory)
    else:
        root, _, _, _ = daily.setup(fixture_root, patch)
        sync_fixture = importlib.import_module("test_m12_sync_command")
        provider, http = sync_fixture.MCP(root), sync_fixture.HTTP()
        original_factory = provider.factory

        @asynccontextmanager
        async def daily_factory(spec):
            async with original_factory(spec) as client:
                try:
                    yield client
                finally:
                    (area / "provider.json").write_text(
                        json.dumps(
                            {
                                "calls": provider.calls,
                                "starts": provider.starts,
                                "closed": provider.closed + 1,
                            }
                        )
                    )

        patch.setattr(garmin_fit, "sdk_session", daily_factory)
    original_request = http.request

    def request(*args, **kwargs):
        try:
            return original_request(*args, **kwargs)
        finally:
            (area / "http.json").write_text(
                json.dumps({"calls": [list(v[:2]) for v in http.calls]})
            )

    patch.setattr(http, "request", request)
    patch.setattr(requests, "Session", lambda: http)
    if mode == "claim":
        original_append = schedule_state.append

        def append(root, event):
            result = original_append(root, event)
            if event["kind"] == "claim":
                (area / "claimed").write_text("ready")
                signal.pause()
            return result

        patch.setattr(schedule_state, "append", append)
    if mode == "provider":
        sdk = importlib.reload(garmin_fit).sdk_session
        patch.setattr(garmin_fit, "sdk_session", sdk)
        server = area / "provider-server.py"
        server.write_text("""import os,sys,json,subprocess,time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],process_group=0)
open(sys.argv[1],'w').write(json.dumps([os.getpid(),child.pid]))
for line in sys.stdin:
    message=json.loads(line)
    method=message.get('method','')
    if 'id' not in message: continue
    if method=='initialize':
        result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'synthetic','version':'1'}}
    elif method=='tools/list':
        result={'tools':[{'name':name,'inputSchema':{'type':'object'}} for name in ['get_activities_by_date','download_activity_file']]}
    else:
        open(sys.argv[1]+'.waiting','w').write('ready')
        time.sleep(120)
        continue
    print(json.dumps({'jsonrpc':'2.0','id':message['id'],'result':result}),flush=True)
""")
        original_spec = garmin_fit.launch_spec

        def launch_spec(*args, **kwargs):
            spec = original_spec(*args, **kwargs)
            spec.update(
                command=sys.executable,
                args=["-I", "-B", str(server), str(area / "provider-pids.json")],
            )
            return spec

        patch.setattr(garmin_fit, "launch_spec", launch_spec)
    if (area / "resume-instance").exists():
        root = Path((area / "resume-instance").read_text())
        if hasattr(provider, "root"):
            provider.root = root
    patch.setattr(
        publication_ledger, "utc_now", lambda: (area / "clock").read_text().strip()
    )
    (area / "ready").write_text(str(root))
    sys.argv = [
        "fit_weekly",
        "--instance",
        str(root),
        "daemon",
        "--schedule",
        "schedule.json",
    ]
    runpy.run_module("skills._shared.fit_weekly", run_name="__main__")


if __name__ == "__main__":
    main()
