# TrainLab 产品工程

`source/` 是唯一可直接运行的产品目录，根目录的 AGENTS/PLANS/rules 属于开发 Harness，
不作为运行时配置或输入。

```sh
python3.12 source/index.py --help
python3.12 source/index.py foundation status
python3.12 source/index.py analysis daily --report-date 2026-08-13
```

产品源码在 `src/`，测试在 `tests/`。配置、state 和日志目录只保留本机私有实例；
可跟踪的配置内容仅限 `config/README.md` 与 `config/examples/`。不要把真实配置、
数据库、raw、FIT 或凭据提交到 Git。

运行时 Harness 位于 `src/resources/harness/`。分析输入必须是带 schema、来源和 lineage
的有界 JSON；报告生成不会自动发送邮件或写入 Garmin。
