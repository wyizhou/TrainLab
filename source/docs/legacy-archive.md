# M12 旧实例归档

这是开发迁移工具，不是正常同步或 AI 的运行依赖。从 `source/` 执行：

```sh
python skills/_shared/scripts/archive_legacy.py create
python skills/_shared/scripts/archive_legacy.py verify --archive ../data-backup/m12-legacy-时间
python skills/_shared/scripts/archive_legacy.py restore --archive ../data-backup/m12-legacy-时间 --destination ../data-backup/独立恢复副本
```

- 创建时只复制 Git 登记的非私人源码，以及锁内冻结的旧 `state`；目标、邮箱、Token、凭据和私人配置不复制，仍留在原位置。
- `legacy-source` 保存旧源码原字节；`legacy-state` 保存原始数据库、sidecar、lock 和 raw 原字节；`recovery/trainlab.db` 是 SQLite Online Backup 得到的自包含恢复数据库。
- 源锁必须已经存在且可只读取得；WAL 必须为空。工具不创建源锁、不 checkpoint、不删除正式 sidecar。锁或 WAL 条件不满足时停止。
- 每项源文件的 SHA 和原元数据保存在私有 `manifest.json`；归档和恢复副本目录为 0700、文件为 0600。恢复旧可执行位时使用清单中的源 mode，不能将归档权限宽泛放开。
- 完整性、外键、逻辑数据摘要、逐文件 SHA 和独立复制恢复演练通过后，才将 pending 目录原子改名为成功归档。成功演练的临时副本会清理；失败 pending 保留，不自动删除或覆盖。
- `restore` 只创建一个不存在的独立恢复副本，不覆盖当前 source，不修改远端邮件/课程，不自动启动旧程序。验证成功不等于正式切换已经执行。
- 旧失败记录继续由 Git 和既有私有产物保留；本工具不复制其他任务的临时 Candidate，不把旧报告导入新库。

确定性回归入口：`pytest tests/code/contract/test_m12_legacy_archive.py`。测试只创建合成源码/SQLite/FIT 字节，不读取正式资料或调用 Provider。
