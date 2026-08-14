from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.analysis.config import (
    MAX_CODEX_TIMEOUT_SECONDS,
    MAX_CONTEXT_BYTES,
    MAX_DELIVERY_TIMEOUT_SECONDS,
    AnalysisConfigurationError,
    load_analysis_config,
)
from src.resources import resource_path


def valid_payload() -> dict[str, object]:
    return {
        "analysis": {
            "timezone": "Asia/Hong_Kong",
            "harness_root": "harness",
            "input_schema": "harness/schemas/analysis_input.schema.json",
            "output_schema": "harness/schemas/analysis_result.schema.json",
            "max_context_bytes": MAX_CONTEXT_BYTES,
            "completed_window_days": 28,
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


def test_loads_static_hong_kong_config_under_project_root(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, valid_payload())
    before = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )

    config = load_analysis_config(tmp_path, config_path)

    assert config.timezone == "Asia/Hong_Kong"
    assert config.max_context_bytes == MAX_CONTEXT_BYTES
    assert config.codex_timeout_seconds == MAX_CODEX_TIMEOUT_SECONDS
    assert config.delivery_timeout_seconds == MAX_DELIVERY_TIMEOUT_SECONDS
    assert config.training_difficulty_level == 2
    assert config.training_difficulty_source == "default"
    assert config.marathon_target_finish_time is None
    assert config.marathon_target_finish_time_source == "default"
    assert config.half_marathon_target_finish_time is None
    assert config.half_marathon_target_finish_time_source == "default"
    assert config.harness_root == resource_path("harness")
    assert config.lock_path == tmp_path / "state" / "locks" / "analysis.lock"
    assert (
        sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
        == before
    )


@pytest.mark.parametrize("level", [1, 2, 5])
def test_loads_project_wide_training_difficulty(tmp_path: Path, level: int) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / "config" / "src.json").write_text(
        json.dumps({"schema_version": 1, "training_difficulty_level": level}),
        encoding="utf-8",
    )

    config = load_analysis_config(tmp_path, config_path)

    assert config.training_difficulty_level == level
    assert config.training_difficulty_source == "project_global_config"


@pytest.mark.parametrize("level", [True, 0, 6, 2.0, "2", None])
def test_rejects_invalid_project_wide_training_difficulty(
    tmp_path: Path, level: object
) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / "config" / "src.json").write_text(
        json.dumps({"schema_version": 1, "training_difficulty_level": level}),
        encoding="utf-8",
    )

    with pytest.raises(
        AnalysisConfigurationError,
        match="analysis_project_config_invalid:training_difficulty_level",
    ):
        load_analysis_config(tmp_path, config_path)


@pytest.mark.parametrize(
    ("marathon", "half_marathon"),
    [
        (None, None),
        ("03:30", None),
        (None, "01:45"),
        ("12:00", "00:59"),
        ("99:59", "23:59"),
    ],
)
def test_loads_project_wide_race_goal_times(
    tmp_path: Path, marathon: str | None, half_marathon: str | None
) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / "config" / "src.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "training_difficulty_level": 2,
                "marathon_target_finish_time": marathon,
                "half_marathon_target_finish_time": half_marathon,
            }
        ),
        encoding="utf-8",
    )

    config = load_analysis_config(tmp_path, config_path)

    assert config.marathon_target_finish_time == marathon
    assert config.half_marathon_target_finish_time == half_marathon
    assert config.marathon_target_finish_time_source == "project_global_config"
    assert config.half_marathon_target_finish_time_source == "project_global_config"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("marathon_target_finish_time", "3:30"),
        ("marathon_target_finish_time", "03:3"),
        ("marathon_target_finish_time", "03:60"),
        ("marathon_target_finish_time", "00:00"),
        ("marathon_target_finish_time", 210),
        ("half_marathon_target_finish_time", ""),
        ("half_marathon_target_finish_time", "1:45"),
        ("half_marathon_target_finish_time", "01:75"),
        ("half_marathon_target_finish_time", False),
    ],
)
def test_rejects_invalid_project_wide_race_goal_times(
    tmp_path: Path, key: str, value: object
) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / "config" / "src.json").write_text(
        json.dumps({"schema_version": 1, key: value}),
        encoding="utf-8",
    )

    with pytest.raises(
        AnalysisConfigurationError,
        match=f"analysis_project_config_invalid:{key}",
    ):
        load_analysis_config(tmp_path, config_path)


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
def test_rejects_forbidden_or_non_static_settings_before_operations(
    tmp_path: Path, change: dict[str, object]
) -> None:
    payload = valid_payload()
    payload["analysis"].update(change)  # type: ignore[index]
    config_path = write_config(tmp_path, payload)

    with pytest.raises(
        AnalysisConfigurationError, match="analysis_config_schema_invalid"
    ):
        load_analysis_config(tmp_path, config_path)


def test_rejects_config_path_outside_allowed_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-analysis.yaml"
    outside.write_text(yaml.safe_dump(valid_payload()), encoding="utf-8")

    with pytest.raises(
        AnalysisConfigurationError,
        match="analysis_config_path_escapes_project_root:config",
    ):
        load_analysis_config(tmp_path, outside)


@pytest.mark.parametrize("directory", ["state/locks", "state/tmp/analysis"])
def test_rejects_insecure_private_runtime_directories(
    tmp_path: Path, directory: str
) -> None:
    config_path = write_config(tmp_path, valid_payload())
    (tmp_path / directory).chmod(0o755)

    with pytest.raises(
        AnalysisConfigurationError, match="analysis_config_private_directory_mode"
    ):
        load_analysis_config(tmp_path, config_path)
