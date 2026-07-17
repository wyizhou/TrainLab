from fastapi import APIRouter

from trainlab.api.routes.activities import router as activities_router
from trainlab.api.routes.auth import router as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(activities_router)
