# Garmin 数据采集工具运行手册

第二层仅通过 `trainlab garmin` 的一次性命令运行；它不含 daemon、timer 或轮询。
第五层传入稳定 invocation ID 并读取唯一 JSON receipt 和退出码。首次全量同步必须在
`config/garmin.yaml` 设置 `history_start_date`，或显式传入 `--health-from`。

部署前安装锁定依赖：`python -m pip install -r requirements.lock`。token 目录必须在
`state/secrets/garmin` 下，目录 0700、文件 0600；不得把密码、MFA、token、原始 JSON
或 FIT 写进日志、receipt 或工单。

离线验证使用 fake transport 与 `test_data/new` 的脱敏代表性 FIT。真实账号 smoke、
legacy shadow、生产切换与第五层正式编排必须由授权流程单独批准；本手册不授权登录。

失败时：429 的长冷却读取 receipt `next_retry_at_utc` 后由第五层恢复；401 执行显式
`trainlab garmin auth`；解析或 raw 问题使用有界 `repair --strategy reparse`，对账使用
`reconcile`，不得直接修改 cursor/gap 或删除原始对象。
