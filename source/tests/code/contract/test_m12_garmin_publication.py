"""Single-workout DTO, readback and calendar boundaries against fake MCP."""

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import garmin_publication
from skills._shared.fit_weekly import publication_ledger as ledger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_publication_factory")


def test_real_steps_repeat_and_separate_schedule_receipts(tmp_path, monkeypatch):
    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    create, schedule = prepared["workouts"][0].values()
    sdk = f.Garmin()
    grant = f.authorization([create, schedule])
    result = asyncio.run(
        garmin_publication.deliver(
            root, create, schedule, sdk, grant, now=lambda: f.NOW
        )
    )
    assert result["create"]["status"] == result["schedule"]["status"] == "success"
    assert result["create"]["evidence"]["workout_id"] == 123
    assert result["schedule"]["evidence"]["scheduled_workout_id"] == 987
    dto = sdk.workouts[123]
    group = dto["workoutSegments"][0]["workoutSteps"][0]
    assert group["type"] == "RepeatGroupDTO"
    assert group["numberOfIterations"] == 2
    assert group["endCondition"] == {
        "conditionTypeId": 7,
        "conditionTypeKey": "iterations",
    }
    assert group["workoutSteps"][0]["endConditionValue"] == 600
    count = len(sdk.calls)
    asyncio.run(
        garmin_publication.deliver(
            root, create, schedule, sdk, grant, now=lambda: f.NOW
        )
    )
    assert len(sdk.calls) == count


@pytest.mark.parametrize(
    "fail", ["upload_workout", "get_workout_by_id", "schedule_workout"]
)
def test_unknown_never_recreates_or_reschedules(tmp_path, monkeypatch, fail):
    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    create, schedule = prepared["workouts"][0].values()
    sdk = f.Garmin()
    sdk.fail = fail
    grant = f.authorization([create, schedule])
    asyncio.run(
        garmin_publication.deliver(
            root, create, schedule, sdk, grant, now=lambda: f.NOW
        )
    )
    sdk.fail = None
    before = [n for n, _ in sdk.calls if n in ("upload_workout", "schedule_workout")]
    asyncio.run(
        garmin_publication.reconcile(
            root, create, schedule, sdk, grant, now=lambda: f.NOW
        )
    )
    assert [
        n for n, _ in sdk.calls if n in ("upload_workout", "schedule_workout")
    ] == before
    assert ledger.status(root, create)["status"] in ("unknown", "success")


def test_wrong_steps_block_schedule_and_past_date_blocks_create(tmp_path, monkeypatch):
    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    create, schedule = prepared["workouts"][0].values()
    sdk = f.Garmin()
    sdk.change = lambda v: v.update(description="truncated")
    grant = f.authorization([create, schedule])
    result = asyncio.run(
        garmin_publication.deliver(
            root, create, schedule, sdk, grant, now=lambda: f.NOW
        )
    )
    assert result["create"]["status"] == "unknown"
    assert "schedule_workout" not in [n for n, _ in sdk.calls]


def test_past_course_is_never_created_or_moved(tmp_path, monkeypatch):
    from dataclasses import replace

    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    create, schedule = prepared["workouts"][0].values()
    sdk = f.Garmin()
    grant = replace(
        f.authorization([create, schedule]),
        starts_utc="2026-08-11T00:00:00Z",
        expires_utc="2026-08-11T01:00:00Z",
    )
    result = asyncio.run(
        garmin_publication.deliver(
            root, create, schedule, sdk, grant, now=lambda: "2026-08-11T00:00:00Z"
        )
    )
    assert result["create"]["status"] == "prepared"
    assert sdk.calls == []


def test_distance_work_phase_and_no_heart_rate_target():
    from skills._shared.fit_weekly import garmin_workouts

    day = {
        "date": "2026-08-10",
        "kind": "run",
        "workout": f.reports.coaching_fixture.workout(unit="meters", value=1000),
    }
    day["workout"]["steps"][0]["steps"][0]["phase"] = "work"
    dto = garmin_workouts.convert(day)
    step = dto["workoutSegments"][0]["workoutSteps"][0]
    assert step["endConditionValue"] == 1000
    assert step["endCondition"] == {
        "conditionTypeId": 3,
        "conditionTypeKey": "distance",
    }
    assert step["targetType"] == {
        "workoutTargetTypeId": 1,
        "workoutTargetTypeKey": "no.target",
    }
    garmin_workouts.verify(f.curated(dto, 123), dto, 123)
    with pytest.raises(ValueError):
        garmin_workouts.convert({"kind": "rest", "workout": None})


