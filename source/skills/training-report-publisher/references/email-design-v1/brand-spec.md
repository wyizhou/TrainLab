# TrainLab 邮件品牌规范

系统一句话：冷白数据底盘、深蓝灰阅读层级与克制青绿色强调，结合跑步、攀岩、睡眠和恢复的稳定活动色，形成亲切而可信的运动日志。

## 核心 OKLch tokens

```css
:root {
  --bg: oklch(0.975 0.008 205);
  --surface: oklch(1 0 0);
  --fg: oklch(0.305 0.040 220);
  --muted: oklch(0.515 0.025 215);
  --border: oklch(0.900 0.020 205);
  --accent: oklch(0.525 0.100 190);
}
```

邮件生产代码使用 `design-tokens.json` 中的 sRGB 十六进制 fallback；OKLch 仅作为设计源，避免 Gmail 客户端不兼容。

## 字体栈

- Display / body：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- Mono：`SFMono-Regular, Consolas, Menlo, monospace`

## 视觉姿态

1. 先结论、后处方、再证据；重要信息不依赖图片。
2. 青绿色只用于品牌锚点或最关键状态；单个邮件首屏最多两处。
3. 卡片用浅边框和留白建立层级，不使用彩色左边框。
4. 跑步、攀岩、睡眠、恢复各有稳定活动色，但面积保持克制。
5. 状态必须同时提供中文词、符号与颜色；blocked 不出现正常绿色图表。
