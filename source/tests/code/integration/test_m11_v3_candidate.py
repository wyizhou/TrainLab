from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skills._shared.state import canonical_json

SOURCE = Path(__file__).resolve().parents[3]


def _load() -> Any:
    path = SOURCE / "skills/training-report-publisher/scripts/build_m11_v3_candidate.py"
    spec = importlib.util.spec_from_file_location("trainlab_m11_v3_candidate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def _raw_database(path: Path, rows: list[tuple[int, str, int, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE raw_files (id INTEGER PRIMARY KEY, relative_path TEXT, "
        "byte_size INTEGER, sha256 TEXT, integrity_state TEXT)"
    )
    connection.executemany("INSERT INTO raw_files VALUES (?,?,?,?,'verified')", rows)
    connection.commit()
    connection.close()
    path.chmod(0o600)


def test_candidate_copies_registered_raw_as_new_owner_only_files(
    tmp_path: Path,
) -> None:
    builder = _load()
    parent = tmp_path / "parent/source"
    candidate = tmp_path / "candidate/source"
    raw_one = b'{"sleep":true}'
    raw_two = b"FIT-bytes"
    paths = ["garmin/health/one.json", "garmin/activities/two.fit"]
    _owner_write(parent / "state/raw" / paths[0], raw_one)
    _owner_write(parent / "state/raw" / paths[1], raw_two)
    database = tmp_path / "parent.db"
    _raw_database(
        database,
        [
            (1, paths[0], len(raw_one), hashlib.sha256(raw_one).hexdigest()),
            (2, paths[1], len(raw_two), hashlib.sha256(raw_two).hexdigest()),
        ],
    )

    copied = builder.copy_registered_raw(database, parent, candidate)

    assert copied["count"] == 2
    assert copied["bytes"] == len(raw_one) + len(raw_two)
    for relative in paths:
        source = parent / "state/raw" / relative
        target = candidate / "state/raw" / relative
        metadata = target.lstat()
        assert target.read_bytes() == source.read_bytes()
        assert metadata.st_ino != source.lstat().st_ino
        assert metadata.st_nlink == 1
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_uid == os.getuid()


def test_candidate_raw_copy_rejects_symlink_and_unregistered_file(
    tmp_path: Path,
) -> None:
    builder = _load()
    parent = tmp_path / "parent/source"
    candidate = tmp_path / "candidate/source"
    payload = b"registered"
    target = parent / "outside.bin"
    _owner_write(target, payload)
    raw_path = parent / "state/raw/garmin/health/one.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.symlink_to(target)
    _owner_write(parent / "state/raw/garmin/health/unregistered.json", b"private")
    database = tmp_path / "parent.db"
    _raw_database(
        database,
        [
            (
                1,
                "garmin/health/one.json",
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        ],
    )

    with pytest.raises(builder.CandidateBuildError, match="registered_raw_invalid"):
        builder.copy_registered_raw(database, parent, candidate)


def test_frozen_output_digest_detects_content_or_sha_drift(tmp_path: Path) -> None:
    builder = _load()
    database = tmp_path / "outputs.db"
    payload = {"frozen": True}
    content_text = "frozen"
    digest = hashlib.sha256(
        canonical_json(
            {
                "title": None,
                "json": payload,
                "text": content_text,
                "html": None,
                "lineage": [],
            }
        ).encode()
    ).hexdigest()
    expected = dict(builder.FROZEN_OUTPUT_CONTRACT[85])
    expected["content_sha256"] = digest
    builder.FROZEN_OUTPUT_CONTRACT[85] = expected
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE skill_runs (id INTEGER PRIMARY KEY,skill_name TEXT,"
        "operation TEXT,status TEXT)"
    )
    connection.execute(
        "CREATE TABLE skill_outputs (id INTEGER PRIMARY KEY,skill_run_id INTEGER,"
        "output_kind TEXT,logical_key TEXT,revision_no INTEGER,period_start_date TEXT,"
        "period_end_date TEXT,schema_name TEXT,schema_version TEXT,title_text TEXT,"
        "content_json TEXT,content_text TEXT,content_html TEXT,lineage_json TEXT,"
        "content_sha256 TEXT)"
    )
    connection.execute(
        "INSERT INTO skill_runs VALUES (1,'training-coach','daily_coach','succeeded')"
    )
    connection.execute(
        "INSERT INTO skill_outputs VALUES (85,1,'daily_summary',"
        "'training-coach:ai:daily-v2:2026-08-12',1,'2026-08-12','2026-08-12',"
        "'daily_ai_result_v2','2',NULL,?,?,NULL,'[]',?)",
        (canonical_json(payload), content_text, digest),
    )
    connection.commit()
    connection.close()
    database.chmod(0o600)

    first = builder.frozen_output_digest(database, [85])
    assert first["85"]["content_sha256"] == digest
    assert (
        first["85"]["content_json_sha256"]
        == hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    )

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE skill_outputs SET content_json=? WHERE id=85", (json.dumps({}),)
    )
    connection.commit()
    connection.close()
    with pytest.raises(
        builder.CandidateBuildError, match="frozen_output_contract_mismatch"
    ):
        builder.frozen_output_digest(database, [85])


def test_candidate_uses_an_existing_sqlite_operation_contract() -> None:
    builder = _load()
    assert builder.CANDIDATE_OPERATION == "render_weekly"


def test_browser_preview_maps_each_cid_to_private_local_asset() -> None:
    builder = _load()
    assets = [
        SimpleNamespace(cid="chart-one@trainlab.invalid", filename="one.png"),
        SimpleNamespace(cid="chart-two@trainlab.invalid", filename="two.png"),
    ]
    email_html = (
        '<img src="cid:chart-one@trainlab.invalid">'
        '<img src="cid:chart-two@trainlab.invalid">'
    )
    preview = builder._browser_preview_html(email_html, assets)
    assert preview == '<img src="assets/one.png"><img src="assets/two.png">'
    with pytest.raises(
        builder.CandidateBuildError, match="browser_preview_cid_invalid"
    ):
        builder._browser_preview_html(email_html, assets[:1])
