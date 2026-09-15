"""Only public synthetic accounts, messages, sessions and reports."""

import base64
import importlib
import json
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from typing import Any

reports = importlib.import_module("m12_report_factory")
NOW = "2026-08-10T00:00:00Z"


def prepared(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import (
        model_job,
        publication,
        report_artifacts,
        report_revisions,
    )

    root, _, calls = reports.setup(
        tmp_path, monkeypatch, transform=reports.supported_content, with_cadence=True
    )
    revision = report_revisions.create(root, reports.END)
    sha = model_job.sha(revision)
    report_artifacts.render(root, reports.END, "ai", sha)
    result = publication.prepare_weekly(
        root,
        reports.END,
        "ai",
        sha,
        recipient="runner@example.invalid",
        sender="owner@example.invalid",
        late=True,
        mail_version=1,
    )
    return root, result, calls


def authorization(actions, *, tools=None, key="synthetic-grant", limits=None):
    from skills._shared.fit_weekly.publication_ledger import TOOLS, Authorization

    allowed = tools or sorted(TOOLS)
    return Authorization(
        key=key,
        action_keys=tuple(actions),
        start_date="2026-08-01",
        end_date="2026-08-31",
        starts_utc="2026-08-10T00:00:00Z",
        expires_utc="2026-08-10T01:00:00Z",
        max_calls={t: 30 for t in allowed} if limits is None else limits,
    )


class Gmail:
    def __init__(self):
        self.calls = []
        self.labels = []
        self.applied_labels = []
        self.sent = {}
        self.fail = None
        self.change = None
        self.page = False
        self.rewrite = True

    def request(self, method, url, *, headers, timeout, **kwargs):
        self.calls.append((method, url, deepcopy(kwargs)))
        if self.fail and self.fail in url:
            raise OSError("synthetic failure")
        if url.endswith("/labels"):
            if method == "POST":
                assert kwargs["json"] == {"name": "TrainLab"}
                self.labels = [
                    {"id": "Label_synthetic", "name": "TrainLab", "type": "user"}
                ]
            return SimpleNamespace(
                status_code=200, json=lambda: {"labels": self.labels}
            )
        if url.endswith("/modify"):
            assert kwargs["json"] == {"addLabelIds": ["Label_synthetic"]}
            self.applied_labels = ["Label_synthetic"]
            return SimpleNamespace(status_code=200, json=lambda: {"id": "abc123"})
        if url.endswith("/profile"):
            body: dict[str, Any] = {"emailAddress": "owner@example.invalid"}
        elif url.endswith("/send"):
            raw = base64.urlsafe_b64decode(kwargs["json"]["raw"])
            mail = BytesParser(policy=policy.default).parsebytes(raw)
            if self.rewrite:
                mail.replace_header("Message-ID", "<rewritten@example.invalid>")
            self.sent["abc123"] = mail.as_bytes(policy=policy.SMTP)
            body = {"id": "abc123", "threadId": "abc123"}
        elif url.endswith("/messages"):
            body = {"messages": [{"id": i} for i in self.sent]}
            if self.page:
                body["nextPageToken"] = "unresolved-next-page"
        else:
            ident = url.rsplit("/", 1)[1]
            raw = self.sent[ident]
            if self.change:
                raw = self.change(raw)
            body = {
                "id": ident,
                "labelIds": self.applied_labels,
                "raw": base64.urlsafe_b64encode(raw).decode(),
            }
        return SimpleNamespace(status_code=200, json=lambda: body)


class Auth:
    account = "owner@example.invalid"

    def require_labels(self):
        pass

    def headers(self, timeout=30, before_refresh=None):
        return {"Authorization": "Bearer synthetic-token-not-for-persistence"}


class Garmin:
    def __init__(self):
        self.calls = []
        self.workouts = {}
        self.calendar = []
        self.fail = None
        self.change = None

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        if name == self.fail:
            raise OSError("synthetic response lost")
        if name == "upload_workout":
            self.workouts[123] = deepcopy(arguments["workout_data"])
            result = {
                "status": "success",
                "workout_id": 123,
                "name": self.workouts[123]["workoutName"],
            }
        elif name == "get_workout_by_id":
            result = curated(self.workouts[int(arguments["workout_id"])], 123)
            if self.change:
                self.change(result)
        elif name == "schedule_workout":
            self.calendar.append(
                {
                    "date": arguments["calendar_date"],
                    "workout_id": arguments["workout_id"],
                    "scheduled_workout_id": 987,
                }
            )
            result = {
                "status": "success",
                "workout_id": arguments["workout_id"],
                "scheduled_date": arguments["calendar_date"],
            }
        else:
            result = {
                "count": len(self.calendar),
                "date_range": {
                    "start": arguments["start_date"],
                    "end": arguments["end_date"],
                },
                "scheduled_workouts": self.calendar,
            }
        return SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps(result))],
        )


def curated(dto, ident):
    # Independent spelling of the pinned upstream curated protocol.
    def step(s):
        out = {
            "order": s["stepOrder"],
            "type": s["stepType"]["stepTypeKey"],
            "end_condition": s["endCondition"]["conditionTypeKey"],
        }
        if "description" in s:
            out["description"] = s["description"]
        if s["type"] == "RepeatGroupDTO":
            out.update(
                repeat_count=s["numberOfIterations"],
                steps=[step(x) for x in s["workoutSteps"]],
                step_count=len(s["workoutSteps"]),
            )
        else:
            out["end_condition_value"] = s["endConditionValue"]
        return out

    return {
        "id": ident,
        "name": dto["workoutName"],
        "description": dto["description"],
        "sport": "running",
        "segment_count": 1,
        "segments": [
            {
                "order": 1,
                "sport": "running",
                "step_count": len(dto["workoutSegments"][0]["workoutSteps"]),
                "steps": [step(s) for s in dto["workoutSegments"][0]["workoutSteps"]],
            }
        ],
    }


def prepared_sync(tmp_path):
    from skills._shared.fit_weekly import publication, storage, sync_calendar

    root = tmp_path / "instance"
    storage.initialize(root)
    spec = sync_calendar.InventoryRequest(
        "public-sync", "2026-08-09", "2026-08-10", NOW, 10, 1
    )
    sync_calendar.collect_inventory(
        root,
        spec,
        lambda *a: {"page": 0, "page_size": 10, "has_more": False, "items": []},
    )
    return root, publication.prepare_sync(
        root,
        spec.key,
        sender=Auth.account,
        recipient="runner@example.invalid",
        mail_version=1,
    )


def token(tmp_path, **overrides):
    from skills._shared.fit_weekly import gmail_auth

    directory = tmp_path / "private-auth"
    directory.mkdir(mode=0o700)
    path = directory / "token.json"
    value = {
        "token": "synthetic-old-access",
        "expiry": "2020-01-01T00:00:00Z",
        "refresh_token": "synthetic-refresh-only",
        "client_id": "synthetic-client-only",
        "client_secret": "synthetic-secret-only",
        "token_uri": gmail_auth.TOKEN_URI,
        "scopes": sorted(gmail_auth.SCOPES),
        **overrides,
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


class Refresh:
    def __init__(self):
        self.calls = []
        self.value = {
            "access_token": "synthetic-refreshed-access",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        self.status = 200

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=self.status, json=lambda: self.value)
