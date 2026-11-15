# 地面无人值守 SQL 基线

基线提交：`5fca0856d86a4d850133aa150623dec1b179dc93`
采集方式：`scripts/dev/ground_sql_profile_20261115.py`
数据：隔离 SQLite fixture，50 列车、100 MR、200 IP、20 个 Quick Ping 运行；每个查询 60 次。不是现场设备、生产数据或 Electron HTTP 基线。

## 基线结果

| 查询 | p50 wall ms | p95 wall ms | p99 wall ms | p50 SQL 次数 |
| --- | ---: | ---: | ---: | ---: |
| inventory | 2.867 | 3.807 | 4.153 | 9 |
| heartbeat_inventory_state | 1.849 | 2.454 | 2.641 | 8 |
| heartbeat_snapshots | 2.496 | 3.083 | 3.308 | 8 |
| quick_ping_runs | 2.603 | 3.311 | 3.417 | 48 |
| quick_ping_query | 2.272 | 3.014 | 3.115 | 49 |
| quick_ping_events | 1.808 | 2.361 | 2.968 | 8 |
| raw_files | 1.758 | 2.384 | 2.678 | 8 |

基线读路径通过普通连接触发 SQLite 配置/WAL 初始化；基线 fixture 的最终 journal mode 为 `wal`。响应 JSON 字节数作为 projection 体积记录，未发现本次优化改变响应契约。

详细原始结果：

`D:\study\NetConsole-Workspace\diagnostic\ap-ledger-sql-opt-20261115\sql-profile-before\metrics.json`

## EXPLAIN QUERY PLAN 基线边界

本基线保留运行时查询数量和时间，不把本地 fixture 的查询计划当作现场数据库计划。优化后计划见对比报告；现场数据库版本、数据规模和索引状态不同，必须在真实数据副本上复核。
