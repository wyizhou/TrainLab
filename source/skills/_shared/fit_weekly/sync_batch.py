from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import fit_sync, storage


def read(root: Path, key: str) -> dict[str, Any] | None:
    with storage.open_store(root) as db:
        saved = fit_sync.document(db, key + ":sealed")
        if saved is None:
            return None
        request = fit_sync.document(db, key + ":request")
        if request is None or saved["request_sha256"] != storage.digest(
            storage.canonical(request).encode()
        ):
            raise ValueError("sync_batch_request_conflict")
        for segment in saved["segments"]:
            for source in segment["sources"]:
                value = fit_sync.document(db, source["key"])
                if (
                    value is None
                    or storage.digest(storage.canonical(value).encode())
                    != source["sha256"]
                ):
                    raise ValueError("sync_batch_source_conflict")
        return saved


def seal(root: Path, key: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    from skills._shared.fit_weekly import publication

    for segment in segments:
        try:
            actual = publication.sync_snapshot(root, segment["job_key"])
        except ValueError as exc:
            if str(exc) != "publication_sync_source_missing":
                raise
            actual = None
        if actual != segment["snapshot"]:
            raise ValueError("sync_batch_snapshot_conflict")
    with storage.open_store(root) as db:
        request = fit_sync.document(db, key + ":request")
        if request is None or len(segments) != len(request["specs"]):
            raise ValueError("sync_batch_request_missing")
        rows = []
        for spec_value, segment in zip(request["specs"], segments, strict=True):
            spec = fit_sync.read_request(
                {"schema_version": "fit_sync_request_v2", "request": spec_value}
            )
            job = spec.inventory.key
            if segment["job_key"] != job:
                raise ValueError("sync_batch_segment_conflict")
            prefix = "fit-sync:" + storage.digest(job.encode())
            original = fit_sync.document(db, prefix + ":request")
            if original is not None and fit_sync.read_request(original) != spec:
                raise ValueError("sync_batch_segment_conflict")
            sources = []
            calls = []
            for logical_key, content in db.execute(
                "SELECT logical_key,content_json FROM documents WHERE kind='sync_receipt' AND (substr(logical_key,1,?)=? OR logical_key=?) ORDER BY logical_key",
                (len(prefix + ":"), prefix + ":", "inventory:" + job),
            ):
                value = json.loads(content)
                if fit_sync.document(db, logical_key) != value:
                    raise ValueError("sync_batch_source_conflict")
                sources.append(
                    {
                        "key": logical_key,
                        "sha256": storage.digest(storage.canonical(value).encode()),
                    }
                )
                if value.get("schema_version") == "fit_transport_intent_v1":
                    outcome = fit_sync.document(
                        db, f"{prefix}:outcome:{value['ordinal']}"
                    )
                    calls.append(
                        {
                            "kind": value["call_kind"],
                            "ordinal": value["ordinal"],
                            "outcome": outcome,
                        }
                    )
            done = fit_sync.document(db, prefix + ":complete")
            if (segment["status"] == "complete") != (done is not None):
                raise ValueError("sync_batch_completion_conflict")
            rows.append({**segment, "sources": sources, "calls": calls})
        result = {
            "schema_version": "fit_sync_batch_receipt_v1",
            "batch_key": key,
            "request_sha256": storage.digest(storage.canonical(request).encode()),
            "dates": request["dates"],
            "status": "complete"
            if all(s["status"] == "complete" for s in rows)
            else "failed",
            "segments": rows,
        }
        fit_sync.put(db, key + ":sealed", result)
        return result
