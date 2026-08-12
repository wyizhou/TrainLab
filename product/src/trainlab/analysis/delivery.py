"""A3-14 pending analysis-delivery creation and deterministic safe rendering.

This module intentionally stops before any provider interaction.  It binds a
pending delivery to the immutable artifact revisions returned by A3-13 and
returns an in-memory plain-text/HTML representation for the later delivery
runner.  It never stores a rendered body or changes artifact/current/run state.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence, cast
from zoneinfo import ZoneInfo

from trainlab.email_templates import (
    Element,
    Template,
    Text,
    assert_no_bindings,
    element,
    load_template,
    text,
)

DeliveryKind = Literal["daily_report", "weekly_report", "plan_revision"]

_DELIVERY_SHAPES: dict[str, tuple[tuple[str, str], ...]] = {
    "daily_report": (
        ("daily_summary", "daily_summary"),
        ("daily_training_advice", "daily_advice"),
    ),
    "weekly_report": (
        ("weekly_summary", "weekly_summary"),
        ("weekly_training_plan", "weekly_plan"),
    ),
    "plan_revision": (("weekly_training_plan", "plan_revision"),),
}
_TITLES = {
    "daily_summary": "昨日回顾",
    "daily_advice": "今日安排",
    "weekly_summary": "每周总结",
    "weekly_plan": "未来七天计划",
    "plan_revision": "计划修订",
}
_DELIVERY_PRESENTATION = {
    "daily_report": ("每日训练简报", "恢复状态与今日安排"),
    "weekly_report": ("每周训练报告", "本周回顾与未来七天计划"),
    "plan_revision": ("训练计划更新", "根据最新情况调整"),
}
_ROLE_PRESENTATION = {
    "daily_summary": ("#2563eb", "#eff6ff"),
    "daily_advice": ("#059669", "#ecfdf5"),
    "weekly_summary": ("#7c3aed", "#f5f3ff"),
    "weekly_plan": ("#ea580c", "#fff7ed"),
    "plan_revision": ("#ea580c", "#fff7ed"),
}


class AnalysisDeliveryError(RuntimeError):
    """A controlled A3-14 failure; accepted artifacts remain untouched."""


_DELIVERY_STATUSES = frozenset(
    {"pending", "sending", "sent", "already_sent", "delivery_unknown", "failed"}
)
_SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_ERROR_CODE = re.compile(r"analysis_[a-z0-9_]{1,120}\Z")
_DELIVERY_FAILURE_SUMMARY = "analysis delivery did not complete"


class _PublishReceiptLike(Protocol):
    run_id: int
    artifact_ids: Mapping[str, int]


@dataclass(frozen=True)
class DeliveryArtifact:
    artifact_id: int
    artifact_kind: str
    content_role: str
    revision_no: int
    content_sha256: str
    user_visible_text: str
    period_start_local_date: str
    period_end_local_date: str
    structured_content_json: Mapping[str, object]
    created_at_utc: str


@dataclass(frozen=True)
class SleepChart:
    """Lineage-bound sleep values safe for deterministic email rendering."""

    completeness: Literal["complete", "partial"]
    start_local_time: str
    end_local_time: str
    window_seconds: int
    asleep_seconds: int
    deep_seconds: int
    light_seconds: int
    rem_seconds: int
    awake_seconds: int
    unmeasurable_seconds: int


@dataclass(frozen=True)
class RecoveryMetric:
    """One exact recovery value with a neutral personal-baseline comparison."""

    key: Literal["resting_heart_rate", "hrv", "spo2"]
    label: str
    value_text: str
    comparison_text: str
    observation_text: str
    available: bool


@dataclass(frozen=True)
class TrainingLoadDay:
    local_date: str
    duration_seconds: int
    activity_count: int


@dataclass(frozen=True)
class TrainingLoadChart:
    start_local_date: str
    end_local_date: str
    total_seconds: int
    activity_count: int
    days: tuple[TrainingLoadDay, ...]


@dataclass(frozen=True)
class ActivityOverview:
    sport_label: str
    duration_seconds: int
    distance_m: float | None
    average_heart_rate_bpm: float | None
    weather_text: str | None
    average_pace_seconds_per_km: float | None = None
    maximum_heart_rate_bpm: float | None = None
    highlight_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingDelivery:
    delivery_id: int
    subject_id: int
    analysis_run_id: int
    run_key: str
    delivery_kind: DeliveryKind
    idempotency_key: str
    artifacts: tuple[DeliveryArtifact, ...]
    sleep_chart: SleepChart | None = None
    recovery_metrics: tuple[RecoveryMetric, ...] = ()
    training_load_chart: TrainingLoadChart | None = None
    yesterday_activities: tuple[ActivityOverview, ...] = ()
    heart_rate_zone_comparison: tuple[str, ...] = ()
    resend_authorization_id: str | None = None


@dataclass(frozen=True)
class ResendAuthorization:
    """An explicit, immutable authorization for one additional formal send.

    The Foundation schema deliberately has no mutable resend flag.  The
    authorization identifier is therefore included in the new delivery's
    immutable idempotency key, which is retained with the delivery audit row.
    """

    authorization_id: str

    def __post_init__(self) -> None:
        if not _SAFE_PROVIDER_ID.fullmatch(self.authorization_id):
            raise AnalysisDeliveryError(
                "analysis_delivery_resend_authorization_invalid"
            )


def _zone_comparison_lines(
    connection: sqlite3.Connection, *, delivery_kind: str, subject_id: int
) -> tuple[str, ...]:
    if delivery_kind != "weekly_report":
        return ()
    from .heart_rate_zones_store import latest_zone_candidate

    try:
        stored = latest_zone_candidate(connection, subject_id)
    except sqlite3.OperationalError:
        # Compatibility for narrow renderer fixtures and historical read-only
        # databases that predate the physiology projection.
        return ()
    if stored is None:
        return ()
    methods = stored["methods"]

    def zones_text(value: object) -> str:
        if not isinstance(value, Mapping) or not isinstance(value.get("zones"), list):
            return "证据不足，暂不生成区间"
        parts = []
        for zone in value["zones"]:
            bpm = zone.get("bpm") if isinstance(zone, Mapping) else None
            if isinstance(bpm, list) and len(bpm) == 2:
                parts.append(f"Z{zone.get('zone')} {bpm[0]}–{bpm[1]}")
        return "；".join(parts) or "证据不足，暂不生成区间"

    hrr = methods.get("hrr", {})
    threshold = methods.get("historical_threshold_proxy", {})
    tanaka = methods.get("tanaka_low_confidence", {})
    threshold_bpm = (
        threshold.get("heart_rate_bpm") if isinstance(threshold, Mapping) else None
    )
    threshold_text = (
        f"候选阈值 {threshold_bpm} 次/分钟（仅一致性校验）"
        if isinstance(threshold_bpm, (int, float))
        else "证据不足（仅一致性校验）"
    )
    return (
        "HRR（主方法，待确认）：" + zones_text(hrr),
        "历史阈值代理：" + threshold_text,
        "Tanaka（低置信度备用）：" + zones_text(tanaka),
    )


@dataclass(frozen=True)
class RenderedDelivery:
    """Ephemeral provider-ready content.  It is deliberately not persisted."""

    subject: str
    headers: Mapping[str, str]
    plain_text: str
    html: str


@dataclass(frozen=True)
class AnalysisDeliveryState:
    """Provider-independent, durable delivery state and evidence."""

    delivery_id: int
    subject_id: int
    analysis_run_id: int
    status: str
    provider_message_id: str | None
    provider_thread_id: str | None
    sent_at_utc: str | None
    last_verified_at_utc: str | None
    error_code: str | None
    error_summary: str | None


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _safe_header(value: str) -> str:
    if not value or "\r" in value or "\n" in value:
        raise AnalysisDeliveryError("analysis_delivery_header_invalid")
    return value


def _local_date(value: object) -> str:
    """Accept only one ISO local date; presentation never repairs source data."""
    if not isinstance(value, str):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AnalysisDeliveryError(
            "analysis_delivery_artifact_content_invalid"
        ) from None
    if parsed.isoformat() != value:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return value


def _structured_content(value: object) -> Mapping[str, object]:
    if not isinstance(value, str):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    try:
        parsed = json.loads(
            value,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise AnalysisDeliveryError(
            "analysis_delivery_artifact_content_invalid"
        ) from None
    if not isinstance(parsed, dict):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return parsed


def _receipt_values(
    receipt: _PublishReceiptLike | Mapping[str, object],
) -> tuple[int, Mapping[str, int]]:
    if isinstance(receipt, Mapping):
        run_id, artifact_ids = receipt.get("run_id"), receipt.get("artifact_ids")
    else:
        run_id, artifact_ids = receipt.run_id, receipt.artifact_ids
    if (
        not isinstance(run_id, int)
        or isinstance(run_id, bool)
        or run_id <= 0
        or not isinstance(artifact_ids, Mapping)
    ):
        raise AnalysisDeliveryError("analysis_delivery_publish_receipt_invalid")
    normalized: dict[str, int] = {}
    for kind, artifact_id in artifact_ids.items():
        if (
            not isinstance(kind, str)
            or not isinstance(artifact_id, int)
            or isinstance(artifact_id, bool)
            or artifact_id <= 0
        ):
            raise AnalysisDeliveryError("analysis_delivery_publish_receipt_invalid")
        normalized[kind] = artifact_id
    return run_id, normalized


def _idempotency_key(
    subject_id: int,
    delivery_kind: str,
    artifacts: Sequence[DeliveryArtifact],
    *,
    resend_authorization: ResendAuthorization | None = None,
) -> str:
    """Return a business key, not a run/revision key, for formal reports.

    A later analysis run may revise an artifact, but it must not silently
    produce another email for the same subject and logical report/plan dates.
    ``plan_revision`` remains revision-addressed because it is explicitly a
    different business object.
    """
    if (
        not isinstance(subject_id, int)
        or isinstance(subject_id, bool)
        or subject_id <= 0
    ):
        raise AnalysisDeliveryError("analysis_delivery_subject_invalid")
    if delivery_kind in {"daily_report", "weekly_report"}:
        material: Mapping[str, object] = {
            "version": 2,
            "subject_id": subject_id,
            "delivery_kind": delivery_kind,
            "logical_dates": [
                {
                    "role": item.content_role,
                    "start": item.period_start_local_date,
                    "end": item.period_end_local_date,
                }
                for item in artifacts
            ],
        }
    else:
        material = {
            "version": 2,
            "subject_id": subject_id,
            "delivery_kind": delivery_kind,
            "artifacts": [
                {
                    "role": item.content_role,
                    "id": item.artifact_id,
                    "revision": item.revision_no,
                    "content_sha256": item.content_sha256,
                }
                for item in artifacts
            ],
        }
    digest = sha256(_canonical(material).encode("utf-8")).hexdigest()
    base = f"analysis-delivery:v2:{digest}"
    if resend_authorization is None:
        return base
    return f"{base}:resend:{resend_authorization.authorization_id}"


def _verified_context_snapshot(
    connection: sqlite3.Connection,
    *,
    analysis_run_id: int,
    subject_id: int,
) -> Mapping[str, object] | None:
    """Load only a hash-verified immutable context owned by the analysis run."""

    run_columns = {
        str(column[1])
        for column in connection.execute("PRAGMA table_info(analysis_runs)")
    }
    if not {"context_snapshot_json", "context_snapshot_sha256"}.issubset(run_columns):
        return None
    row = connection.execute(
        "SELECT context_snapshot_json,context_snapshot_sha256 "
        "FROM analysis_runs WHERE id=? AND subject_id=?",
        (analysis_run_id, subject_id),
    ).fetchone()
    if row is None:
        return None
    try:
        snapshot_json = str(row["context_snapshot_json"])
        expected_hash = str(row["context_snapshot_sha256"])
        if sha256(snapshot_json.encode("utf-8")).hexdigest() != expected_hash:
            return None
        snapshot = json.loads(snapshot_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _sleep_chart(
    connection: sqlite3.Connection,
    *,
    analysis_run_id: int,
    subject_id: int,
    advice_local_date: str,
) -> SleepChart | None:
    """Read the exact morning-sleep aggregates frozen into this analysis run."""

    snapshot = _verified_context_snapshot(
        connection,
        analysis_run_id=analysis_run_id,
        subject_id=subject_id,
    )
    sleep_entries = snapshot.get("sleep") if snapshot is not None else None
    if not isinstance(sleep_entries, list):
        return None

    values: dict[str, object] = {}
    source_revision: str | None = None
    for entry in sleep_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("content"), dict):
            continue
        content = entry["content"]
        window = content.get("window")
        latest = content.get("latest")
        if (
            content.get("family") != "morning_sleep"
            or window
            != {
                "start_local_date": advice_local_date,
                "end_local_date": advice_local_date,
            }
            or not isinstance(latest, dict)
            or latest.get("local_date") != advice_local_date
            or content.get("observation_count") != 1
            or content.get("source_count") != 1
            or content.get("source_revision_count") != 1
        ):
            continue
        revisions = content.get("source_revision_ids")
        metric = content.get("metric_key")
        if (
            not isinstance(revisions, list)
            or len(revisions) != 1
            or not isinstance(revisions[0], str)
            or not isinstance(metric, str)
            or metric in values
        ):
            return None
        if source_revision is None:
            source_revision = revisions[0]
        elif source_revision != revisions[0]:
            return None
        values[metric] = latest.get("value")
    names = {
        "sleepTimeSeconds",
        "deepSleepSeconds",
        "lightSleepSeconds",
        "remSleepSeconds",
        "awakeSleepSeconds",
        "unmeasurableSleepSeconds",
    }
    durations: dict[str, int] = {}
    for name in names:
        value = values.get(f"sleep.{name}")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        durations[name] = value
    start_ms = values.get("sleep.sleepStartTimestampGMT")
    end_ms = values.get("sleep.sleepEndTimestampGMT")
    if (
        isinstance(start_ms, bool)
        or not isinstance(start_ms, (int, float))
        or isinstance(end_ms, bool)
        or not isinstance(end_ms, (int, float))
    ):
        return None
    try:
        start = datetime.fromtimestamp(float(start_ms) / 1000, tz=timezone.utc)
        end = datetime.fromtimestamp(float(end_ms) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    window_seconds = int((end - start).total_seconds())
    asleep = durations["sleepTimeSeconds"]
    awake = durations["awakeSleepSeconds"]
    stage_total = (
        durations["deepSleepSeconds"]
        + durations["lightSleepSeconds"]
        + durations["remSleepSeconds"]
    )
    accounted_window = asleep + awake + durations["unmeasurableSleepSeconds"]
    # Garmin may round independently reported stage totals by a few seconds.
    # Accept only a tightly bounded discrepancy; material inconsistencies stay
    # fail-closed and are not rendered.
    if (
        not 0 < window_seconds <= 24 * 60 * 60
        or asleep <= 0
        or abs(stage_total - asleep) > 60
        or abs(accounted_window - window_seconds) > 60
    ):
        return None
    final = (
        values.get("sleep.sleepWindowConfirmed") is True
        and values.get("sleep.sleepWindowConfirmationType")
        == "enhanced_confirmed_final"
        and values.get("sleep.calendarDate") == advice_local_date
        and values.get("sleep.session_type") == "main_sleep"
    )
    local = ZoneInfo("Asia/Hong_Kong")
    return SleepChart(
        completeness="complete" if final else "partial",
        start_local_time=start.astimezone(local).strftime("%H:%M"),
        end_local_time=end.astimezone(local).strftime("%H:%M"),
        window_seconds=window_seconds,
        asleep_seconds=asleep,
        deep_seconds=durations["deepSleepSeconds"],
        light_seconds=durations["lightSleepSeconds"],
        rem_seconds=durations["remSleepSeconds"],
        awake_seconds=awake,
        unmeasurable_seconds=durations["unmeasurableSleepSeconds"],
    )


def _delivery_sleep_chart(
    connection: sqlite3.Connection,
    *,
    delivery_kind: str,
    analysis_run_id: int,
    subject_id: int,
    artifacts: Sequence[DeliveryArtifact],
) -> SleepChart | None:
    if delivery_kind != "daily_report":
        return None
    advice = next(
        (item for item in artifacts if item.content_role == "daily_advice"), None
    )
    if advice is None:
        return None
    return _sleep_chart(
        connection,
        analysis_run_id=analysis_run_id,
        subject_id=subject_id,
        advice_local_date=advice.period_start_local_date,
    )


def _context_metric(
    snapshot: Mapping[str, object],
    *,
    section: str,
    family: str,
    metric_key: str,
) -> Mapping[str, object] | None:
    entries = snapshot.get(section)
    if not isinstance(entries, list):
        return None
    matches: list[Mapping[str, object]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        content = entry.get("content")
        if (
            isinstance(content, Mapping)
            and content.get("family") == family
            and content.get("metric_key") == metric_key
        ):
            matches.append(content)
    return matches[0] if len(matches) == 1 else None


def _numeric_latest(content: Mapping[str, object] | None) -> tuple[float, str] | None:
    if content is None or not isinstance(content.get("latest"), Mapping):
        return None
    latest = cast(Mapping[str, object], content["latest"])
    value, local_date = latest.get("value"), latest.get("local_date")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not isinstance(local_date, str)
    ):
        return None
    try:
        if date.fromisoformat(local_date).isoformat() != local_date:
            return None
    except ValueError:
        return None
    return float(value), local_date


def _numeric_average(content: Mapping[str, object] | None) -> float | None:
    if content is None:
        return None
    value = content.get("average")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    return float(value)


def _metric_value(value: float, *, digits: int = 0) -> str:
    rounded = round(value, digits)
    if digits == 0:
        return str(int(rounded))
    return f"{rounded:.{digits}f}".rstrip("0").rstrip(".")


def _baseline_comparison(
    value: float,
    baseline: float | None,
    *,
    unit: str,
    digits: int,
) -> str:
    if baseline is None:
        return "28日个人基线不可用"
    delta = value - baseline
    sign = "+" if delta > 0 else ""
    return (
        f"较28日基线 {sign}{_metric_value(delta, digits=digits)}{unit}"
        f"（基线 {_metric_value(baseline, digits=digits)}{unit}）"
    )


def _observation_label(local_date: str, advice_local_date: str) -> str:
    if local_date == advice_local_date:
        return "今晨记录"
    parsed = date.fromisoformat(local_date)
    return f"最近记录：{parsed.month}月{parsed.day}日"


def _hrv_metric(
    snapshot: Mapping[str, object], family: str
) -> Mapping[str, object] | None:
    for section in ("health", "sleep"):
        entries = snapshot.get(section)
        if not isinstance(entries, list):
            continue
        matches: list[Mapping[str, object]] = []
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(
                entry.get("content"), Mapping
            ):
                continue
            content = entry["content"]
            key = content.get("metric_key")
            if (
                content.get("family") == family
                and isinstance(key, str)
                and "hrv" in key.casefold()
                and "adjustment" not in key.casefold()
                and _numeric_latest(content) is not None
            ):
                matches.append(content)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            for token in ("last_night_average", "overnight_average", "weekly_average"):
                preferred = [
                    item
                    for item in matches
                    if token in str(item.get("metric_key", "")).casefold()
                ]
                if len(preferred) == 1:
                    return preferred[0]
            return None
    return None


def _recovery_metrics(
    snapshot: Mapping[str, object], *, advice_local_date: str
) -> tuple[RecoveryMetric, ...]:
    specs: list[
        tuple[
            str, str, Mapping[str, object] | None, Mapping[str, object] | None, str, int
        ]
    ] = []
    resting = _context_metric(
        snapshot,
        section="health",
        family="health",
        metric_key="health.garmin.daily.resting_heart_rate_bpm",
    )
    specs.append(("resting_heart_rate", "静息心率", resting, resting, " 次/分钟", 0))
    hrv_current = _hrv_metric(snapshot, "morning_recovery")
    if hrv_current is None:
        hrv_current = _hrv_metric(snapshot, "health")
    hrv_key = str(hrv_current.get("metric_key")) if hrv_current else ""
    hrv_baseline_key = (
        "health." + hrv_key.removeprefix("morning_recovery.")
        if hrv_key.startswith("morning_recovery.")
        else hrv_key
    )
    hrv_baseline = (
        _context_metric(
            snapshot, section="health", family="health", metric_key=hrv_baseline_key
        )
        or _context_metric(
            snapshot, section="sleep", family="sleep", metric_key=hrv_baseline_key
        )
        if hrv_baseline_key
        else None
    )
    specs.append(("hrv", "HRV", hrv_current, hrv_baseline, " ms", 0))
    spo2_current = _context_metric(
        snapshot,
        section="sleep",
        family="morning_sleep",
        metric_key="sleep.averageSpO2Value",
    )
    spo2_baseline = _context_metric(
        snapshot,
        section="sleep",
        family="sleep",
        metric_key="sleep.averageSpO2Value",
    )
    specs.append(("spo2", "平均血氧", spo2_current, spo2_baseline, "%", 1))

    result: list[RecoveryMetric] = []
    for key, label, current, baseline_content, unit, digits in specs:
        latest = _numeric_latest(current)
        if latest is None:
            result.append(
                RecoveryMetric(
                    key=key,  # type: ignore[arg-type]
                    label=label,
                    value_text="未收到",
                    comparison_text="本次分析没有可验证数值",
                    observation_text="不会按正常值处理",
                    available=False,
                )
            )
            continue
        value, observed = latest
        result.append(
            RecoveryMetric(
                key=key,  # type: ignore[arg-type]
                label=label,
                value_text=_metric_value(value, digits=digits) + unit,
                comparison_text=_baseline_comparison(
                    value,
                    _numeric_average(baseline_content),
                    unit=unit,
                    digits=digits,
                ),
                observation_text=_observation_label(observed, advice_local_date),
                available=True,
            )
        )
    return tuple(result)


_SPORT_LABELS = {
    "running": "跑步",
    "cycling": "骑行",
    "bouldering": "抱石",
    "indoor_climbing": "室内攀岩",
    "climbing": "攀岩",
    "strength": "力量训练",
}


def _activity_rows(snapshot: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    entries = snapshot.get("activities")
    if not isinstance(entries, list):
        return ()
    rows: list[Mapping[str, object]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(
            entry.get("content"), Mapping
        ):
            continue
        content = entry["content"]
        digest = content.get("aggregate_sha256")
        if (
            content.get("source_count") != 1
            or content.get("source_revision_count") != 1
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            continue
        rows.append(content)
    return tuple(rows)


def _activity_seconds(row: Mapping[str, object]) -> int | None:
    value = row.get("timer_seconds", row.get("elapsed_seconds"))
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 24 * 60 * 60
    ):
        return None
    return int(round(float(value)))


def _training_load_chart(
    snapshot: Mapping[str, object], *, summary_local_date: str
) -> TrainingLoadChart | None:
    end = date.fromisoformat(summary_local_date)
    start = end - timedelta(days=6)
    totals = {
        date.fromordinal(start.toordinal() + offset).isoformat(): [0, 0]
        for offset in range(7)
    }
    for row in _activity_rows(snapshot):
        local_date = row.get("local_date")
        seconds = _activity_seconds(row)
        if (
            not isinstance(local_date, str)
            or local_date not in totals
            or seconds is None
        ):
            continue
        totals[local_date][0] += seconds
        totals[local_date][1] += 1
    days = tuple(
        TrainingLoadDay(day, values[0], values[1]) for day, values in totals.items()
    )
    activity_count = sum(item.activity_count for item in days)
    if activity_count == 0:
        return None
    return TrainingLoadChart(
        start.isoformat(),
        end.isoformat(),
        sum(item.duration_seconds for item in days),
        activity_count,
        days,
    )


def _weather_text(row: Mapping[str, object]) -> str | None:
    weather = row.get("weather") or row.get("weather_summary")
    if isinstance(weather, str) and weather.strip():
        return weather.strip()
    if not isinstance(weather, Mapping):
        return None
    parts: list[str] = []
    for key, suffix in (("temperature_c", "℃"), ("humidity_percent", "%")):
        value = weather.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(_metric_value(float(value), digits=1) + suffix)
    condition = weather.get("condition")
    if isinstance(condition, str) and condition.strip():
        parts.append(condition.strip())
    return " · ".join(parts) or None


def _yesterday_activities(
    snapshot: Mapping[str, object],
    *,
    summary_local_date: str,
    requested_highlights: Sequence[str] = (),
) -> tuple[ActivityOverview, ...]:
    entries = snapshot.get("activities")
    fit_by_activity: dict[str, Mapping[str, object]] = {}
    weather_by_activity: dict[str, Mapping[str, object]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(
                entry.get("content"), Mapping
            ):
                continue
            content = entry["content"]
            identity = content.get("activity_id")
            if identity is None:
                continue
            if entry.get("role") == "activity.fit_summary":
                fit_by_activity[str(identity)] = content
            elif entry.get("role") == "activity.weather_summary":
                weather_by_activity[str(identity)] = content
    result: list[ActivityOverview] = []
    for row in _activity_rows(snapshot):
        if row.get("local_date") != summary_local_date:
            continue
        seconds = _activity_seconds(row)
        sport = row.get("sport")
        if seconds is None or not isinstance(sport, str):
            continue
        distance = row.get("distance_m")
        distance_value = (
            float(distance)
            if isinstance(distance, (int, float))
            and not isinstance(distance, bool)
            and math.isfinite(float(distance))
            and float(distance) >= 0
            else None
        )
        identity = str(row.get("id"))
        fit = fit_by_activity.get(identity, {})
        weather = weather_by_activity.get(identity, {})
        heart_rate = fit.get("avg_heart_rate_bpm")
        heart_rate_value = (
            float(heart_rate)
            if isinstance(heart_rate, (int, float))
            and not isinstance(heart_rate, bool)
            and math.isfinite(float(heart_rate))
            and 0 < float(heart_rate) < 260
            else None
        )
        max_heart_rate = fit.get("max_heart_rate_bpm")
        max_heart_rate_value = (
            float(max_heart_rate)
            if isinstance(max_heart_rate, (int, float))
            and not isinstance(max_heart_rate, bool)
            and math.isfinite(float(max_heart_rate))
            and 0 < float(max_heart_rate) < 260
            else None
        )
        speed = fit.get("avg_speed_mps")
        pace = (
            1000.0 / float(speed)
            if isinstance(speed, (int, float))
            and not isinstance(speed, bool)
            and math.isfinite(float(speed))
            and float(speed) > 0
            else None
        )
        dynamic: list[str] = []
        highlight_values = {
            "cadence": (fit.get("avg_running_cadence_spm"), "平均步频", " 步/分钟"),
            "power": (fit.get("avg_power_w"), "平均功率", " W"),
            "ascent": (fit.get("total_ascent_m"), "累计爬升", " m"),
        }
        for key in requested_highlights:
            value, label, suffix = highlight_values.get(key, (None, "", ""))
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                dynamic.append(
                    f"{label} {_metric_value(float(value), digits=1)}{suffix}"
                )
            if len(dynamic) == 2:
                break
        result.append(
            ActivityOverview(
                _SPORT_LABELS.get(sport, sport),
                seconds,
                distance_value,
                heart_rate_value,
                _weather_text(weather) or _weather_text(row),
                pace,
                max_heart_rate_value,
                tuple(dynamic),
            )
        )
    return tuple(result[:8])


def _delivery_daily_visuals(
    connection: sqlite3.Connection,
    *,
    delivery_kind: str,
    analysis_run_id: int,
    subject_id: int,
    artifacts: Sequence[DeliveryArtifact],
) -> tuple[
    tuple[RecoveryMetric, ...], TrainingLoadChart | None, tuple[ActivityOverview, ...]
]:
    if delivery_kind != "daily_report":
        return (), None, ()
    summary = next(
        (item for item in artifacts if item.content_role == "daily_summary"), None
    )
    advice = next(
        (item for item in artifacts if item.content_role == "daily_advice"), None
    )
    snapshot = _verified_context_snapshot(
        connection,
        analysis_run_id=analysis_run_id,
        subject_id=subject_id,
    )
    if summary is None or advice is None or snapshot is None:
        return (), None, ()
    highlights = summary.structured_content_json.get("activity_highlights", [])
    highlight_values = highlights if isinstance(highlights, list) else []
    return (
        _recovery_metrics(snapshot, advice_local_date=advice.period_start_local_date),
        _training_load_chart(
            snapshot, summary_local_date=summary.period_start_local_date
        ),
        _yesterday_activities(
            snapshot,
            summary_local_date=summary.period_start_local_date,
            requested_highlights=tuple(
                value for value in highlight_values if isinstance(value, str)
            ),
        ),
    )


class AnalysisDeliveryFactory:
    """Seed one pending delivery in a short transaction, with no send capability."""

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], str] = _now
    ) -> None:
        self._connection = connection
        self._clock = clock

    def create_pending(
        self,
        *,
        publish_receipt: _PublishReceiptLike | Mapping[str, object],
        delivery_kind: DeliveryKind,
        resend_authorization: ResendAuthorization | None = None,
    ) -> PendingDelivery:
        run_id, artifact_ids = _receipt_values(publish_receipt)
        shape = _DELIVERY_SHAPES.get(delivery_kind)
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        self._connection.execute("PRAGMA foreign_keys=ON")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            pending = self._create_in_transaction(
                run_id, artifact_ids, delivery_kind, shape, resend_authorization
            )
            self._connection.execute("COMMIT")
            return pending
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def create_pending_in_transaction(
        self,
        *,
        publish_receipt: _PublishReceiptLike | Mapping[str, object],
        delivery_kind: DeliveryKind,
        resend_authorization: ResendAuthorization | None = None,
    ) -> PendingDelivery:
        """Seed pending delivery inside a caller-owned publication transaction."""
        if not self._connection.in_transaction:
            raise AnalysisDeliveryError("analysis_delivery_transaction_required")
        run_id, artifact_ids = _receipt_values(publish_receipt)
        shape = _DELIVERY_SHAPES.get(delivery_kind)
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        return self._create_in_transaction(
            run_id, artifact_ids, delivery_kind, shape, resend_authorization
        )

    def prepare(
        self,
        *,
        publish_receipt: _PublishReceiptLike | Mapping[str, object],
        delivery_kind: DeliveryKind,
        resend_authorization: ResendAuthorization | None = None,
        renderer: Callable[[PendingDelivery], RenderedDelivery] = None,  # type: ignore[assignment]
    ) -> tuple[PendingDelivery, RenderedDelivery]:
        """Commit the pending seed before rendering, so render failures are recoverable."""
        pending = self.create_pending(
            publish_receipt=publish_receipt,
            delivery_kind=delivery_kind,
            resend_authorization=resend_authorization,
        )
        return pending, (render_delivery if renderer is None else renderer)(pending)

    def _create_in_transaction(
        self,
        run_id: int,
        artifact_ids: Mapping[str, int],
        delivery_kind: str,
        shape: tuple[tuple[str, str], ...],
        resend_authorization: ResendAuthorization | None,
    ) -> PendingDelivery:
        if set(artifact_ids) != {artifact_kind for artifact_kind, _ in shape}:
            raise AnalysisDeliveryError("analysis_delivery_artifact_set_invalid")
        run = self._connection.execute(
            "SELECT id,subject_id,run_key FROM analysis_runs WHERE id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise AnalysisDeliveryError("analysis_delivery_run_missing")
        artifacts: list[DeliveryArtifact] = []
        for artifact_kind, content_role in shape:
            row = self._connection.execute(
                "SELECT id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,content_sha256,user_visible_text,structured_content_json,generated_by_run_id,created_at_utc "
                "FROM analysis_artifacts WHERE id=?",
                (artifact_ids[artifact_kind],),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != run["subject_id"]
                or row["generated_by_run_id"] != run_id
                or row["artifact_kind"] != artifact_kind
            ):
                raise AnalysisDeliveryError(
                    "analysis_delivery_artifact_not_published_by_run"
                )
            artifacts.append(
                DeliveryArtifact(
                    artifact_id=int(row["id"]),
                    artifact_kind=str(row["artifact_kind"]),
                    content_role=content_role,
                    revision_no=int(row["revision_no"]),
                    content_sha256=str(row["content_sha256"]),
                    user_visible_text=str(row["user_visible_text"]),
                    period_start_local_date=_local_date(row["period_start_local_date"]),
                    period_end_local_date=_local_date(row["period_end_local_date"]),
                    structured_content_json=_structured_content(
                        row["structured_content_json"]
                    ),
                    created_at_utc=str(row["created_at_utc"]),
                )
            )
        run_key = _safe_header(str(run["run_key"]))
        business_key = _idempotency_key(
            int(run["subject_id"]), delivery_kind, artifacts
        )
        key = _idempotency_key(
            int(run["subject_id"]),
            cast(DeliveryKind, delivery_kind),
            artifacts,
            resend_authorization=resend_authorization,
        )
        existing = self._connection.execute(
            "SELECT id,subject_id,analysis_run_id,delivery_kind FROM analysis_deliveries WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if existing is not None:
            if (
                existing["subject_id"] != run["subject_id"]
                or existing["delivery_kind"] != delivery_kind
            ):
                raise AnalysisDeliveryError("analysis_delivery_idempotency_conflict")
            return self._pending_from_delivery(int(existing["id"]))
        original = self._connection.execute(
            "SELECT id FROM analysis_deliveries WHERE idempotency_key=?",
            (business_key,),
        ).fetchone()
        if original is not None and resend_authorization is None:
            return self._pending_from_delivery(int(original["id"]))
        if original is None and resend_authorization is not None:
            raise AnalysisDeliveryError("analysis_delivery_resend_not_required")
        if original is not None and delivery_kind not in {
            "daily_report",
            "weekly_report",
        }:
            raise AnalysisDeliveryError("analysis_delivery_resend_unsupported")
        if original is not None and resend_authorization is not None:
            # The explicit authorization is embedded in the otherwise opaque,
            # immutable key of this separate formal delivery record.
            pass
        if original is None or resend_authorization is not None:
            now = self._clock()
            cursor = self._connection.execute(
                "INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,created_at_utc,updated_at_utc) "
                "VALUES(?,?,?,?, 'pending',?,?)",
                (run["subject_id"], key, run_id, delivery_kind, now, now),
            )
            if cursor.lastrowid is None:
                raise AnalysisDeliveryError("analysis_delivery_insert_failed")
            delivery_id = int(cursor.lastrowid)
            for ordinal, artifact in enumerate(artifacts):
                self._connection.execute(
                    "INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)",
                    (delivery_id, artifact.artifact_id, artifact.content_role, ordinal),
                )
        sleep_chart = _delivery_sleep_chart(
            self._connection,
            delivery_kind=delivery_kind,
            analysis_run_id=run_id,
            subject_id=int(run["subject_id"]),
            artifacts=artifacts,
        )
        recovery_metrics, training_load_chart, yesterday_activities = (
            _delivery_daily_visuals(
                self._connection,
                delivery_kind=delivery_kind,
                analysis_run_id=run_id,
                subject_id=int(run["subject_id"]),
                artifacts=artifacts,
            )
        )
        return PendingDelivery(
            delivery_id,
            int(run["subject_id"]),
            run_id,
            run_key,
            cast(DeliveryKind, delivery_kind),
            key,
            tuple(artifacts),
            sleep_chart,
            recovery_metrics,
            training_load_chart,
            yesterday_activities,
            _zone_comparison_lines(
                self._connection,
                delivery_kind=delivery_kind,
                subject_id=int(run["subject_id"]),
            ),
            resend_authorization.authorization_id if resend_authorization else None,
        )

    def _pending_from_delivery(self, delivery_id: int) -> PendingDelivery:
        """Return the original immutable report when business delivery repeats."""
        return AnalysisDeliveryRepository(
            self._connection, clock=self._clock
        ).load_pending(delivery_id)

    def _verify_existing_relations(
        self, delivery_id: int, expected: Sequence[DeliveryArtifact]
    ) -> None:
        actual = self._connection.execute(
            "SELECT analysis_artifact_id,content_role,ordinal FROM analysis_delivery_artifacts WHERE analysis_delivery_id=? ORDER BY ordinal",
            (delivery_id,),
        ).fetchall()
        triples = [
            (
                int(row["analysis_artifact_id"]),
                str(row["content_role"]),
                int(row["ordinal"]),
            )
            for row in actual
        ]
        wanted = [
            (item.artifact_id, item.content_role, ordinal)
            for ordinal, item in enumerate(expected)
        ]
        if triples != wanted:
            raise AnalysisDeliveryError("analysis_delivery_relation_conflict")


class AnalysisDeliveryRepository:
    """Fail-closed SQLite state machine for one immutable analysis delivery.

    This repository deliberately has no Gmail dependency.  A future provider
    runner must claim a record, perform its external work, and then call one of
    the evidence-recording methods below.  Every write re-reads the immutable
    artifact relation in the same short ``BEGIN IMMEDIATE`` transaction.
    """

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], str] = _now
    ) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._clock = clock

    def load_pending(
        self, delivery_id: int, *, subject_id: int | None = None
    ) -> PendingDelivery:
        """Load exactly the revisions linked to one delivery, never current rows."""
        self._validate_identifier(delivery_id, "analysis_delivery_id_invalid")
        if subject_id is not None:
            self._validate_identifier(subject_id, "analysis_delivery_subject_invalid")
        row, artifacts = self._load_verified(delivery_id)
        if subject_id is not None and int(row["subject_id"]) != subject_id:
            raise AnalysisDeliveryError("analysis_delivery_ownership_invalid")
        sleep_chart = _delivery_sleep_chart(
            self._connection,
            delivery_kind=cast(DeliveryKind, str(row["delivery_kind"])),
            analysis_run_id=int(row["analysis_run_id"]),
            subject_id=int(row["subject_id"]),
            artifacts=artifacts,
        )
        recovery_metrics, training_load_chart, yesterday_activities = (
            _delivery_daily_visuals(
                self._connection,
                delivery_kind=str(row["delivery_kind"]),
                analysis_run_id=int(row["analysis_run_id"]),
                subject_id=int(row["subject_id"]),
                artifacts=artifacts,
            )
        )
        return PendingDelivery(
            delivery_id=int(row["id"]),
            subject_id=int(row["subject_id"]),
            analysis_run_id=int(row["analysis_run_id"]),
            run_key=str(row["run_key"]),
            delivery_kind=cast(DeliveryKind, str(row["delivery_kind"])),
            idempotency_key=str(row["idempotency_key"]),
            artifacts=tuple(artifacts),
            sleep_chart=sleep_chart,
            recovery_metrics=recovery_metrics,
            training_load_chart=training_load_chart,
            yesterday_activities=yesterday_activities,
            heart_rate_zone_comparison=_zone_comparison_lines(
                self._connection,
                delivery_kind=str(row["delivery_kind"]),
                subject_id=int(row["subject_id"]),
            ),
        )

    def load_rendered(
        self, delivery_id: int, *, subject_id: int | None = None
    ) -> RenderedDelivery:
        """Re-render the delivery's original revisions; never follow ``is_current``."""
        return render_delivery(self.load_pending(delivery_id, subject_id=subject_id))

    # Explicit aliases keep provider code readable without exposing raw rows.
    load_pending_delivery = load_pending
    load_rendered_delivery = load_rendered

    def read_state(
        self, delivery_id: int, *, subject_id: int | None = None
    ) -> AnalysisDeliveryState:
        pending = self.load_pending(delivery_id, subject_id=subject_id)
        row = self._connection.execute(
            "SELECT * FROM analysis_deliveries WHERE id=?", (pending.delivery_id,)
        ).fetchone()
        if (
            row is None
        ):  # Defensive: a concurrent destructive writer is not a valid replay.
            raise AnalysisDeliveryError("analysis_delivery_missing")
        return self._state_from_row(row)

    get_state = read_state

    def claim_for_send(
        self, subject_id: int, delivery_id: int
    ) -> AnalysisDeliveryState:
        """Atomically claim a pending/failed record. Unknown records are never resent."""
        return self.transition_delivery_state(subject_id, delivery_id, "sending")

    def record_sent(
        self,
        subject_id: int,
        delivery_id: int,
        *,
        provider_message_id: str,
        provider_thread_id: str | None = None,
        sent_at_utc: str,
        last_verified_at_utc: str,
    ) -> AnalysisDeliveryState:
        return self.transition_delivery_state(
            subject_id,
            delivery_id,
            "sent",
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            sent_at_utc=sent_at_utc,
            last_verified_at_utc=last_verified_at_utc,
        )

    def record_search_match(
        self,
        subject_id: int,
        delivery_id: int,
        *,
        provider_message_id: str,
        provider_thread_id: str | None = None,
        sent_at_utc: str,
        last_verified_at_utc: str,
    ) -> AnalysisDeliveryState:
        """Persist one exact provider search result as already-sent evidence."""
        return self.transition_delivery_state(
            subject_id,
            delivery_id,
            "already_sent",
            recovery_kind="reconcile",
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            sent_at_utc=sent_at_utc,
            last_verified_at_utc=last_verified_at_utc,
        )

    def record_failed(
        self, subject_id: int, delivery_id: int, *, error_code: str
    ) -> AnalysisDeliveryState:
        return self.transition_delivery_state(
            subject_id, delivery_id, "failed", error_code=error_code
        )

    def record_delivery_unknown(
        self,
        subject_id: int,
        delivery_id: int,
        *,
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
        error_code: str,
    ) -> AnalysisDeliveryState:
        """Use after an ambiguous send or a post-send label failure; do not retry it."""
        return self.transition_delivery_state(
            subject_id,
            delivery_id,
            "delivery_unknown",
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            error_code=error_code,
        )

    def transition_delivery_state(
        self,
        subject_id: int,
        delivery_id: int,
        status: str,
        *,
        recovery_kind: str = "normal",
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
        sent_at_utc: str | None = None,
        last_verified_at_utc: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> AnalysisDeliveryState:
        """CAS transition with durable, minimal evidence.

        ``error_summary`` is accepted only for API compatibility and is never
        persisted: provider/model text may contain private health or mailbox
        data.  The stable summary is derived from a validated error code.
        """
        del error_summary
        self._validate_identifier(subject_id, "analysis_delivery_subject_invalid")
        self._validate_identifier(delivery_id, "analysis_delivery_id_invalid")
        if status not in _DELIVERY_STATUSES or recovery_kind not in {
            "normal",
            "reconcile",
        }:
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        self._validate_provider_id(provider_message_id)
        self._validate_provider_id(provider_thread_id)
        if sent_at_utc is not None and not self._canonical_utc(sent_at_utc):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if last_verified_at_utc is not None and not self._canonical_utc(
            last_verified_at_utc
        ):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if error_code is not None and not _SAFE_ERROR_CODE.fullmatch(error_code):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if status in {"sent", "already_sent"} and (
            provider_message_id is None
            or sent_at_utc is None
            or last_verified_at_utc is None
        ):
            raise AnalysisDeliveryError("analysis_delivery_evidence_required")
        if status in {"sending", "sent", "already_sent"} and error_code is not None:
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if status in {"failed", "delivery_unknown"} and error_code is None:
            raise AnalysisDeliveryError("analysis_delivery_error_required")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row, _ = self._load_verified(delivery_id)
            if int(row["subject_id"]) != subject_id:
                raise AnalysisDeliveryError("analysis_delivery_ownership_invalid")
            current = str(row["status"])
            if current == status:
                state = self._state_from_row(row)
                if current in {"sent", "already_sent"} and self._replay_matches(
                    state,
                    provider_message_id,
                    provider_thread_id,
                    sent_at_utc,
                    last_verified_at_utc,
                    error_code,
                ):
                    self._connection.execute("COMMIT")
                    return state
                raise AnalysisDeliveryError(
                    "analysis_delivery_replay_conflict"
                    if current in {"sent", "already_sent"}
                    else "analysis_delivery_transition_illegal"
                )
            if not self._permitted(current, status, recovery_kind):
                raise AnalysisDeliveryError("analysis_delivery_transition_illegal")

            message_id = self._immutable_provider_value(
                row["provider_message_id"], provider_message_id
            )
            thread_id = self._immutable_provider_value(
                row["provider_thread_id"], provider_thread_id
            )
            if status in {"sent", "already_sent"} and message_id is None:
                raise AnalysisDeliveryError("analysis_delivery_evidence_required")
            # An ambiguous record intentionally remains non-sendable even when
            # Gmail accepted a message but applying the label later failed.
            stored_error_code = (
                error_code if status in {"failed", "delivery_unknown"} else None
            )
            stored_error_summary = (
                _DELIVERY_FAILURE_SUMMARY if stored_error_code is not None else None
            )
            cursor = self._connection.execute(
                "UPDATE analysis_deliveries SET provider_message_id=?,provider_thread_id=?,status=?,sent_at_utc=?,"
                "last_verified_at_utc=?,error_code=?,error_summary=?,updated_at_utc=? WHERE id=? AND status=?",
                (
                    message_id,
                    thread_id,
                    status,
                    sent_at_utc,
                    last_verified_at_utc,
                    stored_error_code,
                    stored_error_summary,
                    self._clock(),
                    delivery_id,
                    current,
                ),
            )
            if cursor.rowcount != 1:
                raise AnalysisDeliveryError("analysis_delivery_compare_and_swap_failed")
            updated = self._connection.execute(
                "SELECT * FROM analysis_deliveries WHERE id=?", (delivery_id,)
            ).fetchone()
            if updated is None:
                raise AnalysisDeliveryError("analysis_delivery_missing")
            self._connection.execute("COMMIT")
            return self._state_from_row(updated)
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _validate_identifier(value: object, code: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AnalysisDeliveryError(code)

    @staticmethod
    def _validate_provider_id(value: str | None) -> None:
        if value is not None and (
            not isinstance(value, str) or not _SAFE_PROVIDER_ID.fullmatch(value)
        ):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")

    @staticmethod
    def _canonical_utc(value: str) -> bool:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            value.endswith("Z")
            and parsed.tzinfo is not None
            and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
        )

    @staticmethod
    def _immutable_provider_value(existing: object, supplied: str | None) -> str | None:
        if existing is not None and supplied not in {None, existing}:
            raise AnalysisDeliveryError("analysis_delivery_provider_evidence_conflict")
        return str(existing) if existing is not None else supplied

    @staticmethod
    def _permitted(current: str, target: str, recovery_kind: str) -> bool:
        if current in {"sent", "already_sent"}:
            return False
        if target == "sending":
            return recovery_kind == "normal" and current in {"pending", "failed"}
        if target in {"sent", "already_sent"}:
            if current == "sending" and target == "sent":
                return recovery_kind == "normal"
            # A provider search is the only route to already_sent. It can also
            # reconcile an ambiguous outcome, but never authorizes a re-send.
            return recovery_kind == "reconcile" and current in {
                "pending",
                "sending",
                "delivery_unknown",
                "failed",
            }
        if target in {"failed", "delivery_unknown"}:
            return recovery_kind == "normal" and current == "sending"
        return False

    @staticmethod
    def _replay_matches(
        state: AnalysisDeliveryState,
        provider_message_id: str | None,
        provider_thread_id: str | None,
        sent_at_utc: str | None,
        last_verified_at_utc: str | None,
        error_code: str | None,
    ) -> bool:
        wanted = (
            state.provider_message_id
            if provider_message_id is None
            else provider_message_id,
            state.provider_thread_id
            if provider_thread_id is None
            else provider_thread_id,
            state.sent_at_utc if sent_at_utc is None else sent_at_utc,
            state.last_verified_at_utc
            if last_verified_at_utc is None
            else last_verified_at_utc,
            state.error_code if error_code is None else error_code,
        )
        return wanted == (
            state.provider_message_id,
            state.provider_thread_id,
            state.sent_at_utc,
            state.last_verified_at_utc,
            state.error_code,
        )

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> AnalysisDeliveryState:
        return AnalysisDeliveryState(
            delivery_id=int(row["id"]),
            subject_id=int(row["subject_id"]),
            analysis_run_id=int(row["analysis_run_id"]),
            status=str(row["status"]),
            provider_message_id=row["provider_message_id"],
            provider_thread_id=row["provider_thread_id"],
            sent_at_utc=row["sent_at_utc"],
            last_verified_at_utc=row["last_verified_at_utc"],
            error_code=row["error_code"],
            error_summary=row["error_summary"],
        )

    def _load_verified(
        self, delivery_id: int
    ) -> tuple[sqlite3.Row, list[DeliveryArtifact]]:
        row = self._connection.execute(
            "SELECT d.*,r.run_key,r.subject_id AS run_subject_id FROM analysis_deliveries d "
            "JOIN analysis_runs r ON r.id=d.analysis_run_id WHERE d.id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise AnalysisDeliveryError("analysis_delivery_missing")
        if int(row["subject_id"]) != int(row["run_subject_id"]):
            raise AnalysisDeliveryError("analysis_delivery_run_subject_conflict")
        shape = _DELIVERY_SHAPES.get(str(row["delivery_kind"]))
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        links = self._connection.execute(
            "SELECT a.id AS link_id,a.analysis_artifact_id,a.content_role,a.ordinal,"
            "x.subject_id,x.artifact_kind,x.period_start_local_date,x.period_end_local_date,x.revision_no,x.content_sha256,x.user_visible_text,x.structured_content_json,x.generated_by_run_id,x.created_at_utc "
            "FROM analysis_delivery_artifacts a JOIN analysis_artifacts x ON x.id=a.analysis_artifact_id "
            "WHERE a.analysis_delivery_id=? ORDER BY a.ordinal",
            (delivery_id,),
        ).fetchall()
        expected = [(kind, role, ordinal) for ordinal, (kind, role) in enumerate(shape)]
        actual = [
            (
                str(item["artifact_kind"]),
                str(item["content_role"]),
                int(item["ordinal"]),
            )
            for item in links
        ]
        if actual != expected:
            raise AnalysisDeliveryError("analysis_delivery_relation_conflict")
        artifacts: list[DeliveryArtifact] = []
        for item, (_, role, _) in zip(links, expected, strict=True):
            if int(item["subject_id"]) != int(row["subject_id"]) or int(
                item["generated_by_run_id"]
            ) != int(row["analysis_run_id"]):
                raise AnalysisDeliveryError(
                    "analysis_delivery_artifact_not_published_by_run"
                )
            artifacts.append(
                DeliveryArtifact(
                    artifact_id=int(item["analysis_artifact_id"]),
                    artifact_kind=str(item["artifact_kind"]),
                    content_role=role,
                    revision_no=int(item["revision_no"]),
                    content_sha256=str(item["content_sha256"]),
                    user_visible_text=str(item["user_visible_text"]),
                    period_start_local_date=_local_date(
                        item["period_start_local_date"]
                    ),
                    period_end_local_date=_local_date(item["period_end_local_date"]),
                    structured_content_json=_structured_content(
                        item["structured_content_json"]
                    ),
                    created_at_utc=str(item["created_at_utc"]),
                )
            )
        key = str(row["idempotency_key"])
        base_key = _idempotency_key(
            int(row["subject_id"]), str(row["delivery_kind"]), artifacts
        )
        if key != base_key and not key.startswith(base_key + ":resend:"):
            raise AnalysisDeliveryError("analysis_delivery_idempotency_conflict")
        return row, artifacts


_ACTIVITY = {"running": "跑步", "rest": "休息"}
_ROLE = {
    "easy": "轻松跑",
    "long": "长距离跑",
    "tempo": "节奏跑",
    "speed": "速度训练",
    "running_strength": "跑步力量训练",
}
_COURSE = {
    "easy": "轻松跑",
    "long_easy": "长距离轻松跑",
    "steady": "稳定跑",
    "intervals": "间歇跑",
}
_ROLE_COURSE = {
    "easy": "easy",
    "long": "long_easy",
    "tempo": "steady",
    "speed": "intervals",
    "running_strength": "intervals",
}
_COMPLETENESS = {"complete": "完整", "partial": "部分完整", "limited": "有限"}
_ACTIVITY_EVIDENCE = {
    "confirmed_recorded": "已确认有活动",
    "confirmed_no_recorded_activity": "已确认无记录活动",
    "partial": "活动数据不完整",
    "unconfirmed": "活动记录尚未确认",
}
_PLAN_EVIDENCE = {
    "available": "已有正式训练计划",
    "partial": "训练计划信息不完整",
    "unavailable": "未提供正式训练计划",
}
_PRESCRIPTION_TEXT = {
    "gentle_warmup": "轻柔热身，逐步进入跑步状态",
    "talk_test_easy": "以能够完整说句子的体感轻松跑",
    "structured_intervals": "按计划完成间歇主训练",
    "gentle_cooldown": "逐步降速并完成冷身",
    "easy_by_duration": "按计划时长完成轻松跑",
    "interval_session_by_duration": "按计划时长完成间歇训练",
    "full_sentences": "能够完整说句子",
    "short_phrases": "只能说短句",
}
_STOP_CONDITIONS = {
    "acute_pain": "出现急性疼痛",
    "chest_pain": "出现胸痛",
    "fainting_or_dizziness": "出现晕厥或明显头晕",
    "unusual_shortness_of_breath": "出现异常呼吸困难",
}
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_CONFIDENCE = frozenset({"较高", "一般", "较低"})
_SLEEP_COMPLETENESS = {
    "complete": "已收到一条时间与阶段均闭合、且由设备最终确认的主睡眠记录",
    "partial": "已收到睡眠记录，但尚未满足最终确认或完整闭合条件",
    "unavailable": "未获得与本日报输入绑定的可验证睡眠记录；相关结论按保守方式处理",
}


def _display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def _duration_label(seconds: int) -> str:
    minutes = int(round(seconds / 60))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}小时{remainder}分钟"
    if hours:
        return f"{hours}小时"
    return f"{remainder}分钟"


def _sleep_chart_segments(chart: SleepChart) -> tuple[Element, ...]:
    stages = (
        ("深睡", chart.deep_seconds, "#315C8C"),
        ("浅睡", chart.light_seconds, "#76A7D8"),
        ("REM", chart.rem_seconds, "#8B78C6"),
        ("清醒", chart.awake_seconds, "#D3B66F"),
        ("未测", chart.unmeasurable_seconds, "#B8C1CC"),
    )
    chart_total = sum(seconds for _, seconds, _ in stages)
    if chart_total <= 0:
        return ()
    segments: list[Element] = []
    for label, seconds, color in stages:
        if seconds <= 0:
            continue
        width = f"{seconds * 100 / chart_total:.2f}%"
        segments.append(
            element(
                "td",
                text(" "),
                attributes={
                    "width": width,
                    "bgcolor": color,
                    "aria-label": f"{label} {_duration_label(seconds)}",
                    "style": f"width:{width};height:18px;background:{color};font-size:1px;line-height:18px;",
                },
            )
        )
    return tuple(segments)


def _sleep_chart_legend(chart: SleepChart) -> tuple[Element, ...]:
    stages = (
        ("深睡", chart.deep_seconds, "#315C8C"),
        ("浅睡", chart.light_seconds, "#76A7D8"),
        ("REM", chart.rem_seconds, "#8B78C6"),
        ("清醒", chart.awake_seconds, "#D3B66F"),
        ("未测", chart.unmeasurable_seconds, "#B8C1CC"),
    )
    return tuple(
        element(
            "td",
            element(
                "span",
                text(" "),
                attributes={
                    "style": f"display:inline-block;width:9px;height:9px;margin-right:5px;background:{color};border-radius:2px;"
                },
            ),
            text(f"{label} {_duration_label(seconds)}"),
            attributes={
                "valign": "top",
                "style": "padding:7px 12px 0 0;font-size:11px;line-height:1.5;color:#627184;white-space:nowrap;",
            },
        )
        for label, seconds, color in stages
        if seconds > 0
    )


def _recovery_metric_cells(metrics: Sequence[RecoveryMetric]) -> tuple[Element, ...]:
    cells: list[Element] = []
    for index, metric in enumerate(metrics):
        border = "border-right:1px solid #D8E2E5;" if index < len(metrics) - 1 else ""
        cells.append(
            element(
                "td",
                element(
                    "div",
                    text(metric.label),
                    attributes={
                        "style": "font-size:11px;line-height:1.3;font-weight:600;letter-spacing:.04em;color:#627184;"
                    },
                ),
                element(
                    "div",
                    text(metric.value_text),
                    attributes={
                        "style": "margin-top:6px;font-size:20px;line-height:1.3;font-weight:600;color:#142337;"
                    },
                ),
                element(
                    "div",
                    text(metric.comparison_text),
                    attributes={
                        "style": "margin-top:5px;font-size:11px;line-height:1.55;color:#33445A;"
                    },
                ),
                element(
                    "div",
                    text(metric.observation_text),
                    attributes={
                        "style": "margin-top:3px;font-size:10px;line-height:1.5;color:#8290A0;"
                    },
                ),
                attributes={
                    "class": "stat-cell",
                    "width": f"{100 / max(len(metrics), 1):.2f}%",
                    "valign": "top",
                    "style": f"padding:0 14px 2px;{border}",
                },
            )
        )
    return tuple(cells)


def _load_day_label(local_date: str) -> str:
    parsed = date.fromisoformat(local_date)
    weekdays = ("一", "二", "三", "四", "五", "六", "日")
    return f"周{weekdays[parsed.weekday()]} {parsed.month}/{parsed.day}"


def _training_load_rows(chart: TrainingLoadChart) -> tuple[Element, ...]:
    maximum = max((item.duration_seconds for item in chart.days), default=0)
    rows: list[Element] = []
    for day in chart.days:
        width = 0 if maximum <= 0 else day.duration_seconds * 100 / maximum
        bar = element(
            "table",
            element(
                "tr",
                element(
                    "td",
                    text(" "),
                    attributes={
                        "width": f"{width:.2f}%",
                        "bgcolor": "#237F8E",
                        "style": f"width:{width:.2f}%;height:9px;background:#237F8E;font-size:1px;line-height:9px;",
                    },
                )
                if width > 0
                else element(
                    "td",
                    text(" "),
                    attributes={"style": "height:9px;font-size:1px;line-height:9px;"},
                ),
            ),
            attributes={
                "role": "presentation",
                "width": "100%",
                "cellpadding": "0",
                "cellspacing": "0",
                "border": "0",
                "style": "width:100%;background:#EAF0F2;border-radius:5px;overflow:hidden;",
            },
        )
        rows.append(
            element(
                "tr",
                element(
                    "td",
                    text(_load_day_label(day.local_date)),
                    attributes={
                        "width": "76",
                        "style": "padding:5px 10px 5px 0;font-size:11px;line-height:1.4;color:#627184;white-space:nowrap;",
                    },
                ),
                element(
                    "td",
                    bar,
                    attributes={"style": "padding:5px 12px 5px 0;"},
                ),
                element(
                    "td",
                    text(_duration_label(day.duration_seconds)),
                    attributes={
                        "width": "72",
                        "align": "right",
                        "style": "padding:5px 0;font-size:11px;line-height:1.4;color:#33445A;white-space:nowrap;",
                    },
                ),
            )
        )
    return tuple(rows)


def _activity_overview_rows(
    activities: Sequence[ActivityOverview],
) -> tuple[Element, ...]:
    rows: list[Element] = []
    for activity in activities:
        details = [f"时长 {_duration_label(activity.duration_seconds)}"]
        if activity.distance_m is not None:
            details.append(
                f"距离 {_metric_value(activity.distance_m / 1000, digits=2)} km"
            )
        if activity.average_pace_seconds_per_km is not None:
            minutes, seconds = divmod(
                int(round(activity.average_pace_seconds_per_km)), 60
            )
            details.append(f"平均配速 {minutes}:{seconds:02d}/km")
        if activity.average_heart_rate_bpm is not None:
            details.append(
                f"平均心率 {_metric_value(activity.average_heart_rate_bpm)} 次/分钟"
            )
        if activity.maximum_heart_rate_bpm is not None:
            details.append(
                f"最高心率 {_metric_value(activity.maximum_heart_rate_bpm)} 次/分钟"
            )
        details.extend(activity.highlight_metrics)
        if activity.weather_text:
            details.append(f"天气 {activity.weather_text}")
        rows.append(
            element(
                "tr",
                element(
                    "td",
                    text(activity.sport_label),
                    attributes={
                        "width": "86",
                        "valign": "top",
                        "style": "padding:7px 12px 7px 0;font-size:12px;line-height:1.5;font-weight:600;color:#142337;",
                    },
                ),
                element(
                    "td",
                    text(" · ".join(details)),
                    attributes={
                        "style": "padding:7px 0;font-size:12px;line-height:1.6;color:#33445A;"
                    },
                ),
            )
        )
    return tuple(rows)


def _recovery_plain(metrics: Sequence[RecoveryMetric]) -> str:
    return "；".join(
        f"{item.label}{item.value_text}，{item.comparison_text}，{item.observation_text}"
        for item in metrics
    )


def _training_load_plain(chart: TrainingLoadChart) -> str:
    days = "、".join(
        f"{_load_day_label(item.local_date)} {_duration_label(item.duration_seconds)}"
        for item in chart.days
    )
    return (
        f"最近7日共{chart.activity_count}次活动、{_duration_label(chart.total_seconds)}；"
        + days
    )


def _activities_plain(activities: Sequence[ActivityOverview]) -> str:
    values: list[str] = []
    for activity in activities:
        details = [activity.sport_label, _duration_label(activity.duration_seconds)]
        if activity.distance_m is not None:
            details.append(_metric_value(activity.distance_m / 1000, digits=2) + " km")
        if activity.average_pace_seconds_per_km is not None:
            minutes, seconds = divmod(
                int(round(activity.average_pace_seconds_per_km)), 60
            )
            details.append(f"{minutes}:{seconds:02d}/km")
        if activity.average_heart_rate_bpm is not None:
            details.append(_metric_value(activity.average_heart_rate_bpm) + " 次/分钟")
        if activity.maximum_heart_rate_bpm is not None:
            details.append(
                "最高 " + _metric_value(activity.maximum_heart_rate_bpm) + " 次/分钟"
            )
        details.extend(activity.highlight_metrics)
        if activity.weather_text:
            details.append(activity.weather_text)
        values.append(" · ".join(details))
    return "；".join(values)


def _text(value: object, *, neutral: str = "未提供") -> str:
    return value if isinstance(value, str) and value.strip() else neutral


def _number(value: object, *, suffix: str = "") -> str:
    return (
        f"{value}{suffix}"
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else "未提供"
    )


def _date_label(value: object, *, neutral: str = "未设置") -> str:
    if not isinstance(value, str):
        return neutral
    try:
        return _display_date(_local_date(value))
    except AnalysisDeliveryError:
        return neutral


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _activity_weather_summary(value: object) -> str:
    """Render only bounded, human-readable activity/weather evidence.

    Weekly artifacts may carry a structured ``actual_activities`` list.  The
    renderer intentionally selects a small allow-list of fields instead of
    exposing identifiers or serializing arbitrary JSON into the email.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, list):
        return "本周实际活动与天气明细未随本次报告提供；请以数据说明和后续补录为准。"
    lines: list[str] = []
    for item in value[:14]:
        if not isinstance(item, Mapping):
            continue
        day = _date_label(item.get("local_date"), neutral="日期未提供")
        sport = (
            _scalar(
                item.get("sport")
                or item.get("activity_kind")
                or item.get("activity_type")
            )
            or "活动"
        )
        details: list[str] = []
        for key, label, suffix in (
            ("duration_minutes", "时长", " 分钟"),
            ("distance_km", "距离", " km"),
            ("average_heart_rate_bpm", "平均心率", " 次/分钟"),
        ):
            scalar = _scalar(item.get(key))
            if scalar:
                details.append(f"{label}{scalar}{suffix}")
        weather = item.get("weather") or item.get("weather_summary")
        weather_text = _scalar(weather)
        if not weather_text and isinstance(weather, Mapping):
            weather_parts: list[str] = []
            for key, label, suffix in (
                ("temperature_c", "温度", "℃"),
                ("humidity_percent", "湿度", "%"),
                ("condition", "天气", ""),
            ):
                scalar = _scalar(weather.get(key))
                if scalar:
                    weather_parts.append(f"{label}{scalar}{suffix}")
            weather_text = "，".join(weather_parts)
        if weather_text:
            details.append(f"天气：{weather_text}")
        suffix = "；".join(details)
        lines.append(f"{day} · {sport}" + (f" · {suffix}" if suffix else ""))
    return (
        "\n".join(lines)
        if lines
        else "本周实际活动与天气明细未随本次报告提供；请以数据说明和后续补录为准。"
    )


def _enum(value: object, choices: Mapping[str, str]) -> str:
    return choices.get(value, "未提供") if isinstance(value, str) else "未提供"


def _list_text(value: object) -> list[str]:
    return (
        list(value)
        if isinstance(value, list)
        and all(isinstance(item, str) and item.strip() for item in value)
        else []
    )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return value


def _required_string_list(
    value: object, *, minimum: int = 0, maximum: int = 12
) -> list[str]:
    items = _list_text(value)
    if (
        not isinstance(value, list)
        or not minimum <= len(items) <= maximum
        or len(items) != len(set(items))
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return items


def _required_level(value: object, *, maximum: int = 5) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return value


def _validate_prescription(value: object, activity: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or value.get("activity_kind") != activity:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if activity == "rest":
        return value
    if activity != "running":
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    role = value.get("hansons_session_role")
    course = value.get("course_type")
    if (
        role not in _ROLE_COURSE
        or course not in _COURSE
        or _ROLE_COURSE[role] != course
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    for key in ("warmup", "main_set", "cooldown"):
        _required_text(value.get(key))
    _required_level(value.get("planned_duration_minutes"), maximum=24 * 60)
    _required_level(value.get("prescribed_rpe"), maximum=10)
    _required_string_list(value.get("stop_conditions"), maximum=12)
    bpm = value.get("target_bpm_range")
    if bpm is not None and _heart_rate(bpm) is None:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return value


def _validate_daily_payload(
    summary: Mapping[str, object], advice: Mapping[str, object]
) -> Mapping[str, object]:
    _required_text(summary.get("overall_state"))
    _required_string_list(summary.get("decision_factors"), minimum=1, maximum=3)
    if summary.get("activity_evidence") not in _ACTIVITY_EVIDENCE:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if summary.get("plan_evidence") not in _PLAN_EVIDENCE:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if summary.get("data_completeness") not in _COMPLETENESS:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    primary = advice.get("primary_item")
    activity = primary.get("activity_kind") if isinstance(primary, Mapping) else None
    primary = _validate_prescription(primary, activity)
    _required_level(advice.get("configured_difficulty_level"))
    _required_level(advice.get("selected_session_difficulty_level"))
    if advice.get("confidence") not in _CONFIDENCE:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    _required_text(advice.get("confidence_reason"))
    for key in ("difficulty_adjustment_reason", "data_limitation"):
        if advice.get(key) is not None and not isinstance(advice.get(key), str):
            raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return primary


def _localized(value: object, choices: Mapping[str, str], *, neutral: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return neutral
    return choices.get(value, neutral)


def _rpe(value: object) -> str:
    return (
        f"RPE {value}"
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10
        else "按体感执行"
    )


def _heart_rate(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    minimum, maximum = value.get("minimum_bpm"), value.get("maximum_bpm")
    if (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and 30 <= minimum <= maximum <= 240
    ):
        return f"心率 {minimum}–{maximum} 次/分钟"
    return None


def _mapping_text(value: object, *preferred: str, neutral: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if not isinstance(value, Mapping):
        return neutral
    for key in preferred:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return neutral


def _find_control(value: object, keys: Sequence[str]) -> object:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        if key in value:
            return value[key]
    for child in value.values():
        found = _find_control(child, keys)
        if found is not None:
            return found
    return None


def _created_at_local(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AnalysisDeliveryError(
            "analysis_delivery_artifact_content_invalid"
        ) from None
    if parsed.tzinfo is None:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    return parsed.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M")


def _stop_text(value: object) -> str:
    return "；".join(
        _STOP_CONDITIONS.get(item, "出现需要停止训练的情况")
        for item in _list_text(value)
    )


def _daily_advice_paragraphs(value: str) -> tuple[str, ...]:
    """Keep plan rationale readable without repeating host-owned sections.

    Confidence, data limitations and stop conditions already have dedicated
    email blocks.  The accepted artifact remains immutable; this function only
    removes those duplicated sentences from the delivery presentation.
    """
    lines = [
        line.strip()
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip() and not line.strip().startswith(("判断置信度：", "数据说明："))
    ]
    sentences = [
        sentence.strip()
        for line in lines
        for sentence in re.findall(r"[^。！？]+[。！？]?", line)
        if sentence.strip()
    ]
    paragraphs: list[str] = []
    for sentence in sentences:
        if sentence in {"今日跑步。", "今日休息。"}:
            continue
        if "停止" in sentence and any(
            phrase in sentence
            for phrase in ("急性疼痛", "胸痛", "晕厥", "头晕", "呼吸困难")
        ):
            continue
        paragraphs.append(sentence)
    return tuple(paragraphs)


def _daily_advice_paragraph_nodes(paragraphs: Sequence[str]) -> tuple[Element, ...]:
    return tuple(
        element(
            "div",
            text(paragraph),
            attributes={
                "style": (
                    "margin-top:10px;font-size:14px;line-height:1.75;color:#33445A;"
                )
            },
        )
        for paragraph in paragraphs
    )


def _stop_condition_nodes(value: object) -> tuple[Element, ...]:
    return tuple(
        element(
            "div",
            element(
                "span",
                text("•"),
                attributes={"style": "display:inline-block;width:16px;color:#A56D00;"},
            ),
            text(_STOP_CONDITIONS.get(item, "出现需要停止训练的情况")),
            attributes={"style": "margin-top:4px;"},
        )
        for item in _list_text(value)
    )


def _strip_design_ids(root: Element) -> None:
    root.discard_attribute("data-od-id")
    for child in root.children:
        if isinstance(child, Element):
            _strip_design_ids(child)


def _find_repeat(root: Element, name: str) -> Element:
    if name in root.attribute_values("data-repeat"):
        return root
    for child in root.children:
        if isinstance(child, Element):
            try:
                return _find_repeat(child, name)
            except LookupError:
                pass
    raise LookupError(name)


def _first_variant(root: Element, variant: str) -> Element:
    if variant in root.attribute_values("data-variant"):
        return root.clone()
    for child in root.children:
        if isinstance(child, Element):
            try:
                return _first_variant(child, variant)
            except LookupError:
                pass
    raise LookupError(variant)


def _remove_table_with_field(root: Element, field: str) -> None:
    def contains(target: Element) -> bool:
        return any(
            field in node.attribute_values("data-field")
            for node in _walk_elements(target)
        )

    def nested_table_contains(target: Element) -> bool:
        return any(
            node is not target and node.tag == "table" and contains(node)
            for node in _walk_elements(target)
        )

    kept: list[Element | Any] = []
    for child in root.children:
        if not isinstance(child, Element):
            kept.append(child)
            continue
        if (
            child.tag == "table"
            and contains(child)
            and not nested_table_contains(child)
        ):
            continue
        _remove_table_with_field(child, field)
        kept.append(child)
    root.children = kept


def _walk_elements(root: Element):
    yield root
    for child in root.children:
        if isinstance(child, Element):
            yield from _walk_elements(child)


def _replace_design_example(root: Element, source: str, replacement: str) -> None:
    """Remove literal example copy that is intentionally not a template binding."""
    root.children = [
        Text(replacement)
        if isinstance(child, Text) and child.value == source
        else child
        for child in root.children
    ]
    for child in root.children:
        if isinstance(child, Element):
            _replace_design_example(child, source, replacement)


def _weekly_item(template: Element, item: Mapping[str, object], index: int) -> Element:
    local_date = _local_date(item.get("local_date"))
    activity = item.get("activity_kind")
    if activity not in _ACTIVITY:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    prescription = _validate_prescription(item.get("prescription"), activity)
    if (
        not isinstance(item.get("item_index"), int)
        or isinstance(item.get("item_index"), bool)
        or not 0 <= cast(int, item["item_index"]) <= 6
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if item.get("rationale_text") is not None and not isinstance(
        item.get("rationale_text"), str
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    _required_string_list(item.get("stop_conditions"), maximum=12)
    variant = "running" if activity == "running" else "rest"
    fragment = Template(_first_variant(template, variant)).select_variant(variant)
    fragment.root.discard_attribute("data-variant")
    role = _enum(prescription.get("hansons_session_role"), _ROLE)
    course = _enum(prescription.get("course_type"), _COURSE)
    warmup = _localized(
        prescription.get("warmup"), _PRESCRIPTION_TEXT, neutral="按身体状态逐步热身"
    )
    main_work = _localized(
        prescription.get("main_set"), _PRESCRIPTION_TEXT, neutral="按课程说明完成主训练"
    )
    cooldown = _localized(
        prescription.get("cooldown"), _PRESCRIPTION_TEXT, neutral="逐步降速完成冷身"
    )
    heart_rate = _heart_rate(prescription.get("target_bpm_range"))
    # The safety-normalized prescription is canonical.  The duplicated outer
    # list remains validated for schema integrity but never overrides it.
    stop_conditions = _stop_text(prescription.get("stop_conditions"))
    details = "；".join(
        value
        for value in (
            f"热身：{warmup}",
            f"主训练：{main_work}",
            f"冷身：{cooldown}",
            heart_rate,
            f"停止条件：{stop_conditions}" if stop_conditions else None,
        )
        if value
    )
    fields = {
        "weekday": _WEEKDAYS[date.fromisoformat(local_date).weekday()],
        "date": _display_date(local_date),
        "session_title": role
        if activity == "running" and role != "未提供"
        else ("跑步训练" if activity == "running" else "休息日"),
        "rationale": _text(item.get("rationale_text")),
        "recovery_advice": _text(
            prescription.get("recovery_advice"),
            neutral="恢复日，不安排跑步训练。",
        ),
        "hansons_session_role": role,
        "course_type": course,
        "planned_duration": _number(
            prescription.get("planned_duration_minutes"), suffix=" 分钟"
        ),
        "effort_guidance": " · ".join(
            value
            for value in (_rpe(prescription.get("prescribed_rpe")), heart_rate)
            if value
        ),
        "main_work": details,
    }
    fragment.set_fields(fields).remove_empty_optional({})
    assert_no_bindings(fragment.root)
    _strip_design_ids(fragment.root)
    return fragment.root


def _weekly_html(pending: PendingDelivery, *, revision: bool) -> str:
    summary = next(
        (item for item in pending.artifacts if item.content_role == "weekly_summary"),
        None,
    )
    plan = next(
        item
        for item in pending.artifacts
        if item.content_role in {"weekly_plan", "plan_revision"}
    )
    content = plan.structured_content_json
    items = content.get("items")
    if (
        not isinstance(items, list)
        or (not revision and len(items) != 7)
        or (revision and not 1 <= len(items) <= 7)
        or not all(isinstance(item, dict) for item in items)
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    period = content.get("period")
    if (
        not isinstance(period, dict)
        or _local_date(period.get("start_local_date")) != plan.period_start_local_date
        or _local_date(period.get("end_local_date")) != plan.period_end_local_date
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if (
        content.get("timezone") != "Asia/Hong_Kong"
        or not isinstance(content.get("objective"), Mapping)
        or not isinstance(content.get("constraints"), Mapping)
    ):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    start = date.fromisoformat(plan.period_start_local_date)
    end = date.fromisoformat(plan.period_end_local_date)
    if (end - start).days != 6:
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    item_dates = [_local_date(item.get("local_date")) for item in items]
    if len(item_dates) != len(set(item_dates)):
        raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    if not revision:
        expected_dates = [
            date.fromordinal(start.toordinal() + index).isoformat()
            for index in range(7)
        ]
        if item_dates != expected_dates or [
            item.get("item_index") for item in items
        ] != list(range(7)):
            raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    else:
        item_indexes = [item.get("item_index") for item in items]
        if (
            any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 6
                for value in item_indexes
            )
            or any(
                not start <= date.fromisoformat(value) <= end for value in item_dates
            )
            or item_dates != sorted(item_dates)
            or len(item_indexes) != len(set(item_indexes))
            or item_indexes != sorted(item_indexes)
        ):
            raise AnalysisDeliveryError("analysis_delivery_artifact_content_invalid")
    template = load_template("weekly_report")
    summary_text = (
        summary.user_visible_text if summary is not None else plan.user_visible_text
    )
    title = "训练计划修订" if revision else "每周训练报告"
    fields = {
        "brand_name": "TrainLab",
        "display_date": f"{_display_date(plan.period_start_local_date)}—{_display_date(plan.period_end_local_date)}",
        "title": title,
        "subtitle": "现有计划项目" if revision else "本周回顾与未来七天计划",
        "preheader": "现有训练计划项目",
        "review_start_date": _display_date(summary.period_start_local_date)
        if summary
        else "未提供",
        "review_end_date": _display_date(summary.period_end_local_date)
        if summary
        else "未提供",
        "weekly_summary_text": summary_text,
        "recovery_summary": _mapping_text(
            summary.structured_content_json if summary else None,
            "recovery_summary",
            "summary",
            neutral="详见本周总结",
        ),
        "training_load_summary": _mapping_text(
            summary.structured_content_json if summary else None,
            "training_load_summary",
            neutral="详见本周总结",
        ),
        "progress_summary": _mapping_text(
            summary.structured_content_json if summary else None,
            "progress_summary",
            neutral="详见本周总结",
        ),
        "training_method": "Hansons Marathon Method",
        "training_difficulty_level": _number(
            _find_control(content, ("training_difficulty_level", "configured_level")),
            suffix=" / 5",
        ),
        "marathon_goal_time": _text(
            _find_control(content, ("marathon_target_finish_time",)), neutral="未设置"
        ),
        "half_marathon_goal_time": _text(
            _find_control(content, ("half_marathon_target_finish_time",)),
            neutral="未设置",
        ),
        "marathon_race_date": "参赛："
        + _date_label(_find_control(content, ("marathon_race_date",))),
        "half_marathon_race_date": "参赛："
        + _date_label(_find_control(content, ("half_marathon_race_date",))),
        "actual_activity_weather": _activity_weather_summary(
            _find_control(
                summary.structured_content_json if summary else None,
                (
                    "actual_activities",
                    "activity_weather_summary",
                    "actual_activity_summary",
                ),
            )
        ),
        "plan_objective": _mapping_text(
            content.get("objective"),
            "focus",
            "summary",
            "description",
            neutral="详见计划正文",
        ),
        "plan_constraints": _mapping_text(
            content.get("constraints"), "summary", "description", neutral="详见计划正文"
        ),
        "plan_note": "每次训练前根据体感与安全信号决定是否降级或停止。",
        "week_start_date": _display_date(plan.period_start_local_date),
        "week_end_date": _display_date(plan.period_end_local_date),
        "attention_items": "",
        "data_limitation": "",
        "footer_note": "请以当天真实感受与安全信号为准。",
        "generated_at_local": _created_at_local(plan.created_at_utc),
    }
    repeat = _find_repeat(template.root, "daily_plans")
    repeat_template = repeat.clone()
    daily_plans = [
        _weekly_item(repeat_template, item, index) for index, item in enumerate(items)
    ]
    _replace_design_example(template.root, "先稳定恢复，再延续训练节奏", "本周回顾")
    template.remove_empty_optional(
        {
            "key_findings": [],
            "heart_rate_zone_comparison": pending.heart_rate_zone_comparison,
            "attention_items": "",
            "data_limitation": "",
        }
    ).replace_repeats(
        {
            "daily_plans": daily_plans,
            "key_findings": [],
            "heart_rate_zone_comparison": tuple(
                element(
                    "div",
                    text(line),
                    attributes={
                        "style": "margin-top:7px;font-size:13px;line-height:1.7;color:#33445A;"
                    },
                )
                for line in pending.heart_rate_zone_comparison
            ),
        }
    ).set_fields(fields)
    return template.finalize()


def _daily_html(pending: PendingDelivery) -> str:
    summary = next(
        item for item in pending.artifacts if item.content_role == "daily_summary"
    )
    advice = next(
        item for item in pending.artifacts if item.content_role == "daily_advice"
    )
    primary = _validate_daily_payload(
        summary.structured_content_json, advice.structured_content_json
    )
    activity = primary["activity_kind"]
    factors = _list_text(summary.structured_content_json.get("decision_factors"))
    for value, choices in (
        (summary.structured_content_json.get("activity_evidence"), _ACTIVITY_EVIDENCE),
        (summary.structured_content_json.get("plan_evidence"), _PLAN_EVIDENCE),
    ):
        localized = _enum(value, choices)
        if localized != "未提供" and localized not in factors:
            factors.append(localized)
    heart_rate = _heart_rate(primary.get("target_bpm_range"))
    stop_conditions = _stop_text(primary.get("stop_conditions"))
    advice_paragraphs = _daily_advice_paragraphs(advice.user_visible_text)
    is_rest = activity == "rest"
    sleep_chart = pending.sleep_chart
    sleep_completeness = (
        sleep_chart.completeness if sleep_chart is not None else "unavailable"
    )
    recovery_metrics = pending.recovery_metrics
    training_load = pending.training_load_chart
    yesterday_activities = pending.yesterday_activities
    fields = {
        "brand_name": "TrainLab",
        "display_date": _display_date(advice.period_start_local_date),
        "title": "每日训练简报",
        "subtitle": "昨日状态与今日安排",
        "preheader": "昨日状态与今日安排",
        "overall_state": _text(summary.structured_content_json.get("overall_state")),
        "data_completeness": _enum(
            summary.structured_content_json.get("data_completeness"), _COMPLETENESS
        ),
        "data_window": (
            f"{_display_date(summary.period_start_local_date)}白天活动与健康；"
            f"{_display_date(summary.period_start_local_date)}晚至{_display_date(advice.period_start_local_date)}早睡眠；"
            f"{_display_date(advice.period_start_local_date)}早晨恢复（Asia/Hong_Kong）"
        ),
        "sleep_recovery_status": _SLEEP_COMPLETENESS.get(
            sleep_completeness, _SLEEP_COMPLETENESS["unavailable"]
        ),
        "sleep_window": (
            f"{sleep_chart.start_local_time}–{sleep_chart.end_local_time}"
            if sleep_chart is not None
            else ""
        ),
        "sleep_window_duration": (
            _duration_label(sleep_chart.window_seconds)
            if sleep_chart is not None
            else ""
        ),
        "sleep_asleep_duration": (
            _duration_label(sleep_chart.asleep_seconds)
            if sleep_chart is not None
            else ""
        ),
        "sleep_awake_duration": (
            _duration_label(sleep_chart.awake_seconds)
            if sleep_chart is not None
            else ""
        ),
        "training_load_window": (
            f"{_display_date(training_load.start_local_date)}—"
            f"{_display_date(training_load.end_local_date)}"
            if training_load is not None
            else ""
        ),
        "training_load_total": (
            _duration_label(training_load.total_seconds)
            if training_load is not None
            else ""
        ),
        "training_load_count": (
            f"{training_load.activity_count}次活动" if training_load is not None else ""
        ),
        "confidence": _text(advice.structured_content_json.get("confidence")),
        "summary_date": _display_date(summary.period_start_local_date),
        "daily_summary_text": summary.user_visible_text,
        "advice_date": _display_date(advice.period_start_local_date),
        "session_title": "跑步训练" if activity == "running" else "休息日",
        "activity_kind": _ACTIVITY[cast(str, activity)],
        "total_volume": "恢复优先"
        if is_rest
        else _number(primary.get("planned_duration_minutes"), suffix=" 分钟"),
        "hansons_session_role": "休息"
        if is_rest
        else _enum(primary.get("hansons_session_role"), _ROLE),
        "effort_guidance": "不安排训练"
        if is_rest
        else " · ".join(
            value
            for value in (_rpe(primary.get("prescribed_rpe")), heart_rate)
            if value
        ),
        "warmup": _localized(
            primary.get("warmup"), _PRESCRIPTION_TEXT, neutral="按身体状态逐步热身"
        ),
        "main_work": _localized(
            primary.get("main_set"), _PRESCRIPTION_TEXT, neutral="按课程说明完成主训练"
        ),
        "cooldown": _localized(
            primary.get("cooldown"), _PRESCRIPTION_TEXT, neutral="逐步降速完成冷身"
        ),
        "stop_conditions": stop_conditions,
        "configured_difficulty_level": _number(
            advice.structured_content_json.get("configured_difficulty_level")
        ),
        "selected_session_difficulty_level": _number(
            advice.structured_content_json.get("selected_session_difficulty_level")
        ),
        "difficulty_adjustment_reason": _text(
            advice.structured_content_json.get("difficulty_adjustment_reason"),
            neutral="",
        ),
        "confidence_reason": _text(
            advice.structured_content_json.get("confidence_reason")
        ),
        "data_limitation": _text(
            advice.structured_content_json.get("data_limitation"), neutral=""
        ),
        "footer_note": "请以当天真实感受与安全信号为准。",
        "generated_at_local": _created_at_local(advice.created_at_utc),
    }
    template = load_template("daily_report")
    _replace_design_example(template.root, "恢复信号改善，但暂不增加强度", "昨日回顾")
    if activity == "rest":
        for field in ("warmup", "main_work", "cooldown"):
            _remove_table_with_field(template.root, field)
    template.remove_empty_optional(
        {
            "decision_factors": factors,
            "sleep_chart": sleep_chart,
            "recovery_metrics": recovery_metrics,
            "yesterday_activities": yesterday_activities,
            "training_load_chart": training_load,
            "daily_advice_paragraphs": advice_paragraphs,
            "stop_conditions": fields["stop_conditions"],
            "difficulty_adjustment_reason": fields["difficulty_adjustment_reason"],
            "data_limitation": fields["data_limitation"],
        }
    ).replace_repeats(
        {
            "decision_factors": factors,
            "sleep_stage_segments": (
                _sleep_chart_segments(sleep_chart) if sleep_chart is not None else ()
            ),
            "sleep_stage_legend": (
                _sleep_chart_legend(sleep_chart) if sleep_chart is not None else ()
            ),
            "recovery_metrics": _recovery_metric_cells(recovery_metrics),
            "yesterday_activities": _activity_overview_rows(yesterday_activities),
            "training_load_days": (
                _training_load_rows(training_load) if training_load is not None else ()
            ),
            "daily_advice_paragraphs": _daily_advice_paragraph_nodes(advice_paragraphs),
            "stop_conditions": _stop_condition_nodes(primary.get("stop_conditions")),
        }
    ).set_fields(fields)
    return template.finalize()


def render_delivery(pending: PendingDelivery) -> RenderedDelivery:
    """Bind immutable structured artifacts to the packaged, escaped email designs."""
    _safe_header(pending.run_key)
    idempotency_key = _safe_header(pending.idempotency_key)
    if pending.delivery_kind == "daily_report":
        html = _daily_html(pending)
    else:
        html = _weekly_html(pending, revision=pending.delivery_kind == "plan_revision")
    period = pending.artifacts[-1]
    report_title = _DELIVERY_PRESENTATION[pending.delivery_kind][0]
    if pending.delivery_kind == "daily_report":
        summary = next(
            item for item in pending.artifacts if item.content_role == "daily_summary"
        )
        advice = next(
            item for item in pending.artifacts if item.content_role == "daily_advice"
        )
        subject = _safe_header(
            f"TrainLab｜{report_title}｜回顾{_display_date(summary.period_start_local_date)}｜"
            f"安排{_display_date(advice.period_start_local_date)}"
        )
        sleep_chart = pending.sleep_chart
        sleep_completeness = (
            sleep_chart.completeness if sleep_chart is not None else "unavailable"
        )
        plain = [
            report_title,
            f"回顾日期：{_display_date(summary.period_start_local_date)}",
            f"安排日期：{_display_date(advice.period_start_local_date)}",
            "数据窗口："
            f"{_display_date(summary.period_start_local_date)}白天活动与健康；"
            f"{_display_date(summary.period_start_local_date)}晚至{_display_date(advice.period_start_local_date)}早睡眠；"
            f"{_display_date(advice.period_start_local_date)}早晨恢复（Asia/Hong_Kong）",
            "睡眠数据："
            + _SLEEP_COMPLETENESS.get(
                sleep_completeness, _SLEEP_COMPLETENESS["unavailable"]
            ),
            "",
            _TITLES[summary.content_role],
            summary.user_visible_text.replace("\r\n", "\n").replace("\r", "\n"),
        ]
        if sleep_chart is not None:
            plain.append(
                "睡眠图表："
                f"{sleep_chart.start_local_time}–{sleep_chart.end_local_time}；"
                f"实际睡眠{_duration_label(sleep_chart.asleep_seconds)}；"
                f"深睡{_duration_label(sleep_chart.deep_seconds)}、"
                f"浅睡{_duration_label(sleep_chart.light_seconds)}、"
                f"REM {_duration_label(sleep_chart.rem_seconds)}、"
                f"清醒{_duration_label(sleep_chart.awake_seconds)}"
            )
        if pending.recovery_metrics:
            plain.append("恢复指标：" + _recovery_plain(pending.recovery_metrics))
        if pending.yesterday_activities:
            plain.append("昨日运动：" + _activities_plain(pending.yesterday_activities))
        if pending.training_load_chart is not None:
            plain.append(
                "最近7日训练量：" + _training_load_plain(pending.training_load_chart)
            )
        advice_paragraphs = _daily_advice_paragraphs(advice.user_visible_text)
        primary_item = advice.structured_content_json.get("primary_item")
        stop_conditions = _list_text(
            primary_item.get("stop_conditions")
            if isinstance(primary_item, Mapping)
            else None
        )
        plain.extend(("", _TITLES[advice.content_role], *advice_paragraphs))
        if stop_conditions:
            plain.append("停止条件：")
            plain.extend(
                "- " + _STOP_CONDITIONS.get(item, "出现需要停止训练的情况")
                for item in stop_conditions
            )
    elif pending.delivery_kind == "weekly_report":
        weekly_summary = next(
            (
                item
                for item in pending.artifacts
                if item.content_role == "weekly_summary"
            ),
            None,
        )
        subject = _safe_header(
            f"TrainLab｜{report_title}｜回顾"
            f"{_display_date(weekly_summary.period_start_local_date) if weekly_summary else '未提供'}—"
            f"{_display_date(weekly_summary.period_end_local_date) if weekly_summary else '未提供'}｜计划"
            f"{_display_date(period.period_start_local_date)}—{_display_date(period.period_end_local_date)}"
        )
        plan_content = period.structured_content_json
        plain = [
            report_title,
            f"回顾日期：{_display_date(weekly_summary.period_start_local_date) if weekly_summary else '未提供'}—{_display_date(weekly_summary.period_end_local_date) if weekly_summary else '未提供'}",
            f"计划日期：{_display_date(period.period_start_local_date)}—{_display_date(period.period_end_local_date)}",
            "实际活动与天气："
            + _activity_weather_summary(
                _find_control(
                    weekly_summary.structured_content_json if weekly_summary else None,
                    (
                        "actual_activities",
                        "activity_weather_summary",
                        "actual_activity_summary",
                    ),
                )
            ),
            "全马目标："
            + _text(
                _find_control(plan_content, ("marathon_target_finish_time",)),
                neutral="未设置",
            )
            + "；"
            + "参赛："
            + _date_label(_find_control(plan_content, ("marathon_race_date",))),
            "半马目标："
            + _text(
                _find_control(plan_content, ("half_marathon_target_finish_time",)),
                neutral="未设置",
            )
            + "；"
            + "参赛："
            + _date_label(_find_control(plan_content, ("half_marathon_race_date",))),
        ]
        if pending.heart_rate_zone_comparison:
            plain.extend(
                ("", "跑步心率区间三方法对比", *pending.heart_rate_zone_comparison)
            )
    else:
        subject = _safe_header(
            f"TrainLab｜{report_title}｜{_display_date(period.period_start_local_date)}"
        )
        plain = [report_title, f"日期：{_display_date(period.period_start_local_date)}"]
    if pending.delivery_kind != "daily_report":
        for artifact in pending.artifacts:
            plain.extend(
                (
                    "",
                    _TITLES[artifact.content_role],
                    artifact.user_visible_text.replace("\r\n", "\n").replace(
                        "\r", "\n"
                    ),
                )
            )
    plain_text = "\n".join(plain)
    if (
        pending.run_key in subject
        or pending.run_key in plain_text
        or pending.run_key in html
        or idempotency_key in subject
        or idempotency_key in plain_text
        or idempotency_key in html
    ):
        raise AnalysisDeliveryError("analysis_delivery_internal_identifier_visible")
    return RenderedDelivery(
        subject, {"X-TrainLab-Idempotency-Key": idempotency_key}, plain_text, html
    )
