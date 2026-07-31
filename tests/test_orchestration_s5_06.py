from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from copy import deepcopy

import pytest

from trainlab.orchestration import DownstreamCall, SubprocessRunner
from trainlab.orchestration.subprocess_runner import SubprocessBoundaryError
from trainlab.process_liveness import process_is_running
import trainlab.orchestration.subprocess_runner as runner_module


def call() -> DownstreamCall:
    return DownstreamCall("foundation", "status", "invoke-1", None)


def receipt(**change: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1", "invocation_id": "invoke-1", "mode": "status",
        "status": "ready", "foundation_schema_version": 1, "ready": True,
        "created_count": 0, "existing_count": 0, "verified_count": 1,
        "migration_start_version": None, "migration_end_version": None,
        "applied_migration_ids": [], "next_action": "none", "warnings": [], "errors": [],
        "started_at_utc": "2026-07-24T00:00:00Z", "completed_at_utc": "2026-07-24T00:00:01Z",
    }
    value.update(change)
    return value


class FakeProcess:
    def __init__(self, out: bytes, code: int = 0, timeout: bool = False, ignore_term: bool = False) -> None:
        self.out, self.code, self.timeout, self.ignore_term, self.pid, self.returncode = out, code, timeout, ignore_term, 12345, code
        self.calls = 0
    def communicate(self, timeout: int):
        self.calls += 1
        if self.timeout and (self.calls == 1 or (self.ignore_term and self.calls == 2)):
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.out, b"secret=never-returned"


def install(monkeypatch: pytest.MonkeyPatch, process: FakeProcess) -> dict[str, object]:
    captured: dict[str, object] = {}
    def popen(argv, **kwargs):
        captured["argv"] = argv; captured.update(kwargs); return process
    monkeypatch.setattr(runner_module.subprocess, "Popen", popen)
    return captured


def test_success_uses_frozen_no_shell_boundary_and_hashes_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert result.kind == "accepted" and result.receipt_sha256 and len(result.request_sha256) == 64
    assert captured["shell"] is False and captured["close_fds"] is True and captured["start_new_session"] is True
    assert captured["env"] == {"PATH": runner_module.bounded_runtime_path(), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "Asia/Singapore"}
    assert "secret" not in repr(result)


@pytest.mark.parametrize("out", [b"not json", b"{}\n{}", b"notice {}", json.dumps(receipt(mode="verify")).encode()])
def test_non_json_multiple_garbage_and_identity_mismatch_are_untrusted(monkeypatch: pytest.MonkeyPatch, out: bytes) -> None:
    install(monkeypatch, FakeProcess(out))
    assert SubprocessRunner().run(call()).kind == "untrusted"


def test_schema_and_exit_mismatch_and_output_limit_are_untrusted(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeProcess(json.dumps(receipt(ready="bad")).encode()))
    assert SubprocessRunner().run(call()).error_code == "receipt_schema_invalid"
    install(monkeypatch, FakeProcess(json.dumps(receipt()).encode(), 21))
    assert SubprocessRunner().run(call()).error_code == "receipt_exit_mismatch"
    install(monkeypatch, FakeProcess(b"x" * 2_000))
    assert SubprocessRunner(output_limit=1_024).run(call()).error_code == "process_output_limit"


def test_timeout_is_unknown_and_terminates_the_whole_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(b"", timeout=True)
    install(monkeypatch, process)
    killed: list[int] = []
    monkeypatch.setattr(runner_module.os, "killpg", lambda pid, sig: killed.append(sig))
    monkeypatch.setattr(SubprocessRunner, "_process_group_exists", staticmethod(lambda _pid: False))
    result = SubprocessRunner().run(call())
    assert result.kind == "timeout_unknown" and result.error_code == "process_timeout_unknown"
    assert killed == [runner_module.signal.SIGTERM]


def test_timeout_ignoring_term_is_killed_with_its_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(b"", timeout=True, ignore_term=True)
    install(monkeypatch, process)
    killed: list[int] = []
    monkeypatch.setattr(runner_module.os, "killpg", lambda pid, sig: killed.append(sig))
    monkeypatch.setattr(SubprocessRunner, "_process_group_exists", staticmethod(lambda _pid: False))
    assert SubprocessRunner().run(call()).kind == "timeout_unknown"
    assert killed == [runner_module.signal.SIGTERM, runner_module.signal.SIGKILL]


