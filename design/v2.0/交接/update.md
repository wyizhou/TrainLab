---
design_rev: 2
version: "2.0"
updated_at: 2026-07-11T10:30:00+08:00
---

# v2.0 更新摘要

建立全设备响应式基线(手机 / 平板 / 桌面 / 宽屏逐屏真重排),按精确参数完成全局视觉保真返工(含对话气泡布局返工),并删除「数据保留策略」分组。信息架构、组件集合与 mock 边界与 v1.0 一致。

## 变更清单

| # | 模块 | 变更描述 | impact | 涉及组件/token |
|---|------|---------|--------|---------------|
| 1 | 全局 | G-resp 基线升级为多设备断点矩阵:mobile <640 / tablet 640–980 / desktop 980–1440 / wide ≥1440,断点状态由 resize 驱动 | structural | BreakpointState |
| 2 | 全局 | 视觉保真返工:全部组件按精确参数(背景/边框/圆角/内外边距/字号/字重)固化到设计文档 token 与组件参数表 | cosmetic | 全部组件, 全部 token |
| 3 | 全局 | 手机端导航重排:隐藏顶部导航项,新增固定底部 tab 栏(5 项,图标+文字);主内容区底部预留 76px | structural | TopNav, BottomTabBar |
| 4 | 全局 | 顶栏「上次同步」胶囊仅 desktop/wide 显示;主内容区 padding 按断点分级 | structural | Header, Main |
| 5 | 分析 | 对话框布局返工:气泡最大宽度按断点分级,用户/AI 气泡圆角不对称(尾角 4px),移除 AI 气泡 46% 最小宽度 | structural | ChatMessage |
| 6 | 分析 | 图表卡片展开态数据明细行仅 desktop/wide 显示;会话栏 desktop 左栏 / tablet+mobile 顶部下拉(v1.0 已有 tablet,本版扩展到 mobile) | structural | ChartCard, SessionRail |
| 7 | 运动记录 | 列表 mobile 行转卡片(名称+4 指标网格+日期来源行),desktop/tablet 保持全列表格;卡片模式配简化分页 | structural | ActivityTable, ActivityCardList |
| 8 | 运动记录 | 详情 mobile:Laps 表、逐秒数据表行转卡片;时序图表 X 轴刻度 mobile 抽稀为 3 档(首/中/末) | structural | LapsTable, RecordTable, TimeSeriesChart |
| 9 | 健康记录 | 睡眠/体重/静息心率/HRV 四张明细表 mobile 行转卡片;睡眠柱状图 mobile 显示近 7 天(桌面 14 天) | structural | HealthTables, SleepChart |
| 10 | 连接器 | 双卡片与上传双栏 grid 最小列宽改为 min(320px,100%),mobile 单列堆叠且无横向溢出 | structural | ConnectorCard, FileUpload |
| 11 | 连接器 | 2FA 授权弹窗与冲突合并弹窗 mobile 全屏化(100% 宽、无圆角、内部滚动) | structural | ConnectorAuthModal, ConflictModal |
| 12 | 设置 | 心率区间输入 grid:desktop 4 列 → mobile 2 列;各分组卡片单列堆叠 | structural | SettingsSections |
| 13 | 设置 | 删除「数据保留策略」分组(占用统计/保留期限/到期清理),五分组 → 四分组;数据不提供整体删除或到期清理 | scope | SettingsSections(-RetentionGroup) |

## 详细设计

见 `v2.0-设计文档.md`。
