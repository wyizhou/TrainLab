"""Offline fault-matrix acceptance tests for L2-07 request control."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from garminconnect import Garmin

from trainlab import garmin_client
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    SyncRequest,
    classify_garmin_error,
)
from trainlab.garmin_client import GarminConnectTransport, TokenStore

from .garmin_fakes import FakeGarminTransport


class QuietTransport(FakeGarminTransport):
    """Fixture transport: only explicitly configured health calls occur."""

    def list_activities(self, start: str | None, through: str | None):
        self._fault("activities")
        return []


def _tool(
    tmp_path: Path,
    *,
    faults: dict[str, GarminError | list[GarminError]] | None = None,
    resource_interval: int = 0,
    resource_interval_jitter: int = 0,
    max_attempts: int = 5,
    inline_retry_after_max_seconds: int = 120,
    rate_limit_fallback_seconds: int = 900,
):
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/receipt.json",
        root / "state/locks/foundation.lock",
    )
    FoundationTool(foundation).execute(
        FoundationRequest("init", "fixture", "2026-01-01T00:00:00Z")
    )
    config = GarminConfig(
        foundation.database_path,
        foundation.raw_root,
        foundation.state_root,
        "2026-04-15",
        request_min_interval_ms=resource_interval,
        request_interval_jitter_ms=resource_interval_jitter,
        max_attempts=max_attempts,
        inline_retry_after_max_seconds=inline_retry_after_max_seconds,
        rate_limit_fallback_seconds=rate_limit_fallback_seconds,
    )
    # This control-path suite never enumerates activities, so its fake only
    # needs an opaque value for the unused activity-original method.
    transport = QuietTransport(b"synthetic-unused-fit", faults=faults or {})
    sleeps: list[float] = []
    tool = GarminCollectionTool(
        config,
        transport,
        sleep=sleeps.append,
        clock=lambda: datetime(2026, 4, 17),
        monotonic=lambda: 100.0,
        rng=lambda: 0.25,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport, sleeps


def _item_row(config: GarminConfig, invocation: str):
    with sqlite3.connect(config.database_path) as conn:
        return conn.execute(
            """SELECT i.status,i.attempt_count,i.http_status,i.error_code,i.next_retry_at_utc
               FROM garmin_sync_items i JOIN garmin_sync_runs r ON r.id=i.garmin_sync_run_id
               WHERE r.invocation_id=? AND i.stage='fetch' ORDER BY i.id DESC LIMIT 1""",
            (invocation,),
        ).fetchone()


def _resource_request(resources: tuple[str, ...], invocation: str) -> SyncRequest:
    # Public request schema reserves resource filters for targeted repair.
    return SyncRequest(
        "repair",
        through_local_date="2026-04-15",
        resource_kinds=resources,
        repair_strategy="refetch",
        invocation_id=invocation,
    )


class _PacingClock:
    def __init__(self, now: float = 100.0, *, early_sleep: bool = False) -> None:
        self.now = now
        self.early_sleep = early_sleep
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += (
            seconds / 2 if self.early_sleep and len(self.sleeps) == 1 else seconds
        )

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _pacing_tool(tmp_path: Path, clock: _PacingClock):
    config = GarminConfig(
        tmp_path / "data.db",
        tmp_path / "raw",
        tmp_path / "state",
        "2026-04-15",
        request_min_interval_ms=1_500,
    )
    tool = GarminCollectionTool(config)
    tool.monotonic = clock.monotonic
    tool.sleep = clock.sleep
    tool.rng = lambda: 0.0
    return tool


def test_normal_calls_use_bounded_pseudorandom_intervals(tmp_path: Path) -> None:
    clock = _PacingClock()
    config = GarminConfig(
        tmp_path / "data.db",
        tmp_path / "raw",
        tmp_path / "state",
        "2026-04-15",
        request_min_interval_ms=1_000,
        request_interval_jitter_ms=2_000,
    )
    tool = GarminCollectionTool(config, sleep=clock.sleep, monotonic=clock.monotonic)
    random_values = iter((0.25, 0.75))
    tool.rng = lambda: next(random_values)

    assert tool._call(lambda: "first") == "first"
    assert tool._call(lambda: "second") == "second"
    assert tool._call(lambda: "third") == "third"

    assert clock.sleeps == [pytest.approx(1.5), pytest.approx(2.5)]


def test_provider_entry_pacing_first_call_and_exact_minimum(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []

    def provider() -> None:
        entries.append(clock.monotonic())

    tool._call(provider)
    clock.advance(1.5)
    tool._call(provider)

    assert entries == [100.0, 101.5]
    assert clock.sleeps == []


def test_provider_entry_pacing_just_below_minimum(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []

    def provider() -> None:
        entries.append(clock.monotonic())

    tool._call(provider)
    clock.advance(1.499)
    tool._call(provider)

    assert entries[1] - entries[0] == pytest.approx(1.5)
    assert clock.sleeps == [pytest.approx(0.001)]


def test_provider_entry_pacing_counts_pre_call_persistence(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []
    tool.repo.item = lambda *args: clock.advance(0.75)

    def provider() -> None:
        entries.append(clock.monotonic())

    tool._call(provider, conn=object(), run=1, resource="steps", key="day")
    clock.advance(0.75)
    tool._call(provider, conn=object(), run=1, resource="steps", key="day")

    assert entries[1] - entries[0] == pytest.approx(1.5)
    assert clock.sleeps == []


def test_provider_entry_pacing_rechecks_early_sleep_return(tmp_path: Path) -> None:
    clock = _PacingClock(early_sleep=True)
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []

    def provider() -> None:
        entries.append(clock.monotonic())

    tool._call(provider)
    tool._call(provider)

    assert entries[1] - entries[0] == pytest.approx(1.5)
    assert clock.sleeps == [pytest.approx(1.5), pytest.approx(0.75)]


def test_provider_entry_pacing_includes_retry_calls(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []

    def provider() -> str:
        entries.append(clock.monotonic())
        if len(entries) == 1:
            raise GarminError("timeout")
        return "ok"

    assert tool._call(provider) == "ok"
    assert entries[1] - entries[0] >= 1.5
    assert clock.sleeps == [pytest.approx(2.0)]


def test_provider_entry_pacing_allows_long_provider_calls(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []

    def provider() -> None:
        entries.append(clock.monotonic())
        clock.advance(2.0)

    tool._call(provider)
    tool._call(provider)

    assert entries[1] - entries[0] == pytest.approx(2.0)
    assert clock.sleeps == []


def test_live_acceptance_hard_stops_401_without_login_or_retry(tmp_path: Path) -> None:
    tool = _pacing_tool(tmp_path, _PacingClock())
    tool._live_acceptance_no_retry = True
    calls: list[str] = []
    tool._transport = lambda: type(
        "ForbiddenRefresh", (), {"login": lambda _self: calls.append("login")}
    )()

    def provider() -> None:
        calls.append("provider")
        raise GarminError("expired", http_status=401)

    with pytest.raises(GarminError, match="401_blocked"):
        tool._call(provider)
    assert calls == ["provider"]


def test_v4_driver_import_and_noarg_are_inert_with_exact_manual_gate() -> None:
    driver = (
        Path("/home/dev/Project/state/test-tmp/garmin-live-acceptance")
        / "v4-a1-20260808-n14"
        / "driver.py"
    )
    source = driver.read_text(encoding="utf-8")
    assert 'arguments != ["--execute-once"]' in source
    assert "subprocess" not in source.split("\n\n", 1)[1]
    assert "threading" not in source
    assert "multiprocessing" not in source
    namespace = {"__name__": "v4_driver_test", "__file__": str(driver)}
    exec(compile(source, str(driver), "exec"), namespace)
    assert namespace["main"]([]) == 0
    assert namespace["main"](["--wrong"]) == 2
    namespace["_verify_control_plane"]()
    namespace["_verify_t12_edge_input"]()


def test_v4_driver_low_level_allowlist_counts_only_reviewed_entries() -> None:
    driver = (
        Path("/home/dev/Project/state/test-tmp/garmin-live-acceptance")
        / "v4-a1-20260808-n14"
        / "driver.py"
    )
    namespace = {"__name__": "v4_driver_gate_test", "__file__": str(driver)}
    exec(compile(driver.read_text(encoding="utf-8"), str(driver), "exec"), namespace)

    class Response:
        status_code = 200

    class Session:
        def request(self, *_args, **_kwargs):
            return Response()

        def get(self, *_args, **_kwargs):
            return Response()

        def post(self, *_args, **_kwargs):
            return Response()

    class Client:
        _di_token_url = "https://di.invalid/token"
        _connectapi = "https://api.invalid"

        def __init__(self) -> None:
            self._api_session = Session()
            self.cs = Session()

        def _http_post(self, *_args, **_kwargs):
            return Response()

        def _run_request(self, method, path, **_kwargs):
            return self._api_session.request(
                method, f"{self._connectapi}/{path.lstrip('/')}"
            )

        def _refresh_di_token(self):
            return self._http_post(self._di_token_url)

        def dump(self, *_args, **_kwargs):
            raise AssertionError("must be replaced")

        def _refresh_session(self):
            raise AssertionError("must be replaced")

    client = Client()
    facade = type("Facade", (), {})()
    gate = namespace["_ProviderGate"](client, 0)
    gate.install(facade)
    gate.phase = "refresh"
    assert client._refresh_di_token().status_code == 200
    with pytest.raises(namespace["LiveGateError"]):
        client._http_post("https://di.invalid/token")
    gate.phase = "profiles"
    assert (
        client._run_request("GET", "/userprofile-service/socialProfile").status_code
        == 200
    )
    assert (
        client._run_request(
            "GET", "/userprofile-service/userprofile/user-settings"
        ).status_code
        == 200
    )
    with pytest.raises(namespace["LiveGateError"], match="profile_retry_blocked"):
        client._run_request("GET", "/userprofile-service/socialProfile")
    with pytest.raises(namespace["LiveGateError"], match="run_request_blocked"):
        client._run_request("GET", "/unreviewed")
    with pytest.raises(namespace["LiveGateError"]):
        client.cs.get("https://sso.invalid")
    with pytest.raises(namespace["LiveGateError"]):
        client.dump("forbidden")
    assert gate.counts["refresh_provider_entry_count"] == 1
    assert gate.counts["social_profile_http_count"] == 1
    assert gate.counts["user_settings_http_count"] == 1
    assert gate.counts["cached_identity_http_count"] == 0
    assert gate.counts["auth_profile_retry_attempt_count"] == 1
    assert gate.counts["unreviewed_profile_attempt_count"] == 1
    assert gate.counts["credential_fallback_attempt_count"] == 1
    assert gate.counts["library_token_dump_attempt_count"] == 1


def test_v4_driver_fake_end_to_end_foundation_and_drift_plumbing(
    tmp_path: Path,
) -> None:
    """Exercise driver-owned gates with fixtures only; no execute-once path."""
    driver = (
        Path("/home/dev/Project/state/test-tmp/garmin-live-acceptance")
        / "v4-a1-20260808-n14"
        / "driver.py"
    )
    namespace = {"__name__": "v4_driver_dry_test", "__file__": str(driver)}
    exec(compile(driver.read_text(encoding="utf-8"), str(driver), "exec"), namespace)

    root = tmp_path / "isolated"
    root.mkdir(mode=0o700)
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "ready.json",
        root / "state" / "locks" / "foundation.lock",
        tmp_path,
    )
    foundation_tool = FoundationTool(foundation)
    init = foundation_tool.execute(
        FoundationRequest("init", "driver-dry-init", "2026-08-08T00:00:00Z")
    )
    status = foundation_tool.execute(
        FoundationRequest("status", "driver-dry-status", "2026-08-08T00:00:00Z")
    )
    namespace["_require_foundation_ready"](init, ("initialized", "already_initialized"))
    namespace["_require_foundation_ready"](status, ("ready",))
    with pytest.raises(namespace["LiveGateError"]):
        namespace["_require_foundation_ready"](
            SimpleNamespace(status="failed", ready=False), ("ready",)
        )

    production_db = tmp_path / "production.db"
    with sqlite3.connect(production_db) as connection:
        connection.execute("CREATE TABLE fixture (id INTEGER PRIMARY KEY)")
    production_raw = tmp_path / "production-raw"
    production_raw.mkdir()
    production = SimpleNamespace(
        database_path=production_db,
        raw_root=production_raw,
        state_root=tmp_path / "production-state",
    )
    assert namespace["_production_quiescence_snapshot"](
        production, foundation_tool
    ) == namespace["_production_quiescence_snapshot"](production, foundation_tool)
    (production.state_root / "locks").mkdir(parents=True)
    (production.state_root / "locks" / "garmin.lock").write_text("fixture")
    with pytest.raises(namespace["LiveGateError"], match="production_not_quiescent"):
        namespace["_production_quiescence_snapshot"](production, foundation_tool)

    _config, sync_tool, _transport, _sleeps = _tool(tmp_path / "sync-receipt")
    sync_receipt = sync_tool.execute(SyncRequest("auth", invocation_id="driver-dry"))
    assert namespace["_require_sync_receipt"](sync_tool, sync_receipt) is sync_receipt
    with pytest.raises(namespace["LiveGateError"], match="sync_receipt_invalid"):
        namespace["_require_sync_receipt"](sync_tool, object())

    def blocked_by_gate() -> None:
        raise namespace["LiveGateError"]("blocked")

    with pytest.raises(namespace["LiveGateError"], match="blocked"):
        namespace["_closed_adapter_invoke"](
            lambda _error: AssertionError("must not translate gate failures"),
            blocked_by_gate,
        )

    key = ("garmin", "personal_records", "record")
    first = {
        "raw_ids": {1},
        "history": {key: [(1, 1, "a" * 64, 1, 1)]},
        "current": {key: [(1, 1, "a" * 64, 1, 1)]},
        "raw_tree_digest": "b" * 64,
    }
    second = {
        "raw_ids": {1},
        "history": {key: [(1, 1, "a" * 64, 1, 1)]},
        "current": {key: [(1, 1, "a" * 64, 1, 1)]},
        "raw_tree_digest": "b" * 64,
    }
    drift = namespace["_drift_evidence"](first, second)
    assert drift == {
        "stable_repeat_count": 1,
        "changed_payload_count": 0,
        "stable_repeat_violation_count": 0,
        "changed_revision_violation_count": 0,
        "changed_current_provenance_violation_count": 0,
    }
    partitions = namespace["_observed_partitions"]([], [], 1_500_000_000, drift)
    assert partitions["idempotence"] == [
        "incremental-through-2026-08-06",
        "snapshot-2026-08-07",
        "audit-only-2026-08-06",
        "stable-repeat-no-new-object",
    ]


def test_v4_driver_drift_accepts_only_real_demote_promote_transition() -> None:
    driver = (
        Path("/home/dev/Project/state/test-tmp/garmin-live-acceptance")
        / "v4-a1-20260808-n14"
        / "driver.py"
    )
    namespace = {"__name__": "v4_driver_drift_test", "__file__": str(driver)}
    exec(compile(driver.read_text(encoding="utf-8"), str(driver), "exec"), namespace)
    key = ("garmin", "personal_records", "record")
    old = (1, 1, "a" * 64, 10, 1)
    demoted = (1, 1, "a" * 64, 10, 0)
    promoted = (2, 2, "b" * 64, 11, 1)

    def snapshot(
        history: list[tuple[int, int, str, int, int]], raw_ids: set[int], tree: str
    ) -> dict[str, object]:
        return {
            "raw_ids": raw_ids,
            "history": {key: history},
            "current": {key: [entry for entry in history if entry[4] == 1]},
            "raw_tree_digest": tree,
        }

    first = snapshot([old], {10}, "c" * 64)
    second = snapshot([demoted, promoted], {10, 11}, "d" * 64)
    assert namespace["_drift_evidence"](first, second) == {
        "stable_repeat_count": 0,
        "changed_payload_count": 1,
        "stable_repeat_violation_count": 0,
        "changed_revision_violation_count": 0,
        "changed_current_provenance_violation_count": 0,
    }

    invalid_transitions = (
        snapshot([demoted, (2, 3, "b" * 64, 11, 1)], {10, 11}, "d" * 64),
        snapshot([old, promoted], {10, 11}, "d" * 64),
        snapshot([demoted, (2, 2, "b" * 64, 10, 1)], {10}, "d" * 64),
        snapshot([demoted, promoted], {10, 11}, "c" * 64),
    )
    for invalid in invalid_transitions:
        evidence = namespace["_drift_evidence"](first, invalid)
        assert (
            evidence["changed_revision_violation_count"]
            + evidence["changed_current_provenance_violation_count"]
            > 0
        )


def test_network_408_and_temporary_5xx_retry_with_jitter_and_durable_attempts(
    tmp_path: Path,
) -> None:
    faults = {
        "health:heart_rates": [
            GarminError("dns"),
            GarminError("http_408", http_status=408),
            GarminError("http_503", http_status=503),
        ]
    }
    config, tool, transport, sleeps = _tool(tmp_path, faults=faults)
    result = tool.execute(_resource_request(("heart_rates",), "retry"))
    assert result.status == "succeeded" and result.counts["empty"] == 1
    assert _item_row(config, "retry") == ("empty", 4, None, None, None)
    assert sleeps == [2.25, 4.25, 8.25]
    assert transport.calls.count("health:heart_rates") == 4


def test_short_429_waits_inline_then_succeeds_and_long_429_defers_with_cooldown(
    tmp_path: Path,
) -> None:
    config, tool, transport, sleeps = _tool(
        tmp_path,
        faults={
            "health:heart_rates": [
                GarminError("limited", http_status=429, retry_after=2)
            ]
        },
    )
    short = tool.execute(_resource_request(("heart_rates",), "short"))
    assert short.status == "succeeded"
    assert sleeps == [2.0]
    assert _item_row(config, "short") == ("empty", 2, None, None, None)

    config, tool, transport, _ = _tool(
        tmp_path / "long",
        faults={
            "health:heart_rates": GarminError(
                "limited", http_status=429, retry_after=121
            )
        },
    )
    first = tool.execute(_resource_request(("heart_rates",), "long-one"))
    calls = transport.calls.count("health:heart_rates")
    assert first.status == "deferred" and first.next_retry_at_utc
    assert _item_row(config, "long-one")[0:2] == ("deferred", 1)
    second = tool.execute(_resource_request(("heart_rates",), "long-two"))
    assert (
        second.status == "deferred"
        and transport.calls.count("health:heart_rates") == calls
    )


def test_configured_429_threshold_controls_inline_retry_vs_deferred(
    tmp_path: Path,
) -> None:
    # The same Retry-After is inline at a larger configured threshold.
    _, inline, transport, sleeps = _tool(
        tmp_path / "inline",
        faults={
            "health:heart_rates": [
                GarminError("limited", http_status=429, retry_after=3)
            ]
        },
        inline_retry_after_max_seconds=3,
    )
    assert (
        inline.execute(_resource_request(("heart_rates",), "inline-threshold")).status
        == "succeeded"
    )
    assert transport.calls.count("health:heart_rates") == 2 and sleeps == [3.0]

    # Reducing the threshold changes the actual call path: no second request,
    # persisted deferred state, and no inline sleep.
    _, deferred, transport, sleeps = _tool(
        tmp_path / "deferred",
        faults={
            "health:heart_rates": GarminError("limited", http_status=429, retry_after=3)
        },
        inline_retry_after_max_seconds=2,
    )
    result = deferred.execute(_resource_request(("heart_rates",), "deferred-threshold"))
    assert result.status == "deferred" and result.next_retry_at_utc
    assert transport.calls.count("health:heart_rates") == 1 and sleeps == []


def test_429_without_retry_after_uses_configured_fallback(tmp_path: Path) -> None:
    _, tool, transport, sleeps = _tool(
        tmp_path,
        faults={"health:heart_rates": [GarminError("limited", http_status=429)]},
        inline_retry_after_max_seconds=3,
        rate_limit_fallback_seconds=3,
    )
    result = tool.execute(_resource_request(("heart_rates",), "fallback-threshold"))
    assert result.status == "succeeded"
    assert transport.calls.count("health:heart_rates") == 2
    assert sleeps == [3.0]


def test_401_refreshes_once_then_success_or_stops_all_following_network_work(
    tmp_path: Path,
) -> None:
    config, tool, transport, _ = _tool(
        tmp_path,
        faults={"health:heart_rates": [GarminError("expired", http_status=401)]},
    )
    refreshed = tool.execute(_resource_request(("heart_rates",), "refresh"))
    assert refreshed.status == "succeeded"
    assert transport.calls.count("login") == 3  # auth, sync token login, one refresh

    config, tool, transport, _ = _tool(
        tmp_path / "final",
        faults={
            "health:heart_rates": [
                GarminError("expired", http_status=401),
                GarminError("still_expired", http_status=401),
            ]
        },
    )
    final = tool.execute(_resource_request(("heart_rates", "spo2"), "final-401"))
    assert final.status == "auth_required"
    assert transport.calls.count("health:heart_rates") == 2
    assert "health:spo2" not in transport.calls
    with sqlite3.connect(config.database_path) as conn:
        assert (
            conn.execute(
                "SELECT status FROM garmin_sync_runs WHERE invocation_id='final-401'"
            ).fetchone()[0]
            == "auth_required"
        )


@pytest.mark.parametrize(
    ("resource", "error", "item_status", "receipt_status"),
    [
        ("heart_rates", GarminError("denied", http_status=403), "forbidden", "partial"),
        (
            "body_composition",
            GarminError("missing", http_status=404),
            "not_available",
            "succeeded",
        ),
        ("spo2", GarminError("missing", http_status=404), "not_available", "succeeded"),
        (
            "heart_rates",
            GarminError("bad_request", http_status=400),
            "failed",
            "partial",
        ),
    ],
)
def test_4xx_matrix_uses_catalog_404_rule_without_retry(
    tmp_path: Path,
    resource: str,
    error: GarminError,
    item_status: str,
    receipt_status: str,
) -> None:
    config, tool, transport, sleeps = _tool(
        tmp_path, faults={f"health:{resource}": error}
    )
    result = tool.execute(_resource_request((resource,), f"four-{resource}"))
    row = _item_row(config, f"four-{resource}")
    assert result.status == receipt_status and row[0] == item_status and row[1] == 1
    assert transport.calls.count(f"health:{resource}") == 1 and sleeps == []


def test_classifier_and_adapter_error_translation_are_safe_and_configuration_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert classify_garmin_error(GarminError("timeout")).status == "retry"
    assert classify_garmin_error(GarminError("x", http_status=408)).status == "retry"
    assert (
        classify_garmin_error(GarminError("x", http_status=404), allows_404=True).status
        == "not_available"
    )
    assert (
        classify_garmin_error(
            GarminError("x", http_status=404), allows_404=False
        ).status
        == "failed"
    )
    assert (
        classify_garmin_error(GarminError("secret-password", http_status=403)).status
        == "forbidden"
    )

    class Response:
        status_code = 503
        headers = {"Retry-After": "7"}

    class ProviderFailure(Exception):
        response = Response()

    translated = GarminConnectTransport._error(ProviderFailure())
    assert (translated.code, translated.http_status, translated.retry_after) == (
        "http_503",
        503,
        7,
    )
    assert (
        GarminConnectTransport._error(RuntimeError("PASSWORD_SECRET")).code
        == "provider_error"
    )

    captured: dict[str, object] = {}
    production_calls: list[tuple[str, dict[str, object]]] = []

    class Session:
        def __init__(self, name: str) -> None:
            self.name = name

        def request(self, method: str, url: str, **kwargs):
            production_calls.append((self.name, kwargs))
            return object()

    class LowClient:
        def __init__(self) -> None:
            self.cs = Session("cs")
            self._api_session = Session("api")

    class PinnedClient:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)
            self.client = LowClient()

    monkeypatch.setattr(garmin_client, "Garmin", PinnedClient)
    production = GarminConnectTransport(
        None,
        None,
        TokenStore(tmp_path / "pinned"),
        region="cn",
        request_timeout_seconds=17,
    )
    assert captured["retry_attempts"] == 0 and captured["is_cn"] is True
    production.client.client.cs.request("GET", "https://offline.invalid", timeout=999)
    production.client.client._api_session.request(
        "GET", "https://offline.invalid", timeout=999
    )
    assert production_calls == [("cs", {"timeout": 17}), ("api", {"timeout": 17})]

    # This uses the installed 0.3.6 Client structure but replaces its sessions
    # before invocation; no real request is made.  ``connectapi`` would supply
    # its own default/override without the adapter's Session wrapper.
    pinned = Garmin(None, None, retry_attempts=0).client
    calls: list[tuple[str, dict[str, object]]] = []

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    def api_request(method: str, url: str, **kwargs):
        calls.append(("api", kwargs))
        return Response()

    def sso_request(method: str, url: str, **kwargs):
        calls.append(("sso", kwargs))
        return Response()

    pinned._api_session.request = api_request
    pinned.cs.request = sso_request
    pinned.get_api_headers = lambda: {}
    bounded = GarminConnectTransport(
        None,
        None,
        TokenStore(tmp_path / "bounded"),
        client=pinned,
        request_timeout_seconds=17,
    )
    assert bounded.client.connectapi("/offline", timeout=999) == {}
    bounded.client.cs.request("GET", "https://offline.invalid", timeout=999)
    assert calls == [("api", {"headers": {}, "timeout": 17}), ("sso", {"timeout": 17})]
    with pytest.raises(ValueError, match="invalid_request_timeout"):
        GarminConnectTransport(
            None,
            None,
            TokenStore(tmp_path / "tokens"),
            client=object(),
            request_timeout_seconds=0,
        )
    with pytest.raises(GarminError, match="unsupported_garmin_client_structure"):
        GarminConnectTransport(
            None,
            None,
            TokenStore(tmp_path / "bad-shape"),
            client=object(),
            request_timeout_seconds=17,
        )

    config, tool, _, _ = _tool(tmp_path / "config", max_attempts=5)
    assert tool.config.max_attempts == 5
    tool.config = GarminConfig(
        config.database_path,
        config.raw_root,
        config.state_root,
        config.history_start_date,
        max_attempts=6,
    )
    with pytest.raises(ValueError, match="max_attempts_out_of_range"):
        tool.execute(
            SyncRequest(
                "incremental",
                through_local_date="2026-04-15",
                invocation_id="bad-config",
            )
        )
