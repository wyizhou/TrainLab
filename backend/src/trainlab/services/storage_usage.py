import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trainlab.db.models.activity import ActivityImport
from trainlab.db.models.user import User
from trainlab.schemas.storage_usage import StorageUsageResponse
from trainlab.services.activity_storage import PrivateActivityStorage


@dataclass(frozen=True)
class ReconciliationReport:
    candidate_count: int
    candidate_bytes: int
    removed_count: int
    removed_bytes: int


def storage_usage(
    db: Session,
    user_id: uuid.UUID,
    max_bytes: int,
    max_files: int,
) -> StorageUsageResponse:
    used_bytes, file_count = db.execute(
        select(
            func.coalesce(func.sum(ActivityImport.size_bytes), 0),
            func.count(ActivityImport.id),
        ).where(ActivityImport.user_id == user_id)
    ).one()
    used = int(used_bytes)
    count = int(file_count)
    return StorageUsageResponse(
        used_bytes=used,
        file_count=count,
        max_bytes=max_bytes,
        max_files=max_files,
        remaining_bytes=max(0, max_bytes - used),
        remaining_files=max(0, max_files - count),
    )


def reconcile_storage(
    db: Session,
    storage: PrivateActivityStorage,
    grace_minutes: int,
    *,
    apply: bool,
    now: datetime | None = None,
) -> ReconciliationReport:
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=grace_minutes)
    candidate_count = 0
    candidate_bytes = 0
    removed_count = 0
    removed_bytes = 0
    for user_id in storage.list_user_ids():
        try:
            db.scalar(select(User).where(User.id == user_id).with_for_update())
            referenced = set(
                db.scalars(
                    select(ActivityImport.storage_key).where(ActivityImport.user_id == user_id)
                ).all()
            )
            for candidate in storage.generated_files(user_id):
                if not candidate.isolated and candidate.storage_key in referenced:
                    continue
                if candidate.modified_at > cutoff:
                    continue
                candidate_count += 1
                candidate_bytes += candidate.size_bytes
                if apply:
                    storage.remove_generated(candidate)
                    removed_count += 1
                    removed_bytes += candidate.size_bytes
            db.commit()
        except Exception:
            db.rollback()
            raise
    return ReconciliationReport(
        candidate_count=candidate_count,
        candidate_bytes=candidate_bytes,
        removed_count=removed_count,
        removed_bytes=removed_bytes,
    )
