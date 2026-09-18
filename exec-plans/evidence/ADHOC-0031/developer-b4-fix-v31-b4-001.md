# Developer 修复报告：V31-B4-001

## 修改摘要

修复 ADHOC-0031 B4 / 0031-T3 的 V31-B4-001：已有上次成功同步状态时，本轮同步若部分活动已成功导入、后续活动导入失败，持久化状态必须保留上一轮 `last_success_at_utc`，不能写成 `null`。

对应改动：

- `source/skills/_shared/scripts/trainlab/garmin_sync.py`：部分成功后的中间状态从写入 `last_success_at_utc=None` 改为保留本轮开始时的 `attempted_state.last_success_at_utc`。
- `source/tests/sync/test_garmin_sync.py`：新增回归测试，直接覆盖 Validator 场景：已有 `last_success`，本轮 force 两个新活动，第一个导入成功，第二个导入失败；结果失败、失败 FIT 原件保留、失败 remote 不标记、成功 remote 可保留、`last_success_at_utc` 保持上一轮成功时间。
- `source/pyproject.toml`、`source/skills/_shared/scripts/trainlab/__init__.py`、`source/uv.lock`：版本同步到 `0.1.4`，保证 `uv sync --locked --no-editable` 安装的包包含本次修复。

## 修复说明

失败原因：原实现每成功导入一个远端活动后会保存中间状态，但该中间状态把 `last_success_at_utc` 写成 `None`。如果后续活动导入失败，失败处理会再次保存这个中间状态，导致上一轮成功时间丢失，下一轮 `sync_window()` 会回退到首次七天窗口。

本次办法与原实现的实质区别：保留“部分成功可持久化”的设计，只把中间状态的 `last_success_at_utc` 改为沿用本轮开始时已有的上次成功时间；最终全量成功时仍写入本轮 `now`。这样不会牺牲已成功远端的持久化，也不会把失败远端标记为 synced。

累计失败事实：V31-B4-001 首次独立验证失败 1；本次为修复尝试 1，开发自查全部通过，仍需全新 Validator 复验。

## 实际版本与未提交改动

- 工作目录：`/Volumes/DiskOther/Code/TrainLab`
- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始前已有未提交计划/证据移动和 `source/` 产品实现；本次只修改允许范围内的 `source/**` 文件，未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步锁文件 | `trainlab-source v0.1.3 -> v0.1.4` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/uv-lock.log` |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-fix-v31-b4-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 仓库外隔离安装，安装包包含修复 | 通过，安装 `trainlab-source==0.1.4`，源码检查确认安装包使用 `attempted_state.last_success_at_utc` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/uv-sync.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m pytest tests/sync/test_garmin_sync.py -q -p no:cacheprovider` | B4 同步测试通过 | `7 passed` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/pytest-sync-final3.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `178 passed, 2 warnings` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/pytest-all-final3.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/ruff-final3.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 44 source files` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/mypy-final3.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/compileall-final3.log` |
| `cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/architecture-final3.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0；`/tmp/trainlab-b4-fix-v31-b4-001-logs/git-diff-check-final3.log`、`/tmp/trainlab-b4-fix-v31-b4-001-logs/staged-final3.log` |

## 未运行 / 未解决事项

- 未做真实 Garmin、pygarminconnect、网络、登录/MFA、私人 `states/verification/garmin.json` 或私人活动数据调用，符合本次边界。
- 未推进 B5～B7。
- 本次是 Developer 修复自查，不替代后续全新只读 Validator 复验。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅修复 V31-B4-001：中间同步状态保留 attempted_state.last_success_at_utc，新增回归测试覆盖已有 last_success 时部分导入失败场景；未扩大到真实 Garmin 或后续阶段。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、失败原因、修复方式、命令结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/garmin_sync.py",
    "source/tests/sync/test_garmin_sync.py",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/sync/test_garmin_sync.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 版本到 0.1.4。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-fix-v31-b4-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建仓库外隔离环境并安装 trainlab-source==0.1.4。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m pytest tests/sync/test_garmin_sync.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "7 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "178 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 44 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b4-fix-v31-b4-001-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门通过。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/uv-lock.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/uv-sync.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/pytest-sync-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/pytest-all-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/ruff-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/mypy-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/compileall-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/architecture-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/git-diff-check-final3.log",
    "/tmp/trainlab-b4-fix-v31-b4-001-logs/staged-final3.log"
  ],
  "residualRisks": [
    "未做真实 Garmin/pygarminconnect/网络/私人凭据调用。",
    "真实适配器仍需后续受控真实联调验证。",
    "本次自查不替代全新只读 Validator 复验。"
  ],
  "noStagedFiles": true,
  "diffSummary": "将部分成功后的中间状态 last_success_at_utc 改为保留上一轮成功时间，新增对应回归测试，并同步 source 包版本/锁文件到 0.1.4 以支持 locked no-editable 安装。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "调试中曾发现 no-editable venv 未自动拾取同版本源码修改，因此同步了 pyproject/__init__/uv.lock 版本到 0.1.4；最终检查均使用新隔离 venv 通过。"
}
```