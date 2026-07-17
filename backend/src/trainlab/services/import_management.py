import base64
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from trainlab.db.base import utc_now
from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.db.models.user import User
from trainlab.schemas.import_management import ImportListItem, ImportListPage
from trainlab.services.activity_states import (
    DELETE_RECOVERABLE_STATUSES,
    PARSE_RETRYABLE_STATUSES,
)
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError

_SAFE_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,80}$")


class ImportManagementError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DeleteTarget:
    import_id: uuid.UUID | None = None
    activity_id: uuid.UUID | None = None


def _safe_failure(imported: ActivityImport) -> tuple[str | None, str | None]:
    code = imported.delete_error_code if imported.status == "delete_failed" else imported.error_code
    if code is None:
        return None, None
    if _SAFE_ERROR_CODE.fullmatch(code) is None:
        code = "import_failed"
    message = (
        "原始 FIT 文件删除尚未完成" if imported.status == "delete_failed" else "FIT 导入处理失败"
    )
    return code, message


def _encode_cursor(imported: ActivityImport) -> str:
    payload = f"{imported.created_at.isoformat()}|{imported.id}".encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, raw_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("cursor timestamp must have timezone")
        return parsed.astimezone(UTC), uuid.UUID(raw_id)
    except (ValueError, UnicodeError) as exc:
        raise ImportManagementError("invalid_cursor", "分页游标无效") from exc


def list_user_imports(
    db: Session,
    user_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> ImportListPage:
    query = (
        select(ActivityImport, Activity.id)
        .outerjoin(
            Activity,
            and_(
                Activity.source_import_id == ActivityImport.id,
                Activity.user_id == user_id,
            ),
        )
        .where(ActivityImport.user_id == user_id)
    )
    if cursor is not None:
        cursor_time, cursor_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                ActivityImport.created_at < cursor_time,
                and_(ActivityImport.created_at == cursor_time, ActivityImport.id < cursor_id),
            )
        )
    rows = db.execute(
        query.order_by(ActivityImport.created_at.desc(), ActivityImport.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    visible = rows[:limit]
    items: list[ImportListItem] = []
    for imported, activity_id in visible:
        error_code, error_message = _safe_failure(imported)
        items.append(
            ImportListItem(
                import_id=imported.id,
                activity_id=activity_id,
                source=imported.source,
                original_file_name=imported.original_filename,
                size_bytes=imported.size_bytes,
                status=imported.status,
                created_at=imported.created_at,
                updated_at=imported.updated_at,
                attempt_count=imported.attempt_count,
                last_attempt_at=imported.last_attempt_at,
                completed_at=imported.completed_at,
                warning_count=imported.warning_count,
                error_code=error_code,
                error_message=error_message,
                retry_available=imported.status in PARSE_RETRYABLE_STATUSES,
                delete_retry_available=imported.status in DELETE_RECOVERABLE_STATUSES,
            )
        )
    return ImportListPage(
        items=items,
        next_cursor=_encode_cursor(visible[-1][0]) if has_more and visible else None,
    )


def _lock_user(db: Session, user_id: uuid.UUID) -> None:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ImportManagementError("not_found", "资源不存在")


def _lock_target(
    db: Session,
    user_id: uuid.UUID,
    target: DeleteTarget,
) -> ActivityImport | None:
    query = select(ActivityImport).where(ActivityImport.user_id == user_id)
    if target.import_id is not None:
        query = query.where(ActivityImport.id == target.import_id)
    elif target.activity_id is not None:
        query = query.join(Activity, Activity.source_import_id == ActivityImport.id).where(
            Activity.id == target.activity_id,
            Activity.user_id == user_id,
        )
    else:  # pragma: no cover - constructor boundary
        raise ValueError("delete target is empty")
    return db.scalar(
        query.execution_options(populate_existing=True).with_for_update(of=ActivityImport)
    )


def _mark_delete_failed(
    db: Session,
    user_id: uuid.UUID,
    import_id: uuid.UUID,
    error_code: str,
) -> bool:
    _lock_user(db, user_id)
    imported = _lock_target(db, user_id, DeleteTarget(import_id=import_id))
    if imported is None:
        db.rollback()
        return False
    imported.status = "delete_failed"
    imported.processing_token = None
    imported.last_delete_attempt_at = utc_now()
    imported.delete_error_code = (
        error_code if _SAFE_ERROR_CODE.fullmatch(error_code) else "delete_failed"
    )
    db.commit()
    return True


def delete_user_import(
    db: Session,
    storage: PrivateActivityStorage,
    user_id: uuid.UUID,
    target: DeleteTarget,
    stale_minutes: int,
) -> None:
    try:
        _lock_user(db, user_id)
        imported = _lock_target(db, user_id, target)
        if imported is None:
            db.rollback()
            return
        now = utc_now()
        if imported.status == "processing":
            stale_before = now - timedelta(minutes=stale_minutes)
            if imported.last_attempt_at is None or imported.last_attempt_at > stale_before:
                db.rollback()
                raise ImportManagementError("import_in_progress", "FIT 导入仍在处理中")
        imported.status = "deleting"
        imported.processing_token = None
        imported.delete_requested_at = imported.delete_requested_at or now
        imported.last_delete_attempt_at = now
        imported.delete_attempt_count += 1
        imported.delete_error_code = None
        import_id = imported.id
        storage_key = imported.storage_key
        db.commit()
    except ImportManagementError:
        raise
    except Exception:
        db.rollback()
        raise ImportManagementError("delete_incomplete", "删除尚未完成，可稍后重试") from None

    try:
        storage.remove(storage_key, user_id)
    except StorageError as exc:
        try:
            remains = _mark_delete_failed(db, user_id, import_id, exc.code)
        except Exception:
            db.rollback()
            raise ImportManagementError("delete_incomplete", "删除尚未完成，可稍后重试") from None
        if not remains:
            return
        raise ImportManagementError("delete_incomplete", "删除尚未完成，可稍后重试") from None

    try:
        _lock_user(db, user_id)
        imported = _lock_target(db, user_id, DeleteTarget(import_id=import_id))
        if imported is None:
            db.rollback()
            return
        db.delete(imported)
        db.commit()
    except Exception:
        db.rollback()
        raise ImportManagementError("delete_incomplete", "删除尚未完成，可稍后重试") from None
