# ADHOC-0031 B2 / ADHOC-0025+0026 独立验证报告

## 结论

**通过（适用范围：固定快照 `exec-plans/evidence/ADHOC-0031/b2-developer-review-snapshot.json` 的 59 个受审产品文件）**。

核心语义、只读安全、工具声明/README/Schema 一致性、Python/前端常规检查均已在 `/tmp` 隔离副本验证。未调用真实 Garmin、AI、网络、真实 `states` 数据或密钥。

注意：在隔离副本内直接执行朴素 `mypy .` 会因项目多 Skill 目录均名为 `scripts` 以及安装构建产物 `build/lib` 触发 mypy 重复模块报错；按 B2 相关源码/测试范围及模块入口执行 mypy 通过。此为检查入口限制，未发现 B2 运行语义缺陷。

## 受审版本与冻结核对

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 当前工作区存在计划/证据及 `source/` 未提交变更；产品核对以固定快照为准。
- 快照：59 文件，`product_aggregate_sha256 = 8b3f7c0349cf2194abef6bb2e39913f3fa6dbd8ce2924bf378ea6ecf96864114`
- 核对结果：逐文件 path/size/mode/sha256 全部一致；按 `json.dumps(items, sort_keys=True, separators=(",", ":"))` 重算聚合 SHA 与快照一致。
- 隔离验证目录：`/tmp/trainlab-b2-validator-clean-yPzyHR`
- 证据目录：`/tmp/trainlab-b2-validator-clean-yPzyHR/logs`

## 场景表

