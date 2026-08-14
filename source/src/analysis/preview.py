"""Read-only local previews for already persisted analysis deliveries.

The preview boundary deliberately has no delivery writer and no provider
dependency.  It reads the immutable artifact revisions linked to one delivery
from a SQLite read-only connection, reuses the normal escaped renderer, and
writes two owner-only files outside the TrainLab instance root.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ..util import atomic_write_json
from .delivery import (
    AnalysisDeliveryRepository,
    RenderedDelivery,
)


class PreviewError(ValueError):
    """Controlled failure for a local, non-delivery preview."""


def _owner_only_directory(path: Path, *, create: bool = False) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        info = path.lstat()
    except OSError as error:
        raise PreviewError("analysis_preview_output_directory_missing") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PreviewError("analysis_preview_output_directory_unsafe")
    return path


def _safe_output_directory(root: Path, output_dir: Path) -> Path:
    if not output_dir.is_absolute():
        raise PreviewError("analysis_preview_output_directory_absolute_required")
    resolved_root = root.resolve()
    resolved_output = output_dir.resolve(strict=False)
    if resolved_output == resolved_root or resolved_root in resolved_output.parents:
        raise PreviewError("analysis_preview_output_inside_instance_forbidden")
    return _owner_only_directory(resolved_output, create=True)


def _atomic_text(path: Path, value: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _artifact_payload(artifact: Any) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_kind": artifact.artifact_kind,
        "content_role": artifact.content_role,
        "revision_no": artifact.revision_no,
        "content_sha256": artifact.content_sha256,
        "period_start_local_date": artifact.period_start_local_date,
        "period_end_local_date": artifact.period_end_local_date,
        "structured_content": artifact.structured_content_json,
        "user_visible_text": artifact.user_visible_text,
        "created_at_utc": artifact.created_at_utc,
    }


def _named_values(value: object, names: set[str]) -> list[object]:
    found: list[object] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in names:
                found.append(child)
            found.extend(_named_values(child, names))
    elif isinstance(value, list):
        for child in value:
            found.extend(_named_values(child, names))
    return found


def _preview_json(
    *, pending: Any, state: Any, rendered: RenderedDelivery
) -> dict[str, object]:
    structured = [artifact.structured_content_json for artifact in pending.artifacts]
    capacities = _named_values(structured, {"capacity_assessment"})
    contracts = _named_values(structured, {"course_contract", "course_contract_v2"})
    decisions = _named_values(
        structured,
        {
            "hard_load_decision",
            "progression_decision",
            "safety_decision",
            "stop_conditions",
        },
    )
    return {
        "schema_version": "1",
        "preview_only": True,
        "delivery": {
            "delivery_id": pending.delivery_id,
            "delivery_kind": pending.delivery_kind,
            "status": state.status,
            "run_key": pending.run_key,
            "analysis_run_id": pending.analysis_run_id,
            "subject_id": pending.subject_id,
        },
        "artifacts": [_artifact_payload(item) for item in pending.artifacts],
        "course_contracts": contracts,
        "capacity_assessments": capacities,
        "safety_decisions": decisions,
        "rendered": {
            "subject": rendered.subject,
            "headers": dict(rendered.headers),
            "plain_text": rendered.plain_text,
        },
        "side_effects": {
            "delivery_state_changed": False,
            "gmail_called": False,
            "garmin_called": False,
            "formal_instance_written": False,
        },
    }


def render_delivery_preview(
    root: Path,
    delivery_id: int,
    output_dir: Path,
) -> dict[str, object]:
    """Render one persisted delivery without changing its database state."""

    if (
        isinstance(delivery_id, bool)
        or not isinstance(delivery_id, int)
        or delivery_id <= 0
    ):
        raise PreviewError("analysis_preview_delivery_id_invalid")
    instance = root.resolve()
    output = _safe_output_directory(instance, output_dir)
    database = instance / "state" / "data.db"
    if not database.is_file() or database.is_symlink():
        raise PreviewError("analysis_preview_database_missing")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        try:
            repository = AnalysisDeliveryRepository(connection)
            pending = repository.load_pending(delivery_id)
            state = repository.read_state(delivery_id)
            rendered = repository.load_rendered(delivery_id)
            payload = _preview_json(
                pending=pending,
                state=state,
                rendered=rendered,
            )
        except (RuntimeError, sqlite3.Error) as error:
            raise PreviewError("analysis_preview_delivery_invalid") from error
    finally:
        connection.close()
    report_json = output / "report.json"
    report_html = output / "report.html"
    atomic_write_json(report_json, payload)
    _atomic_text(report_html, rendered.html)
    os.chmod(report_json, 0o600)
    os.chmod(report_html, 0o600)
    return {
        "schema_version": "1",
        "status": "succeeded",
        "delivery_id": delivery_id,
        "delivery_status": state.status,
        "output_dir": str(output),
        "report_json": str(report_json),
        "report_html": str(report_html),
        "delivery_state_changed": False,
        "provider_calls": {"gmail": 0, "garmin": 0},
    }


def create_isolated_preview_instance(
    source_root: Path, destination: Path
) -> dict[str, object]:
    """Create an owner-only analysis clone using a consistent SQLite backup.

    Only the analysis config and Foundation schema config are copied.  Garmin
    config, credentials, raw files, FIT files and logs are intentionally not
    copied.  The destination must be outside the source instance and empty.
    """

    source = source_root.resolve()
    target = destination.resolve(strict=False)
    if target == source or source in target.parents:
        raise PreviewError("analysis_preview_clone_inside_source_forbidden")
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise PreviewError("analysis_preview_clone_destination_not_empty")
    else:
        target.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    for name in ("config", "state", "logs"):
        path = target / name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    for name in ("locks", "tmp", "coaching-profile"):
        path = target / "state" / name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    for name in ("trainlab.json", "foundation.yaml"):
        source_file = source / "config" / name
        if not source_file.is_file() or source_file.is_symlink():
            raise PreviewError(f"analysis_preview_config_missing:{name}")
        destination_file = target / "config" / name
        shutil.copyfile(source_file, destination_file)
        destination_file.chmod(0o600)
    source_database = source / "state" / "data.db"
    destination_database = target / "state" / "data.db"
    if not source_database.is_file() or source_database.is_symlink():
        raise PreviewError("analysis_preview_source_database_missing")
    with sqlite3.connect(
        f"file:{source_database}?mode=ro", uri=True
    ) as source_connection:
        with sqlite3.connect(destination_database) as destination_connection:
            source_connection.backup(destination_connection)
    destination_database.chmod(0o600)
    return {
        "status": "succeeded",
        "instance_root": str(target),
        "database_copied": True,
        "credentials_copied": False,
        "garmin_config_copied": False,
    }
