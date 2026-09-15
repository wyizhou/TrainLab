"""Freeze complete local weekly FIT evidence, independently of any AI or plan.

The sync receipt proves inventory as observed at its recorded time, not all
future uploads. FIT end time assigns the whole activity to a half-open week.
Once frozen, late arrivals cannot silently change this week's model input.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from skills._shared.fit_weekly import (
    fit_detail,
    fit_parse,
    fit_sync,
    fit_time,
    garmin_fit,
    storage,
    sync_calendar,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_weekly_evidence_v1.schema.json"
)
SCHEMAS = {
    "fit-summary-1": "fit_weekly_evidence_v1",
    "fit-summary-2": "fit_weekly_evidence_v2",
    "fit-summary-3": "fit_weekly_evidence_v3",
}


def content_sha(value: dict[str, Any]) -> str:
    return storage.digest(storage.canonical(value).encode())


def completed_sync(
    db: sqlite3.Connection, root: Path, job: str, slot: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = "fit-sync:" + storage.digest(job.encode())
    request = fit_sync.document(db, key + ":request")
    done = fit_sync.document(db, key + ":complete")
    inventory = fit_sync.document(db, "inventory:" + job)
    if request is None or done is None or inventory is None:
        raise ValueError("weekly_sync_incomplete")
    spec_data = request["request"]
    spec = fit_sync.read_request(request)
    req = spec.inventory
    start_day, end_day = (
        sync_calendar.utc_time(slot[x])
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
        for x in ("start_utc", "end_utc")
    )
    if (
        req.key != job
        or req.start_date > start_day
        or req.end_date < end_day
        or sync_calendar.utc_time(req.as_of_utc)
        < sync_calendar.utc_time(slot["end_utc"])
    ):
        raise ValueError("weekly_sync_coverage_invalid")
    if (
        done["schema_version"] != "fit_sync_receipt_v1"
        or done["status"] != "complete"
        or done["job_key"] != job
        or inventory["schema_version"] != "fit_inventory_receipt_v1"
        or inventory["job_key"] != job
        or inventory["inventory_complete"] is not True
        or done["external_actions"] != 0
        or inventory["external_actions"] != 0
        or fit_sync.document(db, key + ":blocked") is not None
    ):
        raise ValueError("weekly_sync_incomplete")
    stored_request = db.execute(
        "SELECT input_json,input_sha256 FROM sync_jobs WHERE job_key=?", (job,)
    ).fetchone()
    if stored_request is None or tuple(stored_request) != (
        storage.canonical(spec_data["inventory"]),
        content_sha(spec_data["inventory"]),
    ):
        raise ValueError("weekly_sync_source_conflict")
    # Reconstruct membership from successful pages, not a caller-supplied list.
    rows = db.execute(
        "SELECT c.page,r.content_json,r.content_sha256 FROM sync_results r JOIN sync_calls c USING(job_key,ordinal) WHERE r.job_key=? AND r.status='page' ORDER BY c.page",
        (job,),
    ).fetchall()
    seen: set[str] = set()
    items = []
    more = True
    for n, row in enumerate(rows):
        if row[0] != n or not more or storage.digest(row[1].encode()) != row[2]:
            raise ValueError("weekly_sync_source_conflict")
        page = sync_calendar.valid_page(json.loads(row[1]), req, n, seen)
        items.extend(page["items"])
        seen.update(i["activity_ref"] for i in page["items"])
        more = page["has_more"]
    items.sort(key=lambda i: (i["activity_date"], i["activity_ref"]))
    if more or inventory["items"] != items or inventory["activity_count"] != len(items):
        raise ValueError("weekly_sync_source_conflict")
    projected = [
        {k: m[k] for k in ("activity_ref", "activity_date")} for m in done["members"]
    ]
    if projected != items or done["activity_count"] != len(items):
        raise ValueError("weekly_sync_source_conflict")
    available = sum(m["status"] == "available" for m in done["members"])
    missing = sum(m["status"] == "no_fit" for m in done["members"])
    if available + missing != len(items) or (
        done["fit_count"],
        done["no_fit_count"],
    ) != (available, missing):
        raise ValueError("weekly_sync_source_conflict")
    journal = fit_sync.Journal(db, root, spec)
    if (
        journal.artifacts() != done["files"]
        or journal.counts() != done["provider_calls"]
    ):
        raise ValueError("weekly_sync_source_conflict")
    for m in done["members"]:
        if m["status"] == "available":
            raw = fit_detail.fit_bytes(db, root, m["activity_ref"], m["sha256"])
            if (
                len(raw) != m["byte_size"]
                or m["relative_path"] != f"fits/{m['sha256']}.fit"
            ):
                raise ValueError("weekly_sync_source_conflict")
    sources = {
        "sync_job_key": job,
        "sync_request_sha256": content_sha(request),
        "sync_receipt_sha256": content_sha(done),
        "inventory_receipt_sha256": content_sha(inventory),
        "inventory_as_of_utc": req.as_of_utc,
        "inventory_start_date": req.start_date,
        "inventory_end_date": req.end_date,
        "inventory_complete": True,
    }
    return done, sources


def validate(body: dict[str, Any]) -> None:
    version = fit_parse.require_parser_version(body.get("parser_version", ""))
    resource = Resource.from_contents(
        json.loads(fit_parse.schema_path(version).read_text())
    )
    registry: Registry = Registry().with_resource(
        "urn:trainlab:" + fit_parse.SCHEMAS[version], resource
    )
    try:
        jsonschema.Draft202012Validator(
            json.loads(
                SCHEMA_PATH.with_name(f"{SCHEMAS[version]}.schema.json").read_text()
            ),
            registry=registry,
            format_checker=jsonschema.FormatChecker(),
        ).validate(body)
        slot = sync_calendar.weekly_slot(body["period_end_utc"])
        if (
            slot["end_utc"] != body["period_end_utc"]
            or slot["start_utc"] != body["period_start_utc"]
            or slot["plan_dates"] != body["next_plan_dates"]
            or len(body["activities"]) != len(body["activity_sources"])
        ):
            raise ValueError("binding")
        refs = []
        for activity, source in zip(body["activities"], body["activity_sources"]):
            refs.append(activity["activity_ref"])
            if (
                not sync_calendar.in_week(activity["end_utc"], slot)
                or source["activity_ref"] != activity["activity_ref"]
                or source["fit_sha256"] != activity["fit_sha256"]
                or source["parse_sha256"] != content_sha(activity)
            ):
                raise ValueError("binding")
        no_fit_refs = [m["activity_ref"] for m in body["unplaced_no_fit"]]
        if len(set(refs + no_fit_refs)) != len(refs + no_fit_refs):
            raise ValueError("duplicate")
        if body["counts"]["activities_with_fit"] != len(refs) or body["counts"][
            "unplaced_no_fit"
        ] != len(no_fit_refs):
            raise ValueError("count")
    except (jsonschema.ValidationError, KeyError, TypeError, ValueError):
        raise ValueError("weekly_evidence_invalid") from None


def missing_name() -> dict[str, Any]:
    return {"status": "missing", "value": None, "source": None}


def activity_names(db: sqlite3.Connection, root: Path, job: str) -> dict[str, Any]:
    """Project only names from captures matching the accepted inventory pages."""
    request = fit_sync.document(
        db, "fit-sync:" + storage.digest(job.encode()) + ":request"
    )
    if request is None:
        raise ValueError("weekly_name_source_invalid")
    spec = fit_sync.read_request(request)
    journal = fit_sync.Journal(db, root, spec)
    rows = db.execute(
        "SELECT c.request_json,r.content_json,r.content_sha256 FROM sync_calls c JOIN sync_results r USING(job_key,ordinal) WHERE c.job_key=? AND r.status='page' ORDER BY c.page",
        (job,),
    ).fetchall()
    names: dict[str, Any] = {}
    for row in rows:
        args = json.loads(row[0])
        accepted = json.loads(row[1])
        cached = journal.cached("inventory", args)
        if (
            cached is None
            or storage.digest(row[1].encode()) != row[2]
            or cached["value"] != accepted
        ):
            raise ValueError("weekly_name_source_invalid")
        intent = cached["intent"]
        if intent["tool"] != "get_activities_by_date" or intent["job_key"] != job:
            raise ValueError("weekly_name_source_invalid")
        raw_path = journal.directory(intent) / "response.mcp"
        storage.private_entry(raw_path, nonempty=True)
        raw = raw_path.read_bytes()
        projected = garmin_fit.inventory_page(
            raw, args["start_date"], args["end_date"], args["page"], args["page_size"]
        )
        if projected != accepted:
            raise ValueError("weekly_name_source_invalid")
        for index, item in enumerate(garmin_fit.strict_object(raw)["activities"]):
            ref = str(item["id"])
            if ref in names:
                raise ValueError("weekly_name_source_invalid")
            value = item.get("name")
            status = (
                "available"
                if isinstance(value, str) and value.strip()
                else "missing"
                if value is None or isinstance(value, str)
                else "insufficient_data"
            )
            names[ref] = {
                "status": status,
                "value": value if status == "available" else None,
                "source": {
                    "kind": "garmin_mcp_inventory",
                    "field": "activities[].name",
                    "capture_sha256": storage.digest(raw),
                    "intent_sha256": content_sha(intent),
                    "page": args["page"],
                    "item_index": index,
                },
            }
    return names


def verify_name_sources(
    db: sqlite3.Connection, root: Path, body: dict[str, Any]
) -> None:
    if body["parser_version"] not in fit_parse.LOCATION_VERSIONS:
        return
    _, sources = completed_sync(
        db,
        root,
        body["sources"]["sync_job_key"],
        sync_calendar.weekly_slot(body["period_end_utc"]),
    )
    if body["sources"] != sources:
        raise ValueError("weekly_name_source_invalid")
    names = activity_names(db, root, sources["sync_job_key"])
    for source in [*body["activity_sources"], *body["unplaced_no_fit"]]:
        if source["activity_name"] != names.get(source["activity_ref"], missing_name()):
            raise ValueError("weekly_name_source_invalid")


def freeze(root: Path, period_end: str, sync_job_key: str) -> dict[str, Any]:
    _, slot = fit_detail.period_key(period_end)
    if not isinstance(sync_job_key, str):
        raise ValueError("weekly_sync_incomplete")
    key = "weekly-evidence:" + period_end
    with storage.open_store(root) as db:
        done, sources = completed_sync(db, root, sync_job_key, slot)
        old = fit_detail.get(db, key)
        if old is not None:
            body = old[1]
            validate(body)
            if old[0] != content_sha(body) or body["sources"] != sources:
                raise ValueError("weekly_evidence_frozen_conflict")
            verify_name_sources(db, root, body)
            # Only the original chosen FITs are adopted on replay. New arrivals
            # cannot rewrite this freeze, but source drift must still stop it.
            for activity in body["activities"]:
                parsed = fit_parse.parse_registered(
                    db,
                    root,
                    activity["activity_ref"],
                    activity["fit_sha256"],
                    parser_version=body["parser_version"],
                )
                if parsed != activity:
                    raise ValueError("weekly_evidence_source_drift")
            return body
        storage.verify_fit_closure(db, root)
        names = (
            activity_names(db, root, sync_job_key)
            if fit_parse.VERSION in fit_parse.LOCATION_VERSIONS
            else None
        )
        members = {m["activity_ref"]: m for m in done["members"]}
        rows = db.execute(
            "SELECT activity_ref,fit_sha256 FROM activity_fits ORDER BY activity_ref,fit_sha256"
        ).fetchall()
        revision_counts = Counter(row[0] for row in rows)
        activities = []
        activity_sources = []
        for ref, sha in rows:
            parsed = fit_parse.parse_registered(db, root, ref, sha)
            if not sync_calendar.in_week(parsed["end_utc"], slot):
                continue
            if revision_counts[ref] != 1:
                raise ValueError("weekly_activity_revision_conflict")
            member = members.get(ref)
            if member is not None and (
                member["status"] != "available" or member["sha256"] != sha
            ):
                raise ValueError("weekly_sync_source_conflict")
            activities.append(parsed)
            activity_sources.append(
                {
                    "activity_ref": ref,
                    "fit_sha256": sha,
                    "parse_sha256": content_sha(parsed),
                    "inventory_membership": "current_sync"
                    if member is not None
                    else "registered_fit_only",
                    **(
                        {"activity_name": names.get(ref, missing_name())}
                        if names is not None
                        else {}
                    ),
                }
            )
        ordered = sorted(
            zip(activities, activity_sources),
            key=lambda pair: (
                fit_time.utc_time(pair[0]["end_utc"]),
                pair[0]["activity_ref"],
            ),
        )
        activities = [pair[0] for pair in ordered]
        activity_sources = [pair[1] for pair in ordered]
        # Without FIT there is no trusted end time. Keep these inventory rows
        # explicitly unplaced rather than guessing a period or zero metrics.
        no_fit = [
            {
                "activity_ref": m["activity_ref"],
                "inventory_date": m["activity_date"],
                "reason": "provider_no_fit_end_unknown",
                **(
                    {"activity_name": names.get(m["activity_ref"], missing_name())}
                    if names is not None
                    else {}
                ),
            }
            for m in done["members"]
            if m["status"] == "no_fit"
        ]
        body = {
            "schema_version": SCHEMAS[fit_parse.VERSION],
            "parser_version": fit_parse.VERSION,
            "period_start_utc": slot["start_utc"],
            "period_end_utc": period_end,
            "next_plan_dates": slot["plan_dates"],
            "sources": sources,
            "activities": activities,
            "activity_sources": activity_sources,
            "unplaced_no_fit": no_fit,
            "counts": {
                "activities_with_fit": len(activities),
                "unplaced_no_fit": len(no_fit),
                "sync_inventory": done["activity_count"],
            },
            "limitations": [
                "inventory_is_as_of_snapshot",
                "registered_fit_end_time_membership",
                "no_fit_end_time_unknown",
                "late_data_does_not_rewrite_frozen_week",
            ],
            "provider_calls": 0,
            "external_actions": 0,
        }
        validate(body)
        storage.put_document(db, "weekly_input", key, content_sha(body), body)
        return body