| 要求 | 类型 | 步骤与输入 | 预期 | 实际/退出结果 | 证据 |
|---|---|---|---|---|---|
| 快照冻结 | 正常 | 核 branch/HEAD/status；读取快照并逐文件核 SHA/size/mode；重算聚合 SHA | 与任务给定版本一致 | 一致 | 命令输出；本报告“受审版本” |
| 依赖安装 | 正常 | `/tmp` 复制受审 `source/`；`uv venv --python 3.12`；`uv pip install '.[dev]'` | 不写仓库 `.venv`，依赖可安装 | 通过 | `npm-ci.log`、安装命令输出 |
| Python 全量测试 | 回归 | `python -m pytest` | 全部通过 | 163 passed, 2 warnings | `pytest.log` |
| Ruff | 回归 | `python -m ruff check .` | 通过 | All checks passed | `ruff.log` |
| mypy（B2 相关源码/测试） | 回归 | `python -m mypy skills/_shared/scripts/trainlab tests/contracts tests/tools`；另跑模块入口 `-m trainlab.running_records -m trainlab.contracts.interfaces -m trainlab.local_web.server` | 通过 | 均通过 | `mypy-b2-scope.log`、`mypy-modules-b2.log` |
| mypy（朴素全目录） | 环境/入口限制 | `python -m mypy .`；移除构建产物后复跑 | 应有可用入口 | 失败：重复模块 `trainlab`/`scripts`；未作为 B2 语义失败 | `mypy-dot.log`、`mypy-dot-after-rm-build.log` |
| compileall | 回归 | `python -m compileall -q .` | 通过 | 退出 0 | `compileall.log` |
| 架构门 | 回归 | `python -m trainlab.check_architecture`（venv 在 source 外） | 通过 | `architecture and public Schema checks passed` | `architecture.log` |
| 前端回归 | 回归 | `npm ci`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build` | 通过 | lint/typecheck/test/build 均通过；vitest 3 passed | `frontend-*.log` |
| get_running_records 成功 | 正常/边界 | 合成 SQLite running 活动，授权集合包含 activity_id；records 含原 record_index、重复/缺失时间、0 值、JSON metrics 对象 | 全量返回，顺序不变，顶层 activity_id 唯一，结果 Schema 有效 | 通过 | `semantic.log`、`tests/tools/test_running_records.py` |
| 参数拒绝 | 错误 | `handle_get_running_records` 传 `limit/cursor/sql/path/database/metrics/start_time/end_time` 等额外参数，db_path 指向缺失库 | `INVALID_ARGUMENT`，`data=null`，不访问/创建库 | 通过 | `semantic.log` |
| 授权/运动类型/活动存在性 | 错误 | 未授权、cycling、unknown sport、活动不存在 | 固定失败且 `data=null` | 通过：分别返回 `TOOL_NOT_ALLOWED`、`SPORT_NOT_ALLOWED`、`SPORT_UNKNOWN`、`ACTIVITY_NOT_FOUND` | `semantic.log` |
| 无库/坏 JSON/unsupported schema/容量超限 | 错误/边界 | 缺失 DB、破坏 `metrics_json`、改 schema_version、容量限制 1 byte | 整体失败，`data=null`，不截断不造库 | 通过：`DATABASE_UNAVAILABLE`、`DATA_INVALID`、`SCHEMA_UNSUPPORTED`、`RESOURCE_LIMIT` | `semantic.log` |
| 只读/安全 | 安全 | 查询前后 dump SQLite；报告表、weekly、config 已填充；缺失 DB 场景检查文件不存在 | 数据库不变，不读 FIT 原件/任意路径，不接受 SQL/路径 | 通过；源码入口仅接受宿主 `db_path` 和 auth/capacity，SQL 参数化只读 `mode=ro/query_only` | `semantic.log`；`running_records.py`、`database.py` 人工检查 |
| 字典闭包 | 正常/人工 | 检查 `definition_closure` 与 `_read_records` 选择逻辑 | 返回实际引用字段的定义闭包与所需 developer_sources | 通过；使用字段经 `definition_closure` 补父字段，sources 只随选中定义的 `source_ref` 返回 | `running_records.py`、`json_validation.py` 人工检查 |
| ADHOC-0026 工具索引 | 合同 | 检查 README、`TOOL_CONTRACTS`、Schema、实际函数 | 当前仅注册 `get_running_records`；`read_reference` 不冒称可用 | 通过；`TOOL_CONTRACTS` 只有 `get_running_records`，README 明示 B5/read_reference 未注册 | `semantic.log`；`grep`/人工检查 |

## 问题表

无 B2 阻塞问题。未分配 `V31-B2-*`。

非阻塞检查入口限制：朴素 `mypy .` 在隔离副本失败，原因是当前项目布局下多个目录映射为同名模块 `scripts`，且安装命令会生成 `build/lib` 重复包；B2 相关 mypy 命令通过。若项目希望“全仓 mypy .”成为固定门禁，需要后续明确统一 mypy 入口或排除规则。

## 未验证事项 / 证据缺口 / 环境限制

- 未做真实 Garmin、AI Provider、网络、真实 `states` 或密钥访问，符合任务边界。
- 未验证 B3～B7 后续阶段能力。
- 未以真实复杂 FIT 开发者字段样本动态验证 developer_sources 非空返回；对闭包与来源选择采用源码审查加现有 Schema/测试覆盖确认。
- 证据保存在 `/tmp/trainlab-b2-validator-clean-yPzyHR/logs`，属于临时目录。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "报告给出结论、场景结果、问题表和残余风险；验证证据位于 /tmp/trainlab-b2-validator-clean-yPzyHR/logs"
    }
  ],
  "changedFiles": [
    "/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/7b9869e5-affb-40db-bfab-9b0d60df14a1/adhoc0031/validator-b2.md"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "git branch --show-current && git rev-parse HEAD && git status --short",
      "result": "passed",
      "summary": "分支和 HEAD 符合任务；工作区有既有计划/证据/source 未提交变更"
    },
    {
      "command": "snapshot sha/size/mode/product aggregate verification script",
      "result": "passed",
      "summary": "59 个受审文件逐项一致，聚合 SHA 匹配 8b3f7c0349cf2194abef6bb2e39913f3fa6dbd8ce2924bf378ea6ecf96864114"
    },
    {
      "command": "uv venv --python 3.12 /tmp/.../venv && uv pip install --python /tmp/.../venv/bin/python '.[dev]'",
      "result": "passed",
      "summary": "隔离依赖安装成功，未创建仓库 .venv"
    },
    {
      "command": "python -m pytest",
      "result": "passed",
      "summary": "163 passed, 2 warnings"
    },
    {
      "command": "python -m ruff check .",
      "result": "passed",
      "summary": "All checks passed"
    },
    {
      "command": "python -m mypy skills/_shared/scripts/trainlab tests/contracts tests/tools; python -m mypy -m trainlab.running_records -m trainlab.contracts.interfaces -m trainlab.local_web.server",
      "result": "passed",
      "summary": "B2 相关源码/测试和模块入口 mypy 均通过"
    },
    {
      "command": "python -m mypy .",
      "result": "failed",
      "summary": "朴素全目录入口因 build/lib 与多 scripts 目录重复模块失败，记录为入口限制"
    },
    {
      "command": "python -m compileall -q .",
      "result": "passed",
      "summary": "退出 0"
    },
    {
      "command": "python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "architecture and public Schema checks passed"
    },
    {
      "command": "npm ci && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "前端 lint/typecheck/vitest/build 均通过，vitest 3 passed"
    },
    {
      "command": "PYTHONPATH=. VALIDATOR_TMP=/tmp/.../semantic python /tmp/trainlab-b2-validator-semantic.py",
      "result": "passed",
      "summary": "get_running_records 正常、错误、边界、安全和合同语义场景通过"
    },
    {
      "command": "git diff --cached --name-only | wc -l",
      "result": "passed",
      "summary": "0 个 staged 文件"
    }
  ],
  "validationOutput": [
    "结论：通过（固定 59 文件快照范围）",
    "pytest 163 passed；ruff/compileall/architecture/semantic/frontend checks passed",
    "未发现 B2 阻塞问题；朴素 mypy . 存在项目布局入口限制"
  ],
  "residualRisks": [
    "未访问真实 Garmin/AI/网络/真实 states，符合任务边界但不证明外部集成",
    "developer_sources 非空返回未用真实复杂 FIT 样本动态验证，主要基于源码闭包逻辑和现有 Schema/测试审查",
    "朴素 mypy . 不是当前可用全仓入口，需要项目后续明确 mypy 门禁命令或排除规则"
  ],
  "noStagedFiles": true,
  "diffSummary": "仅写入本验证报告；未修改受审 source、PLAN、exec-plans、MEMORY 或 Git 索引",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "证据目录：/tmp/trainlab-b2-validator-clean-yPzyHR/logs；临时语义测试脚本：/tmp/trainlab-b2-validator-semantic.py"
}
```