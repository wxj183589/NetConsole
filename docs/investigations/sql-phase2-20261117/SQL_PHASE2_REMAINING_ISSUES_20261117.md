# SQL 第二阶段剩余问题

状态：`PARTIAL_SQL_PHASE2`

以下项目保持未完成，不能从本阶段的 Job Center 结果读取优化推导为全局 PASS：

1. **AC / FIT-AP / Mesh-Link**：需要非空双 AC、堆叠/集群/1+1 和 Mesh-Link 分页 fixture，分别记录 SELECT、连接、行数、p50/p95/p99 和 EXPLAIN；重点核对 `_mr_rows`、`_link_rows` 是否全量读取后内存切片。
2. **Ground ARP**：需要多 MR、重复 IP/MAC、冲突和部分快照的读取 profile；写入语义、增量 Upsert、历史身份和冲突阻断已冻结，本阶段没有改变它们。
3. **Heartbeat API**：需要覆盖有/无心跳事实、主备 IP、离线/恢复、清空历史、切 Site 以及 100/200 MR。动态事实不得进入静态缓存；第一阶段无事实路径的结果不能替代这些场景。
4. **历史和归档**：Heartbeat、Quick Ping、Syslog、丢包、位置、Ground 运行记录、任务日志仍需时间范围、分页和归档 fixture，确认过滤是否在 SQL 层完成以及排序是否命中索引。
5. **Job Center 列表排序**：当前计划仍报告 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`。没有大规模真实读负载和写入成本对比前不增加索引。
6. **集成验收**：本地定向门禁通过，但未运行全量测试、Renderer/Electron、Release Gate、真实 GUI、设备、长时或合并后验证；本阶段没有创建 PR 或合并。

数据安全结论保持：`PRODUCTION_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`MAINTENANCE_AUTHORIZED=NO`。这些问题需要独立的合成数据和明确范围，不通过复制完整真实数据或清理历史资料解决。
