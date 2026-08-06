"""A3-10 bounded, deterministic analysis-context construction.

The repository seam accepts only the A3-06 stable-view repository.  The
builder itself is pure: it receives one immutable ``StableSnapshot`` plus
already-computed bounded summaries, validates their lineage, and returns a
canonical JSON document without logging or writing it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

from .features import (
    CONFLICT_POLICY_SHA256,
    CONFLICT_POLICY_VERSION,
    FEATURE_LIBRARY_VERSION,
)
from .fit_context import ExplicitFitContextError, build_explicit_fit_context
from .harness import HarnessBundle
from .quality_gate import (
    QUALITY_GATE_POLICY_SHA256,
    QUALITY_GATE_POLICY_VERSION,
    QualityGateResult,
)
from .safety_rules import (
    TRAINING_SAFETY_POLICY_SHA256,
    TRAINING_SAFETY_POLICY_VERSION,
)
from .stable_views import StableSnapshot, StableSubjectContext


class ContextBuildError(ValueError):
    """Controlled context-contract failure with no source payload."""


ContextRoute = Literal["daily", "weekly", "revise_plan", "regenerate"]
SourceRoute = Literal["daily", "weekly", "revise_plan"]

_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _ROOT.parents[2]
_SCHEMA_PATH = _PROJECT_ROOT / "harness" / "schemas" / "analysis_input.schema.json"
_POLICY_PATH = _ROOT / "context_policy.json"
_SCHEMA_BYTES = _SCHEMA_PATH.read_bytes()
_POLICY_BYTES = _POLICY_PATH.read_bytes()
_SCHEMA: dict[str, Any] = json.loads(_SCHEMA_BYTES)
_POLICY: dict[str, Any] = json.loads(_POLICY_BYTES)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())

ANALYSIS_INPUT_SCHEMA_VERSION = "1"
ANALYSIS_INPUT_SCHEMA_SHA256 = sha256(_SCHEMA_BYTES).hexdigest()
CONTEXT_POLICY_VERSION = str(_POLICY["policy_version"])
CONTEXT_POLICY_SHA256 = sha256(_POLICY_BYTES).hexdigest()
DEFAULT_MAX_CONTEXT_BYTES = int(_POLICY["default_max_context_bytes"])

_SG = ZoneInfo("Asia/Hong_Kong")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_KEY = re.compile(r"^[A-Za-z0-9_.:%-]{1,256}$")
_TRUST = frozenset(_POLICY["trust_classes"])
_FACT_SCOPES = frozenset(_POLICY["fact_scopes"])
_SAMPLE_METRICS = frozenset(_POLICY["technical_sample_metrics"])
_MAX_ITEMS = int(_POLICY["maximum_manifest_items"])
_MAX_SNAPSHOT_ITEMS = int(_POLICY["maximum_snapshot_items"])
_MAX_SAMPLE_SUMMARIES = int(_POLICY["maximum_technical_sample_summaries"])
_MAX_SAMPLE_ROWS = int(_POLICY["maximum_technical_sample_rows"])
_PRUNE_CODES = tuple(_POLICY["pruning_order"])
_BASELINE_WINDOW_DAYS = int(_POLICY.get("baseline_window_days", _POLICY["completed_window_days"]))
_SHORT_WINDOW_DAYS = int(_POLICY.get("short_window_days", 7))
_TREND_WINDOW_DAYS = int(_POLICY.get("trend_window_days", 90))
_COMPLETED_WINDOW_DAYS = _BASELINE_WINDOW_DAYS
_SECTIONS = (
    "coverage",
    "gaps",
    "health",
    "sleep",
    "physiology",
    "activities",
    "technical_samples",
    "deterministic_features",
    "current_plan",
    "plan_adherence",
    "prior_artifacts",
    "user_facts",
    "policies",
)
_EXPECTED_VIEWS = frozenset(
    {
        "v_current_daily_health",
        "v_current_physiology_records",
        "v_current_physiology_metrics",
        "v_current_sleep_sessions",
        "v_current_activities",
        "v_activity_segments",
        "v_activity_metric_sources",
        "v_active_user_facts",
        "v_current_analysis_artifacts",
        "v_current_weekly_summaries",
        "v_current_training_plans",
        "v_training_plan_items",
        "v_analysis_history_context",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "attachment",
        "authorization",
        "authorization_url",
        "body_html",
        "body_text",
        "context_snapshot_sha256",
        "credential",
        "credentials",
        "gmail_html",
        "identity_hmac",
        "input_sha256",
        "mime",
        "password",
        "provider_account_id",
        "raw_payload",
        "refresh_token",
        "secret",
        "token",
    }
)
_DISPLAY_FIELDS = frozenset(
    {"description", "display_label", "display_name", "label", "name", "status_text"}
)
_EMBEDDED_JSON_NAMES = {
    "fact_value_json": "fact_value",
    "objective_json": "objective",
    "constraints_json": "constraints",
    "prescription_json": "prescription",
    "value_json": "value",
    "values_json": "values",
}
_FOUNDATION_ORIGIN_TO_CONTEXT = {
    "sensor_observed": "provider_fact",
    "user_entered": "user_asserted",
    "profile_setting": "user_asserted",
}


def _fail(code: str) -> None:
    raise ContextBuildError(code)


def _canonical(value: Any) -> str:
    _json_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ContextBuildError("analysis_context_json_invalid") from error


def _json_value(
    value: Any, *, key: str | None = None, forbid_source_keys: bool = False
) -> None:
    if forbid_source_keys and key is not None and key.lower() in _FORBIDDEN_KEYS:
        _fail("analysis_context_forbidden_field")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("analysis_context_nonfinite_number")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item, forbid_source_keys=forbid_source_keys)
        return
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                _fail("analysis_context_object_key_invalid")
            _json_value(
                child,
                key=child_key,
                forbid_source_keys=forbid_source_keys,
            )
        return
    _fail("analysis_context_json_type_invalid")


def _json_compatible(value: Any) -> Any:
    """Normalize accepted Python containers before JSON Schema validation."""
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _json_compatible(child)
            for key, child in value.items()
        }
    return deepcopy(value)


def _sha(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _duplicate_checked_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            _fail("analysis_context_duplicate_json_key")
        output[key] = value
    return output


def _reject_constant(_: str) -> None:
    _fail("analysis_context_nonfinite_number")


def parse_canonical_json(value: str) -> Any:
    """Parse only the exact canonical JSON representation.

    This closes duplicate-key, NaN/Infinity, whitespace and key-order byte-limit
    bypasses.  Normal source strings are not parsed unless their stable-view
    column is explicitly a JSON projection.
    """

    if not isinstance(value, str):
        _fail("analysis_context_json_text_invalid")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_reject_constant,
        )
    except ContextBuildError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ContextBuildError("analysis_context_json_text_invalid") from error
    if _canonical(parsed) != value:
        _fail("analysis_context_json_not_canonical")
    return parsed


def _parse_embedded_json(value: str) -> Any:
    """Parse trusted stable-view JSON without imposing a storage byte format.

    Foundation guarantees ``json_valid`` but does not require compact,
    key-sorted bytes.  The context serializer canonicalizes the parsed value
    itself.  Duplicate keys and non-finite values remain rejected so alternate
    byte formatting cannot change meaning or bypass validation.
    """

    if not isinstance(value, str):
        _fail("analysis_context_json_text_invalid")
    try:
        return json.loads(
            value,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_reject_constant,
        )
    except ContextBuildError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ContextBuildError("analysis_context_json_text_invalid") from error


def _local_date(value: Any) -> date:
    if not isinstance(value, str):
        _fail("analysis_context_date_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ContextBuildError("analysis_context_date_invalid") from error
    if parsed.isoformat() != value:
        _fail("analysis_context_date_invalid")
    return parsed


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("analysis_context_utc_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ContextBuildError("analysis_context_utc_invalid") from error
    if parsed.tzinfo != timezone.utc:
        _fail("analysis_context_utc_invalid")
    fraction = value[19:-1]
    is_shortest_fraction = (
        len(fraction) > 1
        and len(fraction) < 7
        and fraction[-1] != "0"
    )
    is_fixed_microsecond_fraction = len(fraction) == 7
    if (
        (fraction and parsed.microsecond == 0)
        or (fraction and not (is_shortest_fraction or is_fixed_microsecond_fraction))
    ):
        _fail("analysis_context_utc_not_canonical")
    return parsed


def _identifier(value: Any, code: str = "analysis_context_identity_invalid") -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        _fail(code)
    text = str(value)
    if not text or len(text) > 192:
        _fail(code)
    return text


def _period(start: date, end: date) -> dict[str, str]:
    if start > end:
        _fail("analysis_context_period_invalid")
    return {"start_local_date": start.isoformat(), "end_local_date": end.isoformat()}


@dataclass(frozen=True)
class ContextBuildRequest:
    route: ContextRoute
    run_key: str
    subject_id: int
    as_of_utc: str
    regenerate_source_route: SourceRoute | None = None
    summary_local_date: str | None = None
    advice_local_date: str | None = None
    review_end_local_date: str | None = None
    plan_start_local_date: str | None = None
    plan_end_local_date: str | None = None
    effective_local_date: str | None = None
    plan_id: int | None = None
    reason_event_id: int | None = None
    artifact_id: int | None = None
    max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES
    # Raw FIT is opt-in and must be bound to exact stable activity IDs.  The
    # default empty tuple keeps the production context compact and FIT-free.
    explicit_fit_activity_ids: tuple[str | int, ...] = ()
    explicit_fit_include_gps: bool = False

    def source_route(self) -> SourceRoute:
        if self.route == "regenerate":
            if self.regenerate_source_route not in {"daily", "weekly", "revise_plan"}:
                _fail("analysis_context_regenerate_route_invalid")
            if (
                isinstance(self.artifact_id, bool)
                or not isinstance(self.artifact_id, int)
                or self.artifact_id <= 0
            ):
                _fail("analysis_context_regenerate_route_invalid")
            return self.regenerate_source_route
        if self.regenerate_source_route is not None or self.artifact_id is not None:
            _fail("analysis_context_regenerate_route_invalid")
        if self.route not in {"daily", "weekly", "revise_plan"}:
            _fail("analysis_context_route_invalid")
        return self.route

    def validated_periods(self) -> dict[str, Any]:
        if (
            isinstance(self.subject_id, bool)
            or not isinstance(self.subject_id, int)
            or self.subject_id <= 0
            or not isinstance(self.max_context_bytes, int)
            or isinstance(self.max_context_bytes, bool)
            or not 1 <= self.max_context_bytes <= DEFAULT_MAX_CONTEXT_BYTES
            or not isinstance(self.run_key, str)
            or _RUN_KEY.fullmatch(self.run_key) is None
            or not isinstance(self.explicit_fit_activity_ids, tuple)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or not str(value)
                or len(str(value)) > 192
                for value in self.explicit_fit_activity_ids
            )
            or len(set(str(value) for value in self.explicit_fit_activity_ids))
            != len(self.explicit_fit_activity_ids)
            or len(self.explicit_fit_activity_ids) > 16
            or not isinstance(self.explicit_fit_include_gps, bool)
        ):
            _fail("analysis_context_request_invalid")
        as_of = _utc(self.as_of_utc)
        source_route = self.source_route()
        local_as_of = as_of.astimezone(_SG).date()
        summary = advice = review = plan = None
        effective: date | None = None
        if source_route == "daily":
            if any(
                value is not None
                for value in (
                    self.review_end_local_date,
                    self.plan_start_local_date,
                    self.plan_end_local_date,
                    self.effective_local_date,
                    self.plan_id,
                    self.reason_event_id,
                )
            ) or self.summary_local_date is None or self.advice_local_date is None:
                _fail("analysis_context_daily_window_invalid")
            summary_day = _local_date(self.summary_local_date)
            advice_day = _local_date(self.advice_local_date)
            if advice_day != summary_day + timedelta(days=1) or summary_day >= local_as_of:
                _fail("analysis_context_daily_window_invalid")
            summary = _period(summary_day, summary_day)
            advice = _period(advice_day, advice_day)
            baseline = _period(
                summary_day - timedelta(days=_COMPLETED_WINDOW_DAYS - 1),
                summary_day,
            )
        elif source_route == "weekly":
            if any(
                value is not None
                for value in (
                    self.summary_local_date,
                    self.advice_local_date,
                    self.plan_start_local_date,
                    self.plan_end_local_date,
                    self.effective_local_date,
                    self.plan_id,
                    self.reason_event_id,
                )
            ) or self.review_end_local_date is None:
                _fail("analysis_context_weekly_window_invalid")
            review_end = _local_date(self.review_end_local_date)
            review_start = review_end - timedelta(days=6)
            if review_end >= local_as_of:
                _fail("analysis_context_weekly_window_invalid")
            plan_start = review_end + timedelta(days=1)
            review = _period(review_start, review_end)
            plan = _period(plan_start, plan_start + timedelta(days=6))
            baseline = _period(
                review_end - timedelta(days=_COMPLETED_WINDOW_DAYS - 1),
                review_end,
            )
        else:
            if any(
                value is not None
                for value in (
                    self.summary_local_date,
                    self.advice_local_date,
                    self.review_end_local_date,
                )
            ) or None in (
                self.plan_start_local_date,
                self.plan_end_local_date,
                self.effective_local_date,
                self.plan_id,
                self.reason_event_id,
            ):
                _fail("analysis_context_revision_window_invalid")
            plan_start = _local_date(self.plan_start_local_date)
            plan_end = _local_date(self.plan_end_local_date)
            effective = _local_date(self.effective_local_date)
            if (
                plan_end - plan_start != timedelta(days=6)
                or not plan_start <= effective <= plan_end
                or isinstance(self.plan_id, bool)
                or not isinstance(self.plan_id, int)
                or self.plan_id <= 0
                or isinstance(self.reason_event_id, bool)
                or not isinstance(self.reason_event_id, int)
                or self.reason_event_id <= 0
            ):
                _fail("analysis_context_revision_window_invalid")
            plan = _period(plan_start, plan_end)
            baseline = _period(
                effective - timedelta(days=_COMPLETED_WINDOW_DAYS),
                effective - timedelta(days=1),
            )
        return {
            "summary": summary,
            "advice": advice,
            "review": review,
            "plan": plan,
            "baseline": baseline,
            "effective_local_date": effective.isoformat() if effective else None,
        }

    def repository_window(self) -> tuple[str, str]:
        periods = self.validated_periods()
        source = self.source_route()
        if source == "daily":
            end = periods["advice"]["end_local_date"]
        elif source == "weekly":
            end = periods["review"]["end_local_date"]
        else:
            end = periods["plan"]["end_local_date"]
        start = (date.fromisoformat(end) - timedelta(days=_TREND_WINDOW_DAYS - 1)).isoformat()
        return start, end


@dataclass(frozen=True)
class TechnicalSampleRequest:
    activity_id: int
    metric: str
    start_utc: str
    end_utc: str
    limit: int

    def validate(self) -> None:
        if (
            isinstance(self.activity_id, bool)
            or not isinstance(self.activity_id, int)
            or self.activity_id <= 0
            or self.metric not in _SAMPLE_METRICS
            or isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 100
            or _utc(self.start_utc) >= _utc(self.end_utc)
        ):
            _fail("analysis_context_sample_request_invalid")


@dataclass(frozen=True)
class ContextSource:
    snapshot: StableSnapshot
    technical_samples: tuple[dict[str, Any], ...] = ()
    # Each row is an already decoded, locally selected FIT payload.  It is
    # never populated by the ordinary repository seam.
    explicit_fit_messages: tuple[Mapping[str, Any], ...] = ()


class StableContextRepository(Protocol):
    def snapshot(
        self, subject_id: int, start_local_date: str, end_local_date: str
    ) -> StableSnapshot: ...

    def technical_samples(
        self,
        subject_id: int,
        activity_id: int,
        metric: str,
        start_utc: str,
        end_utc: str,
        *,
        limit: int,
    ) -> dict[str, Any]: ...

    def explicit_fit_messages(
        self, subject_id: int, activity_ids: tuple[str | int, ...]
    ) -> tuple[Mapping[str, Any], ...]: ...


def load_context_source(
    repository: StableContextRepository,
    request: ContextBuildRequest,
    technical_sample_requests: Sequence[TechnicalSampleRequest] = (),
) -> ContextSource:
    """Read only through A3-06's fixed repository seam."""

    if len(technical_sample_requests) > _MAX_SAMPLE_SUMMARIES:
        _fail("analysis_context_sample_limit_exceeded")
    seen: set[tuple[int, str, str, str]] = set()
    total_limit = 0
    for sample in technical_sample_requests:
        if not isinstance(sample, TechnicalSampleRequest):
            _fail("analysis_context_sample_request_invalid")
        sample.validate()
        key = (sample.activity_id, sample.metric, sample.start_utc, sample.end_utc)
        if key in seen:
            _fail("analysis_context_duplicate_sample_request")
        seen.add(key)
        total_limit += sample.limit
    if total_limit > _MAX_SAMPLE_ROWS:
        _fail("analysis_context_sample_limit_exceeded")
    start, end = request.repository_window()
    snapshot = repository.snapshot(request.subject_id, start, end)
    samples = tuple(
        repository.technical_samples(
            request.subject_id,
            sample.activity_id,
            sample.metric,
            sample.start_utc,
            sample.end_utc,
            limit=sample.limit,
        )
        for sample in technical_sample_requests
    )
    explicit: tuple[Mapping[str, Any], ...] = ()
    if request.explicit_fit_activity_ids:
        loader = getattr(repository, "explicit_fit_messages", None)
        if not callable(loader):
            _fail("analysis_explicit_fit_loader_unavailable")
        try:
            loaded = loader(request.subject_id, request.explicit_fit_activity_ids)
        except Exception as error:
            if isinstance(error, ContextBuildError):
                raise
            _fail("analysis_explicit_fit_loader_failed")
        if not isinstance(loaded, tuple) or any(not isinstance(row, Mapping) for row in loaded):
            _fail("analysis_explicit_fit_loader_invalid")
        explicit = loaded
    return ContextSource(
        snapshot=snapshot,
        technical_samples=samples,
        explicit_fit_messages=explicit,
    )


