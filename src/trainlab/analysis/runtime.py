"""Production wiring for the explicit ``trainlab run --analysis-only`` path.

This module is intentionally a small composition root.  It does not schedule,
poll mail, or deliver mail; ``DailyRoute`` can only seed a pending delivery.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from ..foundation import FoundationConfig, FoundationTool
from ..util import project_root
from .config import load_analysis_config
from .contracts import AnalysisRequest, AnalysisReceipt
from .delivery import AnalysisDeliveryFactory
from .publisher import AnalysisPublisher
from .run_state import AnalysisRunCoordinator, AnalysisRunRepository, SubjectLockManager
from .runner import AnalysisCodexRunner
from .stable_views import StableViewRepository


_SINGAPORE = ZoneInfo("Asia/Singapore")
_SUBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _strict_date(value: str | None) -> date | None:
    if value is None:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-" or not (value[:4] + value[5:7] + value[8:]).isdigit():
        raise ValueError("analysis_summary_date_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("analysis_summary_date_invalid") from error


def build_daily_request(
    *, subject_id: str, invocation_id: str, summary_date: str | None, now: datetime | None = None
) -> AnalysisRequest:
    """Build the sole supported production-analysis request without I/O."""
    if not isinstance(subject_id, str) or _SUBJECT_KEY.fullmatch(subject_id) is None:
        raise ValueError("analysis_subject_id_invalid")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("analysis_invocation_id_required")
    summary = _strict_date(summary_date)
    current = (now or datetime.now(UTC)).astimezone(_SINGAPORE).date()
    summary = summary or current - timedelta(days=1)
    if summary >= current:
        raise ValueError("analysis_summary_date_must_be_before_today")
    requested = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return AnalysisRequest.from_dict({
        "schema_version": "1",
        "mode": "daily",
        "subject_id": subject_id,
        "invocation_id": invocation_id,
        "run_key": None,
        "summary_local_date": summary.isoformat(),
        "advice_local_date": (summary + timedelta(days=1)).isoformat(),
        "as_of_local_date": None,
        "plan_id": None,
        "reason_event_id": None,
        "effective_local_date": None,
        "artifact_id": None,
        "delivery_id": None,
        "regeneration_reason_code": None,
        "requested_at_utc": requested,
    })


def _active_subject_key(connection: object) -> str:
    """Read only the active public subject key; fail closed unless it is unique."""
    rows = list(connection.execute(
        "SELECT subject_key FROM data_subjects WHERE is_active=1 ORDER BY id"
    ))  # type: ignore[union-attr]
    if len(rows) != 1:
        raise ValueError("analysis_active_subject_not_unique")
    subject_key = rows[0][0]
    if not isinstance(subject_key, str) or _SUBJECT_KEY.fullmatch(subject_key) is None:
        raise ValueError("analysis_active_subject_invalid")
    return subject_key


def run_analysis_only(
    *, invocation_id: str, summary_date: str | None = None, root: Path | None = None
) -> AnalysisReceipt:
    """Execute one L3 daily route and always release its Foundation connection."""
    root = (root or project_root()).resolve()
    foundation = FoundationConfig.load(root)
    config = load_analysis_config(root, root / "config" / "analysis.yaml")
    connection = FoundationTool(foundation)._connect(foundation.database_path)
    try:
        request = build_daily_request(
            subject_id=_active_subject_key(connection),
            invocation_id=invocation_id,
            summary_date=summary_date,
        )
        repository = AnalysisRunRepository(connection)
        coordinator = AnalysisRunCoordinator(
            repository,
            SubjectLockManager(config.lock_path, trusted_root=config.lock_path.parent.parent),
        )
        # Delay this import so the production entry remains compatible while
        # the independently-owned daily route is being integrated.
        from .daily import DailyRoute

        route = DailyRoute(
            config=config,
            coordinator=coordinator,
            stable_views=StableViewRepository(connection),
            runner=AnalysisCodexRunner(config),
            publisher=AnalysisPublisher(connection),
            delivery=AnalysisDeliveryFactory(connection),
        )
        return route.execute(request)
    finally:
        connection.close()
