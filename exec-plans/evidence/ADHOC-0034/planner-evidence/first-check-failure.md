# 静态检查器首次失败

- 命令：`python3 ../materials/planner-evidence/check_materials.py && git diff --check && git status --short && git diff --cached --name-only`
- 退出：1；后续三个Git命令因`&&`未运行。
- 原异常：`check_materials.py`第47行，`assert not deletions and len(additions) == 3`触发`AssertionError`。
- 原因与核对：检查器错误预设当前PLAN比差异生成时多三行；用标准库`difflib.unified_diff(..., n=0)`实际核得仅两行新增：ADHOC-0034功能行及“当前任务切换”说明，无删除。旧PLAN重构SHA与comparison一致，当前PLAN SHA与manifest一致。
- 修正：只将检查器行数改为实测2，保留必须无删除且新增均含ADHOC-0034的约束；未修改任何输入材料或worktree文件。这是静态检查器假设错误，不是产品或升级验收失败。