def test_timeout_does_not_leave_runner_reader_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {thread.ident for thread in threading.enumerate()}
    process = FakeProcess(b"", timeout=True, ignore_term=True)
    install(monkeypatch, process)
    monkeypatch.setattr(runner_module.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(SubprocessRunner, "_process_group_exists", staticmethod(lambda _pid: False))
    assert SubprocessRunner().run(call()).kind == "timeout_unknown"
    assert {thread.ident for thread in threading.enumerate()} <= before


@pytest.mark.parametrize(("failure", "expected"), [
    (subprocess.TimeoutExpired("fake", 1), "process_timeout_unknown"),
    (ValueError("process_output_limit"), "process_output_limit"),
])
def test_cleanup_failure_overrides_timeout_or_output_limit(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    expected: str,
) -> None:
    """An ordinary execution error is unsafe until the whole group is gone."""
    install(monkeypatch, FakeProcess(b""))
    runner = SubprocessRunner()
    def fail(_process: object, _timeout: int) -> tuple[bytes, bytes]:
        raise failure
    monkeypatch.setattr(runner, "_communicate_bounded", fail)
    monkeypatch.setattr(runner, "_terminate_group", lambda _process: False)
    result = runner.run(call())
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", "process_group_unreaped", None)
    assert result.error_code != expected


class _BrokenPipe:
    def read(self, _size: int) -> bytes:
        raise OSError("child-payload-must-not-escape")

    def close(self) -> None:
        return None


class _EmptyPipe:
    def read(self, _size: int) -> bytes:
        return b""

    def close(self) -> None:
        return None


class _ReaderFailureProcess:
    pid = 54321
    returncode = None
    stdout = _BrokenPipe()
    stderr = _EmptyPipe()

    def poll(self) -> None:
        return None


def test_reader_exception_is_controlled_and_reclaims_threads_and_group(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _ReaderFailureProcess()
    install(monkeypatch, process)  # type: ignore[arg-type]
    runner = SubprocessRunner()
    before = [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")]
    terminated: list[object] = []
    monkeypatch.setattr(runner, "_terminate_group", lambda item: terminated.append(item) or True)
    monkeypatch.setattr(runner, "_process_group_exists", lambda _pid: False)
    result = runner.run(call())
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", "process_reader_error", None)
    # The runner verifies cleanup again at its public boundary; both attempts
    # target the same isolated process group rather than treating reader error
    # as a normal completed invocation.
    assert terminated == [process, process]
    assert [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")] == before
    assert "child-payload-must-not-escape" not in repr(result)


def test_reader_error_cleanup_failure_has_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _ReaderFailureProcess()
    install(monkeypatch, process)  # type: ignore[arg-type]
    runner = SubprocessRunner()
    monkeypatch.setattr(runner, "_terminate_group", lambda _item: False)
    monkeypatch.setattr(runner, "_process_group_exists", lambda _pid: True)
    result = runner.run(call())
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", "process_group_unreaped", None)


def test_rejects_unsafe_mode_or_timeout_before_process(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeProcess(b""))
    with pytest.raises(ValueError, match="subprocess_mode_not_allowed"):
        SubprocessRunner().run(DownstreamCall("foundation", "migrate", "x", None, 5))
    with pytest.raises(ValueError, match="subprocess_timeout_static_only"):
        SubprocessRunner().run(DownstreamCall("foundation", "status", "x", None, 1))
    with pytest.raises(ValueError, match="subprocess_request_hash_invalid"):
        SubprocessRunner().run(DownstreamCall("foundation", "status", "x", "a" * 64))
    with pytest.raises(ValueError, match="subprocess_request_json_invalid"):
        SubprocessRunner().run(DownstreamCall("mail", "run", "x", None, subject_id=1, max_items=float("nan")))  # type: ignore[arg-type]


@pytest.mark.parametrize("layer,mode,kwargs", [
    ("garmin", "full", {}), ("garmin", "incremental", {}),
    ("garmin", "snapshot", {}),
])
def test_public_optional_fields_are_not_narrowed(layer: str, mode: str, kwargs: dict[str, object]) -> None:
    assert runner_module._argv(DownstreamCall(layer, mode, "invoke-1", None, **kwargs))


def test_analysis_regeneration_and_status_use_only_the_root_production_entry() -> None:
    assert runner_module._argv(DownstreamCall(
        "analysis", "regenerate", "invoke-1", None, subject_id="subject-1",
        artifact_id="7", regeneration_reason_code="explicit_user_request",
    )) == (
        str(runner_module._EXECUTABLE), "run", "--slot", "morning", "--analysis-only",
        "--regenerate", "--artifact-id", "7", "--regenerate-reason",
        "explicit_user_request", "--invocation-id", "invoke-1", "--deliver",
    )
    assert runner_module._argv(DownstreamCall(
        "analysis", "status", None, None, subject_id="subject-1",
        run_key="analysis:subject-1:daily:2026-07-24:invoke-1",
    )) == (
        str(runner_module._EXECUTABLE), "run", "--slot", "morning", "--analysis-only",
        "--status", "--run-key", "analysis:subject-1:daily:2026-07-24:invoke-1",
    )
    with pytest.raises(SubprocessBoundaryError, match="status_invocation_forbidden"):
        runner_module._argv(DownstreamCall(
            "analysis", "status", "invoke-1", None, subject_id="subject-1"
        ))


@pytest.mark.parametrize("kwargs,code", [
    ({"resource_kinds":("a", "a")}, "subprocess_collection_invalid"),
    ({"activity_ids":("bad space",)}, "subprocess_collection_invalid"),
    ({"dependency_analysis_artifact_ids":("x",) * 65}, "subprocess_field_forbidden"),
    ({"regeneration_reason_code":"Bad"}, "subprocess_field_forbidden"),
    ({"health_from_local_date":"2026-07-25", "through_local_date":"2026-07-24"}, "subprocess_date_range_invalid"),
    ({"health_from_local_date":"2026-99-99"}, "subprocess_date_invalid"),
])
def test_static_tuple_reason_and_date_boundaries_fail_closed(kwargs: dict[str, object], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        runner_module._argv(DownstreamCall("garmin", "repair", "invoke-1", None, **kwargs))


@pytest.mark.parametrize(("kwargs", "suffix"), [
    ({"health_from_local_date":"2026-07-23"}, ("--health-from", "2026-07-23")),
    ({"through_local_date":"2026-07-24"}, ("--through", "2026-07-24")),
])
def test_garmin_full_preserves_each_independently_optional_date(kwargs: dict[str, str], suffix: tuple[str, str]) -> None:
    assert runner_module._argv(DownstreamCall("garmin", "full", "invoke-1", None, **kwargs))[-2:] == suffix


def test_garmin_audit_preserves_bounded_date_range() -> None:
    assert runner_module._argv(
        DownstreamCall(
            "garmin",
            "audit",
            "invoke-1",
            None,
            health_from_local_date="2026-07-23",
            through_local_date="2026-07-24",
        )
    )[-4:] == ("--from", "2026-07-23", "--through", "2026-07-24")


def test_analysis_subject_disallows_colon_and_allowed_mode_validates_own_fields() -> None:
    with pytest.raises(ValueError, match="subprocess_subject_required"):
        runner_module._argv(DownstreamCall("analysis", "daily", "invoke-1", None, subject_id="subject:bad"))
    with pytest.raises(ValueError, match="subprocess_collection_invalid"):
        runner_module._argv(DownstreamCall("mail", "process", "invoke-1", None, subject_id=1, mail_message_id="message-1", dependency_analysis_artifact_ids=("x",) * 65))
    with pytest.raises(ValueError, match="subprocess_reason_invalid"):
        runner_module._argv(DownstreamCall("analysis", "regenerate", "invoke-1", None, subject_id="subject-1", artifact_id="artifact-1", regeneration_reason_code="Bad"))


def test_plan_revision_argv_uses_only_the_root_production_entry() -> None:
    assert runner_module._argv(
        DownstreamCall(
            "analysis",
            "revise_plan",
            "invoke-1",
            None,
            subject_id="subject-1",
            plan_id="7",
            reason_event_id="9",
            effective_local_date="2026-07-24",
        )
    )[-8:] == (
        "--revise-plan",
        "--plan-id",
        "7",
        "--reason-event-id",
        "9",
        "--effective-date",
        "2026-07-24",
        "--deliver",
    )
    for plan_id, reason_id in (("plan-7", "9"), ("7", "event-9")):
        with pytest.raises(
            SubprocessBoundaryError,
            match="subprocess_plan_revision_target_required",
        ):
            runner_module._argv(
                DownstreamCall(
                    "analysis",
                    "revise_plan",
                    "invoke-1",
                    None,
                    subject_id="subject-1",
                    plan_id=plan_id,
                    reason_event_id=reason_id,
                )
            )


def test_exact_exit_maps_cover_every_manifest_status() -> None:
    assert runner_module._EXIT_BY_LAYER == {
        "foundation": {"initialized": 0, "already_initialized": 0, "ready": 0, "incompatible": 10, "lock_busy": 11, "failed": 20},
        "garmin": {"succeeded": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "auth_required": 20, "failed": 21},
        "analysis": {"succeeded": 0, "unchanged": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "rejected": 20, "failed": 21},
        "mail": {"succeeded": 0, "unchanged": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "auth_required": 20, "rejected": 21, "failed": 22},
    }


@pytest.mark.parametrize("status,exit_code", runner_module._EXIT_BY_LAYER["foundation"].items())
def test_foundation_every_status_uses_its_exact_exit(status: str, exit_code: int) -> None:
    value = receipt(status=status)
    accepted, code = runner_module._validate_receipt(call(), value, exit_code)
    assert accepted is not None and code is not None
    rejected, reason = runner_module._validate_receipt(call(), value, 99)
    assert rejected is None and reason == "receipt_exit_mismatch"


def test_receipt_identity_and_time_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = receipt(invocation_id="other")
    install(monkeypatch, FakeProcess(json.dumps(bad).encode()))
    assert SubprocessRunner().run(call()).error_code == "receipt_invocation_mismatch"
    bad = receipt(completed_at_utc="2026-07-23T00:00:00Z")
    install(monkeypatch, FakeProcess(json.dumps(bad).encode()))
    assert SubprocessRunner().run(call()).error_code == "receipt_time_order_invalid"


def _layer_fixture(layer: str, mode: str) -> dict[str, object]:
    path = Path(__file__).parent / "fixtures/orchestration/s5_00_receipts.json"
    value = deepcopy(json.loads(path.read_text())[layer][mode])
    if layer == "analysis":
        value.update(run_key="analysis:subject-1:daily:default:analysis-daily-001", target_periods={"summary":None,"advice":None,"review":None,"plan":None}, status_snapshot=None, content_same=None)
        value["delivery"] = {"delivery_id":"analysis-delivery-001","status":"sent","artifact_ids":["artifact-001"],"provider_message_id":None,"provider_thread_id":None,"error":None}
    if layer == "mail": value.update(poll_state=[], run_key="mail:1:run:mail-run-001")
    return value


@pytest.mark.parametrize("layer,mode,call_kwargs", [
    ("garmin", "incremental", {"through_local_date":"2026-07-22"}),
    ("analysis", "daily", {"subject_id":"subject-1"}),
    ("mail", "run", {"subject_id":1}),
])
def test_downstream_statuses_have_exact_exit_contract(layer: str, mode: str, call_kwargs: dict[str, object]) -> None:
    request = DownstreamCall(layer, mode, {"garmin": None, "analysis":"analysis-daily-001", "mail":"mail-run-001"}[layer], None, **call_kwargs)  # type: ignore[arg-type]
    base = _layer_fixture(layer, mode)
    for status, exit_code in runner_module._EXIT_BY_LAYER[layer].items():
        value = dict(base); value["status"] = status
        accepted, digest = runner_module._validate_receipt(request, value, exit_code)
        assert accepted is not None and digest is not None
        rejected, reason = runner_module._validate_receipt(request, value, 99)
        assert rejected is None and reason == "receipt_exit_mismatch"


def test_analysis_target_period_mutations_fail_closed() -> None:
    value = _layer_fixture("analysis", "daily")
    request = DownstreamCall("analysis", "daily", "analysis-daily-001", None, subject_id="subject-1", summary_local_date="2026-07-24")
    value["run_key"] = "analysis:subject-1:daily:2026-07-24:analysis-daily-001"
    value["target_periods"] = {"summary":{"start_local_date":"2026-07-23","end_local_date":"2026-07-24"},"advice":None,"review":None,"plan":None}
    assert runner_module._validate_receipt(request, value, 0)[1] == "receipt_target_mismatch"


def test_snapshot_none_range_mutations_fail_closed() -> None:
    value = _layer_fixture("garmin", "incremental")
    request = DownstreamCall("garmin", "snapshot", "invoke-1", None, snapshot_local_date="2026-07-24")
    value.update(mode="snapshot", requested_range={"from":None,"through":"2026-07-24"})
    assert runner_module._validate_receipt(request, value, 0)[1] == "receipt_target_mismatch"
    value["requested_range"] = {"from":"2026-07-24","through":None}
    assert runner_module._validate_receipt(request, value, 0)[1] == "receipt_target_mismatch"


@pytest.mark.parametrize("period,field,wrong", [("review","start_local_date","2026-07-18"),("review","end_local_date","2026-07-22"),("plan","start_local_date","2026-07-25"),("plan","end_local_date","2026-07-31")])
def test_weekly_boundary_mutations_fail_closed(period: str, field: str, wrong: str) -> None:
    value = _layer_fixture("analysis", "daily"); value.update(mode="weekly", invocation_id="invoke-1", run_key="analysis:subject-1:weekly:2026-07-24:invoke-1", target_periods={"summary":None,"advice":None,"review":{"start_local_date":"2026-07-17","end_local_date":"2026-07-23"},"plan":{"start_local_date":"2026-07-24","end_local_date":"2026-07-30"}})
    value["target_periods"][period][field] = wrong
    assert runner_module._validate_receipt(DownstreamCall("analysis","weekly","invoke-1",None,subject_id="subject-1",as_of_local_date="2026-07-24"), value, 0)[1] == "receipt_target_mismatch"


def test_analysis_status_default_key_and_unescaped_key_mutations_fail_closed() -> None:
    value = _layer_fixture("analysis", "daily"); value.update(mode="status", invocation_id=None, run_key="analysis:subject-1:status:current:read_only", status_snapshot={"selected_run":None,"current_artifacts":[],"current_plan":None,"latest_delivery":None,"delivery_counts":{"pending":0,"delivery_unknown":0,"failed":0},"actionable_delivery_ids":{"retry_delivery":[],"reconcile_delivery":[]},"recent_terminal_at_utc":{"succeeded":None,"failed":None,"rejected":None,"deferred":None},"quality_blocker_codes":[],"deferred_history_supported":False})
    assert runner_module._validate_receipt(DownstreamCall("analysis","status",None,None,subject_id="subject-1"), value, 0)[0] is not None
    value["run_key"] = "prefix-analysis:subject-1:status:current:read_only"
    assert runner_module._validate_receipt(DownstreamCall("analysis","status",None,None,subject_id="subject-1"), value, 0)[0] is None


def test_revise_effective_must_be_plan_start() -> None:
    value = _layer_fixture("analysis", "daily"); value.update(mode="revise_plan", invocation_id="invoke-1", run_key="analysis:subject-1:revise_plan:plan-1:event-1:invoke-1", target_periods={"summary":None,"advice":None,"review":None,"plan":{"start_local_date":"2026-07-23","end_local_date":"2026-07-24"}})
    request = DownstreamCall("analysis","revise_plan","invoke-1",None,subject_id="subject-1",plan_id="plan-1",reason_event_id="event-1",effective_local_date="2026-07-24")
    assert runner_module._validate_receipt(request, value, 0)[1] == "receipt_target_mismatch"
    value["target_periods"]["plan"]["start_local_date"] = "2026-07-24"
    assert runner_module._validate_receipt(request, value, 0)[0] is not None


@pytest.mark.parametrize("mode,kwargs,target", [
    ("revise_plan", {"plan_id":"p:a","reason_event_id":"e:b"}, "p%3Aa:e%3Ab"),
    ("regenerate", {"artifact_id":"a:b"}, "a%3Ab"),
    ("retry_delivery", {"delivery_id":"d:e"}, "d%3Ae"),
    ("reconcile_delivery", {"delivery_id":"d:e"}, "d%3Ae"),
])
def test_analysis_dynamic_colon_key_is_escaped_exactly(mode: str, kwargs: dict[str, str], target: str) -> None:
    invocation = "i:c"; value = _layer_fixture("analysis", "daily")
    key = f"analysis:subject-1:{mode}:{target}:i%3Ac"
    value.update(mode=mode, invocation_id=invocation, run_key=key)
    if "delivery_id" in kwargs: value["delivery"]["delivery_id"] = kwargs["delivery_id"]
    if "artifact_id" in kwargs: value["artifact_ids"] = [kwargs["artifact_id"]]
    request = DownstreamCall("analysis", mode, invocation, None, subject_id="subject-1", **kwargs)
    assert runner_module._validate_receipt(request, value, 0)[0] is not None
    value["run_key"] = key.replace("%3A", ":")
    assert runner_module._validate_receipt(request, value, 0)[0] is None


def test_all_mode_argv_snapshots_are_fixed_and_targets_are_required() -> None:
    for layer, modes in runner_module._MODES.items():
        for mode in modes:
            args = dict(layer=layer, mode=mode, invocation_id="invoke-1", request_sha256=None)
            values = {"subject_id": 1 if layer == "mail" else "subject-1", "summary_local_date":"2026-07-24", "advice_local_date":"2026-07-25", "as_of_local_date":"2026-07-24", "plan_id":"7", "reason_event_id":"9", "effective_local_date":"2026-07-24", "artifact_id":"7", "delivery_id":"1" if layer == "analysis" else "delivery-1", "mail_message_id":"message-1", "mail_response_artifact_id":"response-1", "health_from_local_date":"2026-07-23", "through_local_date":"2026-07-24", "snapshot_local_date":"2026-07-24", "resource_kinds":("activities",), "activity_ids":("activity-1",), "repair_strategy":"auto", "regeneration_reason_code":"manual", "run_key":"run-1", "max_items":2, "max_threads":2, "deadline_seconds":30, "dependency_analysis_artifact_ids":("artifact-1",)}
            args.update({key: values[key] for key in runner_module._MODE_FIELDS.get((layer, mode), ())})
            if layer == "analysis" and mode == "status":
                args["invocation_id"] = None
            argv = runner_module._argv(DownstreamCall(**args))
            assert Path(argv[0]).is_absolute() and "sh" not in argv[0]


def test_generated_argv_round_trips_the_real_public_parsers() -> None:
    from trainlab.cli import _parser as root_parser
    from trainlab.mail_agent.cli import _parser as mail_parser
    foundation = runner_module._argv(DownstreamCall("foundation", "verify", "invoke-1", None))
    garmin = runner_module._argv(DownstreamCall("garmin", "repair", "invoke-1", None, health_from_local_date="2026-07-23", through_local_date="2026-07-24", resource_kinds=("activities",), repair_strategy="auto"))
    analysis = runner_module._argv(DownstreamCall("analysis", "daily", "invoke-1", None, subject_id="subject-1", summary_local_date="2026-07-23"))
    revision = runner_module._argv(DownstreamCall("analysis", "revise_plan", "invoke-2", None, subject_id="subject-1", plan_id="7", reason_event_id="9", effective_local_date="2026-07-24"))
    mail = runner_module._argv(DownstreamCall("mail", "run", "invoke-1", None, subject_id=1, max_items=2, deadline_seconds=30))
    root_parser().parse_args(list(foundation[1:]))
    root_parser().parse_args(list(garmin[1:]))
    root_parser().parse_args(list(analysis[1:]))
    root_parser().parse_args(list(revision[1:]))
    mail_parser().parse_args(list(mail[3:]))


def test_mail_scheduler_invocation_with_fractional_seconds_is_safe_argv() -> None:
    invocation = "20260727T155229.484382Z"
    argv = runner_module._argv(
        DownstreamCall(
            "mail",
            "run",
            invocation,
            None,
            subject_id=1,
            max_items=2,
            deadline_seconds=30,
        )
    )
    assert invocation in argv


def _script(path: Path, source: str) -> None:
    path.write_text("#!" + sys.executable + "\n" + source)
    path.chmod(0o700)


def _raw_child(path: Path, payload: bytes, exit_code: int = 0) -> None:
    _script(path, "import sys; sys.stdout.buffer.write(" + repr(payload) + "); sys.stdout.buffer.flush(); raise SystemExit(" + str(exit_code) + ")")


def _assert_pid_gone(pid: int) -> None:
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if not process_is_running(pid):
            return
        time.sleep(0.05)
    pytest.fail("detached_stdio_grandchild_survived")


@pytest.mark.parametrize(("payload", "expected_kind"), [
    (json.dumps(receipt()).encode(), "accepted"),
    (b"not-json", "untrusted"),
])
def test_parent_exit_reclaims_background_group_without_inherited_pipes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
    expected_kind: str,
) -> None:
    child_pid = tmp_path / "detached-stdio.pid"
    parent = tmp_path / "detached-stdio-parent"
    source = (
        "import subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c',"
        + repr("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)")
        + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        "open(" + repr(str(child_pid)) + ",'w').write(str(child.pid));"
        "sys.stdout.buffer.write(" + repr(payload) + ");sys.stdout.buffer.flush();"
        "raise SystemExit(" + ("0" if expected_kind == "accepted" else "20") + ")"
    )
    _script(parent, source)
    monkeypatch.setattr(runner_module, "_EXECUTABLE", parent)
    readers_before = {item.ident for item in threading.enumerate() if item.name.startswith("trainlab-reader-")}
    fd_before = len(tuple(Path("/dev/fd").iterdir()))
    result = SubprocessRunner(grace_seconds=1).run(call())
    assert result.kind == expected_kind
    assert result.exit_code == (0 if expected_kind == "accepted" else 20)
    _assert_pid_gone(int(child_pid.read_text()))
    assert {item.ident for item in threading.enumerate() if item.name.startswith("trainlab-reader-")} == readers_before
    assert len(tuple(Path("/dev/fd").iterdir())) <= fd_before


def _valid_receipt_bytes() -> bytes:
    return json.dumps(receipt(), separators=(",", ":")).encode()


@pytest.mark.parametrize("payload", [
    _valid_receipt_bytes().replace(b'"status":"ready"', b'"status":"ready","status":"failed"'),
    _valid_receipt_bytes().replace(b'"warnings":[]', b'"warnings":[{"code":"one","code":"two"}]'),
    _valid_receipt_bytes().replace(b'"created_count":0', b'"created_count":NaN'),
    _valid_receipt_bytes().replace(b'"created_count":0', b'"created_count":Infinity'),
    _valid_receipt_bytes().replace(b'"created_count":0', b'"created_count":-Infinity'),
    b"\xef\xbb\xbf" + _valid_receipt_bytes(),
    _valid_receipt_bytes() + b"\xff",
    _valid_receipt_bytes() + b"\n{}",
    b"diagnostic:" + _valid_receipt_bytes(),
    _valid_receipt_bytes() + b":diagnostic",
], ids=[
    "duplicate-top-level", "duplicate-nested", "nan", "infinity",
    "negative-infinity", "bom", "invalid-utf8", "multiple-documents",
    "diagnostic-prefix", "diagnostic-suffix",
])
def test_strict_json_receipt_parser_rejects_nonstandard_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
) -> None:
    child = tmp_path / "strict-json-child"
    _raw_child(child, payload)
    monkeypatch.setattr(runner_module, "_EXECUTABLE", child)
    result = SubprocessRunner().run(call())
    assert (result.kind, result.error_code, result.exit_code) == ("untrusted", "receipt_json_invalid", 0)


class _UnreadableContractFile:
    def read_bytes(self) -> bytes:
        raise PermissionError("content-and-path-must-not-escape")


def _manifest_payload_with_unhashable_mode() -> bytes:
    value = json.loads(runner_module._MANIFEST.read_text(encoding="utf-8"))
    value["interfaces"]["foundation"]["modes"] = [[]]
    return json.dumps(value).encode()


def _manifest_payload_without_required_layer() -> bytes:
    value = json.loads(runner_module._MANIFEST.read_text(encoding="utf-8"))
    del value["interfaces"]["mail"]
    return json.dumps(value).encode()


def _manifest_payload_with_request_required_change(layer: str, mutation: str) -> bytes:
    value = json.loads(runner_module._MANIFEST.read_text(encoding="utf-8"))
    required = value["interfaces"][layer]["request_required"]
    if mutation == "add":
        required.append("unexpected_field")
    elif mutation == "remove":
        required.pop()
    elif mutation == "duplicate":
        required.append(required[0])
    elif mutation == "non_string":
        required.append({"field": "not-a-string"})
    else:
        raise AssertionError("unknown mutation")
    return json.dumps(value).encode()


def _contract_call_for(layer: str) -> DownstreamCall:
    return {
        "foundation": DownstreamCall("foundation", "status", "foundation-contract-1", None),
        "garmin": DownstreamCall("garmin", "status", "garmin-contract-1", None),
        "analysis": DownstreamCall("analysis", "daily", "analysis-contract-1", None, subject_id="subject-1"),
        "mail": DownstreamCall("mail", "run", "mail-contract-1", None, subject_id=1),
    }[layer]


@pytest.mark.parametrize(("payload", "expected"), [
    (b"\xff", "interface_manifest_invalid"),
    (b"{", "interface_manifest_invalid"),
    (b'{"interfaces":{},"interfaces":{}}', "interface_manifest_invalid"),
    (b'{"interfaces":NaN}', "interface_manifest_invalid"),
    (b"[]", "interface_manifest_invalid"),
    (_manifest_payload_with_unhashable_mode(), "interface_manifest_invalid"),
    (b'{"schema_version":"2","interfaces":{}}', "interface_manifest_invalid"),
    (_manifest_payload_without_required_layer(), "interface_manifest_invalid"),
], ids=["non-utf8", "invalid-json", "duplicate-key", "nan", "not-object", "unhashable-mode", "wrong-version", "missing-layer"])
def test_manifest_content_failures_after_child_exit_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
    expected: str,
) -> None:
    contract = tmp_path / "manifest.json"
    contract.write_bytes(payload)
    monkeypatch.setattr(runner_module, "_MANIFEST", contract)
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", expected, None)
    assert repr(result).find(str(contract)) == -1


@pytest.mark.parametrize("contract", ["missing", "unreadable"])
def test_manifest_read_failures_after_child_exit_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contract: str,
) -> None:
    source: object = tmp_path / "missing-manifest.json" if contract == "missing" else _UnreadableContractFile()
    monkeypatch.setattr(runner_module, "_MANIFEST", source)
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code, result.receipt) == (
        "untrusted", "interface_manifest_unavailable", None,
    )
    assert "content-and-path-must-not-escape" not in repr(result)


