# Validator 报告：ADHOC-0031 B3 / ADHOC-0027+0028 独立验证

## 结论

结论：**通过**。适用范围仅限固定快照中的 B3 报告全文存储受控接口，以及 ADHOC-0027/0028 T1～T4 的存储验收；不覆盖 B4～B7、真实 Garmin/AI/网络调用、调度、Context 接线或 Web/API 展示。

## 受审版本与冻结核对

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区存在计划/证据协调记录与 `source/` 未提交产品内容；本次按固定快照验证产品受审内容，未修改仓库、未暂存。
- 快照：`exec-plans/evidence/ADHOC-0031/b3-developer-review-snapshot.json`
- 快照核对：62 个条目的 path/size/mode/sha256 全部一致；聚合 SHA 实算为 `3b476b4bb973df281bfd3f7143d7414f599fa2f09f67150a0ddef0e208bd8c95`，与快照一致。
- 隔离证据目录：`/tmp/trainlab-b3-validator-clean-1789656524/logs`
- 备注：工作树 `source/build/` 存在被忽略的历史生成物，不属于 62 文件受审快照；为避免污染，本次按快照文件重建干净隔离副本运行检查。

## 场景表

| 对应要求 | 类型 | 步骤与输入 | 预期 | 实际结果 | 退出/证据 |
| --- | --- | --- | --- | --- | --- |
| 快照冻结 | 正常 | 校验分支、HEAD；逐文件核对快照 path/size/mode/sha256；按 JSON items 计算聚合 SHA | 62 文件与聚合 SHA 一致 | 一致，聚合 SHA 为 `3b476...8c95` | 0；终端核对输出 |
| 隔离依赖 | 正常 | 从快照重建 `/tmp/trainlab-b3-validator-clean-1789656524/source`；`UV_PROJECT_ENVIRONMENT=/tmp/.../venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 按锁文件安装，不创建仓库 `.venv` | 安装 `trainlab-source==0.1.2` 及 dev 依赖成功 | 0；`uv-sync.log` |
| 全量 Python 回归 | 正常/回归 | `python -m pytest tests -q -p no:cacheprovider` | 全量测试通过 | `171 passed, 2 warnings` | 0；`pytest-all.log` |
| 静态门禁 | 正常/回归 | `ruff check --no-cache .`、`mypy -p trainlab -p tests --no-incremental`、`compileall -q skills schemas tests`、`trainlab.check_architecture` | 全部通过 | Ruff 通过；mypy `Success: no issues found in 40 source files`；compileall 无输出；架构门通过 | 均 0；对应日志 |
| 前端边界 | 回归抽查 | 对比 B2 与 B3 快照中 `source/frontend/**` SHA | B3 未改前端时可说明不跑完整前端 | `frontend_changed_from_b2=[]`，未运行 npm 检查 | 0；终端输出 |
| activties_report Schema | 正常 | 初始化合成 SQLite，检查 `PRAGMA table_info(activties_report)` | 只有 `activity_id,start_time_utc,summary` 三列 | 三列准确，无元数据列 | 0；`probe-reports.log` |
| activties_report 活动关联和 start_time 来源 | 正常/边界 | 插入两条合成 activity：一条有 UTC start，一条 start 为 NULL；调用 `save_activity_report` | 只能保存已有活动；start_time 来自 activities；合法缺失保留 NULL | 有 start 精确保存 `2030-01-02T03:04:05.000000Z`；NULL 原样保留；缺活动报 `ACTIVITY_NOT_FOUND` | 0；`probe-reports.log` |
| activties_report 全文与重复策略 | 正常/边界 | 保存中文、Markdown、SQL/路径片段正文；同一 activity 再保存第二版 | 文本按数据往返；重复保存策略明确且不产生多行 | 原文读取一致；第二版替换当前报告；同 activity 行数仍为 1 | 0；`probe-reports.log` |
| activties_report 错误和回滚 | 错误/边界 | 空白 summary、容量限制、缺活动、触发器失败 | 拒绝并回滚；不破坏 activities/records/weekly_report/config | 均拒绝；异常后五表 dump 与前置状态一致 | 0；`probe-reports.log` |
| weekly_report Schema/ID | 正常/边界 | 检查 `PRAGMA table_info(weekly_report)`；连续保存、删除中间行后再保存 | 只有 `id,run_time_utc,summary`；id SQLite 自增，不要求补洞 | 三列准确；相同 T 可多条；删除后新 id 继续递增 | 0；`probe-reports.log` |
| weekly_report UTC 与同一时间锚 | 正常/边界 | 以 `2030-01-08 11:00 +08:00` 保存；用 `weekly_window(T)` 检查窗口 | run_time_utc 为同一 T 的 UTC，窗口为 `[T-7天,T)` 语义 | 保存为 `2030-01-08T03:00:00.000000Z`；窗口长度 7 天且 end 等于 T | 0；`probe-reports.log` |
| weekly_report 全文/空周固定文本 | 正常 | 保存含 Markdown/SQL 的周报；保存 `本周无任何运动记录` | 全文往返；空周固定文本可保存 | 读取一致；相同 run_time_utc 下多条报告共存 | 0；`probe-reports.log` |
| weekly_report 错误和回滚 | 错误/边界 | 空白 summary、naive datetime、容量限制、触发器失败 | 拒绝并回滚；不破坏 activities/records/activties_report/config | 均拒绝或抛错；五表状态保持 | 0；`probe-reports.log` |
| 安全边界 | 回归/静态 | 检索 `TOOL_CONTRACTS`、报告代码和 README；探针正文包含 SQL/路径片段 | 不新增报告 AI 工具；不接任意 SQL/路径；报告文本不作为指令；README 不冒称 AI/调度/Context/Web 完成 | `TOOL_CONTRACTS` 仍仅 `get_running_records`；报告接口参数化 SQL 且不接路径；README 明确报告生成、同步、AI/Context、完整 Web 仍待后续 | grep 输出；`probe-reports.log` |
| Git 基础检查 | 回归 | `git diff --check && git diff --cached --name-only` | 无空白错误；无暂存 | 命令退出 0；暂存列表为空 | 0；终端输出 |

## 问题表

未发现阻塞问题。未分配 `V31-B3-001`。

| 稳定问题编号 | 对应要求 | 可复现步骤 | 预期与实际 | 影响 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 无 | 无 | 无 | 无 | 无 | 无 |

## 命令摘要

- `git branch --show-current && git rev-parse HEAD && git status --short`：0；分支/HEAD 符合，存在未提交协调记录和受审 `source/`。
- 快照核对 Python 脚本：0；62 文件与聚合 SHA 一致。
- `UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b3-validator-clean-1789656524/venv uv sync --project . --python 3.12 --locked --extra dev --no-editable`：0。
- `python -m pytest tests -q -p no:cacheprovider`：0；171 passed, 2 warnings。
- `python -m ruff check --no-cache .`：0；All checks passed。
- `python -m mypy -p trainlab -p tests --no-incremental`：0；Success。
- `PYTHONDONTWRITEBYTECODE=1 python -m compileall -q skills schemas tests`：0。
- `python -m trainlab.check_architecture`：0；architecture and public Schema checks passed。
- `/tmp/trainlab-b3-validator-clean-1789656524/probe_reports.py`：0；independent report storage probe passed。
- `git diff --check && git diff --cached --name-only`：0；无暂存输出。

## 未验证事项、证据缺口和环境限制

- 未读取真实 `states` 数据、秘密或私人报告。
- 未进行真实 Garmin、AI Provider、网络、费用或调度调用。
- 未运行前端 npm 检查；原因是 B3 相对 B2 快照未修改 `source/frontend/**`，本轮仅做 SHA 抽查。
- B3 仅验证报告存储接口，不证明真实 AI 生成、每日 4 点触发、周 Context、Web/API 展示已完成。
- 隔离副本用于验证固定快照；仓库中被 `.gitignore` 忽略的 `source/build/` 生成物不属于本次产品受审内容。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "已给出结论、版本/快照核对、场景验证、命令结果、未验证事项与残余风险；未发现阻塞问题。"
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "git branch --show-current && git rev-parse HEAD && git status --short",
      "result": "passed",
      "summary": "分支 work/adhoc-0031-local-web-system、HEAD 9db8bb1dda5922e85fe42581e27d2428dbc9f195；存在未提交协调记录和受审 source/。"
    },
    {
      "command": "python snapshot verification script for exec-plans/evidence/ADHOC-0031/b3-developer-review-snapshot.json",
      "result": "passed",
      "summary": "62 个快照文件 path/size/mode/sha256 一致，聚合 SHA 为 3b476b4bb973df281bfd3f7143d7414f599fa2f09f67150a0ddef0e208bd8c95。"
    },
    {
      "command": "UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b3-validator-clean-1789656524/venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "隔离安装成功，未创建仓库 .venv。"
    },
    {
      "command": "/tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "171 passed, 2 warnings。"
    },
    {
      "command": "/tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "/tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 40 source files。"
    },
    {
      "command": "PYTHONDONTWRITEBYTECODE=1 /tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python -m compileall -q skills schemas tests",
      "result": "passed",
      "summary": "无错误输出。"
    },
    {
      "command": "/tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "architecture and public Schema checks passed。"
    },
    {
      "command": "/tmp/trainlab-b3-validator-clean-1789656524/venv/bin/python /tmp/trainlab-b3-validator-clean-1789656524/probe_reports.py",
      "result": "passed",
      "summary": "独立覆盖活动/周报告正常、错误、边界、回滚、工具边界场景。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/uv-sync.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/pytest-all.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/ruff.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/mypy.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/compileall.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/architecture.log",
    "/tmp/trainlab-b3-validator-clean-1789656524/logs/probe-reports.log"
  ],
  "residualRisks": [
    "未验证真实 Garmin/AI/网络/调度/私人 states。",
    "未运行前端 npm 检查；B3 未修改 source/frontend/**，仅做快照 SHA 抽查。",
    "本结论只覆盖 B3 存储接口，不覆盖 B4～B7 或完整 Web/API/Context 闭环。",
    "仓库存在被忽略的 source/build/ 历史生成物；本次按固定62文件快照重建干净副本验证，未把该生成物纳入产品受审内容。"
  ],
  "noStagedFiles": true,
  "diffSummary": "Validator 未修改受审内容；报告写入指定子代理输出路径。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "结论：通过。证据目录为 /tmp/trainlab-b3-validator-clean-1789656524/logs；独立探针覆盖 activties_report 与 weekly_report 的 Schema、全文往返、错误拒绝、回滚和安全边界。"
}
```