import hashlib
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.core.security import normalize_username
from trainlab.db.base import utc_now
from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.db.models.user import User
from trainlab.importers.fit import (
    PARSER_NAME,
    PARSER_VERSION,
    FitDecodeFailure,
    ParsedFitActivity,
    parse_fit_file,
)
from trainlab.services.activity_import import replace_activity_projection_in_place
from trainlab.services.activity_locking import lock_activity_owner
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError

REPARSEABLE_STATUSES = frozenset({"complete", "partial"})


class ActivityReparseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReparseSnapshot:
    import_id: uuid.UUID
    activity_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    storage_key: str
    sha256: str
    size_bytes: int
    original_filename: str
    title_override: str | None
    attempt_count: int


@dataclass(frozen=True)
class PreparedReparse:
    snapshot: ReparseSnapshot
    parsed: ParsedFitActivity


@dataclass(frozen=True)
class ReparseItemReport:
    import_id: uuid.UUID
    activity_id: uuid.UUID
    status: str
    record_count: int
    lap_count: int
    segment_count: int


@dataclass(frozen=True)
class ReparseReport:
    applied: bool
    items: tuple[ReparseItemReport, ...]


def _digest_and_rewind(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    handle.seek(0)
    return digest.hexdigest(), size


def _report(prepared: list[PreparedReparse], *, applied: bool) -> ReparseReport:
    return ReparseReport(
        applied=applied,
        items=tuple(
            ReparseItemReport(
                import_id=item.snapshot.import_id,
                activity_id=item.snapshot.activity_id,
                status=item.parsed.status if applied else "ready",
                record_count=len(item.parsed.records),
                lap_count=len(item.parsed.laps),
                segment_count=len(item.parsed.segments),
            )
            for item in prepared
        ),
    )


def _prepare_reparse(
    db: Session,
    storage: PrivateActivityStorage,
    username: str,
    import_ids: list[uuid.UUID],
) -> list[PreparedReparse]:
    if not import_ids or len(set(import_ids)) != len(import_ids):
        raise ActivityReparseError("invalid_import_ids", "导入 ID 必须非空且不能重复")
    user = db.scalar(select(User).where(User.username_normalized == normalize_username(username)))
    if user is None:
        raise ActivityReparseError("user_not_found", "用户不存在")

    ordered_ids = sorted(import_ids, key=str)
    imports = db.scalars(
        select(ActivityImport)
        .where(ActivityImport.user_id == user.id, ActivityImport.id.in_(ordered_ids))
        .order_by(ActivityImport.id)
    ).all()
    if len(imports) != len(ordered_ids):
        raise ActivityReparseError("import_not_found", "导入记录不存在或不属于指定用户")
    activities = db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id, Activity.source_import_id.in_(ordered_ids))
        .order_by(Activity.source_import_id)
    ).all()
    activity_by_import = {activity.source_import_id: activity for activity in activities}

    prepared: list[PreparedReparse] = []
    for imported in imports:
        activity = activity_by_import.get(imported.id)
        if (
            imported.status not in REPARSEABLE_STATUSES
            or imported.processing_token is not None
            or activity is None
        ):
            raise ActivityReparseError("import_not_reparseable", "导入记录当前不允许完整重解析")
        snapshot = ReparseSnapshot(
            import_id=imported.id,
            activity_id=activity.id,
            user_id=user.id,
            status=imported.status,
            storage_key=imported.storage_key,
            sha256=imported.sha256,
            size_bytes=imported.size_bytes,
            original_filename=imported.original_filename,
            title_override=imported.title_override,
            attempt_count=imported.attempt_count,
        )
        try:
            opened = storage.open_for_read(snapshot.storage_key, snapshot.user_id)
        except StorageError:
            raise ActivityReparseError("raw_file_unavailable", "原始 FIT 文件不可用") from None
        try:
            actual_sha256, actual_size = _digest_and_rewind(opened.handle)
            if (
                actual_sha256 != snapshot.sha256
                or actual_size != snapshot.size_bytes
                or opened.size_bytes != snapshot.size_bytes
            ):
                raise ActivityReparseError("raw_file_mismatch", "原始 FIT 文件与导入记录不一致")
            parsed = parse_fit_file(opened.handle, snapshot.original_filename)
        except ActivityReparseError:
            raise
        except FitDecodeFailure as exc:
            raise ActivityReparseError(exc.code, "FIT 文件无法完整重解析") from None
        except Exception:
            raise ActivityReparseError("fit_parse_failed", "FIT 解析暂时失败") from None
        finally:
            with suppress(Exception):
                opened.handle.close()
        prepared.append(PreparedReparse(snapshot=snapshot, parsed=parsed))
    return prepared


