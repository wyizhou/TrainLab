"""A3-11 isolated, one-shot runner for analysis Codex generations.

This adapter intentionally knows nothing about SQLite, delivery, or CLI output.
It receives a previously verified Harness bundle and canonical context bytes,
creates a private per-invocation directory, and captures exactly one child
process result.  It never logs or returns prompt, context, stderr, or model
output outside the caller-facing byte payload.
"""

from __future__ import annotations

import json
import os
import pwd
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import AnalysisConfig
from .context import ContextBuildError, parse_canonical_context_json
from .harness import HarnessBundle

RUNNER_ADAPTER_VERSION = "a3-11-v1"
_READ_CHUNK_BYTES = 64 * 1024


class AnalysisRunnerError(RuntimeError):
    """A stable, payload-free runner failure.

    ``code`` is suitable for a future run record.  ``str(error)`` contains
    only that code, so accidental exception logging cannot expose context,
    Harness contents, stderr, or process arguments.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AnalysisRunnerResult:
    """Captured model bytes plus non-sensitive execution evidence."""

    output_bytes: bytes
    audit: Mapping[str, Any]


ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _private_mode(path: Path, expected: int, code: str) -> None:
    try:
        if stat.S_IMODE(path.stat().st_mode) != expected:
            raise AnalysisRunnerError(code)
    except OSError as error:
        raise AnalysisRunnerError(code) from error


def _safe_bundle_files(
    config: AnalysisConfig, bundle: HarnessBundle
) -> tuple[tuple[str, bytes], ...]:
    if (
        not isinstance(bundle, HarnessBundle)
        or bundle.route == "delivery"
        or not bundle.files
    ):
        raise AnalysisRunnerError("analysis_runner_harness_invalid")
    root = config.project_root.resolve()
    contents: list[tuple[str, bytes]] = []
    for item in bundle.files:
        candidate = root / item.path_id
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise AnalysisRunnerError("analysis_runner_harness_invalid") from error
        if (
            root not in resolved.parents
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            raise AnalysisRunnerError("analysis_runner_harness_invalid")
        mode = stat.S_IMODE(candidate.stat().st_mode)
        if mode & 0o022:
            raise AnalysisRunnerError("analysis_runner_harness_invalid")
        try:
            payload = candidate.read_bytes()
        except OSError as error:
            raise AnalysisRunnerError("analysis_runner_harness_invalid") from error
        if sha256(payload).hexdigest() != item.sha256:
            raise AnalysisRunnerError("analysis_runner_harness_invalid")
        contents.append((item.path_id, payload))
    return tuple(contents)


def _safe_output_schema(config: AnalysisConfig, bundle: HarnessBundle) -> bytes:
    """Load the already declared output schema without exposing its host path."""

    expected_hash = bundle.schema_evidence.output_schema_sha256
    root = config.project_root.resolve()
    candidate = config.output_schema
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid") from error
    if (
        root not in resolved.parents
        or candidate.is_symlink()
        or not candidate.is_file()
        or stat.S_IMODE(candidate.stat().st_mode) & 0o022
    ):
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid")
    try:
        payload = candidate.read_bytes()
    except OSError as error:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid") from error
    if sha256(payload).hexdigest() != expected_hash:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid")
    return payload


def _codex_compatible_output_schema(payload: bytes) -> bytes:
    """Derive the generation schema without weakening final validation.

    Codex structured output currently rejects ``propertyNames``,
    ``maxProperties`` and ``uniqueItems`` and requires an explicit type
    alongside ``const``.
    The authoritative schema remains byte-for-byte hash checked above and is
    still applied by A3-12 after generation; this derivative only constrains
    the model-side response format.
    """

    try:
        schema = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid") from error

    def adapt(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("propertyNames", None)
            value.pop("maxProperties", None)
            value.pop("uniqueItems", None)
            if "const" in value and "type" not in value:
                constant = value["const"]
                if constant is None:
                    value["type"] = "null"
                elif isinstance(constant, bool):
                    value["type"] = "boolean"
                elif isinstance(constant, int):
                    value["type"] = "integer"
                elif isinstance(constant, float):
                    value["type"] = "number"
                elif isinstance(constant, str):
                    value["type"] = "string"
                else:
                    raise AnalysisRunnerError("analysis_runner_output_schema_invalid")
            for child in value.values():
                adapt(child)
        elif isinstance(value, list):
            for child in value:
                adapt(child)

    adapt(schema)
    try:
        return json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid") from error


def _supports_strict_structured_output(schema: bytes) -> bool:
    """Detect valid schema constructs that strict Structured Outputs rejects."""

    try:
        document = json.loads(schema)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise AnalysisRunnerError("analysis_runner_output_schema_invalid") from error

    def supported(value: Any) -> bool:
        if isinstance(value, dict):
            if isinstance(value.get("additionalProperties"), dict):
                return False
            return all(supported(child) for child in value.values())
        if isinstance(value, list):
            return all(supported(child) for child in value)
        return True

    return supported(document)


def _canonical_context(context_bytes: bytes, maximum: int) -> bytes:
    if (
        not isinstance(context_bytes, bytes)
        or not context_bytes
        or len(context_bytes) > maximum
    ):
        raise AnalysisRunnerError("analysis_runner_context_invalid")
    try:
        text = context_bytes.decode("utf-8")
        parse_canonical_context_json(text)
    except (UnicodeDecodeError, ContextBuildError, ValueError) as error:
        raise AnalysisRunnerError("analysis_runner_context_invalid") from error
    return context_bytes


def _write_private(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise AnalysisRunnerError("analysis_runner_workspace_failed") from error
    _private_mode(path, 0o600, "analysis_runner_workspace_failed")


def _prompt(
    bundle: HarnessBundle,
    harness: Sequence[tuple[str, bytes]],
    harness_files: Sequence[str],
    context_file: str,
    output_schema: bytes,
    correction_code: str | None = None,
) -> bytes:
    # The controlled stdin carries the complete instruction material.  The
    # copied files are only an isolated, auditable reference and never require
    # the agent to call a file tool.
    prefix = (
        "You are the TrainLab analysis generator. Follow the supplied trusted "
        "Harness documents in order and return only the required JSON output.\n"
        f"Route: {bundle.route}\n"
        "Harness files copied into this isolated workspace: "
        + ", ".join(harness_files)
        + "\n"
        + "The complete trusted Harness content follows, in declared order:\n"
    ).encode("utf-8")
    sections: list[bytes] = [prefix]
    for path_id, content in harness:
        sections.extend(
            (
                f"\n--- BEGIN TRUSTED HARNESS {path_id} ---\n".encode("utf-8"),
                content,
                f"\n--- END TRUSTED HARNESS {path_id} ---\n".encode("utf-8"),
            )
        )
    sections.extend(
        (
            b"\n--- BEGIN AUTHORITATIVE OUTPUT SCHEMA ---\n",
            output_schema,
            b"\n--- END AUTHORITATIVE OUTPUT SCHEMA ---\n",
        )
    )
    sections.append(
        f"Canonical analysis input is in {context_file}; its complete UTF-8 JSON follows:\n".encode(
            "utf-8"
        )
    )
    if correction_code is not None:
        sections.append(
            (
                "\nA prior candidate was rejected by the deterministic host validator "
                f"with code `{correction_code}`. Produce a fresh candidate from the "
                "same authoritative context, explicitly correcting that violation. "
                "The rejected candidate is intentionally unavailable; do not infer or "
                "repeat it.\n"
            ).encode("utf-8")
        )
    return b"".join(sections)


def _secure_owned_directory(path: Path) -> Path:
    """Return a current-user-owned, non-link directory without exposing it.

    Authentication state is an operator-owned local boundary.  The analysis
    child may receive only a directory that already exists, is owned by the
    effective service user, is not writable by that user's group or others,
    and contains no symlink indirection in its supplied path.
    """

    if not path.is_absolute():
        raise AnalysisRunnerError("analysis_runner_auth_home_unavailable")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.stat()
    except OSError as error:
        raise AnalysisRunnerError("analysis_runner_auth_home_unavailable") from error
    if (
        resolved != path
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise AnalysisRunnerError("analysis_runner_auth_home_unavailable")
    return resolved


def _trusted_codex_home() -> str:
    """Locate safe Codex auth state for the effective OS user.

    ``HOME`` is intentionally replaced with the isolated workspace below, so
    the CLI cannot discover user configuration or MCP servers.  Codex auth is
    instead supplied through its dedicated home variable.  LaunchAgents may
    omit both ``HOME`` and ``CODEX_HOME``; in that case the account database,
    rather than inherited environment, is authoritative.  This path is never
    included in result metadata or an exception.
    """

    configured = os.environ.get("CODEX_HOME")
    if configured:
        return str(_secure_owned_directory(Path(configured)))
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError, AttributeError):
        raise AnalysisRunnerError("analysis_runner_auth_home_unavailable")
    home = _secure_owned_directory(account_home)
    return str(_secure_owned_directory(home / ".codex"))


def _command(
    executable: Sequence[str],
    output_schema_path: str = "output.schema.json",
    structured_output: bool = True,
) -> tuple[str, ...]:
    if not executable or any(
        not isinstance(item, str) or not item for item in executable
    ):
        raise AnalysisRunnerError("analysis_runner_command_invalid")
    if (
        Path(output_schema_path).is_absolute()
        or output_schema_path != "output.schema.json"
    ):
        raise AnalysisRunnerError("analysis_runner_command_invalid")
    # Do not add --model: model selection remains an operator/runtime concern.
    # The sandbox and empty MCP registry are explicit defence in depth.  The
    # no-tool feature switches are deliberately adapter-owned, never config- or
    # prompt-controlled.
    command = tuple(executable) + (
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--config",
        "mcp_servers={}",
        "--config",
        "tools.shell=false",
        "--config",
        "tools.file_write=false",
        "--config",
        "tools.network=false",
    )
    if not structured_output:
        return command
    insertion = command.index("--sandbox")
    return (
        *command[:insertion],
        "--output-schema",
        output_schema_path,
        *command[insertion:],
    )


def _terminate_group(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    try:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        return process.poll() is not None
    except (OSError, subprocess.SubprocessError):
        return False


class AnalysisCodexRunner:
    """Run at most one isolated ``codex exec --ephemeral`` generation."""

    def __init__(
        self,
        config: AnalysisConfig,
        *,
        executable: Sequence[str] = ("codex",),
        process_factory: ProcessFactory = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(config, AnalysisConfig):
            raise AnalysisRunnerError("analysis_runner_config_invalid")
        self._config = config
        self._executable = tuple(executable)
        self._process_factory = process_factory
        self._monotonic = monotonic

    def execute(
        self, bundle: HarnessBundle, canonical_context: bytes
    ) -> AnalysisRunnerResult:
        """Perform exactly one generation, or raise a stable safe failure code."""

        return self._execute(bundle, canonical_context, correction_code=None)

    def execute_correction(
        self,
        bundle: HarnessBundle,
        canonical_context: bytes,
        correction_code: str,
    ) -> AnalysisRunnerResult:
        """Perform one bounded fresh generation using only a safe rejection code."""

        if (
            not isinstance(correction_code, str)
            or not correction_code.startswith("analysis_result_")
            or len(correction_code) > 160
        ):
            raise AnalysisRunnerError("analysis_runner_correction_code_invalid")
        return self._execute(bundle, canonical_context, correction_code=correction_code)

    def _execute(
        self,
        bundle: HarnessBundle,
        canonical_context: bytes,
        *,
        correction_code: str | None,
    ) -> AnalysisRunnerResult:
        context = _canonical_context(canonical_context, self._config.max_context_bytes)
        harness = _safe_bundle_files(self._config, bundle)
        authoritative_output_schema = _safe_output_schema(self._config, bundle)
        output_schema = _codex_compatible_output_schema(authoritative_output_schema)
        command = _command(
            self._executable,
            structured_output=_supports_strict_structured_output(output_schema),
        )
        codex_home = _trusted_codex_home()
        started = self._monotonic()
        process: subprocess.Popen[bytes] | None = None
        process_cleaned = False

        try:
            with tempfile.TemporaryDirectory(
                dir=self._config.temp_root, prefix="codex-"
            ) as directory:
                workspace = Path(directory)
                os.chmod(workspace, 0o700)
                _private_mode(workspace, 0o700, "analysis_runner_workspace_failed")
                copied_names: list[str] = []
                harness_root = workspace / "harness"
                harness_root.mkdir(mode=0o700)
                _private_mode(harness_root, 0o700, "analysis_runner_workspace_failed")
                for index, (path_id, payload) in enumerate(harness):
                    name = f"{index:02d}-{Path(path_id).name}"
                    _write_private(harness_root / name, payload)
                    copied_names.append(f"harness/{name}")
                context_path = workspace / "context.json"
                _write_private(context_path, context)
                _write_private(workspace / "output.schema.json", output_schema)
                stdin_payload = (
                    _prompt(
                        bundle,
                        harness,
                        copied_names,
                        "context.json",
                        authoritative_output_schema,
                        correction_code,
                    )
                    + context
                )

                try:
                    process = self._process_factory(
                        command,
                        cwd=workspace,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                        env={
                            "PATH": os.environ.get("PATH", ""),
                            "LANG": "C.UTF-8",
                            "LC_ALL": "C.UTF-8",
                            "HOME": str(workspace),
                            "CODEX_HOME": codex_home,
                        },
                    )
                except OSError as error:
                    raise AnalysisRunnerError(
                        "analysis_runner_process_start_failed"
                    ) from error
                if (
                    process.stdin is None
                    or process.stdout is None
                    or process.stderr is None
                ):
                    raise AnalysisRunnerError("analysis_runner_process_start_failed")
                try:
                    process.stdin.write(stdin_payload)
                    process.stdin.close()
                except OSError as error:
                    _terminate_group(process)
                    raise AnalysisRunnerError(
                        "analysis_runner_process_io_failed"
                    ) from error

                output = self._collect_output(process, self._config.max_context_bytes)
                process_cleaned = (
                    _terminate_group(process) if process.poll() is None else True
                )
                if not process_cleaned:
                    raise AnalysisRunnerError("analysis_runner_process_cleanup_failed")
                if process.returncode != 0:
                    raise AnalysisRunnerError("analysis_runner_process_nonzero")
                duration_ms = int((self._monotonic() - started) * 1000)
                return AnalysisRunnerResult(
                    output_bytes=output,
                    audit={
                        "runner_adapter_version": RUNNER_ADAPTER_VERSION,
                        "route": bundle.route,
                        "harness_version": bundle.harness_version,
                        "input_utf8_bytes": len(context),
                        "output_utf8_bytes": len(output),
                        "duration_ms": max(duration_ms, 0),
                        "timed_out": False,
                        "process_group_cleaned": True,
                        "correction_attempt": correction_code is not None,
                        "correction_code": correction_code,
                    },
                )
        finally:
            if process is not None and process.poll() is None:
                _terminate_group(process)

    def _collect_output(self, process: subprocess.Popen[bytes], maximum: int) -> bytes:
        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        output = bytearray()
        try:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            deadline = self._monotonic() + self._config.codex_timeout_seconds
            while selector.get_map():
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    _terminate_group(process)
                    raise AnalysisRunnerError("analysis_runner_process_timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if isinstance(key.fileobj, int):
                        raise AnalysisRunnerError("analysis_runner_selector_invalid")
                    chunk = os.read(key.fileobj.fileno(), _READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stdout":
                        output.extend(chunk)
                        if len(output) > maximum:
                            _terminate_group(process)
                            raise AnalysisRunnerError(
                                "analysis_runner_output_limit_exceeded"
                            )
                if process.poll() is not None and not selector.get_map():
                    break
            process.wait(timeout=1)
            return bytes(output)
        except subprocess.TimeoutExpired as error:
            _terminate_group(process)
            raise AnalysisRunnerError("analysis_runner_process_timeout") from error
        finally:
            selector.close()
