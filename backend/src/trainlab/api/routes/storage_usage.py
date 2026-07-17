from typing import Any

from fastapi import APIRouter

from trainlab.api.dependencies import CurrentSession, Database, RequestSettings
from trainlab.core.errors import ApiError
from trainlab.schemas.storage_usage import StorageUsageResponse
from trainlab.schemas.system import ErrorResponse
from trainlab.services.storage_usage import storage_usage

router = APIRouter(tags=["storage"])
RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.get("/storage/usage", response_model=StorageUsageResponse, responses=RESPONSES)
def get_storage_usage(
    current: CurrentSession,
    db: Database,
    settings: RequestSettings,
) -> StorageUsageResponse:
    try:
        return storage_usage(
            db,
            current.user.id,
            settings.user_storage_max_bytes,
            settings.user_storage_max_files,
        )
    except Exception:
        raise ApiError(500, "storage_usage_unavailable", "存储用量暂时不可用") from None
