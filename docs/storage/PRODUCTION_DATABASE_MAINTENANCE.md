# Production Database Maintenance

NetConsole 的生产数据库维护能力是独立安全边界，不复用或放宽
`DevelopmentDatabaseCompactService` 的 `D:\study` 限制。实现位于
`src/netconsole/services/production_database_maintenance.py`，命令入口位于
`scripts/maintenance/production_database_maintenance.py`。

## 当前授权状态

- `PRODUCTION_STORAGE_CUTOVER_READY = FALSE`
- `PRODUCTION_MUTATION = NONE`
- `PRODUCTION_CUTOVER_AUTHORIZED = FALSE`
- `FAIL_CLOSED = TRUE`

当前 `ProductionMaintenanceCapability` 已登记一个
`TASK_OPERATIONAL_GC` resource-set owner，覆盖 9 个 Production `tasks.db`，并已
完成 SQLite Online Backup、quick/FK 校验和离线 rehearsal；生产 cutover 仍未授权。
不得把 rollback capability VERIFIED、隔离 rehearsal 通过或 manifest 生成解释为
已执行生产迁移。

当前 implementation 与历史 rehearsal evidence 是两个不同身份：

- `CURRENT_IMPLEMENTATION_HEAD` 从实际 Git repository 或 packaged build metadata
  读取，不能由 caller 自报；
- `REHEARSAL_EVIDENCE_HEAD` 只记录上游隔离 rehearsal 的 provenance，不能冒充当前
  implementation validation。

CLI 仍要求 `--git-head`，但该值只作为 caller claim。它与实际 repository/build HEAD
不一致时立即返回 `CURRENT_HEAD_MISMATCH`，且不会生成 manifest 或进入 preflight。
`--rehearsal-evidence-head` 独立记录历史 evidence HEAD。底层 manifest build/publish
helper 同样必须接收 runtime-derived evidence binding，不再接受 caller 提供的生成 HEAD。
source worktree 或 packaged build metadata 还必须明确 `build_dirty=false`；dirty 或无法
确认 clean 的实现没有可用的 `CURRENT_IMPLEMENTATION_HEAD`，立即失败关闭。

## 固定作用域

Production capability 保留旧的单 Site/数据库 scalar owner 兼容路径，同时支持正式
resource-set scope。`TASK_OPERATIONAL_GC` 的本次固定 scope 是 SiteRegistry 中以下
9 个 Site ID 的 `tasks.db`：

`legacy-784dcd2b63e3`、`legacy-dfd356e96ea0`、`legacy-422faf1196ef`、
`legacy-0d1a8935839e`、`hzl10`、`legacy-6fef62d71cfd`、
`legacy-59b885329893`、`hzdt-09`、`sxl1`。

resource-set owner 使用 `maintenance_id`、`maintenance_type`、`scope_kind` 和
`resources[]` 表达范围；每个 resource 绑定 Site、`database_role=tasks.db`、
DataRoot-relative source path、规范化 path、source identity/SHA/revision、size、
schema、quick/FK 和 canonical backup identity。只有 9/9 exact coverage 才能进入
`VERIFIED`。

路径必须由当前 DataRoot 的 SiteRegistry 精确解析；不能传任意局点路径、目录或
SQLite 文件。符号链接、越界路径、未登记 Site、显示名不一致和额外数据库一律
失败关闭。

候选迁移与完整性审计只遍历 SiteRegistry 登记的 `relative_path`。`sites/` 下未登记
的目录或数据库不属于 cutover 作用域，必须保留并单独分类；不得因为未登记而自动
删除、移动或纳入全局迁移。候选路径解析还会拒绝符号链接、越界路径、重复
`site_id` 和缺失的登记目录。

Task Blob rollout 的 `RESULT_REF_AUTHORITY` 只在物理 schema、结果引用、Blob、父任务
关系和内容哈希全部审计通过时才可作为候选证据。迁移会在批次失败时回滚该批次，且
不会通过脚本直接翻转 rollout 状态；生产 `tasks.db` 仍须在受控切换门内替换。

旧 `component_resume` journal 是恢复证据，不是默认清理目标。已终态的 journal 保留
原文件并记录大小、SHA-256、错误和候选/回滚制品；仍有活动制品或越界制品时必须
fail-closed。runtime smoke 只读盘点，不自动归档、隔离、移动或删除生产 journal、
staging、数据库和 WAL；后续 quarantine 必须是独立授权操作。

## Manifest 契约

destructive manifest 必须由当前隔离 snapshot 生成并标记 immutable，至少绑定：

