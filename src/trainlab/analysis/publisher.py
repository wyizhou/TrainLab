"""A3-13 atomic persistence for accepted analysis results.

The publisher deliberately owns only the short SQLite transaction after A3-12
has accepted a result.  It neither completes ``analysis_runs`` nor creates a
delivery; the coordinator retains both of those responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import sqlite3
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .result_validation import ValidatedAnalysisResult


class AnalysisPublishError(RuntimeError):
    """A controlled publication failure; no partial publication is retained."""


_SG = ZoneInfo("Asia/Singapore")
_TRUST = frozenset({
    "provider_fact",
    "provider_derived",
    "provider_predicted",
    "user_asserted",
    "derived_statistic",
    "prior_model_output",
    "unknown",
})
_DAILY_KINDS = frozenset({"daily_summary", "daily_training_advice"})
_WEEKLY_KINDS = frozenset({"weekly_summary", "weekly_training_plan"})
_PLAN_ITEM_KINDS = frozenset({"running", "climbing", "strength", "rest"})
_FORBIDDEN_EVIDENCE_KEYS = frozenset({
    "access_token", "api_key", "authorization", "authorization_url",
    "client_credentials", "client_secret", "credential", "credentials",
    "oauth_token", "password", "provider_response", "raw_model_output",
    "raw_output", "refresh_token", "secret", "token",
})
_MAX_CONTEXT_BYTES = 1_000_000
_MAX_GENERATOR_METADATA_BYTES = 64_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _content_hash(structured: Any, text: str) -> str:
    return sha256(_canonical({"structured_content": structured, "user_visible_text": text}).encode("utf-8")).hexdigest()


def _utc_bounds(window: Mapping[str, Any]) -> tuple[str, str]:
    try:
        start = date.fromisoformat(str(window["start_local_date"]))
        end = date.fromisoformat(str(window["end_local_date"]))
    except (KeyError, TypeError, ValueError) as error:
        raise AnalysisPublishError("analysis_publish_input_window_invalid") from error
    if end < start:
        raise AnalysisPublishError("analysis_publish_input_window_invalid")
    start_utc = datetime.combine(start, time.min, _SG).astimezone(timezone.utc)
    end_utc = datetime.combine(end + timedelta(days=1), time.min, _SG).astimezone(timezone.utc)
    return (
        start_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        end_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def _integer_reference(value: Any) -> int | None:
    """Use the FK column only for actual Foundation numeric source revisions.

    A3-10 also has deterministic synthetic revisions (quality/policy rows).
    They are deliberately not pretended to be ``source_revisions`` records.
    Their immutable lineage remains represented by entity identity and hash.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


@dataclass(frozen=True)
class PublishReceipt:
    run_id: int
    artifact_ids: Mapping[str, int]
    revisions: Mapping[str, int]
    input_count: int
    training_plan_id: int | None = None
    superseded_plan_ids: tuple[int, ...] = ()
    content_same: bool | None = None


@dataclass(frozen=True)
class RunEvidence:
    """Accepted generation evidence persisted on ``analysis_runs``."""

    harness_version: str
    input_schema_version: str
    output_schema_version: str
    context_snapshot_json: Mapping[str, Any]
    context_snapshot_sha256: str
    generator_metadata_json: Mapping[str, Any]


