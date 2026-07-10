# Changelog — append-only 账本

**append-only：永不改写、永不删除历史行。** 只在文件末尾追加。

每条 contract 修订必须记录：`design_rev`、变更档位（cosmetic / structural / scope）、受影响需求编号、决议（保留 / 返工 / 废弃 / 新增）。
`cosmetic` 变更也在此追加一行，但不动 backlog、不动 contract、不阻塞 Executor。

格式：

```
- [<ISO 时间戳>] design_rev=<N> impact=<档位> 受影响=<需求编号,...> 决议=<...> — <一句话摘要>
```

---

<!-- 追加区（新行加在文件末尾） -->