@pytest.mark.parametrize("layer", ["foundation", "garmin", "analysis", "mail"])
@pytest.mark.parametrize(("mutation", "expected"), [
    ("add", "interface_manifest_mismatch"),
    ("remove", "interface_manifest_mismatch"),
    ("duplicate", "interface_manifest_invalid"),
    ("non_string", "interface_manifest_invalid"),
])
def test_manifest_request_required_drift_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    layer: str,
    mutation: str,
    expected: str,
) -> None:
    request = _contract_call_for(layer)
    status = next(status for status, code in runner_module._EXIT_BY_LAYER[layer].items() if code == 0)
    payload = _offline_receipt_for(request, status)
    contract = tmp_path / "request-required-drift.json"
    contract.write_bytes(_manifest_payload_with_request_required_change(layer, mutation))
    monkeypatch.setattr(runner_module, "_MANIFEST", contract)
    captured = install(monkeypatch, FakeProcess(json.dumps(payload).encode()))
    result = SubprocessRunner().run(request)
    assert captured["argv"]
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", expected, None)
    assert "unexpected_field" not in repr(result)


@pytest.mark.parametrize("payload", [
    b"\xff",
    b"{",
    b'{"type":"object","type":"array"}',
    b'{"type":NaN}',
    b"[]",
    b'{"type":7,"required":[]}',
], ids=["non-utf8", "invalid-json", "duplicate-key", "nan", "not-object", "invalid-metaschema"])
def test_receipt_schema_content_failures_after_child_exit_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
) -> None:
    contract = tmp_path / "receipt.schema.json"
    contract.write_bytes(payload)
    monkeypatch.setitem(runner_module._SCHEMAS, "foundation", contract)
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code, result.receipt) == (
        "untrusted", "receipt_schema_invalid", None,
    )
    assert repr(result).find(str(contract)) == -1


