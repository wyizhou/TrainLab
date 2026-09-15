"""Byte-bound Markdown/PDF artifacts and an irreversible local publication seal.

R5 must seal once BEFORE any delivery intent, then consume read_sealed for every
channel. This module performs no delivery, retries, scheduling or provider calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_detail,
    model_job,
    report_markdown,
    report_pdf,
    report_revisions,
    storage,
)
from skills._shared.scripts.schema_validation import validate_payload


@dataclass(frozen=True)
class Bundle:
    revision: dict[str, Any]
    manifest: dict[str, Any]
    plan: dict[str, Any]
    markdown: bytes
    pdf: bytes


def key(end: str, revision_id: str) -> str:
    report_revisions.key(end, revision_id)
    return f"report-artifacts:{end}:{revision_id}"


def directory(root: Path, revision_sha: str, *, create: bool = False) -> Path:
    storage.require_sha(revision_sha)
    storage.private_entry(root, directory=True)
    for path in (root / "reports", root / "reports" / revision_sha):
        if create and not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
            storage.sync_dir(path.parent)
        storage.private_entry(path, directory=True)
    return root / "reports" / revision_sha


def check_manifest(
    body: dict[str, Any], end: str, revision_id: str, revision_sha: str
) -> None:
    if validate_payload(body, "fit_report_artifacts_v1") or (
        body["period_end_utc"] != end
        or body["revision_id"] != revision_id
        or body["revision_sha256"] != revision_sha
    ):
        raise ValueError("report_artifact_manifest_invalid")


def bytes_for(root: Path, manifest: dict[str, Any]) -> tuple[bytes, bytes]:
    path = directory(root, manifest["revision_sha256"])
    values = []
    for name, field in (("report.md", "markdown"), ("report.pdf", "pdf")):
        storage.private_entry(path / name, nonempty=True)
        value = (path / name).read_bytes()
        if storage.digest(value) != manifest[field + "_sha256"]:
            raise ValueError("report_artifact_sha_invalid")
        values.append(value)
    return values[0], values[1]


def render(root: Path, end: str, revision_id: str, revision_sha: str) -> dict[str, Any]:
    view = report_revisions.view(root, end, revision_id, revision_sha)
    with storage.open_store(root) as db:
        old = fit_detail.get(db, key(end, revision_id))
        if old is not None:
            check_manifest(old[1], end, revision_id, revision_sha)
            if old[0] != revision_sha:
                raise ValueError("report_artifact_manifest_invalid")
            try:
                bytes_for(root, old[1])
                return old[1]
            except ValueError:
                # Only absent regular artifacts can be regenerated below.
                # Existing wrong bytes/permissions/links fail atomic_file.
                pass
        report_revisions.require_unsealed(db, end)
        markdown = report_markdown.render(view)
        pdf = report_pdf.render(view)
        manifest = {
            "schema_version": "fit_report_artifacts_v1",
            "period_end_utc": end,
            "revision_id": revision_id,
            "revision_sha256": revision_sha,
            "effective_plan_sha256": view["effective_plan_sha256"],
            "view_sha256": model_job.sha(view),
            "renderer_sha256": report_pdf.identity(),
            "markdown_sha256": storage.digest(markdown),
            "pdf_sha256": storage.digest(pdf),
        }
        check_manifest(manifest, end, revision_id, revision_sha)
        if old is not None and old != (revision_sha, manifest):
            raise ValueError("report_artifact_recovery_conflict")
        path = directory(root, revision_sha, create=True)
        storage.atomic_file(path / "report.md", markdown)
        storage.atomic_file(path / "report.pdf", pdf)
        fit_detail.put(db, key(end, revision_id), revision_sha, manifest)
        return manifest


def read(root: Path, end: str, revision_id: str, revision_sha: str) -> Bundle:
    revision = report_revisions.read(root, end, revision_id, revision_sha)
    view = report_revisions.view(root, end, revision_id, revision_sha)
    with storage.open_store(root) as db:
        saved = fit_detail.get(db, key(end, revision_id))
        if saved is None or saved[0] != revision_sha:
            raise ValueError("report_artifacts_missing")
        manifest = saved[1]
        check_manifest(manifest, end, revision_id, revision_sha)
        if manifest["effective_plan_sha256"] != view[
            "effective_plan_sha256"
        ] or manifest["view_sha256"] != model_job.sha(view):
            raise ValueError("report_artifact_view_invalid")
        markdown, pdf = bytes_for(root, manifest)
    return Bundle(revision, manifest, view["plan"], markdown, pdf)


def seal(root: Path, end: str, revision_id: str, revision_sha: str) -> dict[str, Any]:
    bundle = read(root, end, revision_id, revision_sha)
    body = {
        "schema_version": "fit_report_publication_v1",
        "period_end_utc": end,
        "revision_id": revision_id,
        "revision_sha256": revision_sha,
        "artifacts_sha256": model_job.sha(bundle.manifest),
        "markdown_sha256": bundle.manifest["markdown_sha256"],
        "pdf_sha256": bundle.manifest["pdf_sha256"],
        "effective_plan_sha256": bundle.manifest["effective_plan_sha256"],
    }
    if validate_payload(body, "fit_report_publication_v1"):
        raise ValueError("report_publication_schema_invalid")
    # Same writer lock as edit/manifest commits; no window for a competing
    # version to replace the selection. All later action ledgers key this seal.
    with storage.open_store(root) as db:
        bytes_for(root, bundle.manifest)
        fit_detail.put(
            db, report_revisions.publication_key(end), model_job.sha(body), body
        )
    return body


def read_sealed(root: Path, end: str) -> Bundle:
    with storage.open_store(root) as db:
        saved = fit_detail.get(db, report_revisions.publication_key(end))
    if saved is None or validate_payload(saved[1], "fit_report_publication_v1"):
        raise ValueError("report_publication_missing_or_invalid")
    body = saved[1]
    if body["period_end_utc"] != end or saved[0] != model_job.sha(body):
        raise ValueError("report_publication_invalid")
    bundle = read(root, end, body["revision_id"], body["revision_sha256"])
    if body["artifacts_sha256"] != model_job.sha(bundle.manifest) or any(
        body[k] != bundle.manifest[k]
        for k in ("markdown_sha256", "pdf_sha256", "effective_plan_sha256")
    ):
        raise ValueError("report_publication_binding_invalid")
    return bundle
