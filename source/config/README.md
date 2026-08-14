# TrainLab 实例配置

此目录是 `source/` 的实例根配置位置。真实配置文件、数据库、raw、FIT、token 和
凭据全部被 Git 忽略，并且必须由当前用户以 owner-only 权限创建。

可跟踪的内容只有本说明和 `examples/` 中不含秘密的结构示例。示例不会被自动复制到
实例，也不会覆盖已有配置。运行入口默认将 `source/` 作为实例根；跨电脑运行时可用
`TRAINLAB_INSTANCE_ROOT` 指向另一个已完成权限检查的私有目录。

本迁移不自动执行 Garmin、分析、邮件或 Supervisor。配置变更须先通过对应 schema 和
只读检查。
