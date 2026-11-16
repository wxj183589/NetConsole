# 地面无人值守 SQL 优化报告

## 已实施

1. 读路径新增真正的 SQLite read-only/query-only 连接，不创建缺失数据库、不提交事务、不在每次 GET 上执行 WAL 初始化。
2. 写路径仍保留 WAL 初始化和 busy timeout，避免将“读不产生副作用”错误实现为关闭 WAL。
3. Quick Ping、Heartbeat、Inventory、Heartbeat snapshot、Raw file 和相关统计查询切换到只读连接；Profile 等需要惰性初始化的写兼容路径保留普通连接。
4. 运行时性能 profile 增加 SQL 文本 Top-5、响应字节数，并由 API middleware 记录响应体大小，慢请求日志可关联 SQL 热点。
5. Mesh-Link 的 Peer/MR Identity 反查改为批量索引查询；静态 AP 资料作为当前 Site 的精确 MAC 回退，不依赖 AC 在线状态。
6. AP 基础资料 SQL-first 查询新增交换机、端口、建设阶段、来源类型筛选，以及站点/交换机/端口自然排序；`GE1/0/2` 排在 `GE1/0/10` 之前。

## 查询计划

优化后隔离 fixture 的 `EXPLAIN QUERY PLAN` 使用现有索引：

- inventory：`idx_ground_inventory_site_status`，并使用 train policy 主键索引；
- heartbeat snapshots：使用 `(site_id, run_id, entity_type)` 唯一索引；
- Quick Ping runs：使用 `idx_ground_quick_ping_runs_list`；
- raw files：使用 `idx_ground_raw_files_query`，排序最后一项使用临时 B-tree。

本轮没有为每个字段盲目添加索引；包含 `%keyword%` 的筛选不能有效利用普通前缀索引，保持现有索引边界，避免写放大和数据库膨胀。

## 边界与风险

- API p50/p95/p99、真实 lock wait、真实连接数、WAL checkpoint 压力和 24 小时运行未在本轮现场环境采集。
- 合成 fixture 结果不能替代真实 Site 数据、Windows Electron 进程和并发采集验证。
- 没有删除 WAL/SHM、历史数据或索引；没有执行 VACUUM、checkpoint 或生产维护。

详细原始结果：

`D:\study\NetConsole-Workspace\diagnostic\ap-ledger-sql-opt-20261115\sql-profile-after\metrics.json`
