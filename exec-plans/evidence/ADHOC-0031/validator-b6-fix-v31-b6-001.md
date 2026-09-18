# ADHOC-0031 B6 修复复验报告：V31-B6-001

## 结论

通过。受审快照冻结核对通过；V31-B6-001 的 query/path/body 校验错误已统一返回项目 envelope；B6 相关 API/UI 回归、环境门禁、前端门禁均通过。本次未进行真实 AI/Garmin/网络/登录/MFA/私人数据访问，未推进 B7。

## 受审版本与快照核对

- 分支：`work/adhoc-0031-local-web-system`，匹配。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`，匹配。
- 快照：`exec-plans/evidence/ADHOC-0031/b6-fix-v31-b6-001-review-snapshot.json`。
- 75/75 个文件 path/size/mode/sha256 全部匹配。
- 聚合 SHA：`3e6e5c77f94cd17cbb72fa5615831e112f8d8247d6c977aea1999a3ae6310b55`，匹配。
- `git diff --check` 通过；`git diff --cached --name-only` 为空。
- 证据：`/tmp/trainlab-v31-b6-001-validator/logs/freeze-and-git.log`。

## 场景表

| 要求 | 类型 | 步骤/输入 | 预期 | 实际结果 | 结论/证据 |
| --- | --- | --- | --- | --- | --- |
| 冻结检查 | 边界 | 核对分支、HEAD、75 文件、聚合 SHA、暂存区 | 全匹配、无暂存 | 全匹配，暂存为空 | 通过；`freeze-and-git.log` |
| 环境门禁 | 正常 | `/tmp` 固定副本中 `uv sync --locked --extra dev --no-editable --reinstall-package trainlab-source`；pytest；ruff；mypy；compileall；架构门 | 全部退出 0 | pytest `196 passed, 2 warnings`；其余通过 | 通过；`uv-sync.log`、`pytest-rerun-with-public-references.log`、`ruff.log`、`mypy.log`、`compileall.log`、`architecture.log` |
| Git 门禁 | 正常 | 原工作区 `git diff --check`、`git diff --cached --name-only` | 无空白错误、无暂存 | 通过，暂存为空 | 通过；`freeze-and-git.log` |
| V31-B6-001 query/path | 错误 | `GET /api/activities?limit=abc`；`GET /api/reports/weekly/not-int` | HTTP 400，`ok=false,data=null,error.code=INVALID_ARGUMENT`，无顶层 `detail` | 均符合；`details={}`，未泄漏 FastAPI detail | 通过；`probe-b6-fix.json` |
| body 校验 | 错误 | `POST /api/reports/weekly/generate`，JSON body 为数组 | 同一 envelope；不泄漏原始校验结构/请求体 | HTTP 400、`INVALID_ARGUMENT`、无 `detail`/`loc`/请求体回显 | 通过；`probe-b6-fix.json` |
| API/SPA 路由 | 错误/正常 | `GET /api/not-present`；`GET /not-a-real-spa-route` | API 404 JSON envelope；非 API SPA fallback | API 返回 404 `ACTIVITY_NOT_FOUND`；SPA 返回 200 HTML | 通过；`probe-b6-fix.json` |
| health/status 隐私 | 正常/边界 | 临时实例放置无效 `states/ai.json` 和 Garmin 文件后访问 `/api/health`、`/api/status`、`/api/sync/status` | 不读取/泄漏私密配置，不启动后台任务 | 三接口 200 envelope；响应不含私密文件内容/API key | 通过；`probe-b6-fix.json` |
| 活动列表/搜索/详情 | 正常/边界 | 合成 3 条活动，测分页排序、`sport`、`has_report`、详情、非法/不存在 id | 排序过滤正确；错误 envelope；不暴露原始私密数据 | 均符合 | 通过；`probe-b6-fix.json`、pytest |
| 报告读取/生成 | 正常/错误 | 活动报告读取；默认生成；fake AI 生成 | 默认禁用；fake-only 可生成并保存 | 默认 `CONFIG_UNAVAILABLE`；fake 成功且请求计数 1 | 通过；`probe-b6-fix.json` |
| 周报策略 | 正常/错误 | 缺活动报告周报；空周生成 | 缺报告 `POLICY_UNCONFIGURED`；空周固定文本 | 返回项目 envelope；空周为`本周无任何运动记录` | 通过；`probe-b6-fix.json`、pytest |
| 静态隐私 | 边界 | grep 生产 bundle；请求 `/states/ai.json` | 不包含秘密/绝对私密路径；不暴露 states 内容 | grep 0 行；请求返回 SPA 内容且不含私密文件文本 | 通过；`static-privacy-grep.log`、`probe-b6-fix.json` |
| 前端门禁/UI escaping | 正常/边界 | 验证前端快照与 B6 首验快照一致；`npm ci --offline`、lint、typecheck、test、build | 前端未变；检查通过；恶意文本按文本渲染 | 15 个前端/构建文件未变；lint/type/test/build 退出 0，Vitest 5 passed | 通过；`frontend-unchanged-vs-b6.log`、`npm-*.log` |
| 范围边界 | 边界 | 检索 B6 相关入口 | 不新增 D31-03A/B 自动批次/补跑/周触发；不新增 D31-02A 真实 records 配额；不做真实外部调用 | 未发现 B6 Web 入口触发这些行为；仅保留待决常量/同步适配类 | 通过；`boundary-grep.log` |

说明：第一次在“仅复制 75 个快照文件”的副本中跑 pytest 时，因公共资料 `references/README.md` 不在该快照清单内导致 10 个上下文/报告测试找不到文件；随后只补入公开 `references/` 支撑材料后复跑，pytest 全量通过。产品文件仍按 75 文件快照核验。

## 问题表

| 编号 | 对应要求 | 结果 |
| --- | --- | --- |
| V31-B6-001 | `/api` FastAPI 参数/path/body 校验错误必须返回统一 envelope 和项目状态映射 | 已复验通过；未发现新问题 |

## 命令与证据路径

主要证据目录：`/tmp/trainlab-v31-b6-001-validator/logs/`

- `UV_PROJECT_ENVIRONMENT=/tmp/trainlab-v31-b6-001-validator/venv uv sync --project . --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source` → 0。
- `python -m pytest tests -q -p no:cacheprovider` → 0，`196 passed, 2 warnings`。
- `python -m ruff check --no-cache .` → 0。
- `python -m mypy -p trainlab -p tests --no-incremental` → 0。
- `python -m compileall -q skills schemas tests` → 0。
- `python -m trainlab.check_architecture` → 0。
- `npm ci --offline`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build` → 均 0。
- 自定义 API/隐私探针：`/tmp/trainlab-v31-b6-001-validator/probe_b6_fix.py` → 0，输出 `probe-b6-fix.json`。

## 未验证事项 / 限制

- 未读取真实 `states/ai.json`、真实凭据、私人活动数据或秘密。
- 未调用真实 AI Provider、Garmin、网络、登录/MFA。
- 未使用真实浏览器手工验收；UI escaping 由前端 Vitest/构建和生产 bundle 检查覆盖。
- 未推进 B7，未提交、未推送、未创建 PR。
