from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import uvicorn
from starlette.types import Message, Receive, Scope, Send

from tests.e2e_support.auth_transport import AuthTransport, ControlledClock
from tests.sync.auth_support import CODE, PASSWORD
from trainlab.garmin_auth import GarminAuthService
from trainlab.local_web.auth_runtime import AuthRuntime
from trainlab.local_web.auth_security import Sessions
from trainlab.local_web.server import WebAppSettings, create_app


async def run(root: Path, offset: float) -> None:
    transport = AuthTransport()
    transport.block_network()
    transport.install()
    clock = ControlledClock()
    clock.offset = offset
    clock.install()
    runtime = AuthRuntime(GarminAuthService(root, clock=clock.now, monotonic=clock.monotonic),
                          clock=clock.now, monotonic=clock.monotonic, sessions=Sessions(clock=clock.monotonic))
    app = create_app(WebAppSettings(instance_root=root, project_root=Path(__file__).parents[3],
                                   auth_runtime_factory=lambda _: runtime))
    status_gate, status_entered = threading.Event(), threading.Event()
    status_gate.set()
    hold_status = False

    async def controlled_app(scope: Scope, receive: Receive, send: Send) -> None:
        async def delayed_send(message: Message) -> None:
            nonlocal hold_status
            if (hold_status and scope.get("path") == "/api/garmin/auth/status"
                    and message["type"] == "http.response.start"):
                hold_status = False
                status_entered.set()
                assert await asyncio.to_thread(status_gate.wait, 20)
            await send(message)
        await app(scope, receive, delayed_send)

    server = uvicorn.Server(uvicorn.Config(controlled_app, host="127.0.0.1", port=8080, access_log=False,
                                           proxy_headers=False, log_level="warning"))
    loop = asyncio.get_running_loop()
    lock_process: subprocess.Popen[str] | None = None

    def control() -> None:
        nonlocal lock_process, hold_status
        for line in sys.stdin:
            command = json.loads(line)
            op = command["op"]
            data: dict[str, Any] = {}
            if op == "configure":
                for key, value in command["values"].items():
                    assert key in {"mfa", "bad_mfa", "failure_path", "failure_status", "mode", "expiry", "delay_path", "save_failure", "timeout_path"}
                    setattr(transport, key, value)
            elif op == "advance":
                clock.offset += command["seconds"]
                loop.call_soon_threadsafe(runtime.wake.set)
            elif op == "hold":
                transport.entered.clear()
                transport.gate.clear()
            elif op == "hold_status":
                status_entered.clear()
                status_gate.clear()
                hold_status = True
            elif op == "release":
                transport.gate.set()
                status_gate.set()
            elif op == "actor":
                result = subprocess.run([sys.executable, "-m", "tests.e2e_support.auth_actor", str(root), command["action"],
                                         "--offset", str(clock.offset)], capture_output=True, text=True, timeout=20, check=False)
                data = {"exit": result.returncode}
            elif op == "lock":
                lock_process = subprocess.Popen([sys.executable, "-m", "tests.e2e_support.auth_actor", str(root), "lock"],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                assert lock_process.stdout is not None
                assert lock_process.stdout.readline().strip() == "locked"
            elif op == "unlock":
                assert lock_process is not None and lock_process.stdin is not None
                lock_process.stdin.write("release\n")
                lock_process.stdin.flush()
                data = {"exit": lock_process.wait(20)}
                lock_process = None
            elif op == "inspect":
                pointer = root / "states/verification/garmin.json"
                data = {"events": transport.events, "exchange_count": transport.exchange_count,
                        "external_attempts": transport.external_attempts, "entered": transport.entered.is_set(),
                        "status_entered": status_entered.is_set(),
                        "pointer": hashlib.sha256(pointer.read_bytes()).hexdigest() if pointer.exists() else None,
                        "offset": clock.offset,
                        "private_input_leaks": sum(any(value.encode() in file.read_bytes() for value in (PASSWORD, CODE))
                                                   for file in root.rglob("*") if file.is_file())}
            elif op == "stop":
                server.should_exit = True
            else:
                raise AssertionError("unknown private IPC command")
            print(json.dumps({"id": command["id"], "data": data}), flush=True)
        server.should_exit = True
    reader = threading.Thread(target=control, daemon=True)
    reader.start()
    try:
        await server.serve()
    finally:
        if lock_process is not None:
            lock_process.communicate("release\n", timeout=10)
        assert transport.external_attempts == 0
        assert not runtime.jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--offset", type=float, default=0)
    args = parser.parse_args()
    asyncio.run(run(args.root, args.offset))


if __name__ == "__main__":
    main()
