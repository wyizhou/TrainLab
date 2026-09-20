# H34-CHECK-002：主组合脚本首次入口失败

2026-09-20。首次`python3 exec-plans/evidence/ADHOC-0034/prepare_combinations.py`退出1，报第31行`SyntaxError: Non-UTF-8 code starting with '\xe7'`。发生在解析阶段，未开始组合/写入。

随后读同一文件：UTF-8严格解码成功；Python 3.9.6对同一bytes和text的compile均成功。SHA及诊断保存在`prepare-first-diagnostic.json`，原脚本为`prepare-combinations-first.py`。原因未进一步定论，不将文件编码损坏作为已证事实。

只将该长字面量折行为相邻字面量；AST与原版完全一致。原Python文件入口随后退出0并完成两组合准备。没有换执行协议/升级依赖/改产品；此为主协调工具首错1次，不是Harness功能失败，也不计入0033历史失败。原始错误和恢复方式如实保留。