@dataclass
class _Candidate:
    section: str
    input_role: str
    entity_type: str
    entity_id: str
    revision_id: str
    window_start: str
    window_end: str
    trust_class: str
    value_origin: str
    content: dict[str, Any]
    prune_stage: int | None = None
    display_fields: tuple[str, ...] = ()
    original_ordinal: int = -1

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.section,
            self.input_role,
            self.window_start,
            self.window_end,
            self.entity_type,
            self.entity_id,
            self.revision_id,
            _sha(self.content),
        )

    def manifest(self, ordinal: int) -> dict[str, Any]:
        return {
            "input_role": self.input_role,
            "source_entity_type": self.entity_type,
            "source_entity_id": self.entity_id,
            "source_revision_id": self.revision_id,
            "source_window": {
                "start_local_date": self.window_start,
                "end_local_date": self.window_end,
            },
            "trust_class": self.trust_class,
            "value_origin": self.value_origin,
            "input_sha256": _sha(self.content),
            "ordinal": ordinal,
        }


@dataclass(frozen=True)
class ContextBuildResult:
    context: dict[str, Any]
    canonical_json: str
    context_snapshot_sha256: str
    utf8_bytes: int

    def to_json(self) -> str:
        return self.canonical_json


def _schema_validate(payload: Mapping[str, Any]) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(payload),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "root"
        raise ContextBuildError(f"analysis_context_schema_invalid:{location}")


def _snapshot_hash(snapshot: StableSnapshot) -> str:
    if not isinstance(snapshot, StableSnapshot):
        _fail("analysis_context_snapshot_invalid")
    return _sha(asdict(snapshot))


def _normalized_snapshot_hash(snapshot: StableSnapshot) -> str:
    """Hash snapshot meaning, not caller tuple ordering.

    A3-06 already emits deterministic SQL ordering.  Normalizing again here
    keeps the artifact hash stable for equivalent immutable fixtures/adapters
    while the original A3-07 hash is still checked before normalization.
    """

    payload = asdict(snapshot)
    payload["views"] = {
        name: sorted(rows, key=_canonical)
        for name, rows in sorted(payload["views"].items())
    }
    for key in (
        "coverage",
        "cursors",
        "gaps",
        "activity_stages",
        "quality_issues",
        "facts",
        "capabilities",
        "plan_reasons",
        "audit",
    ):
        payload[key] = sorted(payload[key], key=_canonical)
    return _sha(payload)


