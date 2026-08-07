"""Offline fault-matrix acceptance tests for L2-07 request control."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from garminconnect import Garmin

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest, classify_garmin_error
from trainlab import garmin_client
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
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/receipt.json", root / "state/locks/foundation.lock")
    FoundationTool(foundation).execute(FoundationRequest("init", "fixture", "2026-01-01T00:00:00Z"))
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
    fit = (Path(__file__).parents[1] / "test_data/new/Running.fit").read_bytes()
    transport = QuietTransport(fit, faults=faults or {})
    sleeps: list[float] = []
    tool = GarminCollectionTool(config, transport, sleep=sleeps.append, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 100.0, rng=lambda: 0.25)
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
    return SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=resources, repair_strategy="refetch", invocation_id=invocation)


class _PacingClock:
    def __init__(self, now: float = 100.0, *, early_sleep: bool = False) -> None:
        self.now = now
        self.early_sleep = early_sleep
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds / 2 if self.early_sleep and len(self.sleeps) == 1 else seconds

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
    provider = lambda: entries.append(clock.monotonic())

    tool._call(provider)
    clock.advance(1.5)
    tool._call(provider)

    assert entries == [100.0, 101.5]
    assert clock.sleeps == []


def test_provider_entry_pacing_just_below_minimum(tmp_path: Path) -> None:
    clock = _PacingClock()
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []
    provider = lambda: entries.append(clock.monotonic())

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
    provider = lambda: entries.append(clock.monotonic())

    tool._call(provider, conn=object(), run=1, resource="steps", key="day")
    clock.advance(0.75)
    tool._call(provider, conn=object(), run=1, resource="steps", key="day")

    assert entries[1] - entries[0] == pytest.approx(1.5)
    assert clock.sleeps == []


def test_provider_entry_pacing_rechecks_early_sleep_return(tmp_path: Path) -> None:
    clock = _PacingClock(early_sleep=True)
    tool = _pacing_tool(tmp_path, clock)
    entries: list[float] = []
    provider = lambda: entries.append(clock.monotonic())

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


def test_network_408_and_temporary_5xx_retry_with_jitter_and_durable_attempts(tmp_path: Path) -> None:
    faults = {"health:steps": [GarminError("dns"), GarminError("http_408", http_status=408), GarminError("http_503", http_status=503)]}
    config, tool, transport, sleeps = _tool(tmp_path, faults=faults)
    result = tool.execute(_resource_request(("steps",), "retry"))
    assert result.status == "succeeded" and result.counts["empty"] == 1
    assert _item_row(config, "retry") == ("empty", 4, None, None, None)
    assert sleeps == [2.25, 4.25, 8.25]
    assert transport.calls.count("health:steps") == 4


def test_short_429_waits_inline_then_succeeds_and_long_429_defers_with_cooldown(tmp_path: Path) -> None:
    config, tool, transport, sleeps = _tool(tmp_path, faults={"health:steps": [GarminError("limited", http_status=429, retry_after=2)]})
    short = tool.execute(_resource_request(("steps",), "short"))
    assert short.status == "succeeded"
    assert sleeps == [2.0]
    assert _item_row(config, "short") == ("empty", 2, None, None, None)

    config, tool, transport, _ = _tool(tmp_path / "long", faults={"health:steps": GarminError("limited", http_status=429, retry_after=121)})
    first = tool.execute(_resource_request(("steps",), "long-one"))
    calls = transport.calls.count("health:steps")
    assert first.status == "deferred" and first.next_retry_at_utc
    assert _item_row(config, "long-one")[0:2] == ("deferred", 1)
    second = tool.execute(_resource_request(("steps",), "long-two"))
    assert second.status == "deferred" and transport.calls.count("health:steps") == calls


def test_configured_429_threshold_controls_inline_retry_vs_deferred(tmp_path: Path) -> None:
    # The same Retry-After is inline at a larger configured threshold.
    _, inline, transport, sleeps = _tool(
        tmp_path / "inline", faults={"health:steps": [GarminError("limited", http_status=429, retry_after=3)]},
        inline_retry_after_max_seconds=3,
    )
    assert inline.execute(_resource_request(("steps",), "inline-threshold")).status == "succeeded"
    assert transport.calls.count("health:steps") == 2 and sleeps == [3.0]

    # Reducing the threshold changes the actual call path: no second request,
    # persisted deferred state, and no inline sleep.
    _, deferred, transport, sleeps = _tool(
        tmp_path / "deferred", faults={"health:steps": GarminError("limited", http_status=429, retry_after=3)},
        inline_retry_after_max_seconds=2,
    )
    result = deferred.execute(_resource_request(("steps",), "deferred-threshold"))
    assert result.status == "deferred" and result.next_retry_at_utc
    assert transport.calls.count("health:steps") == 1 and sleeps == []


def test_429_without_retry_after_uses_configured_fallback(tmp_path: Path) -> None:
    _, tool, transport, sleeps = _tool(
        tmp_path,
        faults={"health:steps": [GarminError("limited", http_status=429)]},
        inline_retry_after_max_seconds=3,
        rate_limit_fallback_seconds=3,
    )
    result = tool.execute(_resource_request(("steps",), "fallback-threshold"))
    assert result.status == "succeeded"
    assert transport.calls.count("health:steps") == 2
    assert sleeps == [3.0]


def test_401_refreshes_once_then_success_or_stops_all_following_network_work(tmp_path: Path) -> None:
    config, tool, transport, _ = _tool(tmp_path, faults={"health:user_summary": [GarminError("expired", http_status=401)]})
    refreshed = tool.execute(_resource_request(("user_summary",), "refresh"))
    assert refreshed.status == "succeeded"
    assert transport.calls.count("login") == 3  # auth, sync token login, one refresh

    config, tool, transport, _ = _tool(tmp_path / "final", faults={"health:user_summary": [GarminError("expired", http_status=401), GarminError("still_expired", http_status=401)]})
    final = tool.execute(_resource_request(("user_summary", "steps"), "final-401"))
    assert final.status == "auth_required"
    assert transport.calls.count("health:user_summary") == 2
    assert "health:steps" not in transport.calls
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT status FROM garmin_sync_runs WHERE invocation_id='final-401'").fetchone()[0] == "auth_required"


@pytest.mark.parametrize(
    ("resource", "error", "item_status", "receipt_status"),
    [
        ("steps", GarminError("denied", http_status=403), "forbidden", "partial"),
        ("body_composition", GarminError("missing", http_status=404), "not_available", "succeeded"),
        ("user_summary", GarminError("missing", http_status=404), "failed", "partial"),
        ("steps", GarminError("bad_request", http_status=400), "failed", "partial"),
    ],
)
def test_4xx_matrix_uses_catalog_404_rule_without_retry(tmp_path: Path, resource: str, error: GarminError, item_status: str, receipt_status: str) -> None:
    config, tool, transport, sleeps = _tool(tmp_path, faults={f"health:{resource}": error})
    result = tool.execute(_resource_request((resource,), f"four-{resource}"))
    row = _item_row(config, f"four-{resource}")
    assert result.status == receipt_status and row[0] == item_status and row[1] == 1
    assert transport.calls.count(f"health:{resource}") == 1 and sleeps == []


def test_classifier_and_adapter_error_translation_are_safe_and_configuration_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert classify_garmin_error(GarminError("timeout")).status == "retry"
    assert classify_garmin_error(GarminError("x", http_status=408)).status == "retry"
    assert classify_garmin_error(GarminError("x", http_status=404), allows_404=True).status == "not_available"
    assert classify_garmin_error(GarminError("x", http_status=404), allows_404=False).status == "failed"
    assert classify_garmin_error(GarminError("secret-password", http_status=403)).status == "forbidden"

    class Response: status_code = 503; headers = {"Retry-After": "7"}
    class ProviderFailure(Exception): response = Response()
    translated = GarminConnectTransport._error(ProviderFailure())
    assert (translated.code, translated.http_status, translated.retry_after) == ("http_503", 503, 7)
    assert GarminConnectTransport._error(RuntimeError("PASSWORD_SECRET")).code == "provider_error"

    captured: dict[str, object] = {}
    production_calls: list[tuple[str, dict[str, object]]] = []
    class Session:
        def __init__(self, name: str) -> None: self.name = name
        def request(self, method: str, url: str, **kwargs):
            production_calls.append((self.name, kwargs)); return object()
    class LowClient:
        def __init__(self) -> None:
            self.cs = Session("cs")
            self._api_session = Session("api")
    class PinnedClient:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs); self.client = LowClient()
    monkeypatch.setattr(garmin_client, "Garmin", PinnedClient)
    production = GarminConnectTransport(None, None, TokenStore(tmp_path / "pinned"), region="cn", request_timeout_seconds=17)
    assert captured["retry_attempts"] == 0 and captured["is_cn"] is True
    production.client.client.cs.request("GET", "https://offline.invalid", timeout=999)
    production.client.client._api_session.request("GET", "https://offline.invalid", timeout=999)
    assert production_calls == [("cs", {"timeout": 17}), ("api", {"timeout": 17})]

    # This uses the installed 0.3.6 Client structure but replaces its sessions
    # before invocation; no real request is made.  ``connectapi`` would supply
    # its own default/override without the adapter's Session wrapper.
    pinned = Garmin(None, None, retry_attempts=0).client
    calls: list[tuple[str, dict[str, object]]] = []
    class Response:
        status_code = 200
        content = b"{}"
        def json(self): return {}
    def api_request(method: str, url: str, **kwargs):
        calls.append(("api", kwargs)); return Response()
    def sso_request(method: str, url: str, **kwargs):
        calls.append(("sso", kwargs)); return Response()
    pinned._api_session.request = api_request
    pinned.cs.request = sso_request
    pinned.get_api_headers = lambda: {}
    bounded = GarminConnectTransport(None, None, TokenStore(tmp_path / "bounded"), client=pinned, request_timeout_seconds=17)
    assert bounded.client.connectapi("/offline", timeout=999) == {}
    bounded.client.cs.request("GET", "https://offline.invalid", timeout=999)
    assert calls == [("api", {"headers": {}, "timeout": 17}), ("sso", {"timeout": 17})]
    with pytest.raises(ValueError, match="invalid_request_timeout"):
        GarminConnectTransport(None, None, TokenStore(tmp_path / "tokens"), client=object(), request_timeout_seconds=0)
    with pytest.raises(GarminError, match="unsupported_garmin_client_structure"):
        GarminConnectTransport(None, None, TokenStore(tmp_path / "bad-shape"), client=object(), request_timeout_seconds=17)

    config, tool, _, _ = _tool(tmp_path / "config", max_attempts=5)
    assert tool.config.max_attempts == 5
    tool.config = GarminConfig(config.database_path, config.raw_root, config.state_root, config.history_start_date, max_attempts=6)
    with pytest.raises(ValueError, match="max_attempts_out_of_range"):
        tool.execute(SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="bad-config"))
