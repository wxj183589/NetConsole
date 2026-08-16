# Task Terminal Result Consumer Matrix

## 状态与边界

本文记录 Task 终态结果去重、物理 retention、索引和维护互斥契约。不可变
`task_results`、read-through、Site Return Package 四表合并和 typed retention 已进入受控
治理；dual-write 仍只在单个 `tasks.db` 显式切换后运行。历史 backfill、ref authority、
精确 retention 和 compact 只允许在 `D:\study` 隔离副本演练，生产 apply、生产 DELETE、
生产 VACUUM 和正式 retention policy 仍未启用。

当前 `finished/error/cancelled` 结果通常同时进入：

- `task_snapshots.result_json`，供当前状态、重启恢复、业务详情和 Artifact 投影读取；
- `task_events.payload_json.result`，供实时事件、事件回放、局点回传合并和审计读取。

新库、旧库升级和普通 Backend startup 均初始化为 `LEGACY_DUAL_FULL`，因此默认不为新
终态写入 `task_results`。schema version 4 和表存在只表示 capability 可用，不表示 rollout
已开启。只有带 revision CAS、reason 和 audit 的显式 transition 才进入
`TASK_RESULTS_DUAL_WRITE`，此时才临时保存第三份完整结果。

生产只读剖析显示，两份大型终态结果存在约 154 MB 语义重复。删除任一副本前必须先完成
下面的消费者迁移。

## 消费者矩阵

| Consumer | Snapshot result | Terminal event result | Replay | Restart recovery | Site Package | Agent reconciliation | Online MR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Task Center 列表/详情 | 是，详情、业务状态和 Artifact 投影的主输入 | 事件 API 可见，但不是详情主输入 | 是 | 是 | 间接 | 间接 | 显示映射摘要 |
| `/ws/tasks` / `TaskEventHub` | 否 | 是，当前实时终态原样广播 | 否 | 刷新后改读 REST/snapshot | 否 | 是 | LOCAL 终态协调使用 |
| `TaskApplicationService` / Worker 恢复 | 是，状态、结果、资源键和 orphan 核对 | 是，唯一事件、审计和日志历史 | 是 | 是 | 间接 | 是 | 是 |
| Agent Traffic / Agent package import | 是，Controller 当前任务状态 | 是，外部事件幂等写入和实时通知 | 是 | 是 | 是 | 是 | Agent Online MR 包导入写入两处 |
| Online MR Application Service | 是，Task 状态；Session 另有 mapping/session 事实源 | 是，LOCAL live terminal 的 status、stop reason、warnings | 有限 | 主要依赖 mapping、session metadata 和 snapshot | 是 | 是 | 直接依赖 |
| Ground Unattended | 使用关联 Task 的状态、资源占用和 Task Center 投影 | 不直接以完整 terminal result 作为 run/archive SSOT | 否 | Ground repository、run/session 和 archive 为主 | 间接 | 间接 | 深度采集通过 Online MR mapping |
| Site Return Package | 是，按 `updated_time` 合并 snapshot | 是，按 `event_id` 合并事件 | 是 | 是 | 直接依赖；先合并 `task_results` | 包含 Agent/Online MR 结果 | 已原子合并 `online_mr_task_sessions`，冲突失败关闭 |
| Artifact reconciliation / download | 是，Artifact id/hash/name/path metadata 的主输入 | 否 | 否 | 是 | Artifact 文件另行打包/校验 | 间接 | 报告由领域 owner 管理 |
| Device/Config/File/Network/Export 等领域 Service | 是，完成后刷新、下载和业务部分成功判断 | 少量流程读取事件历史，不应假设完整结果永久存在 | 部分 | 是 | 间接 | 部分 | 部分 |

关键结论：当前绝大多数长期读取依赖 snapshot，但 Online MR live 协调、通用事件 API 和
Site Return Package 仍要求 terminal event 可解释。B3 已补齐
`task_results -> task_snapshots -> task_events -> online_mr_task_sessions` 的单事务合并，
以 result identity/hash、event identity/payload 和 mapping 双重身份校验冲突。兼容期仍不能只
删除 event payload 或 snapshot result；默认生产写入继续只保留两份旧 full result。
Package 中存在 `task_results` 不会改变本地 rollout state。

## 方案比较

