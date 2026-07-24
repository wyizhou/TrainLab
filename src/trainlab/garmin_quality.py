"""Read-only quality gate consumed by analysis, never by a model directly."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class QualityGate:
    state: str
    reasons: tuple[str, ...]
    open_gap_count: int

def weekly_quality_gate(database_path: str, subject_id: int, through: str) -> QualityGate:
    conn=sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        end=date.fromisoformat(through); start=(end-timedelta(days=6)).isoformat()
        gaps=int(conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred') AND window_end_local_date>=? AND window_start_local_date<=?",(subject_id,start,through)).fetchone()[0])
        errors=int(conn.execute("SELECT count(*) FROM data_quality_issues WHERE status IN ('open','acknowledged') AND severity='error'").fetchone()[0])
        partial=int(conn.execute("SELECT count(*) FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND local_date BETWEEN ? AND ? AND availability_state='partial'",(subject_id,start,through)).fetchone()[0])
        reasons=tuple(name for name,count in (("open_gap",gaps),("quality_error",errors),("partial_coverage",partial)) if count)
        return QualityGate("blocked" if gaps or errors else ("ready_with_warnings" if partial else "ready"), reasons, gaps)
    finally: conn.close()
