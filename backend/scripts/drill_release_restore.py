#!/usr/bin/env python3
"""Destructive end-to-end release restore drill, hard-limited to an isolated project."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from backup_release import create_backup
from release_backup_common import (
    ReleaseBackupError,
    compose_command,
    run,
    run_text,
    validate_project_name,
)
from restore_release import confirmation_for, restore_backup

ISOLATED_PROJECT_PREFIX = "trainlab_release_v010_u2"
ROOT_DIR = Path(__file__).resolve().parents[2]
FIT_FIXTURE = ROOT_DIR / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
TEST_USERNAME = "release-owner"
TEST_PASSWORD = "release-test-password"
TRUSTED_ORIGIN = "http://localhost:8000"


class DrillError(RuntimeError):
    pass


def require_isolated_project(project: str) -> str:
    project = validate_project_name(project)
    if project != ISOLATED_PROJECT_PREFIX and not project.startswith(f"{ISOLATED_PROJECT_PREFIX}_"):
        raise DrillError(f"Drill project must be {ISOLATED_PROJECT_PREFIX} or use that prefix")
    return project


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        csrf: bool = False,
        expected: int = 200,
    ) -> bytes:
        headers: dict[str, str] = {}
        if method not in {"GET", "HEAD"}:
            headers["Origin"] = TRUSTED_ORIGIN
        if content_type is not None:
            headers["Content-Type"] = content_type
        if csrf:
            csrf_cookie = next(
                (cookie.value for cookie in self.cookies if cookie.name == "trainlab_csrf"), None
            )
            if csrf_cookie is None:
                raise DrillError("CSRF cookie is missing")
            headers["X-CSRF-Token"] = csrf_cookie
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                status = response.status
                payload = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read()
        if status != expected:
            raise DrillError(f"{method} {path} returned {status}, expected {expected}")
        return payload

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        csrf: bool = False,
        expected: int = 200,
    ) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        response = self.request(
            method,
            path,
            body=body,
            content_type="application/json" if body is not None else None,
            csrf=csrf,
            expected=expected,
        )
        result = json.loads(response)
        if not isinstance(result, dict):
            raise DrillError(f"{path} returned a non-object response")
        return result

    def login(self) -> None:
        self.json(
            "POST",
            "/api/v1/auth/login",
            payload={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )

    def upload(self, source: bytes) -> str:
        boundary = f"trainlab-{secrets.token_hex(16)}"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="fixture.fit"\r\n'
                "Content-Type: application/vnd.ant.fit\r\n\r\n"
            ).encode()
            + source
            + f"\r\n--{boundary}--\r\n".encode()
        )
        result = json.loads(
            self.request(
                "POST",
                "/api/v1/imports/fit",
                body=body,
                content_type=f"multipart/form-data; boundary={boundary}",
                csrf=True,
                expected=201,
            )
        )
        activity = result.get("activity")
        if not isinstance(activity, dict) or not isinstance(activity.get("id"), str):
            raise DrillError("Upload response did not include an activity id")
        return activity["id"]


def compose(project: str, *arguments: str, env: dict[str, str]) -> None:
    run(compose_command(project, *arguments), env=env)


def create_owner(project: str, env: dict[str, str]) -> None:
    owner_env = dict(env)
    owner_env["TRAINLAB_RELEASE_TEST_PASSWORD"] = TEST_PASSWORD
    run(
        compose_command(
            project,
            "exec",
            "-T",
            "-e",
            "TRAINLAB_RELEASE_TEST_PASSWORD",
            "backend",
            "trainlab",
            "create-owner",
            "--username",
            TEST_USERNAME,
            "--password-env",
            "TRAINLAB_RELEASE_TEST_PASSWORD",
        ),
        env=owner_env,
    )


def verify_loopback_binding(project: str, expected_port: int) -> None:
    published = run_text(compose_command(project, "port", "backend", "8000"))
    if published != f"127.0.0.1:{expected_port}":
        raise DrillError("Backend port is not bound exclusively to the expected loopback address")


def verify_data(client: ApiClient, activity_id: str, expected_sha256: str) -> None:
    ready = client.json("GET", "/readyz")
    if ready.get("status") != "ready":
        raise DrillError("Backend did not report ready")
    listing = client.json("GET", "/api/v1/activities")
    items = listing.get("items")
    if (
        not isinstance(items, list)
        or len(items) != 1
        or not isinstance(items[0], dict)
        or items[0].get("id") != activity_id
    ):
        raise DrillError("Restored activity list is missing or duplicated")
    detail = client.json("GET", f"/api/v1/activities/{activity_id}")
    if not isinstance(detail.get("activity"), dict):
        raise DrillError("Restored activity detail is unavailable")
    usage = client.json("GET", "/api/v1/storage/usage")
    if not isinstance(usage.get("usedBytes"), int) or usage["usedBytes"] <= 0:
        raise DrillError("Restored private storage usage is unavailable")
    downloaded = client.request("GET", f"/api/v1/activities/{activity_id}/source")
    if hashlib.sha256(downloaded).hexdigest() != expected_sha256:
        raise DrillError("Restored FIT SHA-256 does not match the uploaded file")


def run_drill(project: str, host_port: int, *, keep: bool) -> None:
    project = require_isolated_project(project)
    if not 1024 <= host_port <= 65535:
        raise DrillError("Host port must be between 1024 and 65535")
    source = FIT_FIXTURE.read_bytes()
    source_sha256 = hashlib.sha256(source).hexdigest()
    environment = dict(os.environ)
    environment["COMPOSE_PROJECT_NAME"] = project
    environment["TRAINLAB_HOST_PORT"] = str(host_port)
    base_url = f"http://127.0.0.1:{host_port}"

    previous_port = os.environ.get("TRAINLAB_HOST_PORT")
    os.environ["TRAINLAB_HOST_PORT"] = str(host_port)
    try:
        compose(project, "down", "-v", "--remove-orphans", env=environment)
        compose(project, "up", "--build", "-d", "--wait", "db", "backend", env=environment)
        verify_loopback_binding(project, host_port)
        create_owner(project, environment)
        before = ApiClient(base_url)
        before.login()
        activity_id = before.upload(source)
        verify_data(before, activity_id, source_sha256)

        with tempfile.TemporaryDirectory(prefix="trainlab-release-v010-") as temporary:
            backup_directory = Path(temporary) / "backup"
            create_backup(backup_directory, project)
            compose(project, "down", "-v", "--remove-orphans", env=environment)
            restore_backup(backup_directory, project, confirmation_for(project))

        # Every session in the restored database must have been revoked.
        before.request("GET", "/api/v1/auth/session", expected=401)
        after = ApiClient(base_url)
        after.login()
        verify_data(after, activity_id, source_sha256)

        # A rebuild and repeated idempotent owner bootstrap must preserve one activity.
        compose(project, "up", "--build", "-d", "--wait", "db", "backend", env=environment)
        create_owner(project, environment)
        after_rebuild = ApiClient(base_url)
        after_rebuild.login()
        verify_data(after_rebuild, activity_id, source_sha256)
    finally:
        try:
            if not keep:
                compose(project, "down", "-v", "--remove-orphans", env=environment)
        finally:
            if previous_port is None:
                os.environ.pop("TRAINLAB_HOST_PORT", None)
            else:
                os.environ["TRAINLAB_HOST_PORT"] = previous_port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=ISOLATED_PROJECT_PREFIX)
    parser.add_argument("--host-port", default=18103, type=int)
    parser.add_argument("--keep", action="store_true", help="keep isolated services for diagnosis")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        run_drill(args.project, args.host_port, keep=args.keep)
    except (DrillError, ReleaseBackupError, OSError) as exc:
        print(f"Release restore drill failed: {exc}", file=sys.stderr)
        return 1
    print("Release restore drill passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
