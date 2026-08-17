from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[3]
SCRIPT = SOURCE / "skills/_shared/scripts/write_workflow_receipt.py"


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "workflow_receipt_v1",
        "status": "succeeded",
        "outcome": "daily_complete",
        "workflow_key": "daily:2026-08-12",
        "provider_calls": 0,
        "summary_output_id": 1,
        "render_output_ids": [2, 3],
        "email_output_id": 4,
        "warnings": [],
    }


def test_workflow_receipt_writer_rejects_internal_output_id(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "receipt.json"
    payload = _receipt()
    payload["output_id"] = 5
    source.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-json",
            str(source),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert not output.exists()


def test_workflow_receipt_writer_is_owner_only_and_atomic(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "receipt.json"
    source.write_text(json.dumps(_receipt()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-json",
            str(source),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == _receipt()
    assert output.stat().st_mode & 0o777 == 0o600
