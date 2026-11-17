# NetConsole 旧版第二阶段 SQL 专项审计

状态：`PARTIAL_SQL_PHASE2`

本阶段在第一阶段共享库存读取优化（产品 Commit `53172bb33caee7202ef16cceb3f22f933eaf7ef6`）之上，审计 Job Center、AC/FIT-AP/Mesh-Link、Ground ARP、Heartbeat API 以及历史/归档查询。范围限定为 SQL 查询次数、连接创建、批量读取和查询计划；不改数据库 Schema、不增加索引、不访问真实数据。

## 证据和方法

- 仓库：`D:\study\NetConsole-Workspace\NetConsole`。
- 分支：`codex-A/sql-read-model-sharing-20261117`；基线 `dd026f2fffa280bb9fa43d3c6da34f831bad9a16`。
- Job Center 使用 `scripts/dev/job_center_sql_profile_20261116.py`，隔离 SQLite fixture，1、20、120 个任务，每个规模 30 次；复用 `performance_profiling`，记录 SQL、连接、fetched rows、SQL 时间、请求 wall 时间和 EXPLAIN QUERY PLAN。
- 其余模块先做静态调用链/SQL 审计，并复核第一阶段已有的 Ground profiler。没有把未独立运行的模块写成 PASS。

## 审计矩阵

| 模块 | 本阶段状态 | 结论 | 后续动作 |
| --- | --- | --- | --- |
| Job Center list/summary/detail/logs | 已测量 | 单入口仍为固定查询数；旧结果 Hydrate 在多任务路径存在 N+1 | 已批量读取结果 authority |
| Job Center include_result / 多任务结果 | 已测量并优化 | 旧路径逐行开连接并读 authority；120 任务为 730 SQL/121 连接 | 一次连接 + `IN (...)` 批量读取 |
| AC / FIT-AP / Mesh-Link | 已审计，未独立测量 | 发现已有批量资源/历史读取；非空双 AC、Mesh-Link 分页和 `_mr_rows`/`_link_rows` 未形成可复现实测基线 | 保持未优化，安排专门 fixture/profile |
| Ground ARP 身份投影 | 已审计，未独立测量 | 代码已有按 MR UUID/IP 的批量读取和最新 collection 复用；本阶段不改写入语义 | 补充多 MR 合成测量 |
| Heartbeat API | 已审计，局部已有第一阶段测量 | 无心跳事实路径的共享库存已在第一阶段优化；本阶段未重新覆盖有心跳、主备、恢复和 100/200 MR 全组合 | 以动态事实专项 profile 验证 |
| Quick Ping / Heartbeat / Syslog 历史 | 静态审计或沿用第一阶段证据 | 已有分页/聚合路径；尚未证明全表扫描或重复加载是本阶段 P0 | 以时间范围、分页和归档 fixture 补测 |

## Job Center 重点发现

`JobCenterQueryService._hydrate_result_references()` 原先在 `include_result=True` 时对每个 `result_id` 独立打开连接、检查列并执行 authority 查询。单个任务看不出线性增长，但多任务 `list_task_results()` 会随结果行数增加连接和 SQL。结果 body 是不可变、按 `result_id` 寻址的数据，因此可以在不改变状态机、取消、事件和结果语义的前提下批量读取。

任务列表、汇总、详情和日志的普通入口没有观察到按任务数量线性增长；其计划仍使用现有快照主键/可见索引和事件序号索引。列表排序保留 `USE TEMP B-TREE`，没有证据支持本阶段新增索引。

## 安全边界

所有本阶段数据库均为任务专属合成 fixture。`PRODUCTION_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`MAINTENANCE_AUTHORIZED=NO`；未访问 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 或设备。完整机器证据保存在 Workspace `reports/diagnostic/sql-query-optimization-20261117/`。
