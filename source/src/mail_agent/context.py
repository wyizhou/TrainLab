"""M4-06: bounded, schema-checked, read-only mail context snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.resources import resource_bytes

from .repository import InputDraft

MAX_TRIGGER_BYTES = 65_536
MAX_THREAD_BYTES = 131_072
MAX_THREAD_MESSAGES = 20
MAX_PRIOR_RESPONSES = 5
MAX_COMPLETED_DAYS = 28
MAX_ARTIFACTS = 8
MAX_CONTEXT_BYTES = 1_000_000
MAX_EXTENSION_DAYS = 30
MAX_FACTS = 100
MAX_EVENTS = 100
MAX_QUALITY = 100
_EXTENSION_REASONS = frozenset(
    {"explicit_earlier_date", "explicit_date_range", "plan_history_question"}
)
_BAD_KEY = re.compile(
    r"(?:lat(?:itude)?|lon(?:gitude)?|gps|geo(?:location)?|address|location|token|secret|password|credential|authori[sz]|refresh)",
    re.I,
)
_COORD = re.compile(r"(?<!\d)-?\d{1,3}\.\d{4,}\s*[,/]\s*-?\d{1,3}\.\d{4,}(?!\d)")
_GOOGLE_ACCESS_TOKEN = re.compile(r"\bya29\.[A-Za-z0-9._-]+\b")
_GOOGLE_CLIENT_SECRET = re.compile(r"\bGOCSPX-[A-Za-z0-9_-]+\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_API_KEY = re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~-]+", re.I)
_OAUTH_PARAMETER = re.compile(
    r"([?&](?:access_token|refresh_token|id_token|token|client_secret|code|state)=)[^&#\s]*",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?<![?&])\b(?:access_token|refresh_token|id_token|client_secret|password|credential)\s*[:=]\s*[^\s,;]+",
    re.I,
)


class MailContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextBuildResult:
    payload: dict[str, Any]
    canonical_json: str
    sha256: str
    manifest: tuple[InputDraft, ...]


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _h(x: Any) -> str:
    return hashlib.sha256(_j(x).encode()).hexdigest()


def _clip(s: str, n: int) -> tuple[str, bool]:
    b = s.encode()
    return (s, False) if len(b) <= n else (b[:n].decode("utf-8", "ignore"), True)


def _redact_text(value: str) -> str:
    value = _OAUTH_PARAMETER.sub(r"\1<redacted-secret>", value)
    value = _BEARER.sub("Bearer <redacted-secret>", value)
    value = _SECRET_ASSIGNMENT.sub("<redacted-secret>", value)
    for pattern in (_GOOGLE_ACCESS_TOKEN, _GOOGLE_CLIENT_SECRET, _JWT, _API_KEY):
        value = pattern.sub("<redacted-secret>", value)
    return _COORD.sub("<redacted-precise-location>", value)


def _safe_json_text(value: str) -> str:
    try:
        return _j(_safe(json.loads(value)))
    except MailContextError:
        raise
    except Exception as e:
        raise MailContextError("context_embedded_json_invalid") from e


def _safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {
            str(k): (
                _safe_json_text(v)
                if str(k).endswith("_json") and isinstance(v, str)
                else _safe(v)
            )
            for k, v in sorted(x.items())
            if not _BAD_KEY.search(str(k))
        }
    if isinstance(x, list):
        return [_safe(v) for v in x]
    if isinstance(x, str):
        return _redact_text(x)
    return x


def _loads(x: str) -> Any:
    try:
        return _safe(json.loads(x))
    except Exception as e:
        raise MailContextError("context_canonical_json_invalid") from e


def _flatten_health(
    value: Any, prefix: str = "", depth: int = 0
) -> list[tuple[str, Any]]:
    if depth > 4:
        return []
    if value is None or isinstance(value, (str, bool, int, float)):
        return [(prefix or "value", value)]
    if not isinstance(value, dict):
        return []
    out = []
    for key in sorted(value, key=str):
        part = (
            "*"
            if str(key).isdigit()
            else re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key)).strip("_")[:80] or "value"
        )
        out.extend(
            _flatten_health(
                value[key], f"{prefix}.{part}" if prefix else part, depth + 1
            )
        )
    return out


def _health_metric_allowed(metric_key: str) -> bool:
    """Keep the mail model on the reviewed health whitelist."""
    key = metric_key.casefold().replace(" ", "_").replace("-", "_")
    return any(
        token in key
        for token in (
            "heart_rate",
            "heartrate",
            "hrv",
            "heart_rate_variability",
            "spo2",
            "pulse_ox",
            "vo2_max",
            "vo2max",
            "max_vo2",
            "weight",
            "body_weight",
        )
    )


def _health_window_summary(
    rows: list[dict[str, Any]], start: date, end: date
) -> dict[str, Any] | None:
    if not rows:
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    material = []
    sources = []
    for row in rows:
        values = _loads(row["values_json"])
        material.append(
            {
                "id": row["id"],
                "local_date": row["local_date"],
                "source_revision_id": row["source_revision_id"],
                "values": values,
            }
        )
        sources.append(
            {
                "id": row["id"],
                "source_revision_id": row["source_revision_id"],
                "local_date": row["local_date"],
            }
        )
        if isinstance(values, dict):
            for key, value in _flatten_health(values):
                if value is not None and _health_metric_allowed(key):
                    groups.setdefault(f"health.{key}", []).append(
                        {"local_date": row["local_date"], "value": value}
                    )
    metrics = []
    for key, observations in sorted(groups.items()):
        observations = sorted(
            observations, key=lambda item: (item["local_date"], _j(item["value"]))
        )
        values = [item["value"] for item in observations]
        numeric = all(
            not isinstance(value, bool) and isinstance(value, (int, float))
            for value in values
        )
        metric: dict[str, Any] = {
            "metric_key": key,
            "value_kind": "numeric" if numeric else "categorical",
            "observation_count": len(values),
            "coverage_days": len({item["local_date"] for item in observations}),
            "latest": {
                "local_date": observations[-1]["local_date"],
                "value": observations[-1]["value"],
            },
        }
        if numeric:
            numbers = [float(value) for value in values]
            average = sum(numbers) / len(numbers)
            if len(numbers) < 4:
                trend = "insufficient"
            else:
                middle = len(numbers) // 2
                earlier = sum(numbers[:middle]) / middle
                later = sum(numbers[-middle:]) / middle
                tolerance = max(abs(average) * 0.02, 1e-9)
                trend = (
                    "increasing"
                    if later - earlier > tolerance
                    else "decreasing"
                    if earlier - later > tolerance
                    else "stable"
                )
            metric.update(
                {
                    "average": round(average, 6),
                    "minimum": round(min(numbers), 6),
                    "maximum": round(max(numbers), 6),
                    "trend": trend,
                }
            )
        else:
            counts: dict[str, int] = {}
            originals: dict[str, Any] = {}
            for value in values:
                token = _j(value)
                counts[token] = counts.get(token, 0) + 1
                originals[token] = value
            metric["value_counts"] = [
                {"value": originals[token], "count": count}
                for token, count in sorted(
                    counts.items(), key=lambda item: (-item[1], item[0])
                )[:5]
            ]
        metrics.append(metric)
    return {
        "window": {"start": str(start), "end": str(end)},
        "completed_days": len({row["local_date"] for row in rows}),
        "source_count": len(rows),
        "sources": sources,
        "aggregate_sha256": _h(material),
        "metrics": metrics,
    }


class MailContextBuilder:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        schema_version: str = "1",
        policy_version: str = "mail-context-v1",
        shared_harness_version: str = "unknown",
        mail_harness_version: str = "unknown",
    ):
        self.connection = connection
        self.schema_version = schema_version
        self.policy_version = policy_version
        self.shared_harness_version = shared_harness_version
        self.mail_harness_version = mail_harness_version
        try:
            self.validator = Draft202012Validator(
                json.loads(
                    resource_bytes("harness/schemas/mail_agent_input.schema.json")
                ),
                format_checker=FormatChecker(),
            )
        except Exception as e:
            raise MailContextError("mail_input_schema_unavailable") from e

    def build(
        self,
        *,
        run_id: int,
        subject_id: int,
        trigger_message_id: int,
        as_of_local_date: str,
        requested_start_local_date: str | None = None,
        extension_reason: str | None = None,
    ) -> ContextBuildResult:
        try:
            asof = date.fromisoformat(as_of_local_date)
            requested = (
                date.fromisoformat(requested_start_local_date)
                if requested_start_local_date
                else None
            )
        except Exception as e:
            raise MailContextError("context_date_invalid") from e
        if requested and requested > asof:
            raise MailContextError("context_date_future_invalid")
        if requested and (
            extension_reason not in _EXTENSION_REASONS
            or (asof - requested).days + 1 > MAX_EXTENSION_DAYS
        ):
            raise MailContextError("context_date_extension_invalid")
        if self.connection.in_transaction:
            raise MailContextError("context_caller_transaction_active")
        old = self.connection.row_factory
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA query_only=ON")
            self.connection.execute("BEGIN")
            out = self._build(
                run_id,
                subject_id,
                trigger_message_id,
                asof,
                requested,
                extension_reason,
            )
            self.connection.execute("COMMIT")
            return out
        except MailContextError:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        except Exception as e:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise MailContextError("context_read_failed") from e
        finally:
            self.connection.row_factory = old
            self.connection.execute("PRAGMA query_only=OFF")

    def _build(
        self,
        run_id: int,
        sid: int,
        trigger_id: int,
        asof: date,
        requested: date | None,
        reason: str | None,
    ) -> ContextBuildResult:
        run = self.connection.execute(
            "SELECT id,run_key,invocation_id,request_kind,status FROM mail_agent_runs WHERE id=? AND subject_id=? AND request_kind='process' AND status IN ('started','deferred')",
            (run_id, sid),
        ).fetchone()
        if not run:
            raise MailContextError("context_run_not_buildable")
        trigger = self.connection.execute(
            "SELECT m.*,t.provider_thread_id FROM v_current_mail_messages m JOIN v_current_mail_threads t ON t.id=m.mail_thread_id JOIN source_revisions r ON r.id=m.source_revision_id AND r.is_current=1 AND r.provider='gmail' AND r.resource_kind='message_json' AND r.provider_object_id=m.provider_message_id WHERE m.id=? AND t.subject_id=? AND m.actor_role='user' AND m.direction='inbound' AND m.processing_state='queued'",
            (trigger_id, sid),
        ).fetchone()
        if (
            not trigger
            or not isinstance(trigger["body_text"], str)
            or not trigger["body_text"].strip()
        ):
            raise MailContextError("context_trigger_not_canonical_or_eligible")
        text, cut = _clip(trigger["body_text"], MAX_TRIGGER_BYTES)
        if cut:
            raise MailContextError("context_trigger_limit_exceeded")
        tid = trigger["mail_thread_id"]
        omissions: list[dict[str, Any]] = []
        # Inner DESC gets newest; outer ASC restores chronological context, with id as a stable tie breaker.
        rows = list(
            self.connection.execute(
                "SELECT * FROM (SELECT m.* FROM v_current_mail_messages m JOIN source_revisions r ON r.id=m.source_revision_id AND r.is_current=1 AND r.provider='gmail' AND r.resource_kind='message_json' AND r.provider_object_id=m.provider_message_id WHERE m.mail_thread_id=? ORDER BY COALESCE(m.received_at_utc,m.sent_at_utc) DESC,m.id DESC LIMIT ?) ORDER BY COALESCE(received_at_utc,sent_at_utc),id",
                (tid, MAX_THREAD_MESSAGES),
            )
        )
        total = self.connection.execute(
            "SELECT count(*) FROM v_current_mail_messages WHERE mail_thread_id=?",
            (tid,),
        ).fetchone()[0]
        if total > len(rows):
            omissions.append(
                {
                    "kind": "thread_messages_omitted",
                    "count": total - len(rows),
                    "selection": "oldest_first_removed",
                }
            )
        thread = []
        used = 0
        # Allocate bytes from newest to oldest, then restore chronological order.
        for r in reversed(rows):
            raw = r["body_text"] or ""
            avail = max(0, MAX_THREAD_BYTES - used)
            body, c = _clip(raw, avail)
            used += len(body.encode())
            if c:
                omissions.append(
                    {
                        "kind": "thread_body_truncated",
                        "entity_id": r["id"],
                        "omitted_bytes": len(raw.encode()) - len(body.encode()),
                        "selection": "oldest_body_first",
                    }
                )
            if r["actor_role"] == "user" and r["direction"] == "inbound":
                origin = "user_asserted"
            elif r["actor_role"] == "trainlab" or r["direction"] == "outbound":
                origin = "prior_model_output"
            else:
                omissions.append(
                    {"kind": "thread_message_untrusted_excluded", "entity_id": r["id"]}
                )
                continue
            thread.append(
                _safe(
                    {
                        "id": r["id"],
                        "provider_message_id": r["provider_message_id"],
                        "timestamp_utc": r["received_at_utc"] or r["sent_at_utc"],
                        "subject": r["subject"],
                        "body_text": body,
                        "body_sha256": r["body_sha256"],
                        "actor_role": r["actor_role"],
                        "direction": r["direction"],
                        "source_revision_id": r["source_revision_id"],
                        "value_origin": origin,
                        "content_instruction_trust": "untrusted_content",
                    }
                )
            )
        thread.reverse()
        # Keep the health baseline and activity evidence on their independent
        # bounded windows.  The mail contract exposes the latest 28 completed
        # health days, while activity summaries are limited to the latest 7
        # completed days by default.  An explicit user-requested start date is
        # an intentional extension and applies to both views.
        health_start = requested or asof - timedelta(days=MAX_COMPLETED_DAYS)
        activity_start = requested or asof - timedelta(days=7)
        # Cross-entity quality/artifact queries use the wider of the two
        # windows so an issue is not hidden merely because it belongs to a
        # different bounded source.
        start = min(health_start, activity_start)
        # Mail context follows the same health allowlist as the production
        # analysis boundary.  Legacy rows for steps, calories, hydration or
        # other broad Garmin summaries stay in SQLite but are not exposed to
        # the model.
        health_source_rows = [
            dict(r)
            for r in self.connection.execute(
                "SELECT d.* FROM v_current_daily_health d JOIN source_revisions r ON r.id=d.source_revision_id AND r.is_current=1 AND r.provider='garmin' AND r.resource_kind IN ('heart_rates','rhr','hrv','spo2') AND r.provider_object_id=d.local_date WHERE d.subject_id=? AND d.local_date BETWEEN ? AND ? AND d.local_date<? ORDER BY d.local_date,d.id",
                (sid, str(health_start), str(asof), str(asof)),
            )
        ]
        health_summary = _health_window_summary(
            health_source_rows, health_start, asof - timedelta(days=1)
        )
        health = [] if health_summary is None else [health_summary]
        if not requested:
            n = self.connection.execute(
                "SELECT count(DISTINCT local_date) FROM v_current_daily_health WHERE subject_id=? AND local_date<?",
                (sid, str(health_start)),
            ).fetchone()[0]
            if n:
                omissions.append(
                    {
                        "kind": "completed_days_omitted",
                        "count": n,
                        "before_local_date": str(health_start),
                    }
                )
        acts = [
            _safe(dict(r))
            for r in self.connection.execute(
                "SELECT a.id,a.provider_activity_id,a.name,a.sport,a.sub_sport,a.start_time_utc,a.end_time_utc,a.local_date,a.elapsed_seconds,a.timer_seconds,a.distance_m,a.primary_revision_id,a.provider_state FROM v_current_activities a JOIN source_revisions r ON r.id=a.primary_revision_id AND r.is_current=1 AND r.provider='garmin' AND r.resource_kind='activity_summary' AND r.provider_object_id=a.provider_activity_id WHERE a.subject_id=? AND a.provider_state IN ('active','suspected_missing') AND a.local_date BETWEEN ? AND ? AND a.local_date<? AND EXISTS(SELECT 1 FROM activity_source_revisions ar WHERE ar.activity_id=a.id AND ar.source_revision_id=a.primary_revision_id AND ar.source_role='summary_json' AND ar.is_active=1) ORDER BY a.local_date,a.start_time_utc,a.id",
                (sid, str(activity_start), str(asof), str(asof)),
            )
        ]
        facts = []
        for r in self.connection.execute(
            "SELECT f.* FROM v_active_user_facts f JOIN conversation_events e ON e.id=f.source_event_id AND e.subject_id=f.subject_id WHERE f.subject_id=? AND f.scope IN ('temporary','long_term') AND f.superseded_by_fact_id IS NULL AND (f.effective_from_utc IS NULL OR f.effective_from_utc<=?) AND (f.expires_at_utc IS NULL OR f.expires_at_utc>?) ORDER BY f.fact_key,f.id LIMIT ?",
            (sid, f"{asof}T23:59:59Z", f"{asof}T00:00:00Z", MAX_FACTS + 1),
        ):
            facts.append(
                _safe(
                    {
                        "id": r["id"],
                        "fact_key": r["fact_key"],
                        "value": _loads(r["fact_value_json"]),
                        "scope": r["scope"],
                        "effective_from_utc": r["effective_from_utc"],
                        "expires_at_utc": r["expires_at_utc"],
                        "confidence": r["confidence"],
                    }
                )
            )
        if len(facts) > MAX_FACTS:
            raise MailContextError("context_active_facts_limit")
        plans = [
            _safe(dict(r))
            for r in self.connection.execute(
                "SELECT p.id,p.subject_id,p.analysis_artifact_id,p.plan_start_local_date,p.plan_end_local_date,p.timezone,p.status,p.objective_json,p.constraints_json,p.created_at_utc,a.revision_no AS artifact_revision_no FROM v_current_training_plans p JOIN v_current_analysis_artifacts a ON a.id=p.analysis_artifact_id JOIN analysis_runs ar ON ar.id=a.generated_by_run_id AND ar.subject_id=p.subject_id AND ar.status='succeeded' WHERE p.subject_id=? AND p.status='active' AND p.plan_start_local_date<=? AND p.plan_end_local_date>=? ORDER BY p.plan_start_local_date DESC,p.id DESC",
                (sid, str(asof), str(asof)),
            )
        ]
        if len(plans) > 1:
            raise MailContextError("context_current_plan_ambiguous")
        if plans:
            plans[0]["items"] = [
                _safe(dict(x))
                for x in self.connection.execute(
                    "SELECT id,training_plan_id,item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json FROM v_training_plan_items WHERE training_plan_id=? ORDER BY item_index,id",
                    (plans[0]["id"],),
                )
            ]
        artifacts = [
            _safe(dict(r))
            for r in self.connection.execute(
                "SELECT a.* FROM v_current_analysis_artifacts a JOIN analysis_runs ar ON ar.id=a.generated_by_run_id AND ar.subject_id=a.subject_id AND ar.status='succeeded' WHERE a.subject_id=? AND a.is_current=1 AND a.period_end_local_date>=? AND a.period_start_local_date<=? AND a.artifact_kind IN ('daily_summary','daily_training_advice','weekly_summary','weekly_training_plan') ORDER BY a.period_end_local_date DESC,a.created_at_utc DESC,a.id DESC LIMIT ?",
                (sid, str(start), str(asof), MAX_ARTIFACTS),
            )
        ][::-1]
        excluded_artifacts = self.connection.execute(
            "SELECT count(*) FROM v_current_analysis_artifacts a WHERE a.subject_id=? AND (a.period_end_local_date<? OR a.period_start_local_date>?)",
            (sid, str(start), str(asof)),
        ).fetchone()[0]
        if excluded_artifacts:
            omissions.append(
                {
                    "kind": "unrelated_artifacts_excluded",
                    "count": excluded_artifacts,
                    "window_start": str(start),
                    "window_end": str(asof),
                }
            )
        prior = [
            _safe(dict(r))
            for r in self.connection.execute(
                "SELECT h.* FROM v_mail_response_history_context h WHERE h.subject_id=? AND h.mail_thread_id=? AND EXISTS(SELECT 1 FROM mail_agent_runs r WHERE r.id=h.generated_by_mail_agent_run_id AND r.subject_id=h.subject_id) ORDER BY h.created_at_utc DESC,h.id DESC LIMIT ?",
                (sid, tid, MAX_PRIOR_RESPONSES),
            )
        ][::-1]
        events = [
            _safe(dict(r))
            for r in self.connection.execute(
                "SELECT e.* FROM v_conversation_context e WHERE e.subject_id=? AND (e.mail_message_id IN (SELECT id FROM mail_messages WHERE mail_thread_id=?) OR e.analysis_artifact_id IN (SELECT id FROM v_current_analysis_artifacts WHERE subject_id=?)) ORDER BY e.occurred_at_utc,e.id LIMIT ?",
                (sid, tid, sid, MAX_EVENTS + 1),
            )
        ]
        if len(events) > MAX_EVENTS:
            dropped = events[:-MAX_EVENTS]
            events = events[-MAX_EVENTS:]
            omissions.append(
                {
                    "kind": "conversation_events_omitted",
                    "count": len(dropped),
                    "selection": "oldest_first",
                }
            )
        # Never join polymorphic quality IDs by number alone: entity type and
        # ownership are both part of the stable read boundary.
        quality_sql = """SELECT q.* FROM v_open_data_quality_issues q WHERE q.status IN ('open','acknowledged') AND
          (q.entity_type='mail_message' AND EXISTS(SELECT 1 FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id WHERE m.id=q.entity_id AND t.subject_id=? AND m.mail_thread_id=? AND (q.source_revision_id IS NULL OR q.source_revision_id=m.source_revision_id))) OR
          (q.entity_type='daily_health' AND EXISTS(SELECT 1 FROM daily_health d WHERE d.id=q.entity_id AND d.subject_id=? AND d.local_date BETWEEN ? AND ? AND (q.source_revision_id IS NULL OR q.source_revision_id=d.source_revision_id))) OR
          (q.entity_type='activity' AND EXISTS(SELECT 1 FROM activities a WHERE a.id=q.entity_id AND a.subject_id=? AND a.local_date BETWEEN ? AND ? AND (q.source_revision_id IS NULL OR q.source_revision_id=a.primary_revision_id))) OR
          (q.entity_type='user_fact' AND EXISTS(SELECT 1 FROM user_facts f WHERE f.id=q.entity_id AND f.subject_id=?)) OR
          (q.entity_type='analysis_artifact' AND EXISTS(SELECT 1 FROM analysis_artifacts a WHERE a.id=q.entity_id AND a.subject_id=? AND a.is_current=1)) OR
          (q.entity_type='training_plan' AND EXISTS(SELECT 1 FROM training_plans p WHERE p.id=q.entity_id AND p.subject_id=? AND p.status='active'))
          ORDER BY q.severity DESC,q.entity_type,q.entity_id,q.id LIMIT ?"""
        quality = [
            _safe(dict(r))
            for r in self.connection.execute(
                quality_sql,
                (
                    sid,
                    tid,
                    sid,
                    str(start),
                    str(asof),
                    sid,
                    str(start),
                    str(asof),
                    sid,
                    sid,
                    sid,
                    MAX_QUALITY + 1,
                ),
            )
        ]
        if len(quality) > MAX_QUALITY:
            dropped = quality[MAX_QUALITY:]
            quality = quality[:MAX_QUALITY]
            omissions.append(
                {
                    "kind": "quality_issues_omitted",
                    "count": len(dropped),
                    "selection": "lowest_priority_last",
                }
            )
        entries: list[dict[str, Any]] = []
        dbmanifest: list[InputDraft] = []

        def add(
            role: str,
            typ: str,
            item: dict[str, Any],
            trust: str,
            revision: int | None,
            *,
            entity_revision: Any = None,
            instruction: str | None = None,
        ):
            entity_revision = item.get(
                "revision_no", revision if entity_revision is None else entity_revision
            )
            if entity_revision is None:
                raise MailContextError("context_source_revision_required")
            if trust not in {
                "provider_fact",
                "user_asserted",
                "derived_statistic",
                "prior_model_output",
            }:
                raise MailContextError("context_unpersistable_trust")
            digest = _h(item)
            dbmanifest.append(
                InputDraft(role, typ, digest, trust, item.get("id"), revision)
            )
            entries.append(
                {
                    "ordinal": len(entries),
                    "input_role": role,
                    "source_entity_type": typ,
                    "source_entity_id": item.get("id"),
                    "source_revision_id": revision,
                    "entity_revision": entity_revision,
                    "value_origin": trust,
                    "trust_class": trust,
                    "content_instruction_trust": instruction or "untrusted_content",
                    "input_sha256": digest,
                    "context_schema_version": self.schema_version,
                    "policy_version": self.policy_version,
                    "shared_harness_version": self.shared_harness_version,
                    "mail_harness_version": self.mail_harness_version,
                }
            )

        trig = {
            "id": trigger_id,
            "provider_message_id": trigger["provider_message_id"],
            "thread_id": tid,
            "provider_thread_id": trigger["provider_thread_id"],
            "timestamp_utc": trigger["received_at_utc"] or trigger["sent_at_utc"],
            "subject": trigger["subject"],
            "latest_authored_text": _safe(text),
            "body_sha256": trigger["body_sha256"],
            "source_revision_id": trigger["source_revision_id"],
            "value_origin": "user_asserted",
            "content_instruction_trust": "untrusted_content",
        }
        add(
            "trigger_message",
            "mail_message",
            trig,
            "user_asserted",
            trigger["source_revision_id"],
            instruction="untrusted_content",
        )
        for x in thread:
            add(
                "thread_message",
                "mail_message",
                x,
                x["value_origin"],
                x["source_revision_id"],
                instruction=x["content_instruction_trust"],
            )
        # User facts have no Foundation source_revision column; their immutable
        # entity id is the revision identity, rather than a forged mail revision.
        for x in facts:
            add(
                "active_user_fact",
                "user_fact",
                x,
                "user_asserted",
                None,
                entity_revision=x["id"],
            )
        if health:
            digest = _h(health[0])
            for source in health[0]["sources"]:
                dbmanifest.append(
                    InputDraft(
                        "health_fact",
                        "daily_health",
                        digest,
                        "provider_fact",
                        source["id"],
                        source["source_revision_id"],
                    )
                )
                entries.append(
                    {
                        "ordinal": len(entries),
                        "input_role": "health_fact",
                        "source_entity_type": "daily_health",
                        "source_entity_id": source["id"],
                        "source_revision_id": source["source_revision_id"],
                        "entity_revision": source["source_revision_id"],
                        "value_origin": "provider_fact",
                        "trust_class": "provider_fact",
                        "content_instruction_trust": "untrusted_content",
                        "input_sha256": digest,
                        "context_schema_version": self.schema_version,
                        "policy_version": self.policy_version,
                        "shared_harness_version": self.shared_harness_version,
                        "mail_harness_version": self.mail_harness_version,
                    }
                )
        for x in acts:
            add(
                "activity_fact",
                "activity",
                x,
                "provider_fact",
                x["primary_revision_id"],
            )
        # Analysis artifact ids are entities, not source_revisions; never forge them into that FK column.
        for x in artifacts:
            add(
                "analysis_artifact",
                "analysis_artifact",
                x,
                "prior_model_output",
                None,
                entity_revision=x["revision_no"],
            )
        for x in prior:
            add(
                "prior_mail_response",
                "mail_response_artifact",
                x,
                "prior_model_output",
                None,
                entity_revision=x["revision_no"],
            )
        if plans:
            add(
                "current_plan",
                "training_plan",
                plans[0],
                "prior_model_output",
                None,
                entity_revision=plans[0]["artifact_revision_no"],
            )
        for x in events:
            add(
                "conversation_event",
                "conversation_event",
                x,
                "derived_statistic",
                None,
                entity_revision=x["id"],
                instruction="untrusted_content",
            )
        for x in quality:
            add(
                "quality_state",
                "data_quality_issue",
                x,
                "derived_statistic",
                x.get("source_revision_id"),
                entity_revision=x["id"],
            )
        payload = {
            "schema_version": self.schema_version,
            "run": _safe(
                {
                    "id": run["id"],
                    "run_key": run["run_key"],
                    "invocation_id": run["invocation_id"],
                    "request_kind": run["request_kind"],
                }
            ),
            "trigger_message": trig,
            "thread_context": thread,
            "conversation_events": events,
            "active_user_facts": facts,
            "current_health_context": health,
            "current_activity_context": acts,
            "current_training_plan": plans[0] if plans else None,
            "relevant_analysis_artifacts": artifacts,
            "prior_mail_responses": prior,
            "data_quality": quality,
            "policies": _safe(
                {
                    "version": self.policy_version,
                    "timezone": "Asia/Hong_Kong",
                    "sensitive_field_policy": "recursive_minimization",
                }
            ),
            "input_manifest": entries,
            "context_limits": {
                "trigger_bytes": len(trig["latest_authored_text"].encode()),
                "thread_body_bytes": used,
                "thread_messages": len(thread),
                "completed_days": 0 if not health else health[0]["completed_days"],
                "prior_responses": len(prior),
                "related_artifacts": len(artifacts),
                "max_bytes": MAX_CONTEXT_BYTES,
                "date_extension_reason": reason,
                "omissions": omissions,
            },
        }

        def remove_manifest(role: str, entity: int) -> None:
            entries[:] = [
                m
                for m in entries
                if not (m["input_role"] == role and m["source_entity_id"] == entity)
            ]
            dbmanifest[:] = [
                m
                for m in dbmanifest
                if not (m.input_role == role and m.source_entity_id == entity)
            ]

        def refresh_manifest(role: str, entity: int, value: dict[str, Any]) -> None:
            digest = _h(value)
            for manifest_entry in entries:
                if (
                    manifest_entry["input_role"] == role
                    and manifest_entry["source_entity_id"] == entity
                ):
                    manifest_entry["input_sha256"] = digest
            for index, db_entry in enumerate(dbmanifest):
                if db_entry.input_role == role and db_entry.source_entity_id == entity:
                    dbmanifest[index] = InputDraft(
                        db_entry.input_role,
                        db_entry.source_entity_type,
                        digest,
                        db_entry.trust_class,
                        db_entry.source_entity_id,
                        db_entry.source_revision_id,
                    )

        # Four deterministic global-limit stages: old thread redundancy,
        # old activity summaries, prior model artifacts/responses, then only
        # fail closed when the protected core cannot fit.
        while len(_j(payload).encode()) > MAX_CONTEXT_BYTES:
            candidate = next(
                (x for x in payload["thread_context"] if x["id"] != trigger_id), None
            )
            if candidate is None:
                break
            payload["thread_context"].remove(candidate)
            remove_manifest("thread_message", candidate["id"])
            omissions.append(
                {
                    "kind": "thread_message_omitted_total_limit",
                    "entity_id": candidate["id"],
                    "selection": "oldest_nontrigger_first",
                }
            )
        for index, x in enumerate(payload["current_activity_context"]):
            if len(_j(payload).encode()) <= MAX_CONTEXT_BYTES:
                break
            compact = {
                key: x.get(key)
                for key in (
                    "id",
                    "provider_activity_id",
                    "sport",
                    "local_date",
                    "start_time_utc",
                    "elapsed_seconds",
                    "distance_m",
                    "primary_revision_id",
                )
            }
            if x != compact:
                payload["current_activity_context"][index] = compact
                refresh_manifest("activity_fact", x["id"], compact)
                omissions.append(
                    {
                        "kind": "activity_detail_compacted_total_limit",
                        "entity_id": x["id"],
                        "omitted_fields": sorted(set(x) - set(compact)),
                    }
                )
        while (
            len(_j(payload).encode()) > MAX_CONTEXT_BYTES
            and payload["relevant_analysis_artifacts"]
        ):
            x = payload["relevant_analysis_artifacts"].pop(0)
            omissions.append(
                {"kind": "artifact_omitted_total_limit", "entity_id": x["id"]}
            )
            remove_manifest("analysis_artifact", x["id"])
        while (
            len(_j(payload).encode()) > MAX_CONTEXT_BYTES
            and payload["prior_mail_responses"]
        ):
            x = payload["prior_mail_responses"].pop(0)
            omissions.append(
                {"kind": "prior_response_omitted_total_limit", "entity_id": x["id"]}
            )
            remove_manifest("prior_mail_response", x["id"])
        for ordinal, item in enumerate(entries):
            item["ordinal"] = ordinal
        payload["context_limits"]["thread_messages"] = len(payload["thread_context"])
        payload["context_limits"]["thread_body_bytes"] = sum(
            len(x["body_text"].encode()) for x in payload["thread_context"]
        )
        payload["context_limits"]["prior_responses"] = len(
            payload["prior_mail_responses"]
        )
        payload["context_limits"]["related_artifacts"] = len(
            payload["relevant_analysis_artifacts"]
        )
        canonical = _j(payload)
        if len(canonical.encode()) > MAX_CONTEXT_BYTES:
            raise MailContextError("context_uncuttable_core_limit_exceeded")
        self._validate_nested(payload)
        errors = sorted(self.validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            raise MailContextError("mail_input_schema_invalid")
        self._validate_manifest(payload)
        self._validate_context_limits(payload)
        self._validate_training_plan(payload["current_training_plan"])
        return ContextBuildResult(
            payload,
            canonical,
            hashlib.sha256(canonical.encode()).hexdigest(),
            tuple(dbmanifest),
        )

    def _validate_manifest(self, payload: dict[str, Any]) -> None:
        """Validate the semantic lineage that JSON Schema cannot express.

        The manifest's position and fragment digest must correspond exactly to
        the bounded payload supplied to the model; merely matching its shape is
        not sufficient for response-input lineage.
        """
        manifest = payload["input_manifest"]
        if [entry["ordinal"] for entry in manifest] != list(range(len(manifest))):
            raise MailContextError("mail_input_manifest_ordinal_invalid")
        specs = (
            (
                "trigger_message",
                "mail_message",
                payload["trigger_message"],
                "user_asserted",
                lambda x: x["source_revision_id"],
                lambda x: x["source_revision_id"],
            ),
            *[
                (
                    "thread_message",
                    "mail_message",
                    x,
                    x["value_origin"],
                    lambda x: x["source_revision_id"],
                    lambda x: x["source_revision_id"],
                )
                for x in payload["thread_context"]
            ],
            *[
                (
                    "active_user_fact",
                    "user_fact",
                    x,
                    "user_asserted",
                    lambda x: None,
                    lambda x: x["id"],
                )
                for x in payload["active_user_facts"]
            ],
            *[
                (
                    "activity_fact",
                    "activity",
                    x,
                    "provider_fact",
                    lambda x: x["primary_revision_id"],
                    lambda x: x["primary_revision_id"],
                )
                for x in payload["current_activity_context"]
            ],
            *[
                (
                    "analysis_artifact",
                    "analysis_artifact",
                    x,
                    "prior_model_output",
                    lambda x: None,
                    lambda x: x["revision_no"],
                )
                for x in payload["relevant_analysis_artifacts"]
            ],
            *[
                (
                    "prior_mail_response",
                    "mail_response_artifact",
                    x,
                    "prior_model_output",
                    lambda x: None,
                    lambda x: x["revision_no"],
                )
                for x in payload["prior_mail_responses"]
            ],
            *(
                []
                if payload["current_training_plan"] is None
                else [
                    (
                        "current_plan",
                        "training_plan",
                        payload["current_training_plan"],
                        "prior_model_output",
                        lambda x: None,
                        lambda x: x["artifact_revision_no"],
                    )
                ]
            ),
            *[
                (
                    "conversation_event",
                    "conversation_event",
                    x,
                    "derived_statistic",
                    lambda x: None,
                    lambda x: x["id"],
                )
                for x in payload["conversation_events"]
            ],
            *[
                (
                    "quality_state",
                    "data_quality_issue",
                    x,
                    "derived_statistic",
                    lambda x: x["source_revision_id"],
                    lambda x: x["id"],
                )
                for x in payload["data_quality"]
            ],
        )
        expected = {
            (role, item["id"]): (
                typ,
                item,
                trust,
                source_revision(item),
                entity_revision(item),
            )
            for role, typ, item, trust, source_revision, entity_revision in specs
        }
        health_source_count = 0
        for summary in payload["current_health_context"]:
            for source in summary["sources"]:
                health_source_count += 1
                expected[("health_fact", source["id"])] = (
                    "daily_health",
                    summary,
                    "provider_fact",
                    source["source_revision_id"],
                    source["source_revision_id"],
                )
        actual = {
            (entry["input_role"], entry["source_entity_id"]): entry
            for entry in manifest
        }
        if (
            len(expected) != len(specs) + health_source_count
            or len(actual) != len(manifest)
            or set(actual) != set(expected)
        ):
            raise MailContextError("mail_input_manifest_bijection_invalid")
        for key, (
            typ,
            item,
            trust,
            source_revision,
            entity_revision,
        ) in expected.items():
            entry = actual[key]
            if (
                entry["source_entity_type"],
                entry["value_origin"],
                entry["trust_class"],
                entry["source_revision_id"],
                entry["entity_revision"],
                entry["input_sha256"],
            ) != (typ, trust, trust, source_revision, entity_revision, _h(item)):
                raise MailContextError("mail_input_manifest_fragment_invalid")
            if (
                entry["context_schema_version"],
                entry["policy_version"],
                entry["shared_harness_version"],
                entry["mail_harness_version"],
            ) != (
                self.schema_version,
                payload["policies"]["version"],
                self.shared_harness_version,
                self.mail_harness_version,
            ):
                raise MailContextError("mail_input_manifest_version_invalid")

    @staticmethod
    def _validate_context_limits(payload: dict[str, Any]) -> None:
        limits = payload["context_limits"]
        exact = {
            "trigger_bytes": len(
                payload["trigger_message"]["latest_authored_text"].encode()
            ),
            "thread_body_bytes": sum(
                len(item["body_text"].encode()) for item in payload["thread_context"]
            ),
            "thread_messages": len(payload["thread_context"]),
            "completed_days": 0
            if not payload["current_health_context"]
            else payload["current_health_context"][0]["completed_days"],
            "prior_responses": len(payload["prior_mail_responses"]),
            "related_artifacts": len(payload["relevant_analysis_artifacts"]),
        }
        if any(limits[key] != value for key, value in exact.items()):
            raise MailContextError("mail_input_context_limits_invalid")
        collections = {
            "thread_context": {item["id"] for item in payload["thread_context"]},
            "current_activity_context": {
                item["id"] for item in payload["current_activity_context"]
            },
            "relevant_analysis_artifacts": {
                item["id"] for item in payload["relevant_analysis_artifacts"]
            },
            "prior_mail_responses": {
                item["id"] for item in payload["prior_mail_responses"]
            },
        }
        for omission in limits["omissions"]:
            kind = omission["kind"]
            if "count" in omission and omission["count"] < 1:
                raise MailContextError("mail_input_omission_invalid")
            if kind == "thread_body_truncated" and (
                omission["entity_id"] not in collections["thread_context"]
                or omission["omitted_bytes"] < 1
            ):
                raise MailContextError("mail_input_omission_invalid")
            if (
                kind == "thread_message_untrusted_excluded"
                and omission["entity_id"] in collections["thread_context"]
            ):
                raise MailContextError("mail_input_omission_invalid")
            if (
                kind == "thread_message_omitted_total_limit"
                and omission["entity_id"] in collections["thread_context"]
            ):
                raise MailContextError("mail_input_omission_invalid")
            if kind == "activity_detail_compacted_total_limit" and (
                omission["entity_id"] not in collections["current_activity_context"]
                or any(
                    field
                    in next(
                        item
                        for item in payload["current_activity_context"]
                        if item["id"] == omission["entity_id"]
                    )
                    for field in omission["omitted_fields"]
                )
            ):
                raise MailContextError("mail_input_omission_invalid")
            if (
                kind == "artifact_omitted_total_limit"
                and omission["entity_id"] in collections["relevant_analysis_artifacts"]
            ):
                raise MailContextError("mail_input_omission_invalid")
            if (
                kind == "prior_response_omitted_total_limit"
                and omission["entity_id"] in collections["prior_mail_responses"]
            ):
                raise MailContextError("mail_input_omission_invalid")

    @staticmethod
    def _validate_training_plan(plan: dict[str, Any] | None) -> None:
        if plan is None:
            return
        if plan["status"] != "active":
            raise MailContextError("mail_input_plan_state_invalid")
        start = date.fromisoformat(plan["plan_start_local_date"])
        end = date.fromisoformat(plan["plan_end_local_date"])
        if (end - start).days != 6:
            raise MailContextError("mail_input_plan_window_invalid")
        items = plan["items"]
        if len(items) != 7 or [item["item_index"] for item in items] != list(range(7)):
            raise MailContextError("mail_input_plan_item_ordinal_invalid")
        dates = [date.fromisoformat(item["local_date"]) for item in items]
        if any(item["training_plan_id"] != plan["id"] for item in items) or set(
            dates
        ) != {start + timedelta(days=offset) for offset in range(7)}:
            raise MailContextError("mail_input_plan_item_invalid")

    @staticmethod
    def _validate_nested(payload: dict[str, Any]) -> None:
        """Closed record gate complementing JSON Schema for SQLite projections.

        Projection records are normalized before this point, so an unexpected
        column is a compatibility/security failure, never prompt data.
        """
        allowed = {
            "thread_context": {
                "id",
                "provider_message_id",
                "timestamp_utc",
                "subject",
                "body_text",
                "body_sha256",
                "actor_role",
                "direction",
                "source_revision_id",
                "value_origin",
                "content_instruction_trust",
            },
            "active_user_facts": {
                "id",
                "fact_key",
                "value",
                "scope",
                "effective_from_utc",
                "expires_at_utc",
                "confidence",
            },
            "current_health_context": {
                "window",
                "completed_days",
                "source_count",
                "sources",
                "aggregate_sha256",
                "metrics",
            },
            "current_activity_context": {
                "id",
                "provider_activity_id",
                "name",
                "sport",
                "sub_sport",
                "start_time_utc",
                "end_time_utc",
                "local_date",
                "elapsed_seconds",
                "timer_seconds",
                "distance_m",
                "primary_revision_id",
                "provider_state",
            },
            "relevant_analysis_artifacts": {
                "id",
                "subject_id",
                "artifact_kind",
                "period_start_local_date",
                "period_end_local_date",
                "revision_no",
                "generated_by_run_id",
                "schema_version",
                "structured_content_json",
                "user_visible_text",
                "content_sha256",
                "is_current",
                "supersedes_artifact_id",
                "created_at_utc",
            },
            "prior_mail_responses": {
                "id",
                "subject_id",
                "mail_thread_id",
                "in_reply_to_mail_message_id",
                "response_kind",
                "revision_no",
                "generated_by_mail_agent_run_id",
                "schema_version",
                "structured_content_json",
                "user_visible_text",
                "content_sha256",
                "is_current",
                "supersedes_mail_response_artifact_id",
                "created_at_utc",
                "trust_class",
            },
            "data_quality": {
                "id",
                "entity_type",
                "entity_id",
                "issue_code",
                "severity",
                "details_json",
                "status",
                "first_seen_at_utc",
                "last_seen_at_utc",
                "resolved_at_utc",
                "source_revision_id",
            },
            "conversation_events": {
                "id",
                "subject_id",
                "event_type",
                "actor_role",
                "occurred_at_utc",
                "mail_message_id",
                "analysis_artifact_id",
                "mail_response_artifact_id",
                "analysis_delivery_id",
                "mail_delivery_id",
                "related_run_key",
                "content_text",
                "structured_payload_json",
                "trust_level",
                "created_by",
            },
        }
        for field, names in allowed.items():
            for record in payload[field]:
                if not isinstance(record, dict) or set(record) - names:
                    raise MailContextError("mail_input_nested_schema_invalid")
        plan = payload["current_training_plan"]
        if plan is not None and (
            not isinstance(plan, dict)
            or not {"id", "analysis_artifact_id", "artifact_revision_no", "items"}
            <= set(plan)
        ):
            raise MailContextError("mail_input_nested_schema_invalid")
