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

代码能力已实现，但当前 production rollback owner 仍为
`PENDING_PRODUCTION_BACKUP`，没有 VERIFIED production rollback set，也没有生产
cutover 授权。不得把 capability 存在、隔离 rehearsal 通过或 manifest 生成解释为
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

第一阶段只允许：

- Site ID：`legacy-dfd356e96ea0`
- SiteRegistry display name：`宁波地铁12号线`
- 数据库：`devices.db`、`tasks.db`

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

maintenance CLI 当前只生成 `execution_status = NOT_EXECUTABLE` 的 preparation
manifest，并默认登记 rollback owner、production backup、writer quiescence 和 cutover
authorization 阻塞项。即使 source/candidate identity 与全部自动化测试一致，preflight
也会拒绝该 manifest；只有在真实生产前置条件均已建立后，由受控授权流程生成无阻塞项
的 `EXECUTABLE` manifest，才可能进入后续 gate。

manifest 转为 `EXECUTABLE` 时，`generated_git_head` 必须等于运行时重新解析的
`CURRENT_IMPLEMENTATION_HEAD`。旧 rehearsal HEAD 只能出现在 authorization evidence
的 `rehearsal_evidence_head`，不能继续生成可执行 manifest。

manifest 和命令输出文件均为 create-only；既有路径或 `--output` 与 `--manifest`
相同一律在任何操作前拒绝。production preflight 在确认不存在非空 WAL 后使用
`mode=ro&immutable=1`，不得因读取 source、candidate 或 rollback backup 创建或更新
WAL/SHM sidecar。

## Rollback owner

`config/storage_registry.yaml` 的 `production_rollback_owners` 是正式 owner 注册表。
owner 必须包含 backup set、Site、operation、database、source identity/SHA/revision、
创建与验证时间、quick check、schema fingerprint、backup SHA/size/canonical relative
path、observation 和 retire state。

只有同时满足以下状态才是可用 rollback authority：

- `quick_check = ok`
- `observation_state = VERIFIED`
- `rollback_required = true`
- `retire_state = PROTECT`
- backup/source/revision/verified time 均非空且格式有效
- backup 必须已存在于
  `files/backups/production-maintenance/<backup_set_id>/database.sqlite`，并匹配登记的
  SHA-256、size 与 schema fingerprint

当前登记项是具体 Site/数据库的待建立槽位，不是 VERIFIED backup。生产切换前必须
用 SQLite Online Backup API 创建并验证 exact backup set，再更新 owner；不能把
历史 `files/backups/**` 文件名推断成 rollback authority。

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

开发/测试使用唯一 `D:\study\test-data\NetConsole\<run-id>`，不得用真实生产根验证
DELETE、DROP、VACUUM、source retirement、database replacement 或 backup retirement。
