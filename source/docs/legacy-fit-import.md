# 一次性复制旧 FIT

这是 M12 迁移工具，不是日常同步入口，也不证明 Garmin 的历史活动已全部采齐。
它只读取已验证备份中旧数据库登记的 2022-01-01 起运动 FIT，将独立副本写入新 SQLite。
不导入健康数据、GPX/TCX、旧 AI 报告、邮件、课程动作或凭据；未登记的 FIT 不自动采用。

从 `source/` 运行，使用明确绝对实例路径与显式归档：

```bash
python -m skills._shared.fit_weekly --instance /absolute/private-fit-instance \
  import-history --archive /absolute/explicit-legacy-archive
```

Python 环境沿用 `requirements.txt`；目标父目录需要预先存在，不能指向备份内部。
本阶段真实验收只在仓库外实例进行，以上命令不意味着已经切换正式库。

执行顺序：

1. 核验完整备份清单、文件 SHA、权限和恢复数据库。
2. 从数据库白名单选择 FIT；分别核对活动身份、日期、登记状态、文件大小、SHA 和 CRC。
3. 前检失败不创建目标实例；通过后以 0700/0600 独立保存文件，索引事务一次提交。
4. 对比备份前后完整指纹，核验新实例文件与数据库闭包，保存可重放的导入回执。

同一文件和身份再次运行不新增文件或数据库记录。有限中断会保留证据；已改名但未登记的
相同文件可在精确重放时补齐持久化检查并登记。损坏或冲突不能靠重放忽略。
若目录含未完成 `.pending-*` 文件，闭包检查会停止，不自动删除失败产物。

新实例保存自己的 FIT 字节和相对路径；回执不含备份的绝对位置。迁移完成后，备份可以离线，
新系统仍可核验和使用文件。只有显式import-history延迟加载legacy_import/history_archive；读取器只有核验和immutable数据库读取，没有create/restore/main。普通运行不导入它。

导入回执 `history_coverage=not_established`：这是“复制了已有文件”，不是“自 2022 年起每天
都已完整查询”。日历覆盖、明确无活动和缺口仍需后续同步表及完整分页来证明。
