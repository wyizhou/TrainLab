# TrainLab 邮件视觉规范

系统一句话：以深海军蓝建立可信的训练工具骨架，用克制青绿标记“可以行动”的信息，并以宽松中文行距保持教练式的友好阅读感。

## 核心令牌

```css
:root {
  --bg: oklch(0.970 0.012 210);
  --surface: oklch(0.990 0.004 210);
  --fg: oklch(0.240 0.040 250);
  --muted: oklch(0.540 0.028 245);
  --border: oklch(0.890 0.020 210);
  --accent: oklch(0.530 0.100 180);
}
```

邮件客户端使用以下兼容回退值：

| 令牌 | HEX 回退 |
|---|---|
| `--bg` | `#F3F7F8` |
| `--surface` | `#FBFCFC` |
| `--fg` | `#142337` |
| `--muted` | `#627184` |
| `--border` | `#D8E2E5` |
| `--accent` | `#0B7F78` |

## 字体

- Display：`"Aptos Display", "SF Pro Display", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- Body：`Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- Mono：`"SFMono-Regular", Consolas, "Liberation Mono", monospace`

## 视觉姿态

1. 邮件宽度控制在 640px，采用表格骨架、内联样式和单列移动端重排。
2. 深色头部只承担品牌、标题、日期三层信息，不使用渐变或装饰图形。
3. 青绿色仅标记当前建议、关键状态或主要动作；安全提醒使用独立语义色。
4. 正文优先使用自然段、步骤表和短标签，不把长文本塞进多个彩色卡片。
5. 数据不完整与判断置信度明确分区，语气说明边界，不伪装成确定结论。
