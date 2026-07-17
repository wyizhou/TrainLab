import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trainlab.core.errors import ApiError
from trainlab.db.migrations import migration_head
from trainlab.schemas.system import StatusResponse

router = APIRouter(tags=["system"])


def _private_storage_ready(root: Path) -> bool:
    """Prove that the configured root is a real, writable directory without leaking it."""
    directory_fd: int | None = None
    probe_fd: int | None = None
    probe_name = f".trainlab-readiness-{secrets.token_hex(16)}"
    created = False
    cleanup_ok = True
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(root, directory_flags)
        probe_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        probe_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        probe_fd = os.open(probe_name, probe_flags, 0o600, dir_fd=directory_fd)
        created = True
        # Unlink before writing so even a process crash cannot leave a
        # permanent readiness file behind.
        os.unlink(probe_name, dir_fd=directory_fd)
        created = False
        os.write(probe_fd, b"ready")
        os.fsync(probe_fd)
    except OSError:
        return False
    finally:
        if probe_fd is not None:
            try:
                os.close(probe_fd)
            except OSError:
                cleanup_ok = False
        if created and directory_fd is not None:
            try:
                os.unlink(probe_name, dir_fd=directory_fd)
            except OSError:
                cleanup_ok = False
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                cleanup_ok = False
    return cleanup_ok


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
    if version != migration_head():
        raise ApiError(503, "migration_pending", "数据库迁移尚未完成")
    if not _private_storage_ready(request.app.state.settings.private_storage_root):
        raise ApiError(503, "private_storage_not_ready", "私有文件存储尚未就绪")
    return StatusResponse(status="ready")
