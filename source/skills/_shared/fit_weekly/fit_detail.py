"""Pre-bound weekly FIT detail host. The model cannot construct a scope or path.

The existing immutable documents table stores model-input scopes and detail
intent/results. A single instance writer lock covers reservation and extraction;
the intent is committed first, so interruption never grants a fresh budget.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from skills._shared.fit_weekly import (
    fit_parse,
    fit_time,
    stage_policy,
    storage,
    sync_calendar,
)

MAX_REQUESTS = 20
MAX_SECONDS = 1200
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/fit_detail_v1.schema.json"
SCHEMAS = {
    "fit-summary-1": "fit_detail_v1",
    "fit-summary-2": "fit_detail_v2",
    "fit-summary-3": "fit_detail_v3",
}


def schema_path(version: str) -> Path:
    return SCHEMA_PATH.with_name(
        f"{SCHEMAS[fit_parse.require_parser_version(version)]}.schema.json"
    )


def period_key(end: str) -> tuple[str, dict[str, Any]]:
    slot = sync_calendar.weekly_slot(end)
    if slot["end_utc"] != end:
        raise ValueError("detail_week_invalid")
    return f"detail:{end}", slot


def get(db: sqlite3.Connection, key: str) -> tuple[str, dict[str, Any]] | None:
    rows = db.execute(
        "SELECT input_sha256,content_json,content_sha256 FROM documents WHERE kind='weekly_input' AND logical_key=?",
        (key,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("detail_document_conflict")
    input_sha, text, sha = rows[0]
    body = json.loads(text)
    if storage.canonical(body) != text or storage.digest(text.encode()) != sha:
        raise ValueError("detail_document_drift")
    return input_sha, body


def put(db: sqlite3.Connection, key: str, input_sha: str, body: dict[str, Any]) -> None:
    old = get(db, key)
    if old is not None and old != (input_sha, body):
        raise ValueError("detail_document_conflict")
    storage.put_document(db, "weekly_input", key, input_sha, body)


def fit_bytes(db: sqlite3.Connection, root: Path, ref: str, sha: str) -> bytes:
    storage.require_sha(sha)
    row = db.execute(
        "SELECT f.relative_path,f.byte_size FROM fits f JOIN activity_fits a ON a.fit_sha256=f.sha256 WHERE a.activity_ref=? AND f.sha256=?",
        (ref, sha),
    ).fetchone()
    if row is None or row[0] != f"fits/{sha}.fit":
        raise ValueError("detail_activity_binding_invalid")
    path = root / row[0]
    storage.private_entry(path, nonempty=True)
    data = path.read_bytes()
    if len(data) != row[1] or storage.digest(data) != sha:
        raise ValueError("fit_sha_mismatch")
    return data


def freeze_scope(
    root: Path,
    period_end: str,
    members: list[dict[str, str]],
    *,
    parser_version: str | None = None,
) -> dict[str, Any]:
    key, slot = period_key(period_end)
    if not isinstance(members, list) or any(
        not isinstance(m, dict)
        or set(m) != {"activity_ref", "fit_sha256"}
        or not isinstance(m["activity_ref"], str)
        or not re.fullmatch(r"[0-9]{1,32}", m["activity_ref"])
        or not isinstance(m["fit_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", m["fit_sha256"])
        for m in members
    ):
        raise ValueError("detail_scope_invalid")
    if len({m["activity_ref"] for m in members}) != len(members):
        raise ValueError("detail_scope_invalid")
    with storage.open_store(root) as db:
        old = get(db, key + ":scope")
        version = fit_parse.require_parser_version(
            old[1]["parser_version"] if old else parser_version
        )
        if old and parser_version is not None and parser_version != version:
            raise ValueError("detail_scope_conflict")
        items = []
        for m in sorted(members, key=lambda m: m["activity_ref"]):
            parsed = fit_parse.parse_registered(
                db, root, m["activity_ref"], m["fit_sha256"], parser_version=version
            )
            if not sync_calendar.in_week(parsed["end_utc"], slot):
                raise ValueError("detail_activity_outside_week")
            duration = (
                fit_time.utc_time(parsed["end_utc"])
                - fit_time.utc_time(parsed["start_utc"])
            ).total_seconds()
            items.append(
                {
                    **m,
                    "parse_sha256": storage.digest(storage.canonical(parsed).encode()),
                    "duration_seconds": duration,
                }
            )
        body = {
            "schema_version": "fit_detail_scope_v1",
            "period_start_utc": slot["start_utc"],
            "period_end_utc": period_end,
            "parser_version": version,
            "max_requests": MAX_REQUESTS,
            "max_seconds": MAX_SECONDS,
            "members": items,
            "provider_calls": 0,
        }
        sha = storage.digest(storage.canonical(body).encode())
        if old is not None and old != (sha, body):
            raise ValueError("detail_scope_conflict")
        put(db, key + ":scope", sha, body)
        return {"scope_sha256": sha, **body}


def request_value(
    value: dict[str, Any], parser_version: str | None = None
) -> dict[str, Any]:
    version = fit_parse.require_parser_version(parser_version)
    fields = {
        "activity_ref",
        "view",
        "start_offset_seconds",
        "end_offset_seconds",
        "resolution_seconds",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("detail_request_invalid")
    start, end, res = (
        value[k]
        for k in ("start_offset_seconds", "end_offset_seconds", "resolution_seconds")
    )
    if (
        not isinstance(value["activity_ref"], str)
        or value["view"] not in ("summary", "laps", "series")
        or type(res) is not int
        or (
            any(not fit_time.millisecond_offset(v) for v in (start, end))
            if version == fit_parse.TIME_VERSION
            else any(type(v) is not int for v in (start, end))
        )
        or not 0 <= start < end
        or (
            round(end * 1000) - round(start * 1000) > MAX_SECONDS * 1000
            if version == fit_parse.TIME_VERSION
            else end - start > MAX_SECONDS
        )
        or res not in (1, 5)
    ):
        raise ValueError("detail_request_invalid")
    result = dict(value)
    if version == fit_parse.TIME_VERSION:
        for key in ("start_offset_seconds", "end_offset_seconds"):
            if result[key] == int(result[key]):
                result[key] = int(result[key])
    return result


def extract(
    data: bytes, req: dict[str, Any], parser_version: str | None = None
) -> list[dict[str, Any]]:
    version = fit_parse.require_parser_version(parser_version)
    decoded = fit_parse.decode(data, parser_version=version)
    origin = decoded.sessions[0]["start"]
    requested_start, requested_end = (
        origin + req["start_offset_seconds"],
        origin + req["end_offset_seconds"],
    )
    blocks = []
    for ordinal, s in enumerate(decoded.sessions, 1):
        start, end = max(requested_start, s["start"]), min(requested_end, s["end"])
        if start >= end:
            continue
        intervals, kind = fit_parse.active_intervals(s, decoded.events)
        series = fit_parse.Series(
            [p for p in decoded.points if s["start"] <= p.time <= s["end"]],
            intervals,
            kind != "unavailable",
        )
        location_points = (
            fit_parse.session_location_points(decoded, ordinal - 1)
            if version in fit_parse.LOCATION_VERSIONS
            else []
        )
        if version == fit_parse.TIME_VERSION and req["view"] == "laps":
            series = fit_parse.Series(location_points, intervals, kind != "unavailable")
        ranges: list[tuple[float, float, str, bool, bool]] = []
        if req["view"] == "laps":
            laps, _ = fit_parse.session_laps(
                s, decoded.laps, parser_version=version, sessions=decoded.sessions
            )
            for lap in laps:
                a, b = max(start, lap["start"]), min(end, lap["end"])
                if a < b:
                    ranges.append(
                        (
                            a,
                            b,
                            lap["role"],
                            a != lap["start"] or b != lap["end"],
                            lap.get("precision_compatible", False),
                        )
                    )
        elif req["view"] == "summary":
            ranges.append((start, end, "unknown", False, False))
        else:
            cursor = start
            while cursor < end:
                stop = min(end, cursor + req["resolution_seconds"])
                ranges.append((cursor, stop, "unknown", False, False))
                cursor = stop
        for a, b, role, clipped, precision in ranges:
            statistics = series.aggregate(a, b)
            if version in fit_parse.LOCATION_VERSIONS:
                statistics["location"] = fit_parse.location_summary(
                    location_points, a, b, include_end=b == s["end"]
                )
            blocks.append(
                {
                    "session_ordinal": ordinal,
                    "start_offset_seconds": round(a - origin, 6)
                    if version == fit_parse.TIME_VERSION
                    else a - origin,
                    "end_offset_seconds": round(b - origin, 6)
                    if version == fit_parse.TIME_VERSION
                    else b - origin,
                    "role": role,
                    "clipped_lap": clipped,
                    **(
                        {"lap_time_precision_compatible": precision}
                        if version == fit_parse.TIME_VERSION
                        else {}
                    ),
                    "timer_source": kind,
                    "statistics": statistics,
                }
            )
    return blocks


def validate_result(body: dict[str, Any]) -> None:
    version = fit_parse.require_parser_version(body.get("parser_version", ""))
    resource = Resource.from_contents(
        json.loads(fit_parse.schema_path(version).read_text())
    )
    registry: Registry = Registry().with_resource(
        "urn:trainlab:" + fit_parse.SCHEMAS[version], resource
    )
    jsonschema.Draft202012Validator(
        json.loads(schema_path(version).read_text()), registry=registry
    ).validate(body)


class DetailHost:
    def __init__(
        self,
        root: Path,
        period_end: str,
        scope_sha256: str,
        *,
        stage: str | None = None,
    ):
        self.root, self.key = root, period_key(period_end)[0]
        self.stage = stage_policy.require(stage, legacy=True)
        storage.require_sha(scope_sha256)
        self.scope_sha = scope_sha256

    def scope(self, db: sqlite3.Connection) -> dict[str, Any]:
        old = get(db, self.key + ":scope")
        if (
            old is None
            or old[0] != self.scope_sha
            or storage.digest(storage.canonical(old[1]).encode()) != self.scope_sha
        ):
            raise ValueError("detail_scope_binding_invalid")
        body = old[1]
        if (
            body["parser_version"] not in fit_parse.SCHEMAS
            or body["max_requests"] != MAX_REQUESTS
            or body["max_seconds"] != MAX_SECONDS
        ):
            raise ValueError("detail_scope_binding_invalid")
        return body

    def count(self, db: sqlite3.Connection) -> int:
        return db.execute(
            "SELECT COUNT(*) FROM documents WHERE kind='weekly_input' AND logical_key LIKE ?",
            (self.key + ":intent:%",),
        ).fetchone()[0]

    def usage(self) -> dict[str, int]:
        with storage.open_store(self.root) as db:
            self.scope(db)
            return {"requests": self.count(db), "max_requests": MAX_REQUESTS}

    def parser_version(self) -> str:
        with storage.open_store(self.root) as db:
            return self.scope(db)["parser_version"]

    def read(self, value: dict[str, Any]) -> dict[str, Any]:
        with storage.open_store(self.root) as db:
            scope = self.scope(db)
            req = request_value(value, scope["parser_version"])
            members = [
                m for m in scope["members"] if m["activity_ref"] == req["activity_ref"]
            ]
            if len(members) != 1:
                raise ValueError("detail_activity_outside_scope")
            member = members[0]
            if req["end_offset_seconds"] > member["duration_seconds"]:
                raise ValueError("detail_range_outside_activity")
            data = fit_bytes(
                db, self.root, member["activity_ref"], member["fit_sha256"]
            )
            parse = db.execute(
                "SELECT content_json,content_sha256 FROM parses WHERE fit_sha256=? AND parser_version=?",
                (member["fit_sha256"], scope["parser_version"]),
            ).fetchone()
            if (
                parse is None
                or parse[1] != member["parse_sha256"]
                or storage.digest(parse[0].encode()) != parse[1]
            ):
                raise ValueError("detail_parse_drift")
            # This must precede BOTH cache lookup and reservation. A summary
            # cache entry never grants planning permission to non-running FIT.
            stage_policy.authorize(self.stage, json.loads(parse[0]), req)
            request_sha = storage.digest(
                storage.canonical(
                    {"scope_sha256": self.scope_sha, "request": req}
                ).encode()
            )
            intent_key, result_key = (
                self.key + ":intent:" + request_sha,
                self.key + ":result:" + request_sha,
            )
            intent = {
                "schema_version": "fit_detail_intent_v1",
                "scope_sha256": self.scope_sha,
                "request_sha256": request_sha,
                "request": req,
            }
            old = get(db, intent_key)
            if old is not None and old != (self.scope_sha, intent):
                raise ValueError("detail_intent_drift")
            cached = get(db, result_key)
            if cached is not None:
                if old is None or cached[0] != request_sha:
                    raise ValueError("detail_result_drift")
                validate_result(cached[1])
                if cached[1]["parser_version"] != scope["parser_version"]:
                    raise ValueError("detail_result_drift")
                return cached[1]
            if old is None:
                if self.count(db) >= MAX_REQUESTS:
                    raise ValueError("detail_budget_exceeded")
                put(db, intent_key, self.scope_sha, intent)
                sync_calendar.durable(db)
            body = {
                "schema_version": SCHEMAS[scope["parser_version"]],
                "parser_version": scope["parser_version"],
                "representation": "time_weighted_bins_not_raw_samples"
                if scope["parser_version"] == "fit-summary-1"
                else "time_weighted_bins_with_actual_location_endpoints",
                "scope_sha256": self.scope_sha,
                "request_sha256": request_sha,
                "fit_sha256": member["fit_sha256"],
                **req,
                "status": "available",
                "error_code": None,
                "blocks": [],
                "provider_calls": 0,
            }
            try:
                body["blocks"] = extract(data, req, scope["parser_version"])
            except Exception:
                body.update(status="unavailable", error_code="detail_read_failed")
            validate_result(body)
            put(db, result_key, request_sha, body)
            return body
