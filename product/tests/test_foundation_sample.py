from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationTool, TABLES, VIEWS
from trainlab.foundation_sample import generate_sample_database


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def table_fingerprint(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    try:
        result: dict[str, str] = {}
        for table in sorted(TABLES):
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            result[table] = hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()
        return result
    finally:
        conn.close()


def database_text_values(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        values: list[str] = []
        for table in TABLES:
            text_columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[2].upper() in {"TEXT", "BLOB"}]
            if text_columns:
                values.extend(str(value) for row in conn.execute(f"SELECT {','.join(text_columns)} FROM {table}") for value in row if value is not None)
        return "\n".join(values)
    finally:
        conn.close()


def test_projection_only_sample_is_complete_private_and_repeat_safe(tmp_path: Path) -> None:
    root = generate_sample_database(tmp_path / "sample")
    with pytest.raises(FileExistsError): generate_sample_database(root)
    metadata = json.loads((root / "sample-metadata.json").read_text())
    assert metadata["synthetic"] and metadata["projection_only"]
    assert metadata["raw_files_are_not_valid_fit_or_provider_payloads"]
    assert (root.stat().st_mode & 0o777) == 0o700
    for path in root.rglob("*"):
        assert (path.stat().st_mode & 0o777) == (0o700 if path.is_dir() else 0o600), path
    conn = sqlite3.connect(root / "data.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert actual == set(TABLES) | {"schema_migrations"}
        assert all(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0 for table in actual)
        for view in VIEWS: conn.execute(f"SELECT * FROM {view} LIMIT 3").fetchall()
        assert conn.execute("SELECT COUNT(*) FROM v_current_activities WHERE provider_state='provider_deleted'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM v_current_daily_health").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_current_mail_response_artifacts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_current_analysis_artifacts WHERE artifact_kind='weekly_summary'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_open_data_quality_issues").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_plan_revision_reason_events").fetchone()[0] == 1
        assert conn.execute("SELECT DISTINCT trust_class FROM v_analysis_history_context").fetchall() == [("prior_model_output",)]
        assert conn.execute("SELECT DISTINCT trust_class FROM v_mail_response_history_context").fetchall() == [("prior_model_output",)]
        malicious = conn.execute("SELECT content_text FROM conversation_events").fetchone()[0]
        assert malicious is None  # the untrusted message remains a mail fact, not promoted event content
        body = conn.execute("SELECT body_text FROM mail_messages WHERE provider_message_id='reply'").fetchone()[0]
        assert "IGNORE ALL PREVIOUS" in body
        assert conn.execute("SELECT trust_level FROM conversation_events").fetchone()[0] == "untrusted_content"
    finally:
        conn.close()
    corpus = (root / "sample-metadata.json").read_bytes() + b"".join(path.read_bytes() for path in (root / "raw" / "synthetic").iterdir())
    for forbidden in (b"@", b"BEGIN PRIVATE KEY", b"access_token", b"refresh_token"):
        assert forbidden not in corpus
    conn = sqlite3.connect(root / "data.db")
    assert conn.execute("SELECT COUNT(*) FROM activity_samples WHERE latitude IS NOT NULL OR longitude IS NOT NULL").fetchone()[0] == 0
    conn.close()
    values = database_text_values(root / "data.db").lower()
    assert not re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", values)
    assert not re.search(r"(?:access|refresh)[_-]?token|api[_-]?key|password|authorization\s*[:=]|https?://accounts\.google", values)


def test_sample_encrypted_backup_restore_is_lossless_and_authenticated(tmp_path: Path) -> None:
    root = generate_sample_database(tmp_path / "sample")
    tool = FoundationTool(config(root)); key = b"s" * 32
    before = table_fingerprint(root / "data.db")
    destination = tmp_path / "backup" / "sample.tlfb"
    temporary_before = {path.name for path in destination.parent.glob("*")} if destination.parent.exists() else set()
    encrypted = tool.backup_encrypted(destination, lambda: key)
    restored = tmp_path / "restore" / "data.db"
    FoundationTool.restore_encrypted(encrypted, restored, key)
    assert table_fingerprint(restored) == before
    check = sqlite3.connect(restored)
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert check.execute("PRAGMA foreign_key_check").fetchall() == []
    check.close()
    with pytest.raises(Exception): FoundationTool.restore_encrypted(encrypted, tmp_path / "wrong.db", b"x" * 32)
    tampered = tmp_path / "tampered.tlfb"; payload = bytearray(encrypted.read_bytes()); payload[-1] ^= 1; tampered.write_bytes(payload)
    with pytest.raises(Exception): FoundationTool.restore_encrypted(tampered, tmp_path / "tampered.db", key)
    with pytest.raises(FileExistsError): FoundationTool.restore_encrypted(encrypted, restored, key)
    assert not [p for p in tmp_path.rglob("*") if p.name == "backup.sqlite" or p.name.startswith(".backup-") or p.name.startswith(".restore-")]
    assert {path.name for path in destination.parent.glob("*")} - temporary_before == {"sample.tlfb"}


def test_runbook_script_works_in_project_venv_and_refuses_existing_target(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "script-sample"
    command = [sys.executable, "scripts/generate_foundation_sample.py", "--output-root", str(output)]
    first = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    assert second.returncode != 0
    assert "sample_output_root_exists" in second.stderr
