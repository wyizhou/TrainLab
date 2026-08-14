# 执行计划：用合成 FIT 夹具替代私人 test_data

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M3-0001`
- 阶段/子项目：`M3/test-fixtures`
- Batch ID：`serial`
- 返工来源：`无`
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 新增完全由代码定义、无个人信息、可重复生成的合成 Garmin FIT 测试夹具。
- 7 个当前直接读取私人 `test_data/` 的 Garmin 测试模块全部切换到合成夹具。
- 合成夹具覆盖测试所需的跑步、骑行、徒步、力量和攀岩等适用边界，不通过弱化断言取得绿灯。
- `test_data/` 的私人文件不被读取、解析、展示、复制或提交；依赖归零后从项目根删除。
- 更新 `.gitignore`、README、runbook、打包隐私测试和相关文档，不再把 `test_data/` 作为必需项目目录。
- Garmin 聚焦测试、完整 pytest、repository quality、Ruff、format-check、mypy 和 schema/隐私门通过。
- 全新独立只读 Validator `PASS`。

## 范围与非目标

- 允许写入：`tests/fixtures/`、测试支持代码、7 个直接依赖模块及受影响测试、`.gitignore`、README、相关 runbook/规则替代条目、计划和 memory；最后删除根 `test_data/`。
- 禁止写入：私人 FIT/表格内容、生产 state/config/logs、产品业务语义、Garmin Provider、分析、邮件、运行服务、全局 Skill、远端 Git。
- 不读取现有 `test_data/` 文件字节；只允许删除前后的路径存在性和文件数量元数据。

## 适用规则与参考资料

- 已批准规则：A-001、A-002 未被替代条款、A-003；本任务按用户当前批准追加 A-004，替代 A-003 中把 `test_data/` 作为长期本地运行目录的表述。
- 上游布局：agentForge v0.4.2 根 `tests/<feature-slug>/`；既有测试不机械重排。

## 依赖与隔离

- 显式依赖：M2 完成；ADHOC-0004 已确认 7 个直接依赖模块。
- 共享接口和冻结依据：FIT 二进制协议、现有解析器/领域输出合同和测试断言。
- 任务分支、Worktree、集成分支：不适用——用户未授权 Git 分支操作，且任务严格串行。
- 允许/禁止写入范围：见上。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 合成 FIT 构建 | `garmin-fit-fixtures` | `tests/fixtures/`、相关 Garmin 既有测试 | 可重复、CRC 有效、无私人值、覆盖所需活动类型 |
| 私人依赖归零 | `garmin-fit-fixtures` | 7 个既有 Garmin 测试模块 | 不再读取 `test_data/`，保持正常/错误/边界断言 |
| 隐私与可移植性 | `root-layout`、`product-packaging` | 现有根布局和打包测试 | test_data 不存在、构建拒绝私人路径合同保持安全 |

## 工具采用情况

- 可执行技术栈：Python 3.12、pytest、fitdecode、Ruff、mypy、JSON Schema。
- Linter：受影响 Python 文件 Ruff check/format-check；既有维护 mypy 目标。
- 测试：先运行 7 个依赖模块与夹具合同，再全部 Garmin 测试，最后唯一完整 pytest。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 独立 Validator / `M3-0001-validator` | FIT 协议、测试真实性和隐私删除 | `high` | `high` | 高风险跨测试夹具迁移，需确认无隐私与无测试弱化 | 支持 | 只读 | 全部验收项报告 | `FAIL`：发现历史值复用和 4 类断言缺口 |
| 2 | 独立 Validator / `M3-0001-validator-r01` | 返修后的隐私来源与测试强度 | `high` | `high` | 必须由未参与实施的新 Agent 复核阻塞项 | 支持 | 只读 | 全部验收项报告 | `FAIL`：lap 与 course-point timestamp 断言不明确 |
| 3 | 独立 Validator / `M3-0001-validator-r02` | lap 与 course-point 时间合同返修 | `high` | `high` | 第二次 Validator 发现精确断言缺口，需再次独立复核 | 支持 | 只读 | 全部验收项报告 | `PASS` |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 审计 7 个模块所需 FIT 字段与断言 | `done` | 不读取私人文件，仅检查代码合同 |
| 先建立合成夹具行为合同与生成器 | `done` | 六类确定性、CRC 有效的合成 FIT |
| 替换 7 个模块的私人路径依赖 | `done` | 聚焦测试通过；私人 manifest 已删除 |
| 运行聚焦/Garmin/完整质量门 | `done` | 聚焦、全部 Garmin、完整 pytest exit 0；静态门通过 |
| 删除 test_data 并更新治理/文档 | `done` | 12 个文件原样移至废纸篓备份；项目路径不存在 |
| 独立 Validator 复核 | `done` | 第三位全新 Validator PASS；180 项独立聚焦测试通过 |
| 归档计划、完成 Roadmap、清除 memory 指针 | `done` | Roadmap 与 memory 已同步 |

## 当前检查点

- 当前 Loop：完成归档。
- 最近完成：第三位全新只读 Validator PASS，全部验收项满足。
- 当前焦点：无。
- 下一动作：等待用户决定是否提交。
- 阻塞项：无。
- 已变更文件：合成夹具、7 个直接依赖模块、相关治理/文档/构建与冻结哈希合同。
- 待验证项：无。

## 决策与发现

- 私人样本不迁入可跟踪 tests；只迁移测试能力，由合成夹具替代。
- 现有 `tests/fixtures/` 已是可提交合成资料的正确位置；新夹具沿用该职责。
- 测试预期只在从真实私人样本切换到明确合成输入所必需时调整，并必须保留相同业务边界和回归强度。
- 合成夹具覆盖 running、cycling、hiking、strength、bouldering、indoor climbing，包含
  record/lap/session、developer field、device、unknown message 及运动专项消息。
- 私人目录未被读取或解析；仅统计 12 个路径项后将整个目录原样移入废纸篓备份。
- 首次 Validator 指出第一版合成值仍复用了历史断言，且缺少四类专项覆盖；同一计划内
  已改为全新中性日期、距离、时长、热量、坐标和运动专项值，并恢复全部四类断言。
- 第二次 Validator 指出 lap 与 course-point timestamp 仅生成未明确绑定断言；现已在
  夹具合同和数据库投影测试中分别增加精确计数、字段定义号和值/投影时间一致性检查。

## 任务级独立验证

- 中性交接：只提供目标、验收、规则和最终仓库结果。
- Validator 身份/上下文：前两位 Validator 分别发现并推动修复真实缺口；第三位全新只读 Validator 完成终验。
- 模型/推理档位：`high/high`。
- 命令与观察：180 项独立聚焦测试；repository quality；Ruff/format-check；维护 mypy；diff/reference/privacy 检查均通过。
- 结果：`PASS`
- 未满足项与剩余风险：无阻塞；废纸篓备份仍可恢复，清空前继续占用空间。

## 集成级独立验证

- 集成范围：不适用——单一串行任务。
- 结果：`不适用——无并行集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | 用户批准；Roadmap 与计划建立 | 私人样本有 7 个直接依赖模块 | 只读提取合成 FIT 合同 |
| 2026-08-12 / Loop 2 | 实现迁移；聚焦、Garmin、完整测试及静态门通过 | 私人样本不再是测试前置条件 | 独立只读验证 |
| 2026-08-12 / Loop 3 | 首次 Validator FAIL 后返修并重跑 Garmin、完整测试与静态门 | 更换全部历史特征值并恢复四类专项断言 | 新 Validator 复核 |
| 2026-08-12 / Loop 4 | 第二次 Validator FAIL 后补齐 lap 与 course-point 时间绑定断言 | 精确聚焦与全部静态门通过 | 第三位新 Validator 复核 |
| 2026-08-12 / Loop 5 | 第三位 Validator PASS；180 项独立聚焦和全部门禁通过 | 无剩余阻塞 | 归档完成 |
