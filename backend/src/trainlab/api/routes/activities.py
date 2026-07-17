import base64
import uuid
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select

from trainlab.api.dependencies import CsrfSession, CurrentSession, Database, RequestSettings
from trainlab.core.errors import ApiError
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
from trainlab.schemas.activity import (
    ActivityDetailResponse,
    ActivityDeviceResponse,
    ActivityLapResponse,
    ActivityListItem,
    ActivityListPage,
    ActivityMetricDefinitionResponse,
    ActivityRecordResponse,
    ActivitySegmentResponse,
    ActivitySessionResponse,
    ActivitySummaryResponse,
    FitImportResponse,
)
from trainlab.schemas.system import ErrorResponse
from trainlab.services.activity_import import (
    ImportInternalError,
    ImportResult,
    ImportStateError,
    register_fit_upload,
    replay_import,
)
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError

router = APIRouter(tags=["activities"])
ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
SOURCE_ERRORS = {**ERRORS, 410: {"model": ErrorResponse}}
UPLOAD_RESPONSES = {
    **ERRORS,
    200: {
        "model": FitImportResponse,
        "description": "Same user and SHA-256 already imported successfully",
    },
}
SOURCE_RESPONSES = {
    **SOURCE_ERRORS,
    200: {
        "description": "Owner-only original Garmin FIT file",
        "content": {"application/vnd.ant.fit": {"schema": {"type": "string", "format": "binary"}}},
    },
}
VALID_PROFILES = {"run", "hike", "strength", "lead", "boulder", "cycling", "generic"}


class PrivateFitStreamError(Exception):
    """Safe connection-abort signal for a late private-file read failure."""


def _activity_type(sport: str, sub_sport: str) -> str:
    sport_key = sport.lower()
    sub_key = sub_sport.lower()
    if sport_key == "running":
        return "越野跑" if "trail" in sub_key else "跑步"
    if sport_key == "cycling":
        return "骑行"
    if sport_key == "swimming":
        return "游泳"
    if sport_key in {"training", "strength_training", "fitness_equipment"}:
        return "力量"
    if sport_key in {"hiking", "walking", "mountaineering"}:
        return "徒步"
    if sport_key in {"rock_climbing", "climbing"}:
        return "抱石" if "boulder" in sub_key else "难度攀岩"
    return "其他"


def _pace(speed_mps: float | None, distance_m: float, duration_sec: float) -> int | None:
    speed = speed_mps
    if (speed is None or speed <= 0) and distance_m > 0 and duration_sec > 0:
        speed = distance_m / duration_sec
    return round(1000 / speed) if speed is not None and speed > 0 else None


def _list_item(activity: Activity, imported: ActivityImport) -> ActivityListItem:
    local_date = (
        activity.local_start_time.date()
        if activity.local_start_time is not None
        else activity.start_time_utc.date()
    )
    return ActivityListItem(
        id=activity.id,
        date=local_date.isoformat(),
        type=_activity_type(activity.sport, activity.sub_sport),
        name=activity.title,
        distance_km=(activity.total_distance_m / 1000 if activity.total_distance_m > 0 else None),
        duration_sec=round(activity.total_timer_time_sec),
        avg_hr=activity.avg_hr,
        pace_sec_per_km=(
            _pace(
                activity.avg_speed_mps,
                activity.total_distance_m,
                activity.total_timer_time_sec,
            )
            if activity.profile == "run"
            else None
        ),
        pace_100_sec=(
            round(100 / activity.avg_speed_mps)
            if activity.sport == "swimming"
            and activity.avg_speed_mps is not None
            and activity.avg_speed_mps > 0
            else None
        ),
        power_w=(
            round(activity.avg_power_w)
            if activity.profile == "cycling" and activity.avg_power_w is not None
            else None
        ),
        source="FIT上传",
        profile=activity.profile,
        parse_status=imported.status,
        original_file_name=imported.original_filename,
    )


def _encode_cursor(activity: Activity) -> str:
    payload = f"{activity.start_time_utc.isoformat()}|{activity.id}".encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, raw_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("cursor timestamp must include a UTC offset")
        return parsed.astimezone(UTC), uuid.UUID(raw_id)
    except (ValueError, UnicodeError) as exc:
        raise ApiError(422, "invalid_cursor", "分页游标无效") from exc


def _import_response(result: ImportResult) -> FitImportResponse:
    if result.model.status not in {"complete", "partial"} or result.activity is None:
        raise ApiError(500, "import_state_invalid", "FIT 导入结果状态异常")
    return FitImportResponse(
        import_id=result.model.id,
        status=result.model.status,
        deduplicated=result.deduplicated,
        activity=_list_item(result.activity, result.model),
        retry_available=result.model.status in {"failed", "partial"},
    )


