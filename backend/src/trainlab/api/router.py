from fastapi import APIRouter

from trainlab.api.routes.activities import router as activities_router
from trainlab.api.routes.activity_metadata import router as activity_metadata_router
from trainlab.api.routes.auth import router as auth_router
from trainlab.api.routes.import_management import router as import_management_router
from trainlab.api.routes.storage_usage import router as storage_usage_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(activities_router)
api_router.include_router(activity_metadata_router)
api_router.include_router(import_management_router)
api_router.include_router(storage_usage_router)
