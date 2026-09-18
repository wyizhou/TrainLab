"""FastAPI application factory for the ADHOC-0031 local web/API app."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from trainlab.ai import AIConfig, AIProtocolError, CompatibleAIClient, ToolDispatcher
from trainlab.context import ContextError
from trainlab.contracts.errors import (
    ErrorCode,
    failure_envelope,
    http_status_for_error,
    success_envelope,
)
from trainlab.contracts.interfaces import CapacityPolicy, ReferenceId, ToolAuthorization
from trainlab.contracts.paths import DATA_DB_PATH
from trainlab.contracts.session import InMemoryConversationHistory
from trainlab.contracts.time import UTC_TIMESTAMP_FORMAT
from trainlab.contracts.web import (
    API_ROUTES,
    DEFAULT_PORT,
    LOCAL_HOST,
    route_paths,
    static_mount_dir,
)
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_sync import GarminSyncError, GarminSyncState, load_sync_state, should_run_sync
from trainlab.local_web.auth_routes import register_auth_routes
from trainlab.local_web.auth_runtime import AuthRuntime
from trainlab.local_web.auth_security import PREFIX, LocalSecurity, error_response
from trainlab.report_service import ReportGenerationError, ReportService
from trainlab.reports import ReportStorageError, get_activity_report, get_weekly_report

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
DEFAULT_WEEKLY_LIMIT = 10
_OPTIONAL_JSON_BODY = Body(default=None)


class WebAppSettings:
    """Explicit local app wiring; AI generation stays disabled unless tests/caller inject fakes."""

    def __init__(
        self,
        *,
        instance_root: Path | None = None,
        project_root: Path | None = None,
        db_relative_path: Path = DATA_DB_PATH,
        ai_client: CompatibleAIClient | None = None,
        ai_config: AIConfig | None = None,
        capacity: CapacityPolicy | None = None,
        auth_maintenance: bool = True,
        auth_runtime_factory: Callable[[Path], AuthRuntime] | None = None,
    ) -> None:
        self.instance_root = Path.cwd() if instance_root is None else instance_root
        self.project_root = Path.cwd() if project_root is None else project_root
        self.db_relative_path = db_relative_path
        self.ai_client = ai_client
        self.ai_config = ai_config
        self.capacity = capacity
        self.auth_maintenance = auth_maintenance
        self.auth_runtime_factory = auth_runtime_factory

    @property
    def db_path(self) -> Path:
        return _inside_root(self.instance_root, self.db_relative_path)


def app_contract() -> dict[str, Any]:
    return {
        "host": LOCAL_HOST,
        "port": DEFAULT_PORT,
        "static_dir": static_mount_dir().as_posix(),
        "routes": [route.__dict__ for route in API_ROUTES],
        "starts_background_jobs_on_create": False,
        "background_jobs_on_lifespan": ["garmin_auth_maintenance"],
        "reads_private_state_on_import": False,
    }


def create_app(settings: WebAppSettings | None = None) -> FastAPI:
    config = WebAppSettings() if settings is None else settings
    static_dir = (config.project_root / static_mount_dir()).resolve(strict=False)
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = (config.auth_runtime_factory(config.instance_root) if config.auth_runtime_factory
                   else AuthRuntime(GarminAuthService(config.instance_root), enabled=config.auth_maintenance))
        app.state.auth = runtime
        try:
            await runtime.start()
            yield
        finally:
            await runtime.stop()
            app.state.auth = None

    app = FastAPI(title="TrainLab Local Web", version="0.1.0", lifespan=lifespan)
    app.add_middleware(LocalSecurity)
    register_auth_routes(app)
    history = InMemoryConversationHistory()

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if request.url.path.startswith(PREFIX):
            return error_response(ErrorCode.INVALID_ARGUMENT, "invalid_request", exc.status_code)
        if request.url.path.startswith("/api/"):
            code = ErrorCode.ACTIVITY_NOT_FOUND if exc.status_code == 404 else ErrorCode.INVALID_ARGUMENT
            message = "not found" if exc.status_code == 404 else str(exc.detail)
            return _error_response(code, message, status_code=exc.status_code)
        return _error_response(ErrorCode.ACTIVITY_NOT_FOUND, "not found", status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _error_response(ErrorCode.INVALID_ARGUMENT, "request parameters are invalid")

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        if _request.url.path.startswith(PREFIX):
            return error_response(ErrorCode.INVALID_ARGUMENT, "invalid_request", 400)
        return _error_response(ErrorCode.INVALID_ARGUMENT, str(exc))

    @app.get("/api/health")
    def health() -> Any:
        db_path = config.db_path
        return success_envelope(
            {
                "service": "trainlab-local-web",
                "local_only": True,
                "starts_background_jobs": bool(getattr(app.state, "auth", None) and app.state.auth.enabled),
                "auth_maintenance_enabled": bool(getattr(app.state, "auth", None) and app.state.auth.enabled),
                "auth_maintenance_state": app.state.auth.maintenance["state"] if getattr(app.state, "auth", None) else "not_started",
                "ai_background_jobs": False,
                "sync_background_jobs": False,
                "reads_private_state_on_import": False,
                "ai_generation_configured": _ai_configured(config),
                "database": {"relative_path": config.db_relative_path.as_posix(), "exists": db_path.exists()},
                "routes": [route.__dict__ for route in API_ROUTES],
            }
        ).to_json()

    @app.get("/api/status")
    def status() -> Any:
        db_path = config.db_path
        try:
            sync_state = load_sync_state(config.instance_root)
        except GarminSyncError as exc:
            return _error_response(exc.code, exc.message)
        return success_envelope(
            {
                "service": "trainlab-local-web",
                "local_only": True,
                "available_routes": list(route_paths()),
                "database": {"relative_path": config.db_relative_path.as_posix(), "exists": db_path.exists()},
                "sync": _sync_state_json(sync_state, datetime.now(UTC)),
                "ai_generation_configured": _ai_configured(config),
            }
        ).to_json()

    @app.get("/api/sync/status")
    def sync_status() -> Any:
        try:
            state = load_sync_state(config.instance_root)
        except GarminSyncError as exc:
            return _error_response(exc.code, exc.message)
        return success_envelope(_sync_state_json(state, datetime.now(UTC))).to_json()

    @app.get("/api/activities")
    def list_activities(
        q: str | None = Query(default=None),
        sport: str | None = Query(default=None),
        has_report: bool | None = Query(default=None),
        limit: int = Query(default=DEFAULT_LIMIT),
        offset: int = Query(default=0),
    ) -> Any:
        args_error = _validate_pagination(limit, offset)
        if args_error is not None:
            return args_error
        if q is not None and len(q) > 200:
            return _error_response(ErrorCode.INVALID_ARGUMENT, "q must be at most 200 characters")
        if sport is not None and len(sport) > 64:
            return _error_response(ErrorCode.INVALID_ARGUMENT, "sport must be at most 64 characters")
        try:
            with _connect_readonly(config.db_path) as connection:
                items, total = _query_activities(
                    connection, q=q, sport=sport, has_report=has_report, limit=limit, offset=offset
                )
        except WebAPIError as exc:
            return _error_response(exc.code, exc.message)
        return success_envelope(
            {"items": items, "total": total, "limit": limit, "offset": offset, "empty": total == 0}
        ).to_json()

    @app.get("/api/activities/{activity_id}")
    def activity_detail(activity_id: str) -> Any:
        if not _valid_activity_id(activity_id):
            return _error_response(ErrorCode.INVALID_ARGUMENT, "activity_id must be a SHA-256 hex string")
        try:
            with _connect_readonly(config.db_path) as connection:
                detail = _get_activity_detail(connection, activity_id)
        except WebAPIError as exc:
            return _error_response(exc.code, exc.message)
        return success_envelope(detail).to_json()

    @app.get("/api/reports/activity/{activity_id}")
    def read_activity_report(activity_id: str) -> Any:
        if not _valid_activity_id(activity_id):
            return _error_response(ErrorCode.INVALID_ARGUMENT, "activity_id must be a SHA-256 hex string")
        try:
            with _connect_readonly(config.db_path) as connection:
                payload = get_activity_report(connection, activity_id)
        except (ReportStorageError, WebAPIError) as exc:
            return _report_error(exc)
        return success_envelope(payload).to_json()

    @app.post("/api/reports/activity/{activity_id}/generate")
    def generate_activity_report(
        activity_id: str,
        body: dict[str, Any] | None = _OPTIONAL_JSON_BODY,
    ) -> Any:
        if not _valid_activity_id(activity_id):
            return _error_response(ErrorCode.INVALID_ARGUMENT, "activity_id must be a SHA-256 hex string")
        message = _body_message(body, default="请生成这次运动的完整总结。")
        if isinstance(message, JSONResponse):
            return message
        service_or_error = _report_service(
            config,
            history,
            authorization=ToolAuthorization(
                frozenset((activity_id,)),
                frozenset(cast(tuple[ReferenceId, ...], ("longdou", "garmin-fit-parsing"))),
            ),
        )
        if isinstance(service_or_error, JSONResponse):
            return service_or_error
        try:
            result = service_or_error.generate_activity_report(
                activity_id=activity_id,
                current_user_message=message,
                now_utc=datetime.now(UTC),
            )
        except (ReportGenerationError, ReportStorageError, ContextError, AIProtocolError) as exc:
            return _report_error(exc)
        finally:
            service_or_error.connection.close()
        return success_envelope(_generated_report_json(result.summary, result.saved)).to_json()

    @app.get("/api/reports/weekly")
    def list_weekly_reports(
        limit: int = Query(default=DEFAULT_WEEKLY_LIMIT),
        offset: int = Query(default=0),
    ) -> Any:
        args_error = _validate_pagination(limit, offset)
        if args_error is not None:
            return args_error
        try:
            with _connect_readonly(config.db_path) as connection:
                items, total = _query_weekly_reports(connection, limit=limit, offset=offset)
        except WebAPIError as exc:
            return _error_response(exc.code, exc.message)
        return success_envelope(
            {"items": items, "total": total, "limit": limit, "offset": offset, "empty": total == 0}
        ).to_json()

    @app.get("/api/reports/weekly/{report_id}")
    def read_weekly_report(report_id: int) -> Any:
        if report_id <= 0:
            return _error_response(ErrorCode.INVALID_ARGUMENT, "report_id must be positive")
        try:
            with _connect_readonly(config.db_path) as connection:
                payload = get_weekly_report(connection, report_id)
        except (ReportStorageError, WebAPIError) as exc:
            return _report_error(exc)
        return success_envelope(payload).to_json()

    @app.post("/api/reports/weekly/generate")
    def generate_weekly_report(body: dict[str, Any] | None = _OPTIONAL_JSON_BODY) -> Any:
        message = _body_message(body, default="请生成过去七天的运动周总结。")
        if isinstance(message, JSONResponse):
            return message
        run_time = _body_run_time(body)
        if isinstance(run_time, JSONResponse):
            return run_time
        service_or_error = _report_service(
            config,
            history,
            authorization=ToolAuthorization(
                frozenset(),
                frozenset(cast(tuple[ReferenceId, ...], ("longdou", "garmin-fit-parsing"))),
            ),
        )
        if isinstance(service_or_error, JSONResponse):
            return service_or_error
        try:
            result = service_or_error.generate_weekly_report(
                run_time_utc=run_time,
                current_user_message=message,
            )
        except (ReportGenerationError, ReportStorageError, ContextError, AIProtocolError) as exc:
            return _report_error(exc)
        finally:
            service_or_error.connection.close()
        return success_envelope(_generated_report_json(result.summary, result.saved)).to_json()

    @app.api_route("/api/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def api_not_found(_path: str) -> JSONResponse:
        return _error_response(ErrorCode.ACTIVITY_NOT_FOUND, "not found", status_code=404)

    app.mount("/", _SPAStaticFiles(directory=static_dir, html=True, follow_symlink=False), name="web")
    return app


class _SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code != 404:
            return response
        return await super().get_response("index.html", scope)


class WebAPIError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code
        self.message = message


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise WebAPIError(ErrorCode.DATABASE_UNAVAILABLE, "database is unavailable")
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("SELECT count(*) FROM activities").fetchone()
    except sqlite3.Error as exc:
        raise WebAPIError(ErrorCode.DATABASE_UNAVAILABLE, "database is unavailable") from exc
    return connection


def _connect_readwrite(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise WebAPIError(ErrorCode.DATABASE_UNAVAILABLE, "database is unavailable")
    try:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except sqlite3.Error as exc:
        raise WebAPIError(ErrorCode.DATABASE_UNAVAILABLE, "database is unavailable") from exc


def _query_activities(
    connection: sqlite3.Connection,
    *,
    q: str | None,
    sport: str | None,
    has_report: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if q:
        pattern = f"%{q}%"
        where.append("(a.activity_id LIKE ? OR a.fit_path LIKE ? OR a.sport LIKE ? OR a.sub_sport LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    if sport:
        where.append("a.sport = ?")
        params.append(sport)
    if has_report is not None:
        where.append("r.activity_id IS NOT NULL" if has_report else "r.activity_id IS NULL")
    where_sql = "" if not where else "WHERE " + " AND ".join(where)
    total = connection.execute(
        "SELECT count(*) FROM activities a LEFT JOIN activties_report r ON r.activity_id=a.activity_id "
        + where_sql,
        params,
    ).fetchone()[0]
    rows = connection.execute(
        """
        SELECT a.activity_id,a.fit_path,a.sport,a.sub_sport,a.start_time_utc,a.end_time_utc,
               a.parsed_at_utc,a.summary_json,r.summary AS report_summary,
               (SELECT count(*) FROM records rec WHERE rec.activity_id=a.activity_id) AS record_count
        FROM activities a
        LEFT JOIN activties_report r ON r.activity_id=a.activity_id
        """
        + where_sql
        + " ORDER BY a.start_time_utc IS NULL, a.start_time_utc DESC, a.activity_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_activity_row_json(row) for row in rows], int(total)


def _get_activity_detail(connection: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT a.activity_id,a.fit_path,a.sport,a.sub_sport,a.start_time_utc,a.end_time_utc,
               a.parsed_at_utc,a.basic_json,a.summary_json,a.segments_json,r.summary AS report_summary,
               (SELECT count(*) FROM records rec WHERE rec.activity_id=a.activity_id) AS record_count
        FROM activities a
        LEFT JOIN activties_report r ON r.activity_id=a.activity_id
        WHERE a.activity_id=?
        """,
        (activity_id,),
    ).fetchone()
    if row is None:
        raise WebAPIError(ErrorCode.ACTIVITY_NOT_FOUND, "activity not found")
    return {
        **_activity_row_json(row),
        "basic": _loads_object(row["basic_json"]),
        "summary": _loads_object(row["summary_json"]),
        "segments": _loads_object(row["segments_json"]),
    }


