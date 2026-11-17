# SQL 第二阶段优化报告

状态：`PARTIAL_SQL_PHASE2`

## 已实施

仅修改 Job Center 结果读取：

- 收集当前结果行的 `result_id`，去重后在一个只读连接中执行参数化 `IN (...)` 查询。
- 在同一查询中按需关联 `task_result_blobs`，保留 Blob authority、SHA-256、字节数和 codec 校验。
- 仍对缺失 authority、缺失 Blob、非法 codec、长度/hash 不一致失败关闭；不回退到过期或损坏的 `canonical_json`。
- 不共享 SQLite connection，不引入全局锁，不改变任务状态机、取消、事件顺序、逐设备结果或日志。
- 增加 24 条结果的连接上界回归测试，并在 profiler 中保留旧逐行路径作为直接对照。

## 结果

120 个任务、每个场景 30 次的 p50：

| 路径 | SELECT | 连接 | fetched rows | SQL ms | wall ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 批量 Hydrate | 17 | 2 | 342 | 0.73 | 3.19 |
| 旧逐行 Hydrate 对照 | 730 | 121 | 3078 | 31.65 | 79.29 |

20 个任务对应 `17/2/142/0.65/1.88`，旧路径为 `130/21/578/5.61/13.93`。1 个任务时两者都接近固定开销，不能用单任务样本证明 N+1；线性差异从多任务场景出现。

## 未实施和不变项

AC/FIT-AP/Mesh-Link、Ground ARP、动态 Heartbeat 事实和历史归档没有达到“先测量再修改”的门槛，因此没有修改。没有新增索引、Schema migration、缓存动态事实或改变数据保留策略。第一阶段共享库存和 Ground snapshot 实现完整保留。

查询计划详见 `SQL_PHASE2_QUERY_PLAN_20261117.json`；完整样本详见 `reports/diagnostic/sql-query-optimization-20261117/phase2-job-*-final2/metrics.json`。
