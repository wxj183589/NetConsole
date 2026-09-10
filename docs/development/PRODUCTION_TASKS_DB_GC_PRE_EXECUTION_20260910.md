# Production tasks.db GC 前置准备记录

日期：2026-09-10  
Agent：codex-A  
状态：`BLOCKED`（只读发现、Preview 和正式 owner verifier 完成；未创建生产 rollback copy，未执行 GC）

## 范围与安全结论

本轮只做 rollback 前置准备和待授权计划，禁止：GC、DELETE、VACUUM、VACUUM INTO 正式库、Replace、schema 变更、Task 代码/保护规则修改和 registry 状态伪造。

当前代码树为 clean `main@00426783a2c7fda893122b569b78c4d4a3acb928`。Production writer 精确扫描为 0，NetConsole scheduled task 为 0；9 个 `tasks.db` 的 WAL 均为 0 bytes，未手工删除 WAL/SHM/journal。

## Production DB Set

- DataRoot：`D:\NetConsoleData`
- DB_COUNT：`9`
- PRODUCTION_BYTES：`402067456`
- freelist：`655360` bytes
- 9/9 `quick_check=ok`
- 9/9 `foreign_key_check=ok`
- 所有发现的 tasks.db 均由当前 `site_registry.json` 登记
- DB set SHA-256：`6393186787f22affc6c0d461d2fb1a438289012039017cf19a6ed4dedc37d72a`

## 最新 Preview

本轮重新执行 dry-run，未带 `--apply`：

- Preview SHA-256：`d50e7a5b97a3b72d5d654268a57a49af8c27983d05ed5b5fc49dacd6a5224779`
- PREVIOUS_SAFE：`6402`
- CURRENT_SAFE：`6402`
- DELTA：`0`
- candidate：`7207`
- safe：`6402`
- protected：`805`
- unknown：`0`
- safe logical payload estimate：`141864358` bytes
- safe-set SHA-256：`bafe15f9ed6be5a4cb1afff15158b2c5bcea033bbdecec3bb926f4bde9d80bcd`

本轮没有扩大 safe 集合，没有将 protected/unknown 改为 safe。

## Rollback Set 与正式 Owner Verifier

已调用项目正式 `ProductionMaintenanceCapability.load_rollback_owners()` 及 `ProductionRollbackOwner.verified()` 校验 registry，没有手工编辑 registry，也没有硬改 `VERIFIED`：

- 当前正式 Production site allowlist：只有 `legacy-dfd356e96ea0`（宁波地铁12号线）
- registry owner：只有该局点的 `devices.db` / `tasks.db` 两个 pending 槽位
- 两个 owner：`observation_state=PENDING_PRODUCTION_BACKUP`、`quick_check=pending`、backup SHA/size 为空
- VERIFIED task owner 覆盖：`0/9`
- ROLLBACK_SCOPE_COMPLETE：`NO`
- ROLLBACK_OWNER_STATUS：`BLOCKED_NOT_REGISTERED_FOR_NINE_DATABASE_SCOPE`

项目已有的 `DatabaseBackupStore` 属于 `site.backups.database_upgrade`，其 owner/恢复语义是数据库升级，不是本轮 `ProductionMaintenanceCapability` 的 Production rollback owner。将其冒充本轮 owner 会绕过正式 contract，因此没有创建不受 formal owner 管理的生产副本。

## 生成的计划

- `PRODUCTION_TASKS_DB_SET.json`：9 库实时发现、大小、mtime、SHA、page/freelist、sidecar、quick/FK、schema/table counts
- `TASK_RETIREMENT_PREVIEW_AUTHORIZATION.json`：本轮最新只读 Preview
- `PRODUCTION_TASKS_DB_ROLLBACK_MANIFEST.json`：`rollback_db_count=0`，明确记录未创建原因和 0/9 formal owner coverage
- `PRODUCTION_TASKS_DB_GC_EXECUTION_PLAN.json`：`execution_status=NOT_EXECUTABLE`，plan digest=`d530789b8eb7d6398fc7f5690d2bd3028c77e1e98dfcd7baca9ac98cf8126152`

证据目录：

`D:\study\NetConsole-Workspace\diagnostic\production-task-gc-prep-20260910-160300`

计划中的 Apply、GC、Compact、Replace 和 rollback trigger 均为待授权动作，没有执行命令。

## 最终状态

```text
PRODUCTION_DB_COUNT = 9
PRODUCTION_BYTES = 402067456
WRITERS_STOPPED = YES
ROLLBACK_PATH = NOT_CREATED
ROLLBACK_DB_COUNT = 0
ROLLBACK_SCOPE_COMPLETE = NO
ROLLBACK_QUICK_CHECK = NOT_RUN
ROLLBACK_FOREIGN_KEY_CHECK = NOT_RUN
ROLLBACK_REHEARSAL = NOT_RUN
ROLLBACK_OWNER = ProductionMaintenanceCapability
ROLLBACK_OWNER_STATUS = BLOCKED_NOT_REGISTERED_FOR_NINE_DATABASE_SCOPE
CURRENT_CANDIDATE = 7207
CURRENT_SAFE = 6402
CURRENT_PROTECTED = 805
CURRENT_UNKNOWN = 0
ESTIMATED_LOGICAL_RECLAIM = 141864358 bytes
PRODUCTION_GC_EXECUTION_PLAN = NOT_EXECUTABLE
PRODUCTION_MUTATION = NONE
PRODUCTION_GC = NOT_RUN
PRODUCTION_VACUUM = NOT_RUN
PRODUCTION_REPLACE = NOT_RUN
PRODUCTION_CUTOVER_AUTHORIZED = FALSE
ROLLBACK_READY = NO
PRODUCTION_GC_EXECUTION_READY_FOR_AUTHORIZATION = NO
```

## 解除条件

需要由 Production owner 提供或建立覆盖全部 9 个 tasks.db 的正式 `production-rollback-owner-v1` workflow：每库 exact source identity/SHA/revision、SQLite Online Backup、quick/FK/schema parity、backup SHA/size、owner、operation、observation 和 registry verifier 结果。完成后必须重新发现 DB set、重新 Preview、重新绑定 current HEAD 和生成 execution plan；不能直接复用本轮 Preview 或 plan。
