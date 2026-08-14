# Layer 1：Foundation v4

Foundation v4 是 TrainLab 的本地、只读优先事实库。它保存从 Garmin raw/FIT
离线重建的活动、健康、睡眠、生理、覆盖和质量事实，并通过固定 schema、外键、
来源 revision 与哈希验证保护数据边界。

## 当前边界

- 数据库、raw、锁和 ready marker 位于 `TRAINLAB_INSTANCE_ROOT` 下的私有 `state/`。
- 配置与数据分离；配置必须由实例根显式提供，默认入口只把 `source/` 作为开发实例根。
- Foundation v4 不创建历史调度、Supervisor 或后台编排表；旧库只保存在
  `data-backup/`，不参与新运行时写入。
- Provider 数据只能经 Garmin 收集边界写入；分析、邮件和模型不能直接读 raw 或凭据。

## 可验证入口

```bash
python3.12 source/index.py foundation status
python3.12 source/index.py foundation verify
```

验证失败时保持 fail-closed，不自动修复、补数或删除旧数据。任何在线 Provider
补数都需要单独的日期、资源和预算授权。

## 迁移原则

旧 Foundation 状态先以原字节、权限和元数据归档到 `data-backup/<timestamp>/`，
再在独立 candidate 目录构建 v4。只有完整性、来源闭包、外键、只读查询和权限门
全部通过，才允许把 candidate 原子切换为 `source/state/`。
