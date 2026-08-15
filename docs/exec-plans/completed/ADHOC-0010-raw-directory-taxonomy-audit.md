# 执行计划：raw 目录分层与用途审计

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0010`
- 阶段/子项目：`不适用`
- Batch ID：`read-only-raw-audit`
- 返工来源：`无`
- 开始日期：2026-08-15
- 最后更新：2026-08-15

## 目标与验收标准

只读解释 `source/state/raw/` 每一层目录和每类直接子目录保存的内容、文件格式、数量、
大小、写入流程、对应数据库登记和下游读取用途。不得读取或展示健康/活动正文；不得调用
Garmin/Gmail、修改正式数据或继续 M6 实现。

## 范围与非目标

- 范围：raw 目录元数据、路径命名规律、扩展名、文件计数/字节、`raw_objects` 和
  `source_revisions` 的目录映射、源码中的写入者与解析者。
- 非目标：打开或解析 raw/FIT 内容、评价具体健康指标、修改目录、补数、去重、删除或迁移。

## 适用规则与参考资料

- A-001、A-004、A-007。
- `source/src/resources/harness/shared/HARNESS.md`。
- 数据质量审计仅使用元数据与确定性登记关系。

## 依赖与隔离

- 依赖：已归档 ADHOC-0009 的来源闭包结论。
- 允许写入：本计划与 `memory.md` 活动指针。
- 禁止写入：`source/` 产品代码/测试、`source/state`、raw/FIT、config/logs、
  `data-backup`、凭据、数据库和外部服务。

## Subagent 派发

| Attempt | Agent 角色/任务 | 风险与复杂度 | 模型档位 | 推理档位 | 写入边界 | 产物 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Worker / 文件系统目录分类 | 私有目录元数据 | `high` | `high` | 只读 | 各层目录、文件数、格式、大小 | `done` |
| 1 | Worker / 源码写入与读取映射 | 跨模块来源解释 | `high` | `high` | 只读 | 目录→writer→parser→投影 | `done` |
| 1 | Worker / SQLite 路径与资源映射 | 数据血缘与去重语义 | `high` | `high` | 只读 | 目录→raw_objects/revisions 统计 | `done` |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 恢复仓库与隐私边界 | `done` | Git、rules/memory/PLANS、shared Harness 已读取 |
| 盘点 raw 目录层级和命名规律 | `done` | 来源/角色 → 格式 → 写入年月 → SHA 文件名 |
| 映射源码写入者、解析者和用途 | `done` | Garmin/Mail/Foundation/rebuild/repair 映射完成 |
| 映射数据库资源类别与内容去重 | `done` | 27,388 raw、44,467 revision；目录分桶完成 |
| 汇总为普通用户可理解的目录说明 | `done` | 三路审计交叉一致 |

## 当前检查点

- 当前 Loop：raw 目录分层和用途已经解释完成。
- 当前焦点：等待用户决定是否清理 Finder 杂项或调整目录合同。
- 阻塞项：无。
- 下一动作：仅按用户明确选择执行后续变更。

## 决策与发现

- `raw/` 按“来源/历史角色 → 文件格式 → 写入 UTC 年月 → SHA-256 文件名”组织，
  不按睡眠、心率、活动等业务指标分目录。
- `garmin/json`：26,832 个规范化 Provider JSON、84,132,306 字节、52 个首次登记 kind、
  43,882 个 revision；包含活动、健康、睡眠、体征、设备和用户设置等语义。
- `garmin/fit`：510 个完整 FIT、71,257,974 字节、583 个 revision；目录无法区分
  `activity_fit` 与 `activity_fit_candidate`，权威语义在 revision。
- `garmin/gpx` 与 `garmin/tcx` 各 1 个，当前只归档并登记 revision，没有结构化 parser。
- `backup/`：两个来源标签目录共 44 个旧备份独有 JSON、无 revision；仅保存证据，不进入
  当前投影链。标签来自备份 DB 路径摘要，不是数据日期或内容分片。
- `gmail/json`、`gmail/attachments`、`legacy/health_xlsx`、`legacy/fit` 当前均为空；它们由
  Foundation 合同预建。Gmail JSON 有可用 writer，附件正文与 legacy 目录当前无实现。
- `YYYY/MM` 是文件写入 raw 时的 UTC 年月，不是健康测量或活动发生日期。
- `raw_objects.sha256` 全局唯一；相同字节只存一次。`raw_objects.resource_kind` 是首次登记
  标签，`source_revisions.resource_kind` 才是每次语义使用的权威来源。
- 27,388 个登记 raw 文件均 0600；25 个目录均 0700；无符号链接或硬链接。
- 另有 8 个 2026-08-15 由 Finder 生成的 `.DS_Store`，合计 71,712 字节、0644、未登记。
  它们不是健康数据，但会让 `FoundationTool.raw_tree_fingerprints()` 以
  `rebuild_raw_tree_unsafe` 拒绝 shadow rebuild/copy。未作删除。

## 独立验证

- 本任务本身为三路只读审计，不修改产品；由主协调 Agent 交叉核对结果。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 回写不适用
- [x] `memory.md` 活动指针已清除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-15 / start | 建立只读目录分类审计 | raw 是目录；需解释每层和每类内容 | 并行检查文件系统、源码和 SQLite 映射 |
| 2026-08-15 / complete | 三路审计完成；目录、代码 writer/reader 与 DB 映射一致 | 目录按来源/格式/写入月组织；8 个 `.DS_Store` 会阻断严格 raw 树校验 | 归档计划，等待用户决定 |
