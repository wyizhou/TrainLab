"""A3-13 atomic persistence for accepted analysis results.

The publisher deliberately owns only the short SQLite transaction after A3-12
has accepted a result.  It neither completes ``analysis_runs`` nor creates a
delivery; the coordinator retains both of those responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    """Publish one accepted daily pair with revision/current invariants."""

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
        failpoint: Callable[[str], None] | None = None,
    ) -> PublishReceipt:
        """Atomically publish a validated daily pair and its full input manifest.

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
                run_id, result, input_manifest, run_evidence, failpoint
            )
            self._connection.execute("COMMIT")
            return receipt
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _publish_in_transaction(
        self, run_id: int, result: Mapping[str, Any],
        input_manifest: Sequence[Mapping[str, Any]],
        run_evidence: RunEvidence | Mapping[str, Any],
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
        if result.get("status") != "accepted" or result.get("mode") != "daily" or run["analysis_kind"] != "daily":
            raise AnalysisPublishError("analysis_publish_route_not_implemented")
        if result.get("run_key") != run["run_key"] or result.get("subject_id") != run["subject_id"]:
            raise AnalysisPublishError("analysis_publish_run_identity_mismatch")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise AnalysisPublishError("analysis_publish_artifacts_invalid")
        by_kind = {item.get("artifact_kind"): item for item in artifacts if isinstance(item, Mapping)}
        if len(by_kind) != 2 or set(by_kind) != _DAILY_KINDS:
            raise AnalysisPublishError("analysis_publish_daily_cardinality_invalid")
        self._persist_run_evidence(run, run_evidence, input_manifest)
        self._fire(failpoint, "after_run_evidence")
        self._insert_inputs(run_id, input_manifest)
        self._fire(failpoint, "after_inputs")
        ids: dict[str, int] = {}
        revisions: dict[str, int] = {}
        for kind in ("daily_summary", "daily_training_advice"):
            artifact_id, revision = self._insert_revision(int(run["subject_id"]), run_id, kind, by_kind[kind])
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
        return PublishReceipt(run_id, dict(ids), dict(revisions), len(input_manifest))

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
            relation = "references_prior_plan" if source["artifact_kind"] == "weekly_training_plan" else "references_prior_summary"
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