def _raise_failed_import(result: ImportResult) -> None:
    if result.model.status != "failed":
        return
    raise ApiError(
        422,
        "fit_import_failed",
        "FIT 文件已保存，但解析失败，可稍后重试",
        {
            "importId": str(result.model.id),
            "status": result.model.status,
            "errorCode": result.model.error_code,
        },
    )


def _stream_private_fit(handle: BinaryIO, expected_size: int) -> Iterator[bytes]:
    remaining = expected_size
    try:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise PrivateFitStreamError("原始 FIT 文件读取中断")
            remaining -= len(chunk)
            yield chunk
    except PrivateFitStreamError:
        raise
    except Exception:
        # Headers may already be committed, so a late read error cannot become a
        # JSON 410. Abort with a context-free error so Content-Length makes the
        # incomplete transfer detectable without leaking a storage path.
        raise PrivateFitStreamError("原始 FIT 文件读取中断") from None
    finally:
        with suppress(Exception):
            handle.close()


@router.post(
    "/imports/fit",
    response_model=FitImportResponse,
    status_code=201,
    responses=UPLOAD_RESPONSES,
)
async def upload_fit(
    response: Response,
    file: Annotated[UploadFile, File(description="Garmin FIT activity file")],
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> FitImportResponse:
    try:
        storage = PrivateActivityStorage(settings.private_storage_root)
        result = await register_fit_upload(
            db,
            storage,
            file,
            current.user.id,
            settings.fit_upload_max_bytes,
            settings.import_processing_stale_minutes,
        )
    except StorageError as exc:
        status = 503 if exc.code == "private_storage_unavailable" else 415
        if exc.code == "fit_file_too_large":
            status = 413
        if exc.code in {"fit_file_empty", "invalid_storage_key"}:
            status = 422
        raise ApiError(status, exc.code, exc.message) from None
    except ImportStateError as exc:
        details = {"importId": str(exc.import_id)} if exc.import_id is not None else None
        raise ApiError(409, exc.code, exc.message, details) from None
    except ImportInternalError as exc:
        raise ApiError(500, exc.code, exc.message) from None
    except Exception:
        raise ApiError(500, "fit_import_unavailable", "FIT 导入暂时不可用") from None
    _raise_failed_import(result)
    response.status_code = 200 if result.deduplicated else 201
    return _import_response(result)


@router.post(
    "/imports/{import_id}/retry",
    response_model=FitImportResponse,
    responses=ERRORS,
)
def retry_fit_import(
    import_id: uuid.UUID,
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> FitImportResponse:
    try:
        model = db.scalar(
            select(ActivityImport).where(
                ActivityImport.id == import_id,
                ActivityImport.user_id == current.user.id,
            )
        )
    except Exception:
        raise ApiError(500, "import_state_unavailable", "FIT 导入状态暂时不可用") from None
    if model is None:
        raise ApiError(404, "import_not_found", "导入记录不存在")
    try:
        result = replay_import(
            db,
            PrivateActivityStorage(settings.private_storage_root),
            model,
            settings.import_processing_stale_minutes,
        )
    except ImportStateError as exc:
        details = {"importId": str(exc.import_id)} if exc.import_id is not None else None
        raise ApiError(409, exc.code, exc.message, details) from None
    except StorageError as exc:
        status = 503 if exc.code == "private_storage_unavailable" else 422
        raise ApiError(status, exc.code, exc.message) from None
    except ImportInternalError as exc:
        raise ApiError(500, exc.code, exc.message) from None
    except Exception:
        raise ApiError(500, "fit_import_unavailable", "FIT 导入暂时不可用") from None
    _raise_failed_import(result)
    return _import_response(result)


@router.get("/activities", response_model=ActivityListPage, responses=ERRORS)
def list_activities(
    current: CurrentSession,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    profile: Annotated[str | None, Query()] = None,
) -> ActivityListPage:
    query = (
        select(Activity, ActivityImport)
        .join(ActivityImport, ActivityImport.id == Activity.source_import_id)
        .where(
            Activity.user_id == current.user.id,
            ActivityImport.user_id == current.user.id,
            ActivityImport.status.in_(("complete", "partial")),
        )
    )
    if profile is not None:
        if profile not in VALID_PROFILES:
            raise ApiError(422, "invalid_profile", "运动类型筛选无效")
        query = query.where(Activity.profile == profile)
    if cursor is not None:
        cursor_time, cursor_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                Activity.start_time_utc < cursor_time,
                and_(Activity.start_time_utc == cursor_time, Activity.id < cursor_id),
            )
        )
    rows = db.execute(
        query.order_by(Activity.start_time_utc.desc(), Activity.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    visible = rows[:limit]
    return ActivityListPage(
        items=[_list_item(activity, imported) for activity, imported in visible],
        next_cursor=_encode_cursor(visible[-1][0]) if has_more and visible else None,
    )


def _owned_activity(
    db: Database, user_id: uuid.UUID, activity_id: uuid.UUID
) -> tuple[Activity, ActivityImport]:
    row = db.execute(
        select(Activity, ActivityImport)
        .join(ActivityImport, ActivityImport.id == Activity.source_import_id)
        .where(
            Activity.id == activity_id,
            Activity.user_id == user_id,
            ActivityImport.user_id == user_id,
            ActivityImport.status.in_(("complete", "partial")),
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "activity_not_found", "运动记录不存在")
    return row[0], row[1]


@router.get(
    "/activities/{activity_id}",
    response_model=ActivityDetailResponse,
    responses=ERRORS,
)
def activity_detail(
    activity_id: uuid.UUID,
    current: CurrentSession,
    db: Database,
    settings: RequestSettings,
    record_limit: Annotated[int, Query(alias="recordLimit", ge=100, le=5000)] = 2000,
) -> ActivityDetailResponse:
    activity, imported = _owned_activity(db, current.user.id, activity_id)
    record_count = (
        db.scalar(
            select(func.count(ActivityRecord.id)).where(
                ActivityRecord.activity_id == activity.id,
                ActivityRecord.user_id == current.user.id,
            )
        )
        or 0
    )
    step = max(1, (record_count + record_limit - 1) // record_limit)
    records = db.scalars(
        select(ActivityRecord)
        .where(
            ActivityRecord.activity_id == activity.id,
            ActivityRecord.user_id == current.user.id,
            ActivityRecord.sequence % step == 0,
        )
        .order_by(ActivityRecord.sequence)
        .limit(record_limit)
    ).all()
    sessions = db.scalars(
        select(ActivitySession)
        .where(
            ActivitySession.activity_id == activity.id,
            ActivitySession.user_id == current.user.id,
        )
        .order_by(ActivitySession.message_index)
    ).all()
    laps = db.scalars(
        select(ActivityLap)
        .where(
            ActivityLap.activity_id == activity.id,
            ActivityLap.user_id == current.user.id,
        )
        .order_by(ActivityLap.message_index)
    ).all()
    segments = db.scalars(
        select(ActivitySegment)
        .where(
            ActivitySegment.activity_id == activity.id,
            ActivitySegment.user_id == current.user.id,
        )
        .order_by(ActivitySegment.sequence)
    ).all()
    devices = db.scalars(
        select(ActivityDevice)
        .where(
            ActivityDevice.activity_id == activity.id,
            ActivityDevice.user_id == current.user.id,
        )
        .order_by(ActivityDevice.message_index)
    ).all()
    definitions = db.scalars(
        select(ActivityMetricDefinition)
        .where(
            ActivityMetricDefinition.activity_id == activity.id,
            ActivityMetricDefinition.user_id == current.user.id,
        )
        .order_by(ActivityMetricDefinition.stable_key)
    ).all()
    try:
        source = PrivateActivityStorage(settings.private_storage_root).open_for_read(
            imported.storage_key, current.user.id
        )
        source.handle.close()
        download_available = True
    except StorageError:
        download_available = False
    return ActivityDetailResponse(
        activity=_list_item(activity, imported),
        summary=ActivitySummaryResponse(
            sport=activity.sport,
            sub_sport=activity.sub_sport,
            start_time=activity.start_time_utc,
            local_start_time=activity.local_start_time,
            utc_offset_minutes=activity.utc_offset_minutes,
            total_timer_time_sec=activity.total_timer_time_sec,
            total_elapsed_time_sec=activity.total_elapsed_time_sec,
            total_distance_m=activity.total_distance_m,
            avg_hr=activity.avg_hr,
            max_hr=activity.max_hr,
            total_calories=activity.total_calories,
            avg_power_w=activity.avg_power_w,
            max_power_w=activity.max_power_w,
            normalized_power_w=activity.normalized_power_w,
            total_ascent_m=activity.total_ascent_m,
            total_descent_m=activity.total_descent_m,
            avg_speed_mps=activity.avg_speed_mps,
            max_speed_mps=activity.max_speed_mps,
            avg_cadence_spm=activity.avg_cadence_spm,
            total_training_effect=activity.total_training_effect,
            total_anaerobic_training_effect=activity.total_anaerobic_training_effect,
            avg_temperature_c=activity.avg_temperature_c,
            max_temperature_c=activity.max_temperature_c,
            min_temperature_c=activity.min_temperature_c,
            avg_gct_ms=activity.avg_gct_ms,
            avg_vert_osc_mm=activity.avg_vert_osc_mm,
            avg_vertical_ratio=activity.avg_vertical_ratio,
            avg_step_length_mm=activity.avg_step_length_mm,
            workout_feel=activity.workout_feel,
            workout_rpe=activity.workout_rpe,
            extra_metrics=activity.extra_metrics,
        ),
        sessions=[
            ActivitySessionResponse(
                message_index=item.message_index,
                sport=item.sport,
                sub_sport=item.sub_sport,
                start_time=item.start_time_utc,
            )
            for item in sessions
        ],
        records=[
            ActivityRecordResponse(
                sequence=item.sequence,
                timestamp=item.timestamp,
                t_sec=item.elapsed_sec,
                distance_m=item.distance_m,
                speed_mps=item.speed_mps,
                pace_sec_per_km=(
                    1000 / item.speed_mps
                    if item.speed_mps is not None and item.speed_mps > 0
                    else None
                ),
                hr=item.heart_rate,
                power_w=item.power_w,
                cadence_spm=item.cadence_spm,
                altitude_m=item.altitude_m,
                temperature_c=item.temperature_c,
                gct_ms=item.stance_time_ms,
                vert_osc_mm=item.vertical_oscillation_mm,
                position_lat=item.position_lat,
                position_long=item.position_long,
                extra_metrics=item.extra_metrics,
            )
            for item in records
        ],
        record_count=record_count,
        records_sampled=record_count > len(records),
        laps=[
            ActivityLapResponse(
                index=item.message_index,
                start_time=item.start_time_utc,
                distance_m=item.distance_m,
                duration_sec=item.duration_sec,
                avg_hr=item.avg_hr,
                max_hr=item.max_hr,
                avg_pace_sec_per_km=(
                    1000 / item.avg_speed_mps
                    if item.avg_speed_mps is not None and item.avg_speed_mps > 0
                    else None
                ),
                avg_power_w=item.avg_power_w,
                extra_metrics=item.extra_metrics,
            )
            for item in laps
        ],
        segments=[
            ActivitySegmentResponse(
                sequence=item.sequence,
                kind=item.kind,
                label=item.label,
                start_time=item.start_time_utc,
                duration_sec=item.duration_sec,
                repetitions=item.repetitions,
                weight_kg=item.weight_kg,
                extra_data=item.extra_data,
            )
            for item in segments
        ],
        devices=[
            ActivityDeviceResponse(
                id=item.id,
                role=item.device_role,
                manufacturer=item.manufacturer,
                product=item.product,
                display_name=item.display_name,
                transport=item.transport,
                source_type=item.source_type,
                software_version=item.software_version,
                battery_status=item.battery_status,
            )
            for item in devices
        ],
        metric_definitions=[
            ActivityMetricDefinitionResponse(
                id=item.id,
                device_id=item.device_id,
                stable_key=item.stable_key,
                message_name=item.message_name,
                field_name=item.field_name,
                unit=item.unit,
                value_type=item.value_type,
                native_message_number=item.native_message_number,
                developer_data_index=item.developer_data_index,
                field_definition_number=item.field_definition_number,
            )
            for item in definitions
        ],
        parse_status=imported.status,
        warning_count=imported.warning_count,
        download_available=download_available,
        original_file_name=imported.original_filename,
    )


@router.get(
    "/activities/{activity_id}/source",
    response_class=StreamingResponse,
    responses=SOURCE_RESPONSES,
)
def download_activity_source(
    activity_id: uuid.UUID,
    current: CurrentSession,
    db: Database,
    settings: RequestSettings,
) -> StreamingResponse:
    _, imported = _owned_activity(db, current.user.id, activity_id)
    try:
        opened = PrivateActivityStorage(settings.private_storage_root).open_for_read(
            imported.storage_key, current.user.id
        )
    except StorageError as exc:
        if exc.code == "private_storage_unavailable":
            raise ApiError(503, exc.code, exc.message) from None
        raise ApiError(410, "raw_file_unavailable", "原始 FIT 文件不可用") from None
    encoded_filename = quote(imported.original_filename, safe="")
    return StreamingResponse(
        _stream_private_fit(opened.handle, opened.size_bytes),
        media_type="application/vnd.ant.fit",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}",
            "Content-Length": str(opened.size_bytes),
        },
    )