def _sanitize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        _fail("analysis_context_row_invalid")
    output: dict[str, Any] = {}
    for key, value in row.items():
        if not isinstance(key, str) or key.lower() in _FORBIDDEN_KEYS:
            _fail("analysis_context_forbidden_field")
        target_key = _EMBEDDED_JSON_NAMES.get(key, key)
        if target_key in output:
            _fail("analysis_context_duplicate_field")
        if key in _EMBEDDED_JSON_NAMES:
            if value is None:
                output[target_key] = None
            elif not isinstance(value, str):
                _fail("analysis_context_embedded_json_invalid")
            else:
                output[target_key] = _parse_embedded_json(value)
        else:
            output[target_key] = _json_compatible(value)
    _json_value(output, forbid_source_keys=True)
    return output


def _row_revision(row: Mapping[str, Any], entity_type: str, entity_id: str) -> str:
    for key in ("source_revision_id", "primary_revision_id", "active_fit_revision_id"):
        if row.get(key) is not None:
            return _identifier(row[key], "analysis_context_revision_invalid")
    if row.get("revision_no") is not None:
        revision = _identifier(row["revision_no"], "analysis_context_revision_invalid")
        content_hash = row.get("content_sha256")
        if not isinstance(content_hash, str) or _SHA256.fullmatch(content_hash) is None:
            _fail("analysis_context_revision_invalid")
        return f"{entity_type}:{entity_id}:r{revision}:{content_hash}"
    return f"snapshot:{entity_type}:{entity_id}:{_sha(_sanitize_row(row))}"


def _row_date_window(row: Mapping[str, Any], fallback: tuple[str, str]) -> tuple[str, str]:
    for start_key, end_key in (
        ("period_start_local_date", "period_end_local_date"),
        ("plan_start_local_date", "plan_end_local_date"),
        ("window_start_local_date", "window_end_local_date"),
    ):
        if row.get(start_key) is not None or row.get(end_key) is not None:
            start = _local_date(row.get(start_key)).isoformat()
            end = _local_date(row.get(end_key)).isoformat()
            if start > end:
                _fail("analysis_context_period_invalid")
            return start, end
    if row.get("local_date") is not None:
        day = _local_date(row["local_date"]).isoformat()
        return day, day
    for start_key, end_key in (
        ("start_time_utc", "end_time_utc"),
        ("effective_from_utc", "expires_at_utc"),
        ("valid_from_utc", "valid_to_utc"),
    ):
        if row.get(start_key) is not None:
            start = _utc(row[start_key]).astimezone(_SG).date().isoformat()
            if row.get(end_key) is not None:
                end = _utc(row[end_key]).astimezone(_SG).date().isoformat()
            else:
                end = start
            if start > end:
                _fail("analysis_context_period_invalid")
            return start, end
    return fallback


def _origin(value: Any, default: str) -> str:
    origin = default if value is None else value
    if isinstance(origin, str):
        origin = _FOUNDATION_ORIGIN_TO_CONTEXT.get(origin, origin)
    if not isinstance(origin, str) or origin not in _TRUST:
        _fail("analysis_context_value_origin_invalid")
    return origin


def _row_identity(row: Mapping[str, Any], entity_type: str) -> str:
    for key in (
        "id",
        "activity_id",
        "physiology_record_id",
        "training_plan_id",
        "provider_activity_id",
        "fact_key",
        "resource_kind",
    ):
        if row.get(key) is not None:
            return _identifier(row[key])
    return _sha(_sanitize_row(row))[:32]


def _add_row(
    candidates: list[_Candidate],
    *,
    section: str,
    role: str,
    entity_type: str,
    row: Mapping[str, Any],
    fallback_window: tuple[str, str],
    trust: str,
    origin: str | None = None,
    revision_id: str | None = None,
    entity_id: str | None = None,
    prune_stage: int | None = None,
    display_fields: Sequence[str] = (),
) -> None:
    if section not in _SECTIONS or trust not in _TRUST:
        _fail("analysis_context_candidate_invalid")
    identity = entity_id or _row_identity(row, entity_type)
    revision = revision_id or _row_revision(row, entity_type, identity)
    window = _row_date_window(row, fallback_window)
    content = _sanitize_row(row)
    candidates.append(
        _Candidate(
            section=section,
            input_role=role,
            entity_type=entity_type,
            entity_id=identity,
            revision_id=revision,
            window_start=window[0],
            window_end=window[1],
            trust_class=trust,
            value_origin=_origin(origin, trust),
            content=content,
            prune_stage=prune_stage,
            display_fields=tuple(sorted(set(display_fields) & set(content))),
        )
    )


def _snapshot_rows(snapshot: StableSnapshot) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for name in sorted(snapshot.views):
        collection = snapshot.views[name]
        if not isinstance(collection, tuple):
            _fail("analysis_context_snapshot_invalid")
        rows.extend(collection)
    for collection in (
        snapshot.coverage,
        snapshot.cursors,
        snapshot.gaps,
        snapshot.activity_stages,
        snapshot.quality_issues,
        snapshot.facts,
        snapshot.capabilities,
        snapshot.plan_reasons,
    ):
        if not isinstance(collection, tuple):
            _fail("analysis_context_snapshot_invalid")
        rows.extend(collection)
    return tuple(rows)


def _validate_snapshot(
    request: ContextBuildRequest,
    snapshot: StableSnapshot,
    as_of: datetime,
) -> None:
    if (
        not isinstance(snapshot, StableSnapshot)
        or set(snapshot.views) != _EXPECTED_VIEWS
        or not isinstance(snapshot.subject_context, StableSubjectContext)
        or snapshot.subject_context
        != StableSubjectContext(
            subject_id=request.subject_id,
            timezone="Asia/Hong_Kong",
            provider="garmin",
            identity_kind="account",
            verified=True,
        )
    ):
        _fail("analysis_context_snapshot_subject_invalid")
    rows = _snapshot_rows(snapshot)
    if len(rows) > _MAX_SNAPSHOT_ITEMS:
        _fail("analysis_context_snapshot_limit_exceeded")
    for row in rows:
        if not isinstance(row, Mapping):
            _fail("analysis_context_snapshot_invalid")
        subject = row.get("subject_id")
        if subject is not None and (
            isinstance(subject, bool) or subject != request.subject_id
        ):
            _fail("analysis_context_cross_subject")
        if row.get("is_current") is False or row.get("current_revision") is False:
            _fail("analysis_context_noncurrent_source")
        if row.get("source_revision_id") is not None:
            marker = row.get("source_revision_current")
            if marker is not None and (
                isinstance(marker, bool) or not isinstance(marker, int) or marker != 1
            ):
                _fail("analysis_context_noncurrent_source")
        for key in ("created_at_utc", "observed_at_utc"):
            if row.get(key) is not None and _utc(row[key]) > as_of:
                _fail("analysis_context_future_source")
        _sanitize_row(row)


def _revision_universe(snapshot: StableSnapshot) -> frozenset[str]:
    revisions: set[str] = set()
    for row in _snapshot_rows(snapshot):
        for key in (
            "source_revision_id",
            "primary_revision_id",
            "active_fit_revision_id",
            "active_weather_revision_id",
        ):
            if row.get(key) is not None:
                revisions.add(_identifier(row[key], "analysis_context_revision_invalid"))
        if row.get("id") is not None and "availability_state" in row:
            revisions.add(f"coverage:{_identifier(row['id'])}")
        # A3-08 represents a plan item's immutable source with the plan's
        # analysis artifact ID.  Admit that exact ID into the revision
        # universe so weekly adherence evidence can be carried into context;
        # do not infer or synthesize a different revision identity.
        if row.get("analysis_artifact_id") is not None:
            revisions.add(_identifier(row["analysis_artifact_id"]))
        if (
            row.get("artifact_kind")
            in {"weekly_summary", "weekly_training_plan"}
            and row.get("id") is not None
        ):
            revisions.add(_identifier(row["id"]))
    return frozenset(revisions)


def _completed_window(periods: Mapping[str, Any], source_route: SourceRoute) -> tuple[str, str]:
    if source_route == "daily":
        return (
            periods["summary"]["start_local_date"],
            periods["summary"]["end_local_date"],
        )
    if source_route == "weekly":
        return (
            periods["review"]["start_local_date"],
            periods["review"]["end_local_date"],
        )
    effective = periods["effective_local_date"]
    return effective, effective


def _trend_window(periods: Mapping[str, Any], source_route: SourceRoute) -> tuple[str, str]:
    """Return the compact 90-day trend window without widening target dates."""
    if source_route == "daily":
        end = periods["advice"]["end_local_date"]
    elif source_route == "weekly":
        end = periods["review"]["end_local_date"]
    else:
        end = periods["plan"]["end_local_date"]
    return (
        (date.fromisoformat(end) - timedelta(days=_TREND_WINDOW_DAYS - 1)).isoformat(),
        end,
    )


def _input_window(periods: Mapping[str, Any], source_route: SourceRoute) -> tuple[str, str]:
    return _trend_window(periods, source_route)


def _within(row: Mapping[str, Any], start: str, end: str) -> bool:
    row_start, row_end = _row_date_window(row, (start, end))
    return row_end >= start and row_start <= end


def _compact_path_segment(value: object) -> str:
    text = str(value)
    if text.isdigit():
        return "*"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:80] or "value"


def _flatten_compact_values(
    value: Any, *, prefix: str = "", depth: int = 0
) -> list[tuple[str, Any]]:
    """Keep scalar semantic values while excluding arrays/time-series payloads."""

    if depth > 4:
        return []
    if value is None or isinstance(value, (str, bool, int, float)):
        return [(prefix or "value", value)]
    if isinstance(value, Mapping):
        output: list[tuple[str, Any]] = []
        for key in sorted(value, key=str):
            segment = _compact_path_segment(key)
            child_prefix = f"{prefix}.{segment}" if prefix else segment
            output.extend(
                _flatten_compact_values(
                    value[key], prefix=child_prefix, depth=depth + 1
                )
            )
        return output
    # Lists and tuples commonly contain Garmin intraday series. They remain in
    # the database/raw revision and are deliberately absent from default AI
    # context.
    return []


def _observation_date(
    row: Mapping[str, Any], fallback: tuple[str, str]
) -> str:
    start, end = _row_date_window(row, fallback)
    return end if end >= start else start


def _source_reference(
    row: Mapping[str, Any], entity_type: str
) -> tuple[str, str]:
    identity = _row_identity(row, entity_type)
    return identity, _row_revision(row, entity_type, identity)


def _rounded(value: float) -> float:
    rendered = round(float(value), 6)
    return 0.0 if rendered == -0.0 else rendered