- `site_id`
- `database_identity`
- `source_size`
- `source_sha256`
- `schema_fingerprint`
- `source_revision`
- `row_identity`
- `expected_count`
- `candidate_identity`（candidate 的 size、SHA-256、schema fingerprint 与逐表行数）
- `plan_digest`
- `generated_git_head`
- `manifest_digest`
- `execution_status` 与 `blocking_prerequisites`

preflight 与进入维护锁后的第二次 source identity 校验都必须完全匹配。旧 source、
SHA、revision、row identity、plan digest 或 Git HEAD 任一不同均为
`STALE_SOURCE` / `STALE_PLAN`，不可执行。

maintenance CLI 当前仍只生成 `execution_status = NOT_EXECUTABLE` 的 replacement
preparation manifest；rollback scope 使用独立的 `scope`、`register-scope`、
`backup-scope`、`manifest-scope` 和 `verify-scope` 受控步骤建立。即使 rollback
owner VERIFIED，production cutover authorization 仍是独立阻断项。

manifest 转为 `EXECUTABLE` 时，`generated_git_head` 必须等于运行时重新解析的
`CURRENT_IMPLEMENTATION_HEAD`。旧 rehearsal HEAD 只能出现在 authorization evidence
的 `rehearsal_evidence_head`，不能继续生成可执行 manifest。

manifest 和命令输出文件均为 create-only；既有路径或 `--output` 与 `--manifest`
相同一律在任何操作前拒绝。production preflight 在确认不存在非空 WAL 后使用
`mode=ro&immutable=1`，不得因读取 source、candidate 或 rollback backup 创建或更新
WAL/SHM sidecar。

## Task Cleanup Schema Contract

`TASK_OPERATIONAL_GC` 还必须通过独立的
`TASK_CLEANUP_SCHEMA_CONTRACT`。该契约使用 `sqlite_schema`、`PRAGMA table_info`、
`PRAGMA index_list/index_info` 和 schema metadata 只读核验，不把 `user_version` 作为
唯一事实源。

预览要求 `task_snapshots`、`task_events`、`task_results` 的清理所需字段，以及
`idx_task_snapshots_visible_updated`、`idx_task_events_task_sequence`、
`idx_task_results_task_created`。Apply 在此基础上硬性要求
`task_retention_tombstones(task_id PRIMARY KEY, retired_at, reason)`。缺失、partial
或索引不匹配时，候选可以被观察为 `SAFE_BUT_SCHEMA_BLOCKED`，但不得进入可执行
manifest；resource-set 的 Production preflight 必须报告 `9/9
TASK_SCHEMA_COMPATIBILITY PASS` 才能继续。

schema upgrade 与 Operational GC 是两个阶段。显式 upgrade 使用现有 SQLite/Task
repository 边界，在 `BEGIN IMMEDIATE` 中完成 tombstone 表/字段/索引修复，失败整体
回滚、重复执行幂等；GC 不得在删除第 N 个任务时隐式创建表。GC 事务必须先验证
apply contract，然后在同一事务中删除 task-owned rows 并写入 tombstone；任一删除或
tombstone 写入失败都回滚全部 task/event/snapshot/result 变化。

`--all-sites --apply` 必须先完成全部目标库的只读 schema preflight，再允许任何一个库
进入 apply；任一库 blocked 时全批次不执行。

当前 contract 修复的完整证据见
`docs/development/LEGACY_TASK_TOMBSTONE_CONTRACT_ACCEPTANCE_20260910.md`。

## Rollback owner

`config/storage_registry.yaml` 的 `production_rollback_owners` 是正式 owner 注册表。
scalar owner 必须包含 backup set、Site、operation、database、source identity/SHA/revision、
创建与验证时间、quick check、schema fingerprint、backup SHA/size/canonical relative
path、observation 和 retire state；resource-set owner 在同一 registry entry 中增加
`maintenance_id`、`maintenance_type`、`scope_kind` 和 `resources[]`，不建立第二套
registry。

只有同时满足以下状态才是可用 rollback authority：

- `quick_check = ok`
- `observation_state = VERIFIED`
- `rollback_required = true`
- `retire_state = PROTECT`
- backup/source/revision/verified time 均非空且格式有效
- backup 必须已存在于
  `files/backups/production-maintenance/<backup_set_id>/database.sqlite`，并匹配登记的
  SHA-256、size 与 schema fingerprint

owner 生命周期固定为：intent → requested scope registration → consistent backup
creation → resource attachment/verification → owner `VERIFIED`。本次 9 库 owner
已完成该流程；旧宁波 12 号线两个 scalar `PENDING_PRODUCTION_BACKUP` 条目仍保留，
没有被改写或吸收。不能把历史 `files/backups/**` 文件名推断成 rollback authority。

