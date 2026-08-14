from __future__ import annotations

import pytest

from src.analysis.fit_context import (
    ExplicitFitContextError,
    build_explicit_fit_context,
)


def _row(activity_id: str = "activity-1") -> dict:
    return {
        "activity_id": activity_id,
        "source_revision_id": "fit-revision-1",
        "messages": [
            {
                "name": "record",
                "heart_rate": 151,
                "position_lat": 123,
                "position_long": 456,
                "serial_number": "must-not-leak",
            }
        ],
    }


def test_fit_is_opt_in_exactly_bound_and_default_sanitizes_gps_and_device_ids() -> None:
    result = build_explicit_fit_context(("activity-1",), (_row(),))
    message = result["activities"][0]["messages"][0]
    assert result["binding"] == "explicit_activity_ids"
    assert "position_lat" not in message and "position_long" not in message
    assert "serial_number" not in message
    assert message["heart_rate"] == 151


def test_fit_route_request_can_keep_coordinates_but_never_secrets() -> None:
    result = build_explicit_fit_context(("activity-1",), (_row(),), include_gps=True)
    message = result["activities"][0]["messages"][0]
    assert message["position_lat"] == 123
    with pytest.raises(ExplicitFitContextError, match="secret_forbidden"):
        build_explicit_fit_context(
            ("activity-1",),
            ({**_row(), "messages": [{"token": "secret"}]},),
        )


def test_fit_extra_or_missing_activity_is_rejected_and_size_is_hard_bounded() -> None:
    with pytest.raises(ExplicitFitContextError, match="activity_binding_invalid"):
        build_explicit_fit_context(("activity-1",), (_row("activity-2"),))
    with pytest.raises(ExplicitFitContextError, match="size_limit_exceeded"):
        build_explicit_fit_context(
            ("activity-1",),
            ({**_row(), "messages": [{"text": "x" * 5000}]},),
            max_bytes=100,
        )
