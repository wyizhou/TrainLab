from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from trainlab.analysis.config import (
    MAX_CODEX_TIMEOUT_SECONDS,
    MAX_CONTEXT_BYTES,
    MAX_DELIVERY_TIMEOUT_SECONDS,
    AnalysisConfigurationError,
    load_analysis_config,
)


def valid_payload() -> dict[str, object]:
    return {
        "analysis": {
            "timezone": "Asia/Singapore",
            "harness_root": "harness",
            "input_schema": "harness/schemas/analysis_input.schema.json",
            "output_schema": "harness/schemas/analysis_result.schema.json",
            "max_context_bytes": MAX_CONTEXT_BYTES,
            "daily_baseline_days": 14,
            "weekly_baseline_days": 28,
            "max_recent_daily_artifacts": 7,
            "codex_timeout_seconds": MAX_CODEX_TIMEOUT_SECONDS,
            "delivery_timeout_seconds": MAX_DELIVERY_TIMEOUT_SECONDS,
            "lock_path": "state/locks/analysis.lock",
            "temp_root": "state/tmp/analysis",
        }
    }


def write_config(root: Path, payload: dict[str, object]) -> Path:
    (root / "state" / "locks").mkdir(parents=True)
    (root / "state" / "tmp" / "analysis").mkdir(parents=True)
    (root / "state" / "locks").chmod(0o700)
    (root / "state" / "tmp" / "analysis").chmod(0o700)
    path = root / "config" / "analysis.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_loads_static_singapore_config_under_project_root(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, valid_payload())
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    config = load_analysis_config(tmp_path, config_path)

    assert config.timezone == "Asia/Singapore"
    assert config.max_context_bytes == MAX_CONTEXT_BYTES
    assert config.codex_timeout_seconds == MAX_CODEX_TIMEOUT_SECONDS
    assert config.delivery_timeout_seconds == MAX_DELIVERY_TIMEOUT_SECONDS
    assert config.harness_root == tmp_path / "harness"
    assert config.lock_path == tmp_path / "state" / "locks" / "analysis.lock"
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "change",
    [
        {"model": "pinned"},
        {"gmail_token": "secret"},
        {"cron": "0 7 * * *"},
        {"mail_recipient": "other@example.test"},
        {"timezone": "UTC"},
        {"harness_root": "../harness"},
        {"input_schema": "../../outside.json"},
        {"max_context_bytes": MAX_CONTEXT_BYTES + 1},
        {"codex_timeout_seconds": MAX_CODEX_TIMEOUT_SECONDS + 1},
        {"delivery_timeout_seconds": MAX_DELIVERY_TIMEOUT_SECONDS + 1},
    ],
)
def test_rejects_forbidden_or_non_static_settings_before_operations(tmp_path: Path, change: dict[str, object]) -> None:
    payload = valid_payload()
    payload["analysis"].update(change)  # type: ignore[index]
    config_path = write_config(tmp_path, payload)

    with pytest.raises(AnalysisConfigurationError, match="analysis_config_schema_invalid"):
        load_analysis_config(tmp_path, config_path)


def test_rejects_config_path_outside_allowed_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-analysis.yaml"
    outside.write_text(yaml.safe_dump(valid_payload()), encoding="utf-8")

    with pytest.raises(AnalysisConfigurationError, match="analysis_config_path_escapes_project_root:config"):
        load_analysis_config(tmp_path, outside)


@pytest.mark.parametrize("directory", ["state/locks", "state/tmp/analysis"])
def test_rejects_insecure_private_runtime_directories(tmp_path: Path, directory: str) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / directory).chmod(0o755)

    with pytest.raises(AnalysisConfigurationError, match="analysis_config_private_directory_mode"):
        load_analysis_config(tmp_path, config_path)
