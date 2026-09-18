from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from trainlab.contracts.errors import ErrorCode, ErrorEnvelope
from trainlab.contracts.time import UTC_TIMESTAMP_FORMAT, ensure_utc
from trainlab.garmin_auth import GarminAuthService

_RETRYABLE = {ErrorCode.TIMEOUT, ErrorCode.RESOURCE_LIMIT, ErrorCode.EXTERNAL_SERVICE_FAILED, ErrorCode.RUN_BUSY}


def maintenance_retryable(result: ErrorEnvelope) -> bool:
    return result.error is not None and result.error.code in _RETRYABLE


def maintenance_retry_delay(result: ErrorEnvelope, failures: int) -> float | None:
    if not maintenance_retryable(result) or failures >= 3:
        return None
    return float(5 * 2 ** (failures - 1))


def maintenance_check_delay(due: datetime, now: datetime) -> float:
    return min(60, max(1, (due - ensure_utc(now)).total_seconds()))


def run_maintenance(
    service: GarminAuthService, *, once: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[ErrorEnvelope], None] = lambda result: None,
) -> ErrorEnvelope:
    failures = 0
    while True:
        result = service.maintain_once(now_utc=ensure_utc(clock()))
        emit(result)
        if once:
            return result
        if not result.ok:
            failures += 1
            delay = maintenance_retry_delay(result, failures)
            if delay is None:
                return result
            sleep(delay)
            continue
        failures = 0
        assert isinstance(result.data, dict)
        due = datetime.strptime(result.data["next_check_at_utc"], UTC_TIMESTAMP_FORMAT).replace(tzinfo=UTC)
        sleep(maintenance_check_delay(due, clock()))
