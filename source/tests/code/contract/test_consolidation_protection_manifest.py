from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/code/fixtures"
for path in (ROOT, FIXTURES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from consolidation_protection_fixture import (  # noqa: E402
    chmod_tree,
    make_dir,
    make_fifo,
    write_private_file,
    write_private_text,
)
from skills._shared.protection_manifest import (  # noqa: E402
    protect_sources,
    validate_manifest,
)


def by_relative(manifest: dict, relative: str) -> list[dict]:
    return [entry for entry in manifest["entries"] if entry["relative_path"] == relative]


def target(entry: dict) -> Path:
    return Path(entry["target"])


def test_files_copy_bytes_metadata_conflicts_and_idempotent_rerun(
    tmp_path: Path,
) -> None:
    source_a = make_dir(tmp_path / "source-a")
    source_b = make_dir(tmp_path / "source-b")
    original = write_private_file(source_a / "activity.fit", b"FIT-A-original")
    conflict = write_private_file(source_b / "activity.fit", b"FIT-B-different")
    duplicate = write_private_file(source_b / "duplicates/same.fit", b"FIT-A-original")
    chmod_tree(source_a)
    chmod_tree(source_b)

    destination = tmp_path / "protected"
    manifest = protect_sources(
        [source_a, source_b], destination, preservation_time_label="T000000Z"
    )

    activity_entries = by_relative(manifest, "activity.fit")
    assert len(activity_entries) == 2
    targets = {entry["target_relative_path"] for entry in activity_entries}
    assert len(targets) == 2
    assert any("." + activity_entries[1]["sha256"][:12] in name for name in targets)
    for entry in activity_entries:
        copied = target(entry)
        source = Path(entry["source"])
        assert copied.read_bytes() == source.read_bytes()
        assert copied.stat().st_ino != source.stat().st_ino
        assert copied.stat().st_nlink == 1
        assert stat.S_IMODE(copied.stat().st_mode) == 0o600
        assert entry["source_meta_before"]["type"] == "file"
        assert entry["source_meta_after"]["type"] == "file"
        assert entry["size"] == len(source.read_bytes())
        assert entry["mode"] == 0o600
        assert entry["closed"] is True

    duplicate_entry = by_relative(manifest, "duplicates/same.fit")[0]
    assert target(duplicate_entry).read_bytes() == original.read_bytes()
    assert duplicate_entry["sha256"] == activity_entries[0]["sha256"]

    payload_files_before = sorted(
        path.relative_to(destination / "payload").as_posix()
        for path in (destination / "payload").rglob("*")
        if path.is_file()
    )
    rerun = protect_sources(
        [source_a, source_b], destination, preservation_time_label="T000000Z"
    )
    payload_files_after = sorted(
        path.relative_to(destination / "payload").as_posix()
        for path in (destination / "payload").rglob("*")
        if path.is_file()
    )
    assert payload_files_after == payload_files_before
    assert {
        entry.get("target_action")
        for entry in rerun["entries"]
        if entry["type"] == "file"
    } == {"already_present_same_sha"}
    assert validate_manifest(destination) == {
        "status": "verified",
        "entry_count": len(rerun["entries"]),
    }


def test_fit_like_sources_keep_unknown_activity_time_and_no_import_claim(
    tmp_path: Path,
) -> None:
    source = make_dir(tmp_path / "source")
    early = write_private_file(source / "1999/early.fit", b"early fit-like bytes")
    unregistered = write_private_file(
        source / "not-in-db/unregistered.fit", b"same duplicate bytes"
    )
    corrupt = write_private_file(source / "broken/corrupt.fit", b"not a real FIT")
    duplicate = write_private_file(
        source / "duplicates/copy.fit", b"same duplicate bytes"
    )
    for path in (early, unregistered, corrupt, duplicate):
        os.utime(path, ns=(123, 456))
    chmod_tree(source)

    manifest = protect_sources(
        [source], tmp_path / "protected", preservation_time_label="PRESERVED-NOT-ACTIVITY"
    )
    fit_entries = [
        entry for entry in manifest["entries"] if entry["classification"] == "fit_original"
    ]
    assert {entry["relative_path"] for entry in fit_entries} == {
        "1999/early.fit",
        "not-in-db/unregistered.fit",
        "broken/corrupt.fit",
        "duplicates/copy.fit",
    }
    for entry in fit_entries:
        assert entry["activity_time"] == {
            "status": "unknown",
            "label": "activity_time_unknown_preserved_at_PRESERVED-NOT-ACTIVITY",
            "source": "preservation_label_not_filesystem_mtime",
        }
        assert entry["source_meta_before"]["mtime_ns"] == 456
        assert "456" not in entry["activity_time"]["label"]
        assert entry["fit_parse_status"] == "not_attempted_preservation_only"
        assert entry["business_import_status"] == "not_evaluated_by_preservation"
    same_sha = {
        entry["sha256"]
        for entry in fit_entries
        if entry["relative_path"].startswith(("not-in-db", "duplicates"))
    }
    assert len(same_sha) == 1


def test_links_special_items_and_opaque_carriers_are_not_followed_or_unpacked(
    tmp_path: Path,
) -> None:
    source = make_dir(tmp_path / "source")
    outside = make_dir(tmp_path / "outside")
    write_private_text(outside / "secret.txt", "SECRET-BODY-MUST-NOT-APPEAR")
    write_private_file(source / "archives/bundle.zip", b"PK\x03\x04opaque payload")
    make_dir(source / "inside")
    (source / "inside-link").symlink_to("inside")
    (source / "outside-link").symlink_to("../outside/secret.txt")
    fifo = make_fifo(source / "pipes/progress.fifo")
    chmod_tree(source)

    manifest = protect_sources(
        [source], tmp_path / "protected", preservation_time_label="LINKS"
    )
    manifest_text = json.dumps(manifest, sort_keys=True)
    assert "SECRET-BODY-MUST-NOT-APPEAR" not in manifest_text

    inside_link = by_relative(manifest, "inside-link")[0]
    assert inside_link["type"] == "symlink"
    assert inside_link["readlink_text"] == "inside"
    assert inside_link["link_lexical_owner"] == "inside_authorized_root"
    assert inside_link["link_followed"] is False
    assert target(inside_link).read_text(encoding="utf-8") == "inside"

    outside_link = by_relative(manifest, "outside-link")[0]
    assert outside_link["readlink_text"] == "../outside/secret.txt"
    assert outside_link["link_lexical_owner"] == "outside_authorized_root"
    assert outside_link["link_followed"] is False
    assert target(outside_link).read_text(encoding="utf-8") == "../outside/secret.txt"

    fifo_entry = by_relative(manifest, "pipes/progress.fifo")[0]
    assert fifo.exists()
    assert fifo_entry["type"] == "fifo"
    assert fifo_entry["skip_reason"] == "special_lstat_only"
    assert fifo_entry["opened"] is False
    assert "target" not in fifo_entry

    carrier = by_relative(manifest, "archives/bundle.zip")[0]
    assert carrier["classification"] == "opaque_carrier_bytes"
    assert carrier["header_hex"] == b"PK\x03\x04opaque payload"[:16].hex()
    assert carrier["opaque_unpack_status"] == "not_attempted_preservation_only"
    assert not (tmp_path / "protected/payload/archives/bundle").exists()


@pytest.mark.parametrize("change", [b"after-before-metadata", b"another-change"])
def test_source_change_before_read_is_unclosed_and_does_not_emit_success(
    tmp_path: Path, change: bytes
) -> None:
    source = make_dir(tmp_path / "source")
    mutating = write_private_file(source / "mutating.fit", b"before")
    chmod_tree(source)

    def mutate_once(path: Path) -> None:
        if path == mutating:
            write_private_file(path, change)

    manifest = protect_sources(
        [source],
        tmp_path / "protected",
        preservation_time_label="CHANGED",
        before_read_hook=mutate_once,
    )
    entry = by_relative(manifest, "mutating.fit")[0]
    assert entry["closed"] is False
    assert entry["skip_reason"] == "source_changed_before_copy_closed"
    assert entry["sha256"] is None
    assert "target" not in entry
    assert validate_manifest(tmp_path / "protected") == {
        "status": "verified",
        "entry_count": 1,
    }


def test_database_sidecars_git_material_empty_dirs_and_private_classification(
    tmp_path: Path,
) -> None:
    source = make_dir(tmp_path / "source")
    write_private_file(source / "state/trainlab.db", b"SQLite format 3\x00synthetic")
    write_private_file(source / "state/trainlab.db-wal", b"nonzero wal bytes")
    write_private_file(source / "state/trainlab.db-shm", b"synthetic shm bytes")
    write_private_text(source / "gmail-api-token.json", "SECRET TOKEN BODY")
    write_private_text(source / ".git/HEAD", "ref: refs/heads/main\n")
    write_private_text(source / ".git/refs/heads/main", "0123456789abcdef\n")
    write_private_file(source / ".git/objects/aa/bb", b"synthetic object")
    write_private_file(source / ".git/index", b"synthetic index")
    write_private_text(source / ".git/logs/HEAD", "synthetic reflog\n")
    make_dir(source / ".git/objects/pack")
    write_private_text(source / "worktree/.git", "gitdir: ../.git/worktrees/wt\n")
    chmod_tree(source)

    destination = tmp_path / "protected"
    manifest = protect_sources(
        [source], destination, preservation_time_label="DB-GIT"
    )
    assert manifest["sqlite_connections"] == 0
    assert manifest["db_groups"]["state/trainlab"]["consistency"] == (
        "consistency_unknown_nonzero_wal"
    )
    for relative in (
        "state/trainlab.db",
        "state/trainlab.db-wal",
        "state/trainlab.db-shm",
    ):
        entry = by_relative(manifest, relative)[0]
        assert entry["classification"] == "database_sidecar_bytes"
        assert entry["sidecar_group"] == "state/trainlab"
        assert target(entry).read_bytes() == Path(entry["source"]).read_bytes()

    git_entries = [
        entry
        for entry in manifest["entries"]
        if entry["classification"] == "git_recovery_material"
    ]
    assert {entry["relative_path"] for entry in git_entries} >= {
        ".git/HEAD",
        ".git/refs/heads/main",
        ".git/objects/aa/bb",
        ".git/index",
        ".git/logs/HEAD",
        ".git/objects/pack",
        "worktree/.git",
    }
    assert all(entry["git_recovery_material"] is True for entry in git_entries)
    assert ".git/objects/pack" in manifest["empty_directories"]
    empty_dir = by_relative(manifest, ".git/objects/pack")[0]
    assert empty_dir["source_observed_empty_dir"] is True

    private_entry = by_relative(manifest, "gmail-api-token.json")[0]
    assert private_entry["privacy_classification"] == "private_candidate"
    assert private_entry["classification"] == "private_candidate_bytes"
    manifest_on_disk = (destination / "manifest.json").read_text(encoding="utf-8")
    assert "SECRET TOKEN BODY" not in manifest_on_disk
    assert validate_manifest(destination) == {
        "status": "verified",
        "entry_count": len(manifest["entries"]),
    }
    for path in (destination, *destination.rglob("*")):
        if path.is_dir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        else:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
