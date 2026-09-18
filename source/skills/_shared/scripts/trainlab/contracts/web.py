"""Local web/API public route and static-file safety contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trainlab.contracts.paths import WEB_STATIC_DIR, validate_static_mount

API_PREFIX = "/api"
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
STATIC_WEB_DIR = WEB_STATIC_DIR


@dataclass(frozen=True)
class RouteContract:
    method: str
    path: str
    purpose: str


API_ROUTES = (
    RouteContract("GET", "/api/health", "Local process health and version"),
    RouteContract("GET", "/api/status", "Combined local status without secrets"),
    RouteContract("GET", "/api/sync/status", "Latest FIT sync status"),
    RouteContract("GET", "/api/activities", "Browse or search parsed activity facts"),
    RouteContract("GET", "/api/activities/{activity_id}", "Read parsed activity details"),
    RouteContract("GET", "/api/reports/activity/{activity_id}", "Read one stored activity summary"),
    RouteContract("POST", "/api/reports/activity/{activity_id}/generate", "Generate one activity summary with explicit AI wiring"),
    RouteContract("GET", "/api/reports/weekly", "Browse stored weekly summaries"),
    RouteContract("GET", "/api/reports/weekly/{report_id}", "Read one stored weekly summary"),
    RouteContract("POST", "/api/reports/weekly/generate", "Generate a weekly summary with explicit AI wiring"),
)


def static_mount_dir() -> Path:
    validate_static_mount(STATIC_WEB_DIR)
    return STATIC_WEB_DIR


def route_paths() -> tuple[str, ...]:
    return tuple(route.path for route in API_ROUTES)