| Option | Replay / restart | Site Package / Artifact | Storage | Migration | 结论 |
| --- | --- | --- | --- | --- | --- |
| 1. Snapshot 保存完整结果，event 保存 ref/summary/hash | restart 简单；event replay 需按 ref 补读 | snapshot 后续 Artifact 最终化可能改写 result，必须先拆分不可变结果 | 低 | 中 | 可作为过渡，不宜作为最终权威模型 |
| 2. Event 保存完整结果，snapshot 保存 ref/summary | replay 简单；大量 snapshot 读取方需 join/回放 | 列表、详情、Artifact 和领域 Service 改动面最大 | 低 | 高 | 不推荐 |
| 3. 独立 `task_results`，snapshot/event 都保存 `result_id` | 可同时支持 replay 和 restart | Site Package 增加表合并；Artifact lifecycle 仍独立 | 最稳定，仅一份完整结果 | 高 | 推荐的长期权威模型 |
| 4. 大结果全部外置 Artifact/file | DB 最小，但文件缺失会影响任务结果恢复 | 必须解决加密、备份、包合并、原子提交和 Artifact 删除顺序 | 最低 | 最高 | 仅适合已有 Artifact 契约的特定领域 |

## 推荐权威模型

推荐 Option 3：使用不可变 `task_results` 作为终态业务结果的唯一权威副本。

- `task_results` 以 `result_id` 为主键，并保存 `task_id`、终态类型、canonical JSON、
  SHA-256、字节数、创建时间和 schema version。
- 显式 `TASK_RESULTS_DUAL_WRITE` 写入 terminal event 时，在同一 `BEGIN IMMEDIATE` 事务中
  写入/验证 result、更新 snapshot，并写入 event；两处旧 full result 和新增的
  `result_id/result_summary/result_hash` 同时保留。默认 `LEGACY_DUAL_FULL` 不执行该写入。
- Query Service 在兼容期通过 join/read-through 继续构造现有 `snapshot.result` DTO；
  事件详情只在明确请求时补读完整结果，列表、日志和普通 replay 使用 summary/hash。
- Snapshot 当前 `status` 不用于推导历史 result 的 terminal event type；legacy 数据可出现
  `FAILED snapshot + finished result event`。Snapshot ref 必须匹配 task/hash；Artifact
  finalization/rejection 产生新的不可变 result identity，并把当前 snapshot 原子重绑到该
  projection，原 terminal result row 保持不可变。event ref 必须额外精确匹配 event type，
  保留的 full result 必须匹配 canonical content。多个 terminal type
  提供不同结果时标记 `CONFLICT` 并保护，不猜测权威来源。
- live WebSocket 继续广播当前完整结果；dual-write 激活时，广播和持久化由同一已验证
  result identity 生成。
  “持久化层只保存 ref/summary/hash”仍是未来 cutover，不是 B3 当前写入行为。
- `artifact_finalized/artifact_rejected` 不得覆盖不可变业务终态结果；Artifact availability
  作为独立、同样不可变的 projection result 保存，当前 snapshot 只指向一个 canonical
  full result。
- Site Return Package 已补齐 `online_mr_task_sessions` 和 `task_results` 合并；相同 identity
  和内容幂等 no-op，不同内容、mapping identity 碰撞、缺失 Controller task、Agent 引用
  不完整或局点不匹配均使整个 tasks merge 回滚。

Rollout 顺序为 `LEGACY_DUAL_FULL -> TASK_RESULTS_DUAL_WRITE -> TASK_RESULTS_VERIFIED ->
RESULT_REF_AUTHORITY`。当前只开放前两态之间的显式启用和停止未来 dual-write；停止不会删除
既有 authority row，read-through 始终开启。`TASK_RESULTS_VERIFIED` 需要独立验证证据，
`RESULT_REF_AUTHORITY` 需要单独获批的生产迁移阶段，两者都没有生产 apply 入口。隔离副本的
development-root-only 演练不改变这个边界；空间节约只能引用真实演练测量，不能外推为生产已释放。

`vehicle_mr_online_refresh_all`、`device_list_page`、`ac_fit_ap_optical_refresh`、
`ac_fit_ap_resources_refresh` 和 `trackside_ap_optical_update` 是重点大型 result producer。
B3 不改变它们的领域结果契约；后续若收敛为 revision/计数/reload hint，必须作为独立领域改动
审计。Online MR 的 session identity、stop reason、integrity、package 和 warnings 必须保留，
并与 Session lifecycle 同步，不能按普通一次性 UI task 处理。

## Retention 设计

当前代码事实必须与未来候选区分：

- `task_snapshots.expires_at` 只驱动任务历史软隐藏：成功/取消默认 7 天，失败/业务告警默认
  30 天；快照、事件、结果和 Artifact 不因此物理删除。
- `SiteRetentionService` 仍是唯一 owner。B4 已将 task history 候选原位升级为 typed preview：
  candidate 为 `safe=false`、`recommended_action=preview`、
  `status=USER_POLICY_REQUIRED` 和 `apply_enabled=false`，task apply 会拒绝；没有执行 DELETE
  或 VACUUM。未来批准的分级策略仍必须原位升级，不能新增并列 retention Service。

