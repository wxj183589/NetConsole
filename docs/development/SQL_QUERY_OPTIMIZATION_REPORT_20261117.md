# SQL 共享读取优化报告（2026-11-17）

状态：`PARTIAL_SQL_QUERY_OPTIMIZATION`。本轮完成无人值守静态库存的批量与共享读取；不把局部通过表述为全局 SQL 优化完成。

## 基线与范围

- 产品基线：`dd026f2fffa280bb9fa43d3c6da34f831bad9a16`，包含 PR #119 的 squash 结果。
- 分支：`codex-A/sql-read-model-sharing-20261117`。只做本地提交，不 Push、PR、Merge 或发布；产品 main 保持原指针。
- 编码前审计和 L3 Consumer Audit：[审计报告](SQL_QUERY_AUDIT_20261117.md)。Registry 对已检查路径给出的最低等级为 L2；因静态读取契约跨多个消费者，人工上调为 L3。
- 合成规模为 25/50/100 trains，即 50/100/200 MR、100/200/400 主备 IP，每场景 30 次。Job Center 使用 120 个合成任务。
- 证据统一放在 Workspace `reports/diagnostic/sql-query-optimization-20261117/`，而不是新增 Workspace 顶层 diagnostic 目录。

## 实际修改

| 文件 | 职责 |
| --- | --- |
| `src/netconsole/models/ground_inventory.py` | 不可变 InventoryCollection、SiteInventorySnapshot、无秘密元数据及递归 freeze/thaw |
| `src/netconsole/repositories/device_repository.py` | UUID 批量读取及批量凭据状态；库存只读凭据存在性；单设备 get 不再加载全部凭据状态 |
| `src/netconsole/repositories/ground_unattended_repository.py` | Site 库存短读事务、1 秒有界缓存、相关写事务成功提交后失效 |
| `src/netconsole/services/ground_unattended/inventory.py` | 静态源投影、revision 复核、批量设备关联、preview/synchronize 共享 collection |
| `src/netconsole/services/ground_unattended/heartbeat_supervisor.py` | 同 tick 使用同 snapshot，目标变化才 configure/reconcile，保留恢复与清除隔离 |
| `src/netconsole/services/ground_unattended/syslog_runtime.py` | revision 驱动 IP/hostname/备用 IP 索引，原子发布并拒绝迟到旧快照 |
| `src/netconsole/services/ground_unattended/supervisor.py` | 复用 Heartbeat 的 source provider；一个调度周期传递同一 Ground snapshot |
| `src/netconsole/services/ground_unattended/deep_scheduler.py` | 共享静态 MR；启动前读取新鲜 Device、凭据和参与资格，精确核对 UUID |
| `src/netconsole/services/ground_unattended/application_service.py` | Heartbeat 请求共用库存/state；复用 mesh_query；Quick Ping 复用静态 MR |
| `tests/test_ground_inventory_sharing.py` | SQL/连接上界、不可变、revision/TTL、并发、Site、Syslog、Deep、共享结果测试 |
| `tests/test_ground_unattended_heartbeat_inventory.py` | 将旧逐 MR 调用桩改为批量读取桩 |
| `scripts/dev/sql_read_sharing_profile_20261117.py` | 组合既有 profiler/fixture，补连接、类别、行数和应用缓存冷读指标 |
| `config/architecture/direct_sql_access.yaml` | 为离线合成 profiler 的 SQLite 入口登记 TEST_ONLY；未加豁免或屏蔽规则 |

另新增本报告、审计报告和[验证报告](SQL_QUERY_VALIDATION_20261117.md)。没有 schema migration、新索引、版本、安装器、前端或用户工作簿修改。

## 共享读取设计与一致性

沿用两个数据权威，不把 Site DB 和 Ground DB 合并为跨库事务：

1. `TrainInventorySyncService` 持有 Site 静态源 `InventoryCollection`。使用现有 `list_mesh_import_context_mrs()`，避免一般 MR 分页的运行态 enrichment。UUID 去重后每批不超过 900 个参数，在同一个只读 connection 和短事务内读取设备及凭据状态。库存元数据在 SQL 中屏蔽秘密，仅返回连接资格/就绪标志；真实连接仍读取原 Device DTO。
2. 标准 source reader 使用已有 `base_data_revision()`，读取前后复核，变化最多重试三次，持续不稳定失败关闭。成功 collection 有 1 秒 TTL，revision 变化立即重新收集；注入 reader 不跨调用缓存，只接受显式操作内共享。
3. Ground Repository 持有 `SiteInventorySnapshot`：同一短读事务执行 train/policy、endpoint、heartbeat selection state 三个 SELECT。缓存按 Site/Repository 实例隔离，包含内容 revision、生成时间和单调加载时间。
4. `sync_inventory`、priority/policy、Heartbeat selection/clear、Syslog identity 确认在原业务写事务成功提交后失效；rollback 保留旧快照。本实例 RLock 只覆盖短静态读/提交发布，不共享 SQLite connection，不引入全局数据库锁。其他 Repository 实例的写入最多在下次 1 秒 TTL 刷新后可见；这不是跨进程即时通知。
5. Heartbeat、Syslog、Supervisor、API 使用同一 Ground provider；Deep 和 Quick Ping 通过同一 source provider 获取身份。Deep 仍需动态 train_runs/调度状态，并在启动前重新授权；没有把动态监控结果写入静态缓存。

Heartbeat 的目标 key 包含 Repository、revision、备用监控策略与 run；身份/IP 目标 signature 不变不重复 configure/reconcile。clear/run 变化重置内存状态，重开 Repository 时恢复持久丢包状态。主备 IP 仍独立监控，冲突地址仍被排除。