def _query_weekly_reports(
    connection: sqlite3.Connection, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    total = connection.execute("SELECT count(*) FROM weekly_report").fetchone()[0]
    rows = connection.execute(
        "SELECT id,run_time_utc,summary FROM weekly_report ORDER BY run_time_utc DESC,id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows], int(total)


def _activity_row_json(row: sqlite3.Row) -> dict[str, Any]:
    summary = _loads_object(row["summary_json"])
    return {
        "activity_id": row["activity_id"],
        "fit_path": row["fit_path"],
        "sport": row["sport"],
        "sub_sport": row["sub_sport"],
        "start_time_utc": row["start_time_utc"],
        "end_time_utc": row["end_time_utc"],
        "parsed_at_utc": row["parsed_at_utc"],
        "record_count": row["record_count"],
        "has_activity_report": row["report_summary"] is not None,
        "report_summary": row["report_summary"],
        "fit_summary": summary,
    }


def _loads_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WebAPIError(ErrorCode.DATA_INVALID, "stored JSON is invalid") from exc
    if not isinstance(value, dict):
        raise WebAPIError(ErrorCode.DATA_INVALID, "stored JSON must be an object")
    return value


def _validate_pagination(limit: int, offset: int) -> JSONResponse | None:
    if limit < 1 or limit > MAX_LIMIT:
        return _error_response(ErrorCode.INVALID_ARGUMENT, f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        return _error_response(ErrorCode.INVALID_ARGUMENT, "offset must be non-negative")
    return None


def _valid_activity_id(activity_id: str) -> bool:
    return len(activity_id) == 64 and all(char in "0123456789abcdef" for char in activity_id)


def _report_service(
    settings: WebAppSettings,
    history: InMemoryConversationHistory,
    *,
    authorization: ToolAuthorization,
) -> ReportService | JSONResponse:
    if not _ai_configured(settings):
        return _error_response(
            ErrorCode.CONFIG_UNAVAILABLE,
            "AI generation requires an explicitly injected local client and config",
        )
    try:
        connection = _connect_readwrite(settings.db_path)
    except WebAPIError as exc:
        return _error_response(exc.code, exc.message)
    assert settings.ai_client is not None
    assert settings.ai_config is not None
    dispatcher = ToolDispatcher(
        db_path=settings.db_path,
        authorization=authorization,
        project_root=settings.project_root,
        capacity=settings.capacity,
    )
    return ReportService(
        connection=connection,
        project_root=settings.project_root,
        ai_client=settings.ai_client,
        ai_config=settings.ai_config,
        dispatcher=dispatcher,
        history=history,
    )


def _ai_configured(settings: WebAppSettings) -> bool:
    return settings.ai_client is not None and settings.ai_config is not None


def _body_message(body: dict[str, Any] | None, *, default: str) -> str | JSONResponse:
    if body is None:
        return default
    message = body.get("message", default)
    if not isinstance(message, str) or message == "" or len(message) > 2000:
        return _error_response(ErrorCode.INVALID_ARGUMENT, "message must be a non-empty string")
    return message


def _body_run_time(body: dict[str, Any] | None) -> datetime | JSONResponse:
    if body is None or "run_time_utc" not in body:
        return datetime.now(UTC)
    value = body["run_time_utc"]
    if not isinstance(value, str):
        return _error_response(ErrorCode.INVALID_ARGUMENT, "run_time_utc must be a UTC string")
    try:
        parsed = datetime.strptime(value, UTC_TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return _error_response(ErrorCode.INVALID_ARGUMENT, "run_time_utc must be a UTC string")
    return parsed


def _generated_report_json(summary: str, saved: Mapping[str, object]) -> dict[str, object]:
    return {"summary": summary, "saved": dict(saved)}


def _sync_state_json(state: GarminSyncState, now_utc: datetime) -> dict[str, Any]:
    data = state.to_json()
    data["due"] = should_run_sync(state, now_utc)
    data["interval_seconds"] = 3 * 60 * 60
    return data


def _report_error(exc: ReportGenerationError | ReportStorageError | ContextError | AIProtocolError | WebAPIError) -> JSONResponse:
    code = exc.code
    message = getattr(exc, "message", str(exc))
    return _error_response(code, message)


def _error_response(code: ErrorCode, message: str, *, status_code: int | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=http_status_for_error(code) if status_code is None else status_code,
        content=failure_envelope(code, message).to_json(),
    )


def _inside_root(root_path: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise ValueError("db path must be instance-relative")
    root = root_path.resolve(strict=False)
    path = (root / relative_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("db path escapes instance root") from exc
    return path
