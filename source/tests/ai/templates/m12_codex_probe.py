"""Explicit macOS PUBLIC CLI diagnostic, never a normal runtime dependency.

Uses synthetic FIT, a localhost fake Responses server and an OS network/private
file guard. It makes two local CLI invocations (probe and adapter), no real model
or business Provider calls. Auth files are denied, never copied or opened here.
Linux launch code is tested separately; this diagnostic does not claim Linux QA.
"""

from __future__ import annotations

import argparse
import http.server
import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SOURCE), str(SOURCE / "tests/code/contract")]


def run(root: Path, model: str, model_stage: str = "plan") -> dict[str, Any]:
    from skills._shared.fit_weekly import (
        codex_adapter,
        codex_boundary,
        codex_capability,
        codex_isolation,
        codex_output,
        codex_runtime,
        detail_transport,
        fit_detail,
        fit_sync,
        model_job,
        model_process,
        process_capture,
        storage,
    )

    if platform.system() != "Darwin":
        raise ValueError("public_probe_platform_unavailable")
    storage.private_entry(root, directory=True)
    fixture = importlib.import_module("test_m12_fit_detail")
    instance, end, members = fixture.instance(root)
    scope = fit_detail.freeze_scope(instance, end, members)["scope_sha256"]
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("public_probe_cli_unavailable")
    runtime = codex_runtime.Runtime(
        Path(executable).resolve(),
        SOURCE,
        model,
        "file",
        "Public Host instructions.",
        "Public weekly input:\n",
        stage=model_stage,
    )
    identity = runtime.identity()
    home = Path(os.environ["HOME"])
    auth = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    marker = auth / "installation_id"
    marker_before = storage.digest(marker.read_bytes())
    work = root / "probe-work"
    fit_sync.private_directory(work)
    for name in ("job", "tmp", "logs", "sqlite"):
        fit_sync.private_directory(work / name)
    storage.atomic_file(work / "instructions.txt", runtime.instructions.encode())
    storage.atomic_file(
        work / "response.schema.json",
        storage.canonical(codex_capability.SCHEMA).encode(),
    )
    requests = [
        fixture.request(end_offset_seconds=1200, resolution_seconds=r)
        for r in (1, 1, 5, 5)
    ]
    calls = [
        *(("read_fit_detail", "mcp__fit", r) for r in requests),
        ("exec_command", None, {"cmd": "touch escaped-command"}),
        (
            "read_mcp_resource",
            None,
            {"server": "fit", "uri": "file:///public-sentinel"},
        ),
        (
            "read_mcp_resource",
            None,
            {"server": "unconfigured", "uri": "file:///public-sentinel"},
        ),
        ("get_activities_by_date", "mcp__garmin", {"start_date": "2026-09-01"}),
    ]
    observed: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    errors: list[str] = []
    stage: dict[str, Any] = {"prompt": codex_capability.PROMPT, "cwd": work / "job"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if (
                    self.path != "/v1/responses"
                    or self.headers.get("Authorization")
                    or not 0 < size <= 4_000_000
                ):
                    raise ValueError("public_probe_request_invalid")
                raw = self.rfile.read(size)
                body = codex_output.strict_json(raw.decode())
                index = len(observed) % 9
                if index == 0:
                    codex_boundary.audit_initial_request(
                        body,
                        instructions=runtime.instructions,
                        prompt=stage["prompt"],
                        cwd=stage["cwd"],
                        model=model,
                        response_schema=codex_capability.SCHEMA,
                    )
                if 1 <= index <= 4:
                    output = [
                        x["output"]
                        for x in body["input"]
                        if x.get("type") == "function_call_output"
                        and x.get("call_id") == f"call_{index - 1}"
                    ]
                    if len(output) != 1:
                        raise ValueError("public_probe_detail_missing")
                    host = fit_detail.DetailHost(instance, end, scope)
                    value = host.read(requests[index - 1])
                    detail_transport.audit_model_output(output[0], value)
                    handoffs.append(
                        {
                            "request": requests[index - 1],
                            "host_result": value,
                            "model_output": output[0],
                            "charged_requests": host.usage()["requests"],
                        }
                    )
                storage.atomic_file(root / f"request-{len(observed)}.json", raw)
                observed.append(body)
                output_item = {
                    "id": "msg_public",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"ok":true}',
                            "annotations": [],
                        }
                    ],
                }
                if index < 8:
                    name, namespace, arguments = calls[index]
                    output_item = {
                        "id": f"fc_{index}",
                        "type": "function_call",
                        "status": "completed",
                        "call_id": f"call_{index}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                    }
                    if namespace is not None:
                        output_item["namespace"] = namespace
                events = [
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": output_item,
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_public",
                            "object": "response",
                            "created_at": 1,
                            "model": model,
                            "status": "completed",
                            "output": [output_item],
                            "usage": {
                                "input_tokens": 1,
                                "output_tokens": 1,
                                "total_tokens": 2,
                            },
                        },
                    },
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()
            except Exception:
                errors.append("public_probe_server_failed")
                self.send_error(400)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    original_command, original_prepare = (
        codex_runtime.Runtime.command,
        codex_isolation.prepare,
    )

    def command(self, *args):
        argv = original_command(self, *args)
        config = {
            "model_provider": "fit_offline",
            "model_providers.fit_offline.name": "Public offline probe",
            "model_providers.fit_offline.base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model_providers.fit_offline.wire_api": "responses",
            "model_providers.fit_offline.requires_openai_auth": False,
            "model_providers.fit_offline.request_max_retries": 0,
            "model_providers.fit_offline.stream_max_retries": 0,
            "model_providers.fit_offline.supports_websockets": False,
        }
        return [
            *argv[:-1],
            *(
                part
                for k, v in config.items()
                for part in ("-c", k + "=" + storage.canonical(v))
            ),
            "-",
        ]

    def isolation(**kwargs):
        from dataclasses import replace

        value = original_prepare(**kwargs)
        policy = value.prefix[2] + "(deny network*)(deny file-write*)"
        policy += "(allow network* (local unix-socket) (remote unix-socket))"
        policy += (
            f'(allow network-outbound (remote ip "localhost:{server.server_port}"))'
        )
        policy += f'(allow file-write* (subpath {json.dumps(str(root))}) (literal "/dev/null"))'
        policy += f"(allow file-write* (literal {json.dumps(str(marker))}) (subpath {json.dumps(str(auth / 'tmp/arg0'))}))"
        protected = [SOURCE / "state", home / "Library/Keychains", auth / "auth.json"]
        protected += [
            SOURCE / name
            for name in (
                "goal.md",
                "email.json",
                "credentials.json",
                "gmail-api-token.json",
                "gcp-oauth.keys.json",
            )
        ]
        for path in protected:
            policy += f"(deny file-read* (subpath {json.dumps(str(path))}))"
        return replace(value, prefix=(value.prefix[0], "-p", policy))

    server_thread.start()
    codex_runtime.Runtime.command, codex_isolation.prepare = command, isolation
    try:
        guard = isolation(work=work / "job", home=home, codex_home=auth)
        env = codex_runtime.environment(work)
        guard.validate_environment(env)
        prompt = codex_capability.PROMPT.encode()
        process = process_capture.run(
            work / "process",
            codex_capability.binding(identity),
            lambda: model_process.execute(
                guard.command(runtime.command(instance, end, scope, work)),
                prompt=prompt,
                env=env,
                cwd=work / "job",
                timeout=60,
            ),
        )
        startup = [
            f"Failed to read global AGENTS.md instructions from `{auth / 'AGENTS.md'}`: Operation not permitted (os error 1)",
            f"Model metadata for `{model}` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.",
        ]
        if errors or len(observed) != 9 or len(handoffs) != 4:
            raise ValueError("public_probe_incomplete")
        refusals = {}
        for i, name in enumerate(codex_capability.REFUSALS):
            outputs = [
                x["output"]
                for x in observed[i + 5]["input"]
                if x.get("type") == "function_call_output"
                and x.get("call_id") == f"call_{i + 4}"
            ]
            if len(outputs) != 1:
                raise ValueError("public_probe_refusal_missing")
            refusals[name] = outputs[0]
        proof = {
            "schema_version": "fit_codex_capability_v1",
            "runtime": identity,
            "cwd": str(work / "job"),
            "initial_request": observed[0],
            "process": process_capture.encode(
                process, codex_capability.binding(identity)
            ),
            "startup_messages": startup,
            "handoffs": handoffs[:4],
            "refusals": refusals,
            "requests": observed[:9],
        }
        codex_capability.validate(proof, identity, runtime.instructions)
        path = root / "capability.json"
        storage.atomic_file(path, storage.canonical(proof).encode())

        def valid_input(value):
            if value != {"public": True}:
                raise ValueError("public_input_invalid")

        def valid_result(value, payload):
            valid_input(payload)
            if value != {"ok": True}:
                raise ValueError("public_result_invalid")

        args = (instance, end, scope, {"public": True}, codex_capability.SCHEMA)
        if model_stage == "summary":
            # Public synthetic prerequisite, never a production fallback.
            model_job.run(*args, model_job.FakeAdapter({"ok": True}, []), stage="plan", validate_input=valid_input, validate_result=valid_result)
        adapter = codex_adapter.prepare(
            *args,
            runtime=runtime,
            capability_path=path,
            stage=model_stage,
            validate_input=valid_input,
            validate_result=valid_result,
        )
        stage.update(
            prompt='Public weekly input:\n{"public":true}', cwd=adapter.work / "job"
        )
        result = model_job.run(
            *args, adapter, stage=model_stage, validate_input=valid_input, validate_result=valid_result
        )
        if errors or result["status"] != "succeeded" or len(observed) != 18:
            raise ValueError("public_adapter_incomplete")
        before = (instance / "trainlab-fit.db").read_bytes()
        recovered = codex_adapter.recover(
            *args, stage=model_stage, validate_input=valid_input, validate_result=valid_result
        )
        if (
            recovered["status"] != "succeeded"
            or recovered["invocation_adapter_calls"]
            or len(observed) != 18
            or before != (instance / "trainlab-fit.db").read_bytes()
        ):
            raise ValueError("public_adapter_replay_invalid")
        if storage.digest(marker.read_bytes()) != marker_before or list(
            root.rglob("escaped-command")
        ):
            raise ValueError("public_probe_boundary_invalid")
        receipt = {
            "status": "checked",
            "real_model_calls": 0,
            "business_provider_calls": 0,
            "local_cli_invocations": 2,
            "local_http_requests": 18,
            "replay_invocations": 0,
            "capability_sha256": storage.digest(path.read_bytes()),
            "model_result": result["receipt"],
            "installation_marker_unchanged": True,
        }
        storage.atomic_file(root / "receipt.json", storage.canonical(receipt).encode())
        return receipt
    finally:
        codex_runtime.Runtime.command, codex_isolation.prepare = (
            original_command,
            original_prepare,
        )
        server.shutdown()
        server.server_close()
        server_thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--stage", choices=("plan", "summary"), default="plan")
    options = parser.parse_args()
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="trainlab-m12-public-adapter-")).resolve()
    try:
        result = run(directory, options.model, options.stage)
        print(json.dumps({"private_evidence_root": str(directory), **result}))
    except Exception:
        print(
            json.dumps(
                {"status": "not_completed", "private_evidence_root": str(directory)}
            )
        )
        raise SystemExit(1) from None
