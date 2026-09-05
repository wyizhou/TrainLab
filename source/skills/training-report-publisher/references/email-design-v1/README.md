# TrainLab 邮件设计快照 v1

本目录是 2026-08-21 从用户提供的 OpenDesign 高保真交接包中筛选出的只读开发快照。外部原件：

`/Volumes/DiskOther/Design/c8d5a31b-0a34-497d-9ef5-9598724331b5`

筛选口径排除 `.open-design/**`、`*.artifact.json` 与四份示例 JSON；其余 41 个源文件的
manifest SHA-256 为：

`150399ae8cd96c6242ba70c3e342a593847c168f2050481e2c9dd725ea9e07d9`

仓库只保存实施所需的七份文本规范、令牌及字段分类，不复制设计预览、二进制样例图或工具元数据：

- `HANDOFF.md`：结构与交接约束；
- `FIELD-MAPPING.md`：183 条设计字段映射原表；
- `DESIGN-SPEC.md`：响应式、颜色、状态和客户端兼容规则；
- `brand-spec.md`、`design-tokens.json`：品牌与颜色来源；
- `field-classification.json`：183 行逐项标记为 `direct`、`derived` 或 `unsupported`。

这里的 HTML/SVG/PNG 样例不是运行时资源。生产邮件使用显式 Python 组件渲染，生产图表必须
从当次已验证数组确定性生成；`unsupported` 字段必须隐藏，不能为了还原视觉样例而补造数据。
