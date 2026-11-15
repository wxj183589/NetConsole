# Ground SQL 优化前后对照

数据来源：同一 synthetic fixture、同一 60 次迭代画像。优化前为基线 `D:\study\NetConsole-Workspace\diagnostic\ap-ledger-sql-opt-20261115\sql-profile-after\metrics.json`，优化后为 `D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\sql-profile-final\metrics.json`。

| 模块 | 优化前 SQL | 优化后 SQL | P95 wall 前 | P95 wall 后 | P95 SQL ms 前 | P95 SQL ms 后 | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Inventory | 5 | 5 | 3.706 | 3.689 | 1.761 | 1.604 | PASS |
| Heartbeat inventory state | 4 | 4 | 1.982 | 2.449 | 1.273 | 1.586 | PARTIAL，测量噪声/轻微回退 |
| Heartbeat snapshots | 4 | 4 | 2.671 | 2.809 | 1.426 | 1.441 | PARTIAL，基本持平 |
| Quick Ping runs | 44 | 6 | 2.861 | 2.309 | 1.571 | 1.131 | PASS |
| Quick Ping query | 45 | 7 | 2.856 | 2.586 | 1.718 | 1.457 | PASS |
| Quick Ping events | 4 | 4 | 2.054 | 2.593 | 1.370 | 1.488 | PARTIAL，结果稳定但画像波动 |
| Raw files | 4 | 4 | 1.784 | 2.197 | 1.129 | 1.321 | PARTIAL，结果稳定但画像波动 |

本轮实际改动集中在 Quick Ping 批量投影；没有调整阈值、删除断言或改变业务统计。Heartbeat/Raw 的小幅 P95 变化如实保留，需后续在固定 CPU/IO 条件下复测。
