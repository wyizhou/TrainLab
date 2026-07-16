from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trainlab.core.errors import ApiError


def install_frontend(app: FastAPI, frontend_dist: Path) -> None:
    index_file = frontend_dist / "index.html"
    assets_dir = frontend_dist / "assets"

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def spa_fallback(request: Request, path: str) -> FileResponse:
        if request.method != "GET" or path.startswith("api/") or path.startswith("assets/"):
            raise ApiError(404, "not_found", "资源不存在")
        requested = frontend_dist / path
        if path and requested.is_file() and frontend_dist in requested.resolve().parents:
            return FileResponse(requested)
        if not index_file.is_file():
            raise ApiError(404, "frontend_not_built", "前端尚未构建")
        return FileResponse(index_file)
