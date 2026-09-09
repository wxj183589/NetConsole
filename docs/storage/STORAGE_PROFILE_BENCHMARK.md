# Storage Profile Benchmark

本轮使用现有 UDP Syslog workload 回归作为功能基准，未连接生产设备、未访问 `D:\NetConsoleData`。

| workload | received | raw_written | parsed | db_saved | application_drop |
|---|---:|---:|---:|---:|---:|
| UDP spool regression (1,000) | 1,000 | 1,000 | 1,000 | 结构化事件按解析结果 | 0 |
| UDP spool regression (5,000) | 5,000 | 5,000 | 5,000 | 结构化事件按解析结果 | 0 |

静态参数对比显示 CONSERVATIVE 将 Raw flush 阈值从记录数主导改为 512 KiB/400 ms，并将 DB 批量目标设为 1,000 条；实际 write-op、checkpoint 和 HDD 延迟曲线需要在主机 `D:\NetConsoleData-dev` 上完成长时组合压测后补录，不能用单元测试伪造。
