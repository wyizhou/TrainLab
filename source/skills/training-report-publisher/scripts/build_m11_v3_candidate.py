#!/usr/bin/env python3
"""Build the owner-only M11 v3 offline design-fidelity Candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

SOURCE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE_ROOT))

from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
)

PERIOD_START = date(2026, 8, 12)
PERIOD_END = date(2026, 8, 18)
DAILY_OUTPUT_IDS = tuple(range(85, 92))
WEEKLY_OUTPUT_ID = 92
FROZEN_OUTPUT_IDS = tuple(range(84, 94))
RECEIPT_NAME = "build-receipt.json"
CANDIDATE_OPERATION = "render_weekly"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
FROZEN_OUTPUT_CONTRACT: dict[int, dict[str, Any]] = {
    84: {
        "output_kind": "training_plan",
        "logical_key": "training-coach:bootstrap-v2-r03:2026-08-12/2026-08-18",
        "period_start_date": "2026-08-12",
        "period_end_date": "2026-08-18",
        "schema_name": "training_plan_v2",
        "schema_version": "2",
        "content_sha256": "1d225af3c7b3a046277bb99a5d3f14c282277cfa48c3ae566995e2d4377a0f33",
        "skill_name": "training-coach",
        "operation": "validate_plan",
    },
    **{
        output_id: {
            "output_kind": "daily_summary",
            "logical_key": f"training-coach:ai:daily-v2:2026-08-{12 + index:02d}",
            "period_start_date": f"2026-08-{12 + index:02d}",
            "period_end_date": f"2026-08-{12 + index:02d}",
            "schema_name": "daily_ai_result_v2",
            "schema_version": "2",
            "content_sha256": digest,
            "skill_name": "training-coach",
            "operation": "daily_coach",
        }
        for index, (output_id, digest) in enumerate(
            (
                (
                    85,
                    "13e0c9614b32807eb8e0c985ee932625d2b777eb62601d906f92223fcf0647d5",
                ),
                (
                    86,
                    "6b1072da091da588a90c597b6b5146cbcc31754fcb0e32770148806cc048a812",
                ),
                (
                    87,
                    "f130096b13a84921326da358a10fcc2198b0d35b936344227d07fc356d298a6c",
                ),
                (
                    88,
                    "9ffc3ed327285e6026a9bb511fbd51c5ddc7275fc48dabeee2970eb0ee4ef1e9",
                ),
                (
                    89,
                    "dfa06e42f5282d116a8ce9791df0e43d780cc3971368aa58d09db21bb5e911ca",
                ),
                (
                    90,
                    "9f160662fc0f1b36c37dd4a3dda9ca160f8e9da7ce9c36fe7b6626a681d03314",
                ),
                (
                    91,
                    "4cba8e85b75dfde74ea897b22608091260273cf633201112d008ff43e66f1f31",
                ),
            )
        )
    },
    92: {
        "output_kind": "weekly_summary",
        "logical_key": "training-coach:ai:weekly-v2:2026-08-12/2026-08-18",
        "period_start_date": "2026-08-12",
        "period_end_date": "2026-08-18",
        "schema_name": "weekly_ai_result_v2",
        "schema_version": "2",
        "content_sha256": "43f6337f191d0ee240077b725a4c28fb920737f232d56f2cedb2e62b54760939",
        "skill_name": "training-coach",
        "operation": "weekly_coach",
    },
    93: {
        "output_kind": "training_plan",
        "logical_key": "training-coach:ai:weekly-v2:2026-08-12/2026-08-18:plan",
        "period_start_date": "2026-08-19",
        "period_end_date": "2026-08-25",
        "schema_name": "training_plan_v2",
        "schema_version": "2",
        "content_sha256": "57043e160db8ee099a88c9d1aad6b8f9d05e997cebe29bad168c26d926c98677",
        "skill_name": "training-coach",
        "operation": "weekly_coach",
    },
}


class CandidateBuildError(ValueError):
    """Stable M11 v3 Candidate construction failure."""


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateBuildError("m11_v3_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[Any, Any, Any, Any, Any]:
    coach = SOURCE_ROOT / "skills/training-coach/scripts"
    publisher = SOURCE_ROOT / "skills/training-report-publisher/scripts"
    gmail = SOURCE_ROOT / "skills/gmail-sender/scripts"
    return (
        _load("trainlab_m11_v3_context", coach / "build_context.py"),
        _load("trainlab_m11_v3_presentation", coach / "presentation_evidence.py"),
        _load("trainlab_m11_v3_view", publisher / "email_view_v3.py"),
        _load("trainlab_m11_v3_renderer", publisher / "email_design_renderer.py"),
        _load("trainlab_m11_v3_mime", gmail / "gmail_readable_delivery.py"),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_owner_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise CandidateBuildError("m11_v3_directory_invalid")
    os.chmod(path, 0o700)


def _atomic_owner_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise CandidateBuildError("m11_v3_artifact_empty")
    _ensure_owner_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _require_owner_file(path: Path, error: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CandidateBuildError(error) from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size <= 0
    ):
        raise CandidateBuildError(error)
    return metadata


def _copy_owner_file(
    source: Path,
    target: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    metadata = _require_owner_file(source, "m11_v3_registered_raw_invalid")
    if metadata.st_size != expected_size or not HEX_64.fullmatch(expected_sha256):
        raise CandidateBuildError("m11_v3_registered_raw_invalid")
    _ensure_owner_directory(target.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    copied = 0
    try:
        os.fchmod(descriptor, 0o600)
        with (
            source.open("rb") as source_handle,
            os.fdopen(descriptor, "wb") as target_handle,
        ):
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                target_handle.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        source_after = source.lstat()
        if (
            source_after.st_ino != metadata.st_ino
            or source_after.st_size != metadata.st_size
            or source_after.st_mtime_ns != metadata.st_mtime_ns
            or copied != expected_size
            or digest.hexdigest() != expected_sha256
        ):
            raise CandidateBuildError("m11_v3_registered_raw_changed")
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_only(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"file:{quote(str(database.resolve()), safe='/')}?mode=ro&immutable=1",
        uri=True,
    )


def frozen_output_digest(
    database: Path, output_ids: Iterable[int]
) -> dict[str, dict[str, str]]:
    ids = tuple(int(value) for value in output_ids)
    if not ids or any(value not in FROZEN_OUTPUT_CONTRACT for value in ids):
        raise CandidateBuildError("m11_v3_frozen_output_ids_empty")
    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT so.id,so.output_kind,so.logical_key,so.revision_no,"
            "so.period_start_date,so.period_end_date,so.schema_name,so.schema_version,"
            "so.title_text,so.content_json,so.content_text,so.content_html,"
            "so.lineage_json,so.content_sha256,sr.skill_name,sr.operation,sr.status "
            "FROM skill_outputs so JOIN skill_runs sr ON sr.id=so.skill_run_id "
            f"WHERE so.id IN ({','.join('?' for _ in ids)}) ORDER BY so.id",
            ids,
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != len(ids) or {int(row[0]) for row in rows} != set(ids):
        raise CandidateBuildError("m11_v3_frozen_output_missing")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        output_id = int(row[0])
        content = str(row[9])
        content_sha = str(row[13])
        if not content or not HEX_64.fullmatch(content_sha):
            raise CandidateBuildError("m11_v3_frozen_output_invalid")
        try:
            payload = json.loads(content)
            lineage = json.loads(str(row[12]))
        except json.JSONDecodeError as exc:
            raise CandidateBuildError("m11_v3_frozen_output_invalid") from exc
        recomputed = sha256_text(
            canonical_json(
                {
                    "title": row[8],
                    "json": payload,
                    "text": row[10],
                    "html": row[11],
                    "lineage": lineage,
                }
            )
        )
        observed: dict[str, Any] = {
            "output_kind": str(row[1]),
            "logical_key": str(row[2]),
            "period_start_date": str(row[4]),
            "period_end_date": str(row[5]),
            "schema_name": str(row[6]),
            "schema_version": str(row[7]),
            "content_sha256": content_sha,
            "skill_name": str(row[14]),
            "operation": str(row[15]),
        }
        if (
            observed != FROZEN_OUTPUT_CONTRACT[output_id]
            or int(row[3]) != 1
            or row[8] is not None
            or str(row[16]) != "succeeded"
            or recomputed != content_sha
        ):
            raise CandidateBuildError("m11_v3_frozen_output_contract_mismatch")
        result[str(output_id)] = {
            "schema_name": str(row[6]),
            "content_sha256": content_sha,
            "content_json_sha256": hashlib.sha256(
                canonical_json(payload).encode()
            ).hexdigest(),
        }
    return result


def copy_registered_raw(
    database: Path,
    parent_source_root: Path,
    candidate_source_root: Path,
) -> dict[str, Any]:
    source_raw_root = (parent_source_root / "state/raw").absolute()
    target_raw_root = (candidate_source_root / "state/raw").absolute()
    _ensure_owner_directory(target_raw_root)
    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT id,relative_path,byte_size,sha256 FROM raw_files "
            "WHERE integrity_state='verified' ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise CandidateBuildError("m11_v3_registered_raw_missing")
    manifest: list[dict[str, Any]] = []
    total_bytes = 0
    for raw_id, relative_text, byte_size, sha256 in rows:
        relative = Path(str(relative_text))
        if relative.is_absolute() or ".." in relative.parts:
            raise CandidateBuildError("m11_v3_registered_raw_invalid")
        source = (source_raw_root / relative).absolute()
        target = (target_raw_root / relative).absolute()
        try:
            if (
                source.resolve(strict=True) != source
                or not source.is_relative_to(source_raw_root)
                or not target.is_relative_to(target_raw_root)
            ):
                raise CandidateBuildError("m11_v3_registered_raw_invalid")
        except OSError as exc:
            raise CandidateBuildError("m11_v3_registered_raw_invalid") from exc
        _copy_owner_file(
            source,
            target,
            expected_size=int(byte_size),
            expected_sha256=str(sha256),
        )
        total_bytes += int(byte_size)
        manifest.append(
            {
                "raw_file_id": int(raw_id),
                "relative_path": str(relative),
                "byte_size": int(byte_size),
                "sha256": str(sha256),
            }
        )
    aggregate = sha256_text(canonical_json(manifest))
    return {
        "count": len(manifest),
        "bytes": total_bytes,
        "sha256": aggregate,
        "files": manifest,
    }


def _initialize_root(candidate_root: Path) -> None:
    if candidate_root.is_symlink():
        raise CandidateBuildError("m11_v3_candidate_root_invalid")
    if candidate_root.exists():
        metadata = candidate_root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or any(candidate_root.iterdir())
        ):
            raise CandidateBuildError("m11_v3_candidate_root_exists")
        os.chmod(candidate_root, 0o700)
    else:
        candidate_root.mkdir(mode=0o700)


def _backup_database(parent: Path, target: Path) -> None:
    _require_owner_file(parent, "m11_v3_parent_database_invalid")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(parent) + suffix)
        if sidecar.exists() and sidecar.stat().st_size > 0:
            raise CandidateBuildError("m11_v3_parent_database_sidecar_nonempty")
    _ensure_owner_directory(target.parent)
    temporary = target.parent / f".{target.name}.backup"
    if temporary.exists() or temporary.is_symlink():
        raise CandidateBuildError("m11_v3_candidate_database_temporary_exists")
    source = _read_only(parent)
    destination = sqlite3.connect(temporary)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    temporary.chmod(0o600)
    descriptor = os.open(temporary, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    _fsync_directory(target.parent)


def _copy_goal(parent_source_root: Path, candidate_source_root: Path) -> None:
    source = parent_source_root / "goal.md"
    metadata = _require_owner_file(source, "m11_v3_goal_invalid")
    _copy_owner_file(
        source,
        candidate_source_root / "goal.md",
        expected_size=metadata.st_size,
        expected_sha256=_sha256_file(source),
    )


def _output_rows(database: Path) -> dict[int, dict[str, Any]]:
    ids = (*DAILY_OUTPUT_IDS, WEEKLY_OUTPUT_ID, 93)
    connection = _read_only(database)
    try:
        rows = connection.execute(
            "SELECT id,content_json,content_sha256,schema_name,period_start_date,period_end_date "
            f"FROM skill_outputs WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY id",
            ids,
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != len(ids):
        raise CandidateBuildError("m11_v3_ai_source_missing")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            payload = json.loads(str(row[1]))
        except json.JSONDecodeError as exc:
            raise CandidateBuildError("m11_v3_ai_source_invalid") from exc
        result[int(row[0])] = {
            "payload": payload,
            "sha256": str(row[2]),
            "content_json_sha256": hashlib.sha256(
                canonical_json(payload).encode()
            ).hexdigest(),
            "schema_name": str(row[3]),
            "period_start_date": str(row[4]),
            "period_end_date": str(row[5]),
        }
    if canonical_json(
        result[WEEKLY_OUTPUT_ID]["payload"]["training_plan"]
    ) != canonical_json(result[93]["payload"]):
        raise CandidateBuildError("m11_v3_weekly_plan_binding_invalid")
    return result


def _raw_lineage(presentation: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    candidates: list[dict[str, Any]] = list(presentation["activities"])
    if isinstance(presentation.get("sleep"), dict):
        candidates.append(presentation["sleep"])
    candidates.extend(
        item for item in presentation["health"].values() if isinstance(item, dict)
    )
    for item in candidates:
        raw_id = item.get("raw_file_id")
        raw_sha = item.get("raw_sha256")
        if isinstance(raw_id, int) and isinstance(raw_sha, str):
            identity = (raw_id, raw_sha)
            if identity not in seen:
                refs.append(
                    {
                        "raw_file_id": raw_id,
                        "raw_sha256": raw_sha,
                        "role": "presentation_source",
                    }
                )
                seen.add(identity)
    return refs


def _write_json(path: Path, value: object) -> None:
    _atomic_owner_write(path, (canonical_json(value) + "\n").encode())


def _browser_preview_html(html: str, assets: Iterable[Any]) -> str:
    result = html
    expected = 0
    for asset in assets:
        source = f"cid:{asset.cid}"
        count = result.count(source)
        if count != 1:
            raise CandidateBuildError("m11_v3_browser_preview_cid_invalid")
        result = result.replace(source, f"assets/{asset.filename}")
        expected += 1
    if result.count("cid:") != 0 or result.count("assets/") != expected:
        raise CandidateBuildError("m11_v3_browser_preview_cid_invalid")
    return result


def _write_bundle(
    root: Path,
    *,
    presentation: dict[str, Any] | None,
    view: dict[str, Any],
    rendered: Any,
) -> None:
    _ensure_owner_directory(root)
    if presentation is not None:
        _write_json(root / "presentation-evidence.json", presentation)
    _write_json(root / "view.json", view)
    _write_json(root / "render.json", rendered.payload)
    _atomic_owner_write(root / "report.html", str(rendered.payload["html"]).encode())
    _atomic_owner_write(
        root / "browser-preview.html",
        _browser_preview_html(str(rendered.payload["html"]), rendered.assets).encode(),
    )
    _atomic_owner_write(root / "report.txt", str(rendered.payload["text"]).encode())
    asset_root = root / "assets"
    _ensure_owner_directory(asset_root)
    for asset in rendered.assets:
        if hashlib.sha256(asset.data).hexdigest() != asset.sha256:
            raise CandidateBuildError("m11_v3_asset_sha_mismatch")
        _atomic_owner_write(asset_root / asset.filename, asset.data)


def _output_sha(connection: sqlite3.Connection, output_id: int) -> str:
    row = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
    ).fetchone()
    if row is None or not HEX_64.fullmatch(str(row[0])):
        raise CandidateBuildError("m11_v3_output_missing")
    return str(row[0])


def _preview_manifest(
    raw_manifest: dict[str, Any],
    frozen_before: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "period": f"{PERIOD_START.isoformat()}/{PERIOD_END.isoformat()}",
        "frozen_outputs": frozen_before,
        "raw_manifest_sha256": raw_manifest["sha256"],
        "provider_calls": 0,
        "external_actions": 0,
    }


def _checkpoint_candidate(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.commit()


def _clean_candidate_sidecars(database: Path) -> None:
    wal = Path(str(database) + "-wal")
    if wal.exists() and wal.stat().st_size != 0:
        raise CandidateBuildError("m11_v3_candidate_wal_nonempty")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    _fsync_directory(database.parent)


def _append_presentations(
    database: Path,
    source_rows: dict[int, dict[str, Any]],
    presentations: list[dict[str, Any]],
    raw_manifest: dict[str, Any],
    frozen_before: dict[str, dict[str, str]],
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    connection = connect(database)
    output_records: list[dict[str, Any]] = []
    try:
        manifest = _preview_manifest(raw_manifest, frozen_before)
        dedupe = sha256_text(canonical_json(manifest))
        run_id = begin_run(
            connection,
            run_key=f"m11:v3:offline-preview:{dedupe}:attempt-1",
            workflow_key="m11:v3:offline-preview:2026-08-12/2026-08-18",
            dedupe_key=dedupe,
            skill_name="training-report-publisher",
            operation=CANDIDATE_OPERATION,
            trigger_kind="skill",
            input_manifest=manifest,
            target_from_date=PERIOD_START.isoformat(),
            target_through_date=PERIOD_END.isoformat(),
        )
        presentation_refs: list[dict[str, Any]] = []
        for index, presentation in enumerate(presentations):
            source_id = DAILY_OUTPUT_IDS[index]
            source_sha = str(source_rows[source_id]["sha256"])
            day = str(presentation["report_date"])
            evidence_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="bounded_evidence",
                logical_key=f"training-coach:presentation-v3:daily:{day}",
                schema_name="daily_presentation_evidence_v1",
                schema_version="1",
                content_json=presentation,
                content_text=canonical_json(presentation),
                lineage=[
                    {
                        "output_id": source_id,
                        "output_sha256": source_sha,
                        "role": "ai_source",
                    },
                    *_raw_lineage(presentation),
                ],
                period_start_date=day,
                period_end_date=day,
            )
            evidence_sha = _output_sha(connection, evidence_id)
            presentation_refs.append(
                {
                    "report_date": day,
                    "output_id": evidence_id,
                    "sha256": evidence_sha,
                    "content_json_sha256": hashlib.sha256(
                        canonical_json(presentation).encode()
                    ).hexdigest(),
                }
            )
            output_records.append(
                {
                    "id": evidence_id,
                    "schema_name": "daily_presentation_evidence_v1",
                    "sha256": evidence_sha,
                }
            )
        _checkpoint_candidate(connection)
    finally:
        connection.close()
    return run_id, output_records, presentation_refs


def _load_persisted_presentations(
    database: Path, refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    connection = _read_only(database)
    result: list[dict[str, Any]] = []
    try:
        for ref in refs:
            row = connection.execute(
                "SELECT output_kind,logical_key,period_start_date,period_end_date,"
                "schema_name,title_text,content_json,content_text,content_html,"
                "lineage_json,content_sha256 FROM skill_outputs WHERE id=?",
                (int(ref["output_id"]),),
            ).fetchone()
            if row is None:
                raise CandidateBuildError("m11_v3_presentation_output_missing")
            try:
                payload = json.loads(str(row[6]))
                lineage = json.loads(str(row[9]))
            except json.JSONDecodeError as exc:
                raise CandidateBuildError("m11_v3_presentation_output_invalid") from exc
            recomputed = sha256_text(
                canonical_json(
                    {
                        "title": row[5],
                        "json": payload,
                        "text": row[7],
                        "html": row[8],
                        "lineage": lineage,
                    }
                )
            )
            day = str(ref["report_date"])
            if (
                str(row[0]) != "bounded_evidence"
                or str(row[1]) != f"training-coach:presentation-v3:daily:{day}"
                or str(row[2]) != day
                or str(row[3]) != day
                or str(row[4]) != "daily_presentation_evidence_v1"
                or row[5] is not None
                or str(row[10]) != str(ref["sha256"])
                or recomputed != str(ref["sha256"])
                or hashlib.sha256(canonical_json(payload).encode()).hexdigest()
                != str(ref["content_json_sha256"])
            ):
                raise CandidateBuildError("m11_v3_presentation_output_invalid")
            require_valid_payload(payload, "daily_presentation_evidence_v1")
            result.append(payload)
    finally:
        connection.close()
    return result


def _append_render_outputs(
    database: Path,
    run_id: int,
    source_rows: dict[int, dict[str, Any]],
    daily_items: list[tuple[dict[str, Any], dict[str, Any], Any]],
    presentation_refs: list[dict[str, Any]],
    weekly_item: tuple[dict[str, Any], Any],
    output_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    connection = connect(database)
    try:
        for index, (_presentation, view, rendered) in enumerate(daily_items):
            source_id = DAILY_OUTPUT_IDS[index]
            source_sha = str(source_rows[source_id]["sha256"])
            evidence_ref = presentation_refs[index]
            day = str(view["report_date"])
            view_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="report_artifact",
                logical_key=f"training-report-publisher:v3:daily:{day}:view",
                schema_name="daily_email_view_v3",
                schema_version="3",
                title_text=str(view["title"]),
                content_json=view,
                content_text=str(rendered.payload["text"]),
                content_html=str(rendered.payload["html"]),
                lineage=[
                    {
                        "output_id": source_id,
                        "output_sha256": source_sha,
                        "role": "ai_source",
                    },
                    {
                        "output_id": int(evidence_ref["output_id"]),
                        "output_sha256": str(evidence_ref["sha256"]),
                        "role": "presentation_evidence",
                    },
                ],
                period_start_date=day,
                period_end_date=day,
            )
            view_sha = _output_sha(connection, view_id)
            render_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="email_render",
                logical_key=f"training-report-publisher:v3:daily:{day}:render",
                schema_name="daily_email_render_v3",
                schema_version="3",
                title_text=str(rendered.payload["subject"]),
                content_json=rendered.payload,
                content_text=str(rendered.payload["text"]),
                content_html=str(rendered.payload["html"]),
                lineage=[
                    {
                        "output_id": source_id,
                        "output_sha256": source_sha,
                        "role": "ai_source",
                    },
                    {
                        "output_id": view_id,
                        "output_sha256": view_sha,
                        "role": "email_view",
                    },
                ],
                period_start_date=day,
                period_end_date=day,
            )
            render_sha = _output_sha(connection, render_id)
            output_records.extend(
                [
                    {
                        "id": view_id,
                        "schema_name": "daily_email_view_v3",
                        "sha256": view_sha,
                    },
                    {
                        "id": render_id,
                        "schema_name": "daily_email_render_v3",
                        "sha256": render_sha,
                    },
                ]
            )
        weekly_view, weekly_rendered = weekly_item
        weekly_source_sha = str(source_rows[WEEKLY_OUTPUT_ID]["sha256"])
        weekly_view_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="report_artifact",
            logical_key="training-report-publisher:v3:weekly:2026-08-12/2026-08-18:view",
            schema_name="weekly_email_view_v3",
            schema_version="3",
            title_text=str(weekly_view["title"]),
            content_json=weekly_view,
            content_text=str(weekly_rendered.payload["text"]),
            content_html=str(weekly_rendered.payload["html"]),
            lineage=[
                {
                    "output_id": WEEKLY_OUTPUT_ID,
                    "output_sha256": weekly_source_sha,
                    "role": "ai_source",
                },
                *[
                    {
                        "output_id": int(ref["output_id"]),
                        "output_sha256": str(ref["sha256"]),
                        "role": "daily_presentation",
                    }
                    for ref in presentation_refs
                ],
            ],
            period_start_date=PERIOD_START.isoformat(),
            period_end_date=PERIOD_END.isoformat(),
        )
        weekly_view_sha = _output_sha(connection, weekly_view_id)
        weekly_render_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="email_render",
            logical_key="training-report-publisher:v3:weekly:2026-08-12/2026-08-18:render",
            schema_name="weekly_email_render_v3",
            schema_version="3",
            title_text=str(weekly_rendered.payload["subject"]),
            content_json=weekly_rendered.payload,
            content_text=str(weekly_rendered.payload["text"]),
            content_html=str(weekly_rendered.payload["html"]),
            lineage=[
                {
                    "output_id": WEEKLY_OUTPUT_ID,
                    "output_sha256": weekly_source_sha,
                    "role": "ai_source",
                },
                {
                    "output_id": weekly_view_id,
                    "output_sha256": weekly_view_sha,
                    "role": "email_view",
                },
            ],
            period_start_date=PERIOD_START.isoformat(),
            period_end_date=PERIOD_END.isoformat(),
        )
        weekly_render_sha = _output_sha(connection, weekly_render_id)
        output_records.extend(
            [
                {
                    "id": weekly_view_id,
                    "schema_name": "weekly_email_view_v3",
                    "sha256": weekly_view_sha,
                },
                {
                    "id": weekly_render_id,
                    "schema_name": "weekly_email_render_v3",
                    "sha256": weekly_render_sha,
                },
            ]
        )
        finish_run(connection, run_id, status="succeeded")
        _checkpoint_candidate(connection)
    finally:
        connection.close()
    _clean_candidate_sidecars(database)
    return output_records


def _database_checks(database: Path) -> dict[str, int | str]:
    connection = _read_only(database)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        fk_rows = list(connection.execute("PRAGMA foreign_key_check"))
        triggers = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
            ).fetchone()[0]
        )
        v3_outputs = int(
            connection.execute(
                "SELECT COUNT(*) FROM skill_outputs WHERE schema_name IN "
                "('daily_presentation_evidence_v1','daily_email_view_v3','daily_email_render_v3',"
                "'weekly_email_view_v3','weekly_email_render_v3')"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    if integrity != "ok" or fk_rows or triggers < 6 or v3_outputs != 23:
        raise CandidateBuildError("m11_v3_candidate_database_invalid")
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(fk_rows),
        "trigger_count": triggers,
        "v3_output_count": v3_outputs,
    }


def _declared_files(candidate_root: Path) -> list[dict[str, Any]]:
    declared: list[dict[str, Any]] = []
    for path in sorted(candidate_root.rglob("*")):
        relative = path.relative_to(candidate_root)
        metadata = path.lstat()
        if path.is_symlink() or metadata.st_uid != os.getuid():
            raise CandidateBuildError("m11_v3_candidate_artifact_invalid")
        if stat.S_ISDIR(metadata.st_mode):
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise CandidateBuildError("m11_v3_candidate_artifact_invalid")
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
        ):
            raise CandidateBuildError("m11_v3_candidate_artifact_invalid")
        if relative.as_posix() == RECEIPT_NAME:
            continue
        declared.append(
            {
                "path": relative.as_posix(),
                "byte_size": metadata.st_size,
                "sha256": _sha256_file(path),
            }
        )
    return declared


def _mime_preview_pairs(candidate_root: Path) -> list[tuple[Path, Path]]:
    pairs = [
        (
            candidate_root / f"previews/daily-2026-08-{day:02d}",
            candidate_root / f"mime/daily-2026-08-{day:02d}",
        )
        for day in range(12, 19)
    ]
    pairs.append(
        (
            candidate_root / "previews/weekly-2026-08-12--2026-08-18",
            candidate_root / "mime/weekly-2026-08-12--2026-08-18",
        )
    )
    return pairs


def _package_and_verify_mime(candidate_root: Path, mime_module: Any) -> int:
    message_ids: set[str] = set()
    date_value = datetime(2026, 8, 23, 12, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    for index, (preview_root, mime_root) in enumerate(
        _mime_preview_pairs(candidate_root)
    ):
        receipt = mime_module.package_offline_preview(
            preview_root,
            mime_root,
            date_value + timedelta(minutes=index),
        )
        verified = mime_module.verify_offline_preview(mime_root)
        if (
            canonical_json(receipt) != canonical_json(verified)
            or receipt.get("provider_calls") != 0
            or receipt.get("external_actions") != 0
        ):
            raise CandidateBuildError("m11_v3_mime_preview_invalid")
        message_ids.add(str(receipt["actual_message_id"]))
    if len(message_ids) != 8:
        raise CandidateBuildError("m11_v3_mime_preview_invalid")
    return len(message_ids)


def verify_completed_candidate(candidate_root: Path) -> dict[str, Any]:
    receipt_path = candidate_root / RECEIPT_NAME
    _require_owner_file(receipt_path, "m11_v3_receipt_invalid")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateBuildError("m11_v3_receipt_invalid") from exc
    if (
        receipt.get("schema_version") != "m11_v3_candidate_receipt_v1"
        or receipt.get("status") != "succeeded"
        or receipt.get("provider_calls") != 0
        or receipt.get("external_actions") != 0
        or receipt.get("offline_mime_preview_count") != 8
    ):
        raise CandidateBuildError("m11_v3_receipt_invalid")
    expected = receipt.get("declared_files")
    actual = _declared_files(candidate_root)
    if not isinstance(expected, list) or canonical_json(expected) != canonical_json(
        actual
    ):
        raise CandidateBuildError("m11_v3_candidate_manifest_mismatch")
    _database_checks(candidate_root / "source/state/trainlab.db")
    mime_module = _load(
        "trainlab_m11_v3_mime_verify",
        SOURCE_ROOT / "skills/gmail-sender/scripts/gmail_readable_delivery.py",
    )
    if _package_and_verify_mime(candidate_root, mime_module) != 8:
        raise CandidateBuildError("m11_v3_mime_preview_invalid")
    return receipt


def build_candidate(
    parent_database: Path,
    parent_source_root: Path,
    candidate_root: Path,
) -> dict[str, Any]:
    if (candidate_root / RECEIPT_NAME).is_file():
        return verify_completed_candidate(candidate_root)
    _initialize_root(candidate_root)
    candidate_source = candidate_root / "source"
    candidate_database = candidate_source / "state/trainlab.db"
    _ensure_owner_directory(candidate_source / "state")
    frozen_parent = frozen_output_digest(parent_database, FROZEN_OUTPUT_IDS)
    _backup_database(parent_database, candidate_database)
    _copy_goal(parent_source_root, candidate_source)
    raw_manifest = copy_registered_raw(
        parent_database, parent_source_root, candidate_source
    )
    if frozen_output_digest(candidate_database, FROZEN_OUTPUT_IDS) != frozen_parent:
        raise CandidateBuildError("m11_v3_frozen_output_copy_drift")

    (
        context_module,
        presentation_module,
        view_module,
        renderer_module,
        mime_module,
    ) = _modules()
    source_rows = _output_rows(candidate_database)
    generated_presentations: list[dict[str, Any]] = []
    for index, output_id in enumerate(DAILY_OUTPUT_IDS):
        report_date = PERIOD_START + timedelta(days=index)
        source = source_rows[output_id]
        if (
            source["schema_name"] != "daily_ai_result_v2"
            or source["period_start_date"] != report_date.isoformat()
        ):
            raise CandidateBuildError("m11_v3_daily_source_binding_invalid")
        context = context_module.build_daily_context(
            candidate_database, candidate_source, report_date
        )
        presentation = presentation_module.build_daily_presentation_evidence(
            candidate_database,
            context,
            output_id=output_id,
        )
        generated_presentations.append(presentation)

    run_id, output_records, presentation_refs = _append_presentations(
        candidate_database,
        source_rows,
        generated_presentations,
        raw_manifest,
        frozen_parent,
    )
    persisted_presentations = _load_persisted_presentations(
        candidate_database, presentation_refs
    )
    if canonical_json(generated_presentations) != canonical_json(
        persisted_presentations
    ):
        raise CandidateBuildError("m11_v3_presentation_reload_mismatch")

    daily_items: list[tuple[dict[str, Any], dict[str, Any], Any]] = []
    for index, presentation in enumerate(persisted_presentations):
        output_id = DAILY_OUTPUT_IDS[index]
        source = source_rows[output_id]
        view = view_module.build_daily_view_v3(source["payload"], presentation)
        rendered = renderer_module.render_email_v3(view)
        daily_items.append((presentation, view, rendered))
        _write_bundle(
            candidate_root / f"previews/daily-{view['report_date']}",
            presentation=presentation,
            view=view,
            rendered=rendered,
        )

    weekly_source = source_rows[WEEKLY_OUTPUT_ID]
    if weekly_source["schema_name"] != "weekly_ai_result_v2":
        raise CandidateBuildError("m11_v3_weekly_source_binding_invalid")
    weekly_view = view_module.build_weekly_view_v3(
        weekly_source["payload"],
        persisted_presentations,
        presentation_refs,
        {
            "output_id": WEEKLY_OUTPUT_ID,
            "sha256": weekly_source["sha256"],
            "content_json_sha256": weekly_source["content_json_sha256"],
        },
    )
    weekly_rendered = renderer_module.render_email_v3(weekly_view)
    _write_bundle(
        candidate_root / "previews/weekly-2026-08-12--2026-08-18",
        presentation=None,
        view=weekly_view,
        rendered=weekly_rendered,
    )
    output_records = _append_render_outputs(
        candidate_database,
        run_id,
        source_rows,
        daily_items,
        presentation_refs,
        (weekly_view, weekly_rendered),
        output_records,
    )
    mime_count = _package_and_verify_mime(candidate_root, mime_module)
    frozen_after = frozen_output_digest(candidate_database, FROZEN_OUTPUT_IDS)
    if frozen_after != frozen_parent:
        raise CandidateBuildError("m11_v3_frozen_output_changed")
    checks = _database_checks(candidate_database)
    receipt: dict[str, Any] = {
        "schema_version": "m11_v3_candidate_receipt_v1",
        "status": "succeeded",
        "period": "2026-08-12/2026-08-18",
        "parent_database_sha256": _sha256_file(parent_database),
        "candidate_database_sha256": _sha256_file(candidate_database),
        "frozen_outputs": frozen_after,
        "raw_count": raw_manifest["count"],
        "raw_bytes": raw_manifest["bytes"],
        "raw_manifest_sha256": raw_manifest["sha256"],
        "outputs": output_records,
        **checks,
        "daily_preview_count": 7,
        "weekly_preview_count": 1,
        "offline_mime_preview_count": mime_count,
        "provider_calls": 0,
        "external_actions": 0,
        "declared_files": _declared_files(candidate_root),
    }
    _write_json(candidate_root / RECEIPT_NAME, receipt)
    return verify_completed_candidate(candidate_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-database", type=Path, required=True)
    parser.add_argument("--parent-source-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        receipt = build_candidate(
            args.parent_database, args.parent_source_root, args.candidate_root
        )
    finally:
        os.umask(previous_umask)
    print(
        canonical_json(
            {
                key: receipt[key]
                for key in (
                    "schema_version",
                    "status",
                    "candidate_database_sha256",
                    "raw_count",
                    "raw_bytes",
                    "v3_output_count",
                    "daily_preview_count",
                    "weekly_preview_count",
                    "offline_mime_preview_count",
                    "provider_calls",
                    "external_actions",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