@pytest.mark.parametrize("contract", ["missing", "unreadable"])
def test_receipt_schema_read_failures_after_child_exit_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contract: str,
) -> None:
    source: object = tmp_path / "missing.schema.json" if contract == "missing" else _UnreadableContractFile()
    monkeypatch.setitem(runner_module._SCHEMAS, "foundation", source)
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code, result.receipt) == (
        "untrusted", "receipt_schema_unavailable", None,
    )
    assert "content-and-path-must-not-escape" not in repr(result)


def test_receipt_schema_meta_validator_exception_is_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_cls: object, _schema: object) -> None:
        raise RuntimeError("schema-content-must-not-escape")

    monkeypatch.setattr(runner_module.Draft202012Validator, "check_schema", classmethod(explode))
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code) == ("untrusted", "receipt_schema_invalid")
    assert "schema-content-must-not-escape" not in repr(result)


def test_receipt_validator_runtime_exception_is_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_self: object, _value: object):
        raise RecursionError("receipt-content-must-not-escape")

    monkeypatch.setattr(runner_module.Draft202012Validator, "iter_errors", explode)
    captured = install(monkeypatch, FakeProcess(json.dumps(receipt()).encode()))
    result = SubprocessRunner().run(call())
    assert captured["argv"]
    assert (result.kind, result.error_code) == ("untrusted", "receipt_schema_invalid")
    assert "receipt-content-must-not-escape" not in repr(result)


