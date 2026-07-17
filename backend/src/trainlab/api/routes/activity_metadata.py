import uuid
from typing import Any

from fastapi import APIRouter

from trainlab.api.dependencies import CsrfSession, Database
from trainlab.api.routes.activities import _list_item
from trainlab.core.errors import ApiError
from trainlab.schemas.activity import ActivityListItem
from trainlab.schemas.activity_metadata import ActivityNameUpdate
from trainlab.schemas.system import ErrorResponse
from trainlab.services.activity_metadata import ActivityMetadataError, update_activity_name

router = APIRouter(tags=["activity-metadata"])
RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.patch(
    "/activities/{activity_id}",
    response_model=ActivityListItem,
    responses=RESPONSES,
)
def rename_activity(
    activity_id: uuid.UUID,
    payload: ActivityNameUpdate,
    current: CsrfSession,
    db: Database,
) -> ActivityListItem:
    try:
        activity, imported = update_activity_name(db, current.user.id, activity_id, payload.name)
    except ActivityMetadataError as exc:
        status = 404 if exc.code == "not_found" else 422
        raise ApiError(status, exc.code, exc.message) from None
    except Exception:
        db.rollback()
        raise ApiError(500, "activity_update_unavailable", "运动名称暂时无法更新") from None
    return _list_item(activity, imported)
