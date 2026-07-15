---
design_rev: 1
version: "1.0"
updated_at: 2026-07-10T18:30:00+08:00
---

# v1.0 更新摘要

TrainLab 首个定版设计:六模块完整可交互原型(登录 / 分析 / 运动记录 / 健康记录 / 连接器 / 设置),确立"只存原始数据、衍生指标全部由 AI 对话产出"的信息架构。

## 变更清单

| # | 模块 | 变更描述 | impact | 涉及组件/token |
|---|------|---------|--------|---------------|
| 1 | 全局 | 顶部导航信息架构定版:分析(默认页)/ 运动记录 / 健康记录 / 连接器 / 设置;深色仪表盘视觉系统与色板定版;全局 tabular-nums | structural | TopNav, 色板 tokens |
| 2 | 登录 | 用户名 + 密码 + 4 位验证码验证登录 | scope | LoginForm |
| 3 | 分析 | 多会话列表(新建/重命名/删除),平板降级为下拉选择 | scope | SessionRail |
| 4 | 分析 | 数据范围选择器(3/7/15/30 天 + 勾选具体运动)+ 附带健康记录 / 附带习惯记录开关(默认均开) | structural | ScopeBar |
| 5 | 分析 | 图表卡片四态:加载 / 数据不足空态 / 折叠(一行摘要)/ 展开(带 X/Y 轴刻度图表 + 数据行);平板下展开态隐藏数据行 | structural | ChartCard |
| 6 | 分析 | AI 回复以 HTML 渲染(表格/列表);内置隐藏系统提示词强制 HTML 回复,设置页可查看 | structural | ChatMessage, SysPrompt |
| 7 | 运动记录 | 列表:类型筛选 + 分页(20/50/100)+ 单条/批量 FIT 下载 | scope | ActivityTable, Pager |
| 8 | 运动记录 | 详情:字段集 = 真实 FIT 文件字段 ∩ 佳明详情页,缺失显示 "--";时序数据双模式:降采样曲线(带轴标签与来源字段)⇄ 逐秒数据表(分页);心率区间图边界取自设置页区间设定 | structural | ActivityDetail, TimeSeriesChart, RecordTable |
| 9 | 健康记录 | 五标签页:睡眠 / 体重 / 静息心率 / HRV / 习惯(习惯含日期选择 + 早/中/晚/全天因子勾选);表格分页 | structural | HealthTabs, HabitPicker |
| 10 | 连接器 | 佳明中国区/国际区双卡片,状态集合:已连接 / 未连接 / 同步中 / 同步失败(错误详情 + 重试) | structural | ConnectorCard |
| 11 | 连接器 | 授权登录弹窗:账号密码 + 可选 2FA 两段式验证 | scope | ConnectorAuthModal |
| 12 | 连接器 | 双账号按「开始时间 + 时长」自动合并去重;冲突横幅 + 手动选择保留弹窗 | scope | ConflictBanner, ConflictModal |
| 13 | 连接器 | FIT / TCX / GPX 文件上传区并入本页,解析入库标记来源 | structural | FileUpload |
| 14 | 设置 | 账户信息、单位制、区间设定(MaxHR/LTHR/FTP/Z1–Z4 上界)、数据保留策略、AI 接口(DeepSeek 兼容)五个分组 | structural | SettingsSections |

## 详细设计

见 `v1.0-设计文档.md`。
