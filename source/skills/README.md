# TrainLab 本地产品模块：M12 迁移中

旧 AI + Skills 自动路线已经退役；不要根据本索引启动旧日/周流程。
[产品边界](../AGENTS.md) 和 [迁移清单](../docs/legacy-retirement.md) 说明当前状态。

| 现有目录 | M12 处理 |
| --- | --- |
| garmin-sync | 迁移活动 inventory、FIT 下载、可选活动 weather；退役健康与睡眠同步 |
| training-coach | 迁移 FIT 解析、证据/安全校验；退役日报及 M11 固定 Candidate 调用链 |
| weekly-fitness-summary | 迁移运动技术复盘；新周报不依赖七份健康日报 |
| training-report-publisher | 退役高保真 HTML/CID 邮件，建立简单 Markdown/PDF 输出 |
| gmail-sender | 保留 REST/OAuth、单次发送、RAW 核验；迁移到新账本，不复用旧批次 |
| garmin-training-sender | 保留课程内容/步骤和排期能力；仅管理新库明确记录的自有 ID |
| _shared | 归档工具及新独立 Python 模块；旧六表和历史批次不是新运行依赖 |

六份 SKILL.md 已统一说明当前 M12 目标、已实现基础和未交付边界；不再指导旧日报或历史发送批次。
旧脚本和测试的退出按逐场景映射核对，不能因仍有文件就把它当作活动入口。auto.txt 只返回退役通知。
新 Python 命令、数据目录和实际部署状态以 M12 后续已验收交付为准，当前尚未启用。
