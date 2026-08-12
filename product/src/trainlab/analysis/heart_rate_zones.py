"""Deterministic, user-confirmed running heart-rate zone candidates.

This module never reads Garmin data, SQLite or raw FIT.  The caller supplies
small, already validated evidence rows.  It returns one append-only revision
candidate containing the three methods agreed for TrainLab: HRR as the primary
method, a historical threshold proxy for comparison, and Tanaka as a
low-confidence fallback.  Persistence and the confirmation mail flow belong
to the collection/mail layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


RHR_WINDOW_DAYS = 28
MAX_HEART_RATE_WINDOW_DAYS = 180
THRESHOLD_WINDOW_DAYS = 90
MIN_MAX_HR_RUNS = 2
MIN_SUSTAINED_HIGH_SECONDS = 30
MIN_THRESHOLD_DURATION_SECONDS = 20 * 60
MAX_THRESHOLD_MAD_BPM = 6.0
ZONE_BANDS: tuple[tuple[int, float, float], ...] = (
    (1, 0.50, 0.60),
    (2, 0.60, 0.70),
    (3, 0.70, 0.80),
    (4, 0.80, 0.90),
    (5, 0.90, 1.00),
)


@dataclass(frozen=True)
class _RhrEvidence:
    local_date: date
    bpm: float


@dataclass(frozen=True)
class _RunEvidence:
    activity_id: str
    local_date: date
    values: tuple[float, ...]
    duration_seconds: float
    sample_interval_seconds: float
    source_quality: str
    is_threshold: bool


def _date(value: Any) -> date | None:
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _number(value: Any, *, low: float = 30.0, high: float = 260.0) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) and low <= value <= high else None


def _mapping_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _rhr_rows(rows: Iterable[Any], start: date, end: date) -> tuple[_RhrEvidence, ...]:
    result: list[_RhrEvidence] = []
    for row in rows:
        if isinstance(row, Mapping):
            day = _date(_mapping_value(row, "local_date", "date", "day"))
            bpm = _number(_mapping_value(row, "bpm", "heart_rate_bpm", "value"), low=30, high=150)
            valid = row.get("valid", True)
        elif isinstance(row, Sequence) and len(row) >= 2:
            day, bpm = _date(row[0]), _number(row[1], low=30, high=150)
            valid = True
        else:
            continue
        if day is not None and start <= day <= end and bool(valid) and bpm is not None:
            result.append(_RhrEvidence(day, bpm))
    # A day may have multiple provider samples.  Use its robust daily median
    # before taking the window median, so a duplicate payload cannot overweight
    # the baseline.
    grouped: dict[date, list[float]] = {}
    for row in result:
        grouped.setdefault(row.local_date, []).append(row.bpm)
    return tuple(_RhrEvidence(day, median(values)) for day, values in sorted(grouped.items()))


def _sample_values(value: Any) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result = [_number(item, low=35, high=240) for item in value]
    return tuple(item for item in result if item is not None)


def _run_rows(rows: Iterable[Any], start: date, end: date) -> tuple[_RunEvidence, ...]:
    result: list[_RunEvidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        day = _date(_mapping_value(row, "local_date", "date", "day"))
        if day is None or not start <= day <= end:
            continue
        sport = str(_mapping_value(row, "sport", "activity_type", "type") or "running").casefold()
        if sport not in {"running", "run", "treadmill_running", "trail_running"}:
            continue
        values = _sample_values(_mapping_value(row, "heart_rate_bpm", "heart_rates", "samples"))
        duration = _number(_mapping_value(row, "duration_seconds", "elapsed_seconds", "duration"), low=0, high=172800) or 0.0
        interval = _number(_mapping_value(row, "sample_interval_seconds", "interval_seconds"), low=0.1, high=120) or 1.0
        quality = str(_mapping_value(row, "source_quality", "heart_rate_source") or "unknown").casefold()
        session = str(_mapping_value(row, "session_type", "workout_type", "purpose") or "").casefold()
        is_threshold = bool(row.get("is_threshold", False)) or any(
            token in session for token in ("tempo", "threshold", "race", "competition", "interval")
        )
        if values:
            result.append(_RunEvidence(str(_mapping_value(row, "activity_id", "id") or f"run-{index}"), day, values, duration, interval, quality, is_threshold))
    return tuple(result)


def _zones(resting_bpm: float, max_bpm: float) -> tuple[dict[str, Any], ...] | None:
    reserve = max_bpm - resting_bpm
    if reserve <= 0:
        return None
    result: list[dict[str, Any]] = []
    for zone, low, high in ZONE_BANDS:
        lower = round(resting_bpm + low * reserve)
        upper = round(resting_bpm + high * reserve) - (1 if zone < 5 else 0)
        result.append({"zone": zone, "percent_hrr": [low, high], "bpm": [lower, max(lower, upper)]})
    return tuple(result)


def _high_candidate(run: _RunEvidence) -> float | None:
    if run.duration_seconds < MIN_SUSTAINED_HIGH_SECONDS or len(run.values) < 5:
        return None
    # A single spike is not evidence.  Retain the upper decile and require it
    # to cover at least the minimum sustained duration (using the declared FIT
    # sampling interval).  The candidate is its median, not its highest point.
    ordered = sorted(run.values)
    cutoff = ordered[max(0, int(len(ordered) * 0.90) - 1)]
    high = [value for value in run.values if value >= cutoff]
    if len(high) * run.sample_interval_seconds < MIN_SUSTAINED_HIGH_SECONDS:
        return None
    return median(high)


def _threshold_candidate(runs: Iterable[_RunEvidence]) -> tuple[float | None, tuple[str, ...], str]:
    candidates: list[tuple[str, float]] = []
    for run in runs:
        if not run.is_threshold or run.duration_seconds < MIN_THRESHOLD_DURATION_SECONDS:
            continue
        if run.source_quality in {"poor", "unknown", "invalid"}:
            continue
        center = median(run.values)
        mad = median([abs(value - center) for value in run.values])
        if mad <= MAX_THRESHOLD_MAD_BPM:
            candidates.append((run.activity_id, center))
    if len(candidates) < 2:
        return None, tuple(activity_id for activity_id, _ in candidates), "insufficient_evidence"
    value = median(candidate for _, candidate in candidates)
    return value, tuple(activity_id for activity_id, _ in candidates), "available"


def calculate_zone_candidates(
    resting_heart_rates: Iterable[Any],
    running_evidence: Iterable[Any],
    *,
    as_of: date | str,
    age_years: int | None = None,
) -> dict[str, Any]:
    """Return an explainable, unconfirmed zone revision candidate.

    ``as_of`` is a completed Hong Kong local date.  Inputs are expected to be
    already quality-filtered summaries; malformed rows are ignored rather than
    converted into zeroes.  The returned object is safe to persist as one
    append-only revision and contains no raw FIT samples.
    """
    end = _date(as_of)
    if end is None:
        raise ValueError("as_of_date_invalid")
    rhr = _rhr_rows(resting_heart_rates, end - timedelta(days=RHR_WINDOW_DAYS - 1), end)
    runs = _run_rows(running_evidence, end - timedelta(days=MAX_HEART_RATE_WINDOW_DAYS - 1), end)
    baseline = median(row.bpm for row in rhr) if len(rhr) >= 5 else None
    high_candidates = tuple(
        (run.activity_id, _high_candidate(run))
        for run in runs
        if _high_candidate(run) is not None and run.source_quality not in {"poor", "unknown", "invalid"}
    )
    max_hr: float | None = None
    max_evidence: tuple[str, ...] = ()
    if len(high_candidates) >= MIN_MAX_HR_RUNS:
        values = [float(value) for _, value in high_candidates]
        if max(values) - min(values) <= 5.0:
            # Conservative: do not let one unusually high activity widen every
            # future prescription.  User confirmation is still mandatory.
            max_hr = min(values)
            max_evidence = tuple(activity_id for activity_id, _ in high_candidates)
    hrr_zones = _zones(float(baseline), max_hr) if baseline is not None and max_hr is not None else None
    threshold_value, threshold_evidence, threshold_status = _threshold_candidate(
        run for run in runs if run.local_date >= end - timedelta(days=THRESHOLD_WINDOW_DAYS - 1)
    )
    tanaka_max = None
    tanaka_zones = None
    if isinstance(age_years, int) and not isinstance(age_years, bool) and 18 <= age_years <= 100:
        tanaka_max = round(208 - 0.7 * age_years)
        tanaka_zones = _zones(float(baseline), tanaka_max) if baseline is not None else None
    return {
        "algorithm_version": "trainlab-hrr-v1",
        "as_of_local_date": end.isoformat(),
        "primary_method": "hrr",
        "requires_user_confirmation": True,
        "accepted": False,
        "windows": {
            "resting_heart_rate_days": RHR_WINDOW_DAYS,
            "max_heart_rate_days": MAX_HEART_RATE_WINDOW_DAYS,
            "threshold_proxy_days": THRESHOLD_WINDOW_DAYS,
        },
        "hrr": {
            "status": "available" if hrr_zones is not None else "unavailable",
            "resting_heart_rate_bpm": round(float(baseline)) if baseline is not None else None,
            "max_heart_rate_bpm": round(float(max_hr)) if max_hr is not None else None,
            "evidence_days": len(rhr),
            "evidence_activity_ids": list(max_evidence),
            "zones": list(hrr_zones) if hrr_zones is not None else None,
        },
        "historical_threshold_proxy": {
            "status": threshold_status,
            "heart_rate_bpm": round(float(threshold_value)) if threshold_value is not None else None,
            "evidence_activity_ids": list(threshold_evidence),
            "not_a_lactate_or_ventilatory_threshold": True,
        },
        "tanaka_low_confidence": {
            "status": "available" if tanaka_zones is not None else ("max_only" if tanaka_max is not None else "unavailable"),
            "age_years": age_years,
            "predicted_max_heart_rate_bpm": tanaka_max,
            "zones": list(tanaka_zones) if tanaka_zones is not None else None,
            "confidence": "low",
        },
    }


# Descriptive aliases keep callers readable while retaining one implementation.
compute_heart_rate_zone_candidates = calculate_zone_candidates
build_zone_revision_candidate = calculate_zone_candidates


__all__ = [
    "RHR_WINDOW_DAYS", "MAX_HEART_RATE_WINDOW_DAYS", "THRESHOLD_WINDOW_DAYS",
    "calculate_zone_candidates", "compute_heart_rate_zone_candidates",
    "build_zone_revision_candidate",
]
