import hashlib
import json
import re
import subprocess
from pathlib import Path

M = Path(__file__).resolve().parent.parent
W = M.parent / "worktree"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    p = subprocess.run(["git", "-C", str(W), *args], capture_output=True, text=True, check=True)
    return p.stdout.strip()

manifest = json.loads((M / "manifest.json").read_text())
upstream = json.loads((M / "upstream.json").read_text())
comparison = json.loads((M / "file-comparison.json").read_text())
baseline = json.loads((M / "baseline.json").read_text())
assert sha(M / "manifest.json") == "e4466ad36bafcf3b839d0212e0af251c218043b601f5084491ab9982e0645885"
assert len(manifest) == 29
assert all(sha(M / p) == h for p, h in manifest.items())
assert len(upstream["files"]) == 11
assert all(sha(M / "upstream" / p) == h for p, h in upstream["files"].items())
assert set(comparison) == set(upstream["files"])
rows = []
for p, record in comparison.items():
    current = M / "current" / p
    local = sha(current) if current.exists() else None
    rows.append({"path": p, "current_sha256": local, "upstream_sha256": sha(M / "upstream" / p),
                 "comparison_local_matches": local == record["local_sha256"],
                 "worktree_matches_current": sha(W / p) == local if current.exists() and (W / p).exists() else None})
    assert record["upstream_sha256"] == sha(M / "upstream" / p)
    if p != "PLAN.md":
        assert local == record["local_sha256"]

text = (M / "upstream.diff").read_text()
section = text.split("--- local/PLAN.md\n+++ upstream/PLAN.md\n", 1)[1].split("--- local/README.md", 1)[0]
old_plan = "".join(line[1:] for line in section.splitlines(keepends=True) if line.startswith(("-", " ")))
old_sha = hashlib.sha256(old_plan.encode()).hexdigest()
assert old_sha == comparison["PLAN.md"]["local_sha256"]
import difflib
plan_delta = list(difflib.unified_diff(old_plan.splitlines(), (M / "current/PLAN.md").read_text().splitlines(), lineterm=""))
additions = [line[1:] for line in plan_delta if line.startswith("+") and not line.startswith("+++")]
deletions = [line[1:] for line in plan_delta if line.startswith("-") and not line.startswith("---")]
assert not deletions and len(additions) == 2
assert all(not line or "ADHOC-0034" in line for line in additions)

links = []
for p in upstream["files"]:
    content = (M / "upstream" / p).read_text()
    for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", content):
        if "://" in target or target.startswith("#"):
            continue
        file_part = target.split("#", 1)[0]
        exists = (M / "upstream" / Path(p).parent / file_part).exists()
        links.append({"from": p, "target": target, "exists": exists})
        assert exists
skill = (M / "upstream/skills/web-browser-acceptance/SKILL.md").read_text()
assert "本技能仅由本 Markdown 文档组成" in skill
assert "仅涉及说明文档、且不影响网页行为的修改：无需启动浏览器验收" in skill
assert (M / "current/references/README.md").read_bytes().startswith((M / "upstream/references/README.md").read_bytes())
assert git("rev-parse", "HEAD") == "af09e3f4b7522e9826eb1655bc8a0cf58a79ba4d"
assert git("branch", "--show-current") == "work/adhoc-0034-agentsmd-parallel"
assert not git("status", "--porcelain")
assert not git("diff", "--cached", "--name-only")
result = {
    "manifest_sha256": sha(M / "manifest.json"), "manifest_files_verified": len(manifest),
    "upstream_commit": upstream["head"], "upstream_files_verified": len(rows), "files": rows,
    "upstream_relative_links": links,
    "plan_comparison_timing": {"comparison_sha": old_sha, "manifest_current_sha": sha(M / "current/PLAN.md"), "additions_only": additions},
    "baseline_protected_entries": len(baseline["source_files"]),
    "baseline_source_entries": sum(p.startswith("source/") for p in baseline["source_files"]),
    "baseline_source_changes": baseline["source_changes"],
    "worktree_head": git("rev-parse", "HEAD"), "worktree_branch": git("branch", "--show-current"),
    "worktree_clean": True, "staging_empty": True,
    "limits": ["Only provided material hashes verified; original dirty workspace not accessed.", "No network, product, browser, install, or Git write operations.", "Evidence proves source-material consistency, not completed upgrade acceptance."]
}
(M / "planner-evidence/check-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"manifest_files_verified": len(manifest), "upstream_files_verified": len(rows), "relative_links_verified": len(links), "protected_entries_in_supplied_baseline": len(baseline["source_files"]), "plan_delta_additions_only": len(additions), "worktree_clean": True}, ensure_ascii=False))
