import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trainlab.db.base import utc_now
from trainlab.db.models.activity import (
    Activity,
    ActivityDevice,
    ActivityImport,
    ActivityLap,
    ActivityMetricDefinition,
    ActivityRecord,
    ActivitySegment,
    ActivitySession,
)
from trainlab.importers.fit import (
    PARSER_NAME,
    PARSER_VERSION,
    FitDecodeFailure,
    ParsedFitActivity,
    parse_fit_file,
)
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError


@dataclass(frozen=True)
class ImportResult:
    model: ActivityImport
    activity: Activity | None
    deduplicated: bool


class ImportStateError(Exception):
    def __init__(self, code: str, message: str, import_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.import_id = import_id


class ImportInternalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_rollback(db: Session) -> None:
    with suppress(Exception):
        db.rollback()


def _safe_remove(storage: PrivateActivityStorage, storage_key: str, user_id: uuid.UUID) -> None:
    with suppress(StorageError):
        storage.remove(storage_key, user_id)


def safe_original_filename(filename: str | None) -> str:
    normalized = (filename or "activity.fit").replace("\\", "/")
    name = PurePosixPath(normalized).name.strip()
    return (name or "activity.fit")[:255]


def validate_fit_upload(filename: str | None, content_type: str | None) -> str:
    safe_name = safe_original_filename(filename)
    if not safe_name.lower().endswith(".fit"):
        raise StorageError("fit_format_required", "本轮仅支持 FIT 文件")
    if content_type and content_type.lower() not in {
        "application/octet-stream",
        "application/vnd.ant.fit",
        "application/fit",
        "binary/octet-stream",
    }:
        raise StorageError("fit_content_type_invalid", "文件内容类型不是 FIT")
    return safe_name


def _activity_for_import(db: Session, user_id: uuid.UUID, import_id: uuid.UUID) -> Activity | None:
    return db.scalar(
        select(Activity).where(
            Activity.user_id == user_id,
            Activity.source_import_id == import_id,
        )
    )


def _deduplicated_result(
    db: Session,
    storage: PrivateActivityStorage,
    user_id: uuid.UUID,
    imported: ActivityImport,
    stale_minutes: int,
) -> ImportResult:
    activity = _activity_for_import(db, user_id, imported.id)
    if imported.status in {"pending", "processing"}:
        replayed = replay_import(db, storage, imported, stale_minutes)
        return ImportResult(
            model=replayed.model,
            activity=replayed.activity,
            deduplicated=True,
        )
    if imported.status == "failed":
        return ImportResult(model=imported, activity=None, deduplicated=True)
    if imported.status not in {"complete", "partial"} or activity is None:
        raise ImportStateError(
            "import_state_invalid",
            "已有 FIT 导入记录状态异常，无法复用",
            imported.id,
        )
    return ImportResult(model=imported, activity=activity, deduplicated=True)


def _replace_activity(
    db: Session,
    import_model: ActivityImport,
    parsed: ParsedFitActivity,
) -> Activity:
    existing = _activity_for_import(db, import_model.user_id, import_model.id)
    if existing is not None:
        db.delete(existing)
        db.flush()

    activity = Activity(
        user_id=import_model.user_id,
        source_import_id=import_model.id,
        title=parsed.title,
        sport=parsed.sport,
        sub_sport=parsed.sub_sport,
        profile=parsed.profile,
        start_time_utc=parsed.start_time_utc,
        local_start_time=parsed.local_start_time,
        utc_offset_minutes=parsed.utc_offset_minutes,
        total_timer_time_sec=parsed.total_timer_time_sec,
        total_elapsed_time_sec=parsed.total_elapsed_time_sec,
        total_distance_m=parsed.total_distance_m,
        avg_hr=parsed.avg_hr,
        max_hr=parsed.max_hr,
        total_calories=parsed.total_calories,
        avg_power_w=parsed.avg_power_w,
        max_power_w=parsed.max_power_w,
        normalized_power_w=parsed.normalized_power_w,
        total_ascent_m=parsed.total_ascent_m,
        total_descent_m=parsed.total_descent_m,
        avg_speed_mps=parsed.avg_speed_mps,
        max_speed_mps=parsed.max_speed_mps,
        avg_cadence_spm=parsed.avg_cadence_spm,
        total_training_effect=parsed.total_training_effect,
        total_anaerobic_training_effect=parsed.total_anaerobic_training_effect,
        avg_temperature_c=parsed.avg_temperature_c,
        max_temperature_c=parsed.max_temperature_c,
        min_temperature_c=parsed.min_temperature_c,
        avg_gct_ms=parsed.avg_gct_ms,
        avg_vert_osc_mm=parsed.avg_vert_osc_mm,
        avg_vertical_ratio=parsed.avg_vertical_ratio,
        avg_step_length_mm=parsed.avg_step_length_mm,
        workout_feel=parsed.workout_feel,
        workout_rpe=parsed.workout_rpe,
        extra_metrics=parsed.extra_metrics,
    )
    db.add(activity)
    db.flush()

    db.add_all(
        [
            ActivitySession(
                user_id=import_model.user_id,
                activity_id=activity.id,
                message_index=item.message_index,
                sport=item.sport,
                sub_sport=item.sub_sport,
                start_time_utc=item.start_time_utc,
                summary=item.summary,
            )
            for item in parsed.sessions
        ]
    )
    db.add_all(
        [
            ActivityRecord(
                user_id=import_model.user_id,
                activity_id=activity.id,
                sequence=item.sequence,
                timestamp=item.timestamp,
                elapsed_sec=item.elapsed_sec,
                distance_m=item.distance_m,
                speed_mps=item.speed_mps,
                heart_rate=item.heart_rate,
                power_w=item.power_w,
                cadence_spm=item.cadence_spm,
                altitude_m=item.altitude_m,
                temperature_c=item.temperature_c,
                stance_time_ms=item.stance_time_ms,
                vertical_oscillation_mm=item.vertical_oscillation_mm,
                position_lat=item.position_lat,
                position_long=item.position_long,
                extra_metrics=item.extra_metrics,
            )
            for item in parsed.records
        ]
    )
    db.add_all(
        [
            ActivityLap(
                user_id=import_model.user_id,
                activity_id=activity.id,
                message_index=item.message_index,
                start_time_utc=item.start_time_utc,
                duration_sec=item.duration_sec,
                distance_m=item.distance_m,
                avg_hr=item.avg_hr,
                max_hr=item.max_hr,
                avg_power_w=item.avg_power_w,
                avg_speed_mps=item.avg_speed_mps,
                extra_metrics=item.extra_metrics,
            )
            for item in parsed.laps
        ]
    )
    db.add_all(
        [
            ActivitySegment(
                user_id=import_model.user_id,
                activity_id=activity.id,
                sequence=item.sequence,
                kind=item.kind,
                label=item.label,
                start_time_utc=item.start_time_utc,
                duration_sec=item.duration_sec,
                repetitions=item.repetitions,
                weight_kg=item.weight_kg,
                extra_data=item.extra_data,
            )
            for item in parsed.segments
        ]
    )
    device_models = [
        ActivityDevice(
            user_id=import_model.user_id,
            activity_id=activity.id,
            message_index=item.message_index,
            device_role=item.device_role,
            manufacturer=item.manufacturer,
            product=item.product,
            display_name=item.display_name,
            transport=item.transport,
            source_type=item.source_type,
            software_version=item.software_version,
            battery_status=item.battery_status,
            serial_number_hash=item.serial_number_hash,
            raw_metadata=item.raw_metadata,
        )
        for item in parsed.devices
    ]
    db.add_all(device_models)
    db.flush()
    # FIT presence alone does not prove which device produced a metric. Keep
    # device_id null until a future decoder can demonstrate that association.
    db.add_all(
        [
            ActivityMetricDefinition(
                user_id=import_model.user_id,
                activity_id=activity.id,
                device_id=None,
                stable_key=item.stable_key,
                message_name=item.message_name,
                field_name=item.field_name,
                unit=item.unit,
                value_type=item.value_type,
                native_message_number=item.native_message_number,
                developer_data_index=item.developer_data_index,
                field_definition_number=item.field_definition_number,
                application_id_hash=item.application_id_hash,
            )
            for item in parsed.metric_definitions
        ]
    )
    return activity


def _mark_import_failed(
    db: Session,
    import_model: ActivityImport,
    error_code: str,
    error_message: str,
    *,
    warning_count: int | None = None,
) -> ActivityImport:
    db.refresh(import_model)
    previous_activity = _activity_for_import(db, import_model.user_id, import_model.id)
    if previous_activity is not None:
        db.delete(previous_activity)
    import_model.status = "failed"
    import_model.error_code = error_code
    import_model.error_message = error_message
    import_model.completed_at = None
    if warning_count is not None:
        import_model.warning_count = warning_count
    db.commit()
    db.refresh(import_model)
    return import_model


def _mark_import_failed_safely(
    db: Session,
    import_model: ActivityImport,
    error_code: str,
    error_message: str,
    *,
    warning_count: int | None = None,
) -> ActivityImport:
    try:
        return _mark_import_failed(
            db,
            import_model,
            error_code,
            error_message,
            warning_count=warning_count,
        )
    except Exception:
        _safe_rollback(db)
        raise ImportInternalError(
            "import_state_persistence_failed", "FIT 导入状态无法保存"
        ) from None


def replay_import(
    db: Session,
    storage: PrivateActivityStorage,
    import_model: ActivityImport,
    stale_minutes: int,
) -> ImportResult:
    try:
        locked = db.scalar(
            select(ActivityImport)
            .where(
                ActivityImport.id == import_model.id,
                ActivityImport.user_id == import_model.user_id,
            )
            .with_for_update()
        )
    except Exception:
        _safe_rollback(db)
        raise ImportInternalError("import_state_unavailable", "FIT 导入状态暂时不可用") from None
    if locked is None:
        raise ImportStateError("import_not_found", "导入记录不存在")
    now = utc_now()
    if locked.status == "processing":
        stale_before = now - timedelta(minutes=stale_minutes)
        if locked.last_attempt_at is None or locked.last_attempt_at > stale_before:
            _safe_rollback(db)
            raise ImportStateError("import_in_progress", "FIT 导入仍在处理中", locked.id)
    elif locked.status not in {"pending", "failed", "partial"}:
        _safe_rollback(db)
        raise ImportStateError("import_not_retryable", "当前导入状态不允许重试", locked.id)
    locked.status = "processing"
    locked.attempt_count += 1
    locked.last_attempt_at = now
    locked.error_code = None
    locked.error_message = None
    try:
        db.commit()
    except Exception:
        _safe_rollback(db)
        raise ImportInternalError(
            "import_state_persistence_failed", "FIT 导入状态无法保存"
        ) from None
    import_model = locked
    try:
        opened = storage.open_for_read(import_model.storage_key, import_model.user_id)
    except StorageError:
        import_model = _mark_import_failed_safely(
            db,
            import_model,
            "raw_file_unavailable",
            "原始 FIT 文件不可用",
        )
        return ImportResult(model=import_model, activity=None, deduplicated=False)
    try:
        parsed = parse_fit_file(opened.handle, import_model.original_filename)
    except FitDecodeFailure as exc:
        import_model = _mark_import_failed_safely(
            db,
            import_model,
            exc.code,
            exc.message,
            warning_count=0,
        )
        return ImportResult(model=import_model, activity=None, deduplicated=False)
    except Exception:
        _mark_import_failed_safely(
            db,
            import_model,
            "fit_parse_failed",
            "FIT 解析器发生内部错误",
            warning_count=0,
        )
        raise ImportInternalError("fit_parse_failed", "FIT 解析暂时失败") from None
    finally:
        with suppress(Exception):
            opened.handle.close()

    try:
        db.refresh(import_model)
        activity = _replace_activity(db, import_model, parsed)
        import_model.status = parsed.status
        import_model.warning_count = parsed.warning_count
        import_model.error_code = None
        import_model.error_message = None
        import_model.completed_at = utc_now()
        import_model.replay_metadata = {
            "parser": PARSER_NAME,
            "parserVersion": PARSER_VERSION,
            "recordCount": len(parsed.records),
            "lapCount": len(parsed.laps),
            "segmentCount": len(parsed.segments),
        }
        db.commit()
        db.refresh(import_model)
        db.refresh(activity)
        return ImportResult(model=import_model, activity=activity, deduplicated=False)
    except Exception:
        _safe_rollback(db)
        try:
            failed = db.get(ActivityImport, import_model.id)
            if failed is not None:
                _mark_import_failed_safely(
                    db,
                    failed,
                    "fit_persistence_failed",
                    "FIT 解析结果无法保存",
                )
        except ImportInternalError:
            raise
        except Exception:
            _safe_rollback(db)
            raise ImportInternalError(
                "import_state_persistence_failed", "FIT 导入状态无法保存"
            ) from None
        raise ImportInternalError("fit_persistence_failed", "FIT 解析结果无法保存") from None


async def register_fit_upload(
    db: Session,
    storage: PrivateActivityStorage,
    upload: UploadFile,
    user_id: uuid.UUID,
    max_bytes: int,
    stale_minutes: int,
) -> ImportResult:
    filename = validate_fit_upload(upload.filename, upload.content_type)
    import_id = uuid.uuid4()
    staged = await storage.stage(upload, user_id, import_id, max_bytes)
    try:
        existing = db.scalar(
            select(ActivityImport).where(
                ActivityImport.user_id == user_id,
                ActivityImport.sha256 == staged.sha256,
            )
        )
    except Exception:
        _safe_rollback(db)
        _safe_remove(storage, staged.storage_key, user_id)
        raise ImportInternalError("import_registration_failed", "FIT 导入登记失败") from None
    if existing is not None:
        _safe_remove(storage, staged.storage_key, user_id)
        try:
            return _deduplicated_result(db, storage, user_id, existing, stale_minutes)
        except (ImportInternalError, ImportStateError, StorageError):
            raise
        except Exception:
            _safe_rollback(db)
            raise ImportInternalError(
                "import_state_unavailable", "FIT 导入状态暂时不可用"
            ) from None

    model = ActivityImport(
        id=import_id,
        user_id=user_id,
        source="fit_upload",
        original_filename=filename,
        content_type=upload.content_type,
        size_bytes=staged.size_bytes,
        sha256=staged.sha256,
        storage_key=staged.storage_key,
        status="pending",
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        attempt_count=0,
        warning_count=0,
        replay_metadata={"source": "fit_upload"},
    )
    db.add(model)
    try:
        db.commit()
    except IntegrityError:
        _safe_rollback(db)
        _safe_remove(storage, staged.storage_key, user_id)
        try:
            duplicate = db.scalar(
                select(ActivityImport).where(
                    ActivityImport.user_id == user_id,
                    ActivityImport.sha256 == staged.sha256,
                )
            )
        except Exception:
            raise ImportInternalError("import_registration_failed", "FIT 导入登记失败") from None
        if duplicate is None:
            raise ImportInternalError("import_registration_failed", "FIT 导入登记失败") from None
        try:
            return _deduplicated_result(db, storage, user_id, duplicate, stale_minutes)
        except (ImportInternalError, ImportStateError, StorageError):
            raise
        except Exception:
            _safe_rollback(db)
            raise ImportInternalError(
                "import_state_unavailable", "FIT 导入状态暂时不可用"
            ) from None
    except Exception:
        _safe_rollback(db)
        _safe_remove(storage, staged.storage_key, user_id)
        raise ImportInternalError("import_registration_failed", "FIT 导入登记失败") from None
    db.refresh(model)
    return replay_import(db, storage, model, stale_minutes)
