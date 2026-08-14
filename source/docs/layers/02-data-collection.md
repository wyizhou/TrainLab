# Layer 2：Garmin 数据收集

Garmin 收集是显式的一次性命令。它只在用户批准的日期、资源和预算范围内运行，
并把原始响应以带来源 revision 的对象写入 Foundation v4。

## 资源层次

- 健康、睡眠和 physiology：按本地日期与时间窗口收集，原始对象进入 raw。
- 活动 inventory：先建立活动目录和生命周期，再按活动请求 summary、FIT 或 weather。
- activity summary / activity FIT / activity weather：是活动的不同 Provider 资源，
  只有在请求合同或 repair 场景明确允许时才取用；不能把单个 FIT 当作活动在线事实。
- 解析和投影只产生可追溯的派生行；无法唯一绑定的历史对象进入归档缺口，不猜测。

## 安全入口

```bash
python3.12 source/index.py garmin auth
python3.12 source/index.py garmin full --help
```

本次 M4 验证不执行认证、同步或 Provider 写入。运行时必须保留 cached-only、
预算、锁、权限、receipt 和失败关闭规则；在线缺口补充另需单独授权。
