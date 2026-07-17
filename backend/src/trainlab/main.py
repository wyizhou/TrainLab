from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from trainlab.api.router import api_router
from trainlab.api.routes.health import router as health_router
from trainlab.core.config import Settings, get_settings
from trainlab.core.errors import install_exception_handlers
from trainlab.core.logging import configure_logging
from trainlab.core.middleware import request_context_middleware
from trainlab.db.database import create_database_engine
from trainlab.services.auth import LoginRateLimiter
from trainlab.web.static import install_frontend


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="TrainLab API",
        version="0.2.0",
        docs_url="/api/v1/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.engine = create_database_engine(app_settings.database_url)
    app.state.login_rate_limiter = LoginRateLimiter()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=app_settings.allowed_hosts)
    app.middleware("http")(request_context_middleware)

    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    install_frontend(app, app_settings.frontend_dist)
    return app


app = create_app()