未来细分策略建议如下，所有期限均为 `USER_POLICY_REQUIRED`：

| Data | Candidate | Safety rule |
| --- | --- | --- |
| PENDING/STARTING/RUNNING/STOPPING snapshot/event | 永不自动 retention | 活动任务、协作取消和资源键必须保留 |
| sampled progress event | 14 天 | 仅终态任务；保留首条、heartbeat、阶段变化和终态前最后一条 |
| 普通 state/log/notification | 30 天 | 错误、取消、协议损坏、人工审计事件另按 terminal metadata |
| terminal enriched event/result payload | 90 天候选 | 到期后只允许收敛为最小审计记录，不直接删除终态身份 |
| terminal minimal audit record | 推荐永久保留 | 仅含 type/time/task/final status/result id/hash/summary；是否允许有限期限仍为 `USER_POLICY_REQUIRED` |
| terminal snapshot summary | 90 天候选 | 有 mapping、Artifact、Site Package 或领域关系时不得删除 |
| 完整 terminal result | 只保留一个权威副本 | Online MR 等领域按 session/package 生命周期，不使用统一天数 |
| Artifact metadata/file | 由领域 Artifact policy 管理 | task event retention 不删除 Artifact 文件 |

这里的最终建议是：富 terminal payload 可按用户批准的候选期限收敛，最小终态审计记录默认永久
保留。若产品要求最小审计记录也有限期删除，必须由用户明确批准，不能沿用现有统一 90 天事件
DELETE 作为默认答案。

Ground Unattended 的 run/session/archive 事实源不在 terminal event payload，但关联 Task 的活动状态、
资源占用和最小终态审计仍需保留。Online MR result 与 `online_mr_task_sessions`、session metadata、
完整包和显式会话删除绑定；存在任一关系时不得由通用 Task retention 删除。

## Retention 索引提案

当前 `task_events` 只有 `(task_id, sequence DESC)`，不适合按时间/类型分批 retention；
`task_snapshots` 的 `(status, updated_time DESC)` 也不等价于物理清理索引。

未来 schema migration 建议先增加可验证的 `event_time_epoch_ms INTEGER NULL`，只为合法时间写值，
非法时间和回退证据保持 `NULL` 并禁止自动删除。候选索引为：

```sql
CREATE INDEX idx_task_events_retention
ON task_events(event_type, event_time_epoch_ms, sequence);

CREATE INDEX idx_task_snapshots_retention
ON task_snapshots(status, expires_at, task_id);
```

如果最终政策只有统一 90 天 cutoff，应通过真实副本的 `EXPLAIN QUERY PLAN` 和批量 DELETE benchmark
比较 `(event_time_epoch_ms, sequence)`，不要同时保留两个重叠索引。迁移前还必须定义 batch size、
WAL 上限、取消点、失败恢复和 compact 独立阶段。B2 未创建这些列或索引。

## Maintenance Exclusive Class

统一重 IO 维护类为：

```text
MAINTENANCE_EXCLUSIVE_CLASS = site-database-maintenance
lock key = site-database-maintenance:<site_id>
owner = src/netconsole/services/database_upgrade/coordinator.py::database_maintenance_lock
```

History migration/cutover 和 Site Retention scan/apply 已复用这个跨进程锁；future task
retention 和 large compact 必须继续复用。
不得新增第二个 scheduler 或 lock 实现。现有 `storage_lock` 可继续保护领域操作，但统一顺序应为
`database_maintenance_lock` 在外、领域 `storage_lock` 在内，避免反向获取造成死锁。锁内还需复核
活动任务、候选 token、数据库 identity、WAL 状态和取消边界。

`SiteRetentionService` 的 typed task preview 已原位接管候选生成，任务历史 apply 被禁用。
期限获批后必须在同一 owner 内实现分批执行，不能恢复旧统一 purge 再增加第二个 Task
retention Service。

## 实施前 Gate

任何物理 retention 或 terminal result cutover 必须满足：

1. 用户确认保留期限，状态从 `USER_POLICY_REQUIRED` 转为明确产品政策。
2. 所有矩阵消费者改为 result reference/read-through，并完成旧库与 Site Package 双向兼容。
3. 在隔离副本验证并发写、崩溃恢复、WAL、分批清理、失败回滚和磁盘空间上限。
4. 在最终集成 commit 运行 L3/L4 Consumer 与 FULL Gate；真实 Electron、设备、长时 Ground/
   Online MR 和 HDD compact 仍单独验收。