def _snapshot_matches(
    imported: ActivityImport,
    activity: Activity,
    snapshot: ReparseSnapshot,
) -> bool:
    return (
        imported.id == snapshot.import_id
        and imported.user_id == snapshot.user_id
        and imported.status == snapshot.status
        and imported.processing_token is None
        and imported.storage_key == snapshot.storage_key
        and imported.sha256 == snapshot.sha256
        and imported.size_bytes == snapshot.size_bytes
        and imported.original_filename == snapshot.original_filename
        and imported.title_override == snapshot.title_override
        and imported.attempt_count == snapshot.attempt_count
        and activity.id == snapshot.activity_id
        and activity.user_id == snapshot.user_id
        and activity.source_import_id == snapshot.import_id
    )


def reparse_fit_imports(
    db: Session,
    storage: PrivateActivityStorage,
    username: str,
    import_ids: list[uuid.UUID],
    *,
    apply: bool,
) -> ReparseReport:
    try:
        prepared = _prepare_reparse(db, storage, username, import_ids)
        # Parsing is intentionally completed before any row lock or database write.
        db.rollback()
        if not apply:
            return _report(prepared, applied=False)

        ordered_ids = [item.snapshot.import_id for item in prepared]
        expected_user_id = prepared[0].snapshot.user_id
        if lock_activity_owner(db, expected_user_id) is None:
            raise ActivityReparseError("import_changed_concurrently", "导入记录在预检后发生变化")
        locked_imports = db.scalars(
            select(ActivityImport)
            .where(
                ActivityImport.id.in_(ordered_ids),
                ActivityImport.user_id == expected_user_id,
            )
            .order_by(ActivityImport.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        ).all()
        locked_activities = db.scalars(
            select(Activity)
            .where(
                Activity.source_import_id.in_(ordered_ids),
                Activity.user_id == expected_user_id,
            )
            .order_by(Activity.source_import_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        ).all()
        imports_by_id = {item.id: item for item in locked_imports}
        activities_by_import = {item.source_import_id: item for item in locked_activities}
        if len(imports_by_id) != len(prepared) or len(activities_by_import) != len(prepared):
            raise ActivityReparseError("import_changed_concurrently", "导入记录在预检后发生变化")

        now = utc_now()
        for item in prepared:
            imported = imports_by_id[item.snapshot.import_id]
            activity = activities_by_import[item.snapshot.import_id]
            if not _snapshot_matches(imported, activity, item.snapshot):
                raise ActivityReparseError(
                    "import_changed_concurrently", "导入记录在预检后发生变化"
                )
            replace_activity_projection_in_place(db, imported, activity, item.parsed)
            imported.status = item.parsed.status
            imported.parser_name = PARSER_NAME
            imported.parser_version = PARSER_VERSION
            imported.warning_count = item.parsed.warning_count
            imported.error_code = None
            imported.error_message = None
            imported.attempt_count += 1
            imported.last_attempt_at = now
            imported.completed_at = now
            imported.processing_token = None
            imported.replay_metadata = {
                **imported.replay_metadata,
                "source": "admin_reparse",
                "parser": PARSER_NAME,
                "parserVersion": PARSER_VERSION,
                "recordCount": len(item.parsed.records),
                "lapCount": len(item.parsed.laps),
                "segmentCount": len(item.parsed.segments),
            }
        db.commit()
        return _report(prepared, applied=True)
    except ActivityReparseError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise ActivityReparseError("reparse_failed", "FIT 完整重解析失败") from None
