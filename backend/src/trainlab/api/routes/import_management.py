import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from trainlab.api.dependencies import CsrfSession, CurrentSession, Database, RequestSettings
from trainlab.core.errors import ApiError
from trainlab.schemas.import_management import ImportListPage
from trainlab.schemas.system import ErrorResponse
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError
from trainlab.services.import_management import (
    DeleteTarget,
    ImportManagementError,
    delete_user_import,
    list_user_imports,
)

router = APIRouter(tags=["import-management"])
RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.get("/imports", response_model=ImportListPage, responses=RESPONSES)
def list_imports(
    current: CurrentSession,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ImportListPage:
    try:
        return list_user_imports(db, current.user.id, limit, cursor)
    except ImportManagementError as exc:
        raise ApiError(422, exc.code, exc.message) from None
    except Exception:
        raise ApiError(500, "import_list_unavailable", "导入记录暂时不可用") from None


def _delete(
    target: DeleteTarget,
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> Response:
    try:
        delete_user_import(
            db,
            PrivateActivityStorage(settings.private_storage_root),
            current.user.id,
            target,
            settings.import_processing_stale_minutes,
        )
    except ImportManagementError as exc:
        status = 409 if exc.code == "import_in_progress" else 503
        raise ApiError(status, exc.code, exc.message) from None
    except StorageError:
        raise ApiError(503, "delete_incomplete", "删除尚未完成，可稍后重试") from None
    except Exception:
        db.rollback()
        raise ApiError(503, "delete_incomplete", "删除尚未完成，可稍后重试") from None
    return Response(status_code=204)


@router.delete("/activities/{activity_id}", status_code=204, responses=RESPONSES)
def delete_activity(
    activity_id: uuid.UUID,
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> Response:
    return _delete(DeleteTarget(activity_id=activity_id), current, db, settings)


@router.delete("/imports/{import_id}", status_code=204, responses=RESPONSES)
def delete_import(
    import_id: uuid.UUID,
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> Response:
    return _delete(DeleteTarget(import_id=import_id), current, db, settings)
