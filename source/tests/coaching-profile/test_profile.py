from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.coaching.profile import (
    CoachingProfileError,
    apply_profile_candidate,
    current_profile,
    propose_profile,
)


def _private_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "instance"
    config = root / "config"
    state = root / "state"
    logs = root / "logs"
    for directory in (config, state, logs):
        directory.mkdir(parents=True)
        os.chmod(directory, 0o700)
    config_file = config / "trainlab.json"
    config_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "training_difficulty_level": 3,
                "available_training_weekdays": "1,2,3,5,7",
                "half_marathon_target_finish_time": "01:50",
                "marathon_target_finish_time": None,
                "mail": {"recipient": "redacted@example.invalid"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(config_file, 0o600)
    return root, config_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_propose_is_structured_and_does_not_modify_formal_config(
    tmp_path: Path,
) -> None:
    root, config_file = _private_root(tmp_path)
    before = config_file.read_bytes()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "available_weekdays": [1, 3, 5, 7],
                "hard_load_max": 3,
                "hard_load_min_gap_days": 2,
            }
        ),
        encoding="utf-8",
    )

    result = propose_profile(root, request_id="request-001", input_path=request)

    assert result["impact"]["formal_config_modified"] is False
    assert result["impact"]["user_confirmation_required"] is True
    assert result["profile"]["available_weekdays"] == [1, 3, 5, 7]
    assert config_file.read_bytes() == before
    candidate = (
        root
        / "state"
        / "coaching-profile"
        / "candidates"
        / (f"{result['candidate_id']}.json")
    )
    assert candidate.is_file()
    assert _mode(candidate) == 0o600


def test_apply_preserves_unrelated_config_and_clears_race_fields(
    tmp_path: Path,
) -> None:
    root, config_file = _private_root(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"weekly_frequency": 4}), encoding="utf-8")

    candidate = propose_profile(root, request_id="request-002", input_path=request)
    result = apply_profile_candidate(root, candidate_id=candidate["candidate_id"])

    updated = json.loads(config_file.read_text(encoding="utf-8"))
    assert result["status"] == "applied"
    assert updated["mail"] == {"recipient": "redacted@example.invalid"}
    assert updated["coaching_profile_contract"]["weekly_frequency"] == 4
    assert updated["available_training_weekdays"] == "1,3,5,7"
    for field in (
        "active_race_goal",
        "marathon_target_finish_time",
        "half_marathon_target_finish_time",
        "marathon_race_date",
        "half_marathon_race_date",
    ):
        assert updated[field] is None
    assert _mode(config_file) == 0o600
    backup = root / "state" / "coaching-profile" / result["backup_relative_path"]
    assert backup.is_file()
    assert _mode(backup) == 0o600
    audit = root / "state" / "coaching-profile" / "audit.jsonl"
    assert audit.is_file()
    assert _mode(audit) == 0o600
    assert current_profile(root)["weekly_frequency"] == 4


def test_invalid_profile_field_and_tampered_candidate_fail_closed(
    tmp_path: Path,
) -> None:
    root, _ = _private_root(tmp_path)
    request = tmp_path / "invalid.json"
    request.write_text(json.dumps({"unknown": True}), encoding="utf-8")
    with pytest.raises(CoachingProfileError, match="input_fields_invalid"):
        propose_profile(root, request_id="request-003", input_path=request)

    request.write_text(json.dumps({"weekly_frequency": 3}), encoding="utf-8")
    candidate = propose_profile(root, request_id="request-004", input_path=request)
    candidate_path = (
        root
        / "state"
        / "coaching-profile"
        / "candidates"
        / f"{candidate['candidate_id']}.json"
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["profile"]["weekly_frequency"] = "three"
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(candidate_path, 0o600)
    with pytest.raises(CoachingProfileError, match="profile_invalid"):
        apply_profile_candidate(root, candidate_id=candidate["candidate_id"])


def test_valid_candidate_tampering_is_rejected_by_content_hash(tmp_path: Path) -> None:
    root, _ = _private_root(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"weekly_frequency": 3}), encoding="utf-8")
    candidate = propose_profile(root, request_id="request-005", input_path=request)
    candidate_path = (
        root
        / "state"
        / "coaching-profile"
        / "candidates"
        / f"{candidate['candidate_id']}.json"
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["profile"]["weekly_frequency"] = 5
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(candidate_path, 0o600)
    with pytest.raises(CoachingProfileError, match="candidate_tampered"):
        apply_profile_candidate(root, candidate_id=candidate["candidate_id"])
