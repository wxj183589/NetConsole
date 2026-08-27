# Task Center 数据所有权矩阵

本矩阵是 `tasks.db` 轻量化、清理和候选库重建的边界。它不授权
Production 操作，也不把所有历史任务宣称已迁移到 `TaskHistoryStore`。
`UNKNOWN` 一律 `PROTECT`。

| 数据 | CURRENT AUTHORITY | HISTORY AUTHORITY | READ OWNER | WRITE OWNER | RETENTION OWNER | DELETE AUTHORITY | COMPACTION BEHAVIOR | MIGRATION STATE |
|---|---|---|---|---|---|---|---|---|
| `tasks` / `task_snapshots` | `tasks.db.task_snapshots` 当前状态、恢复指针 | 现有 Task/History 兼容记录 | `TaskRepository`、Task Center Query | `TaskRepository` / TaskApplicationService | SiteRetentionService；普通软清理仍可逆 | 仅显式 cleanup 候选的 Repository 事务 | 不压缩业务状态；仅随明确批准的 task-owned cleanup 删除 | schema v5 兼容升级完成；未迁移为全量 HistoryStore |
| `task_events` | `tasks.db.task_events` 执行与审计事件 | 已封存的历史事件由既有 HistoryStore 契约负责 | `TaskRepository`、Task Center Detail | `TaskRepository` | TaskHistoryStore / SiteRetentionService | 不按旧、Completed、dismiss 或 payload 大小推断；仅随安全 Task cleanup 删除 | 不抽样、不重写事件；compact 只回收 SQLite 空页 | 终态引用已收口；事件归档/分片未开始 |
| terminal result metadata `task_results` | 不可变 `result_id/task_id/event/hash/size` 身份元数据 | legacy full-only/dual rows 与既有 HistoryStore 兼容证据 | `TaskRepository`、Query Service、Site Sync | `TaskRepository`；维护脚本仅显式离线运行 | TaskRepository / SiteRetentionService | 仅随已 preview 且无引用的 Task-owned cleanup 删除 | 新 rows 不写完整 body；旧 `canonical_json` 可保留并由 Blob-first 读取校验 | DEV ref-authority 已接入；Production migration 未运行 |
| terminal result body `task_result_blobs` | `content_sha256` 内容寻址的 zlib Blob | 旧 `canonical_json` / HistoryStore 作为兼容历史来源 | `TaskResultBlobRepository`、TaskRepository | TaskRepository；migration tool 只写隔离候选 | TaskRepository orphan GC；不删仍被 ready result 引用的 Blob | 只回收无 ready 引用的 Blob；不删除业务结果 | 按内容共享压缩 Blob，hash/长度/UTF-8/JSON 失败闭合 | DEV migration/compact 工具已验证；Production 未启用 |
| `task_result_storage_rollout` / audit | `tasks.db` 当前 rollout 与不可变审计 | rollout audit rows | TaskResultRolloutService / diagnostics | TaskResultRolloutService / schema initialization | 不自动保留清理 | 本轮不删除 | 不 compact、不重写审计 | schema v5 初始化兼容完成 |
| `online_mr_task_sessions` | Online MR 当前 Task/Session 映射 | Online MR session/raw/parsed authority 按领域保存 | Online MR services、Task Center | Online MR session repository | Online MR lifecycle | 通用 Task cleanup 不得删除 | compact 不触碰 mapping | 仅做引用校验，未迁移/删除 |
| Ground current mapping | Ground `index.sqlite` 的运行、深采和操作关联 | Ground active/raw/READY archive 契约 | Ground repository/services；cleanup 只读引用 | Ground repositories/services | Ground archive/raw lifecycle | Ground owner；Task cleanup 永不删除 | compact 不触碰 Ground DB、NDJSON、ZIP | 仅完成 task reference parity；无迁移 |
| Artifact metadata/reference | Task result/summary/path 与受管 manifest 的稳定引用 | Artifact manifest/output authority | ArtifactReconciliationService、Task Center | Artifact owner + export/application services | Artifact lifecycle owner | Artifact owner；Task cleanup 只保护、不删除 | 不把文件内容写回 tasks.db；不 compact 外部文件 | 兼容读取与引用保护完成 |
| task logs / raw evidence | 各领域受管日志、raw 文件和会话目录 | 对应领域历史/raw authority | 领域 Repository/查询服务 | 对应采集/Worker owner | 对应 raw lifecycle | 对应领域 owner；未知路径 `PROTECT` | 不因 Task cleanup 或 VACUUM 删除 | 不纳入本轮迁移 |
| temporary worker files | `.local`/受管 staging 中的任务运行临时物 | 无历史 authority | Worker/runtime owner | Worker/runtime | Job/Export staging lifecycle | 仅 exact owner、无活动锁且有恢复规则时清理 | tasks.db compact 不触碰；崩溃恢复按 owner journal | 本轮不改变 |
| external Artifact files | 受管输出、报告、ZIP、下载文件本体 | Artifact manifest + 文件完整性锚点 | Artifact service / 用户动作 | Export/File/Artifact owner | Artifact lifecycle | Artifact owner 的显式文件操作；Task cleanup 禁止删除 | 不进入 SQLite VACUUM/Blob GC | 本轮仅做引用兼容与 parity |
| unknown ownership / unregistered reference | 无法证明 owner、消费者或恢复边界 | 无可证明历史 authority | 仅诊断/审计 | 禁止新增 writer | `UNKNOWN_PROTECT` | 禁止自动删除、迁移、compact 或省略 | 不触碰 | 未解决，保持保护 |

## 结论

- `TaskCleanupService` 负责 preview、引用判断和 fail-closed 决策；
  `TaskRepository` 负责 `task_events -> task_results -> task_snapshots` 的
  单事务物理变更、tombstone 和孤立 Blob 回收。
- `PENDING / STARTING / RUNNING / STOPPING`、current/restart state、Online MR
  映射、Ground 引用、Artifact/result 引用、未知或不可验证 metadata 都不
  进入物理删除候选。soft-dismiss 仍然是可逆 UI 状态。
- 列表不 materialize 完整结果；详情、结果打开、replay 和 Site Package
  merge 使用 Blob-first authority。旧 full-only/dual rows 保持兼容，新
  result-reference rows 不重新写回完整 `canonical_json`。
- DEV candidate migration/compact 只在隔离库执行并保留 parity/quick-check
  证据；本轮没有 Production migration、Production compact 或真实数据写入。