@pytest.mark.parametrize("payload", [
    b"[" * 1_500 + b"0" + b"]" * 1_500,
    json.dumps({**receipt(), **{f"unexpected_{index}": index for index in range(10_000)}}).encode(),
], ids=["deep", "wide"])
def test_deep_and_wide_receipt_shapes_are_controlled_without_runner_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
) -> None:
    child = tmp_path / "deep-wide-child"
    _raw_child(child, payload)
    monkeypatch.setattr(runner_module, "_EXECUTABLE", child)
    result = SubprocessRunner().run(call())
    assert result.kind == "untrusted"
    assert result.error_code in {"receipt_json_invalid", "receipt_not_object", "receipt_schema_invalid"}
    assert result.receipt is None


def test_real_output_limit_and_process_group_kill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    readers_before = [thread for thread in threading.enumerate() if thread.name.startswith("trainlab-reader-")]
    noisy = tmp_path / "noisy"
    _script(noisy, "import sys; sys.stdout.write('x'*200000); sys.stdout.flush()")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", noisy)
    result = SubprocessRunner(output_limit=1024).run(call())
    assert (result.kind, result.error_code, result.receipt) == ("untrusted", "process_output_limit", None)
    assert [thread for thread in threading.enumerate() if thread.name.startswith("trainlab-reader-")] == readers_before

    tree = tmp_path / "tree"; child_pid = tmp_path / "child.pid"
    _script(tree, "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']); open(" + repr(str(child_pid)) + ",'w').write(str(child.pid)); time.sleep(30)")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", tree)
    runner_module._TIMEOUTS["foundation"]["status"] = 1
    started = time.monotonic(); result = SubprocessRunner(grace_seconds=1).run(call())
    assert result.kind == "timeout_unknown" and time.monotonic() - started < 5
    pid = int(child_pid.read_text())
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if not process_is_running(pid):
            break
        time.sleep(0.05)
    else: pytest.fail("orphaned_grandchild_survived_process_group_cleanup")
    assert [thread for thread in threading.enumerate() if thread.name.startswith("trainlab-reader-")] == readers_before


