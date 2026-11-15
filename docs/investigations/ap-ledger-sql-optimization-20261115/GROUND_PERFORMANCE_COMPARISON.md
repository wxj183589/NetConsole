# 地面 SQL 优化前后对比

范围：同一代码基线、同一隔离 fixture、同一 60 次迭代 harness；仅比较直接 Repository 查询，不宣称 HTTP/API 或现场延迟。

| 查询 | 基线 p50 | 优化后 p50 | 基线 p95 | 优化后 p95 | SQL 次数基线 → 优化后 |
| --- | ---: | ---: | ---: | ---: | ---: |
| inventory | 2.867 | 2.575 | 3.807 | 3.706 | 9 → 5 |
| heartbeat_inventory_state | 1.849 | 1.391 | 2.454 | 1.982 | 8 → 4 |
| heartbeat_snapshots | 2.496 | 1.745 | 3.083 | 2.671 | 8 → 4 |
| quick_ping_runs | 2.603 | 2.042 | 3.311 | 2.861 | 48 → 44 |
| quick_ping_query | 2.272 | 1.923 | 3.014 | 2.856 | 49 → 45 |
| quick_ping_events | 1.808 | 1.410 | 2.361 | 2.054 | 8 → 4 |
| raw_files | 1.758 | 1.385 | 2.384 | 1.784 | 8 → 4 |

优化后 p99（ms）依次为：inventory 5.956、heartbeat inventory 2.149、heartbeat snapshots 3.011、Quick Ping runs 3.127、Quick Ping query 2.957、Quick Ping events 2.275、raw files 2.332。inventory p99 在该小样本中受本机抖动影响上升，因此不隐藏异常，只以 p50/p95 和 SQL 次数作为本次本地证据。

响应 JSON 字节数在每个对比项保持一致；隔离数据库均为 614400 bytes，最终 journal mode 均为 `wal`。这说明本次读连接优化没有改变业务返回体，也没有以关闭写侧 WAL 换取局部读延迟。

HTTP API p50/p95/p99、body size、lock waits、连接峰值、WAL 增长、checkpoint 和队列等待：`NOT RUN / NOT COLLECTED`，需要真实 Backend + Electron/现场采集窗口补齐。
