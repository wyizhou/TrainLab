# Foundation v4 只读验收

候选实例必须先通过 `foundation status` 和显式 `foundation verify`，再由独立 Validator
检查 SQLite integrity、外键、manifest、raw lineage、权限和 owner-only 路径。

本阶段不启动同步、分析、邮件或常驻服务。旧数据库和运行历史只存放在
`data-backup/<timestamp>/`，新库不包含旧 AI 报告、Mail、交付、用户事实或历史调度表。
