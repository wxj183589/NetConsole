# SQL 查询审计（2026-11-17，编码前）

## 范围与证据

- 基线：`dd026f2fffa280bb9fa43d3c6da34f831bad9a16`；独立分支 `codex-A/sql-read-model-sharing-20261117`。PR #119 已以 squash 进入该基线。
- 本报告先于生产代码修改形成；先静态审计，再运行合成基线，再决定下面的实施范围。
- 实测：`scripts/dev/sql_read_sharing_profile_20261117.py`，25/50/100 trains（50/100/200 MR，100/200/400 主备 IP），每场景30次。复用既有 `performance_profiling` Connection/Cursor 和请求统计，以及 Ground/Job profiler fixture/percentile/EXPLAIN。离线 TEST 根，不启动 lifespan、网络探测或设备命令。
- 原始证据：Workspace `reports/diagnostic/sql-query-optimization-20261117/baseline.json`；统计包含真实执行的 SELECT/WITH、PRAGMA、写入、显式事务、连接与 fetched rows，参数不写日志。下表为 SELECT/WITH 与连接数 p50，不是估算。

## 审计矩阵

| 模块/入口 | 查询与调用频率 | 50/100/200 MR SELECT 数 | 连接数 | 重复读取与结论 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| Inventory collect | MR 静态投影 + 循环 get_by_uuid；刷新周期 | 154/304/604 | 51/101/201 | 每 MR 设备、凭据表存在性及状态读；确认 N+1 | P0 |
| preview + synchronize | 一次操作两次 collect | 313/613/1213 | 105/205/405 | 源清单和设备重复收集，Ground previous/state 分开读 | P0 |
| Heartbeat targets + Syslog refresh | heartbeat 每 tick；Syslog刷新 | 5/5/5 | 3/3/3 | 独立全量静态库存；引擎每次 configure | P0 |
| Heartbeat API，无心跳事实 | 一次页面读取 | 14/14/14 | 9/9/9 | fallback 再读 active inventory；每请求创建 AC query | P0 |
| Quick Ping 验证16目标 | start 到 probe 边界 | 32/32/32 | 11/11/11 | 通用 MR 分页携带 runtime enrichment；不是逐目标 SQL，但扫描成本随库存增长 | P1 |
| Quick Ping history | 最近20任务 | 2/2/2 | 1/1/1 | 已聚合，保留 | P1 |
| Job Center | list/summary/detail/logs，120 tasks | 见 baseline.json 的 job_center | 同左 | list轻量投影；detail才加载结果；hydrate内部循环开连接仅在include_result=True，多行调用有潜在N+1，当前单detail不是 | P1 |
| AC/FIT-AP | summaries/resources/history；由业务触发 | NOT MEASURED | NOT MEASURED | AC批量resources、history preload已存在；保留写入与动态变化记录语义 | P1 |
| AC/Mesh-Link | list_mrs分页、_mr_rows/_link_rows | 随上述API实测计入，未独立测量 | 同左 | 静态设备与动态AC混合；避免inventory/QuickPing借用重投影。动态列表分页仍待专项优化 | P1 |
| Ground ARP | build_identity_observation_projection | NOT MEASURED（空API路径除外） | NOT MEASURED | 已按mr_uuid/IP批量IN与最近collection，保留边界；save_collection逐观测写入非本轮读取目标 | P1 |
| Rail Transit | _all_mrs、静态list_mesh_import_context_mrs | collect路径已实测，其他NOT MEASURED | 同左 | 静态投影一次设备+分组，无运行时enrichment；一般list_mrs分页仍需动态资料 | P1 |
| Syslog原始/位置/历史 | refresh_inventory与消息持久化 | refresh计入上方；其余NOT MEASURED | 同左 | 静态IP/hostname索引可按revision复用；不触碰FIFO/raw/parser/spool | P0/P2 |
| Ground历史/报告 | run、loss、archive、train_endpoint_snapshot | NOT MEASURED | NOT MEASURED | 已有批量查询与独立历史权威；不以静态cache代替历史与动态事实 | P2 |

静态检查覆盖 `DeviceRepository`、`GroundUnattendedRepository`、`AcRepository`、`GroundArpRepository`、`RailTransitBaseDataRepository`、`JobCenterQueryService`、`AcMeshLinkQueryService`、`RailTransitBaseDataQueryService` 和 Ground Inventory/Heartbeat/Supervisor/Deep/QuickPing/Syslog 调用链。NOT MEASURED 不代表没有热点，更不代表已完成全局性能验收。

## 编码范围决定

1. DeviceRepository 参数化批量 UUID，<=900 一批，同一连接批量凭据状态；库存只读秘密存在性，不将明文放入快照。
2. 不可变 InventoryCollection；preview/synchronize 共享一次结果，版本变更重读，保留冲突和 stale 检查。统一 Site 源读取服务，身份与连接授权分离。
3. Repository 持有 SiteInventorySnapshot；同一短读事务读全部库存、策略和heartbeat选择状态；不可变且有revision/生成时间；相关writer提交后失效；跨实例变更有界刷新。连接不共享、无全局数据库锁。
4. Heartbeat/Syslog/API/Supervisor消费同一provider；目标/索引仅revision变化重建；Deep保留动态train_runs及启动前新鲜凭据检查。QuickPing使用静态身份投影，保留地址校验及原子预留。
5. 优先减少读次数，不改schema，不预先增加索引；EXPLAIN证据不足不增索引。

## L3 Consumer Audit（编码门禁）

| 维度 | 当前事实/实施约束 | 回归 |
| --- | --- | --- |
| Writers | Device CRUD/group/credential；Ground sync_inventory/set_priority/save_train_policy/heartbeat action/confirm_syslog_identity | 变更后revision、空列表、needs_reentry、主备策略 |
| Readers | Inventory、resident Heartbeat、Syslog身份、Supervisor策略、Deep、QuickPing、Heartbeat API | 对应定向pytest及SQL/连接断言 |
| Cache | 当前无统一静态cache；计划由同一Site repository/service持有；不同DB路径与Site隔离；generation防旧load覆盖 | 不可变、Site隔离、并发失效、TTL/源版本更新 |
| UI/API | DTO/错误码/历史fallback不变；动态RTT/loss/AP/Syslog位置不缓存 | Heartbeat API/state/resident、QuickPing stale/address/exclusivity |
| Export/history | 不改Artifact、schema、历史保留；list_inventory旧接口保持fresh mutable返回 | 定向历史与Job SQL回归；真实导出NOT RUN |
| Legacy | 保留旧credential状态、无状态表、旧profile默认、注入base_query fallback | Device/Inventory兼容测试；任意注入reader不只凭DB版本缓存 |
| Parallel | 起始主仓库clean，仅本任务新增profiler；单worktree，无重叠dirty；不动其他分支 | 最终status/diff复核 |
| Merge verification | 用户禁止merge/push；本分支结果不代表集成main结果 | 后续集成commit需重跑消费者；本任务不执行全量Gate |

风险：静态缓存过期、clear后旧状态恢复、并发load覆盖、凭据标记误作真实连接凭据、动态与静态混用。以有界刷新/版本复核、提交后失效、immutable、启动前fresh Device与定向测试控制。真实设备、GUI、长时及发布均NOT RUN。
