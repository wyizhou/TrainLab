# ADR 0004：FIT 段语义投影与原子重解析

- 状态：Accepted
- 日期：2026-07-18
- 关联：`docs/plans/fit-detail-corrections.md`

## 背景

FIT 原生消息允许同一活动同时包含 set、split、split_summary、设备扩展和当前 SDK 未命名的 profile 字段。直接让前端解释原始字典会造成力量训练组重复、动作标题关联错误、攀岩摘要被当作实例，以及把未知数字误写成等级。已有 complete/partial 导入还需要在解析器修复后安全更新投影，但普通 retry 采用删除重建 Activity 的语义，不能保持用户标题和资源身份。

## 决策

1. 数据库继续原样保存可重放的原始扩展字段；后端在详情 segment 上另外提供版本化 `semantic` 投影。当前 `schemaVersion=1`，来源只允许 `set`、`split`、`split_summary`。
2. 力量业务实例只来自 set；动作标题使用 `set.wkt_step_index → workout_step.message_index → exercise identity → exercise_title.wkt_step_name`。split/split_summary 只保留审计，不参与动作、组数或时间构成。
3. 攀岩业务实例只来自 split；split_summary 不计实例。未知字段只有在字段身份、换算和样本交叉验证均有可靠证据后才能进入 grade；否则返回 `unavailable/unknown_profile_field` 并保留原始值。
4. 已完成导入的维护只提供本机管理员 CLI `reparse-fit`，不增加普通用户 HTTP 端点。整批先做零写入读取、SHA 与解析，再按统一 `User → ActivityImport → Activity` 锁序取得行锁，在单一事务中就地替换子投影。
5. 重解析必须保留 Activity/Import UUID、user_id、source_import_id、title_override、原文件和 storage key。任一所有权、状态、SHA、并发快照或持久化检查失败时整批回滚。

## 结果

- 前端只消费可证明的稳定语义，同时仍能在原始数据页审计未知字段。
- 解析器修复不会改变活动链接、用户标题或跨用户边界。
- 新 FIT profile 字段不会因为“看起来像等级”而进入业务 UI；解除不可用状态需要新的可信格式证据。
- 管理重解析需要停写窗口和数据库 + 私有 FIT 卷同一时间点备份；数据回滚使用双卷恢复，不使用 Alembic downgrade。
