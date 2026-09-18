# ADHOC-0031 B6 / 0031-T6 独立验证报告

## 结论

失败。固定快照核对通过，环境门禁、现有后端/前端测试和多数 API/UI 场景通过；但 `/api` 上由 FastAPI 参数解析触发的 422 错误仍返回默认 `{"detail": ...}`，不是项目统一 JSON envelope，违反“API errors use common envelope and status mapping”。

## 受审版本与冻结核对

- 分支：`work/adhoc-0031-local-web-system`，匹配。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`，匹配。
- 快照：`exec-plans/evidence/ADHOC-0031/b6-developer-review-snapshot.json`。
- 75/75 个快照文件路径、size、mode、sha256 全部匹配。
- 按 `json.dumps(items, sort_keys=True, separators=(',', ':'))` 计算聚合 SHA：`9517163e2fbb318765cae4537b76f2969c99c08d7c61b489007184bb8e330196`，与快照一致。
- 暂存区：`git diff --cached --name-only` 为空。
- 工作区存在计划/证据/source 未提交变更，符合任务说明；验证以快照产品文件为准。

## 场景表

| 要求 | 类型 | 步骤/输入 | 预期 | 实际 | 结论/证据 |
| --- | --- | --- | --- | --- | --- |
| 冻结检查 | 边界 | 核对 branch/HEAD/75 文件 size/mode/sha256/aggregate | 全匹配，否则停止 | 全匹配 | 通过；`/tmp/trainlab-b6-validator/logs/snapshot-verify.log` |
| 环境门禁 | 正常 | `/tmp` 副本中 `uv sync --locked --extra dev --no-editable`、pytest、ruff、mypy、compileall、架构门 | 全部退出 0 | pytest `195 passed, 2 warnings`；其余通过 | 通过；`/tmp/trainlab-b6-validator/logs/*.log` |
| Git 门禁 | 正常 | 原工作区 `git diff --check`、`git diff --cached --name-only` | 无空白错误、无暂存 | 退出 0；暂存为空 | 通过 |
| 前端门禁 | 正常 | `/tmp` 副本中 `npm ci --offline`、lint、typecheck、test、build | 全部通过，构建到 local-web web | 全部退出 0；build 输出 `skills/local-web/web/index.html` 和 assets | 通过；`npm-*.log`、`build-output-check.log` |
| API 路由分离 | 正常/错误 | `GET /api/nope`、`GET /ui/deep/link` | API 未知为 envelope JSON；非 API 未知为 SPA index | `/api/nope` 404 envelope；非 API 200 HTML index | 通过；`probe.json` |
| API 错误 envelope | 错误 | `GET /api/activities?limit=0` | 统一 envelope | 返回 `INVALID_ARGUMENT` envelope | 通过；`probe.json` |
| API 错误 envelope | 错误 | `GET /api/activities?limit=abc`、`GET /api/reports/weekly/not-int` | 统一 envelope 和项目状态映射 | 返回 FastAPI 默认 `{"detail": [...]}`，缺少 `ok/data/error` | 失败；见 V31-B6-001 |
| 状态/隐私 | 正常/边界 | 在隔离 root 放置无效 `states/ai.json`、无效 Garmin 凭据后访问 health/status/sync status | 不读 AI/Garmin 私密配置、不启动任务、只暴露本地服务/路由/相对 DB 信息 | 三个接口 200 envelope；未因无效私密文件报错 | 通过；`probe.json` |
| 活动列表/搜索 | 正常/边界 | 合成 DB 三条活动，测默认排序、`q`、`sport`、`has_report`、分页 | 固定排序、过滤正确、无 raw FIT bytes | 返回按 start_time 倒序；过滤正确；只返回 summary/basic JSON 和相对 fit_path | 通过；`probe.json`、`test_b6_api.py` |
| 活动错误 | 错误 | 无 DB、非法 activity id、不存在 id | envelope；DB unavailable/invalid/not found 正确 | 分别返回 `DATABASE_UNAVAILABLE`、`INVALID_ARGUMENT`、`ACTIVITY_NOT_FOUND` envelope | 通过；`probe.json` |
| 报告读取/生成 | 正常/错误 | 读活动报告；默认生成；注入 fake AI 后生成 | 默认禁用；fake 调 B5 服务并只在成功保存 | 默认 `CONFIG_UNAVAILABLE`；fake 成功保存；请求计数 1 | 通过；`probe.json`、pytest |
| 周报策略 | 正常/错误 | pytest 覆盖缺活动报告与空周 | 缺报告保持 `POLICY_UNCONFIGURED`；空周固定文本 | 现有测试通过 | 通过；`pytest.log` |
| 前端 UI | 正常/边界 | Vitest SSR 渲染 loading、empty、error、状态、活动/周报、恶意报告文本 | 状态完整，报告按文本转义 | 5 个前端测试通过，恶意 HTML 被转义 | 通过；`npm-test.log` |
| 静态隐私 | 边界 | grep 生产 bundle；请求 `/states/ai.json` | bundle 无秘密/绝对路径；不暴露 states 内容 | grep 无匹配；请求返回 SPA index，不是私密文件内容 | 通过；`build-output-check.log`、`probe.json` |
| 范围边界 | 边界 | 检查接口/行为 | 不实现 B7、真实 AI/Garmin、自动批次/补跑/周触发/旧 records 配额 | 未发现相关实现或声明 | 通过；代码检查/探针 |

## 问题表

| 编号 | 对应要求 | 可复现步骤 | 预期 | 实际 | 影响 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| V31-B6-001 | API errors use common envelope and status mapping | 在受审快照运行 app，访问 `GET /api/activities?limit=abc` 或 `GET /api/reports/weekly/not-int` | `/api` 错误均返回统一 envelope：`ok=false,data=null,error={code,message,details}`，并使用项目错误码/状态映射 | 两个请求均返回 HTTP 422，body 只有 FastAPI 默认 `detail` 列表，缺少 `ok/data/error` | 前端/调用方不能按统一 API 合同处理所有 `/api` 错误；违反 B6 API 错误边界 | `/tmp/trainlab-b6-validator/logs/probe.json`；相关实现未注册 `RequestValidationError` 处理器，见 `source/skills/local-web/scripts/server.py` |

## 命令与证据

主要命令均在 `/tmp/trainlab-b6-validator/source` 隔离副本执行，未写受审 source：

- `UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b6-validator/venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` → 0，`uv-sync.log`
- `/tmp/trainlab-b6-validator/venv/bin/python -m pytest tests -q -p no:cacheprovider` → 0，`195 passed, 2 warnings`，`pytest.log`
- `python -m ruff check --no-cache .` → 0，`ruff.log`
- `python -m mypy -p trainlab -p tests --no-incremental` → 0，`mypy.log`
- `python -m compileall -q skills schemas tests` → 0，`compileall.log`
- `python -m trainlab.check_architecture` → 0，`architecture.log`
- `npm ci --offline` → 0，`npm-ci.log`（有 fsevents allow-scripts 提示但未阻塞）
- `npm run lint`、`npm run typecheck`、`npm test`、`npm run build` → 0，`npm-*.log`
- 原工作区 `git diff --check` → 0；`git diff --cached --name-only` → 空。
- 自定义 API/隐私探针：`/tmp/trainlab-b6-validator/probe_b6.py` → 0；输出 `probe.json`。

## 未验证事项 / 限制

- 按任务边界未进行真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json`、真实凭据或真实活动数据访问。
- 未推进 B7，未做完整真实外部端到端。
- 未使用真实浏览器手工打开页面；前端 UI 通过 Vitest/React SSR 和生产构建验证。