def test_normal_parent_exit_with_pipe_inheriting_grandchild_is_reclaimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    child_pid = tmp_path / "normal-child.pid"; tree = tmp_path / "normal-tree"
    _script(tree, "import subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']); open(" + repr(str(child_pid)) + ",'w').write(str(child.pid))")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", tree)
    result = SubprocessRunner(grace_seconds=1).run(call())
    assert result.kind == "untrusted"
    pid = int(child_pid.read_text()); until = time.monotonic() + 3
    while time.monotonic() < until:
        if not process_is_running(pid):
            break
        time.sleep(0.05)
    else: pytest.fail("normal_parent_left_pipe_inheriting_grandchild")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_each_stream_limit_leaves_no_named_reader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stream: str) -> None:
    script = tmp_path / f"limit-{stream}"
    _script(script, f"import sys; sys.{stream}.write('x'*200000); sys.{stream}.flush()")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", script)
    before = [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")]
    assert SubprocessRunner(output_limit=1024).run(call()).error_code == "process_output_limit"
    assert [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")] == before


@pytest.mark.parametrize("payload,expected", [(json.dumps(receipt()), "accepted"), ("not-json", "untrusted")])
def test_real_normal_exit_paths_leave_no_named_reader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str, expected: str) -> None:
    script = tmp_path / "normal"; _script(script, "print(" + repr(payload) + ")")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", script)
    before = [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")]
    assert SubprocessRunner().run(call()).kind == expected
    assert [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")] == before


def test_real_timeout_leaves_no_named_reader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "timeout"; _script(script, "import time; time.sleep(30)")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", script); runner_module._TIMEOUTS["foundation"]["status"] = 1
    before = [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")]
    assert SubprocessRunner(grace_seconds=1).run(call()).kind == "timeout_unknown"
    assert [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")] == before


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_grandchild_inheriting_one_stream_is_reclaimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stream: str) -> None:
    pid_file = tmp_path / f"pid-{stream}"; script = tmp_path / f"tree-{stream}"
    _script(script, "import subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'], " + stream + "=sys." + stream + "); open(" + repr(str(pid_file)) + ",'w').write(str(child.pid))")
    monkeypatch.setattr(runner_module, "_EXECUTABLE", script)
    before = [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")]
    assert SubprocessRunner(grace_seconds=1).run(call()).kind == "untrusted"
    pid = int(pid_file.read_text()); until = time.monotonic() + 3
    while time.monotonic() < until:
        if not process_is_running(pid):
            break
        time.sleep(.05)
    else: pytest.fail("inherited_stream_grandchild_survived")
    assert [item for item in threading.enumerate() if item.name.startswith("trainlab-reader-")] == before


# These are deliberately exercised through ``run`` instead of calling _argv or
# _validate_receipt directly.  The child is an offline executable: it records
# the actual boundary it received and emits only the supplied JSON receipt.
def _every_allowlisted_call() -> tuple[DownstreamCall, ...]:
    return (
        *(DownstreamCall("foundation", mode, "foundation-1", None) for mode in ("init", "status", "verify")),
        DownstreamCall("garmin", "full", "garmin-full-1", None, health_from_local_date="2026-07-23", through_local_date="2026-07-24"),
        DownstreamCall("garmin", "incremental", "garmin-incremental-1", None, through_local_date="2026-07-24"),
        DownstreamCall("garmin", "snapshot", "garmin-snapshot-1", None, snapshot_local_date="2026-07-24"),
        DownstreamCall("garmin", "repair", "garmin-repair-1", None, health_from_local_date="2026-07-23", through_local_date="2026-07-24", resource_kinds=("activities",), activity_ids=("activity-1",), repair_strategy="reconcile"),
        DownstreamCall("garmin", "audit", "garmin-audit-1", None, health_from_local_date="2026-07-23", through_local_date="2026-07-24"),
        DownstreamCall("garmin", "status", "garmin-status-1", None),
        DownstreamCall("analysis", "daily", "analysis-daily-1", None, subject_id="subject-1", summary_local_date="2026-07-23", advice_local_date="2026-07-24"),
        DownstreamCall("analysis", "weekly", "analysis-weekly-1", None, subject_id="subject-1", as_of_local_date="2026-07-24"),
        DownstreamCall("analysis", "revise_plan", "analysis-revision-1", None, subject_id="subject-1", plan_id="7", reason_event_id="9", effective_local_date="2026-07-24"),
        DownstreamCall("analysis", "retry_delivery", "analysis-retry-1", None, subject_id="subject-1", delivery_id="1"),
        DownstreamCall("analysis", "reconcile_delivery", "analysis-reconcile-1", None, subject_id="subject-1", delivery_id="1"),
        DownstreamCall("mail", "run", "mail-run-1", None, subject_id=1, max_items=2, deadline_seconds=30),
        DownstreamCall("mail", "poll", "mail-poll-1", None, subject_id=1, max_threads=2),
        DownstreamCall("mail", "process", "mail-process-1", None, subject_id=1, mail_message_id="message-1", dependency_analysis_artifact_ids=("artifact-1",), regeneration_reason_code="operator_request"),
        DownstreamCall("mail", "deliver_response", "mail-deliver-1", None, subject_id=1, mail_response_artifact_id="response-1"),
        DownstreamCall("mail", "reconcile", "mail-reconcile-1", None, subject_id=1, delivery_id="mail-delivery-1"),
        DownstreamCall("mail", "status", "mail-status-1", None, subject_id=1, run_key="mail:1:process:mail-process-1", mail_message_id="message-1"),
    )


def _offline_receipt_for(call: DownstreamCall, status: str) -> dict[str, object]:
    if call.layer == "foundation":
        return receipt(mode=call.mode, invocation_id=call.invocation_id, status=status)
    value = _layer_fixture(call.layer, "daily" if call.layer == "analysis" else "incremental" if call.layer == "garmin" else "run")
    value.update(mode=call.mode, status=status)
    if call.layer == "garmin":
        requested = {"from": call.health_from_local_date, "through": call.through_local_date}
        if call.snapshot_local_date is not None:
            requested = {"from": call.snapshot_local_date, "through": call.snapshot_local_date}
        value.update(requested_range=requested, effective_range=requested)
        return value
    if call.layer == "analysis":
        from trainlab.analysis.contracts import AnalysisRequest, build_run_key

        request = AnalysisRequest(
            mode=call.mode, subject_id=str(call.subject_id), invocation_id=call.invocation_id,
            requested_at_utc="2026-07-24T00:00:00Z", run_key=call.run_key,
            summary_local_date=call.summary_local_date, advice_local_date=call.advice_local_date,
            as_of_local_date=call.as_of_local_date, plan_id=call.plan_id,
            reason_event_id=call.reason_event_id, effective_local_date=call.effective_local_date,
            artifact_id=call.artifact_id, delivery_id=call.delivery_id,
            regeneration_reason_code=call.regeneration_reason_code,
        )
        value.update(invocation_id=call.invocation_id, run_key=build_run_key(request))
        periods: dict[str, object] = {"summary": None, "advice": None, "review": None, "plan": None}
        if call.mode == "daily":
            for name, target in (("summary", call.summary_local_date), ("advice", call.advice_local_date)):
                if target is not None: periods[name] = {"start_local_date": target, "end_local_date": target}
        elif call.mode == "weekly":
            periods.update(review={"start_local_date": "2026-07-17", "end_local_date": "2026-07-23"}, plan={"start_local_date": "2026-07-24", "end_local_date": "2026-07-30"})
        elif call.mode == "revise_plan":
            periods["plan"] = {"start_local_date": call.effective_local_date, "end_local_date": "2026-07-30"}
        value["target_periods"] = periods
        if call.mode == "regenerate": value["artifact_ids"] = ["regenerated-artifact-1"]
        if call.delivery_id is not None: value["delivery"] = {**value["delivery"], "delivery_id": call.delivery_id}
        return value
    # Use the public request builder to obtain the lower-layer stable key.
    from trainlab.mail_agent.contracts import MailRequest
    request = MailRequest(
        mode=call.mode, subject_id=int(call.subject_id), invocation_id=str(call.invocation_id), requested_at_utc="2026-07-24T00:00:00Z",
        mail_message_ids=(call.mail_message_id,) if call.mail_message_id else (),
        mail_response_artifact_ids=(call.mail_response_artifact_id,) if call.mail_response_artifact_id else (),
        mail_delivery_ids=(call.delivery_id,) if call.delivery_id else (),
        dependency_analysis_artifact_ids=call.dependency_analysis_artifact_ids,
        regeneration_reason_code=call.regeneration_reason_code, run_key=call.run_key,
    )
    value.update(invocation_id=call.invocation_id, run_key=call.run_key if call.mode == "status" and call.run_key else request.stable_run_key)
    if status in runner_module._PROGRESS_STATUSES:
        if call.mail_message_id: value["processed_message_ids"] = [call.mail_message_id]
        if call.mail_response_artifact_id: value["mail_response_artifact_ids"] = [call.mail_response_artifact_id]
        if call.delivery_id: value["mail_delivery_ids"] = [call.delivery_id]
    else:
        value.update(processed_message_ids=[], mail_response_artifact_ids=[], mail_delivery_ids=[])
    return value


@pytest.mark.parametrize("downstream_call", _every_allowlisted_call(), ids=lambda item: f"{item.layer}-{item.mode}")
def test_every_allowlisted_mode_runs_offline_with_fixed_boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downstream_call: DownstreamCall) -> None:
    log = tmp_path / "child-boundary.json"
    child = tmp_path / "offline-child"
    for status, exit_code in runner_module._EXIT_BY_LAYER[downstream_call.layer].items():
        payload = _offline_receipt_for(downstream_call, status)
        _script(child, "import json,os,sys; open(" + repr(str(log)) + ",'w').write(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),'env':dict(os.environ)},sort_keys=True)); print(" + repr(json.dumps(payload)) + "); raise SystemExit(" + str(exit_code) + ")")
        if downstream_call.layer in {"foundation", "garmin", "analysis"}:
            monkeypatch.setattr(runner_module, "_EXECUTABLE", child)
        else:
            monkeypatch.setattr(runner_module, "_PYTHON", child)
        result = SubprocessRunner().run(downstream_call)
        assert result.kind == "accepted"
        assert result.exit_code == exit_code
        assert result.receipt is not None and result.receipt["status"] == status
        boundary = json.loads(log.read_text())
        assert boundary["argv"] == list(runner_module._argv(downstream_call))[1:]
        assert boundary["cwd"] == str(runner_module._ROOT)
        # macOS's interpreter may add ``__CF_USER_TEXT_ENCODING`` after
        # execve.  Verify the runner's supplied environment exactly and that
        # no inherited credential/home environment crossed the boundary.
        assert {name: boundary["env"][name] for name in runner_module._ENV} == runner_module._ENV
        assert boundary["env"]["PATH"] == runner_module.bounded_runtime_path()
        assert not ({"HOME", "USER", "LOGNAME", "SHELL", "VIRTUAL_ENV", "PYTHONPATH", "TOKEN", "PASSWORD"} & set(boundary["env"]))


@pytest.mark.parametrize(("status", "processed", "expected"), [
    ("succeeded", ["message-1", "message-1"], "receipt_message_identity_invalid"),
    ("partial", ["message-2"], "receipt_message_mismatch"),
    ("failed", [], None),
    ("deferred", [], None),
    ("lock_busy", [], None),
    ("auth_required", [], None),
])
def test_mail_business_identifiers_are_bounded_only_when_progress_is_claimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str, processed: list[str], expected: str | None) -> None:
    request = DownstreamCall("mail", "process", "mail-process-1", None, subject_id=1, mail_message_id="message-1")
    payload = _offline_receipt_for(request, status)
    payload["processed_message_ids"] = processed
    child = tmp_path / "malicious-mail-child"
    _script(child, "import sys; print(" + repr(json.dumps(payload)) + "); raise SystemExit(" + str(runner_module._EXIT_BY_LAYER["mail"][status]) + ")")
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    if expected is None:
        assert result.kind == "accepted"
    else:
        assert (result.kind, result.error_code) == ("untrusted", expected)


@pytest.mark.parametrize("status", sorted(runner_module._FAILURE_STATUSES))
@pytest.mark.parametrize("field", ["processed_message_ids", "mail_response_artifact_ids", "mail_delivery_ids"])
def test_mail_failure_receipts_reject_every_nonempty_business_identifier_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    field: str,
) -> None:
    request = DownstreamCall("mail", "run", "mail-run-1", None, subject_id=1)
    payload = _offline_receipt_for(request, status)
    payload[field] = ["out-of-request-1"]
    child = tmp_path / "failure-id-child"
    _raw_child(child, json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"][status])
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert (result.kind, result.error_code, result.exit_code) == (
        "untrusted", "receipt_failure_identity_invalid", runner_module._EXIT_BY_LAYER["mail"][status],
    )


@pytest.mark.parametrize("field", ["processed_message_ids", "mail_response_artifact_ids", "mail_delivery_ids"])
@pytest.mark.parametrize(("identifiers", "error"), [
    (["item-1", "item-1"], "receipt_message_identity_invalid"),
    ([""], "receipt_message_identity_invalid"),
    (["item-1"] * 65, "receipt_message_identity_invalid"),
])
def test_mail_progress_receipts_bound_format_count_and_uniqueness_for_every_id_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    identifiers: list[str],
    error: str,
) -> None:
    request = DownstreamCall("mail", "run", "mail-run-1", None, subject_id=1)
    payload = _offline_receipt_for(request, "partial")
    payload[field] = identifiers
    child = tmp_path / "progress-id-child"
    _raw_child(child, json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"]["partial"])
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert (result.kind, result.error_code) == ("untrusted", error)


@pytest.mark.parametrize(("mode", "field", "kwargs", "foreign"), [
    ("process", "processed_message_ids", {"mail_message_id": "message-1"}, "message-2"),
    ("deliver_response", "mail_response_artifact_ids", {"mail_response_artifact_id": "response-1"}, "response-2"),
    ("reconcile", "mail_delivery_ids", {"delivery_id": "delivery-1"}, "delivery-2"),
])
def test_mail_targeted_progress_rejects_foreign_id_in_every_target_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    field: str,
    kwargs: dict[str, str],
    foreign: str,
) -> None:
    request = DownstreamCall("mail", mode, f"mail-{mode}-1", None, subject_id=1, **kwargs)
    payload = _offline_receipt_for(request, "succeeded")
    payload[field] = [foreign]
    child = tmp_path / "foreign-id-child"
    _raw_child(child, json.dumps(payload).encode())
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert (result.kind, result.error_code) == ("untrusted", "receipt_message_mismatch")


@pytest.mark.parametrize("status", sorted(runner_module._PROGRESS_STATUSES))
@pytest.mark.parametrize(("mode", "field", "kwargs"), [
    ("process", "processed_message_ids", {"mail_message_id": "message-1"}),
    ("deliver_response", "mail_response_artifact_ids", {"mail_response_artifact_id": "response-1"}),
    ("reconcile", "mail_delivery_ids", {"delivery_id": "delivery-1"}),
])
def test_mail_targeted_progress_requires_exact_single_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    mode: str,
    field: str,
    kwargs: dict[str, str],
) -> None:
    request = DownstreamCall("mail", mode, f"mail-{mode}-1", None, subject_id=1, **kwargs)
    payload = _offline_receipt_for(request, status)
    payload[field] = []
    child = tmp_path / "missing-target-child"
    _raw_child(child, json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"][status])
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert (result.kind, result.error_code) == ("untrusted", "receipt_message_mismatch")


@pytest.mark.parametrize("status", sorted(runner_module._PROGRESS_STATUSES))
@pytest.mark.parametrize(("mode", "field", "kwargs", "created"), [
    ("process", "mail_response_artifact_ids", {"mail_message_id": "message-1"}, "response-created-1"),
    ("deliver_response", "mail_delivery_ids", {"mail_response_artifact_id": "response-1"}, "delivery-created-1"),
    ("reconcile", "mail_response_artifact_ids", {"delivery_id": "delivery-1"}, "response-existing-1"),
])
def test_mail_targeted_progress_allows_bounded_unrelated_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    mode: str,
    field: str,
    kwargs: dict[str, str],
    created: str,
) -> None:
    request = DownstreamCall("mail", mode, f"mail-{mode}-1", None, subject_id=1, **kwargs)
    payload = _offline_receipt_for(request, status)
    payload[field] = [created]
    child = tmp_path / "unrelated-output-child"
    _raw_child(child, json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"][status])
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert result.kind == "accepted"


@pytest.mark.parametrize("status", sorted(runner_module._PROGRESS_STATUSES))
def test_mail_reconcile_without_delivery_id_is_rejected_before_process_start(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    request = DownstreamCall("mail", "reconcile", "mail-reconcile-missing-1", None, subject_id=1)
    payload = _offline_receipt_for(request, status)
    captured = install(
        monkeypatch,
        FakeProcess(json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"][status]),
    )
    with pytest.raises(ValueError, match="subprocess_field_required"):
        SubprocessRunner().run(request)
    assert captured == {}


@pytest.mark.parametrize("status", sorted(runner_module._PROGRESS_STATUSES))
def test_mail_reconcile_exact_delivery_runs_with_fixed_argv_and_accepts_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
) -> None:
    request = DownstreamCall(
        "mail", "reconcile", "mail-reconcile-exact-1", None,
        subject_id=1, delivery_id="delivery-1",
    )
    payload = _offline_receipt_for(request, status)
    log = tmp_path / "reconcile-argv.json"
    child = tmp_path / "reconcile-child"
    _script(
        child,
        "import json,sys;open(" + repr(str(log)) + ",'w').write(json.dumps(sys.argv[1:]));"
        "print(" + repr(json.dumps(payload)) + ");raise SystemExit("
        + str(runner_module._EXIT_BY_LAYER["mail"][status]) + ")",
    )
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert result.kind == "accepted"
    assert json.loads(log.read_text()) == [
        "-m", "trainlab.mail_agent.cli", "--subject-id", "1",
        "--invocation-id", "mail-reconcile-exact-1",
        "reconcile", "--delivery-id", "delivery-1",
    ]


@pytest.mark.parametrize("status", sorted(runner_module._FAILURE_STATUSES))
def test_mail_reconcile_failure_receipts_require_empty_business_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
) -> None:
    request = DownstreamCall(
        "mail", "reconcile", "mail-reconcile-failure-1", None,
        subject_id=1, delivery_id="delivery-1",
    )
    payload = _offline_receipt_for(request, status)
    assert payload["processed_message_ids"] == []
    assert payload["mail_response_artifact_ids"] == []
    assert payload["mail_delivery_ids"] == []
    child = tmp_path / "reconcile-failure-child"
    _raw_child(
        child,
        json.dumps(payload).encode(),
        runner_module._EXIT_BY_LAYER["mail"][status],
    )
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert result.kind == "accepted"


@pytest.mark.parametrize("mode", ["run", "poll"])
def test_mail_discovery_progress_accepts_bounded_new_ids_in_all_business_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    request = DownstreamCall("mail", mode, f"mail-{mode}-1", None, subject_id=1)
    payload = _offline_receipt_for(request, "partial")
    payload.update(
        processed_message_ids=["message-1"],
        mail_response_artifact_ids=["response-1"],
        mail_delivery_ids=["delivery-1"],
    )
    child = tmp_path / "new-id-child"
    _raw_child(child, json.dumps(payload).encode(), runner_module._EXIT_BY_LAYER["mail"]["partial"])
    monkeypatch.setattr(runner_module, "_PYTHON", child)
    result = SubprocessRunner().run(request)
    assert result.kind == "accepted"


def test_provider_timeouts_are_fixed_and_cover_incremental_runtime() -> None:
    assert runner_module._TIMEOUTS["garmin"] == {
        "full": 86_400,
        "incremental": 3_600,
        "snapshot": 900,
        "repair": 3_600,
        "audit": 1_800,
        "status": 60,
    }
    assert set(runner_module._TIMEOUTS) == {
        "foundation", "garmin", "analysis", "mail",
    }
