---
name: garmin-sync
description: Inspect or run the current FIT-only activity synchronization module within an explicitly approved date and call budget. Do not collect health data or manage Workouts.
---

# Garmin FIT 同步

当前实现与接口见[运动同步](../../docs/fit-sync.md)和[协议适配](../../docs/garmin-fit-adapter.md)。遵守[产品边界](../../AGENTS.md)，旧 M9/M10 固定测试窗口不是当前授权。

- 只查询运动库存和下载 FIT；优先复用登记文件。完整分页才能证明无活动，查询完成和下载完成分别记账。
- Python 管理日期、缺口、预算、SHA、原子落盘和新 SQLite。不要让 AI 转抄 MCP 原始结果。
- 日常目标是香港22:00检查当日、昨日及已登记缺口，周日15:00额外同步；完整调度尚未交付，本文件不会启动后台任务。
- 真实读取前核对当前批次的日期、工具、调用/下载上限及墙钟授权。固定缓存版本和认证防护保持，不静默安装、登录、刷新 Garmin Token 或重试。
- 内部 `SyncSpec` 必须显式提供 `total_timeout_seconds`；单次超时不是整次预算。
  原截止时刻随请求耐久冻结，重启/搬迁不返还时间；旧无总预算任务仅可只读核对已有成功证据。
- GPS/名称可随有来源的运动事实进入选定 AI；不得公开、进入 Git 或输出凭据。位置不是天气或坡度的证明，不新增地图/天气服务。
- 成功范围直接复用，失败或未知按当前同步账本对账，不通过旧脚本或改请求重跑。

健康 API、旧 raw 六表写入及旧日/周批次执行器已退出目标；只按当前模块和迁移状态工作。