### Rollback owner revision lifecycle

Production `TASK_OPERATIONAL_GC` 使用 Strategy B：每个 immutable rollback revision
保留一个 owner entry。新 revision 注册时，正式把同类、未被 supersede 的旧
resource-set owner 写入 `superseded_by=<new maintenance_id>`；旧 owner 的
`observation_state=VERIFIED`、backup manifest、SHA-256、size 和 `retire_state=PROTECT`
保持不变，因此仍是可查询的历史 recovery evidence，但不再是当前 rollback authority。

`PENDING_PRODUCTION_BACKUP` 的安全计数只统计当前、未 supersede、9/9 tasks resource-set
owner 的 actionable pending 状态。旧 scalar cutover 槽位继续按兼容/保护语义保留，不能
被冒充为当前 tasks GC owner。任何时刻当前 `TASK_OPERATIONAL_GC` 最多只能有一个
actionable pending owner；Gate 不通过时禁止 backup、preview 或 mutation。

`config/storage_registry.yaml` 是静态 owner/evidence registry，不是 append-only 的
运行实例日志。生命周期 transition 由 `register_rollback_scope` 与
`reconcile_rollback_owner_lifecycle` 完成；registry restart 后必须仍能区分 current
owner 与 historical superseded evidence。历史 owner 不得因 Gate 收口而删除、改写为
VERIFIED 或复用为新 source revision。

## 执行门

mutation 入口必须同时具备：

1. 显式 `mode=production`。
2. 精确授权令牌。
3. Site 与 database allowlist 通过。
4. SiteRegistry identity 通过。
5. maintenance lock 已获取。
6. runtime/writer quiescence 已确认。
7. VERIFIED rollback owner 已登记。
8. immutable manifest 与当前 Git HEAD 匹配。
9. source identity 二次校验通过。
10. operation journal 可持久化。
11. 所有 production gate 为 PASS。
12. replacement 后 restart 与 functional gate 为 PASS。

静态 writer quiescence evidence 必须明确记录 runtime writer stopped、database owner
inactive、WAL zero 与 SQLite sidecar quiescent。进入 maintenance lock 后、atomic replace
之前还会获取 Backend 排他锁，并重新验证：

- repository/build HEAD 未变化；
- runtime writer 已停止且数据库 owner 不活动；
- WAL 为零且 sidecar 可安全收敛；
- source SHA-256、size、schema fingerprint 与 manifest/preflight 完全一致；
- replacement candidate identity 未变化。

任一 execution-time recheck 失败都记录 journal 并在 switch 前失败关闭。

production authorization evidence 必须同时记录：

- `current_implementation_head`
- `rehearsal_evidence_head`
- `source_snapshot_identity`
- `manifest_generated_head`
- `storage_registry_sha256`
- `production_maintenance_script_sha256`

最终 gate 不接受 `key=true` 这类 caller 布尔值。每个 gate 必须提供
`production-current-head-gate-v1` evidence，状态为 `PASS`，并绑定同一
`current_implementation_head`。最终授权至少覆盖 TARGETED、FAST、CONSUMER、FULL、
Renderer、Electron、Architecture、No-Reinflation 与 functional compatibility；旧
rehearsal evidence 只保留为 provenance。本阶段不重复运行完整 gate，等当前生产快照、
exact manifest、VERIFIED rollback owner 与 maintenance gate 全部准备完成后，再针对最终
integrated HEAD 统一重跑。

restart 或 functional gate 失败时必须使用已验证 rollback authority 恢复，并保留
失败数据库和 journal；自动 rollback 在恢复替换前也必须重新取得 Backend 排他锁、
复核当前 HEAD 和 rollback owner。无法证明 writer/owner 已静默时拒绝恢复替换并保留
失败现场，不得以并发改写或清理失败现场代替恢复。

## Backup 生命周期

生产 cutover 前不得退役 `files/backups/**`。顺序固定为：cutover、restart、功能验证、
observation、分类、精确退役。分类仅允许
`ACTIVE_ROLLBACK_REQUIRED`、`OBSERVATION_REQUIRED`、`SUPERSEDED`、
`EXACT_DUPLICATE`、`EXPIRED_ROLLBACK`、`UNKNOWN`；`UNKNOWN = PROTECT`。

开发/测试使用唯一 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`，不得用真实生产根验证
DELETE、DROP、VACUUM、source retirement、database replacement 或 backup retirement。