def _numeric_summary(values: Sequence[float], dates: Sequence[str]) -> dict[str, Any]:
    count = len(values)
    average = sum(values) / count
    if count < 4:
        trend = "insufficient"
    else:
        middle = count // 2
        earlier = sum(values[:middle]) / middle
        later = sum(values[-middle:]) / middle
        tolerance = max(abs(average) * 0.02, 1e-9)
        trend = (
            "increasing"
            if later - earlier > tolerance
            else "decreasing"
            if earlier - later > tolerance
            else "stable"
        )
    anomaly_dates: list[str] = []
    if count >= 5:
        variance = sum((value - average) ** 2 for value in values) / count
        deviation = math.sqrt(variance)
        if deviation > 0:
            anomaly_dates = sorted(
                {
                    day
                    for day, value in zip(dates, values, strict=True)
                    if abs(value - average) >= 2 * deviation
                }
            )[:10]
    return {
        "average": _rounded(average),
        "minimum": _rounded(min(values)),
        "maximum": _rounded(max(values)),
        "trend": trend,
        "anomaly_dates": anomaly_dates,
    }


def _compact_series_content(
    *, family: str, metric_key: str, unit: str | None,
    observations: Sequence[Mapping[str, Any]],
    window: tuple[str, str],
) -> dict[str, Any]:
    ordered = sorted(
        observations,
        key=lambda item: (
            str(item["local_date"]),
            str(item["source_id"]),
            str(item["source_revision_id"]),
            _canonical(item["value"]),
        ),
    )
    observation_keys = {
        (
            str(item["local_date"]),
            str(item["source_id"]),
            str(item["source_revision_id"]),
            _canonical(item["value"]),
        )
        for item in ordered
    }
    if len(observation_keys) != len(ordered):
        _fail("analysis_context_duplicate_lineage")
    source_ids = sorted({str(item["source_id"]) for item in ordered})
    revision_ids = sorted(
        {str(item["source_revision_id"]) for item in ordered}
    )
    material = [
        {
            "local_date": item["local_date"],
            "source_id": str(item["source_id"]),
            "source_revision_id": str(item["source_revision_id"]),
            "value": item["value"],
        }
        for item in ordered
    ]
    digest = _sha(material)
    latest = ordered[-1]
    values = [item["value"] for item in ordered]
    numeric = all(
        not isinstance(value, bool) and isinstance(value, (int, float))
        for value in values
    )
    content: dict[str, Any] = {
        "family": family,
        "metric_key": metric_key,
        "unit": unit,
        "window": {
            "start_local_date": window[0],
            "end_local_date": window[1],
        },
        "observation_count": len(ordered),
        "coverage_days": len({str(item["local_date"]) for item in ordered}),
        "source_count": len(source_ids),
        "source_revision_count": len(revision_ids),
        "source_ids": source_ids[:12],
        "source_ids_truncated": len(source_ids) > 12,
        "source_revision_ids": revision_ids[:12],
        "source_revision_ids_truncated": len(revision_ids) > 12,
        "aggregate_sha256": digest,
        "latest": {
            "local_date": latest["local_date"],
            "value": latest["value"],
        },
        "value_kind": "numeric" if numeric else "categorical",
    }
    if numeric:
        content.update(
            _numeric_summary(
                [float(value) for value in values],
                [str(item["local_date"]) for item in ordered],
            )
        )
    else:
        counts: dict[str, int] = {}
        canonical_values: dict[str, Any] = {}
        for value in values:
            key = _canonical(value)
            counts[key] = counts.get(key, 0) + 1
            canonical_values[key] = value
        content["value_counts"] = [
            {"value": canonical_values[key], "count": count}
            for key, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[:5]
        ]
    return content


def _add_compact_observations(
    candidates: list[_Candidate], *,
    section: str, role: str, entity_type: str, family: str,
    observations: Sequence[Mapping[str, Any]],
    window: tuple[str, str],
) -> None:
    groups: dict[tuple[str, str | None], list[Mapping[str, Any]]] = {}
    for observation in observations:
        groups.setdefault(
            (str(observation["metric_key"]), observation.get("unit")),
            [],
        ).append(observation)
    for (metric_key, unit), rows in sorted(
        groups.items(), key=lambda item: (item[0][0], str(item[0][1]))
    ):
        content = _compact_series_content(
            family=family,
            metric_key=metric_key,
            unit=unit,
            observations=rows,
            window=window,
        )
        digest = str(content["aggregate_sha256"])
        _add_row(
            candidates,
            section=section,
            role=role,
            entity_type=entity_type,
            row=content,
            fallback_window=window,
            trust="derived_statistic",
            origin="derived_statistic",
            entity_id=f"{family}:{_sha([metric_key, unit])[:24]}",
            revision_id=f"aggregate:{digest}",
        )