class AnalysisPublisher:
    """Publish accepted daily or weekly revisions in one short transaction."""

    def __init__(self, connection: sqlite3.Connection, *, clock: Callable[[], str] = _now) -> None:
        self._connection = connection
        self._clock = clock

    def publish(
        self,
        *,
        run_id: int,
        accepted: ValidatedAnalysisResult | Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]],
        run_evidence: RunEvidence | Mapping[str, Any],
        regeneration_source: Mapping[str, Any] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> PublishReceipt:
        """Atomically publish one validated route and its full input manifest.

        ``failpoint`` is an intentionally test-only seam.  Raising at any named
        stage proves that the enclosing transaction leaves the old current
        revisions unchanged.
        """
        result = accepted.result if isinstance(accepted, ValidatedAnalysisResult) else accepted
        if not isinstance(result, Mapping):
            raise AnalysisPublishError("analysis_publish_result_invalid")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
            raise AnalysisPublishError("analysis_publish_run_invalid")
        self._connection.execute("PRAGMA foreign_keys=ON")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            receipt = self._publish_in_transaction(
                run_id, result, input_manifest, run_evidence, regeneration_source, failpoint
            )
            self._connection.execute("COMMIT")
            return receipt
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def publish_with_pending_delivery(
        self,
        *,
        run_id: int,
        accepted: ValidatedAnalysisResult | Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]],
        run_evidence: RunEvidence | Mapping[str, Any],
        regeneration_source: Mapping[str, Any],
        delivery_factory: Any,
        delivery_kind: str,
        failpoint: Callable[[str], None] | None = None,
    ) -> tuple[PublishReceipt, Any]:
        """Atomically publish regeneration and seed its exact pending delivery."""
        result = (
            accepted.result
            if isinstance(accepted, ValidatedAnalysisResult)
            else accepted
        )
        if not isinstance(result, Mapping):
            raise AnalysisPublishError("analysis_publish_result_invalid")
        self._connection.execute("PRAGMA foreign_keys=ON")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            receipt = self._publish_in_transaction(
                run_id,
                result,
                input_manifest,
                run_evidence,
                regeneration_source,
                failpoint,
            )
            create = getattr(
                delivery_factory, "create_pending_in_transaction", None
            )
            if not callable(create):
                raise AnalysisPublishError(
                    "analysis_publish_delivery_adapter_invalid"
                )
            pending = create(
                publish_receipt=receipt,
                delivery_kind=delivery_kind,
            )
            self._fire(failpoint, "after_pending_delivery")
            self._connection.execute("COMMIT")
            return receipt, pending
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _publish_in_transaction(
        self, run_id: int, result: Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]],
        run_evidence: RunEvidence | Mapping[str, Any],
        regeneration_source: Mapping[str, Any] | None,
        failpoint: Callable[[str], None] | None,
    ) -> PublishReceipt:
        run = self._connection.execute(
            "SELECT id,subject_id,run_key,status,analysis_kind,harness_version,"
            "input_schema_version,output_schema_version,context_snapshot_json,"
            "context_snapshot_sha256,generator_metadata_json "
            "FROM analysis_runs WHERE id=?", (run_id,)
        ).fetchone()
        if run is None or run["status"] != "started":
            raise AnalysisPublishError("analysis_publish_run_not_started")
        if result.get("status") != "accepted":
            raise AnalysisPublishError("analysis_publish_route_not_implemented")
        if result.get("run_key") != run["run_key"] or result.get("subject_id") != run["subject_id"]:
            raise AnalysisPublishError("analysis_publish_run_identity_mismatch")
        if result.get("mode") == "daily" and run["analysis_kind"] == "daily":
            return self._publish_daily(run, result, input_manifest, run_evidence, failpoint)
        if result.get("mode") == "weekly" and run["analysis_kind"] == "weekly":
            return self._publish_weekly(run, result, input_manifest, run_evidence, failpoint)
        if result.get("mode") == "revise_plan" and run["analysis_kind"] == "plan_revision":
            return self._publish_plan_revision(
                run, result, input_manifest, run_evidence, failpoint
            )
        if result.get("mode") == "regenerate" and run["analysis_kind"] == "regeneration":
            return self._publish_regeneration(run, result, input_manifest, run_evidence, regeneration_source, failpoint)
        raise AnalysisPublishError("analysis_publish_route_not_implemented")

    def _publish_regeneration(self, run: sqlite3.Row, result: Mapping[str, Any], input_manifest: Sequence[Mapping[str, Any]], run_evidence: RunEvidence | Mapping[str, Any], source: Mapping[str, Any] | None, failpoint: Callable[[str], None] | None) -> PublishReceipt:
        if (
            not isinstance(source, Mapping)
            or source.get("shape") not in {"daily", "weekly", "plan_revision"}
            or not isinstance(source.get("artifact_id"), int)
            or source.get("kind") not in _DAILY_KINDS | _WEEKLY_KINDS
            or not isinstance(source.get("start"), str)
            or not isinstance(source.get("end"), str)
        ):
            raise AnalysisPublishError("analysis_publish_regeneration_source_invalid")
        target_id, shape = source["artifact_id"], source["shape"]
        target = self._connection.execute(
            "SELECT a.subject_id,a.artifact_kind,a.period_start_local_date,"
            "a.period_end_local_date,a.content_sha256,a.is_current,"
            "source_run.analysis_kind AS source_run_kind "
            "FROM analysis_artifacts a "
            "JOIN analysis_runs source_run ON source_run.id=a.generated_by_run_id "
            "WHERE a.id=?",
            (target_id,),
        ).fetchone()
        expected_source_run_kind = (
            "daily" if shape == "daily"
            else "weekly" if shape == "weekly"
            else "plan_revision"
        )
        if (
            target is None
            or target["subject_id"] != run["subject_id"]
            or target["is_current"] != 1
            or target["artifact_kind"] != source["kind"]
            or target["period_start_local_date"] != source["start"]
            or target["period_end_local_date"] != source["end"]
            or target["source_run_kind"] != expected_source_run_kind
        ):
            raise AnalysisPublishError("analysis_publish_regeneration_source_invalid")
        if shape == "daily":
            receipt = self._publish_daily(run, result, input_manifest, run_evidence, failpoint)
        elif shape == "weekly":
            receipt = self._publish_weekly(run, result, input_manifest, run_evidence, failpoint)
        else:
            receipt = self._publish_regenerated_plan(run, result, input_manifest, run_evidence, failpoint)
        direct_successor_id = receipt.artifact_ids.get(str(source["kind"]))
        if not isinstance(direct_successor_id, int):
            raise AnalysisPublishError("analysis_publish_regeneration_source_invalid")
        self._connection.execute(
            "INSERT INTO analysis_artifact_relations("
            "from_artifact_id,to_artifact_id,relation_type,created_at_utc"
            ") VALUES(?,?,?,?)",
            (direct_successor_id, target_id, "derived_from", self._clock()),
        )
        successor = self._connection.execute(
            "SELECT content_sha256 FROM analysis_artifacts WHERE id=?",
            (direct_successor_id,),
        ).fetchone()
        if successor is None:
            raise AnalysisPublishError("analysis_publish_regeneration_source_invalid")
        return replace(
            receipt,
            content_same=successor["content_sha256"] == target["content_sha256"],
        )

    def _publish_regenerated_plan(self, run: sqlite3.Row, result: Mapping[str, Any], input_manifest: Sequence[Mapping[str, Any]], run_evidence: RunEvidence | Mapping[str, Any], failpoint: Callable[[str], None] | None) -> PublishReceipt:
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)) or len(artifacts) != 1 or not isinstance(artifacts[0], Mapping) or artifacts[0].get("artifact_kind") != "weekly_training_plan":
            raise AnalysisPublishError("analysis_publish_regeneration_plan_cardinality_invalid")
        artifact = artifacts[0]; plan = self._validate_weekly_plan(result.get("training_plan"), artifact)
        self._persist_run_evidence(run, run_evidence, input_manifest); self._fire(failpoint, "after_run_evidence")
        self._insert_inputs(int(run["id"]), input_manifest); self._fire(failpoint, "after_inputs")
        artifact_id, revision = self._insert_revision(int(run["subject_id"]), int(run["id"]), "weekly_training_plan", artifact)
        self._fire(failpoint, "after_artifact:weekly_training_plan")
        superseded = self._supersede_overlapping_plans(int(run["subject_id"]), plan["start"], plan["end"]); self._fire(failpoint, "after_plan_supersession")
        now = self._clock()
        cursor = self._connection.execute("INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(?,?,?,?,?,'active',?,?,?)", (int(run["subject_id"]), artifact_id, plan["start"].isoformat(), plan["end"].isoformat(), plan["timezone"], _canonical(plan["objective"]), _canonical(plan["constraints"]), now))
        plan_id = int(cursor.lastrowid); self._fire(failpoint, "after_plan")
        for item in plan["items"]:
            self._connection.execute("INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json) VALUES(?,?,?,?,?,?,?)", (plan_id, item["item_index"], item["local_date"], item["activity_kind"], _canonical(item["prescription"]), item["rationale_text"], _canonical(item["stop_conditions"])))
            self._fire(failpoint, f"after_plan_item:{item['item_index']}")
        self._fire(failpoint, "after_plan_items")
        return PublishReceipt(int(run["id"]), {"weekly_training_plan": artifact_id}, {"weekly_training_plan": revision}, len(input_manifest), plan_id, superseded)

    def _publish_daily(
        self, run: sqlite3.Row, result: Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]], run_evidence: RunEvidence | Mapping[str, Any],
        failpoint: Callable[[str], None] | None,
    ) -> PublishReceipt:
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_artifacts_invalid")
        by_kind = {item.get("artifact_kind"): item for item in artifacts if isinstance(item, Mapping)}
        if len(by_kind) != 2 or set(by_kind) != _DAILY_KINDS:
            raise AnalysisPublishError("analysis_publish_daily_cardinality_invalid")
        self._persist_run_evidence(run, run_evidence, input_manifest)
        self._fire(failpoint, "after_run_evidence")
        self._insert_inputs(int(run["id"]), input_manifest)
        self._fire(failpoint, "after_inputs")
        ids: dict[str, int] = {}
        revisions: dict[str, int] = {}
        for kind in ("daily_summary", "daily_training_advice"):
            artifact_id, revision = self._insert_revision(int(run["subject_id"]), int(run["id"]), kind, by_kind[kind])
            ids[kind], revisions[kind] = artifact_id, revision
            self._fire(failpoint, f"after_artifact:{kind}")
        now = self._clock()
        # paired_with is materialized in both directions so either artifact
        # remains sufficient to navigate the daily atomic pair.
        for left, right in (("daily_summary", "daily_training_advice"), ("daily_training_advice", "daily_summary")):
            self._connection.execute(
                "INSERT INTO analysis_artifact_relations(from_artifact_id,to_artifact_id,relation_type,created_at_utc) VALUES(?,?,?,?)",
                (ids[left], ids[right], "paired_with", now),
            )
        self._record_prior_artifact_relations(int(run["subject_id"]), ids, input_manifest, now)
        self._fire(failpoint, "after_relations")
        return PublishReceipt(int(run["id"]), dict(ids), dict(revisions), len(input_manifest))

    def _publish_weekly(
        self, run: sqlite3.Row, result: Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]], run_evidence: RunEvidence | Mapping[str, Any],
        failpoint: Callable[[str], None] | None,
    ) -> PublishReceipt:
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_artifacts_invalid")
        by_kind = {item.get("artifact_kind"): item for item in artifacts if isinstance(item, Mapping)}
        if len(by_kind) != 2 or set(by_kind) != _WEEKLY_KINDS:
            raise AnalysisPublishError("analysis_publish_weekly_cardinality_invalid")
        plan = self._validate_weekly_plan(result.get("training_plan"), by_kind["weekly_training_plan"])
        self._persist_run_evidence(run, run_evidence, input_manifest)
        self._fire(failpoint, "after_run_evidence")
        self._insert_inputs(int(run["id"]), input_manifest)
        self._fire(failpoint, "after_inputs")
        ids: dict[str, int] = {}
        revisions: dict[str, int] = {}
        for kind in ("weekly_summary", "weekly_training_plan"):
            artifact_id, revision = self._insert_revision(
                int(run["subject_id"]), int(run["id"]), kind, by_kind[kind]
            )
            ids[kind], revisions[kind] = artifact_id, revision
            self._fire(failpoint, f"after_artifact:{kind}")
        now = self._clock()
        for left, right in (("weekly_summary", "weekly_training_plan"), ("weekly_training_plan", "weekly_summary")):
            self._connection.execute(
                "INSERT INTO analysis_artifact_relations(from_artifact_id,to_artifact_id,relation_type,created_at_utc) VALUES(?,?,?,?)",
                (ids[left], ids[right], "paired_with", now),
            )
        self._record_prior_artifact_relations(int(run["subject_id"]), ids, input_manifest, now)
        self._fire(failpoint, "after_relations")
        superseded = self._supersede_overlapping_plans(int(run["subject_id"]), plan["start"], plan["end"])
        self._fire(failpoint, "after_plan_supersession")
        cursor = self._connection.execute(
            "INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(?,?,?,?,?,'active',?,?,?)",
            (int(run["subject_id"]), ids["weekly_training_plan"], plan["start"].isoformat(), plan["end"].isoformat(),
             plan["timezone"], _canonical(plan["objective"]), _canonical(plan["constraints"]), now),
        )
        plan_id = int(cursor.lastrowid)
        self._fire(failpoint, "after_plan")
        for item in plan["items"]:
            self._connection.execute(
                "INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json) VALUES(?,?,?,?,?,?,?)",
                (plan_id, item["item_index"], item["local_date"], item["activity_kind"],
                 _canonical(item["prescription"]), item["rationale_text"], _canonical(item["stop_conditions"])),
            )
            self._fire(failpoint, f"after_plan_item:{item['item_index']}")
        self._fire(failpoint, "after_plan_items")
        return PublishReceipt(int(run["id"]), dict(ids), dict(revisions), len(input_manifest), plan_id, superseded)

    def _publish_plan_revision(
        self, run: sqlite3.Row, result: Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]], run_evidence: RunEvidence | Mapping[str, Any],
        failpoint: Callable[[str], None] | None,
    ) -> PublishReceipt:
        """Persist one immutable replacement for one explicitly named plan.

        The new plan is a full seven-day snapshot.  Rows before its effective
        date are copied from the old plan's stored values, never from model
        output, so published history cannot be rewritten during a revision.
        """
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_artifacts_invalid")
        by_kind = {item.get("artifact_kind"): item for item in artifacts if isinstance(item, Mapping)}
        if len(by_kind) != 1 or set(by_kind) != {"weekly_training_plan"}:
            raise AnalysisPublishError("analysis_publish_plan_revision_cardinality_invalid")
        plan, revision = self._validate_plan_revision(
            result.get("training_plan"), by_kind["weekly_training_plan"]
        )
        subject_id = int(run["subject_id"])
        old = self._load_revision_source(subject_id, revision)
        if (
            old["plan_start_local_date"] != plan["start"].isoformat()
            or old["plan_end_local_date"] != plan["end"].isoformat()
        ):
            raise AnalysisPublishError("analysis_publish_revision_period_invalid")
        self._validate_revision_manifest(input_manifest, old, revision)
        self._assert_reason_unused(revision["reason_event_id"])
        old_items = self._load_plan_items(int(old["plan_id"]), plan["start"], plan["end"])

        self._persist_run_evidence(run, run_evidence, input_manifest)
        self._fire(failpoint, "after_run_evidence")
        self._insert_inputs(int(run["id"]), input_manifest)
        self._fire(failpoint, "after_inputs")
        artifact_id, artifact_revision = self._insert_revision(
            subject_id, int(run["id"]), "weekly_training_plan", by_kind["weekly_training_plan"]
        )
        self._fire(failpoint, "after_artifact:weekly_training_plan")
        now = self._clock()
        for relation in ("derived_from", "references_prior_plan"):
            self._connection.execute(
                "INSERT INTO analysis_artifact_relations(from_artifact_id,to_artifact_id,relation_type,created_at_utc) VALUES(?,?,?,?)",
                (artifact_id, int(old["artifact_id"]), relation, now),
            )
        self._fire(failpoint, "after_plan_revision_lineage")
        changed = self._connection.execute(
            "UPDATE training_plans SET status='superseded' WHERE id=? AND subject_id=? AND status='active'",
            (int(old["plan_id"]), subject_id),
        ).rowcount
        if changed != 1:
            raise AnalysisPublishError("analysis_publish_revision_source_invalid")
        self._fire(failpoint, "after_plan_supersession")
        cursor = self._connection.execute(
            "INSERT INTO training_plans(subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(?,?,?,?,?,'active',?,?,?)",
            (subject_id, artifact_id, plan["start"].isoformat(), plan["end"].isoformat(),
             plan["timezone"], _canonical(plan["objective"]), _canonical(plan["constraints"]), now),
        )
        new_plan_id = int(cursor.lastrowid)
        self._fire(failpoint, "after_plan")
        prefix_count = (
            date.fromisoformat(revision["effective_local_date"]) - plan["start"]
        ).days
        published_items: list[tuple[dict[str, Any], bool]] = [
            (item, True) for item in old_items[:prefix_count]
        ]
        published_items.extend(
            ({**item, "item_index": prefix_count + ordinal}, False)
            for ordinal, item in enumerate(plan["items"])
        )
        if len(published_items) != 7:
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
        for item, copied in published_items:
            self._connection.execute(
                "INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json) VALUES(?,?,?,?,?,?,?)",
                (new_plan_id, item["item_index"], item["local_date"], item["activity_kind"],
                 item["prescription_json"] if copied else _canonical(item["prescription"]),
                 item["rationale_text"],
                 item["stop_conditions_json"] if copied else _canonical(item["stop_conditions"])),
            )
            self._fire(failpoint, f"after_plan_item:{item['item_index']}")
        self._fire(failpoint, "after_plan_items")
        return PublishReceipt(
            int(run["id"]), {"weekly_training_plan": artifact_id},
            {"weekly_training_plan": artifact_revision}, len(input_manifest),
            new_plan_id, (int(old["plan_id"]),),
        )

    @staticmethod
    def _validate_plan_revision(value: Any, artifact: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(value, Mapping) or set(value) != {
            "period", "timezone", "objective", "constraints", "original_plan_id",
            "original_artifact_id", "reason_event_id", "effective_local_date", "items",
        }:
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
        if artifact.get("structured_content") != value:
            raise AnalysisPublishError("analysis_publish_weekly_plan_artifact_mismatch")
        period = value.get("period")
        artifact_period = artifact.get("period")
        if (
            not isinstance(period, Mapping)
            or not isinstance(artifact_period, Mapping)
            or dict(period) != dict(artifact_period)
        ):
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
        try:
            start = date.fromisoformat(str(period["start_local_date"]))
            end = date.fromisoformat(str(period["end_local_date"]))
            effective = date.fromisoformat(str(value["effective_local_date"]))
        except (KeyError, TypeError, ValueError) as error:
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid") from error
        if (
            end - start != timedelta(days=6)
            or not start <= effective <= end
            or value.get("timezone") != "Asia/Singapore"
            or not isinstance(value.get("objective"), Mapping)
            or not isinstance(value.get("constraints"), Mapping)
        ):
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
        revision: dict[str, Any] = {}
        normalized: dict[str, Any] = {}
        for key in ("original_plan_id", "original_artifact_id", "reason_event_id"):
            value_id = _integer_reference(value.get(key))
            if value_id is None:
                raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
            revision[key] = value_id
        revision["effective_local_date"] = effective.isoformat()
        rows = value.get("items")
        suffix_days = (end - effective).days + 1
        if (
            not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes))
            or len(rows) != suffix_days
        ):
            raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
        items: list[dict[str, Any]] = []
        for ordinal, row in enumerate(rows):
            if not isinstance(row, Mapping) or set(row) != {
                "item_index", "local_date", "activity_kind", "prescription",
                "rationale_text", "stop_conditions",
            }:
                raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
            if (
                isinstance(row.get("item_index"), bool)
                or row.get("item_index") != ordinal
                or row.get("local_date") != (effective + timedelta(days=ordinal)).isoformat()
                or row.get("activity_kind") not in _PLAN_ITEM_KINDS
                or not isinstance(row.get("prescription"), Mapping)
                or row["prescription"].get("activity_kind") != row.get("activity_kind")
                or not isinstance(row.get("rationale_text"), str)
            ):
                raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
            stops = row.get("stop_conditions")
            if (
                not isinstance(stops, Sequence)
                or isinstance(stops, (str, bytes))
                or any(not isinstance(item, str) or not item for item in stops)
            ):
                raise AnalysisPublishError("analysis_publish_plan_revision_invalid")
            items.append({
                "item_index": ordinal,
                "local_date": row["local_date"],
                "activity_kind": row["activity_kind"],
                "prescription": dict(row["prescription"]),
                "rationale_text": row["rationale_text"],
                "stop_conditions": list(stops),
            })
        return {
            "start": start,
            "end": end,
            "timezone": value["timezone"],
            "objective": dict(value["objective"]),
            "constraints": dict(value["constraints"]),
            "items": items,
        }, revision

    def _load_revision_source(self, subject_id: int, revision: Mapping[str, Any]) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT p.id AS plan_id,p.subject_id,p.analysis_artifact_id,p.plan_start_local_date,p.plan_end_local_date,p.timezone,p.status,"
            "a.id AS artifact_id,a.subject_id AS artifact_subject_id,a.artifact_kind,a.period_start_local_date,a.period_end_local_date,a.is_current "
            "FROM training_plans p JOIN analysis_artifacts a ON a.id=p.analysis_artifact_id "
            "WHERE p.id=? AND p.subject_id=? AND a.id=?",
            (revision["original_plan_id"], subject_id, revision["original_artifact_id"]),
        ).fetchone()
        if (
            row is None or row["artifact_subject_id"] != subject_id
            or row["status"] != "active" or row["is_current"] != 1
            or row["artifact_kind"] != "weekly_training_plan"
            or row["timezone"] != "Asia/Singapore"
            or row["plan_start_local_date"] != row["period_start_local_date"]
            or row["plan_end_local_date"] != row["period_end_local_date"]
        ):
            raise AnalysisPublishError("analysis_publish_revision_source_invalid")
        return row

    def _validate_revision_manifest(
        self, manifest: Sequence[Mapping[str, Any]], old: sqlite3.Row, revision: Mapping[str, Any],
    ) -> None:
        if not isinstance(manifest, Sequence) or isinstance(manifest, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_input_manifest_invalid")
        expected = {
            ("training_plan", int(old["plan_id"])),
            ("analysis_artifact", int(old["artifact_id"])),
            ("conversation_event", int(revision["reason_event_id"])),
        }
        actual = [
            (item.get("source_entity_type"), _integer_reference(item.get("source_entity_id")))
            for item in manifest if isinstance(item, Mapping)
        ]
        if any(actual.count(reference) != 1 for reference in expected):
            raise AnalysisPublishError("analysis_publish_revision_manifest_invalid")
        reason = self._connection.execute(
            "SELECT id,subject_id,event_type,actor_role,trust_level FROM conversation_events WHERE id=?",
            (revision["reason_event_id"],),
        ).fetchone()
        if (
            reason is None or reason["subject_id"] != old["subject_id"]
            or reason["event_type"] != "plan_revision_reason_recorded"
            or reason["actor_role"] != "trainlab" or reason["trust_level"] != "system_generated"
        ):
            raise AnalysisPublishError("analysis_publish_revision_reason_invalid")

    def _assert_reason_unused(self, reason_event_id: int) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM analysis_artifact_inputs i JOIN analysis_runs r ON r.id=i.analysis_run_id "
            "WHERE i.source_entity_type='conversation_event' AND i.source_entity_id=? "
            "AND r.analysis_kind='plan_revision' AND r.status='succeeded' LIMIT 1",
            (reason_event_id,),
        ).fetchone()
        if row is not None:
            raise AnalysisPublishError("analysis_publish_revision_reason_already_consumed")

    def _load_plan_items(self, plan_id: int, start: date, end: date) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json "
            "FROM training_plan_items WHERE training_plan_id=? ORDER BY item_index",
            (plan_id,),
        ).fetchall()
        if len(rows) != 7:
            raise AnalysisPublishError("analysis_publish_revision_source_items_invalid")
        items: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if row["item_index"] != index or row["local_date"] != (start + timedelta(days=index)).isoformat() or row["activity_kind"] not in _PLAN_ITEM_KINDS or not isinstance(row["rationale_text"], str):
                raise AnalysisPublishError("analysis_publish_revision_source_items_invalid")
            try:
                prescription, stops = json.loads(row["prescription_json"]), json.loads(row["stop_conditions_json"])
            except (TypeError, ValueError) as error:
                raise AnalysisPublishError("analysis_publish_revision_source_items_invalid") from error
            if not isinstance(prescription, Mapping) or not isinstance(stops, list):
                raise AnalysisPublishError("analysis_publish_revision_source_items_invalid")
            items.append({**dict(row), "prescription": dict(prescription), "stop_conditions": stops})
        return items

    @staticmethod
    def _validate_weekly_plan(value: Any, plan_artifact: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"period", "timezone", "objective", "constraints", "prior_artifact_state", "items"}:
            raise AnalysisPublishError("analysis_publish_weekly_plan_invalid")
        if plan_artifact.get("structured_content") != value:
            raise AnalysisPublishError("analysis_publish_weekly_plan_artifact_mismatch")
        period = value.get("period")
        artifact_period = plan_artifact.get("period")
        if (
            not isinstance(period, Mapping)
            or not isinstance(artifact_period, Mapping)
            or dict(period) != dict(artifact_period)
        ):
            raise AnalysisPublishError("analysis_publish_weekly_plan_period_invalid")
        try:
            start = date.fromisoformat(str(period["start_local_date"]))
            end = date.fromisoformat(str(period["end_local_date"]))
        except (KeyError, TypeError, ValueError) as error:
            raise AnalysisPublishError("analysis_publish_weekly_plan_period_invalid") from error
        if end - start != timedelta(days=6) or value.get("timezone") != "Asia/Singapore":
            raise AnalysisPublishError("analysis_publish_weekly_plan_period_invalid")
        if not isinstance(value.get("objective"), Mapping) or not isinstance(value.get("constraints"), Mapping):
            raise AnalysisPublishError("analysis_publish_weekly_plan_invalid")
        prior_state = value.get("prior_artifact_state")
        if (
            not isinstance(prior_state, Mapping)
            or set(prior_state) != {"summary", "plan"}
            or prior_state.get("summary") not in {"available", "no_prior_artifact"}
            or prior_state.get("plan") not in {"available", "no_prior_artifact"}
        ):
            raise AnalysisPublishError("analysis_publish_weekly_plan_prior_artifact_state_invalid")
        rows = value.get("items")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != 7:
            raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
        normalized: list[dict[str, Any]] = []
        for ordinal, row in enumerate(rows):
            if not isinstance(row, Mapping) or set(row) != {"item_index", "local_date", "activity_kind", "prescription", "rationale_text", "stop_conditions"}:
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
            if row.get("item_index") != ordinal or isinstance(row.get("item_index"), bool):
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
            try:
                local_day = date.fromisoformat(str(row["local_date"]))
            except (KeyError, TypeError, ValueError) as error:
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid") from error
            if local_day != start + timedelta(days=ordinal) or row.get("activity_kind") not in _PLAN_ITEM_KINDS:
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
            if not isinstance(row.get("prescription"), Mapping) or not isinstance(row.get("rationale_text"), str):
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
            stops = row.get("stop_conditions")
            if not isinstance(stops, Sequence) or isinstance(stops, (str, bytes)) or any(not isinstance(x, str) or not x for x in stops):
                raise AnalysisPublishError("analysis_publish_weekly_plan_items_invalid")
            normalized.append({
                "item_index": ordinal, "local_date": local_day.isoformat(), "activity_kind": row["activity_kind"],
                "prescription": dict(row["prescription"]), "rationale_text": row["rationale_text"],
                "stop_conditions": list(stops),
            })
        return {"start": start, "end": end, "timezone": value["timezone"], "objective": dict(value["objective"]), "constraints": dict(value["constraints"]), "prior_artifact_state": dict(prior_state), "items": normalized}

    def _supersede_overlapping_plans(self, subject_id: int, start: date, end: date) -> tuple[int, ...]:
        rows = self._connection.execute(
            "SELECT id FROM training_plans WHERE subject_id=? AND status IN ('active','proposed') AND plan_end_local_date>=? AND plan_start_local_date<=? ORDER BY id",
            (subject_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        ids = tuple(int(row["id"]) for row in rows)
        if ids:
            self._connection.executemany("UPDATE training_plans SET status='superseded' WHERE id=? AND status IN ('active','proposed')", ((plan_id,) for plan_id in ids))
        return ids

    def _persist_run_evidence(
        self, run: sqlite3.Row, value: RunEvidence | Mapping[str, Any],
        manifest: Sequence[Mapping[str, Any]],
    ) -> None:
        if isinstance(value, RunEvidence):
            evidence = {
                "harness_version": value.harness_version,
                "input_schema_version": value.input_schema_version,
                "output_schema_version": value.output_schema_version,
                "context_snapshot_json": value.context_snapshot_json,
                "context_snapshot_sha256": value.context_snapshot_sha256,
                "generator_metadata_json": value.generator_metadata_json,
            }
        elif isinstance(value, Mapping):
            evidence = dict(value)
        else:
            raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
        expected_keys = {
            "harness_version", "input_schema_version", "output_schema_version",
            "context_snapshot_json", "context_snapshot_sha256",
            "generator_metadata_json",
        }
        if set(evidence) != expected_keys:
            raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
        for name in ("harness_version", "input_schema_version", "output_schema_version"):
            field = evidence[name]
            if not isinstance(field, str) or not field or len(field) > 128:
                raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
        snapshot = evidence["context_snapshot_json"]
        metadata = evidence["generator_metadata_json"]
        if not isinstance(snapshot, Mapping) or not isinstance(metadata, Mapping):
            raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
        if snapshot.get("input_manifest") != list(manifest):
            raise AnalysisPublishError("analysis_publish_run_evidence_manifest_mismatch")
        _validate_safe_evidence(snapshot)
        _validate_safe_evidence(metadata)
        try:
            snapshot_json = _canonical(snapshot)
            metadata_json = _canonical(metadata)
        except (TypeError, ValueError, OverflowError) as error:
            raise AnalysisPublishError("analysis_publish_run_evidence_invalid") from error
        if (
            len(snapshot_json.encode("utf-8")) > _MAX_CONTEXT_BYTES
            or len(metadata_json.encode("utf-8")) > _MAX_GENERATOR_METADATA_BYTES
        ):
            raise AnalysisPublishError("analysis_publish_run_evidence_too_large")
        digest = evidence["context_snapshot_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or sha256(snapshot_json.encode("utf-8")).hexdigest() != digest
        ):
            raise AnalysisPublishError("analysis_publish_run_evidence_hash_mismatch")
        values = (
            evidence["harness_version"], evidence["input_schema_version"],
            evidence["output_schema_version"], snapshot_json, digest, metadata_json,
        )
        existing = tuple(run[name] for name in (
            "harness_version", "input_schema_version", "output_schema_version",
            "context_snapshot_json", "context_snapshot_sha256",
            "generator_metadata_json",
        ))
        if any(item is not None for item in existing) and existing != values:
            raise AnalysisPublishError("analysis_publish_run_evidence_conflict")
        updated = self._connection.execute(
            "UPDATE analysis_runs SET harness_version=?,input_schema_version=?,"
            "output_schema_version=?,context_snapshot_json=?,"
            "context_snapshot_sha256=?,generator_metadata_json=? "
            "WHERE id=? AND status='started'",
            (*values, run["id"]),
        ).rowcount
        if updated != 1:
            raise AnalysisPublishError("analysis_publish_run_not_started")

    def _record_prior_artifact_relations(
        self, subject_id: int, artifact_ids: Mapping[str, int], manifest: Sequence[Mapping[str, Any]], now: str,
    ) -> None:
        """Make prior-model references explicit instead of inferring them by date later."""
        for item in manifest:
            if not isinstance(item, Mapping) or item.get("source_entity_type") != "analysis_artifact":
                continue
            source_id = _integer_reference(item.get("source_entity_id"))
            if source_id is None:
                raise AnalysisPublishError("analysis_publish_prior_artifact_invalid")
            source = self._connection.execute(
                "SELECT id,subject_id,artifact_kind FROM analysis_artifacts WHERE id=?", (source_id,)
            ).fetchone()
            if source is None or source["subject_id"] != subject_id:
                raise AnalysisPublishError("analysis_publish_prior_artifact_invalid")
            if source["artifact_kind"] not in {
                "weekly_summary",
                "weekly_training_plan",
            }:
                continue
            relation = (
                "references_prior_plan"
                if source["artifact_kind"] == "weekly_training_plan"
                else "references_prior_summary"
            )
            for artifact_id in artifact_ids.values():
                self._connection.execute(
                    "INSERT OR IGNORE INTO analysis_artifact_relations(from_artifact_id,to_artifact_id,relation_type,created_at_utc) VALUES(?,?,?,?)",
                    (artifact_id, source_id, relation, now),
                )

    def _insert_inputs(self, run_id: int, manifest: Sequence[Mapping[str, Any]]) -> None:
        if not isinstance(manifest, Sequence) or isinstance(manifest, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_input_manifest_invalid")
        rows = list(manifest)
        for ordinal, item in enumerate(rows):
            if not isinstance(item, Mapping) or item.get("ordinal") != ordinal:
                raise AnalysisPublishError("analysis_publish_input_manifest_invalid")
            required = ("input_role", "source_entity_type", "source_entity_id", "source_revision_id", "input_sha256", "trust_class", "source_window")
            if any(not isinstance(item.get(key), str) or not item.get(key) for key in required[:-1]):
                raise AnalysisPublishError("analysis_publish_input_manifest_invalid")
            if item["trust_class"] not in _TRUST or len(item["input_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in item["input_sha256"]):
                raise AnalysisPublishError("analysis_publish_input_manifest_invalid")
            start_utc, end_utc = _utc_bounds(item["source_window"])
            self._connection.execute(
                "INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, item["input_role"], item["source_entity_type"], _integer_reference(item["source_entity_id"]), _integer_reference(item["source_revision_id"]), start_utc, end_utc, item["input_sha256"], item["trust_class"], ordinal),
            )

    def _insert_revision(self, subject_id: int, run_id: int, kind: str, artifact: Mapping[str, Any]) -> tuple[int, int]:
        period, structured, text = artifact.get("period"), artifact.get("structured_content"), artifact.get("user_visible_text")
        if not isinstance(period, Mapping) or not isinstance(text, str) or not text:
            raise AnalysisPublishError("analysis_publish_artifact_invalid")
        try:
            start, end = date.fromisoformat(str(period["start_local_date"])), date.fromisoformat(str(period["end_local_date"]))
        except (KeyError, TypeError, ValueError) as error:
            raise AnalysisPublishError("analysis_publish_artifact_period_invalid") from error
        if end < start:
            raise AnalysisPublishError("analysis_publish_artifact_period_invalid")
        prior = self._connection.execute(
            "SELECT id,revision_no FROM analysis_artifacts WHERE subject_id=? AND artifact_kind=? AND period_start_local_date=? AND period_end_local_date=? AND is_current=1",
            (subject_id, kind, start.isoformat(), end.isoformat()),
        ).fetchone()
        next_revision = int(self._connection.execute(
            "SELECT COALESCE(MAX(revision_no),0)+1 FROM analysis_artifacts WHERE subject_id=? AND artifact_kind=? AND period_start_local_date=? AND period_end_local_date=?",
            (subject_id, kind, start.isoformat(), end.isoformat()),
        ).fetchone()[0])
        now = self._clock()
        cursor = self._connection.execute(
            "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,supersedes_artifact_id,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (subject_id, kind, start.isoformat(), end.isoformat(), next_revision, run_id, "1", _canonical(structured), text, _content_hash(structured, text), 0, int(prior["id"]) if prior else None, now),
        )
        artifact_id = int(cursor.lastrowid)
        if prior:
            self._connection.execute("UPDATE analysis_artifacts SET is_current=0 WHERE id=? AND is_current=1", (prior["id"],))
            self._connection.execute(
                "INSERT INTO analysis_artifact_relations(from_artifact_id,to_artifact_id,relation_type,created_at_utc) VALUES(?,?,?,?)",
                (artifact_id, int(prior["id"]), "supersedes", now),
            )
        self._connection.execute("UPDATE analysis_artifacts SET is_current=1 WHERE id=?", (artifact_id,))
        return artifact_id, next_revision

    @staticmethod
    def _fire(failpoint: Callable[[str], None] | None, stage: str) -> None:
        if failpoint is not None:
            failpoint(stage)


def publish_accepted_daily(
    connection: sqlite3.Connection, *, run_id: int,
    accepted: ValidatedAnalysisResult | Mapping[str, Any],
    input_manifest: Sequence[Mapping[str, Any]],
    run_evidence: RunEvidence | Mapping[str, Any],
) -> PublishReceipt:
    """Small functional entrypoint for a future route coordinator."""
    return AnalysisPublisher(connection).publish(
        run_id=run_id, accepted=accepted, input_manifest=input_manifest,
        run_evidence=run_evidence,
    )


def _validate_safe_evidence(value: Any, *, key: str | None = None) -> None:
    if key is not None and key.casefold() in _FORBIDDEN_EVIDENCE_KEYS:
        raise AnalysisPublishError("analysis_publish_run_evidence_forbidden")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
        return
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
            _validate_safe_evidence(child, key=child_key)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_safe_evidence(child)
        return
    raise AnalysisPublishError("analysis_publish_run_evidence_invalid")
