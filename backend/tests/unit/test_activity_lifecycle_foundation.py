import uuid
from datetime import UTC, datetime

from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.services.activity_projection import effective_activity_title
from trainlab.services.activity_states import (
    DELETE_RECOVERABLE_STATUSES,
    PARSE_RETRYABLE_STATUSES,
    PUBLIC_IMPORT_STATUSES,
    VISIBLE_ACTIVITY_STATUSES,
)


def _models() -> tuple[Activity, ActivityImport]:
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    imported = ActivityImport(
        id=import_id,
        user_id=user_id,
        source="fit_upload",
        original_filename="run.fit",
        size_bytes=10,
        sha256="a" * 64,
        storage_key=f"{user_id}/{import_id}.fit",
        status="complete",
        parser_name="test",
        parser_version="1",
        attempt_count=1,
        warning_count=0,
        replay_metadata={},
    )
    activity = Activity(
        user_id=user_id,
        source_import_id=import_id,
        title="Parsed title",
        sport="running",
        sub_sport="generic",
        profile="run",
        start_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        total_timer_time_sec=1,
        total_elapsed_time_sec=1,
        total_distance_m=1,
        extra_metrics={},
    )
    return activity, imported


def test_public_lifecycle_status_sets_are_centralized_and_non_overlapping() -> None:
    assert {
        "pending",
        "processing",
        "complete",
        "partial",
        "failed",
        "deleting",
        "delete_failed",
    } == PUBLIC_IMPORT_STATUSES
    assert {"complete", "partial"} == VISIBLE_ACTIVITY_STATUSES
    assert {"pending", "failed", "partial"} == PARSE_RETRYABLE_STATUSES
    assert {"deleting", "delete_failed"} == DELETE_RECOVERABLE_STATUSES
    assert PARSE_RETRYABLE_STATUSES.isdisjoint(DELETE_RECOVERABLE_STATUSES)


def test_effective_title_keeps_parsed_and_user_override_as_separate_facts() -> None:
    activity, imported = _models()
    assert effective_activity_title(activity, imported) == "Parsed title"

    imported.title_override = "User title"
    assert effective_activity_title(activity, imported) == "User title"

    activity.title = "Replayed parser title"
    assert effective_activity_title(activity, imported) == "User title"
