from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _formal_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    state = root / "state"
    raw = state / "raw" / "garmin" / "health"
    raw.mkdir(parents=True, mode=0o700)
    (state / "trainlab.db").write_bytes(b"synthetic-db")
    (state / "trainlab.lock").write_bytes(b"")
    (raw / "20260812-rhr.json").write_bytes(b"{}")
    for path in (
        state / "trainlab.db",
        state / "trainlab.lock",
        raw / "20260812-rhr.json",
    ):
        os.chmod(path, 0o600)
    os.chmod(root, 0o700)
    os.chmod(state, 0o700)
    return root


def test_formal_fingerprint_includes_raw_and_sidecars(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_fingerprint",
    )
    root = _formal_root(tmp_path)
    fingerprint = builder._formal_state_fingerprint(root)
    paths = {str(item["path"]) for item in fingerprint["entries"]}
    assert "trainlab.db" in paths
    assert "trainlab.lock" in paths
    assert "raw/garmin/health/20260812-rhr.json" in paths
    assert fingerprint["raw_entry_count"] >= 3


def test_nonempty_formal_wal_fails_before_candidate_creation(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_wal",
    )
    root = _formal_root(tmp_path)
    wal = root / "state/trainlab.db-wal"
    wal.write_bytes(b"uncheckpointed")
    os.chmod(wal, 0o600)
    candidate = tmp_path / "candidate"
    with pytest.raises(ValueError, match="formal_wal_nonempty"):
        builder.build(root, candidate)
    assert not candidate.exists()


def test_formal_lock_contention_fails_before_candidate_creation(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_lock",
    )
    root = _formal_root(tmp_path)
    lock_path = root / "state/trainlab.lock"
    descriptor = os.open(lock_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate = tmp_path / "candidate"
        with pytest.raises(ValueError, match="formal_state_lock_unavailable"):
            builder.build(root, candidate)
        assert not candidate.exists()
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_formal_state_drift_is_detected_after_candidate_build(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_drift",
    )
    root = _formal_root(tmp_path)

    def mutate(formal_root: Path, candidate_root: Path) -> dict[str, object]:
        candidate_root.mkdir(mode=0o700)
        raw = formal_root / "state/raw/garmin/health/20260812-rhr.json"
        raw.write_bytes(b"changed")
        os.chmod(raw, 0o600)
        return {"candidate_root": str(candidate_root)}

    builder._build_unlocked = mutate
    with pytest.raises(ValueError, match="formal_state_changed_during_snapshot"):
        builder.build(root, tmp_path / "candidate")


def test_nonempty_candidate_sidecar_is_not_deleted(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_candidate_sidecar",
    )
    database = tmp_path / "trainlab.db"
    sidecar = tmp_path / "trainlab.db-wal"
    sidecar.write_bytes(b"must-keep")
    os.chmod(sidecar, 0o600)
    with pytest.raises(ValueError, match="candidate_wal_nonempty"):
        builder._cleanup_candidate_sidecars(database)
    assert sidecar.read_bytes() == b"must-keep"


def _write_manifest(path: Path, files: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": "artifact_manifest_v1", "files": files},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_artifact_verifier_requires_owner_only_nonempty_declared_json(
    tmp_path: Path,
) -> None:
    verifier = _module(
        ROOT / "skills/_shared/scripts/verify_m8_artifacts.py",
        "m8_r32_artifacts",
    )
    root = tmp_path / "outputs"
    root.mkdir(mode=0o700)
    report = root / "reports/report.json"
    report.parent.mkdir(mode=0o700)
    report.write_text('{"ok":true}\n', encoding="utf-8")
    os.chmod(report, 0o600)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{"path": "reports/report.json", "json": True}])
    result = verifier.verify_artifacts(root, manifest)
    assert result["verified"] is True


def test_artifact_verifier_rejects_empty_wrong_mode_and_undeclared_files(
    tmp_path: Path,
) -> None:
    verifier = _module(
        ROOT / "skills/_shared/scripts/verify_m8_artifacts.py",
        "m8_r32_artifacts_negative",
    )
    root = tmp_path / "outputs"
    root.mkdir(mode=0o700)
    declared = root / "reports/report.json"
    declared.parent.mkdir(mode=0o700)
    declared.write_bytes(b"")
    os.chmod(declared, 0o600)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{"path": "reports/report.json", "json": True}])
    with pytest.raises(ValueError, match="artifact_empty_file"):
        verifier.verify_artifacts(root, manifest)
    declared.write_text("{}\n", encoding="utf-8")
    os.chmod(declared, 0o644)
    with pytest.raises(ValueError, match="artifact_file_permissions"):
        verifier.verify_artifacts(root, manifest)
    os.chmod(declared, 0o600)
    extra = root / "reports/extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    os.chmod(extra, 0o600)
    with pytest.raises(ValueError, match="artifact_undeclared_file"):
        verifier.verify_artifacts(root, manifest)
