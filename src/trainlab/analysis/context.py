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

_SG = ZoneInfo("Asia/Singapore")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_KEY = re.compile(r"^[A-Za-z0-9_.:%-]{1,256}$")
_TRUST = frozenset(_POLICY["trust_classes"])
_FACT_SCOPES = frozenset(_POLICY["fact_scopes"])
_SAMPLE_METRICS = frozenset(_POLICY["technical_sample_metrics"])
_MAX_ITEMS = int(_POLICY["maximum_manifest_items"])
_MAX_SAMPLE_SUMMARIES = int(_POLICY["maximum_technical_sample_summaries"])
_MAX_SAMPLE_ROWS = int(_POLICY["maximum_technical_sample_rows"])
_PRUNE_CODES = tuple(_POLICY["pruning_order"])
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
    max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES

    def source_route(self) -> SourceRoute:
        if self.route == "regenerate":
            if self.regenerate_source_route not in {"daily", "weekly", "revise_plan"}:
                _fail("analysis_context_regenerate_route_invalid")
            return self.regenerate_source_route
        if self.regenerate_source_route is not None:
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
                summary_day - timedelta(days=int(_POLICY["daily_baseline_days"])),
                summary_day - timedelta(days=1),
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
                review_start - timedelta(days=int(_POLICY["weekly_baseline_days"])),
                review_start - timedelta(days=1),
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
                effective - timedelta(days=int(_POLICY["weekly_baseline_days"])),
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
        start = periods["baseline"]["start_local_date"]
        source = self.source_route()
        if source == "daily":
            end = periods["advice"]["end_local_date"]
        elif source == "weekly":
            end = periods["review"]["end_local_date"]
        else:
            end = periods["plan"]["end_local_date"]
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
    return ContextSource(snapshot=snapshot, technical_samples=samples)


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
            output[target_key] = deepcopy(value)
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
            timezone="Asia/Singapore",
            provider="garmin",
            identity_kind="account",
            verified=True,
        )
    ):
        _fail("analysis_context_snapshot_subject_invalid")
    rows = _snapshot_rows(snapshot)
    if len(rows) > _MAX_ITEMS:
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


def _input_window(periods: Mapping[str, Any], source_route: SourceRoute) -> tuple[str, str]:
    start = periods["baseline"]["start_local_date"]
    if source_route == "daily":
        end = periods["summary"]["end_local_date"]
    elif source_route == "weekly":
        end = periods["review"]["end_local_date"]
    else:
        end = periods["plan"]["end_local_date"]
    return start, end


def _within(row: Mapping[str, Any], start: str, end: str) -> bool:
    row_start, row_end = _row_date_window(row, (start, end))
    return row_end >= start and row_start <= end


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
            elif _sha(_sanitize_row(existing)) != _sha(_sanitize_row(row)):
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
        if _within(row, baseline_start, complete_end):
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

    for row in snapshot.views["v_current_daily_health"]:
        if _within(row, baseline_start, complete_end):
            _add_row(
                candidates,
                section="health",
                role="health.daily",
                entity_type="daily_health",
                row=row,
                fallback_window=fallback_window,
                trust="provider_fact",
                display_fields=_DISPLAY_FIELDS,
            )
    for row in snapshot.views["v_current_sleep_sessions"]:
        if _within(row, baseline_start, complete_end):
            _add_row(
                candidates,
                section="sleep",
                role="sleep.session",
                entity_type="sleep_session",
                row=row,
                fallback_window=fallback_window,
                trust="provider_fact",
                display_fields=_DISPLAY_FIELDS,
            )

    physiology_records = {
        _identifier(row.get("id")): row
        for row in snapshot.views["v_current_physiology_records"]
        if _within(row, baseline_start, complete_end)
    }
    for identity, row in physiology_records.items():
        origin = _origin(row.get("value_origin"), "provider_derived")
        _add_row(
            candidates,
            section="physiology",
            role="physiology.record",
            entity_type="physiology_record",
            row=row,
            fallback_window=fallback_window,
            trust=origin,
            origin=origin,
            entity_id=identity,
            display_fields=_DISPLAY_FIELDS,
        )
    for row in snapshot.views["v_current_physiology_metrics"]:
        parent = physiology_records.get(
            _identifier(row.get("physiology_record_id"))
        )
        if parent is None:
            continue
        origin = _origin(row.get("value_origin"), "provider_derived")
        _add_row(
            candidates,
            section="physiology",
            role="physiology.metric",
            entity_type="physiology_metric",
            row=row,
            fallback_window=_row_date_window(parent, fallback_window),
            trust=origin,
            origin=origin,
            revision_id=_row_revision(
                parent, "physiology_record", _identifier(parent.get("id"))
            ),
            display_fields=_DISPLAY_FIELDS,
        )

    feature_revisions = {
        _identifier(revision, "analysis_context_feature_lineage_invalid")
        for feature in deterministic_features
        for revision in feature.get("input_revision_ids", ())
    }
    activities: dict[str, Mapping[str, Any]] = {}
    for row in snapshot.views["v_current_activities"]:
        if not _within(row, complete_start, complete_end):
            continue
        identity = _identifier(row.get("id"))
        revision = _row_revision(row, "activity", identity)
        activities[identity] = row
        can_prune_old = (
            source_route == "weekly"
            and row.get("local_date") != complete_end
            and revision in feature_revisions
        )
        _add_row(
            candidates,
            section="activities",
            role="activity.summary",
            entity_type="activity",
            row=row,
            fallback_window=(complete_start, complete_end),
            trust="provider_fact",
            entity_id=identity,
            revision_id=revision,
            prune_stage=2 if can_prune_old else None,
            display_fields=_DISPLAY_FIELDS,
        )
    for role, entity_type, view in (
        ("activity.segment", "activity_segment", "v_activity_segments"),
        (
            "activity.metric_source",
            "activity_metric_source",
            "v_activity_metric_sources",
        ),
    ):
        for row in snapshot.views[view]:
            activity_id = _identifier(row.get("activity_id"))
            activity = activities.get(activity_id)
            if activity is None:
                continue
            _add_row(
                candidates,
                section="activities",
                role=role,
                entity_type=entity_type,
                row=row,
                fallback_window=_row_date_window(activity, fallback_window),
                trust="provider_fact",
                revision_id=(
                    _identifier(row["source_revision_id"])
                    if row.get("source_revision_id") is not None
                    else _row_revision(activity, "activity", activity_id)
                ),
                prune_stage=1,
                display_fields=_DISPLAY_FIELDS,
            )
    for row in snapshot.activity_stages:
        identity = _identifier(row.get("id"))
        if identity in activities:
            _add_row(
                candidates,
                section="activities",
                role="activity.stage_status",
                entity_type="activity_stage_status",
                row=row,
                fallback_window=_row_date_window(activities[identity], fallback_window),
                trust="provider_fact",
                revision_id=_row_revision(activities[identity], "activity", identity),
                entity_id=identity,
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
            "timezone": "Asia/Singapore",
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
            "omission_count": len(omissions),
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
            trial_omissions.extend(
                _omission(
                    candidate,
                    stage=stage,
                    before_sha256=_sha(candidate.content),
                    after_sha256=None,
                )
                for candidate in selected
            )
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
        or limits.get("omission_count") != len(omissions)
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
        if (
            isinstance(stage, bool)
            or not isinstance(stage, int)
            or not 1 <= stage <= 4
            or isinstance(original, bool)
            or not isinstance(original, int)
            or key in seen_omissions
            or omission.get("reason_code") != _PRUNE_CODES[stage - 1]
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
