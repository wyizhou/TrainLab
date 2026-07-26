"""A3-21 bounded, subject-scoped, read-only analysis status query."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from .contracts import AnalysisDelivery, AnalysisError, AnalysisReceipt, AnalysisRequest, build_run_key


class AnalysisStatusError(RuntimeError):
    """A controlled status-query failure without database content."""


_ARTIFACT_KINDS = (
    "daily_summary", "daily_training_advice", "weekly_summary", "weekly_training_plan",
)
_DELIVERY_COUNTS = ("pending", "delivery_unknown", "failed")
_RETRY_STATUSES = ("pending", "failed")
_RECONCILE_STATUSES = ("sending", "delivery_unknown")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _empty_snapshot() -> dict[str, Any]:
    return {
        "selected_run": None,
        "current_artifacts": [],
        "current_plan": None,
        "latest_delivery": None,
        "delivery_counts": {name: 0 for name in _DELIVERY_COUNTS},
        "actionable_delivery_ids": {"retry_delivery": [], "reconcile_delivery": []},
        "recent_terminal_at_utc": {"succeeded": None, "failed": None, "rejected": None, "deferred": None},
        "quality_blocker_codes": [],
        # The frozen Foundation status enum stores public deferred outcomes as
        # failed runs, so reporting a timestamp here would be untruthful.
        "deferred_history_supported": False,
    }


class AnalysisStatusQueryService:
    """Read status only; it has no write, lock, provider, or model capability."""

    def __init__(self, connection: sqlite3.Connection, *, clock=_utc_now) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._clock = clock

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        request.validate()
        if request.mode != "status":
            raise AnalysisStatusError("analysis_status_mode_required")
        started = request.requested_at_utc
        try:
            subject_id = self._subject_id(request.subject_id)
            snapshot, delivery = self._snapshot(subject_id, request.run_key)
            action = self._next_action(snapshot)
            return AnalysisReceipt(
                run_key=build_run_key(request), invocation_id=None, mode="status",
                status="succeeded", started_at_utc=started, completed_at_utc=self._clock(),
                analysis_run_id=None if snapshot["selected_run"] is None else snapshot["selected_run"]["id"],
                quality_gate_state="blocked" if snapshot["quality_blocker_codes"] else "ready",
                artifact_ids=tuple(item["id"] for item in snapshot["current_artifacts"]),
                training_plan_id=None if snapshot["current_plan"] is None else snapshot["current_plan"]["id"],
                delivery=delivery, next_action=action, status_snapshot=snapshot,
            )
        except (sqlite3.Error, AnalysisStatusError):
            # Do not serialize exception messages, SQL text, or stored data.
            return AnalysisReceipt(
                run_key=build_run_key(request), invocation_id=None, mode="status",
                status="failed", started_at_utc=started, completed_at_utc=self._clock(),
                errors=(AnalysisError("service", "analysis_status_unavailable", "analysis status is unavailable"),),
                status_snapshot=_empty_snapshot(),
            )

    def _subject_id(self, subject_key: str) -> int:
        row = self._connection.execute(
            "SELECT id FROM data_subjects WHERE subject_key=? AND is_active=1", (subject_key,)
        ).fetchone()
        if row is None:
            raise AnalysisStatusError("analysis_status_subject_not_active")
        return int(row["id"])

    def _snapshot(self, subject_id: int, run_key: str | None) -> tuple[dict[str, Any], AnalysisDelivery | None]:
        snapshot = _empty_snapshot()
        selected = self._selected_run(subject_id, run_key)
        snapshot["selected_run"] = selected
        snapshot["current_artifacts"] = self._artifacts(subject_id)
        snapshot["current_plan"] = self._plan(subject_id)
        latest, delivery = self._latest_delivery(subject_id)
        snapshot["latest_delivery"] = latest
        snapshot["delivery_counts"] = self._delivery_counts(subject_id)
        snapshot["actionable_delivery_ids"] = self._actionable_delivery_ids(subject_id)
        snapshot["recent_terminal_at_utc"] = self._terminal_times(subject_id)
        snapshot["quality_blocker_codes"] = self._quality_blockers(subject_id)
        return snapshot, delivery

    def _selected_run(self, subject_id: int, run_key: str | None) -> dict[str, Any] | None:
        if run_key is None:
            row = self._connection.execute(
                "SELECT id,run_key,status,started_at_utc,completed_at_utc FROM analysis_runs "
                "WHERE subject_id=? AND run_key LIKE 'analysis:%' "
                "ORDER BY started_at_utc DESC,id DESC LIMIT 1", (subject_id,)
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT id,run_key,status,started_at_utc,completed_at_utc FROM analysis_runs "
                "WHERE subject_id=? AND run_key=? LIMIT 1", (subject_id, run_key)
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row["id"]), "run_key": row["run_key"], "status": row["status"],
                "started_at_utc": row["started_at_utc"], "completed_at_utc": row["completed_at_utc"]}

    def _artifacts(self, subject_id: int) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in _ARTIFACT_KINDS)
        rows = self._connection.execute(
            "SELECT id,artifact_kind,period_start_local_date,period_end_local_date,revision_no "
            f"FROM v_current_analysis_artifacts WHERE subject_id=? AND artifact_kind IN ({placeholders}) "
            "ORDER BY artifact_kind,period_start_local_date,period_end_local_date,revision_no,id LIMIT 16",
            (subject_id, *_ARTIFACT_KINDS),
        )
        return [{"id": str(row["id"]), "kind": row["artifact_kind"],
                 "period_start_local_date": row["period_start_local_date"],
                 "period_end_local_date": row["period_end_local_date"], "revision_no": row["revision_no"]} for row in rows]

    def _plan(self, subject_id: int) -> dict[str, Any] | None:
        rows = list(self._connection.execute(
            "SELECT id,plan_start_local_date,plan_end_local_date,status FROM v_current_training_plans "
            "WHERE subject_id=? ORDER BY created_at_utc DESC,id DESC LIMIT 2", (subject_id,)
        ))
        if len(rows) > 1:
            raise AnalysisStatusError("analysis_status_current_plan_ambiguous")
        if not rows:
            return None
        row = rows[0]
        return {"id": str(row["id"]), "start_local_date": row["plan_start_local_date"],
                "end_local_date": row["plan_end_local_date"], "status": row["status"]}

    def _latest_delivery(self, subject_id: int) -> tuple[dict[str, Any] | None, AnalysisDelivery | None]:
        row = self._connection.execute(
            "SELECT id,status FROM analysis_deliveries WHERE subject_id=? "
            "ORDER BY updated_at_utc DESC,id DESC LIMIT 1", (subject_id,)
        ).fetchone()
        if row is None:
            return None, None
        artifact_rows = self._connection.execute(
            "SELECT da.analysis_artifact_id FROM analysis_delivery_artifacts da "
            "JOIN analysis_deliveries d ON d.id=da.analysis_delivery_id "
            "WHERE d.id=? AND d.subject_id=? ORDER BY da.ordinal", (row["id"], subject_id)
        )
        artifacts = tuple(str(item["analysis_artifact_id"]) for item in artifact_rows)
        status = row["status"]
        return ({"id": str(row["id"]), "status": status},
                AnalysisDelivery(str(row["id"]), status, artifacts))

    def _delivery_counts(self, subject_id: int) -> dict[str, int]:
        counts = {name: 0 for name in _DELIVERY_COUNTS}
        rows = self._connection.execute(
            "SELECT status,COUNT(*) AS count FROM analysis_deliveries WHERE subject_id=? "
            "AND status IN ('pending','delivery_unknown','failed') GROUP BY status", (subject_id,)
        )
        for row in rows:
            counts[row["status"]] = int(row["count"])
        return counts

    def _actionable_delivery_ids(self, subject_id: int) -> dict[str, list[str]]:
        rows = self._connection.execute(
            "SELECT id,status FROM analysis_deliveries WHERE subject_id=? "
            "AND status IN ('pending','failed','sending','delivery_unknown') "
            "ORDER BY updated_at_utc DESC,id DESC LIMIT 64", (subject_id,)
        )
        result = {"retry_delivery": [], "reconcile_delivery": []}
        for row in rows:
            if row["status"] in _RETRY_STATUSES and len(result["retry_delivery"]) < 32:
                result["retry_delivery"].append(str(row["id"]))
            elif row["status"] in _RECONCILE_STATUSES and len(result["reconcile_delivery"]) < 32:
                result["reconcile_delivery"].append(str(row["id"]))
        return result

    def _terminal_times(self, subject_id: int) -> dict[str, str | None]:
        result: dict[str, str | None] = {"succeeded": None, "failed": None, "rejected": None, "deferred": None}
        rows = self._connection.execute(
            "SELECT status,MAX(completed_at_utc) AS completed_at_utc FROM analysis_runs "
            "WHERE subject_id=? AND status IN ('succeeded','failed','rejected') GROUP BY status", (subject_id,)
        )
        for row in rows:
            result[row["status"]] = row["completed_at_utc"]
        return result

    def _quality_blockers(self, subject_id: int) -> list[str]:
        # The frozen issue table has no subject_id.  Report only issue entities
        # that can be proved to belong to this subject; unscoped issues are not
        # safe to expose through a subject status receipt.
        rows = self._connection.execute(
            "SELECT DISTINCT q.issue_code FROM v_open_data_quality_issues q "
            "WHERE q.severity='error' AND ("
            "(q.entity_type='analysis_run' AND EXISTS(SELECT 1 FROM analysis_runs r WHERE r.id=q.entity_id AND r.subject_id=?)) OR "
            "(q.entity_type='analysis_artifact' AND EXISTS(SELECT 1 FROM analysis_artifacts a WHERE a.id=q.entity_id AND a.subject_id=?)) OR "
            "(q.entity_type='training_plan' AND EXISTS(SELECT 1 FROM training_plans p WHERE p.id=q.entity_id AND p.subject_id=?))"
            ") ORDER BY q.issue_code LIMIT 64", (subject_id, subject_id, subject_id),
        )
        return [str(row["issue_code"]) for row in rows]

    @staticmethod
    def _next_action(snapshot: dict[str, Any]) -> str:
        if snapshot["actionable_delivery_ids"]["reconcile_delivery"]:
            return "reconcile_delivery"
        if snapshot["actionable_delivery_ids"]["retry_delivery"]:
            return "retry_delivery"
        if snapshot["quality_blocker_codes"]:
            return "repair_data"
        return "none"
