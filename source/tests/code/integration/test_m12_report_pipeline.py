"""R4 closed resources and version-fixed local output, no test/archive dependency."""

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from skills._shared.fit_weekly import runtime_resources

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_report_factory")


def test_closed_report_edit_seal_and_relocation(tmp_path, monkeypatch):
    root, _, calls = f.setup(tmp_path, monkeypatch)
    source = Path(__file__).resolve().parents[3]
    closed = tmp_path / "closed"
    for path in runtime_resources.files(source):
        target = closed / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    assert not (closed / "tests").exists() and not (closed / "data-backup").exists()
    program = """
import json, sys
from pathlib import Path
from skills._shared.fit_weekly import report_revisions as r, report_artifacts as a, model_job, storage
root, end = Path(sys.argv[1]), sys.argv[2]
base = r.create(root, end)
s = model_job.clone(base['summary_content'])
s['core_conclusions'][0]['text'] = '仅依据现有记录，仍有数据局限。'
revision = r.edit(root, end, base_revision_id='ai', base_revision_sha256=model_job.sha(base), revision_id='local-edit', target='summary', content=s)
bundle = a.read(root, end, 'local-edit', model_job.sha(revision))
a.seal(root, end, 'local-edit', model_job.sha(revision))
moved = root.with_name('relocated')
root.rename(moved)
assert a.read_sealed(moved, end) == bundle
assert r.create(moved, end) == base
assert bundle.plan['days'][0]['date'] == '2026-08-10'
assert len(bundle.plan['days']) == 7
assert bundle.pdf.startswith(b'%PDF-')
assert storage.digest(bundle.pdf) == bundle.manifest['pdf_sha256']
for name, module in tuple(sys.modules.items()):
    if name.startswith('skills.') and getattr(module, '__file__', None):
        assert Path(module.__file__).is_relative_to(Path.cwd())
print(json.dumps({'revision': revision['revision_id'], 'days': len(bundle.plan['days']), 'pdf_sha256': bundle.manifest['pdf_sha256']}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root), f.END],
        cwd=closed,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["revision"] == "local-edit" and result["days"] == 7
    assert len(result["pdf_sha256"]) == 64
    assert [c.calls for c in calls] == [1, 1]