Syslog 把 IP/hostname 两个索引作为同一 tuple 一次发布，解析只取一个版本引用；备用地址进入索引，歧义仍返回冲突/未识别。FIFO、raw writer、parser、spool 与动态位置投影链没有重构。

## 实测对比

主规模 50 trains / 100 MR / 200 IP。`SELECT/连接` 为每次操作 p50，时间为包含 JSON 序列化的请求 wall p50，单位 ms。

| 场景 | 基线 SELECT/连接 | 优化连续读取 SELECT/连接 | 优化应用缓存冷读 SELECT/连接 | wall 基线 / 连续 / 冷读 |
| --- | --- | --- | --- | --- |
| Inventory collect | 304/101 | 1/1 | 9/4 | 309.82 / 4.37 / 33.33 |
| preview + synchronize | 613/205 | 7/4 | 15/7 | 626.74 / 25.98 / 58.21 |
| Heartbeat targets + Syslog refresh | 5/3 | 0/0 | 3/1 | 8.76 / 0.01 / 6.04 |
| Heartbeat API，无心跳事实 | 14/9 | 9/6 | 12/7 | 25.23 / 19.15 / 24.92 |
| Quick Ping 验证 16 目标，停止在 probe 前 | 32/11 | 1/1 | 9/4 | 66.78 / 5.19 / 36.58 |
| Quick Ping 空历史 | 2/1 | 2/1 | 未单独冷读 | 1.72 / 1.87 / — |

Inventory 冷读的 9 个 SELECT 包含源 revision、静态源投影、设备和凭据；不是只报设备子查询。连续读取仍有 1 次源 revision 查询，因此不能宣称整个 Inventory 零 SQL。每次同步仍执行原业务写事务，本轮不把它替换为内存覆盖。

扩展规模的冷读 SELECT/连接：

| MR 数量 | collect 基线 → 优化冷读 | preview/sync 基线 → 优化冷读 | Heartbeat/Syslog 基线 → 优化冷读 |
| --- | --- | --- | --- |
| 50 | 154/51 → 9/4 | 313/105 → 15/7 | 5/3 → 3/1 |
| 100 | 304/101 → 9/4 | 613/205 → 15/7 | 5/3 → 3/1 |
| 200 | 604/201 → 9/4 | 1213/405 → 15/7 | 5/3 → 3/1 |

这些规模没有跨过 900 参数边界；另有 902 个唯一 UUID 的回归，验证跨两批仍为 1 connection / 6 SELECT。消除了设备查询次数随每个 MR 线性增长的路径；对象构造、序列化和数据行数仍随库存规模增长。

## 查询计划与索引

机器证据 `query-plan.json` 区分既有 profiler 的代表性查询和本轮实际 shared read 查询。

- UUID 批量设备和凭据状态均命中现有唯一索引。
- Ground train/policy 关联和 state 读取命中现有 Site/复合主键索引。
- 实际 all-inventory 排序包含 policy COALESCE，train 与 endpoint 查询仍有 `USE TEMP B-TREE FOR ORDER BY`；raw files 代表性查询也有末项排序临时树。没有把它们隐瞒为全索引覆盖。
- 当前证据确认主要成本来自重复读取/N+1；不足以证明新增索引的净收益，故保留 schema 和索引。更大库存与真实动态负载下的排序成本留待专项。

## 未完成与测量限制

- Job Center 120 任务的 list/summary/detail/logs 仍为 5/5/7/4 SELECT，各 1 connection；这些实际入口未观察到逐任务增长，但不能据此证明所有 hydrate/include_result 批量路径无 N+1。未改 Job Center 业务代码。
- 非空 AC/Mesh、ARP、历史和报告场景仅静态审查，未独立全面测量；Heartbeat API 本次测的是无心跳事实路径，不能外推到全部页面状态。
- 200 MR 的 Heartbeat API 冷读 p50 从 33.32 增至 35.21 ms，p99 从 39.90 增至 60.84 ms；100 MR 的连续读取 p99 也从 29.91 增至 34.90 ms。未宣称所有时延指标改善。
- 同机同时存在定向测试负载；30 样本的尾分位仅作描述，不代表统计显著性或长稳承诺。冷读仅清空应用静态缓存，不清空 OS/SQLite page cache。
- InventoryCollection 比旧 tuple 多 MR/revision 等字段，其 JSON bytes 增长不等于 API payload 退化；Heartbeat API 在本次各规模测量的 response bytes 与基线一致。SQL 行数统计包括元数据 fetched rows。
- 不执行全量测试、发布 Gate、GUI、真实数据、设备、长时或合并后验收；这些全部 NOT RUN/NOT VERIFIED。

## 数据与目录影响

`PRODUCTION_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`（业务/历史数据库）、`MAINTENANCE_AUTHORIZED=NO`。未访问 Production/Dev 真实数据库，未执行 checkpoint、VACUUM、数据库或 WAL/SHM 删除，未修改用户工作簿。

早期默认 pytest 临时 fixture 曾由测试框架自动清理，不能表述为所有合成 DB 均被保留。最终两组定向测试使用唯一显式 basetemp 与 `NETCONSOLE_PRESERVE_TEST_BASETEMP=1`，保留本轮基准及定向 fixture，未为清理本任务而删除旧数据库。

先前经用户逐项授权完成历史目录精确迁移，并停止旧 5174 Vite/pnpm 链；17 文件迁移前后 SHA-256 一致。路径映射见 Workspace `reports/maintenance/workspace-layout-20261117-sql-read-optimization/migration-manifest.json`。本轮未重复迁移或整理其他目录。

后续先在本地审阅本分支，再按独立授权集成；集成 commit 需复跑消费者。全局 AC/ARP/历史性能、长时缓存一致性和真实 GUI/设备验证保留待办。
