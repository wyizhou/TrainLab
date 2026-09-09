"""Byte-bound local artifacts and a single durable publication selection."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    model_job,
    storage,
)
from skills._shared.fit_weekly import (
    report_artifacts as artifacts,
)
from skills._shared.fit_weekly import (
    report_revisions as revisions,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_report_factory")


def prepared(tmp_path, monkeypatch):
    root, _, calls = f.setup(tmp_path, monkeypatch)
    revision = revisions.create(root, f.END)
    manifest = artifacts.render(root, f.END, "ai", model_job.sha(revision))
    return root, revision, manifest, calls


def test_artifact_replay_and_fixed_publication_survive_move(tmp_path, monkeypatch):
    root, revision, manifest, calls = prepared(tmp_path, monkeypatch)
    assert artifacts.render(root, f.END, "ai", model_job.sha(revision)) == manifest
    bundle = artifacts.read(root, f.END, "ai", model_job.sha(revision))
    assert storage.digest(bundle.markdown) == manifest["markdown_sha256"]
    assert storage.digest(bundle.pdf) == manifest["pdf_sha256"]
    assert (
        bundle.plan
        == revisions.view(root, f.END, "ai", model_job.sha(revision))["plan"]
    )
    sealed = artifacts.seal(root, f.END, "ai", model_job.sha(revision))
    assert artifacts.seal(root, f.END, "ai", model_job.sha(revision)) == sealed
    with pytest.raises(ValueError, match="sealed"):
        revisions.edit(
            root,
            f.END,
            base_revision_id="ai",
            base_revision_sha256=model_job.sha(revision),
            revision_id="after-intent",
            target="summary",
            content=f.edited_summary(revision),
        )
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert artifacts.read_sealed(moved, f.END) == bundle
    assert [c.calls for c in calls] == [1, 1]
    for p in (moved / "reports").rglob("*"):
        assert p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)


@pytest.mark.parametrize("name", ["report.md", "report.pdf"])
def test_damaged_missing_or_symlink_artifact_not_publishable(
    tmp_path, monkeypatch, name
):
    root, revision, manifest, _ = prepared(tmp_path, monkeypatch)
    path = root / "reports" / model_job.sha(revision) / name
    original = path.read_bytes()
    path.write_bytes(b"broken")
    with pytest.raises(ValueError):
        artifacts.seal(root, f.END, "ai", model_job.sha(revision))
    path.unlink()
    with pytest.raises(ValueError):
        artifacts.read(root, f.END, "ai", model_job.sha(revision))
    # A missing completed artifact may be recovered from the exact same renderer;
    # a changed byte stream must never replace its committed SHA.
    assert artifacts.render(root, f.END, "ai", model_job.sha(revision)) == manifest
    assert path.read_bytes() == original
    path.unlink()
    target = tmp_path / name
    target.write_bytes(original)
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(ValueError):
        artifacts.read(root, f.END, "ai", model_job.sha(revision))


def test_interrupted_render_has_no_publishable_manifest_and_can_resume(
    tmp_path, monkeypatch
):
    root, _, calls = f.setup(tmp_path, monkeypatch)
    revision = revisions.create(root, f.END)
    original = storage.atomic_file

    def stop(path, data):
        if path.name == "report.pdf":
            raise OSError("synthetic interrupted PDF commit")
        original(path, data)

    with monkeypatch.context() as m:
        m.setattr(storage, "atomic_file", stop)
        with pytest.raises(OSError):
            artifacts.render(root, f.END, "ai", model_job.sha(revision))
    with pytest.raises(ValueError):
        artifacts.seal(root, f.END, "ai", model_job.sha(revision))
    artifacts.render(root, f.END, "ai", model_job.sha(revision))
    assert artifacts.read(root, f.END, "ai", model_job.sha(revision)).pdf.startswith(
        b"%PDF-"
    )
    assert [c.calls for c in calls] == [1, 1]


def test_publication_never_reads_latest_or_reauthorizes_another_revision(
    tmp_path, monkeypatch
):
    root, base, _, _ = prepared(tmp_path, monkeypatch)
    edited = revisions.edit(
        root,
        f.END,
        base_revision_id="ai",
        base_revision_sha256=model_job.sha(base),
        revision_id="edited",
        target="summary",
        content=f.edited_summary(base),
    )
    artifacts.render(root, f.END, "edited", model_job.sha(edited))
    artifacts.seal(root, f.END, "ai", model_job.sha(base))
    assert artifacts.read_sealed(root, f.END).revision == base
    with pytest.raises(ValueError, match="conflict"):
        artifacts.seal(root, f.END, "edited", model_job.sha(edited))


def test_edit_and_seal_share_instance_lock(tmp_path, monkeypatch):
    root, base, _, _ = prepared(tmp_path, monkeypatch)
    with storage.open_store(root):
        with pytest.raises(ValueError, match="busy"):
            artifacts.seal(root, f.END, "ai", model_job.sha(base))
