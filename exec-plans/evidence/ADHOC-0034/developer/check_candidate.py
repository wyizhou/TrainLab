import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[4]
MATERIALS = ROOT.parent / "materials"
BASELINE_SHA = "6e78707006789bed4a11ffc4b26ac807c392c36cb0146caadbf173615c9bd751"
UPSTREAM_HEAD = "37520a5132bb5f84064e04f18d7a4467ebdc9116"
EVIDENCE = "exec-plans/evidence/ADHOC-0034/developer/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def section(text, title):
    return text.split("## " + title + "\n", 1)[1].split("\n## ", 1)[0]


def fields(text, title):
    return [line[2:] for line in section(text, title).splitlines() if line.startswith("- ")]


def main():
    baseline_bytes = (MATERIALS / "developer-baseline.json").read_bytes()
    check(sha(baseline_bytes) == BASELINE_SHA, "baseline SHA")
    baseline = json.loads(baseline_bytes)
    upstream = json.loads((MATERIALS / "upstream.json").read_text())
    check(upstream["head"] == UPSTREAM_HEAD, "upstream commit")
    check(git("branch", "--show-current").strip() == baseline["branch"], "branch")
    check(git("rev-parse", "HEAD").strip() == baseline["head"], "HEAD")
    check(not git("diff", "--cached", "--name-only"), "staged changes")
    allowed = set(baseline["allowed_changes"])
    check(len(allowed) == 8, "eight authorized files")
    inventory = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")) - {""}
    missing = set(baseline["files"]) - inventory
    added = inventory - set(baseline["files"])
    check(not missing, "missing baseline files: " + repr(missing))
    check(all(p in allowed or p.startswith(EVIDENCE) for p in added), "out-of-scope new files")
    check({p for p in inventory if p.startswith("states/")} == {
        "states/Goal-example.md", "states/activities/.gitkeep",
        "states/health/.gitkeep", "states/verification/.gitkeep",
    }, "only four public baseline states files may be hashed")
    changed = []
    current = {}
    for p in sorted(inventory):
        file = ROOT / p
        check(not file.is_symlink(), "unexpected symlink: " + p)
        current[p] = sha(file.read_bytes())
        if p in baseline["files"] and current[p] != baseline["files"][p]:
            changed.append(p)
    check(set(changed) == allowed - {"skills/web-browser-acceptance/SKILL.md"}, "exact changed file set")
    check(all(current[p] == digest for p, digest in baseline["files"].items() if p not in allowed), "protected content")
    filesystem = set()
    for directory, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".git", "states"}]
        for name in files:
            p = (Path(directory) / name).relative_to(ROOT).as_posix()
            if p != ".git":
                filesystem.add(p)
    check(not filesystem - inventory, "unexpected ignored/non-Git files: " + repr(filesystem - inventory))
    for p, digest in upstream["files"].items():
        check(sha((MATERIALS / "upstream" / p).read_bytes()) == digest, "upstream SHA: " + p)
    for p in allowed - {"skills/README.md"}:
        check((ROOT / p).read_bytes() == (MATERIALS / "upstream" / p).read_bytes(), "byte equality: " + p)
    old_index = git("show", "HEAD:skills/README.md")
    old_line = "当前目录没有SKILL.md技能包，因此无技能条目；不把本README当作可执行技能，不生成占位技能。后续有实际技能时再添加相对链接。"
    new_line = "- [网页开发与浏览器验收](./web-browser-acceptance/SKILL.md)：适用于网页开发、修改、修复与交付验收。"
    check(old_index.count(old_line) == 1, "old index replacement uniqueness")
    check((ROOT / "skills/README.md").read_text() == old_index.replace(old_line, new_line), "minimal skills index change")
    readme = (ROOT / "README.md").read_text()
    upstream_readme = (MATERIALS / "upstream/README.md").read_text()
    check(readme.split("## MIT 授权\n", 1)[1] == upstream_readme.split("## MIT 授权\n", 1)[1], "complete MIT license")
    check("Copyright (c) 2026 wyizhou" in readme and readme.endswith("SOFTWARE.\n"), "license boundaries")
    check((ROOT / "references/README.md").read_bytes().startswith((MATERIALS / "upstream/references/README.md").read_bytes()), "reference introduction retained")
    skill_dir = ROOT / "skills/web-browser-acceptance"
    check(sorted(p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*") if p.is_file()) == ["SKILL.md"], "single-file skill")
    skill = (skill_dir / "SKILL.md").read_text()
    check(skill.startswith("---\nname: web-browser-acceptance\ndescription:"), "skill front matter")
    check("本技能仅由本 Markdown 文档组成" in skill, "self-contained skill")
    check("仅涉及说明文档、且不影响网页行为的修改：无需启动浏览器验收" in skill, "documentation exemption")
    expected_plan_fields = [
        "当前环节所需输入及就绪依据：",
        "规划审核情况及依据：",
        "并行任务、角色、各功能独立目录与分支、各 Developer 写入范围（每目录最多一名）：",
        "共享文件、接口及重要数据规则的修改归属、消费方固定版本与交接条件：",
        "受审内容、未提交差异及相关依赖的固定位置与核对方法：",
        "写入隔离与测试资源安排（含数据库、账号、端口等）：",
        "冲突或暂停影响的任务及依赖链、恢复条件：",
        "组合与冲突处理责任方、实际组合版本及相关依赖：",
        "最终组合版本的适用集成检查、独立验证和主 Agent 验收安排（版本变化影响结果时补查和复验）：",
    ]
    check(fields((ROOT / "exec-plans/template.md").read_text(), "流水线与并行开发安排") == expected_plan_fields, "nine parallel plan fields")
    role_fields = {}
    for role in ["planner", "developer", "validator"]:
        path = "subagent-templates/" + role + ".md"
        text = (ROOT / path).read_text()
        listed = fields(text, "本次任务材料")
        for prefix in ["任务类型", "目标与对应编号", "验收标准", "适用规则", "工作目录与分支", "材料位置与来源", "共享文件", "输入与预期输出", "允许修改范围", "错误边界", "停止条件与报告对象", "检查方法或命令", "返回内容与证据保存位置"]:
            check(any(f.startswith(prefix) for f in listed), role + " missing field: " + prefix)
        for phrase in ["就绪", "每目录最多一名", "固定版本", "交接条件", "实际组合版本", "相关依赖", "复验", "测试资源"]:
            check(any(phrase in f for f in listed), role + " missing parallel material: " + phrase)
        if role == "developer":
            check(any("已审核规划的依据" in f for f in listed), "development requires approved plan")
            check(any("禁止写入范围" in f for f in listed), "developer fixed review exclusion")
        if role == "validator":
            check(any("含实际未提交差异及所需文件" in f for f in listed), "validator freezes actual differences")
            check("证据仅对应实际核对的固定内容及依赖，不用于变化后的版本" in text, "validator evidence binding")
        role_fields[role] = listed
    link_results = []
    checked_docs = sorted(allowed | {"references/README.md"})
    for p in checked_docs:
        text = (ROOT / p).read_text()
        check(not re.search(r"(?:/Users/|/home/|/private/var/|/var/folders/|[A-Za-z]:\\)", text), "absolute filesystem path: " + p)
        check(not re.search(r"\b(?:OpenAI|Anthropic|ChatGPT|Claude|Codex|Gemini)\b", text, re.I), "specific AI product: " + p)
        for match in re.finditer(r"\[[^\]\n]*\]\(([^)\s]+)\)", text):
            target = match.group(1)
            parsed = urlsplit(target)
            if parsed.scheme:
                continue
            check(not parsed.path.startswith("/"), "non-relative link: " + p)
            resolved = (ROOT / p).parent / unquote(parsed.path) if parsed.path else ROOT / p
            resolved = resolved.resolve()
            check(resolved.is_relative_to(ROOT), "escaping local link: " + p)
            check(resolved.exists(), "missing target: " + p + " -> " + target)
            if parsed.fragment:
                headings = re.findall(r"^#{1,6}\s+(.+)$", resolved.read_text(), re.M)
                anchors = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}
                check(unquote(parsed.fragment) in anchors, "missing anchor: " + target)
            link_results.append({"source": p, "target": target, "line": text[:match.start()].count("\n") + 1})
    diff_check = subprocess.run(["git", "diff", "--check"], cwd=ROOT, text=True, capture_output=True)
    check(diff_check.returncode == 0, "git diff --check: " + diff_check.stdout + diff_check.stderr)
    return {
        "result": "passed", "scope": "T02 candidate H self-check, not independent or final acceptance",
        "baseline_sha256": BASELINE_SHA, "baseline_files": len(baseline["files"]),
        "branch": baseline["branch"], "head": baseline["head"], "upstream_commit": UPSTREAM_HEAD,
        "upstream_files_verified": len(upstream["files"]), "byte_identical_files": 7,
        "candidate_h_sha256": {p: current[p] for p in sorted(allowed | {"references/README.md"})},
        "changed_baseline_files": changed, "added_files": sorted(added),
        "unchanged_baseline_files": len(baseline["files"]) - len(changed),
        "protected_source_files": sum(p.startswith("source/") for p in baseline["files"]),
        "protected_reference_files": sum(p.startswith("references/") for p in baseline["files"]),
        "inventory": sorted(inventory), "filesystem_scan": "All non-states, non-.git files match Git tracked/untracked inventory; no unexpected ignored files",
        "parallel_plan_fields": expected_plan_fields, "role_material_fields": role_fields,
        "local_links": link_results, "local_link_count": len(link_results),
        "license": "Complete upstream MIT section unchanged; no assertion about historical product relicensing",
        "skills_index": "One paragraph replaced with upstream link; project boundary paragraph unchanged",
        "git_status": git("status", "--short"), "no_staged_files": True,
        "git_diff_check_exit": diff_check.returncode,
        "not_run": ["Original user worktree/protected dirty files recheck", "C34/Cuse assembly and independent/final acceptance", "Remote freshness and Git delivery", "Product, browser, actual multi-writer runtime"],
    }


if __name__ == "__main__":
    try:
        result = main()
    except Exception as exc:
        print(json.dumps({"result": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))