def test_publication_session_has_exact_four_tools_and_original_token_guard(
    tmp_path, monkeypatch
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from skills._shared.fit_weekly import garmin_fit, storage

    token = tmp_path / "token"
    token.mkdir(mode=0o700)
    (token / "synthetic").write_text("public fake token")
    (token / "synthetic").chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    specs = []

    class SDK:
        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name=name)
                    for name in sorted(garmin_publication.TOOLS)
                ]
            )

    @asynccontextmanager
    async def factory(spec):
        specs.append(spec)
        yield SDK()

    instance = tmp_path / "instance"
    storage.initialize(instance)

    async def run():
        with ledger.open_ledger(
            instance, f.authorization(["session-test"]), now=lambda: f.NOW
        ) as journal:
            async with garmin_publication.open_session(
                token,
                work,
                is_cn=False,
                timeout=1,
                journal=journal,
                action="session-test",
                factory=factory,
            ):
                pass

    asyncio.run(run())
    assert (
        set(specs[0]["environment"]["GARMIN_ENABLED_TOOLS"].split(","))
        == garmin_publication.TOOLS
    )
    assert garmin_fit.TOOLS == {"get_activities_by_date", "download_activity_file"}
    assert (token / "synthetic").read_text() == "public fake token"


def test_budgeted_session_factory_executes_without_nested_lock(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    root, prepared, _ = f.prepared(tmp_path, monkeypatch)
    create, schedule = prepared["workouts"][0].values()
    token = tmp_path / "session-token"
    token.mkdir(mode=0o700)
    (token / "synthetic").write_text("public synthetic token")
    (token / "synthetic").chmod(0o600)
    work = tmp_path / "session-work"
    work.mkdir(mode=0o700)

    delegated = f.Garmin()

    class SDK:
        async def call_tool(self, name, arguments):
            return await delegated.call_tool(name, arguments)

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[SimpleNamespace(name=n) for n in garmin_publication.TOOLS]
            )

    sdk = SDK()
    closed = []

    @asynccontextmanager
    async def factory(spec):
        try:
            yield sdk
        finally:
            closed.append(True)

    opener = garmin_publication.session_opener(
        token, work, is_cn=False, timeout=1, factory=factory
    )
    result = asyncio.run(
        garmin_publication.deliver(
            root,
            create,
            schedule,
            opener,
            f.authorization([create, schedule]),
            now=lambda: f.NOW,
        )
    )
    assert result["schedule"]["status"] == "success"
    assert closed == [True]


def test_expired_business_deadline_still_closes_session(tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from skills._shared.fit_weekly import storage

    root = tmp_path / "instance"
    storage.initialize(root)
    token = tmp_path / "token"
    token.mkdir(mode=0o700)
    (token / "fake").write_text("synthetic token")
    (token / "fake").chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    closed = []
    current = [f.NOW]

    class Session:
        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[SimpleNamespace(name=n) for n in garmin_publication.TOOLS]
            )

    @asynccontextmanager
    async def factory(spec):
        try:
            yield Session()
        finally:
            closed.append(True)

    async def run():
        with ledger.open_ledger(
            root, f.authorization(["test-session"]), now=lambda: current[0]
        ) as journal:
            async with garmin_publication.open_session(
                token,
                work,
                is_cn=False,
                timeout=1,
                journal=journal,
                action="test-session",
                factory=factory,
            ):
                current[0] = "2026-08-10T02:00:00Z"
            with pytest.raises(ValueError, match="time"):
                journal.reserve(
                    "test-session", "get_workout_by_id", {"workout_id": 123}
                )

    asyncio.run(run())
    assert closed == [True]
