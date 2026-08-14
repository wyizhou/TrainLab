"""Bounded, opt-in decoded FIT context for user-requested diagnostics.

The normal analysis context never contains raw FIT messages.  A caller may
explicitly bind one or more activity IDs to this pure helper after a local FIT
decoder has produced JSON messages.  The helper performs no file, database,
network or model access; it only validates the binding, removes secrets and
default GPS/device identifiers, and enforces the same hard context limit as
the analysis Harness.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

FIT_CONTEXT_MAX_BYTES = 1_100_000
_MAX_MESSAGES = 4_000
_MAX_DEPTH = 12
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "authorization_url",
        "client_id",
        "client_secret",
        "credential",
        "credentials",
        "identity_hmac",
        "password",
        "refresh_token",
        "secret",
        "token",
        "provider_account_id",
    }
)
_DEVICE_KEYS = frozenset(
    {
        "serial",
        "serial_number",
        "device_serial",
        "device_serial_number",
        "device_id",
        "device_uid",
        "device_uid_hash",
        "unit_id",
    }
)
_GPS_KEYS = frozenset(
    {
        "latitude",
        "longitude",
        "position_lat",
        "position_long",
        "gps",
        "coordinates",
        "route",
        "polyline",
        "course_points",
    }
)


class ExplicitFitContextError(ValueError):
    """Controlled failure for an unbound, unsafe or oversized FIT request."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExplicitFitContextError("fit_context_json_invalid") from exc


def _id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ExplicitFitContextError("fit_context_activity_id_invalid")
    text = str(value)
    if not text or len(text) > 192:
        raise ExplicitFitContextError("fit_context_activity_id_invalid")
    return text


def _clean(value: Any, *, include_gps: bool, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise ExplicitFitContextError("fit_context_depth_exceeded")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExplicitFitContextError("fit_context_nonfinite_number")
        return value
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ExplicitFitContextError("fit_context_key_invalid")
            normalized = key.casefold().replace("-", "_")
            if normalized in _SECRET_KEYS:
                raise ExplicitFitContextError("fit_context_secret_forbidden")
            if normalized in _DEVICE_KEYS:
                continue
            if not include_gps and normalized in _GPS_KEYS:
                continue
            if key in output:
                raise ExplicitFitContextError("fit_context_duplicate_key")
            output[key] = _clean(child, include_gps=include_gps, depth=depth + 1)
        if len(output) > 128:
            raise ExplicitFitContextError("fit_context_object_limit_exceeded")
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_MESSAGES:
            raise ExplicitFitContextError("fit_context_array_limit_exceeded")
        return [
            _clean(item, include_gps=include_gps, depth=depth + 1) for item in value
        ]
    raise ExplicitFitContextError("fit_context_value_invalid")


def build_explicit_fit_context(
    requested_activity_ids: Sequence[str | int],
    decoded_fit: Iterable[Mapping[str, Any]],
    *,
    include_gps: bool = False,
    max_bytes: int = FIT_CONTEXT_MAX_BYTES,
) -> dict[str, Any]:
    """Build an explicitly bound FIT payload safe for one model invocation.

    ``decoded_fit`` must contain exactly one record per requested activity and
    each record must provide ``activity_id``, ``source_revision_id`` and a
    list/tuple ``messages``.  Extra activity records or missing IDs fail
    closed; a caller cannot accidentally broaden the request to all FIT data.
    """
    if not isinstance(requested_activity_ids, Sequence) or isinstance(
        requested_activity_ids, (str, bytes, bytearray)
    ):
        raise ExplicitFitContextError("fit_context_activity_ids_invalid")
    requested = tuple(_id(value) for value in requested_activity_ids)
    if not requested or len(requested) != len(set(requested)) or len(requested) > 16:
        raise ExplicitFitContextError("fit_context_activity_ids_invalid")
    if (
        not isinstance(include_gps, bool)
        or not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
    ):
        raise ExplicitFitContextError("fit_context_limits_invalid")
    if not 1 <= max_bytes <= FIT_CONTEXT_MAX_BYTES:
        raise ExplicitFitContextError("fit_context_limits_invalid")
    rows: dict[str, dict[str, Any]] = {}
    for row in decoded_fit:
        if not isinstance(row, Mapping):
            raise ExplicitFitContextError("fit_context_record_invalid")
        activity_id = _id(row.get("activity_id"))
        if activity_id not in requested or activity_id in rows:
            raise ExplicitFitContextError("fit_context_activity_binding_invalid")
        revision = row.get("source_revision_id")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, (str, int))
            or not str(revision)
        ):
            raise ExplicitFitContextError("fit_context_revision_invalid")
        messages = row.get("messages")
        if not isinstance(messages, Sequence) or isinstance(
            messages, (str, bytes, bytearray)
        ):
            raise ExplicitFitContextError("fit_context_messages_invalid")
        if len(messages) > _MAX_MESSAGES:
            raise ExplicitFitContextError("fit_context_messages_limit_exceeded")
        rows[activity_id] = {
            "activity_id": activity_id,
            "source_revision_id": str(revision),
            "messages": _clean(messages, include_gps=include_gps),
        }
    if set(rows) != set(requested):
        raise ExplicitFitContextError("fit_context_activity_binding_invalid")
    payload: dict[str, Any] = {
        "schema_version": "1",
        "binding": "explicit_activity_ids",
        "include_gps": include_gps,
        "activities": [rows[activity_id] for activity_id in requested],
    }
    encoded = _canonical(payload)
    if len(encoded) > max_bytes:
        raise ExplicitFitContextError("fit_context_size_limit_exceeded")
    payload["size_bytes"] = len(encoded)
    payload["payload_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


__all__ = [
    "FIT_CONTEXT_MAX_BYTES",
    "ExplicitFitContextError",
    "build_explicit_fit_context",
]
