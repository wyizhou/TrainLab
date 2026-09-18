# ADHOC-0031 B7 本地完整独立验证报告

## 结论

**通过（本地/合成范围）**。

受审 B7 快照、Python/前端门禁、端到端合成业务流、Garmin 合成同步、AI/Context 安全、Web/API/静态、重启持久化和边界检查均通过。未发现新问题，问题表为空。

本结论不覆盖真实 AI、真实 Garmin、互联网/网络、登录/MFA、真实私人状态或真实浏览器人工 8080 验收。

## 快照与冻结核对

- 分支：`work/adhoc-0031-local-web-system`，匹配。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`，匹配。
- 快照：`exec-plans/evidence/ADHOC-0031/b7-local-validation-snapshot.json`。
- 79/79 个文件 `path/size/mode/sha256` 全部一致。
- 聚合 SHA：按 `json.dumps(items, sort_keys=True, separators=(',', ':'))` 计算为 `aaddd5a762aa7a79b287b92f61c6b3990bb0cc9cca1a696e71d83f7291f27751`，匹配。
- 暂存区：空。
- 原工作区 `git diff --check`：退出 0。
- 验证用固定副本：`/tmp/trainlab-b7-validate2-66869/repo`；依赖和生成物仅在 `/tmp` 副本/venv 中产生。

## 场景表

| 范围 | 类型 | 方法/输入 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| Python 安装/测试 | 门禁 | `/tmp` 副本，`uv sync --frozen --extra dev`，`pytest tests -q` | `196 passed, 2 warnings` | `/tmp/trainlab-b7-uv-sync2.log`、`/tmp/trainlab-b7-python-gates2.log` |
| Ruff/compile/架构 | 门禁 | `ruff check`、`compileall -q skills schemas tests`、`python -m trainlab.check_architecture .` | 均退出 0；架构门输出通过 | `/tmp/trainlab-b7-python-gates2.log` |
| Mypy | 门禁 | 构建 wheel 后在隔离 venv 运行 `python -m mypy -p trainlab --no-incremental` | `Success: no issues found in 31 source files` | `/tmp/trainlab-b7-build-wheel.log`、`/tmp/trainlab-b7-mypy-wheel.log` |
| Git 门禁 | 门禁 | 原工作区 `git diff --check`、`git diff --cached --name-only` | 退出 0；暂存为空 | `/tmp/trainlab-b7-git-diff-check.log`、`/tmp/trainlab-b7-staged.log` |
| 前端 | 门禁 | `npm ci --offline`、lint、typecheck、Vitest、生产 build | 全部退出 0；Vitest 5 passed；输出到 `source/skills/local-web/web` | `/tmp/trainlab-b7-npm-ci-offline.log`、`/tmp/trainlab-b7-frontend-gates.log` |
| FIT/SQLite/records | 端到端 | 合成 FIT 导入，初始化 DB；检查四业务表+config；running/cycling 样本；records 授权/越权/非 running | 12/4/3/3/3 列符合；running 返回完整记录；越权 `TOOL_NOT_ALLOWED`；非 running `SPORT_NOT_ALLOWED` | `/tmp/trainlab-b7-e2e-probe.log` |
| 报告存储 | 端到端 | 保存含 HTML/换行/Markdown 的活动和周报全文 | 活动/周报全文保真；不截断、不解释 SQL/HTML | `/tmp/trainlab-b7-e2e-probe.log` |
| AI/Context | 正常/错误/安全 | Fake AI 多轮 `read_reference` + `get_running_records`；未知工具、非法参数、未注册 reference；截断/容量错误 | 正常最终全文保存；错误显式失败；容量失败不插入/覆盖；`api_key` 不在消息可见输出中 | `/tmp/trainlab-b7-e2e-probe.log` |
| 周/日 Context | 边界 | 缺活动报告周报、空周、daily placeholder | 缺报为 `POLICY_UNCONFIGURED`；空周保存 `本周无任何运动记录`；daily 不读健康数据、不新增业务表 | `/tmp/trainlab-b7-e2e-probe.log` |
| Web/API | 端到端 | TestClient 调 `/api/health/status/sync/status/activities/detail/reports`、搜索、校验错误、API 404、SPA fallback | `/api` 均为 `ok/data/error` envelope；校验错误也是 envelope；API 404 与 SPA 404 分离；status 标识 local-only | `/tmp/trainlab-b7-e2e-probe.log` |
| 静态与隐私 | 安全 | 检查生产 bundle；请求 `/states/ai.json` | bundle 未发现 `api_key`/secret/Garmin token/private state 字样；未暴露私有文件内容 | `/tmp/trainlab-b7-static-scan` 命令输出、`/tmp/trainlab-b7-e2e-probe.log` |
| Garmin 合成同步 | 正常/错误/恢复 | Fake adapter 分页/重复/下载/import；刷新 auth；部分失败恢复 | 首次合成同步下载 2 条并按 UTC 日期+FIT SHA 命名；失败时保留上一轮 `last_success_at_utc`，成功项保留，失败项不标记 synced，覆盖 V31-B4-001 | `/tmp/trainlab-b7-e2e-probe.log` |
| 重启/持久化 | 重启边界 | 重建 app/TestClient，重开 DB | DB 报告/status 仍可读；未出现 history/conversation 持久表，内存历史不作为 DB 数据保存 | `/tmp/trainlab-b7-e2e-probe.log` |
| 边界 | 范围核对 | 全程只用 `/tmp` 合成实例和 Fake 客户端 | 未读取真实 `states/ai.json`、Garmin 凭据、私人活动；未联网；未发 PR/提交/推送；未发明 D31-03A/B 自动策略或 D31-02A 真实 records 配额 | 命令与探针设计 |

## 问题表

| 编号 | 对应要求 | 结果 |
| --- | --- | --- |
| 无 | 无新增问题 | B7 未发现需要编号为 `V31-B7-001` 的失败 |

## 命令与证据路径

- 快照核对脚本：分支/HEAD/79 文件/聚合 SHA/暂存区通过。
- `/tmp/trainlab-b7-uv-sync2.log`：隔离依赖安装。
- `/tmp/trainlab-b7-python-gates2.log`：pytest、ruff、compileall、架构门；其中 mypy 的一次源码副本调用因隔离安装布局不能定位包，未作为最终 mypy 证据。
- `/tmp/trainlab-b7-build-wheel.log`、`/tmp/trainlab-b7-mypy-wheel.log`：wheel 构建和最终 mypy 通过。
- `/tmp/trainlab-b7-npm-ci-offline.log`、`/tmp/trainlab-b7-frontend-gates.log`：前端离线安装、lint/type/test/build。
- `/tmp/trainlab-b7-e2e-probe.log`：完整合成端到端探针，退出 0，输出活动 ID、表计数、Garmin 下载与失败恢复证据。
- `/tmp/trainlab-b7-git-diff-check.log`、`/tmp/trainlab-b7-staged.log`：Git 空白和暂存检查。

## 未验证事项与残余风险

- 未做真实 AI 请求、真实 Garmin/pygarminconnect、网络、登录/MFA、真实私人活动或真实密钥读取；按任务边界属于未验证，不算失败。
- 未用真实浏览器手工访问 8080；本次使用 FastAPI TestClient、前端 Vitest 和生产 bundle 检查覆盖本地静态/API 行为，真实浏览器人工体验仍未验证。
- D31-03A/B 自动批次/补跑/周触发策略、D31-02A 真实 records 配额政策仍未配置；本次确认实现未擅自发明这些策略。