def _health_observations(
    rows: Sequence[Mapping[str, Any]], window: tuple[str, str]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        sanitized = _sanitize_row(row)
        values = sanitized.get("values")
        if not isinstance(values, Mapping):
            continue
        source_id, revision = _source_reference(row, "daily_health")
        local_date = _observation_date(row, window)
        for metric_key, value in _flatten_compact_values(values):
            if value is None or not _health_metric_allowed(metric_key):
                continue
            output.append({
                "metric_key": f"health.{metric_key}",
                "unit": None,
                "value": value,
                "local_date": local_date,
                "source_id": source_id,
                "source_revision_id": revision,
            })
    return output


def _health_metric_allowed(metric_key: str) -> bool:
    """Apply the health whitelist at the analysis boundary as well as ingest."""
    key = metric_key.casefold().replace(" ", "_").replace("-", "_")
    allowed_tokens = (
        "heart_rate", "heartrate", "resting_heart_rate", "restingheartrate",
        "hrv", "heart_rate_variability", "spo2", "pulse_ox",
        "vo2_max", "vo2max", "max_vo2", "weight", "body_weight",
    )
    return any(token in key for token in allowed_tokens)


_MORNING_RECOVERY_TOKENS = frozenset({
    "sleep", "sleep_score", "resting_heart_rate", "restingheart rate",
    "heart_rate", "heartrate", "hrv", "spo2", "pulse_ox", "vo2_max",
    "vo2max", "weight", "body_weight",
})


def _morning_recovery_observations(
    rows: Sequence[Mapping[str, Any]], window: tuple[str, str]
) -> list[dict[str, Any]]:
    """Keep only D+1 morning recovery signals for a daily report.

    This is deliberately a path allowlist.  Steps, calories, distance and
    same-day activity fields are not allowed to enter the daily morning slice
    even when an old database row happens to contain them.
    """
    output: list[dict[str, Any]] = []
    for row in rows:
        local_date = _observation_date(row, window)
        if local_date != window[1]:
            continue
        values = _sanitize_row(row).get("values")
        if not isinstance(values, Mapping):
            continue
        source_id, revision = _source_reference(row, "daily_health")
        for metric_key, value in _flatten_compact_values(values):
            first = metric_key.split(".", 1)[0].casefold().replace(" ", "_")
            if value is None or not any(token in first or token in metric_key.casefold() for token in _MORNING_RECOVERY_TOKENS):
                continue
            output.append({
                "metric_key": f"morning_recovery.{metric_key}",
                "unit": None,
                "value": value,
                "local_date": local_date,
                "source_id": source_id,
                "source_revision_id": revision,
            })
    return output


def _sleep_observations(
    rows: Sequence[Mapping[str, Any]], window: tuple[str, str], *,
    include_session_timestamps: bool = False,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        source_id, revision = _source_reference(row, "sleep_session")
        local_date = _observation_date(row, window)
        sanitized = _sanitize_row(row)
        values = sanitized.get("values")
        if isinstance(values, Mapping):
            for metric_key, value in _flatten_compact_values(values):
                if value is None or not _sleep_metric_allowed(
                    metric_key,
                    include_session_timestamps=include_session_timestamps,
                ):
                    continue
                output.append({
                    "metric_key": f"sleep.{metric_key}",
                    "unit": None,
                    "value": value,
                    "local_date": local_date,
                    "source_id": source_id,
                    "source_revision_id": revision,
                })
        if row.get("session_type") is not None:
            output.append({
                "metric_key": "sleep.session_type",
                "unit": None,
                "value": row["session_type"],
                "local_date": local_date,
                "source_id": source_id,
                "source_revision_id": revision,
            })
        if row.get("start_time_utc") and row.get("end_time_utc"):
            duration = (
                _utc(row["end_time_utc"]) - _utc(row["start_time_utc"])
            ).total_seconds() / 60
            if duration >= 0:
                output.append({
                    "metric_key": "sleep.session_duration",
                    "unit": "min",
                    "value": _rounded(duration),
                    "local_date": local_date,
                    "source_id": source_id,
                    "source_revision_id": revision,
                })
    return output


_SLEEP_METRIC_NAMES = frozenset({
    "calendardate",
    "sleeptimeseconds", "deepsleepseconds", "lightsleepseconds",
    "remsleepseconds", "awakesleepseconds", "unmeasurablesleepseconds",
    "averagespo2value", "lowestspo2value", "averageheartrate",
    "restingheartrate", "averagerespirationvalue", "lowestrespirationvalue",
    "highestrespirationvalue", "avgsleepstress", "awakecount",
    "sleepwindowconfirmed", "sleepwindowconfirmationtype",
})
_SLEEP_METRIC_PATHS = frozenset({
    "sleepscores.overall.value", "sleepscores.overall.qualifier",
})
_SLEEP_SESSION_TIMESTAMP_NAMES = frozenset({
    "sleepstarttimestampgmt", "sleependtimestampgmt",
})


def _sleep_metric_allowed(
    metric_key: str, *, include_session_timestamps: bool = False,
) -> bool:
    """Expose only compact recovery facts, never provider/account metadata."""
    normalized = metric_key.casefold().replace("_", "")
    return (
        normalized in _SLEEP_METRIC_NAMES
        or normalized in _SLEEP_METRIC_PATHS
        or (
            include_session_timestamps
            and normalized in _SLEEP_SESSION_TIMESTAMP_NAMES
        )
    )


def _physiology_observations(
    records: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    window: tuple[str, str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    parents: dict[str, Mapping[str, Any]] = {
        _identifier(row.get("id")): row for row in records
    }
    for identity, row in parents.items():
        source_id, revision = _source_reference(row, "physiology_record")
        local_date = _observation_date(row, window)
        prefix = ".".join(
            _compact_path_segment(row.get(key) or "unknown")
            for key in ("domain", "record_type")
        )
        for key in ("status_key", "status_text"):
            if row.get(key) is not None:
                output.append({
                    "metric_key": f"physiology.{prefix}.{key}",
                    "unit": None,
                    "value": row[key],
                    "local_date": local_date,
                    "source_id": source_id,
                    "source_revision_id": revision,
                })
    for row in metrics:
        parent = parents.get(_identifier(row.get("physiology_record_id")))
        if parent is None:
            continue
        source_id, revision = _source_reference(
            parent, "physiology_record"
        )
        local_date = _observation_date(parent, window)
        prefix = ".".join(
            _compact_path_segment(parent.get(key) or "unknown")
            for key in ("domain", "record_type")
        )
        metric_key = _compact_path_segment(row.get("metric_key") or "value")
        sanitized = _sanitize_row(row)
        values: list[tuple[str, Any]] = []
        for key in ("value_number", "value_text", "value_boolean"):
            if sanitized.get(key) is not None:
                values = [("", sanitized[key])]
                break
        if not values and sanitized.get("value") is not None:
            values = _flatten_compact_values(sanitized["value"])
        unit = row.get("canonical_unit") or row.get("raw_unit")
        for suffix, value in values:
            if value is None:
                continue
            full_key = f"physiology.{prefix}.{metric_key}"
            if suffix:
                full_key += f".{suffix}"
            output.append({
                "metric_key": full_key,
                "unit": str(unit) if unit is not None else None,
                "value": value,
                "local_date": local_date,
                "source_id": source_id,
                "source_revision_id": revision,
            })
    return output


def _prior_artifact_rows(snapshot: StableSnapshot) -> tuple[Mapping[str, Any], ...]:
    by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    ordered_views = (
        "v_analysis_history_context",
        "v_current_weekly_summaries",
        "v_current_analysis_artifacts",
    )
    for name in ordered_views:
        for row in snapshot.views[name]:
            identity = _identifier(row.get("id"))
            revision = _identifier(row.get("revision_no"))
            key = (identity, revision)
            existing = by_identity.get(key)
            if existing is None:
                by_identity[key] = row
            else:
                # ``v_analysis_history_context`` adds the trusted
                # ``trust_class`` projection to the same immutable artifact
                # row exposed by the two current-artifact views.  Projection
                # metadata is not artifact content and must not make one
                # underlying row look like conflicting lineage.
                existing_content = dict(_sanitize_row(existing))
                row_content = dict(_sanitize_row(row))
                for projection_field in ("trust_class", "is_current"):
                    existing_content.pop(projection_field, None)
                    row_content.pop(projection_field, None)
                if _sha(existing_content) != _sha(row_content):
                    _fail("analysis_context_duplicate_lineage")
    return tuple(by_identity[key] for key in sorted(by_identity))


def _base_candidates(
    request: ContextBuildRequest,
    source: ContextSource,
    quality_gate: QualityGateResult,
    harness_bundle: HarnessBundle,
    deterministic_features: Sequence[Mapping[str, Any]],
    plan_adherence: Sequence[Mapping[str, Any]],
) -> tuple[list[_Candidate], dict[str, Any]]:
    periods = request.validated_periods()
    source_route = request.source_route()
    as_of = _utc(request.as_of_utc)
    snapshot = source.snapshot
    _validate_snapshot(request, snapshot, as_of)
    snapshot_hash = _snapshot_hash(snapshot)
    normalized_snapshot_hash = _normalized_snapshot_hash(snapshot)
    if (
        not isinstance(quality_gate, QualityGateResult)
        or quality_gate.snapshot_sha256 != snapshot_hash
        or quality_gate.policy_version != QUALITY_GATE_POLICY_VERSION
    ):
        _fail("analysis_context_quality_gate_lineage_invalid")
    quality_gate.validate()
    if not isinstance(harness_bundle, HarnessBundle):
        _fail("analysis_context_harness_invalid")
    if (
        harness_bundle.route != source_route
        or harness_bundle.schema_evidence.input_schema_version
        != ANALYSIS_INPUT_SCHEMA_VERSION
        or harness_bundle.schema_evidence.input_schema_sha256
        != ANALYSIS_INPUT_SCHEMA_SHA256
        or _SHA256.fullmatch(harness_bundle.schema_evidence.output_schema_sha256)
        is None
    ):
        _fail("analysis_context_harness_invalid")
    fallback_window = _input_window(periods, source_route)
    complete_start, complete_end = _completed_window(periods, source_route)
    baseline_start = periods["baseline"]["start_local_date"]
    baseline_end = periods["baseline"]["end_local_date"]
    baseline_window = (baseline_start, baseline_end)
    trend_window = _trend_window(periods, source_route)
    candidates: list[_Candidate] = []

    gate_row = quality_gate.as_dict()
    gate_row["snapshot_sha256"] = normalized_snapshot_hash
    _add_row(
        candidates,
        section="coverage",
        role="quality_gate",
        entity_type="quality_gate_result",
        row=gate_row,
        fallback_window=(complete_start, complete_end),
        trust="derived_statistic",
        revision_id=f"quality-gate:{normalized_snapshot_hash}",
        entity_id=normalized_snapshot_hash,
    )
    # The schema exposes this one record separately; section is reassigned only
    # after the common candidate validation above.
    candidates[-1].section = "quality_gate"

    for row in snapshot.coverage:
        # The quality gate validates coverage across the complete repository
        # snapshot, including the weekly baseline.  Repeating every baseline
        # day/resource row in the model context is redundant and can dominate
        # a 35-day Garmin snapshot.  Expose granular coverage only for the
        # completed target window; baseline health and physiology observations
        # remain available for trend analysis.
        if _within(row, complete_start, complete_end):
            revision = (
                _identifier(row["source_revision_id"])
                if row.get("source_revision_id") is not None
                else f"coverage:{_identifier(row.get('id'))}"
            )
            _add_row(
                candidates,
                section="coverage",
                role="coverage.resource",
                entity_type="resource_coverage",
                row=row,
                fallback_window=fallback_window,
                trust="provider_fact",
                revision_id=revision,
            )
    for role, entity_type, rows in (
        ("coverage.cursor", "garmin_sync_cursor", snapshot.cursors),
        ("coverage.capability", "garmin_resource_capability", snapshot.capabilities),
        ("coverage.quality_issue", "data_quality_issue", snapshot.quality_issues),
    ):
        for row in rows:
            if (
                role == "coverage.quality_issue"
                and row.get("local_date") is not None
                and not _within(row, complete_start, complete_end)
            ):
                continue
            _add_row(
                candidates,
                section="coverage",
                role=role,
                entity_type=entity_type,
                row=row,
                fallback_window=fallback_window,
                trust="provider_fact",
            )
    for row in snapshot.gaps:
        if _within(row, baseline_start, complete_end):
            _add_row(
                candidates,
                section="gaps",
                role="gap.open_or_deferred",
                entity_type="garmin_sync_gap",
                row=row,
                fallback_window=fallback_window,
                trust="provider_fact",
            )

    health_rows = [
        row
        for row in snapshot.views["v_current_daily_health"]
        if _within(row, *baseline_window)
    ]
    sleep_rows = [
        row
        for row in snapshot.views["v_current_sleep_sessions"]
        if _observation_date(row, trend_window) <= baseline_end
        and _observation_date(row, trend_window) >= baseline_start
    ]
    physiology_records = [
        row
        for row in snapshot.views["v_current_physiology_records"]
        if _within(row, *baseline_window)
    ]
    physiology_ids = {
        _identifier(row.get("id")) for row in physiology_records
    }
    physiology_metrics = [
        row
        for row in snapshot.views["v_current_physiology_metrics"]
        if _identifier(row.get("physiology_record_id")) in physiology_ids
    ]
    _add_compact_observations(
        candidates,
        section="health",
        role="health.aggregate_28d",
        entity_type="health_metric_aggregate",
        family="health",
        observations=_health_observations(health_rows, baseline_window),
        window=baseline_window,
    )
    trend_health_rows = [
        row for row in snapshot.views["v_current_daily_health"]
        if _within(row, *trend_window)
    ]
    _add_compact_observations(
        candidates,
        section="health",
        role="health.trend_90d",
        entity_type="health_metric_trend",
        family="health_trend",
        observations=_health_observations(trend_health_rows, trend_window),
        window=trend_window,
    )
    if source_route == "daily":
        advice_day = periods["advice"]["end_local_date"]
        morning_window = (advice_day, advice_day)
        _add_compact_observations(
            candidates,
            section="health",
            role="health.morning_recovery",
            entity_type="morning_recovery_aggregate",
            family="morning_recovery",
            observations=_morning_recovery_observations(
                trend_health_rows, morning_window
            ),
            window=morning_window,
        )
    _add_compact_observations(
        candidates,
        section="sleep",
        role="sleep.aggregate_28d",
        entity_type="sleep_metric_aggregate",
        family="sleep",
        observations=_sleep_observations(sleep_rows, baseline_window),
        window=baseline_window,
    )
    trend_sleep_rows = [
        row for row in snapshot.views["v_current_sleep_sessions"]
        if _within(row, *trend_window)
    ]
    _add_compact_observations(
        candidates,
        section="sleep",
        role="sleep.trend_90d",
        entity_type="sleep_metric_trend",
        family="sleep_trend",
        observations=_sleep_observations(trend_sleep_rows, trend_window),
        window=trend_window,
    )
    if source_route == "daily":
        advice_day = periods["advice"]["end_local_date"]
        morning_window = (advice_day, advice_day)
        morning_sleep_rows = [
            row for row in trend_sleep_rows
            if _observation_date(row, trend_window) == advice_day
        ]
        _add_compact_observations(
            candidates,
            section="sleep",
            role="sleep.morning_recovery",
            entity_type="morning_sleep_aggregate",
            family="morning_sleep",
            observations=_sleep_observations(
                morning_sleep_rows, morning_window,
                include_session_timestamps=True,
            ),
            window=morning_window,
        )
    _add_compact_observations(
        candidates,
        section="physiology",
        role="physiology.aggregate_28d",
        entity_type="physiology_metric_aggregate",
        family="physiology",
        observations=_physiology_observations(
            physiology_records, physiology_metrics, baseline_window
        ),
        window=baseline_window,
    )
    trend_physiology_records = [
        row for row in snapshot.views["v_current_physiology_records"]
        if _within(row, *trend_window)
    ]
    trend_ids = {_identifier(row.get("id")) for row in trend_physiology_records}
    trend_physiology_metrics = [
        row for row in snapshot.views["v_current_physiology_metrics"]
        if _identifier(row.get("physiology_record_id")) in trend_ids
    ]
    _add_compact_observations(
        candidates,
        section="physiology",
        role="physiology.trend_90d",
        entity_type="physiology_metric_trend",
        family="physiology_trend",
        observations=_physiology_observations(
            trend_physiology_records, trend_physiology_metrics, trend_window
        ),
        window=trend_window,
    )

    activities: dict[str, Mapping[str, Any]] = {}
    activity_window = (
        (date.fromisoformat(complete_end) - timedelta(days=_SHORT_WINDOW_DAYS - 1)).isoformat(),
        complete_end,
    )
    for row in snapshot.views["v_current_activities"]:
        if not _within(row, *activity_window):
            continue
        identity = _identifier(row.get("id"))
        revision = _row_revision(row, "activity", identity)
        activities[identity] = row
        summary = {
            key: value for key, value in _sanitize_row(row).items()
            if not key.startswith(("fit_", "weather_"))
            and key not in {"active_fit_revision_id", "active_weather_revision_id"}
        }
        summary.update({
            "source_count": 1,
            "source_revision_count": 1,
            "aggregate_sha256": _sha(summary),
        })
        _add_row(
            candidates,
            section="activities",
            role="activity.summary",
            entity_type="activity",
            row=summary,
            fallback_window=activity_window,
            trust="provider_fact",
            entity_id=identity,
            revision_id=revision,
            display_fields=_DISPLAY_FIELDS,
        )
        fit_values = {
            key.removeprefix("fit_"): row.get(key)
            for key in (
                "fit_avg_heart_rate_bpm", "fit_max_heart_rate_bpm",
                "fit_avg_running_cadence_spm",
                "fit_avg_speed_mps", "fit_avg_power_w",
                "fit_avg_temperature_c", "fit_total_ascent_m",
            )
            if row.get(key) is not None
        }
        if fit_values and row.get("active_fit_revision_id") is not None:
            _add_row(
                candidates,
                section="activities",
                role="activity.fit_summary",
                entity_type="activity_fit_summary",
                row={"activity_id": identity, "local_date": row.get("local_date"), **fit_values},
                fallback_window=activity_window,
                trust="provider_fact",
                entity_id=f"{identity}:fit",
                revision_id=_identifier(row["active_fit_revision_id"]),
            )
        weather_values = {
            key.removeprefix("weather_"): row.get(key)
            for key in (
                "weather_temperature_provider_value",
                "weather_relative_humidity_percent", "weather_condition",
                "weather_wind_speed_provider_value", "weather_observed_at",
            )
            if row.get(key) is not None
        }
        if weather_values and row.get("active_weather_revision_id") is not None:
            weather_values["provider_numeric_units"] = "unspecified"
            _add_row(
                candidates,
                section="activities",
                role="activity.weather_summary",
                entity_type="activity_weather_summary",
                row={"activity_id": identity, "local_date": row.get("local_date"), **weather_values},
                fallback_window=activity_window,
                trust="provider_fact",
                entity_id=f"{identity}:weather",
                revision_id=_identifier(row["active_weather_revision_id"]),
            )

    # A raw FIT payload can enter the model context only when the host binds
    # exact activity IDs on this request.  Normal routes leave both values
    # empty, so no file or decoded sample stream is reachable here.
    if source.explicit_fit_messages or request.explicit_fit_activity_ids:
        try:
            explicit = build_explicit_fit_context(
                request.explicit_fit_activity_ids,
                source.explicit_fit_messages,
                include_gps=request.explicit_fit_include_gps,
                max_bytes=request.max_context_bytes,
            )
        except ExplicitFitContextError as error:
            _fail(str(error))
        entries = explicit["activities"]
        for entry in entries:
            activity_id = str(entry["activity_id"])
            activity = activities.get(activity_id)
            if activity is None:
                _fail("fit_context_activity_not_in_snapshot")
            active_revision = activity.get("active_fit_revision_id")
            if active_revision is None or str(active_revision) != str(entry["source_revision_id"]):
                _fail("fit_context_revision_not_current")
            local_day = str(activity.get("local_date"))
            _add_row(
                candidates,
                section="activities",
                role="activity.explicit_fit",
                entity_type="activity_fit_explicit",
                row=entry,
                fallback_window=(local_day, local_day),
                trust="provider_fact",
                entity_id=activity_id,
                revision_id=str(entry["source_revision_id"]),
            )

    if (
        not isinstance(source.technical_samples, tuple)
        or len(source.technical_samples) > _MAX_SAMPLE_SUMMARIES
    ):
        _fail("analysis_context_sample_limit_exceeded")
    sample_total = 0
    sample_keys: set[tuple[str, str, str, str]] = set()
    for row in source.technical_samples:
        required = {
            "activity_id",
            "metric",
            "start_utc",
            "end_utc",
            "count",
            "minimum",
            "maximum",
            "latest",
            "truncated",
        }
        if not isinstance(row, Mapping) or set(row) != required:
            _fail("analysis_context_sample_result_invalid")
        activity_id = _identifier(row["activity_id"])
        activity = activities.get(activity_id)
        if activity is None or row["metric"] not in _SAMPLE_METRICS:
            _fail("analysis_context_sample_lineage_invalid")
        start_at, end_at = _utc(row["start_utc"]), _utc(row["end_utc"])
        activity_start = _utc(activity["start_time_utc"])
        activity_end = _utc(activity["end_time_utc"])
        if start_at >= end_at or start_at < activity_start or end_at > activity_end:
            _fail("analysis_context_sample_window_invalid")
        count = row["count"]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= 100
            or not isinstance(row["truncated"], bool)
        ):
            _fail("analysis_context_sample_result_invalid")
        for key in ("minimum", "maximum", "latest"):
            value = row[key]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                _fail("analysis_context_sample_result_invalid")
        key = (activity_id, row["metric"], row["start_utc"], row["end_utc"])
        if key in sample_keys:
            _fail("analysis_context_duplicate_sample_result")
        sample_keys.add(key)
        sample_total += count
        _add_row(
            candidates,
            section="technical_samples",
            role="activity.sample_summary",
            entity_type="activity_sample_summary",
            row=row,
            fallback_window=_row_date_window(activity, fallback_window),
            trust="derived_statistic",
            origin="derived_statistic",
            entity_id=f"{activity_id}:{row['metric']}:{row['start_utc']}",
            revision_id=_row_revision(activity, "activity", activity_id),
        )
    if sample_total > _MAX_SAMPLE_ROWS:
        _fail("analysis_context_sample_limit_exceeded")

    snapshot_revisions = _revision_universe(snapshot)
    for section, role, entity_type, rows in (
        (
            "deterministic_features",
            "feature.deterministic",
            "deterministic_feature",
            deterministic_features,
        ),
        (
            "plan_adherence",
            "plan.adherence",
            "plan_adherence",
            plan_adherence,
        ),
    ):
        if len(rows) > _MAX_ITEMS:
            _fail("analysis_context_feature_limit_exceeded")
        for row in rows:
            if not isinstance(row, Mapping):
                _fail("analysis_context_feature_invalid")
            origin = row.get("value_origin")
            allowed_origins = (
                _TRUST
                if section == "deterministic_features"
                else frozenset({"derived_statistic"})
            )
            if origin not in allowed_origins:
                _fail("analysis_context_feature_origin_invalid")
            lineage = row.get("input_revision_ids")
            if (
                not isinstance(lineage, (list, tuple))
                or any(
                    isinstance(item, bool) or not isinstance(item, (str, int))
                    for item in lineage
                )
            ):
                _fail("analysis_context_feature_lineage_invalid")
            revisions = tuple(sorted({_identifier(item) for item in lineage}))
            if len(revisions) != len(lineage) or not set(revisions) <= snapshot_revisions:
                _fail("analysis_context_feature_lineage_invalid")
            if row.get("subject_id") not in (None, request.subject_id):
                _fail("analysis_context_cross_subject")
            identity = _identifier(
                row.get("key", row.get("id", _sha(_sanitize_row(row))[:32]))
            )
            algorithm = _identifier(
                row.get("algorithm_version", FEATURE_LIBRARY_VERSION)
            )
            _add_row(
                candidates,
                section=section,
                role=role,
                entity_type=entity_type,
                row=row,
                fallback_window=fallback_window,
                trust=str(origin),
                origin=str(origin),
                entity_id=identity,
                revision_id=f"{entity_type}:{algorithm}:{_sha(_sanitize_row(row))}",
            )

    prior_rows = _prior_artifact_rows(snapshot)
    artifacts_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for artifact_row in prior_rows:
        artifacts_by_id.setdefault(
            _identifier(artifact_row.get("id")), []
        ).append(artifact_row)
    current_plans = snapshot.views["v_current_training_plans"]
    regeneration_artifact: tuple[str, str] | None = None
    if request.route == "regenerate":
        matches = [
            row for row in snapshot.views["v_current_analysis_artifacts"]
            if row.get("id") == request.artifact_id
            and row.get("subject_id") == request.subject_id
        ]
        if len(matches) != 1:
            _fail("analysis_context_regeneration_artifact_invalid")
        target = matches[0]
        regeneration_artifact = (
            _identifier(target.get("id")),
            _identifier(target.get("revision_no")),
        )
        _add_row(
            candidates,
            section="prior_artifacts",
            role="regeneration.source_artifact",
            entity_type="analysis_artifact",
            row=target,
            fallback_window=fallback_window,
            trust="prior_model_output",
            origin="prior_model_output",
            entity_id=regeneration_artifact[0],
        )
    plan_ids: set[str] = set()
    current_plan_artifacts: set[tuple[str, str]] = set()
    for row in current_plans:
        if (
            request.source_route() == "revise_plan"
            and row.get("id") != request.plan_id
        ):
            continue
        if not _within(row, complete_start, periods["plan"]["end_local_date"] if periods["plan"] else complete_end):
            continue
        identity = _identifier(row.get("id"))
        plan_ids.add(identity)
        artifact_id = _identifier(
            row.get("analysis_artifact_id"),
            "analysis_context_plan_lineage_invalid",
        )
        matching_artifacts = artifacts_by_id.get(artifact_id, [])
        if len(matching_artifacts) != 1:
            _fail("analysis_context_plan_lineage_invalid")
        plan_artifact = matching_artifacts[0]
        if (
            plan_artifact.get("artifact_kind") != "weekly_training_plan"
            or plan_artifact.get("subject_id") != request.subject_id
            or plan_artifact.get("period_start_local_date")
            != row.get("plan_start_local_date")
            or plan_artifact.get("period_end_local_date")
            != row.get("plan_end_local_date")
        ):
            _fail("analysis_context_plan_lineage_invalid")
        artifact_revision = _identifier(plan_artifact.get("revision_no"))
        current_plan_artifacts.add((artifact_id, artifact_revision))
        _add_row(
            candidates,
            section="current_plan",
            role="plan.current",
            entity_type="training_plan",
            row=row,
            fallback_window=fallback_window,
            trust="prior_model_output",
            origin="prior_model_output",
            entity_id=identity,
        )
        _add_row(
            candidates,
            section="current_plan",
            role="plan.current_revision",
            entity_type="analysis_artifact",
            row=plan_artifact,
            fallback_window=fallback_window,
            trust="prior_model_output",
            origin="prior_model_output",
            entity_id=artifact_id,
        )
    for row in snapshot.views["v_training_plan_items"]:
        plan_id = _identifier(row.get("training_plan_id"))
        if plan_id not in plan_ids:
            continue
        _add_row(
            candidates,
            section="current_plan",
            role="plan.current_item",
            entity_type="training_plan_item",
            row=row,
            fallback_window=fallback_window,
            trust="prior_model_output",
            origin="prior_model_output",
        )

    if request.source_route() == "revise_plan":
        effective = periods["effective_local_date"]
        matching_reasons = [
            row for row in snapshot.plan_reasons
            if row.get("id") == request.reason_event_id
            and row.get("current_plan_id") == request.plan_id
            and row.get("effective_local_date") == effective
        ]
        if len(matching_reasons) != 1:
            _fail("analysis_context_plan_reason_invalid")
        reason = matching_reasons[0]
        _add_row(
            candidates,
            section="current_plan",
            role="plan.revision_reason",
            entity_type="conversation_event",
            row=reason,
            fallback_window=(effective, effective),
            trust="user_asserted",
            origin="user_asserted",
            entity_id=_identifier(reason.get("id")),
            revision_id=f"conversation_event:{_identifier(reason.get('id'))}:{_identifier(reason.get('source_revision_id'))}",
        )

    daily_rows = sorted(
        (
            row
            for row in prior_rows
            if row.get("artifact_kind") in {"daily_summary", "daily_training_advice"}
            and _within(row, baseline_start, complete_end)
        ),
        key=lambda row: (
            str(row.get("period_end_local_date")),
            str(row.get("artifact_kind")),
            _identifier(row.get("id")),
        ),
        reverse=True,
    )
    daily_ids = {
        (_identifier(row.get("id")), _identifier(row.get("revision_no")))
        for row in daily_rows[: int(_POLICY["maximum_recent_daily_artifacts"])]
    }
    weekly_rows = [
        row
        for row in prior_rows
        if row.get("artifact_kind")
        in {"weekly_summary", "weekly_training_plan"}
        and str(row.get("period_end_local_date", "")) < complete_start
    ]
    latest_weekly: dict[str, Mapping[str, Any]] = {}
    for row in sorted(
        weekly_rows,
        key=lambda item: (
            str(item.get("period_end_local_date")),
            _identifier(item.get("revision_no")),
            _identifier(item.get("id")),
        ),
    ):
        latest_weekly[str(row.get("artifact_kind"))] = row
    protected_weekly = {
        (_identifier(row.get("id")), _identifier(row.get("revision_no")))
        for row in latest_weekly.values()
    }
    for row in prior_rows:
        identity_key = (
            _identifier(row.get("id")),
            _identifier(row.get("revision_no")),
        )
        if identity_key in current_plan_artifacts:
            continue
        if identity_key == regeneration_artifact:
            continue
        if identity_key not in daily_ids | protected_weekly:
            continue
        if row.get("trust_class") not in (None, "prior_model_output"):
            _fail("analysis_context_prior_output_trust_invalid")
        _add_row(
            candidates,
            section="prior_artifacts",
            role="artifact.prior_model_output",
            entity_type="analysis_artifact",
            row=row,
            fallback_window=fallback_window,
            trust="prior_model_output",
            origin="prior_model_output",
            prune_stage=3 if identity_key in daily_ids else None,
        )

    for row in snapshot.views["v_active_user_facts"]:
        scope = row.get("scope")
        if scope not in _FACT_SCOPES:
            _fail("analysis_context_fact_scope_invalid")
        effective = (
            _utc(row["effective_from_utc"])
            if row.get("effective_from_utc") is not None
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        expiry = (
            _utc(row["expires_at_utc"])
            if row.get("expires_at_utc") is not None
            else None
        )
        if expiry is not None and expiry <= effective:
            _fail("analysis_context_fact_range_invalid")
        if scope == "message_only" or effective > as_of or (
            expiry is not None and as_of >= expiry
        ):
            continue
        _add_row(
            candidates,
            section="user_facts",
            role="fact.active",
            entity_type="user_fact",
            row=row,
            fallback_window=fallback_window,
            trust="user_asserted",
            origin="user_asserted",
        )

    policy_window = (as_of.astimezone(_SG).date().isoformat(),) * 2
    policy_records = (
        (
            "context_policy",
            CONTEXT_POLICY_VERSION,
            CONTEXT_POLICY_SHA256,
        ),
        (
            "analysis_input_schema",
            ANALYSIS_INPUT_SCHEMA_VERSION,
            ANALYSIS_INPUT_SCHEMA_SHA256,
        ),
        (
            "quality_gate_policy",
            QUALITY_GATE_POLICY_VERSION,
            QUALITY_GATE_POLICY_SHA256,
        ),
        ("feature_library", FEATURE_LIBRARY_VERSION, None),
        ("feature_conflict_policy", CONFLICT_POLICY_VERSION, CONFLICT_POLICY_SHA256),
        (
            "training_safety_policy",
            TRAINING_SAFETY_POLICY_VERSION,
            TRAINING_SAFETY_POLICY_SHA256,
        ),
        (
            "harness_bundle",
            harness_bundle.harness_version,
            _sha(harness_bundle.audit_record()),
        ),
        (
            "analysis_output_schema",
            harness_bundle.schema_evidence.output_schema_version,
            harness_bundle.schema_evidence.output_schema_sha256,
        ),
    )
    for name, version, digest in policy_records:
        row = {"name": name, "version": str(version), "sha256": digest}
        _add_row(
            candidates,
            section="policies",
            role=f"policy.{name}",
            entity_type="analysis_policy",
            row=row,
            fallback_window=policy_window,
            trust="unknown",
            origin="unknown",
            entity_id=name,
            revision_id=f"{name}:{version}:{digest or 'version-only'}",
        )
    return candidates, periods


def _prepare_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    ordered = sorted(candidates, key=lambda candidate: candidate.sort_key())
    if len(ordered) > _MAX_ITEMS:
        _fail("analysis_context_manifest_limit_exceeded")
    seen: set[tuple[str, str, str]] = set()
    for ordinal, candidate in enumerate(ordered):
        key = (candidate.entity_type, candidate.entity_id, candidate.revision_id)
        if key in seen:
            _fail("analysis_context_duplicate_lineage")
        seen.add(key)
        candidate.original_ordinal = ordinal
    quality = [candidate for candidate in ordered if candidate.section == "quality_gate"]
    if len(quality) != 1:
        _fail("analysis_context_quality_gate_invalid")
    return ordered


def _render(
    request: ContextBuildRequest,
    periods: Mapping[str, Any],
    candidates: Sequence[_Candidate],
    omissions: Sequence[Mapping[str, Any]],
    *,
    strict: bool = True,
) -> tuple[dict[str, Any], str, int]:
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in _SECTIONS}
    manifests: list[dict[str, Any]] = []
    quality_item: dict[str, Any] | None = None
    for ordinal, candidate in enumerate(candidates):
        item = {"ordinal": ordinal, "content": deepcopy(candidate.content)}
        if candidate.section == "quality_gate":
            quality_item = item
        else:
            sections[candidate.section].append(item)
        manifests.append(candidate.manifest(ordinal))
    if quality_item is None:
        _fail("analysis_context_quality_gate_invalid")
    snapshot = request.source_route()
    context = {
        "schema_version": ANALYSIS_INPUT_SCHEMA_VERSION,
        "run": {
            "run_key": request.run_key,
            "route": request.route,
            "source_route": snapshot,
            "as_of_utc": request.as_of_utc,
        },
        "subject": {
            "subject_id": request.subject_id,
            "timezone": "Asia/Hong_Kong",
            "provider": "garmin",
            "identity_kind": "account",
            "verified": True,
        },
        "target_periods": deepcopy(dict(periods)),
        "quality_gate": quality_item,
        **sections,
        "input_manifest": manifests,
        "context_limits": {
            "max_utf8_bytes": request.max_context_bytes,
            "pruning_policy_version": CONTEXT_POLICY_VERSION,
            "applied_pruning_stages": sorted(
                {int(item["stage"]) for item in omissions}
            ),
            "omission_count": _omission_count(omissions),
            "omissions": [deepcopy(dict(item)) for item in omissions],
        },
    }
    if strict:
        _schema_validate(context)
        _validate_manifest_bindings(context)
    serialized = _canonical(context)
    return context, serialized, len(serialized.encode("utf-8"))


def _omission(
    candidate: _Candidate,
    *,
    stage: int,
    before_sha256: str,
    after_sha256: str | None,
    removed_fields: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "stage": stage,
        "reason_code": _PRUNE_CODES[stage - 1],
        "input_role": candidate.input_role,
        "source_entity_type": candidate.entity_type,
        "source_entity_id": candidate.entity_id,
        "source_revision_id": candidate.revision_id,
        "original_ordinal": candidate.original_ordinal,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "removed_fields": list(sorted(removed_fields)),
    }


def _omissions_for_selected(
    selected: Sequence[_Candidate], stage: int
) -> list[dict[str, Any]]:
    if len(selected) < 64:
        return [
            _omission(
                candidate,
                stage=stage,
                before_sha256=_sha(candidate.content),
                after_sha256=None,
            )
            for candidate in selected
        ]
    grouped: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in selected:
        grouped.setdefault(
            (candidate.input_role, candidate.entity_type), []
        ).append(candidate)
    omissions: list[dict[str, Any]] = []
    for (role, entity_type), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda item: item.original_ordinal)
        if len(ordered) == 1:
            omissions.append(
                _omission(
                    ordered[0],
                    stage=stage,
                    before_sha256=_sha(ordered[0].content),
                    after_sha256=None,
                )
            )
            continue
        aggregate = _sha([
            {
                "entity_id": item.entity_id,
                "revision_id": item.revision_id,
                "original_ordinal": item.original_ordinal,
                "before_sha256": _sha(item.content),
            }
            for item in ordered
        ])
        omissions.append({
            "stage": stage,
            "reason_code": _PRUNE_CODES[stage - 1],
            "input_role": role,
            "source_entity_type": entity_type,
            "source_entity_id": (
                f"group:{len(ordered)}:{ordered[0].original_ordinal}:"
                f"{ordered[-1].original_ordinal}"
            ),
            "source_revision_id": f"aggregate:{aggregate}",
            "original_ordinal": ordered[0].original_ordinal,
            "before_sha256": aggregate,
            "after_sha256": None,
            "removed_fields": [],
            "omitted_count": len(ordered),
        })
    return omissions


def _omission_count(omissions: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(item.get("omitted_count", 1)) for item in omissions)


def _prune(
    request: ContextBuildRequest,
    periods: Mapping[str, Any],
    candidates: list[_Candidate],
) -> tuple[dict[str, Any], str, int]:
    remaining = list(candidates)
    omissions: list[dict[str, Any]] = []
    context, serialized, size = _render(
        request, periods, remaining, omissions, strict=False
    )
    if size <= request.max_context_bytes:
        return _render(request, periods, remaining, omissions)

    def stage_state(
        eligible: Sequence[_Candidate], stage: int, count: int
    ) -> tuple[list[_Candidate], list[dict[str, Any]]]:
        selected = eligible[:count]
        trial_omissions = list(omissions)
        if stage < 4:
            selected_ids = {id(candidate) for candidate in selected}
            trial_remaining = [
                candidate
                for candidate in remaining
                if id(candidate) not in selected_ids
            ]
            trial_omissions.extend(_omissions_for_selected(selected, stage))
            return trial_remaining, trial_omissions
        replacements: dict[int, _Candidate] = {}
        for candidate in selected:
            replacement = deepcopy(candidate)
            removed_fields = tuple(
                field
                for field in candidate.display_fields
                if field in candidate.content
            )
            replacement.content = {
                key: value
                for key, value in candidate.content.items()
                if key not in removed_fields
            }
            replacements[id(candidate)] = replacement
            trial_omissions.append(
                _omission(
                    candidate,
                    stage=stage,
                    before_sha256=_sha(candidate.content),
                    after_sha256=_sha(replacement.content),
                    removed_fields=removed_fields,
                )
            )
        return [
            replacements.get(id(candidate), candidate) for candidate in remaining
        ], trial_omissions

    for stage in range(1, 5):
        eligible = [
            candidate
            for candidate in remaining
            if (
                candidate.prune_stage == stage
                if stage < 4
                else bool(candidate.display_fields)
            )
        ]
        if stage == 3:
            eligible.sort(
                key=lambda candidate: (
                    candidate.window_end,
                    candidate.window_start,
                    candidate.original_ordinal,
                )
            )
        else:
            eligible.sort(key=lambda candidate: candidate.original_ordinal)
        if not eligible:
            continue
        full_remaining, full_omissions = stage_state(
            eligible, stage, len(eligible)
        )
        full_context, full_serialized, full_size = _render(
            request,
            periods,
            full_remaining,
            full_omissions,
            strict=False,
        )
        if full_size >= size and full_size > request.max_context_bytes:
            continue
        if full_size > request.max_context_bytes:
            remaining, omissions = full_remaining, full_omissions
            context, serialized, size = (
                full_context,
                full_serialized,
                full_size,
            )
            continue
        low, high = 1, len(eligible)
        best = (full_remaining, full_omissions, full_context, full_serialized, full_size)
        while low <= high:
            middle = (low + high) // 2
            trial_remaining, trial_omissions = stage_state(
                eligible, stage, middle
            )
            trial_context, trial_serialized, trial_size = _render(
                request,
                periods,
                trial_remaining,
                trial_omissions,
                strict=False,
            )
            if trial_size <= request.max_context_bytes:
                best = (
                    trial_remaining,
                    trial_omissions,
                    trial_context,
                    trial_serialized,
                    trial_size,
                )
                high = middle - 1
            else:
                low = middle + 1
        remaining, omissions, context, serialized, size = best
        return _render(request, periods, remaining, omissions)
    _fail("analysis_context_unprunable_limit_exceeded")


def _flatten_context_items(context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = [context["quality_gate"]]
    for section in _SECTIONS:
        section_items = context[section]
        if not isinstance(section_items, list):
            _fail("analysis_context_manifest_binding_invalid")
        items.extend(section_items)
    return items


def _validate_manifest_bindings(context: Mapping[str, Any]) -> None:
    manifests = context.get("input_manifest")
    if not isinstance(manifests, list):
        _fail("analysis_context_manifest_binding_invalid")
    items = _flatten_context_items(context)
    if len(items) != len(manifests) or len(items) > _MAX_ITEMS:
        _fail("analysis_context_manifest_binding_invalid")
    item_by_ordinal: dict[int, Mapping[str, Any]] = {}
    for item in items:
        ordinal = item.get("ordinal")
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal in item_by_ordinal
            or not isinstance(item.get("content"), Mapping)
        ):
            _fail("analysis_context_manifest_binding_invalid")
        item_by_ordinal[ordinal] = item
    if set(item_by_ordinal) != set(range(len(items))):
        _fail("analysis_context_manifest_binding_invalid")
    seen_lineage: set[tuple[str, str, str]] = set()
    for expected_ordinal, manifest in enumerate(manifests):
        if manifest.get("ordinal") != expected_ordinal:
            _fail("analysis_context_manifest_binding_invalid")
        item = item_by_ordinal.get(expected_ordinal)
        if item is None or manifest.get("input_sha256") != _sha(item["content"]):
            _fail("analysis_context_manifest_hash_invalid")
        lineage = (
            manifest.get("source_entity_type"),
            manifest.get("source_entity_id"),
            manifest.get("source_revision_id"),
        )
        if lineage in seen_lineage:
            _fail("analysis_context_duplicate_lineage")
        seen_lineage.add(lineage)
        if (
            manifest.get("trust_class") not in _TRUST
            or manifest.get("value_origin") not in _TRUST
            or (
                manifest.get("trust_class") == "prior_model_output"
                and manifest.get("value_origin") != "prior_model_output"
            )
        ):
            _fail("analysis_context_trust_invalid")
    limits = context.get("context_limits")
    if not isinstance(limits, Mapping):
        _fail("analysis_context_omission_invalid")
    omissions = limits.get("omissions")
    if (
        not isinstance(omissions, list)
        or limits.get("omission_count") != _omission_count(omissions)
        or [item.get("stage") for item in omissions]
        != sorted(item.get("stage") for item in omissions)
    ):
        _fail("analysis_context_omission_invalid")
    seen_omissions: set[tuple[int, int, str]] = set()
    for omission in omissions:
        stage = omission.get("stage")
        original = omission.get("original_ordinal")
        before = omission.get("before_sha256")
        key = (stage, original, str(before))
        omitted_count = omission.get("omitted_count", 1)
        grouped = "omitted_count" in omission
        if (
            isinstance(stage, bool)
            or not isinstance(stage, int)
            or not 1 <= stage <= 4
            or isinstance(original, bool)
            or not isinstance(original, int)
            or key in seen_omissions
            or omission.get("reason_code") != _PRUNE_CODES[stage - 1]
            or isinstance(omitted_count, bool)
            or not isinstance(omitted_count, int)
            or not 1 <= omitted_count <= _MAX_ITEMS
            or (
                grouped
                and (
                    omitted_count < 2
                    or stage == 4
                    or not str(omission.get("source_entity_id", "")).startswith(
                        f"group:{omitted_count}:"
                    )
                    or not str(
                        omission.get("source_revision_id", "")
                    ).startswith("aggregate:")
                )
            )
        ):
            _fail("analysis_context_omission_invalid")
        seen_omissions.add(key)


def validate_analysis_context(context: Mapping[str, Any]) -> None:
    if not isinstance(context, Mapping):
        _fail("analysis_context_type_invalid")
    _canonical(context)
    _schema_validate(context)
    _validate_manifest_bindings(context)
    limit = context["context_limits"]["max_utf8_bytes"]
    if isinstance(limit, bool) or not isinstance(limit, int):
        _fail("analysis_context_limit_invalid")
    if len(_canonical(context).encode("utf-8")) > limit:
        _fail("analysis_context_limit_exceeded")


def parse_canonical_context_json(value: str) -> dict[str, Any]:
    payload = parse_canonical_json(value)
    if not isinstance(payload, dict):
        _fail("analysis_context_type_invalid")
    validate_analysis_context(payload)
    return payload


class AnalysisContextBuilder:
    """Pure A3-10 builder.  It never logs or returns context on failure."""

    policy_version = CONTEXT_POLICY_VERSION
    policy_sha256 = CONTEXT_POLICY_SHA256
    input_schema_version = ANALYSIS_INPUT_SCHEMA_VERSION
    input_schema_sha256 = ANALYSIS_INPUT_SCHEMA_SHA256

    def build(
        self,
        request: ContextBuildRequest,
        source: ContextSource,
        *,
        quality_gate: QualityGateResult,
        harness_bundle: HarnessBundle,
        deterministic_features: Sequence[Mapping[str, Any]] = (),
        plan_adherence: Sequence[Mapping[str, Any]] = (),
    ) -> ContextBuildResult:
        if not isinstance(request, ContextBuildRequest) or not isinstance(
            source, ContextSource
        ):
            _fail("analysis_context_request_invalid")
        candidates, periods = _base_candidates(
            request,
            source,
            quality_gate,
            harness_bundle,
            deterministic_features,
            plan_adherence,
        )
        candidates = _prepare_candidates(candidates)
        context, serialized, size = _prune(request, periods, candidates)
        validate_analysis_context(context)
        if serialized != _canonical(context) or size != len(
            serialized.encode("utf-8")
        ):
            _fail("analysis_context_serialization_invalid")
        return ContextBuildResult(
            context=context,
            canonical_json=serialized,
            context_snapshot_sha256=sha256(
                serialized.encode("utf-8")
            ).hexdigest(),
            utf8_bytes=size,
        )
