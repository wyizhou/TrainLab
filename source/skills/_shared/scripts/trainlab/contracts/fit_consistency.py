from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trainlab.contracts.time import format_utc


def validate_record_time(record: dict[str, Any], definitions: dict[str, Any]) -> None:
    metrics = record["metrics_json"]
    timestamps = [
        value
        for key, value in metrics["standard"].items()
        if definitions[key]["field_number"] == 253 and definitions[key]["origin"] == "direct"
    ]
    if len(timestamps) > 1:
        raise ValueError("multiple record timestamps")
    if not timestamps:
        expected: dict[str, Any] = {"kind": "missing", "raw": None, "unit": None}
        stamp = None
    else:
        raw = timestamps[0]
        if raw is None:
            expected = {"kind": "invalid", "raw": None, "unit": "s"}
            stamp = None
        else:
            if type(raw) is not int or not 0 <= raw < 0xFFFFFFFF:
                raise ValueError("invalid raw record timestamp")
            absolute = raw >= 0x10000000
            expected = {"kind": "absolute" if absolute else "relative", "raw": raw, "unit": "s"}
            stamp = (
                format_utc(datetime(1989, 12, 31, tzinfo=UTC) + timedelta(seconds=raw))
                if absolute
                else None
            )
    if metrics["time_evidence"] != expected or record["timestamp_utc"] != stamp:
        raise ValueError("record timestamp/SQL/evidence mismatch")
