import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.services.activity_states import VISIBLE_ACTIVITY_STATUSES


class ActivityMetadataError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_activity_name(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = name.strip()
    if not normalized or len(normalized) > 255:
        raise ActivityMetadataError("invalid_activity_name", "运动名称长度必须为 1 到 255 个字符")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise ActivityMetadataError("invalid_activity_name", "运动名称不能包含控制字符")
    return normalized


def update_activity_name(
    db: Session,
    user_id: uuid.UUID,
    activity_id: uuid.UUID,
    name: str | None,
) -> tuple[Activity, ActivityImport]:
    row = db.execute(
        select(Activity, ActivityImport)
        .join(ActivityImport, ActivityImport.id == Activity.source_import_id)
        .where(
            Activity.id == activity_id,
            Activity.user_id == user_id,
            ActivityImport.user_id == user_id,
            ActivityImport.status.in_(VISIBLE_ACTIVITY_STATUSES),
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise ActivityMetadataError("not_found", "运动记录不存在")

    activity, imported = row
    imported.title_override = normalize_activity_name(name)
    db.commit()
    db.refresh(activity)
    db.refresh(imported)
    return activity, imported
