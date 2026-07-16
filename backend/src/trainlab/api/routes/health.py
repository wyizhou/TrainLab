from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trainlab.core.errors import ApiError
from trainlab.schemas.system import StatusResponse

router = APIRouter(tags=["system"])
MIGRATION_HEAD = "0001_backend_foundation"


@router.get("/healthz", response_model=StatusResponse)
def health() -> StatusResponse:
    return StatusResponse(status="ok")


@router.get("/readyz", response_model=StatusResponse)
def ready(request: Request) -> StatusResponse:
    try:
        with Session(request.app.state.engine) as db:
            db.execute(text("SELECT 1"))
            version = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    except (SQLAlchemyError, LookupError):
        raise ApiError(503, "not_ready", "服务尚未就绪") from None
    if version != MIGRATION_HEAD:
        raise ApiError(503, "migration_pending", "数据库迁移尚未完成")
    return StatusResponse(status="ready")
